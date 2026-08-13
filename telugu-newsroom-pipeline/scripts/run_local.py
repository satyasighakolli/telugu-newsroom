#!/usr/bin/env python3
"""Start the MediaOps API directly on macOS without Docker using absolute adapter paths."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from static_ffmpeg import run as static_ffmpeg_run


PROJECT_DIR = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MediaOps locally without Docker")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()

    load_env_file(PROJECT_DIR / ".env")
    ffmpeg_path, ffprobe_path = static_ffmpeg_run.get_or_fetch_platform_executables_else_raise()
    yt_dlp_path = shutil.which("yt-dlp", path=str(Path(sys.executable).parent))
    if not yt_dlp_path:
        raise SystemExit("yt-dlp is missing; run ./scripts/setup_local.sh")

    # Resolve absolute venv python executable to prevent relative path failure in subprocesses
    venv_python = PROJECT_DIR / ".venv" / "bin" / "python"
    python_bin = str(venv_python.resolve()) if venv_python.exists() else sys.executable

    local_whisper = (PROJECT_DIR / "adapters" / "local_whisper_speech.py").resolve()
    local_editorial = (PROJECT_DIR / "adapters" / "local_llm_editorial.py").resolve()

    speech_cmd = os.environ.get("MEDIAOPS_SPEECH_COMMAND", f"{python_bin} {local_whisper}").strip()
    editorial_cmd = os.environ.get("MEDIAOPS_EDITORIAL_COMMAND", f"{python_bin} {local_editorial}").strip()

    # Expand relative paths to absolute paths
    if speech_cmd.startswith(".venv"):
        speech_cmd = speech_cmd.replace(".venv/bin/python", python_bin, 1)
    if editorial_cmd.startswith(".venv"):
        editorial_cmd = editorial_cmd.replace(".venv/bin/python", python_bin, 1)

    print(f"[In-House Mode] Speech Command: {speech_cmd}", file=sys.stderr)
    print(f"[In-House Mode] Editorial Command: {editorial_cmd}", file=sys.stderr)

    command = [
        python_bin,
        "-m",
        "telugu_newsroom",
        "--root",
        str(PROJECT_DIR / "var" / "newsroom"),
        "--config",
        str(PROJECT_DIR / "configs" / "default.json"),
        "serve",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--speech-command",
        speech_cmd,
        "--editorial-command",
        editorial_cmd,
        "--ffmpeg",
        ffmpeg_path,
        "--ffprobe",
        ffprobe_path,
        "--yt-dlp",
        yt_dlp_path,
    ]

    env = dict(os.environ)
    src_dir = str(PROJECT_DIR / "src")
    env["PYTHONPATH"] = f"{src_dir}:{env.get('PYTHONPATH', '')}" if env.get("PYTHONPATH") else src_dir

    import subprocess
    os.chdir(PROJECT_DIR)
    sys.exit(subprocess.call(command, env=env))


if __name__ == "__main__":
    main()
