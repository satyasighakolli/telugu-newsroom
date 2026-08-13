#!/usr/bin/env python3
"""Two-Pass Newsroom Proofreader & Editorial Adapter for MediaOps.

Architecture:
- Pass 1 (Local Qwen 2.5 7B / Rule Engine): Rapid clip parsing & draft topic segmentation.
- Pass 2 (Gemini API): High-precision Telugu TV headline & summary refinement (if GEMINI_API_KEY present).
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

# Load .env file automatically
_env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.isfile(_env_path):
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _raw_line in _f:
            _line = _raw_line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")
BATCH_SIZE = int(os.environ.get("EDITORIAL_BATCH_SIZE", "20"))


try:
    from json_repair import repair_json
except ImportError:
    def repair_json(text: str) -> str:
        return text


def _clean_json_response(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract valid JSON object from LLM output using json_repair."""
    if not raw_text:
        return None
    raw_text = raw_text.strip()
    raw_text = re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL).strip()
    if raw_text.startswith("```"):
        raw_text = re.sub(r"^```(?:json)?\n?", "", raw_text)
        raw_text = re.sub(r"\n?```$", "", raw_text)
    try:
        repaired_str = repair_json(raw_text)
        data = json.loads(repaired_str)
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
            return {"clips": data}
    except Exception as err:
        print(f"[Warning] JSON repair failed: {err}", file=sys.stderr)

    return None


def call_gemini_api(prompt: str) -> Optional[str]:
    """Pass 2: Refine Telugu headlines via Gemini Flash REST API with native JSON response mode."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "replace_me":
        return None

    for model_name in [GEMINI_MODEL, "gemini-3.5-flash", "gemini-3.6-flash", "gemini-flash-latest"]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "temperature": 0.1,
            }
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            print(f"[Editorial LLM] Calling Gemini API ({model_name}) for Telugu headline perfection...", file=sys.stderr)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        text = parts[0].get("text", "")
                        print(f"[Editorial LLM] Gemini successfully refined headlines!", file=sys.stderr)
                        return text
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            print(f"[Notice] Gemini model {model_name} unavailable: {err}", file=sys.stderr)
            continue

    return None


SYSTEM_NEWSROOM_PROMPT = """మీరు ప్రముఖ తెలుగు టీవీ న్యూస్ డెస్క్ చీఫ్ ఎడిటర్ (TV9 / NTV).
గార్బిల్డ్ స్పీచ్-టు-టెక్స్ట్ (ASR) పాఠాన్ని చదివి, 100% వ్యాకరణబద్ధమైన, స్పష్టమైన కర్త-కర్మ-క్రియ పరిపూర్ణ తెలుగు వాక్య నిర్మాణంతో టీవీ న్యూస్ శీర్షికలు, సారాంశాలు, శుద్ధ పాఠాలను తయారు చేయండి.

ముఖ్య నిబంధనలు:
1. "నమస్కారం", "స్వాగతం", "ముందుగా ప్రధాన అంశాలు" వంటి యాంకర్ పరిచయ వచనాలను శీర్షిక (title) మరియు సారాంశం (summary) నుంచి ఖచ్చితంగా తొలగించండి.
2. ASR పొరపాట్లను (ఉదా: పవన్ కల్యం -> పవన్ కళ్యాణ్, దరియాప్తి -> దర్యాప్తు) నిఘంటువు ప్రకారం సరిచేసి, స్పష్టమైన టీవీ వార్తా శీర్షిక (3-5 పదాలు) రాయండి.
3. నివేదికలోని అసలు వార్తా విషయాన్నే శీర్షికగా పెట్టండి."""


def call_ollama(prompt: str) -> Optional[str]:
    """Pass 1: Send prompt to local Ollama instance (Qwen 2.5 7B)."""
    payload = {
        "model": OLLAMA_MODEL,
        "system": SYSTEM_NEWSROOM_PROMPT,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0.1,
            "top_p": 0.9,
            "num_predict": 2048,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        print(f"[Editorial LLM] Querying local Ollama model '{OLLAMA_MODEL}'...", file=sys.stderr)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            resp_text = data.get("response", "") or ""
            think_text = data.get("thinking", "") or ""
            combined = f"{resp_text}\n{think_text}".strip()
            return combined if combined else None
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        print(f"[Warning] Local Ollama call failed: {err}", file=sys.stderr)
        return None


def generate_batch_prompt(clips: List[Dict[str, Any]], full_bulletin_context: str) -> str:
    """Build batch prompt for newsroom headlines."""
    clips_input = []
    for c in clips:
        clips_input.append(
            f"CLIP ID: {c.get('id', '')}\n"
            f"RAW TRANSCRIPT: {c.get('transcript', '')}"
        )
    formatted_clips = "\n---\n".join(clips_input)

    return f"""మొత్తం బులెటిన్ నేపధ్యం:
{full_bulletin_context[:1000]}

క్రింది క్లిప్‌లకు శీర్షికలు (3-5 పదాలు), సారాంశాలు తయారు చేయండి:

{formatted_clips}

OUTPUT FORMAT (JSON ONLY):
{{
  "clips": [
    {{
      "id": "clip-id",
      "topic": "General News",
      "subtopic": "News update",
      "title": "<3-5 పదాల శుద్ధ తెలుగు వార్తా శీర్షిక>",
      "summary": "<1-2 వాక్యాల వార్తా సారాంశం>",
      "clean_transcript": "<సవరించిన పూర్తి వాక్యం>"
    }}
  ]
}}"""


def smart_rule_fallback(clip: Dict[str, Any]) -> Dict[str, Any]:
    """Smart rule-based fallback when LLMs fail."""
    text = clip.get("transcript", "").strip()
    # Purge repetitive ASR hallucination loops (e.g. "చిించిించిి...")
    text = re.sub(r"(.{2,12})\1{3,}", r"\1", text)
    # Strip anchor fluff and incomplete starting fragments
    cleaned_text = re.sub(
        r"^(నమస్కారం|స్వాగతం|ఘంటారావానికి|బిగ్ న్యూస్|హెడ్‌లైన్స్|ముందుగా ప్రధాన అంశాలు|ఈనాటి ప్రధాన వార్తలు|అనే|మరియు|ఈ విధంగా|అయితే)[^.!?]*[.!?\s]*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not cleaned_text or len(cleaned_text) < 4:
        cleaned_text = text

    words = [w for w in re.findall(r"\S+", cleaned_text) if len(w) > 2 and w not in ["అనే", "ముగ్గురి", "గురించి", "మరియు"]]
    title = " ".join(words[:4]) if words else "ముఖ్యమైన వార్తా విశేషాలు"
    # Deduplicate repeating words in title
    title = re.sub(r"\b(\w+)\s+\1\b", r"\1", title, flags=re.IGNORECASE)
    
    return {
        "id": clip.get("id", "clip-0001"),
        "topic": "General News",
        "subtopic": "News update",
        "title": title,
        "summary": cleaned_text[:200] if cleaned_text else "వార్తా విశేషాలు",
        "transcript": cleaned_text if cleaned_text else text,
        "importance": 0.75,
        "hook": 0.75,
        "self_contained": 0.80,
        "reason": "Rule-based fallback",
        "named_entities": [],
    }


def process_clips(clips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process clips using Two-Pass Architecture (Gemini Cloud API -> Local Ollama fallback)."""
    if not clips:
        return []

    full_bulletin_context = "\n".join([c.get("transcript", "") for c in clips])
    results_map: Dict[str, Dict[str, Any]] = {}

    for i in range(0, len(clips), BATCH_SIZE):
        batch = clips[i : i + BATCH_SIZE]
        prompt = generate_batch_prompt(batch, full_bulletin_context)

        # Pass 1: Try Gemini API first if key provided
        llm_response = call_gemini_api(prompt)

        # Pass 2: Fallback to local Qwen 2.5 7B if Gemini key missing or unreachable
        if not llm_response:
            llm_response = call_ollama(prompt)

        parsed = _clean_json_response(llm_response) if llm_response else None

        if parsed and "clips" in parsed and isinstance(parsed["clips"], list):
            res_clips = parsed["clips"]
            for idx, clip in enumerate(batch):
                cid = clip.get("id", "")
                matching_item = None
                for item in res_clips:
                    if isinstance(item, dict):
                        item_id = str(item.get("id", "")).strip()
                        if item_id == cid or item_id.replace("clip-", "").replace("clip_", "").lstrip("0") == cid.replace("clip-", "").replace("clip_", "").lstrip("0"):
                            matching_item = item
                            break
                if not matching_item and idx < len(res_clips) and isinstance(res_clips[idx], dict):
                    matching_item = res_clips[idx]

                if matching_item:
                    matching_item["id"] = cid
                    t = str(matching_item.get("title", ""))
                    t = re.sub(r"^(నమస్కారం|స్వాగతం|ఘంటారావానికి|ముందుగా|హెడ్‌లైన్స్|బులెటిన్|బిగ్ న్యూస్|అనే)\s*", "", t).strip()
                    matching_item["title"] = t if t else "ముఖ్యమైన వార్తా విశేషం"
                    if "clean_transcript" in matching_item and matching_item["clean_transcript"]:
                        matching_item["transcript"] = matching_item["clean_transcript"]
                    else:
                        matching_item["transcript"] = matching_item.get("summary", "")
                    results_map[cid] = matching_item

        for clip in batch:
            cid = clip.get("id", "")
            if cid not in results_map:
                results_map[cid] = smart_rule_fallback(clip)

    final_list = []
    for clip in clips:
        cid = clip.get("id", "")
        final_list.append(results_map.get(cid, smart_rule_fallback(clip)))

    return final_list


def main() -> None:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        payload = json.loads(raw)
        clips = payload.get("clips", [])
        if not isinstance(clips, list):
            print("Invalid request: clips must be a list", file=sys.stderr)
            sys.exit(1)

        enriched_clips = process_clips(clips)
        print(json.dumps({"clips": enriched_clips}, ensure_ascii=False, indent=2))
    except Exception as error:
        print(f"Editorial Adapter Error: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
