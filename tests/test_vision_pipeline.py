"""Vision pipeline persistence, cache, and isolation tests."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from travel_reel.config import VisionConfig
from travel_reel.pipeline import run_analysis, run_vision
from travel_reel.vision import VisionError, normalize_vision_result
from test_vision import valid_payload


class FakeProvider:
    name = "fake-local"
    model = "fake-v1"

    def __init__(self, fail_suffix: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_suffix = fail_suffix

    def analyze_photo(self, media_id: str, _image: Path):
        self.calls.append(media_id)
        if self.fail_suffix and media_id.endswith(self.fail_suffix):
            raise VisionError("isolated failure")
        return normalize_vision_result(valid_payload())

    def analyze_video(self, media_id: str, _frames: list[Path], _timestamps: list[float]):
        self.calls.append(media_id)
        return normalize_vision_result(valid_payload())


class VisionPipelineTests(unittest.TestCase):
    def test_enrichment_cache_invalidation_and_state_preservation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Photos").mkdir()
            photo = root / "Photos" / "one.jpg"
            Image.new("RGB", (900, 600), "green").save(photo)
            run_analysis(root)
            manifest_path = root / "output" / "trip_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            original_id = manifest["photos"][0]["id"]
            manifest["photos"][0]["score"] = {"stale": True}
            manifest.update(events={"stale": True}, creative_direction={"stale": True},
                            selection={"stale": True}, story={"stale": True},
                            reel_plan={"stale": True}, render={"stale": True},
                            timeline={"unrelated": True})
            manifest_path.write_text(json.dumps(manifest))

            provider = FakeProvider()
            config = replace(VisionConfig(), cache_dir_name=".travel_reel_cache/test")
            first = run_vision(root, config, provider)
            self.assertEqual(first["processed"], 1)
            persisted = json.loads(manifest_path.read_text())
            self.assertEqual(persisted["manifest_version"], "1.1")
            self.assertEqual(persisted["photos"][0]["id"], original_id)
            self.assertNotIn("score", persisted["photos"][0])
            for key in ("events", "creative_direction", "selection", "story", "reel_plan", "render"):
                self.assertNotIn(key, persisted)
            self.assertEqual(persisted["timeline"], {"unrelated": True})
            self.assertIn("vision", persisted["photos"][0])

            second = run_vision(root, config, provider)
            self.assertEqual(second["skipped"], 1)
            self.assertEqual(len(provider.calls), 1)

            Image.new("RGB", (900, 600), "purple").save(photo)
            third = run_vision(root, config, provider)
            self.assertEqual(third["processed"], 1)
            self.assertEqual(len(provider.calls), 2)

    def test_one_failure_does_not_erase_success(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Photos").mkdir()
            Image.new("RGB", (100, 100), "red").save(root / "Photos" / "a.jpg")
            Image.new("RGB", (100, 100), "blue").save(root / "Photos" / "b.jpg")
            run_analysis(root)
            manifest_path = root / "output" / "trip_manifest.json"
            manifest = json.loads(manifest_path.read_text())
            failing_id = manifest["photos"][1]["id"]
            provider = FakeProvider(fail_suffix=failing_id[-8:])
            summary = run_vision(root, VisionConfig(), provider)
            self.assertEqual(summary["processed"], 1)
            self.assertEqual(summary["failed"], 1)
            persisted = json.loads(manifest_path.read_text())
            self.assertIn("vision", persisted["photos"][0])
            self.assertIn("vision_error", persisted["photos"][1])

            recovery = FakeProvider()
            progress: list[str] = []
            retried = run_vision(root, VisionConfig(), recovery, progress.append)
            self.assertEqual(retried["total"], 2)
            self.assertEqual(retried["cached"], 1)
            self.assertEqual(retried["skipped"], 1)
            self.assertEqual(retried["retried"], 1)
            self.assertEqual(retried["retry_processed"], 1)
            self.assertEqual(retried["processed"], 1)
            self.assertEqual(retried["recovered"], 1)
            self.assertEqual(retried["failed"], 0)
            self.assertEqual(recovery.calls, [failing_id])
            self.assertTrue(progress[0].startswith("[1/2]"))
            self.assertIn("cached=1", progress[0])
            recovered_manifest = json.loads(manifest_path.read_text())
            self.assertIn("vision", recovered_manifest["photos"][1])
            self.assertNotIn("vision_error", recovered_manifest["photos"][1])


if __name__ == "__main__":
    unittest.main()
