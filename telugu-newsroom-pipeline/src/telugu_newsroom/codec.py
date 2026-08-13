from __future__ import annotations

from typing import Any, Dict, List

from .models import (
    BoundaryEvidence,
    CandidateClip,
    JobManifest,
    JobStatus,
    OverlaySpec,
    RenderSpec,
    ReviewState,
    ScoreBreakdown,
    Shot,
    SourceKind,
)


def manifest_from_dict(raw: Dict[str, Any]) -> JobManifest:
    return JobManifest(
        id=str(raw["id"]),
        source_kind=SourceKind(raw["source_kind"]),
        source=str(raw["source"]),
        title=str(raw.get("title", "")),
        reporter=str(raw.get("reporter", "")),
        status=JobStatus(raw["status"]),
        created_at=str(raw["created_at"]),
        updated_at=str(raw["updated_at"]),
        source_file=raw.get("source_file"),
        duration=float(raw["duration"]) if raw.get("duration") is not None else None,
        language=str(raw.get("language", "te")),
        error=raw.get("error"),
        artifacts=dict(raw.get("artifacts", {})),
    )


def shots_from_dict(raw: Any) -> List[Shot]:
    items = raw.get("shots", []) if isinstance(raw, dict) else raw
    return [
        Shot(
            id=str(item.get("id", f"shot-{index + 1:04d}")),
            start=float(item["start"]),
            end=float(item["end"]),
            confidence=float(item.get("confidence", 1.0)),
        )
        for index, item in enumerate(items)
    ]


def clip_from_dict(raw: Dict[str, Any]) -> CandidateClip:
    boundaries = [BoundaryEvidence(**item) for item in raw.get("boundary_evidence", [])]
    score = ScoreBreakdown(**raw["score"]) if raw.get("score") else None
    return CandidateClip(
        id=str(raw["id"]),
        start=float(raw["start"]),
        end=float(raw["end"]),
        title=str(raw.get("title", "")),
        summary=str(raw.get("summary", "")),
        transcript=str(raw.get("transcript", "")),
        speakers=list(raw.get("speakers", [])),
        topic=str(raw.get("topic", "")),
        subtopic=str(raw.get("subtopic", "")),
        speech_overlap_count=int(raw.get("speech_overlap_count", 0)),
        overlap_count=int(raw.get("overlap_count", 0)),
        overlap_clip_ids=list(raw.get("overlap_clip_ids", [])),
        evidence_ids=list(raw.get("evidence_ids", [])),
        boundary_evidence=boundaries,
        score=score,
        state=ReviewState(raw.get("state", "hold")),
        editor_start=float(raw["editor_start"]) if raw.get("editor_start") is not None else None,
        editor_end=float(raw["editor_end"]) if raw.get("editor_end") is not None else None,
    )


def render_spec_from_dict(raw: Dict[str, Any]) -> RenderSpec:
    overlay = OverlaySpec(**raw.get("overlay", {}))
    return RenderSpec(
        clip_ids=list(raw["clip_ids"]),
        aspect_ratio=str(raw.get("aspect_ratio", "16:9")),
        crop_mode=str(raw.get("crop_mode", "fit")),
        burn_subtitles=bool(raw.get("burn_subtitles", False)),
        overlay=overlay,
        platform=str(raw.get("platform", "youtube")),
        loudness_lufs=float(raw.get("loudness_lufs", -14.0)),
        output_name=str(raw.get("output_name", "clip.mp4")),
    )
