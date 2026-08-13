from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence, Set

from .models import CandidateClip, FaithfulnessResult, PlatformCopy, PublishDraft


PLATFORM_LIMITS = {
    "facebook": 5000,
    "instagram": 2200,
    "x": 280,
    "youtube": 5000,
    "telegram": 4096,
}


def _tokens(text: str) -> Set[str]:
    return {
        token
        for token in re.findall(r"[\w\u0C00-\u0C7F]+", text.casefold(), flags=re.UNICODE)
        if len(token) > 2
    }


def check_faithfulness(copy: str, source_texts: Iterable[str]) -> FaithfulnessResult:
    source_tokens = _tokens(" ".join(source_texts))
    copy_tokens = _tokens(copy)
    if not copy_tokens:
        return FaithfulnessResult(score=0.0, status="empty", notes=["Draft contains no text."])
    unsupported = sorted(copy_tokens - source_tokens)
    support = 1.0 - len(unsupported) / max(1, len(copy_tokens))
    status = "pass" if support >= 0.82 else "review" if support >= 0.62 else "hold"
    notes = [
        "Lexical support is a fast pre-check, not a factual entailment decision.",
        "An editor must review names, numbers, quotations, and allegations against the source.",
    ]
    return FaithfulnessResult(
        score=round(support, 3),
        status=status,
        unsupported_terms=unsupported[:30],
        notes=notes,
    )


def _platform_body(headline: str, body: str, platform: str) -> str:
    combined = f"{headline}\n\n{body}".strip()
    limit = PLATFORM_LIMITS[platform]
    if len(combined) <= limit:
        return combined
    return combined[: max(0, limit - 1)].rstrip() + "…"


def build_publish_draft(
    clip: CandidateClip,
    platforms: Sequence[str] = ("facebook", "instagram", "x", "youtube", "telegram"),
) -> PublishDraft:
    headline = clip.title
    body = clip.summary or clip.transcript
    copies: Dict[str, PlatformCopy] = {}
    for platform in platforms:
        copies[platform] = PlatformCopy(
            platform=platform,
            headline=headline,
            body=_platform_body(headline, body, platform),
        )
    faithfulness = check_faithfulness(f"{headline} {body}", [clip.transcript])
    return PublishDraft(
        clip_id=clip.id,
        master_headline=headline,
        master_body=body,
        platforms=copies,
        faithfulness=faithfulness,
    )

