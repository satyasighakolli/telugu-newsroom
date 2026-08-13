from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional, Sequence

from .codec import clip_from_dict
from .jsonio import DataclassJSONEncoder, dump_json
from .models import OverlaySpec, RenderSpec, SourceKind
from .pipeline import Pipeline
from .providers import CommandEditorialProvider, CommandSpeechProvider
from .rendering import extract_audio_track, render_clip
from .server import PipelineWorkerConfig, serve
from .transcript import load_transcript, segments_in_range, write_srt


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _print(value: Any) -> None:
    print(json.dumps(value, cls=DataclassJSONEncoder, ensure_ascii=False, indent=2))


def _pipeline(args: argparse.Namespace) -> Pipeline:
    config = Path(args.config).resolve() if args.config else None
    return Pipeline(Path(args.root), config)


def _editorial(command: Optional[str]) -> Optional[CommandEditorialProvider]:
    return CommandEditorialProvider.from_string(command) if command else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="newsroom-pipeline",
        description="Long-video analysis, topic clipping, review, render, and publish pipeline.",
    )
    parser.add_argument("--root", default="var/newsroom", help="Persistent pipeline data root")
    parser.add_argument("--config", help="JSON configuration file")
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--source-kind", choices=[item.value for item in SourceKind], required=True)
    create.add_argument("--source", required=True)
    create.add_argument("--title", default="")
    create.add_argument("--reporter", default="")

    ingest = commands.add_parser("ingest")
    ingest.add_argument("job_id")
    ingest.add_argument("--yt-dlp")

    prepare = commands.add_parser("prepare")
    prepare.add_argument("job_id")
    prepare.add_argument("--ffmpeg")
    prepare.add_argument("--ffprobe")

    transcript = commands.add_parser("import-transcript")
    transcript.add_argument("job_id")
    transcript.add_argument("path")

    shots = commands.add_parser("import-shots")
    shots.add_argument("job_id")
    shots.add_argument("path")

    transcribe = commands.add_parser("transcribe")
    transcribe.add_argument("job_id")
    transcribe.add_argument("--provider-command", required=True)

    analyze = commands.add_parser("analyze")
    analyze.add_argument("job_id")
    analyze.add_argument("--editorial-command")

    run = commands.add_parser("run")
    run.add_argument("--source-kind", choices=[item.value for item in SourceKind], required=True)
    run.add_argument("--source", required=True)
    run.add_argument("--title", default="")
    run.add_argument("--reporter", default="")
    run.add_argument("--speech-command", required=True)
    run.add_argument("--editorial-command")
    run.add_argument("--yt-dlp")
    run.add_argument("--ffmpeg")
    run.add_argument("--ffprobe")

    demo = commands.add_parser("demo")
    demo.add_argument("--job-id")

    package = commands.add_parser("package")
    package.add_argument("job_id")
    package.add_argument("--clip-id", action="append", dest="clip_ids")
    package.add_argument("--aspect", choices=["16:9", "9:16", "4:5", "1:1"], default="16:9")
    package.add_argument("--crop", choices=["fit", "fill"], default="fit")
    package.add_argument("--burn-subtitles", action="store_true")
    package.add_argument("--font")
    package.add_argument("--ffmpeg")

    server = commands.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8787)
    server.add_argument("--speech-command")
    server.add_argument("--editorial-command")
    server.add_argument("--ffmpeg")
    server.add_argument("--ffprobe")
    server.add_argument("--yt-dlp")
    server.add_argument("--workers", type=int, default=2)
    server.add_argument("--max-upload-gb", type=float, default=8.0)

    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("job_id")
    return parser


def execute(args: argparse.Namespace) -> Any:
    pipeline = _pipeline(args)
    if args.command == "create":
        return pipeline.create_job(
            SourceKind(args.source_kind), args.source, args.title, args.reporter
        )
    if args.command == "ingest":
        return pipeline.ingest(args.job_id, args.yt_dlp)
    if args.command == "prepare":
        return pipeline.prepare(args.job_id, args.ffmpeg, args.ffprobe)
    if args.command == "import-transcript":
        return pipeline.import_transcript(args.job_id, Path(args.path))
    if args.command == "import-shots":
        return pipeline.import_shots(args.job_id, Path(args.path))
    if args.command == "transcribe":
        return pipeline.transcribe(
            args.job_id,
            CommandSpeechProvider.from_string(args.provider_command),
        )
    if args.command == "analyze":
        return pipeline.analyze(args.job_id, _editorial(args.editorial_command))
    if args.command == "run":
        manifest = pipeline.create_job(
            SourceKind(args.source_kind), args.source, args.title, args.reporter
        )
        pipeline.ingest(manifest.id, args.yt_dlp)
        pipeline.prepare(manifest.id, args.ffmpeg, args.ffprobe)
        pipeline.transcribe(
            manifest.id,
            CommandSpeechProvider.from_string(args.speech_command),
        )
        return pipeline.analyze(manifest.id, _editorial(args.editorial_command))
    if args.command == "demo":
        manifest = pipeline.create_job(
            SourceKind.UPLOAD,
            "fixture://telugu-newsroom-demo",
            "Telugu newsroom pipeline demo",
            "Demo Reporter",
            job_id=args.job_id,
        )
        pipeline.import_transcript(manifest.id, PROJECT_ROOT / "fixtures" / "transcript_te.json")
        pipeline.import_shots(manifest.id, PROJECT_ROOT / "fixtures" / "shots.json")
        return pipeline.analyze(manifest.id)
    if args.command == "package":
        return _package_job(pipeline, args)
    if args.command == "serve":
        worker_config = PipelineWorkerConfig(
            speech_command=args.speech_command or os.environ.get("MEDIAOPS_SPEECH_COMMAND"),
            editorial_command=args.editorial_command or os.environ.get("MEDIAOPS_EDITORIAL_COMMAND"),
            ffmpeg_path=args.ffmpeg or os.environ.get("MEDIAOPS_FFMPEG"),
            ffprobe_path=args.ffprobe or os.environ.get("MEDIAOPS_FFPROBE"),
            yt_dlp_path=args.yt_dlp or os.environ.get("MEDIAOPS_YT_DLP"),
            workers=args.workers,
            max_upload_bytes=int(args.max_upload_gb * 1024 * 1024 * 1024),
        )
        serve(pipeline, args.host, args.port, worker_config)
        return None
    if args.command == "list":
        return {"jobs": pipeline.list_jobs()}
    if args.command == "show":
        return pipeline.load_manifest(args.job_id)
    raise ValueError(args.command)


def _package_job(pipeline: Pipeline, args: argparse.Namespace) -> Any:
    manifest = pipeline.load_manifest(args.job_id)
    if not manifest.source_file:
        raise RuntimeError("This job has no source video; ingest a real source before packaging")
    document = pipeline.read_artifact(args.job_id, "clips")
    clips = [clip_from_dict(item) for item in document["clips"]]
    chosen = [clip for clip in clips if not args.clip_ids or clip.id in set(args.clip_ids)]
    transcript = load_transcript(Path(manifest.artifacts["transcript"]))
    packages = []
    for clip in chosen:
        output_dir = pipeline.job_dir(args.job_id) / "renders" / clip.id / args.aspect.replace(":", "x")
        output_dir.mkdir(parents=True, exist_ok=True)
        effective_start = clip.editor_start if clip.editor_start is not None else clip.start
        effective_end = clip.editor_end if clip.editor_end is not None else clip.end
        segment_list = segments_in_range(transcript.segments, effective_start, effective_end)
        subtitle = output_dir / "transcript.srt"
        write_srt(segment_list, subtitle, offset=effective_start)
        package_transcript = " ".join(segment.text for segment in segment_list)
        (output_dir / "transcript.txt").write_text(package_transcript + "\n", encoding="utf-8")
        spec = RenderSpec(
            clip_ids=[clip.id],
            aspect_ratio=args.aspect,
            crop_mode=args.crop,
            burn_subtitles=args.burn_subtitles,
            overlay=OverlaySpec(enabled=True, text=clip.title),
            output_name=f"{clip.id}.mp4",
        )
        video = render_clip(
            Path(manifest.source_file),
            clips,
            spec,
            output_dir,
            subtitle_file=subtitle,
            font_file=Path(args.font) if args.font else None,
            ffmpeg_path=args.ffmpeg,
        )
        audio = extract_audio_track(video, output_dir / f"{clip.id}.mp3", args.ffmpeg)
        metadata = {
            "clip": clip,
            "video": str(video.resolve()),
            "audio": str(audio.resolve()),
            "transcript": str((output_dir / "transcript.txt").resolve()),
            "subtitles": str(subtitle.resolve()),
        }
        dump_json(output_dir / "package.json", metadata)
        packages.append(metadata)
    return {"packages": packages}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = execute(args)
        if result is not None:
            _print(result)
        return 0
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
