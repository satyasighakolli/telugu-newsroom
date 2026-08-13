#!/usr/bin/env python3
"""MediaOps speech adapter for Deepgram Nova-3 Telugu + batch diarization."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def average_confidence(words: list[dict]) -> Optional[float]:
    values = [float(word["confidence"]) for word in words if word.get("confidence") is not None]
    return sum(values) / len(values) if values else None


def main() -> None:
    payload = json.load(sys.stdin)
    if payload.get("task") != "transcribe_and_diarize":
        fail("Unsupported task")
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        fail("DEEPGRAM_API_KEY is required")
    audio_path = Path(str(payload["audio_path"]))
    if not audio_path.is_file():
        fail(f"Audio file not found: {audio_path}")

    language = str(payload.get("language", "te"))
    params = {
        "model": os.environ.get("DEEPGRAM_MODEL", "nova-3"),
        "language": "te" if language.startswith("te") else language,
        "diarize_model": os.environ.get("DEEPGRAM_DIARIZE_MODEL", "latest"),
        "utterances": "true",
        "punctuate": "true",
        "smart_format": "true",
    }
    endpoint = os.environ.get("DEEPGRAM_ENDPOINT", "https://api.deepgram.com/v1/listen")
    request = Request(
        f"{endpoint}?{urlencode(params)}",
        data=audio_path.read_bytes(),
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "audio/wav",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=1800) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        fail(f"Deepgram returned HTTP {error.code}: {detail[-2000:]}")

    result = raw.get("results", {})
    utterances = result.get("utterances") or []
    if not utterances:
        fail("Deepgram response did not include utterances")

    segments = []
    for index, utterance in enumerate(utterances, start=1):
        words = utterance.get("words") or []
        speaker = utterance.get("speaker")
        segments.append(
            {
                "id": f"seg-{index:05d}",
                "start": float(utterance["start"]),
                "end": float(utterance["end"]),
                "speaker": f"SPEAKER_{int(speaker):02d}" if speaker is not None else None,
                "confidence": utterance.get("confidence", average_confidence(words)),
                "overlap_speakers": [],
                "text": str(utterance.get("transcript", "")).strip(),
                "words": [
                    {
                        "text": str(word.get("punctuated_word") or word.get("word") or ""),
                        "start": float(word["start"]),
                        "end": float(word["end"]),
                        "confidence": word.get("confidence"),
                        "speaker": f"SPEAKER_{int(word['speaker']):02d}" if word.get("speaker") is not None else None,
                        "timing_source": "model",
                    }
                    for word in words
                ],
            }
        )

    metadata = raw.get("metadata", {})
    model_info = metadata.get("model_info", {})
    model_names = [str(item.get("name")) for item in model_info.values() if isinstance(item, dict) and item.get("name")]
    output = {
        "language": language,
        "duration": float(metadata.get("duration") or max(item["end"] for item in segments)),
        "provider": "deepgram",
        "model": model_names[0] if model_names else params["model"],
        "timing_quality": "word",
        "segments": segments,
        "raw_text": " ".join(item["text"] for item in segments),
    }
    json.dump(output, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
