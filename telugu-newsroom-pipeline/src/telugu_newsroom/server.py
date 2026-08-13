from __future__ import annotations

import json
import mimetypes
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

from .codec import clip_from_dict
from .jsonio import DataclassJSONEncoder, dump_json
from .models import JobStatus, ReviewState, SourceKind
from .pipeline import JobNotFound, Pipeline
from .providers import CommandEditorialProvider, CommandSpeechProvider


@dataclass
class PipelineWorkerConfig:
    speech_command: Optional[str] = None
    editorial_command: Optional[str] = None
    ffmpeg_path: Optional[str] = None
    ffprobe_path: Optional[str] = None
    yt_dlp_path: Optional[str] = None
    max_upload_bytes: int = 8 * 1024 * 1024 * 1024
    workers: int = 2


class PipelineExecutor:
    """Runs expensive media stages without blocking HTTP request threads."""

    def __init__(self, pipeline: Pipeline, config: PipelineWorkerConfig) -> None:
        self.pipeline = pipeline
        self.config = config
        self.pool = ThreadPoolExecutor(max_workers=max(1, config.workers), thread_name_prefix="mediaops")
        self._futures: Dict[str, Future[Any]] = {}
        self._lock = threading.Lock()

    @property
    def capabilities(self) -> Dict[str, Any]:
        speech_cmd = self.config.speech_command or ""
        speech_configured = bool(speech_cmd)
        if "deepgram_speech.py" in speech_cmd:
            deepgram_key = os.environ.get("DEEPGRAM_API_KEY", "").strip()
            speech_configured = bool(deepgram_key and deepgram_key != "replace_me")
        elif "local_whisper_speech.py" in speech_cmd or "whisper" in speech_cmd:
            speech_configured = True
        return {
            "speech_provider_configured": speech_configured,
            "editorial_provider_configured": bool(self.config.editorial_command),
            "max_upload_bytes": self.config.max_upload_bytes,
            "accepted_sources": [item.value for item in SourceKind],
        }

    def start(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            current = self._futures.get(job_id)
            if current and not current.done():
                return {"job_id": job_id, "runtime": "running"}
            future = self.pool.submit(self._run, job_id)
            self._futures[job_id] = future
        return {"job_id": job_id, "runtime": "queued"}

    def start_package(
        self,
        job_id: str,
        clip_ids: list[str],
        aspect_ratio: str,
        crop_mode: str,
        burn_subtitles: bool,
    ) -> Dict[str, Any]:
        with self._lock:
            current = self._futures.get(job_id)
            if current and not current.done():
                return {"job_id": job_id, "runtime": "running"}
            future = self.pool.submit(
                self._package,
                job_id,
                clip_ids,
                aspect_ratio,
                crop_mode,
                burn_subtitles,
            )
            self._futures[job_id] = future
        return {"job_id": job_id, "runtime": "queued"}

    def runtime(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            future = self._futures.get(job_id)
        if not future:
            return {"job_id": job_id, "runtime": "idle"}
        if future.running():
            return {"job_id": job_id, "runtime": "running"}
        if not future.done():
            return {"job_id": job_id, "runtime": "queued"}
        error = future.exception()
        return {
            "job_id": job_id,
            "runtime": "failed" if error else "complete",
            "error": str(error) if error else None,
        }

    def _run(self, job_id: str) -> None:
        try:
            manifest = self.pipeline.load_manifest(job_id)
            if not manifest.source_file:
                manifest = self.pipeline.ingest(job_id, self.config.yt_dlp_path)
            if "audio" not in manifest.artifacts or "shots" not in manifest.artifacts:
                manifest = self.pipeline.prepare(
                    job_id,
                    ffmpeg_path=self.config.ffmpeg_path,
                    ffprobe_path=self.config.ffprobe_path,
                )
            if "transcript" not in manifest.artifacts:
                if not self.config.speech_command:
                    raise RuntimeError(
                        "Speech provider is not configured. Set MEDIAOPS_SPEECH_COMMAND "
                        "to an adapter implementing PROVIDER_CONTRACTS.md."
                    )
                manifest = self.pipeline.transcribe(
                    job_id,
                    CommandSpeechProvider.from_string(self.config.speech_command),
                )
            editorial = (
                CommandEditorialProvider.from_string(self.config.editorial_command)
                if self.config.editorial_command
                else None
            )
            self.pipeline.analyze(job_id, editorial)
        except Exception as error:
            self.pipeline.fail_job(job_id, error)
            raise

    def _package(
        self,
        job_id: str,
        clip_ids: list[str],
        aspect_ratio: str,
        crop_mode: str,
        burn_subtitles: bool,
    ) -> None:
        try:
            self.pipeline.package_clips(
                job_id,
                clip_ids,
                aspect_ratio=aspect_ratio,
                crop_mode=crop_mode,
                burn_subtitles=burn_subtitles,
                ffmpeg_path=self.config.ffmpeg_path,
            )
        except Exception as error:
            self.pipeline.fail_job(job_id, error)
            raise


class NewsroomHandler(BaseHTTPRequestHandler):
    pipeline: Pipeline
    executor: PipelineExecutor

    def _send(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, cls=DataclassJSONEncoder, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("JSON body must be an object")
        return raw

    def _stream_upload(self, destination: Path) -> int:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Content-Length is required for video uploads")
        if length > self.executor.config.max_upload_bytes:
            raise ValueError("Upload exceeds the configured size limit")
        destination.parent.mkdir(parents=True, exist_ok=True)
        remaining = length
        written = 0
        with destination.open("wb") as handle:
            while remaining:
                block = self.rfile.read(min(1024 * 1024, remaining))
                if not block:
                    raise ConnectionError("Upload ended before Content-Length bytes arrived")
                handle.write(block)
                remaining -= len(block)
                written += len(block)
        return written

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type,Range,X-Filename,X-Title,X-Reporter",
        )
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            parts = self._parts()
            if parts == ("health",):
                self._send(HTTPStatus.OK, {"status": "ok", "capabilities": self.executor.capabilities})
                return
            if parts == ("api", "config"):
                self._send(HTTPStatus.OK, self.executor.capabilities)
                return
            if parts == ("api", "jobs"):
                self._send(HTTPStatus.OK, {"jobs": self.pipeline.list_jobs()})
                return
            if len(parts) == 3 and parts[:2] == ("api", "jobs"):
                self._send(HTTPStatus.OK, self.pipeline.load_manifest(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ("api", "jobs"):
                if parts[3] == "runtime":
                    self._send(HTTPStatus.OK, self.executor.runtime(parts[2]))
                    return
                if parts[3] == "source":
                    manifest = self.pipeline.load_manifest(parts[2])
                    if not manifest.source_file:
                        raise FileNotFoundError("Source media is not ready")
                    self._send_media(Path(manifest.source_file))
                    return
                if parts[3] == "packages":
                    self._send(HTTPStatus.OK, self._packages(parts[2]))
                    return
                if parts[3] in ("audio", "srt"):
                    manifest = self.pipeline.load_manifest(parts[2])
                    art_path = Path(manifest.artifacts.get(parts[3], ""))
                    if art_path.exists():
                        self._send_media(art_path)
                        return
                artifact = {
                    "clips": "clips",
                    "timeline": "timeline",
                    "publish": "publish",
                    "entities": "entities",
                    "quality": "quality",
                    "waveform": "waveform",
                    "srt": "srt",
                    "audio": "audio",
                }.get(parts[3])
                if artifact:
                    manifest = self.pipeline.load_manifest(parts[2])
                    art_path = Path(manifest.artifacts.get(artifact, ""))
                    if art_path.exists() and parts[3] in ("audio", "srt"):
                        self._send_media(art_path)
                        return
                    self._send(HTTPStatus.OK, self.pipeline.read_artifact(parts[2], artifact))
                    return
            if len(parts) == 7 and parts[:2] == ("api", "jobs") and parts[3] == "packages":
                self._send_package_file(parts[2], parts[4], parts[5], parts[6])
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except (JobNotFound, FileNotFoundError) as error:
            self._send(HTTPStatus.NOT_FOUND, {"error": str(error)})
        except Exception as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def do_POST(self) -> None:
        try:
            parts = self._parts()
            if parts == ("api", "jobs", "upload"):
                self._create_upload_job()
                return
            if parts == ("api", "jobs"):
                body = self._body()
                manifest = self.pipeline.create_job(
                    SourceKind(body["source_kind"]),
                    str(body["source"]),
                    str(body.get("title", "")),
                    str(body.get("reporter", "")),
                )
                if bool(body.get("run", False)):
                    self.executor.start(manifest.id)
                self._send(HTTPStatus.CREATED, manifest)
                return
            if len(parts) == 4 and parts[:2] == ("api", "jobs") and parts[3] == "run":
                self.pipeline.load_manifest(parts[2])
                self._send(HTTPStatus.ACCEPTED, self.executor.start(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ("api", "jobs") and parts[3] == "analyze":
                self._send(HTTPStatus.OK, self.pipeline.analyze(parts[2]))
                return
            if len(parts) == 4 and parts[:2] == ("api", "jobs") and parts[3] == "package":
                body = self._body()
                raw_ids = body.get("clip_ids", [])
                if not isinstance(raw_ids, list):
                    raise ValueError("clip_ids must be a list")
                result = self.executor.start_package(
                    parts[2],
                    [str(item) for item in raw_ids],
                    str(body.get("aspect_ratio", "16:9")),
                    str(body.get("crop_mode", "fit")),
                    bool(body.get("burn_subtitles", True)),
                )
                self._send(HTTPStatus.ACCEPTED, result)
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except Exception as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _create_upload_job(self) -> None:
        raw_filename = unquote(self.headers.get("X-Filename", "video.mp4"))
        filename = Path(raw_filename).name or "video.mp4"
        suffix = Path(filename).suffix.lower()
        if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}:
            raise ValueError("Unsupported video extension")
        upload_id = uuid.uuid4().hex
        destination = self.pipeline.root / "uploads" / f"{upload_id}{suffix}"
        written = self._stream_upload(destination)
        title = unquote(self.headers.get("X-Title", "")) or Path(filename).stem
        reporter = unquote(self.headers.get("X-Reporter", ""))
        manifest = self.pipeline.create_job(SourceKind.UPLOAD, str(destination), title, reporter)
        runtime = self.executor.start(manifest.id)
        self._send(
            HTTPStatus.ACCEPTED,
            {"job": manifest, "runtime": runtime["runtime"], "uploaded_bytes": written},
        )

    def do_PATCH(self) -> None:
        try:
            parts = self._parts()
            if len(parts) == 5 and parts[:2] == ("api", "jobs") and parts[3] == "clips":
                job_id, clip_id = parts[2], parts[4]
                body = self._body()
                manifest = self.pipeline.load_manifest(job_id)
                document = self.pipeline.read_artifact(job_id, "clips")
                clips = [clip_from_dict(item) for item in document["clips"]]
                selected = next((clip for clip in clips if clip.id == clip_id), None)
                if not selected:
                    self._send(HTTPStatus.NOT_FOUND, {"error": "clip_not_found"})
                    return
                for field in ("title", "summary", "topic", "subtopic"):
                    if field in body:
                        setattr(selected, field, str(body[field]))
                for field in ("editor_start", "editor_end"):
                    if field in body:
                        setattr(selected, field, float(body[field]) if body[field] is not None else None)
                if "state" in body:
                    selected.state = ReviewState(body["state"])
                if selected.editor_start is not None and selected.editor_end is not None:
                    if selected.editor_end <= selected.editor_start:
                        raise ValueError("editor_end must be greater than editor_start")
                dump_json(Path(manifest.artifacts["clips"]), {"clips": clips})
                self._send(HTTPStatus.OK, selected)
                return
            self._send(HTTPStatus.NOT_FOUND, {"error": "not_found"})
        except Exception as error:
            self._send(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _send_media(self, path: Path) -> None:
        size = path.stat().st_size
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        start, end = 0, size - 1
        range_header = self.headers.get("Range")
        status = HTTPStatus.OK
        if range_header and range_header.startswith("bytes="):
            value = range_header.removeprefix("bytes=").split(",", 1)[0]
            raw_start, raw_end = value.split("-", 1)
            start = int(raw_start) if raw_start else 0
            end = int(raw_end) if raw_end else min(size - 1, start + 4 * 1024 * 1024 - 1)
            end = min(end, size - 1)
            if start < 0 or start > end:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Expose-Headers", "Content-Length,Content-Range,Accept-Ranges")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with path.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    break
                self.wfile.write(block)
                remaining -= len(block)

    def _packages(self, job_id: str) -> Dict[str, Any]:
        manifest = self.pipeline.load_manifest(job_id)
        packages = []
        for key, package_path in manifest.artifacts.items():
            if not key.startswith("package:"):
                continue
            _, clip_id, aspect = key.split(":", 2)
            metadata = self.pipeline.read_artifact(job_id, key)
            base = f"/api/jobs/{job_id}/packages/{clip_id}/{aspect}"
            packages.append(
                {
                    "clip_id": clip_id,
                    "aspect": aspect,
                    "metadata": metadata,
                    "files": {
                        "video": f"{base}/{clip_id}.mp4",
                        "audio": f"{base}/{clip_id}.mp3",
                        "transcript": f"{base}/transcript.txt",
                        "subtitles": f"{base}/transcript.srt",
                        "metadata": f"{base}/{Path(package_path).name}",
                    },
                }
            )
        return {"packages": packages}

    def _send_package_file(self, job_id: str, clip_id: str, aspect: str, filename: str) -> None:
        if filename not in {f"{clip_id}.mp4", f"{clip_id}.mp3", "transcript.txt", "transcript.srt", "package.json"}:
            raise FileNotFoundError(filename)
        root = (self.pipeline.job_dir(job_id) / "renders").resolve()
        candidate = (root / clip_id / aspect / filename).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise FileNotFoundError(filename) from error
        if not candidate.is_file():
            raise FileNotFoundError(filename)
        self._send_media(candidate)

    def _parts(self) -> Tuple[str, ...]:
        return tuple(part for part in urlparse(self.path).path.split("/") if part)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(
    pipeline: Pipeline,
    host: str = "127.0.0.1",
    port: int = 8787,
    worker_config: Optional[PipelineWorkerConfig] = None,
) -> None:
    executor = PipelineExecutor(pipeline, worker_config or PipelineWorkerConfig())
    handler = type(
        "ConfiguredNewsroomHandler",
        (NewsroomHandler,),
        {"pipeline": pipeline, "executor": executor},
    )
    server = ThreadingHTTPServer((host, port), handler)
    print(f"MediaOps API listening on http://{host}:{port}")
    server.serve_forever()
