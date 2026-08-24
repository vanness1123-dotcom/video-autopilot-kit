"""Sprint 4 manifest persistence and CLI prerequisite tests."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from travel_reel.cli import build_parser, main
from travel_reel.config import ScoringConfig, SelectionConfig
from travel_reel.pipeline import run_analysis, run_scoring, run_selection
from travel_reel.vision import normalize_vision_result
from test_vision import valid_payload


class SelectionPipelineTests(unittest.TestCase):
    def test_score_select_preserve_manifest_state_and_media_ids(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "Photos").mkdir()
            for name, size in (("portrait.jpg", (800, 1200)), ("landscape.jpg", (1200, 800))):
                Image.new("RGB", size, "green").save(root / "Photos" / name)
            run_analysis(root)
            path = root / "output" / "trip_manifest.json"
            payload = json.loads(path.read_text())
            ids = [item["id"] for item in payload["photos"]]
            for item in payload["photos"]:
                vision = normalize_vision_result(valid_payload()).to_dict()
                vision["vision_metadata"] = {}
                item["vision"] = vision
            payload["story"] = {"preserve": True}; payload["timeline"] = {"future": 1}; payload["render"] = {"future": 2}
            path.write_text(json.dumps(payload))
            scored = run_scoring(root, ScoringConfig())
            selected = run_selection(root, SelectionConfig(primary_target=1, alternate_target=1, min_video_target=0, max_video_target=0))
            persisted = json.loads(path.read_text())
            self.assertEqual(scored["scored"], 2)
            self.assertEqual(len(selected["primary_ids"]), 1)
            self.assertEqual([item["id"] for item in persisted["photos"]], ids)
            self.assertEqual(persisted["manifest_version"], "1.2")
            self.assertEqual(persisted["story"], {"preserve": True})
            self.assertEqual(persisted["timeline"], {"future": 1})
            self.assertEqual(persisted["render"], {"future": 2})
            self.assertTrue(all("vision" in item and "score" in item and "selection" in item for item in persisted["photos"]))

    def test_cli_help_and_missing_prerequisites(self):
        help_text = build_parser().format_help()
        self.assertIn("score", help_text); self.assertIn("select", help_text)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["score", str(root)]), 2)
            (root / "output").mkdir()
            (root / "output" / "trip_manifest.json").write_text(json.dumps({"manifest_version": "1.1", "trip": {}, "photos": [], "videos": []}))
            self.assertEqual(main(["select", str(root)]), 2)


if __name__ == "__main__":
    unittest.main()
