from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceKind(str, Enum):
    YOUTUBE = "youtube"
    UPLOAD = "upload"
    WHATSAPP = "whatsapp"
    FTP = "ftp"


class JobStatus(str, Enum):
    CREATED = "created"
    INGESTING = "ingesting"
    INGESTED = "ingested"
    PREPARING = "preparing"
    PREPARED = "prepared"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    RENDERING = "rendering"
    READY = "ready"
    FAILED = "failed"


class ReviewState(str, Enum):
    HOLD = "hold"
    REVIEW = "review"
    OK = "ok"
    PUBLISHED = "published"


@dataclass(frozen=True)
class TimeRange:
    start: float
    end: float

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("start must be non-negative")
        if self.end <= self.start:
            raise ValueError("end must be greater than start")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def overlaps(self, other: "TimeRange") -> float:
        return max(0.0, min(self.end, other.end) - max(self.start, other.start))


@dataclass
class Word:
    text: str
    start: float
    end: float
    confidence: Optional[float] = None
    speaker: Optional[str] = None
    timing_source: str = "model"


@dataclass
class TranscriptSegment:
    id: str
    start: float
    end: float
    text: str
    speaker: Optional[str] = None
    confidence: Optional[float] = None
    words: List[Word] = field(default_factory=list)
    language: str = "te"
    overlap_speakers: List[str] = field(default_factory=list)

    @property
    def time_range(self) -> TimeRange:
        return TimeRange(self.start, self.end)


@dataclass
class TranscriptDocument:
    language: str
    duration: float
    segments: List[TranscriptSegment]
    provider: str
    model: str
    timing_quality: str = "segment"
    raw_text: str = ""


@dataclass
class Shot:
    id: str
    start: float
    end: float
    confidence: float = 1.0


@dataclass
class TimelineEvent:
    id: str
    kind: str
    start: float
    end: float
    source: str
    content: str = ""
    confidence: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BoundaryEvidence:
    time: float
    score: float
    speaker_change: float
    semantic_novelty: float
    pause: float
    visual_cut: float
    reasons: List[str] = field(default_factory=list)


@dataclass
class ScoreBreakdown:
    editorial_importance: float
    hook_strength: float
    self_contained: float
    speaker_clarity: float
    audio_quality: float
    visual_quality: float
    overlap_penalty: float = 0.0
    duplicate_penalty: float = 0.0
    attribution_penalty: float = 0.0
    final_score: float = 0.0
    reasons: List[str] = field(default_factory=list)


@dataclass
class CandidateClip:
    id: str
    start: float
    end: float
    title: str
    summary: str
    transcript: str
    speakers: List[str]
    topic: str = ""
    subtopic: str = ""
    speech_overlap_count: int = 0
    overlap_count: int = 0
    overlap_clip_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    boundary_evidence: List[BoundaryEvidence] = field(default_factory=list)
    score: Optional[ScoreBreakdown] = None
    state: ReviewState = ReviewState.HOLD
    editor_start: Optional[float] = None
    editor_end: Optional[float] = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class OverlaySpec:
    enabled: bool = True
    text: str = ""
    position: str = "bottom"
    align: str = "center"
    style: str = "headline_box"
    reporter_credit: str = ""
    reporter_credit_enabled: bool = False


@dataclass
class RenderSpec:
    clip_ids: List[str]
    aspect_ratio: str = "16:9"
    crop_mode: str = "fit"
    burn_subtitles: bool = False
    overlay: OverlaySpec = field(default_factory=OverlaySpec)
    platform: str = "youtube"
    loudness_lufs: float = -14.0
    output_name: str = "clip.mp4"


@dataclass
class PlatformCopy:
    platform: str
    headline: str
    body: str
    tags: List[str] = field(default_factory=list)
    customized: bool = False


@dataclass
class FaithfulnessResult:
    score: float
    status: str
    unsupported_terms: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class PublishDraft:
    clip_id: str
    master_headline: str
    master_body: str
    platforms: Dict[str, PlatformCopy]
    faithfulness: FaithfulnessResult
    scheduled_for: Optional[str] = None


@dataclass
class EntityMention:
    entity_id: str
    canonical_name: str
    alias: str
    start: float
    end: float
    segment_id: str
    clip_ids: List[str] = field(default_factory=list)


@dataclass
class JobManifest:
    id: str
    source_kind: SourceKind
    source: str
    title: str
    reporter: str
    status: JobStatus
    created_at: str
    updated_at: str
    source_file: Optional[str] = None
    duration: Optional[float] = None
    language: str = "te"
    error: Optional[str] = None
    artifacts: Dict[str, str] = field(default_factory=dict)


def to_dict(value: Any) -> Dict[str, Any]:
    return asdict(value)
