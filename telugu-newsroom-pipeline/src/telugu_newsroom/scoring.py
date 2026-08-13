from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .models import CandidateClip, ScoreBreakdown, Shot, TranscriptSegment


DEFAULT_WEIGHTS: Dict[str, float] = {
    "editorial_importance": 0.25,
    "hook_strength": 0.18,
    "self_contained": 0.19,
    "speaker_clarity": 0.15,
    "audio_quality": 0.13,
    "visual_quality": 0.10,
}


@dataclass
class EditorialSignals:
    importance: Optional[float] = None
    hook: Optional[float] = None
    self_contained: Optional[float] = None
    reason: str = ""
    named_entities: List[str] = field(default_factory=list)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _heuristic_importance(text: str, entities: Sequence[str]) -> float:
    has_number = bool(re.search(r"\d", text))
    has_quote = any(mark in text for mark in ('"', "“", "”", "‘", "’", "'"))
    length_score = min(1.0, len(text) / 260.0)
    return _clamp(0.38 + 0.18 * has_number + 0.16 * has_quote + 0.18 * bool(entities) + 0.10 * length_score)


def _heuristic_hook(text: str) -> float:
    punctuation = sum(text.count(mark) for mark in ("!", "?", "…", ":"))
    quote = any(mark in text for mark in ('"', "“", "”", "‘", "’"))
    compact = 40 <= len(text) <= 360
    return _clamp(0.35 + 0.12 * min(2, punctuation) + 0.18 * quote + 0.15 * compact)


def _self_contained(clip: CandidateClip) -> float:
    duration_fit = 1.0 - min(1.0, abs(clip.duration - 35.0) / 70.0)
    has_text = len(clip.transcript.strip()) >= 30
    clean_edges = all(item.score >= 0.35 for item in clip.boundary_evidence) if clip.boundary_evidence else False
    return _clamp(0.30 + 0.30 * duration_fit + 0.25 * has_text + 0.15 * clean_edges)


def _speaker_clarity(clip: CandidateClip) -> float:
    speaker_penalty = max(0, len(clip.speakers) - 1) * 0.08
    overlap_penalty = min(0.7, clip.speech_overlap_count * 0.18)
    return _clamp(1.0 - speaker_penalty - overlap_penalty)


def _audio_quality(segments: Sequence[TranscriptSegment]) -> float:
    confidences = [segment.confidence for segment in segments if segment.confidence is not None]
    if not confidences:
        return 0.55
    return _clamp(sum(confidences) / len(confidences))


def _visual_quality(clip: CandidateClip, shots: Sequence[Shot]) -> float:
    cuts = sum(1 for shot in shots if clip.start < shot.start < clip.end)
    cuts_per_minute = cuts / max(clip.duration / 60.0, 0.01)
    if cuts_per_minute <= 10:
        return 0.92
    if cuts_per_minute <= 25:
        return 0.75
    return max(0.35, 1.0 - (cuts_per_minute - 25) / 60.0)


def score_clip(
    clip: CandidateClip,
    transcript_segments: Sequence[TranscriptSegment],
    shots: Sequence[Shot],
    editorial: Optional[EditorialSignals] = None,
    weights: Optional[Dict[str, float]] = None,
) -> ScoreBreakdown:
    selected = [segment for segment in transcript_segments if segment.id in set(clip.evidence_ids)]
    signals = editorial or EditorialSignals()
    importance = signals.importance if signals.importance is not None else _heuristic_importance(clip.transcript, signals.named_entities)
    hook = signals.hook if signals.hook is not None else _heuristic_hook(clip.transcript)
    self_contained = signals.self_contained if signals.self_contained is not None else _self_contained(clip)
    speaker_clarity = _speaker_clarity(clip)
    audio_quality = _audio_quality(selected)
    visual_quality = _visual_quality(clip, shots)

    applied = dict(DEFAULT_WEIGHTS)
    if weights:
        applied.update(weights)
    total_weight = sum(applied.values()) or 1.0
    base = (
        importance * applied["editorial_importance"]
        + hook * applied["hook_strength"]
        + self_contained * applied["self_contained"]
        + speaker_clarity * applied["speaker_clarity"]
        + audio_quality * applied["audio_quality"]
        + visual_quality * applied["visual_quality"]
    ) / total_weight

    overlap_penalty = min(0.18, clip.overlap_count * 0.045)
    attribution_penalty = 0.05 if not clip.speakers else 0.0
    final = round(10.0 * _clamp(base - overlap_penalty - attribution_penalty), 1)
    reasons: List[str] = []
    if signals.reason:
        reasons.append(signals.reason)
    if hook >= 0.7:
        reasons.append("strong opening or quotable line")
    if speaker_clarity >= 0.8:
        reasons.append("speaker is cleanly isolated")
    if clip.speech_overlap_count:
        reasons.append(f"{clip.speech_overlap_count} overlapping-speech region(s) lower confidence")
    if clip.overlap_count:
        reasons.append(f"overlaps {clip.overlap_count} other suggested clip(s)")
    if attribution_penalty:
        reasons.append("speaker attribution is missing")

    return ScoreBreakdown(
        editorial_importance=round(importance, 3),
        hook_strength=round(hook, 3),
        self_contained=round(self_contained, 3),
        speaker_clarity=round(speaker_clarity, 3),
        audio_quality=round(audio_quality, 3),
        visual_quality=round(visual_quality, 3),
        overlap_penalty=round(overlap_penalty, 3),
        attribution_penalty=round(attribution_penalty, 3),
        final_score=final,
        reasons=reasons,
    )


def score_all(
    clips: Sequence[CandidateClip],
    transcript_segments: Sequence[TranscriptSegment],
    shots: Sequence[Shot],
    editorial_by_clip: Optional[Dict[str, EditorialSignals]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> List[CandidateClip]:
    editorial_by_clip = editorial_by_clip or {}
    for clip in clips:
        clip.score = score_clip(
            clip,
            transcript_segments,
            shots,
            editorial_by_clip.get(clip.id),
            weights,
        )
    return sorted(clips, key=lambda item: item.score.final_score if item.score else 0.0, reverse=True)
