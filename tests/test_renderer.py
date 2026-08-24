"""Dependency-free Renderer domain and FFmpeg translation tests."""
import copy
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from travel_reel.config import RendererConfig
from travel_reel.renderer import (
    RendererFFmpegError, RendererPrerequisiteError, RendererSourceError,
    RendererValidationError, build_photo_command, build_video_command,
    normalization_filter, probe_render_output, probe_source_duration, render_reel, resolve_shot_source,
    validate_render_output, validate_render_plan,
)


def planned_manifest(source_path="Photos/a.jpg", media_type="photo"):
    duration = 2.0
    shot = {
        "shot_id": "shot-001", "shot_index": 1, "media_id": f"{media_type}-a",
        "media_type": media_type, "source_path": source_path,
        "timeline_start_seconds": 0.0, "timeline_end_seconds": duration,
        "planned_duration_seconds": duration, "source_trim_start_seconds": 1.0 if media_type == "video" else None,
        "source_trim_end_seconds": 3.0 if media_type == "video" else None,
        "transition_intent": "cut",
    }
    item = {"id": shot["media_id"], "path": source_path}
    return {
        "manifest_version": "1.4", "trip": {},
        "photos": [item] if media_type == "photo" else [],
        "videos": [item] if media_type == "video" else [],
        "reel_plan": {"aspect_ratio": "9:16", "actual_duration_seconds": duration, "shots": [shot]},
        "story": {"keep": True}, "selection": {"keep": True}, "render": {"old": True},
    }


class RendererTests(unittest.TestCase):
    def test_missing_plan_prerequisite(self):
        with self.assertRaisesRegex(RendererPrerequisiteError, "Run 'plan' first"):
            validate_render_plan({}, RendererConfig())

    def test_source_resolution_and_traversal_missing_derived_rejection(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "Photos").mkdir(); (root / "Photos/a.jpg").write_bytes(b"image")
            manifest = planned_manifest()
            self.assertEqual(resolve_shot_source(root, manifest, manifest["reel_plan"]["shots"][0]), (root / "Photos/a.jpg").resolve())
            escaped = planned_manifest("../outside.jpg")
            with self.assertRaisesRegex(RendererSourceError, "escapes"):
                resolve_shot_source(root, escaped, escaped["reel_plan"]["shots"][0])
            missing = planned_manifest("Photos/missing.jpg")
            with self.assertRaisesRegex(RendererSourceError, "missing"):
                resolve_shot_source(root, missing, missing["reel_plan"]["shots"][0])
            derived = planned_manifest("output/a.jpg"); (root / "output").mkdir(); (root / "output/a.jpg").write_bytes(b"x")
            with self.assertRaisesRegex(RendererSourceError, "Derived"):
                resolve_shot_source(root, derived, derived["reel_plan"]["shots"][0])

    def test_photo_command_is_fit_pad_not_stretch_or_crop(self):
        config = RendererConfig()
        command = [str(value) for value in build_photo_command("ffmpeg", Path("wide.jpg"), Path("out.mp4"), 60, config)]
        filters = command[command.index("-vf") + 1]
        self.assertIn("force_original_aspect_ratio=decrease", filters)
        self.assertIn("pad=1080:1920", filters)
        self.assertNotIn("crop=", filters)
        self.assertIn("-loop", command); self.assertIn("-frames:v", command); self.assertIn("-an", command)

    def test_video_command_honors_planner_trim_and_normalizes(self):
        config = RendererConfig(); shot = planned_manifest("Videos/a.mov", "video")["reel_plan"]["shots"][0]
        command = [str(value) for value in build_video_command("ffmpeg", Path("a.mov"), Path("out.mp4"), shot, 60, config)]
        self.assertEqual(command[command.index("-ss") + 1], "1.000")
        self.assertIn(normalization_filter(config), command)
        self.assertIn("-an", command); self.assertEqual(command[command.index("-frames:v") + 1], "60")

    def test_unsupported_transition_fails(self):
        manifest = planned_manifest(); manifest["reel_plan"]["shots"][0]["transition_intent"] = "crossfade"
        with self.assertRaisesRegex(RendererValidationError, "Unsupported transition"):
            validate_render_plan(manifest["reel_plan"], RendererConfig())

    def test_probe_and_frame_aware_validation(self):
        payload = {"streams": [{"codec_name": "h264", "width": 1080, "height": 1920,
                                "pix_fmt": "yuv420p", "avg_frame_rate": "30/1"}],
                   "format": {"duration": "2.033"}}
        runner = lambda _command: subprocess.CompletedProcess([], 0, json.dumps(payload), "")
        probe = probe_render_output(Path("out.mp4"), runner=runner)
        with TemporaryDirectory() as directory:
            output = Path(directory) / "out.mp4"; output.write_bytes(b"valid")
            validate_render_output(output, probe, planned_manifest()["reel_plan"], RendererConfig(), 1)
            bad = copy.deepcopy(probe); bad["duration_seconds"] = 2.1
            with self.assertRaisesRegex(RendererValidationError, "tolerance"):
                validate_render_output(output, bad, planned_manifest()["reel_plan"], RendererConfig(), 1)

    def test_source_duration_preflight(self):
        runner = lambda _command: subprocess.CompletedProcess([], 0, '{"format":{"duration":"4.5"}}', "")
        self.assertEqual(probe_source_duration(Path("clip.mov"), runner=runner), 4.5)
        bad = lambda _command: subprocess.CompletedProcess([], 0, '{"format":{}}', "")
        with self.assertRaisesRegex(RendererSourceError, "unavailable"):
            probe_source_duration(Path("clip.mov"), runner=bad)

    def test_ffmpeg_failure_preserves_existing_final_output(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "Photos").mkdir(); (root / "output").mkdir()
            (root / "Photos/a.jpg").write_bytes(b"image")
            final = root / "output/reel.mp4"; final.write_bytes(b"existing-valid")
            def fail(_command): return subprocess.CompletedProcess([], 1, "", "encoder failed")
            with patch("travel_reel.renderer._find_tool", return_value="tool"):
                with self.assertRaisesRegex(RendererFFmpegError, "shot-001"):
                    render_reel(root, planned_manifest(), RendererConfig(), runner=fail)
            self.assertEqual(final.read_bytes(), b"existing-valid")

    def test_config_validation(self):
        invalid = ({"width": 0}, {"width": 1000}, {"fps": 0}, {"output_filename": "../x.mp4"},
                   {"output_filename": "x.avi"}, {"temp_directory_name": "a/b"}, {"crf": 60},
                   {"background_mode": "blur"}, {"photo_motion": "zoom"}, {"keep_temp": "false"})
        for kwargs in invalid:
            with self.assertRaises(ValueError, msg=str(kwargs)): RendererConfig(**kwargs)


if __name__ == "__main__":
    unittest.main()
