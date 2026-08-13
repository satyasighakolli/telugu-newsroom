#!/usr/bin/env bash
set -euo pipefail

OUTPUTS_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$OUTPUTS_DIR/telugu-newsroom-pipeline"
UI_DIR="$OUTPUTS_DIR/telugu-newsroom-ui"
UI_PORT="${MEDIAOPS_UI_PORT:-3001}"

if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  "$BACKEND_DIR/scripts/setup_local.sh"
fi

if [[ ! -d "$UI_DIR/node_modules" ]]; then
  (cd "$UI_DIR" && npm ci)
fi

(cd "$BACKEND_DIR" && exec ./scripts/run_local.sh) &
BACKEND_PID=$!

cleanup() {
  kill "$BACKEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in {1..40}; do
  if curl --silent --fail http://127.0.0.1:8787/health >/dev/null; then
    break
  fi
  sleep 0.25
done

echo "MediaOps UI: http://localhost:$UI_PORT"
echo "MediaOps API: http://127.0.0.1:8787"
echo "Press Ctrl+C to stop both services."

cd "$UI_DIR"
MEDIAOPS_BACKEND_URL="http://127.0.0.1:8787" npm run dev -- --port "$UI_PORT"
