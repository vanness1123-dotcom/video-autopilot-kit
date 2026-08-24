"""Renderer persistence ownership, replacement, stable IDs, and CLI tests."""
import copy
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from travel_reel.cli import build_parser, main
from travel_reel.config import RendererConfig
from travel_reel.pipeline import run_renderer
from travel_reel.renderer import RendererPrerequisiteError
from test_renderer import planned_manifest


class RenderPipelineTests(unittest.TestCase):
    def test_manifest_upstream_preservation_and_render_replacement(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            payload = planned_manifest(); path = root / "output/trip_manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            upstream = copy.deepcopy({key: payload[key] for key in ("photos", "videos", "story", "selection", "reel_plan")})
            state = {"renderer_version": "1.0", "status": "completed", "shot_count": 1,
                     "photo_count": 1, "video_count": 0, "duration_seconds": 2.0,
                     "width": 1080, "height": 1920}
            with patch("travel_reel.pipeline.render_reel", return_value=(state, root / "output/reel.mp4")):
                returned, output = run_renderer(root, RendererConfig())
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(returned, state); self.assertEqual(output, root / "output/reel.mp4")
            self.assertEqual(persisted["manifest_version"], "1.5")
            self.assertEqual({key: persisted[key] for key in upstream}, upstream)
            self.assertEqual(persisted["render"], state)
            self.assertEqual(persisted["photos"][0]["id"], "photo-a")

    def test_failure_does_not_replace_render_state(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            payload = planned_manifest(); path = root / "output/trip_manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with patch("travel_reel.pipeline.render_reel", side_effect=RendererPrerequisiteError("failure")):
                with self.assertRaises(RendererPrerequisiteError): run_renderer(root, RendererConfig())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["render"], {"old": True})

    def test_cli_help_and_missing_plan_prerequisite(self):
        self.assertIn("render", build_parser().format_help())
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            (root / "output/trip_manifest.json").write_text(json.dumps({"trip": {}, "photos": [], "videos": []}))
            output = StringIO()
            with redirect_stdout(output): result = main(["render", str(root)])
            self.assertEqual(result, 2)
            self.assertIn("Renderer prerequisite error: Reel plan not found. Run 'plan' first.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
