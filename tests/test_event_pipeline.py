"""Event persistence, invalidation, and CLI contract tests."""
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_reel.cli import build_parser, main
from travel_reel.config import EventConfig
from travel_reel.pipeline import run_events
from test_event_grouper import media, manifest


class EventPipelineTests(unittest.TestCase):
    def test_additive_upstream_and_downstream_invalidation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            payload = manifest([media("photo-a", "Photos/IMG_1.JPG", "landmark", words=["gothic", "church"])])
            payload.update(manifest_version="1.5", selection={"old": True}, reel_plan={"old": True}, render={"old": True})
            payload["photos"][0].update(selected=True, selection={"old": True})
            original_vision = payload["photos"][0]["vision"].copy(); original_score = payload["photos"][0]["score"].copy()
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(payload))
            first = run_events(root, EventConfig()); persisted = json.loads(path.read_text())
            self.assertEqual(persisted["manifest_version"], "1.6")
            self.assertEqual(persisted["photos"][0]["vision"], original_vision)
            self.assertEqual(persisted["photos"][0]["score"], original_score)
            self.assertTrue(all(key not in persisted for key in ("selection", "story", "reel_plan", "render")))
            self.assertNotIn("selection", persisted["photos"][0])
            second = run_events(root, EventConfig()); self.assertEqual(first, second)

    def test_cli_help_and_prerequisite(self):
        self.assertIn("events", build_parser().format_help())
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            (root / "output" / "trip_manifest.json").write_text(json.dumps({"trip": {}, "photos": [], "videos": []}))
            output = StringIO()
            with redirect_stdout(output): result = main(["events", str(root)])
            self.assertEqual(result, 2); self.assertIn("Events prerequisite error", output.getvalue())


if __name__ == "__main__": unittest.main()
