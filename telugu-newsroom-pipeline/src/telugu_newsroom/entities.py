from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

from .models import CandidateClip, EntityMention, TranscriptDocument


@dataclass
class EntityDefinition:
    id: str
    canonical_name: str
    aliases: List[str]
    kind: str = "personality"
    metadata: Dict[str, str] = field(default_factory=dict)


def _contains_alias(text: str, alias: str) -> bool:
    normalized_text = re.sub(r"\s+", " ", text.casefold()).strip()
    normalized_alias = re.sub(r"\s+", " ", alias.casefold()).strip()
    return bool(normalized_alias and normalized_alias in normalized_text)


def extract_mentions(
    transcript: TranscriptDocument,
    clips: Sequence[CandidateClip],
    entities: Iterable[EntityDefinition],
) -> List[EntityMention]:
    mentions: List[EntityMention] = []
    for segment in transcript.segments:
        clip_ids = [clip.id for clip in clips if clip.end > segment.start and clip.start < segment.end]
        for entity in entities:
            for alias in [entity.canonical_name] + entity.aliases:
                if _contains_alias(segment.text, alias):
                    mentions.append(
                        EntityMention(
                            entity_id=entity.id,
                            canonical_name=entity.canonical_name,
                            alias=alias,
                            start=segment.start,
                            end=segment.end,
                            segment_id=segment.id,
                            clip_ids=clip_ids,
                        )
                    )
                    break
    return mentions


def entity_pages(
    mentions: Sequence[EntityMention],
    clips: Sequence[CandidateClip],
) -> List[Dict[str, object]]:
    by_entity: Dict[str, List[EntityMention]] = defaultdict(list)
    for mention in mentions:
        by_entity[mention.entity_id].append(mention)
    clip_by_id = {clip.id: clip for clip in clips}
    pages: List[Dict[str, object]] = []
    for entity_id, grouped in by_entity.items():
        clip_ids = sorted({clip_id for mention in grouped for clip_id in mention.clip_ids})
        developing = [
            {
                "clip_id": clip_id,
                "title": clip_by_id[clip_id].title,
                "topic": clip_by_id[clip_id].topic,
                "score": clip_by_id[clip_id].score.final_score if clip_by_id[clip_id].score else None,
            }
            for clip_id in clip_ids
            if clip_id in clip_by_id
        ]
        pages.append(
            {
                "entity_id": entity_id,
                "canonical_name": grouped[0].canonical_name,
                "mention_count": len(grouped),
                "first_seen_seconds": min(item.start for item in grouped),
                "last_seen_seconds": max(item.end for item in grouped),
                "aliases_seen": sorted({item.alias for item in grouped}),
                "developing_stories": developing,
            }
        )
    return pages

