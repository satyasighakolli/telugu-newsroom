from __future__ import annotations

import json
import unittest
from pathlib import Path
from telugu_newsroom.providers import CommandEditorialProvider, CommandSpeechProvider
from telugu_newsroom.topics import heuristic_summary, heuristic_title


class InHouseAdaptersTests(unittest.TestCase):
    def test_native_telugu_nlp_helpers(self) -> None:
        text = "ముఖ్యమంత్రి నారా చంద్రబాబు నాయుడు ఈరోజు అమరావతిలో ఉన్నతస్థాయి సమీక్ష నిర్వహించారు. ప్రాజెక్టుల పురోగతిపై వివరాలు అడిగి తెలుసుకున్నారు."
        title = heuristic_title(text)
        summary = heuristic_summary(text)
        self.assertTrue(len(title) > 0)
        self.assertIn("చంద్రబాబు", title)
        self.assertTrue(len(summary) > 0)
        self.assertIn("అమరావతిలో", summary)

    def test_local_llm_editorial_provider_contract(self) -> None:
        script = Path(__file__).resolve().parents[1] / "adapters" / "local_llm_editorial.py"
        provider = CommandEditorialProvider.from_string(f"python3 {script}")
        dummy_clips = [
            type(
                "DummyClip",
                (),
                {
                    "id": "clip-0001",
                    "start": 0.0,
                    "end": 20.0,
                    "transcript": "ముఖ్యమంత్రి శంకుస్థాపన చేశారు.",
                    "speakers": ["SPEAKER_01"],
                    "evidence_ids": ["seg-00001"],
                },
            )()
        ]
        dummy_doc = type(
            "DummyDoc",
            (),
            {"language": "te", "segments": []},
        )()
        enrichment = provider.enrich(dummy_clips, dummy_doc)
        self.assertIn("clip-0001", enrichment)
        item = enrichment["clip-0001"]
        self.assertTrue(len(item.title) > 0)
        self.assertTrue(len(item.summary) > 0)
        self.assertGreaterEqual(item.signals.importance, 0.0)


if __name__ == "__main__":
    unittest.main()
