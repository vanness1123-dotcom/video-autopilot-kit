"""Story persistence, ownership, provider boundary, and CLI tests."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_reel.cli import build_parser, main
from travel_reel.config import StoryConfig
from travel_reel.pipeline import run_story
from travel_reel.story import DeterministicStoryProvider, StoryError
from test_story import candidate, story_manifest


class StoryPipelineTests(unittest.TestCase):
    def test_additive_persistence_and_rerun_replace_only_story_state(self):
        primary = [
            candidate("photo-hook", "landmark", roles=["hook_candidate", "establishing"]),
            candidate("video-action", "activity", roles=["activity"]),
            candidate("photo-food", "food", roles=["food"]),
            candidate("photo-close", "cityscape", mood="calm", roles=["closing_candidate"]),
        ]
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            payload = story_manifest(primary)
            payload["story"] = {"stale": True}
            payload["reel_plan"] = {"stale": True}
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(payload))
            before_media = copy.deepcopy(payload["photos"]), copy.deepcopy(payload["videos"])
            before_selection = copy.deepcopy(payload["selection"])
            first = run_story(root, StoryConfig(min_story_items=2), DeterministicStoryProvider())
            persisted = json.loads(path.read_text())
            self.assertEqual(persisted["manifest_version"], "1.3")
            self.assertEqual((persisted["photos"], persisted["videos"]), before_media)
            self.assertEqual(persisted["selection"], before_selection)
            self.assertEqual(persisted["timeline"], {"keep": True})
            self.assertNotIn("reel_plan", persisted)
            self.assertNotIn("render", persisted)
            persisted["story"]["foreign_stale_field"] = True
            path.write_text(json.dumps(persisted))
            second = run_story(root, StoryConfig(min_story_items=2))
            self.assertEqual(first, second)
            self.assertNotIn("foreign_stale_field", json.loads(path.read_text())["story"])

    def test_cli_help_and_prerequisite_failure(self):
        self.assertIn("story", build_parser().format_help())
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            path = root / "output" / "trip_manifest.json"
            path.write_text(json.dumps({"manifest_version": "1.2", "trip": {}, "photos": [], "videos": []}))
            self.assertEqual(main(["story", str(root)]), 2)

    def test_provider_failure_does_not_destroy_existing_story(self):
        class FailingProvider:
            name = "failing"; version = "1.0"
            def build(self, _manifest, _config):
                raise StoryError("isolated provider failure")

        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            payload = story_manifest([candidate("photo-a", "landmark", roles=["hook_candidate"])])
            payload["story"] = {"preserve": True}
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(StoryError, "isolated provider failure"):
                run_story(root, StoryConfig(min_story_items=1), FailingProvider())
            self.assertEqual(json.loads(path.read_text())["story"], {"preserve": True})


if __name__ == "__main__":
    unittest.main()
