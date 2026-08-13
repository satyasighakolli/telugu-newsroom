from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence

from .models import CandidateClip, TranscriptDocument
from .scoring import EditorialSignals
from .transcript import transcript_from_dict


class ProviderError(RuntimeError):
    """Raised when an external model adapter violates the pipeline contract."""


def run_json_command(
    command: Sequence[str],
    payload: Mapping[str, Any],
    timeout_seconds: int = 1800,
) -> Dict[str, Any]:
    if not command:
        raise ProviderError("Provider command cannot be empty")
    process = subprocess.run(
        list(command),
        input=json.dumps(payload, ensure_ascii=False),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if process.returncode != 0:
        raise ProviderError(
            f"Provider exited with code {process.returncode}: {process.stderr[-3000:]}"
        )
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise ProviderError("Provider stdout was not valid JSON") from error
    if not isinstance(result, dict):
        raise ProviderError("Provider response must be a JSON object")
    return result


@dataclass
class CommandSpeechProvider:
    """Adapter for any ASR + diarization service exposed as a local command.

    The command receives JSON on stdin and must return the transcript contract on
    stdout. This keeps cloud credentials and provider SDKs outside the core.
    """

    command: Sequence[str]
    name: str = "command-speech"
    model: str = "external"

    @classmethod
    def from_string(cls, command: str) -> "CommandSpeechProvider":
        return cls(command=shlex.split(command))

    def transcribe(self, audio_path: Path, language: str = "te") -> TranscriptDocument:
        response = run_json_command(
            self.command,
            {
                "task": "transcribe_and_diarize",
                "audio_path": str(audio_path.resolve()),
                "language": language,
                "requirements": {
                    "word_timestamps": True,
                    "speaker_labels": True,
                    "overlap_regions": True,
                    "confidence": True,
                },
            },
        )
        response.setdefault("provider", self.name)
        response.setdefault("model", self.model)
        return transcript_from_dict(response)


@dataclass
class EditorialEnrichment:
    clip_id: str
    topic: str
    subtopic: str
    title: str
    summary: str
    clean_transcript: str = ""
    signals: Optional[EditorialSignals] = None


@dataclass
class CommandEditorialProvider:
    """Adapter for evidence-grounded topic, headline, and editorial scoring."""

    command: Sequence[str]
    name: str = "command-editorial"

    @classmethod
    def from_string(cls, command: str) -> "CommandEditorialProvider":
        return cls(command=shlex.split(command))

    def enrich(
        self,
        clips: Sequence[CandidateClip],
        transcript: TranscriptDocument,
    ) -> Dict[str, EditorialEnrichment]:
        response = run_json_command(
            self.command,
            {
                "task": "evidence_grounded_clip_enrichment",
                "language": transcript.language,
                "rules": [
                    "Use only the supplied transcript evidence.",
                    "Do not invent names, numbers, quotes, or allegations.",
                    "Return confidence signals from 0 to 1.",
                ],
                "clips": [
                    {
                        "id": clip.id,
                        "start": clip.start,
                        "end": clip.end,
                        "transcript": clip.transcript,
                        "speakers": clip.speakers,
                        "evidence_ids": clip.evidence_ids,
                    }
                    for clip in clips
                ],
            },
        )
        items = response.get("clips")
        if not isinstance(items, list):
            raise ProviderError("Editorial provider must return a 'clips' array")
        valid_ids = {clip.id for clip in clips}
        enriched: Dict[str, EditorialEnrichment] = {}
        for raw in items:
            clip_id = str(raw.get("id", ""))
            if clip_id not in valid_ids:
                continue
            signals = EditorialSignals(
                importance=_optional_unit(raw.get("importance")),
                hook=_optional_unit(raw.get("hook")),
                self_contained=_optional_unit(raw.get("self_contained")),
                reason=str(raw.get("reason", "")),
                named_entities=[str(item) for item in raw.get("named_entities", [])],
            )
            clean_text = str(raw.get("clean_transcript") or raw.get("transcript") or "").strip()
            enriched[clip_id] = EditorialEnrichment(
                clip_id=clip_id,
                topic=str(raw.get("topic", "General")),
                subtopic=str(raw.get("subtopic", "Update")),
                title=str(raw.get("title", "")).strip(),
                summary=str(raw.get("summary", "")).strip(),
                clean_transcript=clean_text,
                signals=signals,
            )
        return enriched


def _optional_unit(value: Any) -> Optional[float]:
    if value is None:
        return None
    number = float(value)
    if not 0.0 <= number <= 1.0:
        raise ProviderError("Editorial signal must be between 0 and 1")
    return number
