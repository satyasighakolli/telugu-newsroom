# MediaOps — local, Docker-free run

The pipeline now runs natively on macOS. Python, FFmpeg, FFprobe and `yt-dlp`
live inside the project environment, so Docker and Homebrew are not required.

## One-time configuration

Open `telugu-newsroom-pipeline/.env` and replace:

```dotenv
DEEPGRAM_API_KEY=replace_me
```

with a real Deepgram key. Without it, the UI and demo work, but uploaded videos
cannot receive production Telugu transcription.

## Start everything

```bash
cd /Users/satyasighakolli/Documents/Codex/2026-08-07/i-want-to-analyze-an-entire/outputs
./run-mediaops-local.sh
```

Then open <http://localhost:3001>. The UI uses its same-origin `/api/pipeline`
proxy to reach the native backend at `127.0.0.1:8787`.

Press `Ctrl+C` in the terminal to stop both services.
