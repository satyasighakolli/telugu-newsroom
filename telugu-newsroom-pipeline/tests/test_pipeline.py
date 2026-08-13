from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telugu_newsroom.models import JobStatus, SourceKind
from telugu_newsroom.pipeline import Pipeline


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PipelineIntegrationTests(unittest.TestCase):
    def test_demo_reaches_ready_with_screen_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pipeline = Pipeline(
                Path(temporary),
                PROJECT_ROOT / "configs" / "default.json",
            )
            manifest = pipeline.create_job(
                SourceKind.UPLOAD,
                "fixture://demo",
                "Demo",
                "Reporter",
                job_id="demo",
            )
            pipeline.import_transcript(
                manifest.id,
                PROJECT_ROOT / "fixtures" / "transcript_te.json",
            )
            pipeline.import_shots(
                manifest.id,
                PROJECT_ROOT / "fixtures" / "shots.json",
            )
            manifest = pipeline.analyze(manifest.id)

            self.assertEqual(manifest.status, JobStatus.READY)
            for artifact in ("clips", "timeline", "publish", "entities", "quality", "srt"):
                self.assertIn(artifact, manifest.artifacts)
                self.assertTrue(Path(manifest.artifacts[artifact]).exists())

            clips = pipeline.read_artifact(manifest.id, "clips")["clips"]
            self.assertEqual(len(clips), 4)
            topics = {clip["topic"] for clip in clips}
            self.assertEqual(
                topics,
                {"Politics & Government", "Health", "Weather & Disaster", "Economy"},
            )
            self.assertTrue(all(clip["evidence_ids"] for clip in clips))

            quality = pipeline.read_artifact(manifest.id, "quality")
            self.assertEqual(quality["status"], "review")
            self.assertEqual(quality["overlap_segment_ids"], ["seg-00007"])

            entities = pipeline.read_artifact(manifest.id, "entities")
            names = {page["canonical_name"] for page in entities["pages"]}
            self.assertIn("Nara Chandrababu Naidu", names)

            source = pipeline.job_dir(manifest.id) / "input" / "source.mp4"
            source.write_bytes(b"video")
            manifest.source_file = str(source.resolve())
            pipeline.save_manifest(manifest)

            def fake_render(_source, _clips, spec, output_dir, **_kwargs):
                path = output_dir / spec.output_name
                path.write_bytes(b"rendered-video")
                return path

            def fake_audio(_video, output_path, _ffmpeg=None):
                output_path.write_bytes(b"audio")
                return output_path

            first_clip_id = clips[0]["id"]
            with patch("telugu_newsroom.pipeline.render_clip", side_effect=fake_render), patch(
                "telugu_newsroom.pipeline.extract_audio_track", side_effect=fake_audio
            ):
                package = pipeline.package_clips(manifest.id, [first_clip_id])
            self.assertEqual(len(package["packages"]), 1)
            packaged_manifest = pipeline.load_manifest(manifest.id)
            self.assertEqual(packaged_manifest.status, JobStatus.READY)
            self.assertIn(f"package:{first_clip_id}:16x9", packaged_manifest.artifacts)
            self.assertTrue(Path(package["packages"][0]["video"]).exists())
            self.assertTrue(Path(package["packages"][0]["audio"]).exists())


if __name__ == "__main__":
    unittest.main()
