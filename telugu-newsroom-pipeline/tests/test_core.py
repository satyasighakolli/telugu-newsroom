from __future__ import annotations

import unittest
from pathlib import Path

from telugu_newsroom.models import (
    CandidateClip,
    OverlaySpec,
    RenderSpec,
    Shot,
    TimeRange,
    TranscriptSegment,
)
from telugu_newsroom.rendering import build_render_command
from telugu_newsroom.scoring import score_clip
from telugu_newsroom.segmentation import annotate_clip_overlaps, semantic_novelty
from telugu_newsroom.transcript import seconds_to_srt


class CoreTests(unittest.TestCase):
    def test_time_overlap(self) -> None:
        self.assertEqual(TimeRange(10, 20).overlaps(TimeRange(15, 25)), 5)
        self.assertEqual(TimeRange(10, 20).overlaps(TimeRange(20, 25)), 0)

    def test_srt_timestamp(self) -> None:
        self.assertEqual(seconds_to_srt(3661.234), "01:01:01,234")

    def test_telugu_semantic_novelty(self) -> None:
        same = semantic_novelty("ప్రభుత్వ నిర్ణయం", "ప్రభుత్వ కొత్త నిర్ణయం")
        changed = semantic_novelty("ప్రభుత్వ నిర్ణయం", "వైద్య ఆరోగ్య సూచనలు")
        self.assertLess(same, changed)

    def test_clip_overlap_badges_are_not_speech_overlap(self) -> None:
        first = self._clip("a", 0, 30)
        second = self._clip("b", 25, 45)
        third = self._clip("c", 45, 60)
        annotate_clip_overlaps([first, second, third])
        self.assertEqual(first.overlap_clip_ids, ["b"])
        self.assertEqual(second.overlap_clip_ids, ["a"])
        self.assertEqual(third.overlap_clip_ids, [])

    def test_score_penalizes_overlapping_speech(self) -> None:
        segment = TranscriptSegment(
            id="s1", start=0, end=30, text="ప్రభుత్వ నిర్ణయం పై పూర్తి వివరణ", speaker="A", confidence=0.95
        )
        clean = self._clip("clean", 0, 30)
        clean.evidence_ids = ["s1"]
        noisy = self._clip("noisy", 0, 30)
        noisy.evidence_ids = ["s1"]
        noisy.speech_overlap_count = 2
        shots = [Shot("shot", 0, 30)]
        self.assertGreater(
            score_clip(clean, [segment], shots).final_score,
            score_clip(noisy, [segment], shots).final_score,
        )

    def test_render_command_supports_multisegment_vertical_fill(self) -> None:
        clips = [self._clip("a", 1, 21), self._clip("b", 40, 55)]
        spec = RenderSpec(
            clip_ids=["a", "b"],
            aspect_ratio="9:16",
            crop_mode="fill",
            burn_subtitles=True,
            overlay=OverlaySpec(text="తెలుగు హెడ్‌లైన్"),
            output_name="story.mp4",
        )
        command = build_render_command(
            Path("source.mp4"),
            clips,
            spec,
            Path("story.mp4"),
            Path("overlay.txt"),
            Path("subs.srt"),
            ffmpeg_path="ffmpeg",
        )
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("crop=1080:1920", graph)
        self.assertIn("concat=n=2:v=1:a=1", graph)
        self.assertIn("subtitles=", graph)
        self.assertIn("drawtext=", graph)
        self.assertIn("loudnorm=I=-14.0", graph)

    @staticmethod
    def _clip(identifier: str, start: float, end: float) -> CandidateClip:
        return CandidateClip(
            id=identifier,
            start=start,
            end=end,
            title="Title",
            summary="Summary",
            transcript="ప్రభుత్వ నిర్ణయం పై పూర్తి వివరణ",
            speakers=["A"],
        )


if __name__ == "__main__":
    unittest.main()

