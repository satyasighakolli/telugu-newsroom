#!/bin/bash
set -eu

echo "=================================================="
echo "🤖 Setting up Local Qwen 2.5 7B Instruct Model..."
echo "=================================================="

# Check if Ollama is installed
if ! command -v ollama &> /dev/null; then
    echo "📦 Installing Ollama LLM Runner..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "📥 Pulling Qwen 2.5 7B Instruct model..."
ollama pull qwen2.5:7b-instruct

echo "✅ Qwen 2.5 7B model is ready for local editorial proofreading!"
