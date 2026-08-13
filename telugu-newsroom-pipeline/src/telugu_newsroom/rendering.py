from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .media import resolve_tool
from .models import CandidateClip, RenderSpec


ASPECT_DIMENSIONS: Dict[str, Tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "4:5": (1080, 1350),
    "1:1": (1080, 1080),
}


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _video_geometry(aspect_ratio: str, crop_mode: str) -> str:
    width, height = ASPECT_DIMENSIONS[aspect_ratio]
    if crop_mode == "fit":
        if aspect_ratio == "9:16":
            # Blurred background fill template for 9:16 IG Reels / Shorts
            return (
                f"split=2[vbg][vfg];"
                f"[vbg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=25:10[bg];"
                f"[vfg]scale={width}:-1:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=0:(H-h)/2"
            )
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    if crop_mode == "fill":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    raise ValueError("crop_mode must be 'fit' or 'fill'")


def _overlay_filter(text_file: Path, spec: RenderSpec, font_file: Optional[Path]) -> str:
    width, height = ASPECT_DIMENSIONS[spec.aspect_ratio]
    position = spec.overlay.position
    if position == "top":
        y = f"{int(height * 0.08)}"
    elif position == "center":
        y = "(h-text_h)/2"
    else:
        y = f"h-text_h-{int(height * 0.08)}"
    if spec.overlay.align == "left":
        x = f"{int(width * 0.06)}"
    elif spec.overlay.align == "right":
        x = f"w-text_w-{int(width * 0.06)}"
    else:
        x = "(w-text_w)/2"
    style = spec.overlay.style.casefold().replace(" ", "_").replace("-", "_")
    options = [
        f"textfile='{_filter_path(text_file)}'",
        "reload=0",
        "fontcolor=white",
        f"fontsize={max(38, int(height * 0.045))}",
        f"x={x}",
        f"y={y}",
    ]
    if style == "plain":
        options.extend(["box=0", "shadowcolor=black@0.85", "shadowx=3", "shadowy=3"])
    elif style in {"breaking_strap", "news_ticker"}:
        options.extend(["box=1", "boxcolor=#b00020@0.92", "boxborderw=24"])
    elif style in {"boxed_(yellow)", "boxed_yellow"}:
        options.extend(["fontcolor=black", "box=1", "boxcolor=#f4e500@0.94", "boxborderw=24"])
    else:
        options.extend(["box=1", "boxcolor=black@0.62", "boxborderw=24"])
    if font_file:
        options.append(f"fontfile='{_filter_path(font_file)}'")
    return "drawtext=" + ":".join(options)


def build_render_command(
    source: Path,
    clips: Sequence[CandidateClip],
    spec: RenderSpec,
    output: Path,
    text_file: Path,
    subtitle_file: Optional[Path] = None,
    font_file: Optional[Path] = None,
    ffmpeg_path: str = "ffmpeg",
) -> List[str]:
    chosen = {clip.id: clip for clip in clips}
    ordered = [chosen[clip_id] for clip_id in spec.clip_ids]
    if not ordered:
        raise ValueError("RenderSpec.clip_ids cannot be empty")
    command: List[str] = [ffmpeg_path, "-y"]
    for clip in ordered:
        start = clip.editor_start if clip.editor_start is not None else clip.start
        end = clip.editor_end if clip.editor_end is not None else clip.end
        command.extend(["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(source)])

    geometry = _video_geometry(spec.aspect_ratio, spec.crop_mode)
    graph: List[str] = []
    for index in range(len(ordered)):
        graph.append(f"[{index}:v]{geometry},setsar=1,setpts=PTS-STARTPTS[v{index}]")
        graph.append(f"[{index}:a]aresample=48000,asetpts=PTS-STARTPTS[a{index}]")
    concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(ordered)))
    graph.append(f"{concat_inputs}concat=n={len(ordered)}:v=1:a=1[vbase][abase]")

    current_video = "vbase"
    if spec.burn_subtitles and subtitle_file:
        graph.append(f"[{current_video}]subtitles='{_filter_path(subtitle_file)}'[vsub]")
        current_video = "vsub"
    if spec.overlay.enabled and spec.overlay.text:
        graph.append(f"[{current_video}]{_overlay_filter(text_file, spec, font_file)}[vout]")
        current_video = "vout"
    graph.append(f"[abase]loudnorm=I={spec.loudness_lufs}:TP=-1.5:LRA=11[aout]")

    command.extend(
        [
            "-filter_complex",
            ";".join(graph),
            "-map",
            f"[{current_video}]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return command


def render_clip(
    source: Path,
    clips: Sequence[CandidateClip],
    spec: RenderSpec,
    output_dir: Path,
    subtitle_file: Optional[Path] = None,
    font_file: Optional[Path] = None,
    ffmpeg_path: Optional[str] = None,
) -> Path:
    tool = resolve_tool("ffmpeg", ffmpeg_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / spec.output_name
    text_file = output_dir / "overlay.txt"
    overlay_text = spec.overlay.text
    if spec.overlay.reporter_credit_enabled and spec.overlay.reporter_credit:
        overlay_text = f"{overlay_text}\n— {spec.overlay.reporter_credit}".strip()
    text_file.write_text(overlay_text, encoding="utf-8")
    command = build_render_command(
        source,
        clips,
        spec,
        output,
        text_file,
        subtitle_file=subtitle_file,
        font_file=font_file,
        ffmpeg_path=tool,
    )
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-4000:])
    return output


def extract_audio_track(
    video_path: Path,
    output_path: Path,
    ffmpeg_path: Optional[str] = None,
) -> Path:
    tool = resolve_tool("ffmpeg", ffmpeg_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run(
        [
            tool,
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-4000:])
    return output_path
