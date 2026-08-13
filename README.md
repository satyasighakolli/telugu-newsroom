# 📺 Telugu Newsroom AI MediaOps Platform

A production-grade AI MediaOps platform for long-form Telugu TV news bulletins (16:9) into topic-wise, evidence-backed multi-format news packages (9:16 Reels / Shorts, 16:9, 1:1, 4:5).

---

## 🏗️ Monorepo Architecture

```
telugu-newsroom/
├── telugu-newsroom-pipeline/   # Python 3.12 Backend (Faster-Whisper, Gemini 3.5 Flash, FFmpeg NVENC)
└── telugu-newsroom-ui/         # React / Next.js Light Studio Frontend (Canvas Matrix, Timeline Editor)
```

---

## ⚡ Key Features

- **Local ASR & Diarization**: 100% local speech-to-text with Faster-Whisper (Telugu).
- **Gemini Headline Polish**: Two-pass AI proofreading (`gemini-3.5-flash`) for 3-5 word Telugu headlines.
- **Dynamic Topic Matrix**: Multi-column matrix cluster representation with uncluttered SVG boundary connectors.
- **Motion Graphic Templates**: TV9 Red Studio, NTV Gold, Cyber Neon, and Yellow Ticker overlays.
- **Multi-Format Video Exports**: 9:16 vertical crop fill, 16:9 YouTube, SRT subtitles, MP3 audio, and JSON story data.

---

## 🚀 Quick Start

### 1. Start Backend Pipeline Server
```bash
cd telugu-newsroom-pipeline
bash scripts/run_local.sh
```

### 2. Start Frontend UI
```bash
cd telugu-newsroom-ui
npm run dev -- --port 3001
```

Open **http://localhost:3001** to view the application.

---

## 📄 License
MIT License.
