from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .models import Shot


class MissingMediaTool(RuntimeError):
    pass


def resolve_tool(name: str, configured: Optional[str] = None) -> str:
    if configured:
        path = Path(configured)
        if path.exists():
            return str(path)
        raise MissingMediaTool(f"Configured {name} does not exist: {configured}")
    found = shutil.which(name)
    if not found:
        raise MissingMediaTool(
            f"{name} is required for this stage. Install it or set its path in configuration."
        )
    return found


def run_checked(command: Sequence[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def download_youtube(
    url: str,
    destination: Path,
    yt_dlp_path: Optional[str] = None,
) -> Path:
    tool = resolve_tool("yt-dlp", yt_dlp_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    output_template = str(destination.with_suffix(".%(ext)s"))
    run_checked(
        [
            tool,
            "--no-playlist",
            "--merge-output-format",
            "mp4",
            "--format",
            "bv*+ba/b",
            "--output",
            output_template,
            url,
        ]
    )
    candidates = sorted(destination.parent.glob(destination.stem + ".*"))
    media = [path for path in candidates if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
    if not media:
        raise RuntimeError("yt-dlp completed but no video file was produced")
    return media[0]


def copy_local_source(source: Path, destination_dir: Path) -> Path:
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / ("source" + source.suffix.lower())
    shutil.copy2(source, destination)
    return destination


def probe_video(path: Path, ffprobe_path: Optional[str] = None) -> Dict[str, Any]:
    tool = resolve_tool("ffprobe", ffprobe_path)
    result = run_checked(
        [
            tool,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    return json.loads(result.stdout)


def video_duration(probe: Dict[str, Any]) -> float:
    raw = probe.get("format", {}).get("duration")
    if raw is not None:
        return float(raw)
    durations = [float(stream["duration"]) for stream in probe.get("streams", []) if stream.get("duration")]
    if not durations:
        raise ValueError("No duration present in ffprobe output")
    return max(durations)


def extract_audio(
    source: Path,
    destination: Path,
    ffmpeg_path: Optional[str] = None,
) -> Path:
    tool = resolve_tool("ffmpeg", ffmpeg_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            tool,
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ]
    )
    return destination


def detect_scenes(
    source: Path,
    duration: float,
    threshold: float = 0.35,
    ffmpeg_path: Optional[str] = None,
) -> List[Shot]:
    tool = resolve_tool("ffmpeg", ffmpeg_path)
    expression = f"select=gt(scene\\,{threshold}),showinfo"
    process = subprocess.run(
        [tool, "-hide_banner", "-i", str(source), "-filter:v", expression, "-an", "-f", "null", "-"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-2000:])
    cut_times = [
        float(match.group(1))
        for match in re.finditer(r"pts_time:([0-9]+(?:\.[0-9]+)?)", process.stderr)
    ]
    boundaries = [0.0] + sorted({value for value in cut_times if 0.0 < value < duration}) + [duration]
    return [
        Shot(id=f"shot-{index + 1:04d}", start=start, end=end)
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]))
        if end - start > 0.04
    ]


def waveform_peaks(audio_path: Path, bins: int = 1800) -> List[float]:
    """Return normalized peak amplitudes for the editor timeline."""
    with wave.open(str(audio_path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        frame_count = handle.getnframes()
        if sample_width != 2:
            raise ValueError("waveform_peaks expects 16-bit PCM audio")
        frames_per_bin = max(1, int(math.ceil(frame_count / max(1, bins))))
        peaks: List[float] = []
        while True:
            raw = handle.readframes(frames_per_bin)
            if not raw:
                break
            count = len(raw) // 2
            samples = struct.unpack("<" + "h" * count, raw)
            if channels > 1:
                samples = samples[::channels]
            peaks.append(max((abs(value) for value in samples), default=0) / 32768.0)
    return peaks


def generate_thumbnail(
    source: Path,
    destination: Path,
    at_seconds: float,
    ffmpeg_path: Optional[str] = None,
) -> Path:
    tool = resolve_tool("ffmpeg", ffmpeg_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            tool,
            "-y",
            "-ss",
            f"{max(0.0, at_seconds):.3f}",
            "-i",
            str(source),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(destination),
        ]
    )
    return destination

