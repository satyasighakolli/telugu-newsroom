from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .codec import clip_from_dict, manifest_from_dict, shots_from_dict
from .entities import EntityDefinition, entity_pages, extract_mentions
from .jsonio import dump_json, load_json
from .media import (
    copy_local_source,
    detect_scenes,
    download_youtube,
    extract_audio,
    probe_video,
    video_duration,
    waveform_peaks,
)
from .models import (
    CandidateClip,
    JobManifest,
    JobStatus,
    OverlaySpec,
    RenderSpec,
    ReviewState,
    Shot,
    SourceKind,
    TimelineEvent,
)
from .providers import CommandEditorialProvider, CommandSpeechProvider, EditorialEnrichment
from .publishing import build_publish_draft
from .rendering import extract_audio_track, render_clip
from .scoring import EditorialSignals, score_all
from .segmentation import SegmentationConfig, annotate_clip_overlaps, segment_video
from .topics import apply_enrichment
from .transcript import load_transcript, segments_in_range, write_srt


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobNotFound(FileNotFoundError):
    pass


class Pipeline:
    """Persistent, resumable orchestration for the newsroom screens."""

    def __init__(self, root: Path, config_path: Optional[Path] = None) -> None:
        self.root = root.resolve()
        self.jobs_root = self.root / "jobs"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.config = load_json(config_path) if config_path else {}

    def job_dir(self, job_id: str) -> Path:
        safe = "".join(character for character in job_id if character.isalnum() or character in "-_")
        if safe != job_id or not safe:
            raise ValueError("Invalid job id")
        return self.jobs_root / safe

    def manifest_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "manifest.json"

    def load_manifest(self, job_id: str) -> JobManifest:
        path = self.manifest_path(job_id)
        if not path.exists():
            raise JobNotFound(job_id)
        return manifest_from_dict(load_json(path))

    def save_manifest(self, manifest: JobManifest) -> None:
        manifest.updated_at = utc_now()
        dump_json(self.manifest_path(manifest.id), manifest)

    def create_job(
        self,
        source_kind: SourceKind,
        source: str,
        title: str = "",
        reporter: str = "",
        job_id: Optional[str] = None,
    ) -> JobManifest:
        identifier = job_id or uuid.uuid4().hex[:12]
        directory = self.job_dir(identifier)
        if directory.exists():
            raise FileExistsError(f"Job already exists: {identifier}")
        for name in ("input", "analysis", "renders"):
            (directory / name).mkdir(parents=True, exist_ok=True)
        now = utc_now()
        manifest = JobManifest(
            id=identifier,
            source_kind=source_kind,
            source=source,
            title=title or Path(source).stem,
            reporter=reporter,
            status=JobStatus.CREATED,
            created_at=now,
            updated_at=now,
        )
        self.save_manifest(manifest)
        return manifest

    def list_jobs(self) -> List[Dict[str, Any]]:
        jobs = []
        for path in sorted(self.jobs_root.glob("*/manifest.json"), reverse=True):
            jobs.append(load_json(path))
        return jobs

    def ingest(
        self,
        job_id: str,
        yt_dlp_path: Optional[str] = None,
    ) -> JobManifest:
        manifest = self.load_manifest(job_id)
        manifest.status = JobStatus.INGESTING
        manifest.error = None
        self.save_manifest(manifest)
        try:
            if manifest.source_kind == SourceKind.YOUTUBE:
                media = download_youtube(
                    manifest.source,
                    self.job_dir(job_id) / "input" / "source",
                    yt_dlp_path,
                )
            else:
                media = copy_local_source(Path(manifest.source), self.job_dir(job_id) / "input")
            manifest.source_file = str(media.resolve())
            manifest.status = JobStatus.INGESTED
            manifest.artifacts["source"] = str(media.resolve())
            manifest.error = None
        except Exception as error:
            manifest.status = JobStatus.FAILED
            manifest.error = str(error)
            self.save_manifest(manifest)
            raise
        self.save_manifest(manifest)
        return manifest

    def prepare(
        self,
        job_id: str,
        ffmpeg_path: Optional[str] = None,
        ffprobe_path: Optional[str] = None,
    ) -> JobManifest:
        manifest = self.load_manifest(job_id)
        if not manifest.source_file:
            raise RuntimeError("Ingest the source before preparing the job")
        manifest.status = JobStatus.PREPARING
        manifest.error = None
        self.save_manifest(manifest)
        source = Path(manifest.source_file)
        analysis = self.job_dir(job_id) / "analysis"
        try:
            probe = probe_video(source, ffprobe_path)
            duration = video_duration(probe)
            audio = extract_audio(source, analysis / "audio.wav", ffmpeg_path)
            shots = detect_scenes(source, duration, ffmpeg_path=ffmpeg_path)
            dump_json(analysis / "probe.json", probe)
            dump_json(analysis / "shots.json", {"shots": shots})
            dump_json(
                analysis / "waveform.json",
                {"duration": duration, "peaks": waveform_peaks(audio)},
            )
            manifest.duration = duration
            manifest.status = JobStatus.PREPARED
            manifest.artifacts.update(
                {
                    "probe": str((analysis / "probe.json").resolve()),
                    "audio": str(audio.resolve()),
                    "shots": str((analysis / "shots.json").resolve()),
                    "waveform": str((analysis / "waveform.json").resolve()),
                }
            )
            manifest.error = None
        except Exception as error:
            manifest.status = JobStatus.FAILED
            manifest.error = str(error)
            self.save_manifest(manifest)
            raise
        self.save_manifest(manifest)
        return manifest

    def import_transcript(self, job_id: str, transcript_path: Path) -> JobManifest:
        manifest = self.load_manifest(job_id)
        transcript = load_transcript(transcript_path)
        destination = self.job_dir(job_id) / "analysis" / "transcript.json"
        dump_json(destination, transcript)
        manifest.duration = manifest.duration or transcript.duration
        manifest.status = JobStatus.TRANSCRIBED
        manifest.artifacts["transcript"] = str(destination.resolve())
        self.save_manifest(manifest)
        return manifest

    def import_shots(self, job_id: str, shots_path: Path) -> JobManifest:
        manifest = self.load_manifest(job_id)
        shots = shots_from_dict(load_json(shots_path))
        destination = self.job_dir(job_id) / "analysis" / "shots.json"
        dump_json(destination, {"shots": shots})
        manifest.artifacts["shots"] = str(destination.resolve())
        self.save_manifest(manifest)
        return manifest

    def transcribe(self, job_id: str, provider: CommandSpeechProvider) -> JobManifest:
        manifest = self.load_manifest(job_id)
        audio = manifest.artifacts.get("audio")
        if not audio:
            raise RuntimeError("Prepare the job before transcription")
        manifest.status = JobStatus.TRANSCRIBING
        manifest.error = None
        self.save_manifest(manifest)
        transcript = provider.transcribe(Path(audio), manifest.language)
        destination = self.job_dir(job_id) / "analysis" / "transcript.json"
        dump_json(destination, transcript)
        manifest.status = JobStatus.TRANSCRIBED
        manifest.duration = manifest.duration or transcript.duration
        manifest.artifacts["transcript"] = str(destination.resolve())
        self.save_manifest(manifest)
        return manifest

    def analyze(
        self,
        job_id: str,
        editorial_provider: Optional[CommandEditorialProvider] = None,
    ) -> JobManifest:
        manifest = self.load_manifest(job_id)
        manifest.status = JobStatus.ANALYZING
        manifest.error = None
        self.save_manifest(manifest)
        transcript_path = manifest.artifacts.get("transcript")
        if not transcript_path:
            raise RuntimeError("A timestamped transcript is required before analysis")
        transcript = load_transcript(Path(transcript_path))
        shots = self._load_shots(manifest, transcript.duration)
        config = self._segmentation_config()
        clips, boundaries = segment_video(transcript, shots, config)

        enrichment: Dict[str, EditorialEnrichment] = {}
        if editorial_provider:
            enrichment = editorial_provider.enrich(clips, transcript)
        apply_enrichment(clips, enrichment)
        annotate_clip_overlaps(clips)
        editorial_signals: Dict[str, EditorialSignals] = {
            clip_id: item.signals for clip_id, item in enrichment.items()
        }
        clips = score_all(
            clips,
            transcript.segments,
            shots,
            editorial_signals,
            self.config.get("score_weights"),
        )
        for clip in clips:
            if clip.score and clip.score.final_score >= 7.5 and clip.speech_overlap_count == 0:
                clip.state = ReviewState.REVIEW
            else:
                clip.state = ReviewState.HOLD

        analysis = self.job_dir(job_id) / "analysis"
        dump_json(analysis / "clips.json", {"clips": clips})
        dump_json(analysis / "boundaries.json", {"boundaries": boundaries})
        dump_json(analysis / "timeline.json", self._timeline(transcript, shots, boundaries))
        write_srt(transcript.segments, analysis / "transcript.srt")
        drafts = [build_publish_draft(clip) for clip in clips]
        dump_json(analysis / "publish.json", {"drafts": drafts})
        entity_definitions = self._entity_definitions()
        mentions = extract_mentions(transcript, clips, entity_definitions)
        dump_json(
            analysis / "entities.json",
            {
                "mentions": mentions,
                "pages": entity_pages(mentions, clips),
            },
        )
        dump_json(analysis / "quality.json", self._quality_report(clips, transcript))

        manifest.status = JobStatus.READY
        manifest.artifacts.update(
            {
                "clips": str((analysis / "clips.json").resolve()),
                "boundaries": str((analysis / "boundaries.json").resolve()),
                "timeline": str((analysis / "timeline.json").resolve()),
                "srt": str((analysis / "transcript.srt").resolve()),
                "publish": str((analysis / "publish.json").resolve()),
                "entities": str((analysis / "entities.json").resolve()),
                "quality": str((analysis / "quality.json").resolve()),
            }
        )
        manifest.error = None
        self.save_manifest(manifest)
        return manifest

    def fail_job(self, job_id: str, error: Exception) -> JobManifest:
        manifest = self.load_manifest(job_id)
        manifest.status = JobStatus.FAILED
        manifest.error = str(error)
        self.save_manifest(manifest)
        return manifest

    def package_clips(
        self,
        job_id: str,
        clip_ids: Sequence[str],
        aspect_ratio: str = "16:9",
        crop_mode: str = "fit",
        burn_subtitles: bool = True,
        font_file: Optional[Path] = None,
        ffmpeg_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Render selected topic clips and persist their video/audio/text package."""
        if aspect_ratio not in {"16:9", "9:16", "4:5", "1:1"}:
            raise ValueError("Unsupported aspect ratio")
        if crop_mode not in {"fit", "fill"}:
            raise ValueError("crop_mode must be 'fit' or 'fill'")
        manifest = self.load_manifest(job_id)
        if not manifest.source_file:
            raise RuntimeError("This job has no source video")
        document = self.read_artifact(job_id, "clips")
        clips = [clip_from_dict(item) for item in document["clips"]]
        selected_ids = set(clip_ids)
        selected = [clip for clip in clips if not selected_ids or clip.id in selected_ids]
        if not selected:
            raise ValueError("No matching clips selected")
        transcript = load_transcript(Path(manifest.artifacts["transcript"]))
        manifest.status = JobStatus.RENDERING
        manifest.error = None
        self.save_manifest(manifest)
        packages: List[Dict[str, Any]] = []
        for clip in selected:
            aspect_key = aspect_ratio.replace(":", "x")
            output_dir = self.job_dir(job_id) / "renders" / clip.id / aspect_key
            output_dir.mkdir(parents=True, exist_ok=True)
            start = clip.editor_start if clip.editor_start is not None else clip.start
            end = clip.editor_end if clip.editor_end is not None else clip.end
            clip_segments = segments_in_range(transcript.segments, start, end)
            subtitle = output_dir / "transcript.srt"
            transcript_file = output_dir / "transcript.txt"
            write_srt(clip_segments, subtitle, offset=start)
            transcript_file.write_text(
                " ".join(segment.text for segment in clip_segments).strip() + "\n",
                encoding="utf-8",
            )
            spec = RenderSpec(
                clip_ids=[clip.id],
                aspect_ratio=aspect_ratio,
                crop_mode=crop_mode,
                burn_subtitles=burn_subtitles,
                overlay=OverlaySpec(enabled=True, text=clip.title),
                output_name=f"{clip.id}.mp4",
            )
            video = render_clip(
                Path(manifest.source_file),
                clips,
                spec,
                output_dir,
                subtitle_file=subtitle,
                font_file=font_file,
                ffmpeg_path=ffmpeg_path,
            )
            audio = extract_audio_track(video, output_dir / f"{clip.id}.mp3", ffmpeg_path)
            metadata = {
                "clip": clip,
                "aspect_ratio": aspect_ratio,
                "crop_mode": crop_mode,
                "video": str(video.resolve()),
                "audio": str(audio.resolve()),
                "transcript": str(transcript_file.resolve()),
                "subtitles": str(subtitle.resolve()),
            }
            package_file = output_dir / "package.json"
            dump_json(package_file, metadata)
            manifest.artifacts[f"package:{clip.id}:{aspect_key}"] = str(package_file.resolve())
            packages.append(metadata)
        manifest.status = JobStatus.READY
        self.save_manifest(manifest)
        return {"packages": packages}

    def read_artifact(self, job_id: str, name: str) -> Any:
        manifest = self.load_manifest(job_id)
        path = manifest.artifacts.get(name)
        if not path:
            raise FileNotFoundError(f"Artifact not available: {name}")
        return load_json(Path(path))

    def _load_shots(self, manifest: JobManifest, duration: float) -> List[Shot]:
        path = manifest.artifacts.get("shots")
        if path and Path(path).exists():
            shots = shots_from_dict(load_json(Path(path)))
            if shots:
                return shots
        return [Shot(id="shot-0001", start=0.0, end=max(duration, 0.001), confidence=0.0)]

    def _segmentation_config(self) -> SegmentationConfig:
        keys = SegmentationConfig.__dataclass_fields__.keys()
        values = {key: self.config[key] for key in keys if key in self.config}
        return SegmentationConfig(**values)

    def _entity_definitions(self) -> List[EntityDefinition]:
        definitions = []
        for raw in self.config.get("entities", []):
            definitions.append(
                EntityDefinition(
                    id=str(raw["id"]),
                    canonical_name=str(raw["canonical_name"]),
                    aliases=[str(item) for item in raw.get("aliases", [])],
                    kind=str(raw.get("kind", "personality")),
                    metadata=dict(raw.get("metadata", {})),
                )
            )
        return definitions

    @staticmethod
    def _timeline(transcript: Any, shots: Sequence[Shot], boundaries: Sequence[Any]) -> Dict[str, Any]:
        events: List[TimelineEvent] = []
        for segment in transcript.segments:
            events.append(
                TimelineEvent(
                    id=segment.id,
                    kind="transcript",
                    start=segment.start,
                    end=segment.end,
                    source="asr",
                    content=segment.text,
                    confidence=segment.confidence if segment.confidence is not None else 0.0,
                    metadata={
                        "speaker": segment.speaker,
                        "overlap_speakers": segment.overlap_speakers,
                    },
                )
            )
        for shot in shots:
            events.append(
                TimelineEvent(
                    id=shot.id,
                    kind="shot",
                    start=shot.start,
                    end=shot.end,
                    source="scene_detection",
                    confidence=shot.confidence,
                )
            )
        return {
            "duration": transcript.duration,
            "events": events,
            "boundaries": list(boundaries),
        }

    @staticmethod
    def _quality_report(clips: Sequence[CandidateClip], transcript: Any) -> Dict[str, Any]:
        low_confidence = [
            segment.id
            for segment in transcript.segments
            if segment.confidence is not None and segment.confidence < 0.75
        ]
        missing_speaker = [segment.id for segment in transcript.segments if not segment.speaker]
        overlap = [segment.id for segment in transcript.segments if segment.overlap_speakers]
        holds = [clip.id for clip in clips if clip.state == ReviewState.HOLD]
        return {
            "status": "review" if low_confidence or missing_speaker or overlap or holds else "pass",
            "low_confidence_segment_ids": low_confidence,
            "missing_speaker_segment_ids": missing_speaker,
            "overlap_segment_ids": overlap,
            "held_clip_ids": holds,
            "policy": "No model-generated clip is published without newsroom review.",
        }
