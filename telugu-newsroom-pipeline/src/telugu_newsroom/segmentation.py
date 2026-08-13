from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .models import BoundaryEvidence, CandidateClip, Shot, TranscriptDocument, TranscriptSegment


@dataclass
class SegmentationConfig:
    min_clip_seconds: float = 12.0
    target_clip_seconds: float = 35.0
    max_clip_seconds: float = 75.0
    boundary_threshold: float = 0.30
    shot_snap_tolerance_seconds: float = 0.75
    speaker_change_weight: float = 0.24
    semantic_novelty_weight: float = 0.34
    pause_weight: float = 0.24
    visual_cut_weight: float = 0.18


def normalize_tokens(text: str) -> Set[str]:
    return {
        token
        for token in re.findall(r"[\w\u0C00-\u0C7F]+", text.casefold(), flags=re.UNICODE)
        if len(token) > 1
    }


def semantic_novelty(left: str, right: str) -> float:
    left_tokens = normalize_tokens(left)
    right_tokens = normalize_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.5
    similarity = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return 1.0 - similarity


def nearest_shot_cut(time: float, shots: Sequence[Shot], tolerance: float) -> Tuple[float, float]:
    cut_times = [shot.start for shot in shots[1:]]
    if not cut_times:
        return time, 0.0
    nearest = min(cut_times, key=lambda value: abs(value - time))
    distance = abs(nearest - time)
    if distance > tolerance:
        return time, 0.0
    return nearest, max(0.0, 1.0 - distance / max(tolerance, 0.001))


def _pause_strength(left: TranscriptSegment, right: TranscriptSegment) -> float:
    gap = max(0.0, right.start - left.end)
    if gap >= 1.5:
        return 1.0
    return min(1.0, gap / 1.5)


def build_boundaries(
    transcript: TranscriptDocument,
    shots: Sequence[Shot],
    config: SegmentationConfig,
) -> List[BoundaryEvidence]:
    boundaries: List[BoundaryEvidence] = []
    segments = transcript.segments
    for left, right in zip(segments, segments[1:]):
        raw_time = (left.end + right.start) / 2.0
        snapped_time, visual = nearest_shot_cut(raw_time, shots, config.shot_snap_tolerance_seconds)
        speaker_change = 1.0 if left.speaker and right.speaker and left.speaker != right.speaker else 0.0
        novelty = semantic_novelty(left.text, right.text)
        pause = _pause_strength(left, right)
        score = (
            speaker_change * config.speaker_change_weight
            + novelty * config.semantic_novelty_weight
            + pause * config.pause_weight
            + visual * config.visual_cut_weight
        )
        reasons: List[str] = []
        if speaker_change:
            reasons.append("speaker changed")
        if novelty >= 0.65:
            reasons.append("language indicates a topic change")
        if pause >= 0.5:
            reasons.append("speech pause")
        if visual > 0:
            reasons.append("near a visual shot cut")
        boundaries.append(
            BoundaryEvidence(
                time=snapped_time,
                score=score,
                speaker_change=speaker_change,
                semantic_novelty=novelty,
                pause=pause,
                visual_cut=visual,
                reasons=reasons,
            )
        )
    return boundaries


def _best_boundary(
    boundaries: Sequence[BoundaryEvidence],
    minimum: float,
    preferred: float,
    maximum: float,
    threshold: float,
) -> Optional[BoundaryEvidence]:
    eligible = [item for item in boundaries if minimum <= item.time <= maximum]
    if not eligible:
        return None
    strong = [item for item in eligible if item.score >= threshold]
    pool = strong or eligible
    target_span = max(1.0, maximum - minimum)
    return max(
        pool,
        key=lambda item: item.score - 0.18 * abs(item.time - preferred) / target_span,
    )


def _clip_title(text: str, limit: int = 12) -> str:
    words = re.findall(r"\S+", text)
    if not words:
        return "Untitled clip"
    title = " ".join(words[:limit])
    return title + ("…" if len(words) > limit else "")


def segment_video(
    transcript: TranscriptDocument,
    shots: Sequence[Shot],
    config: Optional[SegmentationConfig] = None,
) -> Tuple[List[CandidateClip], List[BoundaryEvidence]]:
    cfg = config or SegmentationConfig()
    if not transcript.segments:
        return [], []
    boundaries = build_boundaries(transcript, shots, cfg)
    duration = transcript.duration or transcript.segments[-1].end
    selected: List[BoundaryEvidence] = []
    cursor = max(0.0, transcript.segments[0].start)

    while duration - cursor > cfg.max_clip_seconds:
        boundary = _best_boundary(
            boundaries,
            cursor + cfg.min_clip_seconds,
            cursor + cfg.target_clip_seconds,
            min(duration, cursor + cfg.max_clip_seconds),
            cfg.boundary_threshold,
        )
        if boundary is None or boundary.time <= cursor:
            cursor_next = min(duration - 5.0, cursor + cfg.target_clip_seconds)
            if cursor_next <= cursor:
                break
            boundary = BoundaryEvidence(time=cursor_next, score=0.4, speaker_change=0.0, semantic_novelty=0.5, pause=0.5, visual_cut=0.0, reasons=["time interval split"])
        selected.append(boundary)
        cursor = boundary.time

    strong_after_cursor = [
        item
        for item in boundaries
        if cursor + cfg.min_clip_seconds <= item.time <= duration - cfg.min_clip_seconds
        and item.score >= cfg.boundary_threshold
    ]
    for boundary in strong_after_cursor:
        if not selected or boundary.time - selected[-1].time >= cfg.min_clip_seconds:
            selected.append(boundary)

    cut_times = [max(0.0, transcript.segments[0].start)]
    cut_times.extend(sorted({round(item.time, 3) for item in selected}))
    cut_times.append(duration)

    clips: List[CandidateClip] = []
    for index, (start, end) in enumerate(zip(cut_times, cut_times[1:]), start=1):
        included = [segment for segment in transcript.segments if segment.end > start and segment.start < end]
        if not included:
            continue
        text = " ".join(segment.text.strip() for segment in included if segment.text.strip())
        speakers = sorted({segment.speaker for segment in included if segment.speaker})
        speech_overlap_count = sum(1 for segment in included if segment.overlap_speakers)
        evidence = [segment.id for segment in included]
        local_boundaries = [item for item in selected if math.isclose(item.time, start, abs_tol=0.01) or math.isclose(item.time, end, abs_tol=0.01)]
        clips.append(
            CandidateClip(
                id=f"clip-{index:04d}",
                start=start,
                end=end,
                title=_clip_title(text),
                summary=text[:280] + ("…" if len(text) > 280 else ""),
                transcript=text,
                speakers=speakers,
                speech_overlap_count=speech_overlap_count,
                evidence_ids=evidence,
                boundary_evidence=local_boundaries,
            )
        )
    return clips, boundaries


def annotate_clip_overlaps(clips: Sequence[CandidateClip]) -> None:
    """Populate the UI's OVERLAPS badge for independently suggested clips."""
    for clip in clips:
        clip.overlap_clip_ids = sorted(
            other.id
            for other in clips
            if other.id != clip.id
            and min(clip.end, other.end) > max(clip.start, other.start)
        )
        clip.overlap_count = len(clip.overlap_clip_ids)
