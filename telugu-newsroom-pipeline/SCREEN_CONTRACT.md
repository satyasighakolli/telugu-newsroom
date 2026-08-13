# Supplied Screen → Pipeline Contract

| Screen | Observed product behavior | Backend artifact or action |
|---|---|---|
| 1. Home / Suggested | WhatsApp/FTP/live feed; ranking; filters; score; Process/Compose/Review | `POST /api/jobs`, manifest source kind, explainable `clips.json`, review state |
| 2. Event analysis | Uploaded/YouTube event, READY state, waveform, transcript regions, AI cards, duration/aspects, overlap badge | `manifest.json`, `waveform.json`, `timeline.json`, `clips.json` |
| 3. Composer / Fit | Source clip, aspect tabs, Fit, IN/OUT/Split, Render & Preview | Clip trim fields, `RenderSpec`, FFmpeg fit/pad graph |
| 4. Composer / Fill | Vertical crop that fills the canvas | FFmpeg fill/scale/crop graph; production extension consumes subject tracks |
| 5. Timeline assembly | One selected segment, library/upload, burned-in text | Ordered `clip_ids`, overlay spec, transcript/SRT |
| 6. Rendered overlay | Telugu headline visibly burned over video | Unicode textfile-based FFmpeg drawtext and Telugu font input |
| 7. WA burst assembly | Multiple selected source segments in one story | Multi-input concat graph preserving selected order |
| 8. Overlay controls | Position, alignment, visual style, reporter credit | `OverlaySpec`; style/credit fields remain explicit and editor-owned |
| 9. Publish | Schedule, platform selection, master copy, rewrite actions, platform customization, faithfulness preview | `publish.json`; platform limits; faithfulness precheck; publish adapters are deployment-specific |
| 10. Personality page | Mention count, first/last seen, aliases, developing stories | `entities.json` from canonical entity definitions and clip evidence |

## Important distinctions preserved

- `speech_overlap_count` means two or more people speak at once and lowers speaker
  clarity.
- `overlap_count` and `overlap_clip_ids` mean suggested clips occupy the same source
  time and power the UI's `OVERLAPS N` badge.
- `state=hold/review/ok/published` is editorial workflow state, not model confidence.
- The 0–10 score is a ranking aid. It never authorizes publication.

