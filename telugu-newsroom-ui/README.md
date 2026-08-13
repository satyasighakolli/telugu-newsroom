# MediaOps Newsroom UI

## Run locally without Docker

Start the MediaOps Python backend on `127.0.0.1:8787`, then run:

```bash
npm install
npm run dev
```

The browser calls `/api/pipeline`, and the UI server proxies those requests to the
local backend. Set `MEDIAOPS_BACKEND_URL` only when the backend uses a different
address. This same-origin proxy avoids browser CORS and private-network restrictions.

The investor-facing MediaOps canvas is connected to the real Telugu newsroom
pipeline. It supports streamed uploads, live stage status, topic clips,
timestamped transcript evidence, source-video playback, editor approval, package
rendering, and MP4/MP3/TXT/SRT/JSON downloads.

## Local run

Start the pipeline API on port `8787`, then:

```bash
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. The pipeline URL can also be changed from the
connection/upload dialog and is saved only in that browser.

## Production configuration

Set `NEXT_PUBLIC_MEDIAOPS_API_URL` to the public HTTPS URL of the worker before
building or deploying. The backend must permit the site origin and support large
request bodies at the proxy/load-balancer layer.

```bash
NEXT_PUBLIC_MEDIAOPS_API_URL=https://pipeline.example.com npm run build
```

The UI deliberately reports a missing speech provider rather than pretending a
video can be analyzed. Configure `MEDIAOPS_SPEECH_COMMAND` on the worker according
to the backend `PROVIDER_CONTRACTS.md` file.
