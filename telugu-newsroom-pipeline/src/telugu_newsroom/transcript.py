from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .jsonio import load_json
from .models import TranscriptDocument, TranscriptSegment, Word


def _estimated_words(text: str, start: float, end: float, speaker: Optional[str]) -> List[Word]:
    tokens = re.findall(r"\S+", text)
    if not tokens:
        return []
    duration = max(0.001, end - start)
    unit = duration / len(tokens)
    return [
        Word(
            text=token,
            start=start + index * unit,
            end=start + (index + 1) * unit,
            speaker=speaker,
            timing_source="estimated",
        )
        for index, token in enumerate(tokens)
    ]


def transcript_from_dict(data: Dict[str, Any]) -> TranscriptDocument:
    raw_segments = data.get("segments", [])
    segments: List[TranscriptSegment] = []
    for index, raw in enumerate(raw_segments):
        speaker = raw.get("speaker")
        words = [
            Word(
                text=str(word["text"]),
                start=float(word["start"]),
                end=float(word["end"]),
                confidence=float(word["confidence"]) if word.get("confidence") is not None else None,
                speaker=word.get("speaker", speaker),
                timing_source=word.get("timing_source", "model"),
            )
            for word in raw.get("words", [])
        ]
        if not words:
            words = _estimated_words(str(raw.get("text", "")), float(raw["start"]), float(raw["end"]), speaker)
        segments.append(
            TranscriptSegment(
                id=str(raw.get("id", f"seg-{index + 1:05d}")),
                start=float(raw["start"]),
                end=float(raw["end"]),
                text=str(raw.get("text", "")).strip(),
                speaker=speaker,
                confidence=float(raw["confidence"]) if raw.get("confidence") is not None else None,
                words=words,
                language=str(raw.get("language", data.get("language", "te"))),
                overlap_speakers=list(raw.get("overlap_speakers", [])),
            )
        )
    segments.sort(key=lambda item: (item.start, item.end))
    duration = float(data.get("duration") or max((segment.end for segment in segments), default=0.0))
    return TranscriptDocument(
        language=str(data.get("language", "te")),
        duration=duration,
        segments=segments,
        provider=str(data.get("provider", "import")),
        model=str(data.get("model", "unknown")),
        timing_quality=str(data.get("timing_quality", "word" if any(item.words for item in segments) else "segment")),
        raw_text=str(data.get("raw_text") or " ".join(item.text for item in segments)),
    )


def load_transcript(path: Path) -> TranscriptDocument:
    return transcript_from_dict(load_json(path))


def seconds_to_srt(value: float) -> str:
    milliseconds = int(round(max(0.0, value) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def write_srt(segments: Sequence[TranscriptSegment], path: Path, offset: float = 0.0) -> None:
    blocks: List[str] = []
    for index, segment in enumerate(segments, start=1):
        label = f"{segment.speaker}: " if segment.speaker else ""
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{seconds_to_srt(segment.start - offset)} --> {seconds_to_srt(segment.end - offset)}",
                    label + segment.text,
                ]
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def segments_in_range(
    segments: Iterable[TranscriptSegment],
    start: float,
    end: float,
) -> List[TranscriptSegment]:
    return [segment for segment in segments if segment.end > start and segment.start < end]
