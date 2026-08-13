"use client";

import { CSSProperties, FormEvent, useCallback, useEffect, useMemo, useState } from "react";

type NodeStatus = "ready" | "review" | "hold" | "idle" | "running" | "failed";
type ConnectionState = "checking" | "online" | "offline";

type JobStatus =
  | "created" | "ingesting" | "ingested" | "preparing" | "prepared"
  | "transcribing" | "transcribed" | "analyzing" | "analyzed"
  | "rendering" | "ready" | "failed";

type JobManifest = {
  id: string;
  source_kind: string;
  source: string;
  title: string;
  reporter: string;
  status: JobStatus;
  created_at: string;
  updated_at: string;
  source_file: string | null;
  duration: number | null;
  language: string;
  error: string | null;
  artifacts: Record<string, string>;
};

type Clip = {
  id: string;
  start: number;
  end: number;
  title: string;
  summary: string;
  transcript: string;
  speakers: string[];
  topic: string;
  subtopic: string;
  state: "hold" | "review" | "ok" | "published";
  overlap_count: number;
  speech_overlap_count: number;
  score: { final_score: number; reasons: string[] } | null;
};

type TimelineDocument = {
  duration: number;
  events: Array<{
    id: string;
    kind: string;
    start: number;
    end: number;
    content: string;
    confidence: number;
    metadata: Record<string, unknown>;
  }>;
};

type Health = {
  status: string;
  capabilities: {
    speech_provider_configured: boolean;
    editorial_provider_configured: boolean;
    max_upload_bytes: number;
  };
};

type PackageSummary = {
  clip_id: string;
  aspect: string;
  files: Record<"video" | "audio" | "transcript" | "subtitles" | "metadata", string>;
};

type WorkflowNode = {
  id: string;
  name: string;
  eyebrow: string;
  description: string;
  accent: string;
  x: number;
  y: number;
  status: NodeStatus;
  metric: string;
  kind: "source" | "audio" | "vision" | "topic" | "clip" | "publish";
  clipId?: string;
};

const DEFAULT_API = process.env.NEXT_PUBLIC_MEDIAOPS_API_URL ?? "/api/pipeline";

const baseNodes: WorkflowNode[] = [
  { id: "source", name: "Long Video Input", eyebrow: "SOURCE · UPLOAD", description: "Waiting for a newsroom source", accent: "#8B54F2", x: 54, y: 118, status: "idle", metric: "MP4 · MOV · MKV · WEBM", kind: "source" },
  { id: "audio", name: "Audio Intelligence", eyebrow: "ASR + DIARIZATION", description: "Transcript, speakers, pauses and overlaps", accent: "#7133EF", x: 330, y: 48, status: "idle", metric: "Awaiting source audio", kind: "audio" },
  { id: "vision", name: "Visual Intelligence", eyebrow: "SHOTS + OCR + FACES", description: "Scene changes and active-speaker tracks", accent: "#C254C6", x: 330, y: 288, status: "idle", metric: "Awaiting source frames", kind: "vision" },
  { id: "topics", name: "Topic Segmentation", eyebrow: "CROSS-MODAL REASONING", description: "Find complete, evidence-backed story boundaries", accent: "#A400AA", x: 610, y: 164, status: "idle", metric: "Awaiting transcript + shots", kind: "topic" },
  { id: "publish", name: "Compose & Publish", eyebrow: "MULTI-FORMAT OUTPUT", description: "Review, reframe, render and distribute", accent: "#95009B", x: 1190, y: 242, status: "idle", metric: "16:9 · 9:16 · 4:5 · 1:1", kind: "publish" },
];

const palette = [
  { group: "Inputs", items: ["Video upload", "Source analyzer"] },
  { group: "AI intelligence", items: ["Audio diarization", "Shot detector", "Topic reasoning"] },
  { group: "Outputs", items: ["Multi-format export", "Timeline editor"] },
];

const fallbackWaveform = Array.from({ length: 92 }, (_, index) => 14 + ((index * 17 + index * index * 3) % 44));

function cleanBase(value: string) { return value.trim().replace(/\/$/, ""); }

async function apiRequest<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${cleanBase(base)}${path}`, { ...init, cache: "no-store" });
  const payload = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
  if (!response.ok) throw new Error(payload.error ?? `Request failed with HTTP ${response.status}`);
  return payload as T;
}

function formatTime(value: number) {
  const seconds = Math.max(0, Math.floor(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remaining = seconds % 60;
  return hours > 0
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(remaining).padStart(2, "0")}`;
}

function stageState(job: JobManifest | null, nodeId: string): NodeStatus {
  if (!job) return "idle";
  const sourceReady = Boolean(job.source_file);
  const visionReady = Boolean(job.artifacts.shots);
  const audioReady = Boolean(job.artifacts.transcript);
  const topicsReady = Boolean(job.artifacts.clips);
  const failed = job.status === "failed";
  if (nodeId === "source") {
    if (sourceReady) return "ready";
    if (failed) return "failed";
    return ["created", "ingesting"].includes(job.status) ? "running" : "idle";
  }
  if (nodeId === "vision") {
    if (visionReady) return "ready";
    if (failed && sourceReady) return "failed";
    return job.status === "preparing" ? "running" : "idle";
  }
  if (nodeId === "audio") {
    if (audioReady) return "ready";
    if (failed && Boolean(job.artifacts.audio)) return "failed";
    return ["preparing", "transcribing"].includes(job.status) ? "running" : "idle";
  }
  if (nodeId === "topics") {
    if (topicsReady) return "ready";
    if (failed && audioReady) return "failed";
    return job.status === "analyzing" ? "running" : "idle";
  }
  if (nodeId === "publish") return topicsReady ? "review" : "idle";
  return "idle";
}

function StatusPill({ status }: { status: NodeStatus }) {
  return <span className={`status status-${status}`}>{status}</span>;
}

function NodePreview({ node }: { node: WorkflowNode }) {
  if (node.kind === "source" || node.kind === "clip") {
    return (
      <div className={`media-preview ${node.kind === "clip" ? "media-small" : ""}`}>
        <div className="studio-light studio-light-one" /><div className="studio-light studio-light-two" />
        <div className="person-silhouette"><span /></div><div className="lower-third">MEDIAOPS · SOURCE</div>
        <span className="play-mini" aria-hidden="true">▶</span>
      </div>
    );
  }
  if (node.kind === "audio") return <div className="node-wave" aria-label="Audio waveform preview">{fallbackWaveform.slice(0, 30).map((height, index) => <i key={index} style={{ height: `${Math.max(7, height / 2)}px` }} />)}</div>;
  if (node.kind === "vision") return <div className="frame-strip">{[0, 1, 2].map((item) => <i key={item}><span /></i>)}</div>;
  if (node.kind === "topic") return <div className="topic-list"><span>Semantic</span><span>Speaker</span><span>Visual</span></div>;
  return <div className="destination-grid"><span>YT</span><span>IG</span><span>FB</span><span>TG</span></div>;
}

function WorkflowCard({ node, selected, onSelect }: { node: WorkflowNode; selected: boolean; onSelect: () => void }) {
  return (
    <article className={`workflow-node ${selected ? "is-selected" : ""}`} style={{ "--x": `${node.x}px`, "--y": `${node.y}px`, "--accent": node.accent } as CSSProperties} onClick={onSelect} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(); } }} role="button" tabIndex={0} aria-pressed={selected}>
      <span className="port port-in" /><span className="port port-out" />
      <span className="node-topline"><span className="node-eyebrow">{node.eyebrow}</span><StatusPill status={node.status} /></span>
      <strong>{node.name}</strong><NodePreview node={node} />
      <span className="node-description">{node.description}</span><span className="node-metric">{node.metric}</span>
    </article>
  );
}

function Inspector({ node, clip, packages, apiBase, jobId, rendering, onClipChange, onRender }: { node: WorkflowNode; clip?: Clip; packages: PackageSummary[]; apiBase: string; jobId?: string; rendering: boolean; onClipChange: (clip: Clip) => void; onRender: (clipId: string, aspect: "16:9" | "9:16") => Promise<void> }) {
  const [aspect, setAspect] = useState<"16:9" | "9:16">("16:9");
  const [template, setTemplate] = useState<"tv9_red" | "ntv_gold" | "neon_shorts" | "yellow_ticker">("tv9_red");

  const templateConfig = {
    tv9_red: { bg: "linear-gradient(180deg, #2b080a 0%, #0d0e12 40%, #2b080a 100%)", border: "#d91f2b", headerBg: "linear-gradient(90deg, #d91f2b 0%, #8b0000 100%)", headerTitle: "🔴 TV9 STYLE · LIVE NEWS", badge: "తాజా వార్తలు", badgeBg: "#d91f2b", font: "'Noto Sans Telugu', sans-serif", badgeColor: "#fff" },
    ntv_gold: { bg: "linear-gradient(180deg, #2a2006 0%, #0b0d10 40%, #2a2006 100%)", border: "#e5b836", headerBg: "linear-gradient(90deg, #e5b836 0%, #99740e 100%)", headerTitle: "🏆 NTV GOLD · BULLETIN", badge: "ముఖ్యమైన విశేషాలు", badgeBg: "#e5b836", font: "'Ramabhadra', sans-serif", badgeColor: "#000" },
    neon_shorts: { bg: "linear-gradient(180deg, #09231f 0%, #0d0e12 40%, #1c0827 100%)", border: "#b7f34b", headerBg: "linear-gradient(90deg, #b7f34b 0%, #76b51b 100%)", headerTitle: "⚡ REELS · SHORTS VIRAL", badge: "ట్రెండింగ్ న్యూస్", badgeBg: "#b7f34b", font: "'Mandali', sans-serif", badgeColor: "#000" },
    yellow_ticker: { bg: "linear-gradient(180deg, #1c1a05 0%, #0b0d10 40%, #1c1a05 100%)", border: "#f4e500", headerBg: "linear-gradient(90deg, #f4e500 0%, #b8ad00 100%)", headerTitle: "⚡ BREAKING NEWS TICKER", badge: "హెడ్‌లైన్స్", badgeBg: "#f4e500", font: "'Noto Sans Telugu', sans-serif", badgeColor: "#000" }
  }[template];

  const reviewClip = async () => {
    if (!clip || !jobId) return;
    const updated = await apiRequest<Clip>(apiBase, `/api/jobs/${jobId}/clips/${clip.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: clip.state === "ok" ? "review" : "ok" }) });
    onClipChange(updated);
  };
  const clipPackages = clip ? packages.filter((item) => item.clip_id === clip.id) : [];
  return (
    <aside className="inspector">
      <div className="inspector-heading"><div><span>INSPECTOR</span><h2>{node.name}</h2></div><span className="inspector-dot" style={{ background: node.accent }} /></div>
      <div className="inspector-section"><label>Node type</label><div className="readonly-field">{node.eyebrow}</div></div>
      {clip ? <>
        <div className="inspector-section two-col"><div><label>Start</label><div className="readonly-field">{formatTime(clip.start)}</div></div><div><label>End</label><div className="readonly-field">{formatTime(clip.end)}</div></div></div>
        <div className="inspector-section"><label>Visual Evidence Cut ({formatTime(clip.start)} – {formatTime(clip.end)})</label>{jobId ? (aspect === "9:16" ? (
          <div style={{ position: "relative", width: "100%", aspectRatio: "9/16", background: templateConfig.bg, borderRadius: "8px", overflow: "hidden", border: `1px solid ${templateConfig.border}`, boxShadow: "0 10px 30px rgba(0,0,0,0.8)", display: "flex", flexDirection: "column", justifyContent: "space-between", marginTop: "4px", fontFamily: templateConfig.font }}>
            <div style={{ padding: "10px 12px", background: templateConfig.headerBg, color: templateConfig.badgeColor, display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: "10px", fontWeight: "bold", letterSpacing: "0.5px" }}>
              <span>{templateConfig.headerTitle}</span>
              <span style={{ background: "rgba(255,255,255,0.25)", padding: "2px 6px", borderRadius: "3px" }}>9:16 REELS</span>
            </div>
            <div style={{ position: "relative", width: "100%", flex: 1, display: "flex", alignItems: "center", justifyContent: "center", background: "#000", overflow: "hidden" }}>
              <video key={`${clip.id}-${clip.start}`} className="inspector-clip-video" src={`${cleanBase(apiBase)}/api/jobs/${jobId}/source#t=${clip.start},${clip.end}`} controls preload="metadata" style={{ width: "100%", height: "100%", objectFit: "cover", objectPosition: "center" }}><track kind="captions" /></video>
            </div>
            <div style={{ padding: "10px 12px", background: "rgba(10, 12, 16, 0.95)", borderTop: `2px solid ${templateConfig.border}`, color: "#fff" }}>
              <span style={{ background: templateConfig.badgeBg, color: templateConfig.badgeColor, fontSize: "9px", fontWeight: "bold", padding: "2px 6px", borderRadius: "2px" }}>{templateConfig.badge}</span>
              <p style={{ margin: "4px 0 0 0", fontSize: "13px", fontWeight: "bold", lineHeight: "1.4", color: "#f8fafc", fontFamily: templateConfig.font }}>{clip.title || clip.summary}</p>
            </div>
          </div>
        ) : (
          <video key={`${clip.id}-${clip.start}`} className="inspector-clip-video" src={`${cleanBase(apiBase)}/api/jobs/${jobId}/source#t=${clip.start},${clip.end}`} controls preload="metadata" style={{ width: "100%", aspectRatio: "16/9", borderRadius: "6px", background: "#000", border: "1px solid #303640", marginTop: "4px" }}><track kind="captions" /></video>
        )) : <div className="readonly-field">Video source loading…</div>}</div>
        <div className="inspector-section"><label>Topic Headline (Telugu Font)</label><textarea readOnly value={clip.title || clip.summary} style={{ fontFamily: templateConfig.font, fontSize: "14px", fontWeight: "600" }} /></div>
        <div className="inspector-section"><label>Motion Graphic Template</label><div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "4px" }}><button type="button" onClick={() => setTemplate("tv9_red")} style={{ padding: "6px", borderRadius: "4px", background: template === "tv9_red" ? "#d91f2b" : "#1a1d21", color: "#fff", fontWeight: "bold", border: "1px solid #303640", cursor: "pointer", fontSize: "10px" }}>🔴 TV9 Red Studio</button><button type="button" onClick={() => setTemplate("ntv_gold")} style={{ padding: "6px", borderRadius: "4px", background: template === "ntv_gold" ? "#e5b836" : "#1a1d21", color: template === "ntv_gold" ? "#000" : "#fff", fontWeight: "bold", border: "1px solid #303640", cursor: "pointer", fontSize: "10px" }}>🏆 NTV Gold</button><button type="button" onClick={() => setTemplate("neon_shorts")} style={{ padding: "6px", borderRadius: "4px", background: template === "neon_shorts" ? "#b7f34b" : "#1a1d21", color: template === "neon_shorts" ? "#000" : "#fff", fontWeight: "bold", border: "1px solid #303640", cursor: "pointer", fontSize: "10px" }}>⚡ Cyber Neon</button><button type="button" onClick={() => setTemplate("yellow_ticker")} style={{ padding: "6px", borderRadius: "4px", background: template === "yellow_ticker" ? "#f4e500" : "#1a1d21", color: template === "yellow_ticker" ? "#000" : "#fff", fontWeight: "bold", border: "1px solid #303640", cursor: "pointer", fontSize: "10px" }}>⚡ Yellow Ticker</button></div></div>
        <div className="inspector-section"><label>Aspect Ratio Format</label><div style={{ display: "flex", gap: "8px", marginTop: "4px" }}><button type="button" onClick={() => setAspect("16:9")} style={{ flex: 1, padding: "8px 4px", borderRadius: "4px", background: aspect === "16:9" ? "#b7f34b" : "#1a1d21", color: aspect === "16:9" ? "#000" : "#a0a5ad", fontWeight: "bold", border: "1px solid #303640", cursor: "pointer", fontSize: "11px" }}>16:9 YouTube / FB</button><button type="button" onClick={() => setAspect("9:16")} style={{ flex: 1, padding: "8px 4px", borderRadius: "4px", background: aspect === "9:16" ? "#b7f34b" : "#1a1d21", color: aspect === "9:16" ? "#000" : "#a0a5ad", fontWeight: "bold", border: "1px solid #303640", cursor: "pointer", fontSize: "11px" }}>9:16 IG Reels / Shorts</button></div></div>
        <div className="confidence-row"><span>Editorial score</span><strong>{clip.score?.final_score?.toFixed(1) ?? "—"} / 10</strong></div>
        <div className="confidence-bar"><i style={{ width: `${(clip.score?.final_score ?? 0) * 10}%` }} /></div>
        {(clip.overlap_count > 0 || clip.speech_overlap_count > 0) && <p className="quality-warning">Review required: {clip.overlap_count} clip overlap(s), {clip.speech_overlap_count} speech overlap(s).</p>}
      </> : <div className="inspector-section"><label>Configuration</label><div className="setting-row"><span>Language</span><strong>Telugu</strong></div><div className="setting-row"><span>Evidence mode</span><strong>Strict</strong></div><div className="setting-row"><span>Human gate</span><strong>Required</strong></div></div>}
      <div className="inspector-section">
        <label>Supported Outputs (Click to Download / Export)</label>
        <div className="output-chips" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px", marginTop: "6px" }}>
          <button
            type="button"
            onClick={() => clip && onRender(clip.id, aspect)}
            disabled={!clip || rendering}
            style={{ padding: "8px 6px", borderRadius: "6px", background: "#7133EF", color: "#ffffff", fontWeight: "bold", border: "1px solid #7133EF", cursor: "pointer", fontSize: "10px", textAlign: "center", boxSizing: "border-box" }}
          >
            🎬 MP4 ({aspect})
          </button>
          <a
            href={jobId ? `${cleanBase(apiBase)}/api/jobs/${jobId}/audio` : "#"}
            target="_blank"
            rel="noreferrer"
            style={{ padding: "8px 6px", borderRadius: "6px", background: "#ffffff", border: "1px solid #A400AA", color: "#A400AA", fontWeight: "bold", textDecoration: "none", fontSize: "10px", textAlign: "center", display: "block", boxSizing: "border-box" }}
          >
            🎵 MP3 Audio
          </a>
          <a
            href={jobId ? `${cleanBase(apiBase)}/api/jobs/${jobId}/srt` : "#"}
            target="_blank"
            rel="noreferrer"
            style={{ padding: "8px 6px", borderRadius: "6px", background: "#ffffff", border: "1px solid #2563eb", color: "#2563eb", fontWeight: "bold", textDecoration: "none", fontSize: "10px", textAlign: "center", display: "block", boxSizing: "border-box" }}
          >
            📝 SRT Subtitles
          </a>
          <a
            href={jobId ? `${cleanBase(apiBase)}/api/jobs/${jobId}/clips` : "#"}
            target="_blank"
            rel="noreferrer"
            style={{ padding: "8px 6px", borderRadius: "6px", background: "#ffffff", border: "1px solid #059669", color: "#059669", fontWeight: "bold", textDecoration: "none", fontSize: "10px", textAlign: "center", display: "block", boxSizing: "border-box" }}
          >
            📊 JSON Data
          </a>
        </div>
      </div>
      <button className="primary-action" onClick={clip ? reviewClip : undefined} disabled={!clip}>{clip?.state === "ok" ? "Approved ✓ (Click to review)" : "Approve clip"}<span>→</span></button>
      <button className="secondary-action" onClick={() => clip && onRender(clip.id, aspect)} disabled={!clip || rendering}>{rendering ? `Rendering ${aspect} package…` : `Render ${aspect} Video Package`}</button>
      {clipPackages.map((item) => <div className="package-downloads" key={`${item.clip_id}-${item.aspect}`}><strong>{item.aspect.replace("x", ":")} package ready</strong><div>{Object.entries(item.files).map(([label, path]) => <a key={label} href={`${cleanBase(apiBase)}${path}`} target="_blank" rel="noreferrer">{label}</a>)}</div></div>)}
    </aside>
  );
}

function TimelineEditor({ job, clips, timeline: _timeline, peaks, apiBase, onClipChange, onSelectClip, onSwitchView }: { job: JobManifest | null; clips: Clip[]; timeline: TimelineDocument | null; peaks: number[]; apiBase: string; onClipChange: (clip: Clip) => void; onSelectClip: (clipId: string) => void; onSwitchView: (view: "canvas" | "timeline") => void }) {
  const bars = peaks.length ? peaks.slice(0, 140).map((peak) => Math.max(6, Math.round(peak * 58))) : fallbackWaveform;
  return (
    <section className="timeline-view">
      <div className="editor-main">
        <div className="editor-toolbar"><div><span className="back-arrow">←</span><strong>{job?.title ?? "No active video"}</strong></div><span className={`ready-copy ${job?.status === "failed" ? "failed-copy" : ""}`}><i /> {(job?.status ?? "IDLE").toUpperCase()} · {clips.length} TOPICS</span></div>
        <div className="video-stage">
          {job?.source_file ? <video className="real-video" src={`${cleanBase(apiBase)}/api/jobs/${job.id}/source`} controls preload="metadata" /> : <div className="empty-video"><span>＋</span><strong>Upload a newsroom video</strong><p>The original source will appear here while MediaOps analyzes it.</p></div>}
        </div>
        <div className="transport"><span>{formatTime(job?.duration ?? 0)} source duration</span></div>
        <div className="timeline-panel">
          <div className="timeline-ruler"><span>00:00</span><span>20%</span><span>40%</span><span>60%</span><span>80%</span><span>{formatTime(job?.duration ?? 0)}</span></div>
          <div className="waveform">{bars.map((height, index) => <i key={index} style={{ height: `${height}px` }} />)}<b className="playhead" /></div>
          <div className="topic-track">{(clips.length ? clips.slice().sort((a, b) => a.start - b.start).slice(0, 6) : [{ id: "empty", topic: "Awaiting analysis" } as Clip]).map((clip, index) => <span className={`topic topic-live topic-color-${index % 4}`} key={clip.id} style={{ flex: Math.max(1, clip.end ? clip.end - clip.start : 1) }} onClick={() => { onSelectClip(clip.id); onSwitchView("canvas"); }}>{clip.topic || `Topic ${index + 1}`}</span>)}</div>
          <div className="transcript-track">{clips.length ? clips.slice().sort((a, b) => a.start - b.start).slice(0, 6).map((clip) => <span key={clip.id} onClick={() => { onSelectClip(clip.id); onSwitchView("canvas"); }}>🎬 Cut ({formatTime(clip.start)} – {formatTime(clip.end)})</span>) : <span>Timestamped visual video cuts will populate this track.</span>}</div>
        </div>
      </div>
      <aside className="suggestions">
        <div className="suggestion-title"><div><span>AI SUGGESTED</span><h2>Topic clips</h2></div><b>{clips.length}</b></div>
        {clips.length ? clips.map((clip, index) => <article className="suggestion-card" key={clip.id}>
          <div className="score-ring">{clip.score?.final_score?.toFixed(1) ?? "—"}</div>
          <div><span>TOPIC {String(index + 1).padStart(2, "0")} · {formatTime(clip.start)}–{formatTime(clip.end)}</span><h3>{clip.title}</h3><p>{clip.summary}</p></div>
          <div className="suggestion-actions"><button onClick={() => { onSelectClip(clip.id); onSwitchView("canvas"); }}>Preview ▶</button><button className="accept" onClick={async () => { onSelectClip(clip.id); if (job) { const updated = await apiRequest<Clip>(apiBase, `/api/jobs/${job.id}/clips/${clip.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ state: clip.state === "ok" ? "review" : "ok" }) }); onClipChange(updated); } }}>{clip.state === "ok" ? "Approved ✓" : "Review →"}</button></div>
        </article>) : <div className="empty-suggestions"><span>⌁</span><p>Clips will appear as soon as cross-modal analysis completes.</p></div>}
      </aside>
    </section>
  );
}

function UploadDialog({ open, apiBase, health, connection, onClose, onApiBase, onUploaded }: { open: boolean; apiBase: string; health: Health | null; connection: ConnectionState; onClose: () => void; onApiBase: (value: string) => void; onUploaded: (job: JobManifest) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [reporter, setReporter] = useState("");
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  if (!open) return null;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) { setError("Choose a video file first."); return; }
    setUploading(true); setError(""); setProgress(0);
    const request = new XMLHttpRequest();
    request.open("POST", `${cleanBase(apiBase)}/api/jobs/upload`);
    request.setRequestHeader("Content-Type", file.type || "application/octet-stream");
    request.setRequestHeader("X-Filename", encodeURIComponent(file.name));
    request.setRequestHeader("X-Title", encodeURIComponent(title || file.name.replace(/\.[^.]+$/, "")));
    request.setRequestHeader("X-Reporter", encodeURIComponent(reporter));
    request.upload.onprogress = (uploadEvent) => { if (uploadEvent.lengthComputable) setProgress(Math.round((uploadEvent.loaded / uploadEvent.total) * 100)); };
    request.onerror = () => { setUploading(false); setError("Could not reach the MediaOps pipeline API."); };
    request.onload = () => {
      setUploading(false);
      try {
        const payload = JSON.parse(request.responseText);
        if (request.status < 200 || request.status >= 300) throw new Error(payload.error ?? "Upload failed");
        onUploaded(payload.job as JobManifest);
        onClose();
      } catch (uploadError) { setError(uploadError instanceof Error ? uploadError.message : "Upload failed"); }
    };
    request.send(file);
  };
  return <div className="modal-backdrop" role="presentation"><section className="upload-dialog" role="dialog" aria-modal="true" aria-labelledby="upload-title">
    <div className="dialog-header"><div><span>NEW WORKFLOW</span><h2 id="upload-title">Run a real video pipeline</h2></div><button onClick={onClose} aria-label="Close upload dialog">×</button></div>
    <form onSubmit={submit}>
      <label className="form-label">Pipeline API</label><div className="api-field"><input value={apiBase} onChange={(event) => onApiBase(event.target.value)} /><span className={`connection-light ${connection}`} /> </div>
      <p className="field-help">{connection === "online" ? "Connected to the processing backend." : connection === "checking" ? "Checking the backend…" : "Backend unavailable. Start it locally or enter its HTTPS URL."}</p>
      <label className={`file-drop ${file ? "has-file" : ""}`}><input type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm,.m4v" onChange={(event) => { const next = event.target.files?.[0] ?? null; setFile(next); if (next && !title) setTitle(next.name.replace(/\.[^.]+$/, "")); }} /><span>{file ? "✓" : "＋"}</span><strong>{file?.name ?? "Choose a 30-minute video"}</strong><small>{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : "MP4, MOV, MKV or WEBM"}</small></label>
      <div className="form-grid"><div><label className="form-label">Story title</label><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Prime-time bulletin" /></div><div><label className="form-label">Reporter</label><input value={reporter} onChange={(event) => setReporter(event.target.value)} placeholder="Reporter name" /></div></div>
      <div className="provider-checks"><span className={health?.capabilities.speech_provider_configured ? "configured" : "missing"}>Speech model {health?.capabilities.speech_provider_configured ? "ready" : "not configured"}</span><span className={health?.capabilities.editorial_provider_configured ? "configured" : "optional"}>Editorial model {health?.capabilities.editorial_provider_configured ? "ready" : "fallback enabled"}</span></div>
      {uploading && <div className="upload-progress"><i style={{ width: `${progress}%` }} /><span>{progress}% uploaded</span></div>}
      {error && <p className="dialog-error">{error}</p>}
      <div className="dialog-actions"><button type="button" onClick={onClose}>Cancel</button><button className="dialog-run" disabled={uploading || !file}>{uploading ? "Uploading…" : "Upload & run pipeline →"}</button></div>
    </form>
  </section></div>;
}

export default function Home() {
  const [selectedId, setSelectedId] = useState("topics");
  const [view, setView] = useState<"canvas" | "timeline">("canvas");
  const [zoom, setZoom] = useState(90);
  const [apiBase, setApiBase] = useState(DEFAULT_API);
  const [connection, setConnection] = useState<ConnectionState>("checking");
  const [health, setHealth] = useState<Health | null>(null);
  const [job, setJob] = useState<JobManifest | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [timeline, setTimeline] = useState<TimelineDocument | null>(null);
  const [peaks, setPeaks] = useState<number[]>([]);
  const [packages, setPackages] = useState<PackageSummary[]>([]);
  const [renderingClip, setRenderingClip] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("mediaops-api-url");
    const legacyLocalApi = /^https?:\/\/(127\.0\.0\.1|localhost):8787\/?$/i;
    if (!saved || legacyLocalApi.test(saved)) return;
    const timer = window.setTimeout(() => setApiBase(saved), 0);
    return () => window.clearTimeout(timer);
  }, []);

  const connect = useCallback(async (base: string) => {
    setConnection("checking");
    try {
      const result = await apiRequest<Health>(base, "/health");
      setHealth(result); setConnection("online"); window.localStorage.setItem("mediaops-api-url", cleanBase(base));
      const jobs = await apiRequest<{ jobs: JobManifest[] }>(base, "/api/jobs");
      if (jobs.jobs.length) setJob(jobs.jobs.sort((a, b) => b.created_at.localeCompare(a.created_at))[0]);
    } catch { setHealth(null); setConnection("offline"); }
  }, []);

  useEffect(() => { const timer = window.setTimeout(() => connect(apiBase), 350); return () => window.clearTimeout(timer); }, [apiBase, connect]);

  const loadArtifacts = useCallback(async (activeJob: JobManifest) => {
    if (!activeJob.artifacts.clips) return;
    const [clipDoc, timelineDoc, waveformDoc, packageDoc] = await Promise.all([
      apiRequest<{ clips: Clip[] }>(apiBase, `/api/jobs/${activeJob.id}/clips`),
      apiRequest<TimelineDocument>(apiBase, `/api/jobs/${activeJob.id}/timeline`),
      activeJob.artifacts.waveform
        ? apiRequest<{ peaks: number[] }>(apiBase, `/api/jobs/${activeJob.id}/waveform`).catch(() => ({ peaks: [] }))
        : Promise.resolve({ peaks: [] }),
      apiRequest<{ packages: PackageSummary[] }>(apiBase, `/api/jobs/${activeJob.id}/packages`),
    ]);
    setClips(clipDoc.clips); setTimeline(timelineDoc); setPeaks(waveformDoc.peaks ?? []); setPackages(packageDoc.packages ?? []);
  }, [apiBase]);

  useEffect(() => {
    if (!job?.id || connection !== "online") return;
    let cancelled = false;

    const refresh = async () => {
      try {
        const latest = await apiRequest<JobManifest>(apiBase, `/api/jobs/${job.id}`);
        if (cancelled) return;
        setJob(latest);
        if (latest.status === "ready" && clips.length === 0) {
          await loadArtifacts(latest);
          setRenderingClip(null);
        }
      } catch {
        if (!cancelled) setConnection("offline");
      }
    };

    refresh();

    if (job.status === "ready" || job.status === "failed") {
      return;
    }

    const timer = window.setInterval(refresh, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [job?.id, job?.status, connection, apiBase, loadArtifacts, clips.length]);

  const [searchQuery, setSearchQuery] = useState("");

  const liveNodes = useMemo(() => {
    const fixed = baseNodes.map((node) => {
      const status = stageState(job, node.id);
      if (node.id === "source") return { ...node, status, description: job?.title ?? node.description, metric: job ? `${job.source_kind.toUpperCase()} · ${formatTime(job.duration ?? 0)}` : node.metric };
      if (node.id === "audio") return { ...node, status, metric: job?.artifacts.transcript ? "Timestamped transcript ready" : status === "running" ? "Transcribing + assigning speakers" : node.metric };
      if (node.id === "vision") return { ...node, status, metric: job?.artifacts.shots ? "Shot timeline ready" : status === "running" ? "Detecting visual boundaries" : node.metric };
      if (node.id === "topics") return { ...node, status, metric: clips.length ? `${clips.length} topics · ${clips.filter((clip) => clip.state === "hold").length} held` : status === "running" ? "Finding topic boundaries" : node.metric };
      return { ...node, status, metric: clips.length ? `${clips.length} clips ready for review` : node.metric };
    });

    const CLIPS_PER_COL = 4;
    const clipList = clips.length ? clips : [null, null, null];
    const clipNodes: WorkflowNode[] = clipList.map((clip, index) => {
      const col = Math.floor(index / CLIPS_PER_COL);
      const row = index % CLIPS_PER_COL;
      const x = 900 + col * 310;
      const y = 42 + row * 190;
      return clip ? { id: `node-${clip.id}`, clipId: clip.id, name: clip.title || `Topic ${index + 1}`, eyebrow: `TOPIC ${String(index + 1).padStart(2, "0")} · ${(clip.topic || "GENERAL").toUpperCase()}`, description: `Visual Cut: ${formatTime(clip.start)} – ${formatTime(clip.end)}`, accent: "#b7f34b", x, y, status: clip.state === "ok" ? "ready" : clip.state, metric: `${formatTime(clip.start)}–${formatTime(clip.end)} · ${clip.score?.final_score?.toFixed(1) ?? "—"}`, kind: "clip" } : { id: `clip-placeholder-${index}`, name: `Topic clip ${String(index + 1).padStart(2, "0")}`, eyebrow: "AWAITING ANALYSIS", description: "A ranked topic cut will appear here", accent: "#b7f34b", x, y, status: job?.status === "analyzing" ? "running" : "idle", metric: "Visual cut · timestamped", kind: "clip" };
    });

    const totalCols = Math.max(1, Math.ceil(clipList.length / CLIPS_PER_COL));
    const publishNode: WorkflowNode = {
      ...fixed[4],
      x: 900 + totalCols * 310 + 60,
      y: 220,
    };

    return [...fixed.slice(0, 4), ...clipNodes, publishNode];
  }, [job, clips]);

  const selected = liveNodes.find((node) => node.id === selectedId) ?? liveNodes[3];
  const selectedClip = clips.find((clip) => clip.id === selected.clipId);
  const active = Boolean(job && !["ready", "failed"].includes(job.status));
  const updateClip = (updated: Clip) => setClips((items) => items.map((item) => item.id === updated.id ? updated : item));
  const renderPackage = async (clipId: string, aspect: "16:9" | "9:16" = "16:9") => {
    if (!job) return;
    setRenderingClip(clipId);
    try {
      await apiRequest(apiBase, `/api/jobs/${job.id}/package`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clip_ids: [clipId], aspect_ratio: aspect, crop_mode: "fit", burn_subtitles: true }) });
      setJob((current) => current ? { ...current, status: "rendering" } : current);
    } catch (error) {
      setRenderingClip(null);
      window.alert(error instanceof Error ? error.message : "Could not start package render");
    }
  };

  const topicNode = liveNodes.find((n) => n.id === "topics") ?? liveNodes[3];
  const publishNode = liveNodes.find((n) => n.id === "publish") ?? liveNodes[liveNodes.length - 1];
  const clipNodesOnly = liveNodes.filter((n) => n.kind === "clip");

  return <main className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark">M</span><strong>mediaops</strong><em>AI NEWSROOM</em></div>
      <nav className="view-tabs" aria-label="Workspace views"><button className={view === "canvas" ? "active" : ""} onClick={() => setView("canvas")}><span>⌘</span> Canvas</button><button className={view === "timeline" ? "active" : ""} onClick={() => setView("timeline")}><span>≋</span> Timeline</button></nav>
      <div className="top-actions"><button className={`connection-state ${connection}`} onClick={() => setDialogOpen(true)}><i /> {connection === "online" ? "PIPELINE ONLINE" : connection === "checking" ? "CONNECTING" : "PIPELINE OFFLINE"}</button><button className={`run-button ${active ? "running" : job?.status === "ready" ? "complete" : ""}`} onClick={() => setDialogOpen(true)}>{active ? `${job?.status.replace("ing", "ing…")}` : job?.status === "ready" ? "New workflow ＋" : "▶ Run workflow"}</button><span className="avatar">SJ</span></div>
    </header>
    {job?.status === "failed" && <div className="pipeline-error"><strong>Pipeline stopped</strong><span>{job.error}</span><button onClick={() => setDialogOpen(true)}>Configure & retry</button></div>}
    {view === "canvas" ? (
      <div className="workspace">
        <aside className="node-library">
          <div className="library-title"><span>NODES</span></div>
          <div className="node-search"><span>⌕</span><input aria-label="Search workflow nodes" placeholder="Search nodes…" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} /></div>
          {palette.map((section) => {
            const items = section.items.filter((item) => item.toLowerCase().includes(searchQuery.toLowerCase()));
            if (!items.length) return null;
            return (
              <section key={section.group}>
                <h2>{section.group}</h2>
                {items.map((item, index) => (
                  <button className="palette-node" key={item} onClick={() => {
                    if (item === "Video upload") setDialogOpen(true);
                    else if (item.includes("Speech") || item.includes("Audio") || item.includes("diarization")) setSelectedId("audio");
                    else if (item.includes("Visual") || item.includes("Shot")) setSelectedId("vision");
                    else if (item.includes("Topic") || item.includes("reasoning")) setSelectedId("topics");
                    else if (item.includes("export") || item.includes("Publish")) setSelectedId("publish");
                    else if (item.includes("Timeline")) setView("timeline");
                  }}>
                    <span className={`palette-icon palette-${section.group.split(" ")[0].toLowerCase()}`}>{index + 1}</span>
                    <span>{item}<small>{item === "Video upload" ? "Click to upload" : "Click to view stage"}</small></span>
                    <b>⋮⋮</b>
                  </button>
                ))}
              </section>
            );
          })}
        </aside>
        <section className="canvas-viewport" aria-label="Visual newsroom workflow"><div className="canvas-toolbar"><div><button onClick={() => setSelectedId("topics")}>↶</button><button onClick={() => setSelectedId("publish")}>↷</button><span /><button onClick={() => setZoom(90)}>Auto layout</button></div><div><button onClick={() => setZoom((value) => Math.max(40, value - 10))}>−</button><strong>{zoom}%</strong><button onClick={() => setZoom((value) => Math.min(130, value + 10))}>＋</button><button onClick={() => setZoom(90)}>Fit</button></div></div><div className="canvas-scroll"><div className="canvas" style={{ width: `${Math.max(1600, publishNode.x + 320)}px`, "--zoom": zoom / 100 } as CSSProperties}><div className="canvas-title"><span>WORKFLOW /</span> {job ? `${job.title} · ${job.status.toUpperCase()}` : "Long video → topic-wise newsroom packages"}</div>
        <svg style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 1 }}>
          <defs>
            <linearGradient id="purpleGrad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor="#7133EF" stopOpacity="0.8" />
              <stop offset="100%" stopColor="#A400AA" stopOpacity="0.8" />
            </linearGradient>
          </defs>
          {/* Main Stage Pipeline Wires */}
          <path d={`M 264 191 C 290 191, 290 118, 330 118`} fill="none" stroke="#7133EF" strokeWidth="2" strokeOpacity="0.6" />
          <path d={`M 264 191 C 290 191, 290 358, 330 358`} fill="none" stroke="#7133EF" strokeWidth="2" strokeOpacity="0.6" />
          <path d={`M 540 118 C 575 118, 575 234, 610 234`} fill="none" stroke="#A400AA" strokeWidth="2" strokeOpacity="0.6" />
          <path d={`M 540 358 C 575 358, 575 234, 610 234`} fill="none" stroke="#A400AA" strokeWidth="2" strokeOpacity="0.6" />
          
          {/* Fanned Web Mesh Connectors BEFORE the Matrix Cluster Box (Ends strictly at x=885) */}
          {[140, 260, 380, 500, 620].map((yPos, i) => {
            const startX = topicNode.x + 230;
            const startY = topicNode.y + 70;
            const midX = (startX + 885) / 2;
            return (
              <path key={`web-in-${i}`} d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${yPos}, 885 ${yPos}`} fill="none" stroke="#7133EF" strokeWidth="1.5" strokeOpacity="0.4" strokeDasharray={active ? "5 5" : "none"} />
            );
          })}

          {/* Fanned Web Mesh Connectors AFTER the Matrix Cluster Box (Starts strictly at x=clusterOutX) */}
          {(() => {
            const maxX = Math.max(...clipNodesOnly.map((n) => n.x), 900);
            const gridWidth = maxX - 900 + 250;
            const clusterOutX = 885 + gridWidth;
            const pubX = publishNode.x;
            const pubY = publishNode.y + 70;
            return [140, 260, 380, 500, 620].map((yPos, i) => {
              const midX = (clusterOutX + pubX) / 2;
              return (
                <path key={`web-out-${i}`} d={`M ${clusterOutX} ${yPos} C ${midX} ${yPos}, ${midX} ${pubY}, ${pubX} ${pubY}`} fill="none" stroke="#A400AA" strokeWidth="1.5" strokeOpacity="0.4" />
              );
            });
          })()}

          {/* High-Precision Active Wire for Selected Card (Stops at Box Outer Borders - Zero Pass Through) */}
          {selectedClip && (() => {
            const activeNode = liveNodes.find((n) => n.id === `node-${selectedClip.id}`);
            if (!activeNode) return null;
            const maxX = Math.max(...clipNodesOnly.map((n) => n.x), 900);
            const gridWidth = maxX - 900 + 250;
            const clusterOutX = 885 + gridWidth;
            const targetY = Math.min(750, Math.max(50, activeNode.y + 70));
            const startX = topicNode.x + 230;
            const startY = topicNode.y + 70;
            const midX = (startX + 885) / 2;
            const pubEndX = publishNode.x;
            const pubEndY = publishNode.y + 70;
            const pubMidX = (clusterOutX + pubEndX) / 2;
            return (
              <g key="active-highlight-wire">
                {/* Connector wire strictly BEFORE the box */}
                <path d={`M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${targetY}, 885 ${targetY}`} fill="none" stroke="#7133EF" strokeWidth="3" />
                <circle cx={885} cy={targetY} r="4" fill="#7133EF" />
                {/* Connector wire strictly AFTER the box */}
                <path d={`M ${clusterOutX} ${targetY} C ${pubMidX} ${targetY}, ${pubMidX} ${pubEndY}, ${pubEndX} ${pubEndY}`} fill="none" stroke="#A400AA" strokeWidth="3" />
                <circle cx={clusterOutX} cy={targetY} r="4" fill="#A400AA" />
              </g>
            );
          })()}
        </svg>
        {/* Topic Clips Group Matrix Frame */}
        {(() => {
          const maxX = Math.max(...clipNodesOnly.map((n) => n.x), 900);
          const gridWidth = maxX - 900 + 250;
          return (
            <div style={{ position: "absolute", left: 885, top: 16, width: `${gridWidth}px`, height: "780px", border: "1.5px dashed rgba(113, 51, 239, 0.4)", borderRadius: "12px", pointerEvents: "none", background: "rgba(113, 51, 239, 0.02)", padding: "10px 14px", color: "#7133EF", fontSize: "11px", fontWeight: "bold", letterSpacing: "1px", zIndex: 0 }}>
              ❖ TOPIC CLIPS MATRIX CLUSTER ({clips.length || 3} ITEMS)
            </div>
          );
        })()}
        {liveNodes.map((node) => <WorkflowCard key={node.id} node={node} selected={selected.id === node.id} onSelect={() => setSelectedId(node.id)} />)}<div className="canvas-note note-one"><span>01</span><p>Every clip keeps source timestamps and evidence IDs.</p></div><div className="canvas-note note-two" style={{ left: `${publishNode.x}px` }}><span>02</span><p>Editors approve before anything reaches publish.</p></div></div></div><div className="minimap"><div className="mini-flow"><i /><i /><i /><i /><i /></div><span>WORKFLOW MAP</span></div></section>
        <Inspector node={selected} clip={selectedClip} packages={packages} apiBase={apiBase} jobId={job?.id} rendering={renderingClip === selectedClip?.id} onClipChange={updateClip} onRender={renderPackage} />
      </div>
    ) : (
      <TimelineEditor job={job} clips={clips} timeline={timeline} peaks={peaks} apiBase={apiBase} onClipChange={updateClip} onSelectClip={(clipId) => setSelectedId(`node-${clipId}`)} onSwitchView={setView} />
    )}
    <UploadDialog open={dialogOpen} apiBase={apiBase} health={health} connection={connection} onClose={() => setDialogOpen(false)} onApiBase={setApiBase} onUploaded={(nextJob) => { setJob(nextJob); setClips([]); setTimeline(null); setPeaks([]); setDialogOpen(false); setSelectedId("source"); setView("timeline"); }} />
  </main>;
}
