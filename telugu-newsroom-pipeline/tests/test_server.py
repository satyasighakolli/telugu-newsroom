import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telugu_newsroom.models import SourceKind
from telugu_newsroom.pipeline import Pipeline
from telugu_newsroom.server import NewsroomHandler, PipelineExecutor, PipelineWorkerConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ServerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        pipeline = Pipeline(Path(self.temp.name), PROJECT_ROOT / "configs" / "default.json")
        manifest = pipeline.create_job(
            SourceKind.UPLOAD,
            "fixture://api-contract",
            "API contract demo",
            job_id="api-demo",
        )
        pipeline.import_transcript(manifest.id, PROJECT_ROOT / "fixtures" / "transcript_te.json")
        pipeline.import_shots(manifest.id, PROJECT_ROOT / "fixtures" / "shots.json")
        pipeline.analyze(manifest.id)
        executor = PipelineExecutor(pipeline, PipelineWorkerConfig())
        self.handler = object.__new__(NewsroomHandler)
        self.handler.pipeline = pipeline
        self.handler.executor = executor

    def tearDown(self):
        self.temp.cleanup()

    def test_runtime_capabilities_and_package_contract(self):
        self.assertFalse(self.handler.executor.capabilities["speech_provider_configured"])
        self.assertEqual(self.handler.executor.runtime("api-demo")["runtime"], "idle")
        self.assertEqual(self.handler._packages("api-demo"), {"packages": []})
        self.handler.path = "/api/jobs/api-demo/clips?fresh=1"
        self.assertEqual(self.handler._parts(), ("api", "jobs", "api-demo", "clips"))

    def test_deepgram_capability_requires_a_real_api_key(self):
        executor = PipelineExecutor(
            self.handler.pipeline,
            PipelineWorkerConfig(speech_command="python adapters/deepgram_speech.py"),
        )
        with mock.patch.dict("os.environ", {"DEEPGRAM_API_KEY": "replace_me"}):
            self.assertFalse(executor.capabilities["speech_provider_configured"])
        with mock.patch.dict("os.environ", {"DEEPGRAM_API_KEY": "dg-secret"}):
            self.assertTrue(executor.capabilities["speech_provider_configured"])


if __name__ == "__main__":
    unittest.main()
