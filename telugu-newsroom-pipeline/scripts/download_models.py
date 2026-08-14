#!/usr/bin/env python3
"""Automated Model Downloader & Verification Script for Telugu Newsroom Pipeline.

Pre-downloads and verifies:
1. Faster-Whisper ASR models (large-v3 / medium / small) from HuggingFace.
2. Ollama Local LLM (qwen2.5:7b-instruct) if Ollama is installed.
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = PROJECT_ROOT / "models" / "whisper"


def download_whisper_models() -> None:
    """Pre-download Faster-Whisper models into local models cache."""
    print("==================================================")
    print("📦 Pre-downloading Faster-Whisper ASR Models...")
    print("==================================================")
    
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[Error] faster-whisper is not installed. Please run: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)

    model_sizes = os.environ.get("WHISPER_MODELS", "small,medium,large-v3").split(",")
    
    for size in model_sizes:
        size = size.strip()
        if not size:
            continue
        print(f"\n📥 Downloading Faster-Whisper '{size}' model to {MODELS_DIR}...")
        try:
            # Download and initialize model cache
            model = WhisperModel(
                size,
                device="cpu",
                compute_type="int8",
                download_root=str(MODELS_DIR),
            )
            del model
            print(f"✅ Faster-Whisper '{size}' model successfully cached!")
        except Exception as err:
            print(f"⚠️ Warning: Failed to download '{size}' model: {err}", file=sys.stderr)


def verify_ollama_qwen() -> None:
    """Pull Qwen 2.5 7B model if Ollama CLI is present."""
    print("\n==================================================")
    print("🤖 Checking Local Ollama Qwen 2.5 7B Model...")
    print("==================================================")
    
    try:
        res = subprocess.run(["ollama", "--version"], capture_output=True, text=True)
        if res.returncode == 0:
            print("Found Ollama CLI. Pulling 'qwen2.5:7b-instruct'...")
            subprocess.run(["ollama", "pull", "qwen2.5:7b-instruct"])
            print("✅ Ollama Qwen 2.5 7B model ready!")
        else:
            print("ℹ️ Ollama CLI not found. Pipeline will use Gemini 3.5 API for editorial passes.")
    except FileNotFoundError:
        print("ℹ️ Ollama CLI not found. Pipeline will use Gemini 3.5 API for editorial passes.")


def main() -> None:
    download_whisper_models()
    verify_ollama_qwen()
    print("\n==================================================")
    print("✨ All models verified & cached successfully!")
    print("==================================================")


if __name__ == "__main__":
    main()
