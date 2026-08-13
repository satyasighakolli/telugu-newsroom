#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo " MediaOps In-House Model & ASR Setup (100% Local & Free)"
echo "============================================================"

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Setting up Python virtual environment..."
  python3 -m venv "$VENV_DIR"
fi

echo "Installing local in-house speech (Faster-Whisper) & NLP dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet faster-whisper openai-whisper requests

echo "Checking Ollama for local LLM inference (Qwen 2.5)..."
if command -v ollama >/dev/null 2>&1; then
  echo "✓ Ollama is installed."
  echo "Pulling Qwen 2.5 7B model for Telugu newsroom reasoning..."
  ollama pull qwen2.5:7b || echo "Ollama pull failed or offline. Native fallback will handle processing."
else
  echo "------------------------------------------------------------"
  echo "Notice: Ollama is not installed on system PATH."
  echo "To run Qwen 2.5 - 7B locally, install Ollama from https://ollama.com"
  echo "and run:  ollama pull qwen2.5:7b"
  echo "------------------------------------------------------------"
fi

echo ""
echo "Setup Complete!"
echo "To run MediaOps with 100% In-House local models:"
echo ""
echo "  export MEDIAOPS_SPEECH_COMMAND=\"$PROJECT_DIR/.venv/bin/python $PROJECT_DIR/adapters/local_whisper_speech.py\""
echo "  export MEDIAOPS_EDITORIAL_COMMAND=\"$PROJECT_DIR/.venv/bin/python $PROJECT_DIR/adapters/local_llm_editorial.py\""
echo "  ./scripts/run_local.sh"
echo "============================================================"
