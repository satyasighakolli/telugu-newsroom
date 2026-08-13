# Telugu Newsroom Video Intelligence Pipeline

An evidence-first backend for converting a long Telugu news video into topic-wise,
reviewable media packages. Each package can contain the video clip, extracted audio,
plain transcript, SRT subtitles, topic/subtopic metadata, score explanation, and
platform copy.

This repository implements the vertical slice behind the supplied TV5 SNCC screens:

`ingest → prepare → transcribe/diarize → segment → enrich → score → review → compose → package → publish metadata → entity intelligence`

The core is dependency-light Python. FFmpeg/FFprobe and yt-dlp are external media
tools. ASR/diarization and editorial models use JSON command adapters, so the
newsroom can benchmark or replace providers without changing the workflow.

## What works

- Local upload, WhatsApp/FTP file, or YouTube ingestion.
- Video probing, mono 16 kHz speech audio, scene cuts, and waveform peaks.
- Timestamped Telugu transcript import or external ASR+diarization adapter.
- Cross-modal topic boundaries using language novelty, pauses, speaker changes,
  and visual cuts.
- Topic/subtopic/title/summary enrichment with a grounded model adapter and a
  deterministic fallback.
- Explainable 0–10 clip ranking, separate clip-overlap and overlapping-speech flags.
- Timeline JSON, review/hold state, editor trim fields, transcript SRT.
- Fit/Fill rendering for 16:9, 9:16, 4:5, and 1:1; multi-segment stitching;
  subtitles, Telugu headline overlays, loudness normalization.
- A per-topic package containing MP4, MP3, TXT, SRT, and JSON metadata.
- Platform draft/length rules, a fast faithfulness precheck, and entity pages.
- A small HTTP API matching the major screen data requirements.

## Quick verification (no media tools required)

```bash
cd /path/to/telugu-newsroom-pipeline
PYTHONPATH=src python3 -m unittest discover -s tests -v

PYTHONPATH=src python3 -m telugu_newsroom \
  --root var/demo \
  --config configs/default.json \
  demo --job-id demo-001
```

Inspect the generated job:

```bash
PYTHONPATH=src python3 -m telugu_newsroom \
  --root var/demo \
  --config configs/default.json \
  show demo-001
```

Start the UI-facing API:

```bash
PYTHONPATH=src python3 -m telugu_newsroom \
  --root var/demo \
  --config configs/default.json \
  serve --host 0.0.0.0 --port 8787 \
  --speech-command "/absolute/path/to/speech-adapter" \
  --editorial-command "/absolute/path/to/editorial-adapter"
```

Then open `http://127.0.0.1:8787/api/jobs/demo-001/clips`.

For a containerized worker, copy `.env.example` to `.env`, put provider
credentials in `.env`, and run `docker compose up --build`. A ready Deepgram
Nova-3 Telugu adapter is included; other ASR/diarization vendors can implement
the same command contract. The container
includes FFmpeg, FFprobe, yt-dlp, scene detection, and Telugu-capable Noto fonts.
The `/data` volume persists original videos, intermediate evidence, manifests,
and rendered packages across restarts.

## Run locally on macOS (no Docker)

The local runner keeps Python, FFmpeg, FFprobe, yt-dlp, and scene-detection
packages inside this project directory. It does not require Homebrew, Docker, or
administrator access.

```bash
./scripts/setup_local.sh
```

Put the Deepgram key in `.env` as `DEEPGRAM_API_KEY=...`, then start the API:

```bash
./scripts/run_local.sh
```

Verify it at `http://127.0.0.1:8787/health`. The local runner automatically uses
the included Deepgram adapter and the downloaded Apple-silicon media binaries.

## Real video run

Install FFmpeg/FFprobe and yt-dlp, then expose the selected speech model through
the contract in [PROVIDER_CONTRACTS.md](PROVIDER_CONTRACTS.md).

```bash
PYTHONPATH=src python3 -m telugu_newsroom \
  --root var/newsroom \
  --config configs/default.json \
  run \
  --source-kind upload \
  --source /absolute/path/to/video.mp4 \
  --title "Field report" \
  --reporter "Reporter Name" \
  --speech-command "/absolute/path/to/speech-adapter"
```

Add `--editorial-command "/absolute/path/to/editorial-adapter"` for model-based
Telugu topic labels, headlines, summaries, and editorial signals. Without it, the
pipeline uses a conservative local fallback.

Once an editor accepts the relevant clips, create complete packages:

```bash
PYTHONPATH=src python3 -m telugu_newsroom \
  --root var/newsroom \
  --config configs/default.json \
  package JOB_ID \
  --clip-id clip-0001 \
  --aspect 9:16 \
  --crop fill \
  --burn-subtitles \
  --font /absolute/path/to/a-telugu-font.ttf
```

## HTTP endpoints

- `GET /health`
- `GET /api/jobs`
- `POST /api/jobs`
- `POST /api/jobs/upload` (streamed request body; `X-Filename`, `X-Title`, and
  `X-Reporter` headers)
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/runtime`
- `GET /api/jobs/{job_id}/source` (HTTP range streaming)
- `GET /api/jobs/{job_id}/clips`
- `GET /api/jobs/{job_id}/timeline`
- `GET /api/jobs/{job_id}/waveform`
- `GET /api/jobs/{job_id}/publish`
- `GET /api/jobs/{job_id}/entities`
- `GET /api/jobs/{job_id}/quality`
- `POST /api/jobs/{job_id}/analyze`
- `POST /api/jobs/{job_id}/run`
- `POST /api/jobs/{job_id}/package`
- `GET /api/jobs/{job_id}/packages`
- `GET /api/jobs/{job_id}/packages/{clip_id}/{aspect}/{filename}`
- `PATCH /api/jobs/{job_id}/clips/{clip_id}`

Upload and processing are asynchronous. Poll the job manifest until `status` is
`ready` or `failed`. A package request accepts `clip_ids`, `aspect_ratio`,
`crop_mode`, and `burn_subtitles`; each finished topic exposes MP4, MP3, TXT,
SRT, and JSON download URLs.

The included HTTP worker is suitable for a private pilot. Before public production,
put it behind authentication and TLS, replace permissive CORS with the exact UI
origin, move media to object storage with signed URLs, and use a durable queue
instead of the in-process executor.

## Accuracy rules

1. Never infer speaker identity from diarization labels alone.
2. Preserve word/segment timestamps and evidence IDs through every stage.
3. Run ASR and diarization quality gates before editorial generation.
4. Treat visual boundaries as corroborating evidence, not the sole topic signal.
5. Hold low-confidence, unattributed, overlapping-speech, or unsupported outputs.
6. Require editorial review before publication.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the production topology and
[SCREEN_CONTRACT.md](SCREEN_CONTRACT.md) for the ten-screen mapping.
