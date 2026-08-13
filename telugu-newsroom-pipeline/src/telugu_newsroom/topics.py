from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List, Sequence, Tuple

from .models import CandidateClip
from .providers import EditorialEnrichment

try:
    from indicnlp.normalize.indic_normalize import IndicNormalizerFactory
    _INDIC_NORMALIZER = IndicNormalizerFactory().get_normalizer("te")
except Exception:
    _INDIC_NORMALIZER = None


TOPIC_TERMS: Dict[str, Sequence[str]] = {
    "Politics & Government": (
        "మంత్రి", "ముఖ్యమంత్రి", "ప్రభుత్వం", "ఎన్నిక", "బిజెపి", "బీజేపీ",
        "కాంగ్రెస్", "జనసేన", "assembly", "minister", "government", "election", "party",
    ),
    "Crime & Law": (
        "పోలీసు", "కేసు", "అరెస్ట్", "కోర్టు", "నేరం", "ఉగ్రవాదం", "దాడి", "police", "case", "court", "arrest",
    ),
    "Health": (
        "ఆరోగ్యం", "వైద్య", "ఆసుపత్రి", "వ్యాధి", "health", "hospital", "doctor", "medical",
    ),
    "Economy": (
        "ధర", "రూపాయి", "బడ్జెట్", "ఉద్యోగ", "వ్యాపార", "price", "budget", "economy", "jobs",
    ),
    "Weather & Disaster": (
        "వర్షం", "వరద", "తుఫాను", "వాతావరణం", "రుతుపవనాలు", "rain", "flood", "cyclone", "weather",
    ),
    "Sports": ("క్రికెట్", "మ్యాచ్", "ఆట", "cricket", "match", "sports"),
    "Entertainment": ("సినిమా", "నటుడు", "నటి", "విడాకులు", "film", "actor", "cinema"),
}

STOPWORDS = {
    "అని", "మరియు", "కూడా", "ఇది", "ఆ", "ఈ", "ఒక", "ఉంది", "చేశారు", "the", "and", "for", "with",
    "నమస్కారం", "స్వాగతం", "ఘంటారావానికి", "ముందుగా", "ప్రధాన", "అంశాలు", "హలో", "వ్యూయర్స్",
}

TELUGU_SPELLING_MAP = {
    "పహల్లా": "పహల్గామ్",
    "ముగ్గుదాడి": "ముష్కర దాడి",
    "దరియాప్పులో": "దర్యాప్తులో",
    "సంచరణ": "సంచలన",
    "విషయాల్": "విషయాలు",
    "తలేంగాణ": "తెలంగాణ",
    "పవన కల్యాన": "పవన్ కళ్యాణ్",
    "పవన్నా": "పవన్ కళ్యాణ్",
    "చెందరపాబు": "చంద్రబాబు",
    "కల్నా": "కన్నా",
    "ఇసాయారపై": "అంశాలపై",
    "ఎసాయారపై": "ఎస్ఐఆర్‌పై",
    "జంతియవాదాని": "జాతీయవాదాన్ని",
    "ప్రాంతియత": "ప్రాంతీయత",
    "నయిరుతీ": "నైరుతి",
    "ఇరుతుపవనాలు": "రుతుపవనాలు",
    "వాతావరణ స్స్స్కూ": "వాతావరణ శాఖ",
    "భానడి": "భారీగా",
    "హాస్": "హాని",
    "దసాప్దాలబేదరింప్లకు": "దశాబ్దాల బెదిరింపులకు",
    "సలమగితం": "సవాలుగా",
    "పోట్లు": "పోటీ",
    "ఆముసేలు": "అంశాలు",
    "దసాప్దాలు": "దశాబ్దాలు",
    "ఘంటా రావాని": "ఘంటారావానికి",
    "సంస్తలతు": "సంస్థలతో",
    "హామాస్": "హమాస్",
    "ప్రమైయం": "ప్రమేయం",
    "విచారణా": "విచారణ",
}


def normalize_telugu_text(text: str) -> str:
    """Normalize common ASR phonetic misspellings into standard Telugu using IndicNLP."""
    if not text:
        return text
    if _INDIC_NORMALIZER:
        try:
            text = _INDIC_NORMALIZER.normalize(text)
        except Exception:
            pass
    for wrong, right in TELUGU_SPELLING_MAP.items():
        text = text.replace(wrong, right)
    return text


def strip_anchor_greetings(text: str) -> str:
    """Remove standard news anchor introductory greetings."""
    text = re.sub(r"^నమస్కారం\s*", "", text)
    text = re.sub(r"^ఘంటారావానికి\s+స్వాగతం\s*", "", text)
    text = re.sub(r"^ముందుగా\s+ప్రధాన\s+అంశాలు\s*", "", text)
    text = re.sub(r"^ఈనాటి\s+ముఖ్యాంశాలు\s*", "", text)
    return text.strip()


def _tokens(text: str) -> List[str]:
    return re.findall(r"[\w\u0C00-\u0C7F]+", text.casefold(), flags=re.UNICODE)


def heuristic_topic(text: str) -> Tuple[str, str]:
    tokens = _tokens(text)
    counts = Counter(tokens)
    normalized_text = text.casefold()
    best_topic = "General News"
    best_hits = 0
    for topic, terms in TOPIC_TERMS.items():
        hits = sum(normalized_text.count(term.casefold()) for term in terms)
        if hits > best_hits:
            best_topic, best_hits = topic, hits
    keywords = [token for token, _ in counts.most_common() if len(token) > 2 and token not in STOPWORDS]
    subtopic = " · ".join(keywords[:3]) if keywords else "News update"
    return best_topic, subtopic


def heuristic_title(text: str, limit: int = 5) -> str:
    """Generate a clean, punchy 3-5 word TV news lower-third headline."""
    cleaned_text = strip_anchor_greetings(normalize_telugu_text(text))
    words = [w for w in re.findall(r"\S+", cleaned_text) if w not in STOPWORDS]

    if not words:
        words = re.findall(r"\S+", normalize_telugu_text(text))

    if not words:
        return "ముఖ్య వార్త"

    title = " ".join(words[:limit])
    title = re.sub(r"ముఖ్యమంత్రి\s+నారా\s+చంద్రబాబు\s+నాయుడు", "సీఎం చంద్రబాబు", title)
    title = re.sub(r"ముఖ్యమంత్రి", "సీఎం", title)
    return title


def heuristic_summary(text: str, max_chars: int = 250) -> str:
    """Generate an extractive, normalized Telugu news summary."""
    cleaned_text = strip_anchor_greetings(normalize_telugu_text(text))
    sentences = [s.strip() for s in re.split(r"[.!?।]\s*", cleaned_text) if len(s.strip()) > 10]
    if sentences:
        summary = " ".join(sentences[:2])
        if len(summary) <= max_chars:
            return summary
        return summary[: max_chars - 1] + "…"
    return cleaned_text[:max_chars] + ("…" if len(cleaned_text) > max_chars else "")


def apply_enrichment(
    clips: Iterable[CandidateClip],
    enrichment: Dict[str, EditorialEnrichment],
) -> None:
    for clip in clips:
        fallback_topic, fallback_subtopic = heuristic_topic(clip.transcript)
        item = enrichment.get(clip.id)
        clip.topic = item.topic if item and item.topic else fallback_topic
        clip.subtopic = item.subtopic if item and item.subtopic else fallback_subtopic
        clip.title = item.title if item and item.title else heuristic_title(clip.transcript)
        clip.summary = item.summary if item and item.summary else heuristic_summary(clip.transcript)
        if item and item.clean_transcript:
            clip.transcript = item.clean_transcript
        else:
            clip.transcript = normalize_telugu_text(clip.transcript)
