#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3}

cd "$PROJECT_DIR"
if [ ! -d ".venv" ]; then
    "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e '.[media]'
.venv/bin/static_ffmpeg_paths || true

# Pre-download and cache models
.venv/bin/python scripts/download_models.py

echo "=================================================="
echo "🎉 Telugu Newsroom pipeline runtime is ready!"
echo "Run ./scripts/run_local.sh to start the backend daemon."
echo "=================================================="
