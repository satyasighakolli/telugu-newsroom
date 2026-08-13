#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

cd "$PROJECT_DIR"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e '.[media]' yt-dlp static-ffmpeg
.venv/bin/static_ffmpeg_paths

echo "MediaOps local runtime is ready."
echo "Add DEEPGRAM_API_KEY to $PROJECT_DIR/.env, then run ./scripts/run_local.sh"

