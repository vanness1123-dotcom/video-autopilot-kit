"""Sprint 6 Reel Planner domain, persistence, and CLI tests."""
import copy
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_reel.cli import build_parser, main
from travel_reel.config import PlannerConfig
from travel_reel.pipeline import run_planner
from travel_reel.planner import ReelPlanInsufficientMedia, build_reel_plan, validate_reel_plan


SECTIONS = ("hook", "arrival", "exploration", "experience", "highlight", "closing")


def fixture(count=20, videos=(0, 5, 9, 14, 18)):
    photos, video_items, sequence = [], [], []
    for index in range(count):
        kind = "video" if index in videos else "photo"
        media_id = f"{kind}-{index:02d}"
        section = SECTIONS[min(len(SECTIONS) - 1, index * len(SECTIONS) // count)]
        item = {
            "id": media_id, "path": f"Media/{media_id}.{'mov' if kind == 'video' else 'jpg'}",
            "score": {"total": 70 + index, "story_value": 65 + index},
            "selection": {"status": "primary", "candidate_roles": [section]}, "selected": True,
        }
        if kind == "video": item["duration"] = 8.0
        (video_items if kind == "video" else photos).append(item)
        sequence.append({"position": index + 1, "media_id": media_id, "scene_id": f"scene-{section}",
                         "section": section, "editorial_role": section, "reasons": ["fixture"]})
    return {"manifest_version": "1.3", "trip": {"name": "Test"}, "photos": photos, "videos": video_items,
            "story": {"story_version": "1.0", "sequence": sequence, "structure": list(dict.fromkeys(e["section"] for e in sequence))},
            "selection": {"suppressed_ids": []}, "timeline": {"keep": True}, "render": {"keep": True}}


class ReelPlannerTests(unittest.TestCase):
    def test_deterministic_exact_continuous_bounded_plan(self):
        manifest = fixture()
        config = PlannerConfig()
        first = build_reel_plan(manifest, config)
        second = build_reel_plan(copy.deepcopy(manifest), config)
        self.assertEqual(first, second)
        self.assertEqual(first["actual_duration_seconds"], 40.0)
        self.assertEqual(first["shots"][0]["timeline_start_seconds"], 0.0)
        previous = 0.0
        for shot in first["shots"]:
            self.assertEqual(shot["timeline_start_seconds"], previous)
            self.assertGreater(shot["planned_duration_seconds"], 0)
            if shot["media_type"] == "photo":
                self.assertLessEqual(config.photo_min_duration, shot["planned_duration_seconds"])
                self.assertLessEqual(shot["planned_duration_seconds"], config.photo_max_duration)
                self.assertIsNone(shot["source_trim_start_seconds"])
            else:
                self.assertLessEqual(config.video_min_duration, shot["planned_duration_seconds"])
                self.assertLessEqual(shot["planned_duration_seconds"], config.video_max_duration)
                self.assertGreaterEqual(shot["source_trim_start_seconds"], 0)
                self.assertLessEqual(shot["source_trim_end_seconds"], 8.0)
                self.assertAlmostEqual(shot["source_trim_end_seconds"] - shot["source_trim_start_seconds"], shot["planned_duration_seconds"], places=3)
            previous = shot["timeline_end_seconds"]
        validate_reel_plan(first, manifest, config)

    def test_short_video_degrades_to_available_duration(self):
        manifest = fixture(videos=(0,))
        manifest["videos"][0]["duration"] = 1.2
        plan = build_reel_plan(manifest, PlannerConfig(min_shots=10))
        shot = next(s for s in plan["shots"] if s["media_type"] == "video")
        self.assertEqual(shot["planned_duration_seconds"], 1.2)
        self.assertEqual((shot["source_trim_start_seconds"], shot["source_trim_end_seconds"]), (0.0, 1.2))

    def test_too_few_candidates_fails_instead_of_breaking_bounds(self):
        with self.assertRaisesRegex(ReelPlanInsufficientMedia, "requires at least"):
            build_reel_plan(fixture(3, videos=()), PlannerConfig())

    def test_excess_reduction_preserves_sections_and_ids(self):
        manifest = fixture(30, videos=(0, 6, 12, 18, 24, 28))
        plan = build_reel_plan(manifest, PlannerConfig(min_shots=6, max_shots=16))
        self.assertEqual(len(plan["shots"]), 16)
        self.assertEqual({s["story_section"] for s in plan["shots"]}, set(SECTIONS))
        known = {entry["media_id"] for entry in manifest["story"]["sequence"]}
        self.assertTrue({s["media_id"] for s in plan["shots"]} <= known)
        self.assertEqual(len(plan["summary"]["dropped_candidates"]), 14)

    def test_missing_video_duration_is_explainably_dropped(self):
        manifest = fixture(videos=(0,))
        del manifest["videos"][0]["duration"]
        plan = build_reel_plan(manifest, PlannerConfig(min_shots=10))
        self.assertNotIn("video-00", [s["media_id"] for s in plan["shots"]])
        self.assertEqual(plan["summary"]["dropped_candidates"][0]["reason"], "video_duration_unavailable_or_invalid")

    def test_configuration_validation(self):
        for kwargs in ({"target_duration_seconds": 0}, {"photo_default_duration": .5},
                       {"video_min_duration": 5}, {"min_shots": 9, "max_shots": 8},
                       {"default_transition": "spin"}, {"target_duration_seconds": 100}):
            with self.assertRaises(ValueError): PlannerConfig(**kwargs)

    def test_additive_manifest_persistence_and_rerun_determinism(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            payload = fixture(); path = root / "output" / "trip_manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            upstream = copy.deepcopy({key: payload[key] for key in ("photos", "videos", "story", "selection", "timeline")})
            first = run_planner(root, PlannerConfig())
            persisted = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["manifest_version"], "1.4")
            self.assertEqual({key: persisted[key] for key in upstream}, upstream)
            self.assertNotIn("render", persisted)
            second = run_planner(root, PlannerConfig())
            self.assertEqual(first, second)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["reel_plan"], first)

    def test_real_adaptive_32_shot_bounds_are_feasible_for_40_seconds(self):
        manifest = fixture(32, videos=(0, 5, 10, 15, 20, 25))
        manifest["creative_direction"] = {
            "style": "beat_montage", "pacing": {"overall": "fast"},
            "media_budget": {"target_shots": 32, "minimum_shots": 26, "maximum_shots": 38},
            "template_strategy": {"primary": "beat_montage"},
        }
        plan = build_reel_plan(manifest, PlannerConfig())
        self.assertEqual(plan["summary"]["planned_shot_count"], 32)
        self.assertEqual(plan["summary"]["photos"], 26)
        self.assertEqual(plan["summary"]["videos"], 6)
        self.assertEqual(plan["actual_duration_seconds"], 40.0)

    def test_planner_consumes_director_resolved_duration_not_config_default(self):
        manifest = fixture(32, videos=(0, 5, 10, 15, 20, 25))
        manifest["creative_direction"] = {
            "style": "beat_montage", "pacing": {"overall": "fast"},
            "duration_strategy": {"mode": "adaptive", "resolved_seconds": 58.0},
            "media_budget": {"target_shots": 32, "minimum_shots": 26, "maximum_shots": 38},
            "template_strategy": {"primary": "beat_montage"},
        }
        plan = build_reel_plan(manifest, PlannerConfig())
        self.assertEqual(plan["target_duration_seconds"], 58.0)
        self.assertEqual(plan["actual_duration_seconds"], 58.0)
        self.assertEqual(plan["summary"]["planned_shot_count"], 32)

    def test_planner_consumes_music_duration_and_preserves_story_order(self):
        manifest = fixture(20, videos=(0, 5, 10, 15))
        manifest["creative_direction"] = {
            "style": "beat_montage", "pacing": {"overall": "fast"},
            "duration_strategy": {"resolved_seconds": 40.0},
            "media_budget": {"minimum_shots": 15, "maximum_shots": 24},
        }
        manifest["music_analysis"] = {
            "version": "1.0", "duration_seconds": 60.0,
            "source": {"cache_key": "music-key"}, "tempo": {"bpm": 120},
            "duration_alignment": {"music_aligned_duration": 42.0},
            "beats": [{"time": value+.05} for value in range(2, 42, 2)],
            "phrases": [{"start": 0.0, "end": 60.0}],
            "sync_anchors": [], "story_mapping": [],
        }
        expected = [entry["media_id"] for entry in manifest["story"]["sequence"]]
        plan = build_reel_plan(manifest, PlannerConfig())
        self.assertEqual(plan["actual_duration_seconds"], 42.0)
        self.assertEqual([shot["media_id"] for shot in plan["shots"]], expected)
        self.assertEqual(plan["music_intelligence"]["cache_key"], "music-key")
        self.assertLess(plan["music_intelligence"]["snapped_boundary_count"], len(plan["shots"])-1)

    def test_cli_prerequisite_behavior(self):
        self.assertIn("plan", build_parser().format_help())
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            (root / "output" / "trip_manifest.json").write_text(json.dumps({"trip": {}, "photos": [], "videos": []}))
            output = StringIO()
            with redirect_stdout(output): result = main(["plan", str(root)])
            self.assertEqual(result, 2)
            self.assertIn("Planner prerequisite error: Story plan not found. Run 'story' first.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
