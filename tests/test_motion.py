"""Base Motion, inherited visibility, persistence, and dependency tests."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tests.test_layout import fixture as layout_fixture
from travel_reel.layout import resolve_layouts
from travel_reel.motion import (resolve_motion, validate_motion_plan, MotionValidationError,
                               crop_slack, duration_class, _candidates, _rank, _slot_bounds)
from travel_reel.config import MotionConfig, LayoutConfig, TemplateConfig
from travel_reel.pipeline import run_motion_planner, run_layout_planner, run_template_planner, run_media_metadata_enrichment
from travel_reel.cli import main


def fixture(kind="fullscreen_media", duration=6, orientations=None):
    m = layout_fixture(kind, duration=duration, orientations=orientations)
    b = m["visual_plan"]["blocks"][0]
    b["motion"] = {"type": "push_in"}
    b["layout"] = {"layers": []}
    m["reel_plan"]["shots"] = []
    count = len(b["shots"])
    for index, shot in enumerate(b["shots"]):
        start, end = duration*index/count, duration*(index+1)/count
        timing = {"start_seconds": start, "end_seconds": end}
        b["layout"]["layers"].append({"shot_id": shot["shot_id"], "slot_id": f"template-{index}",
            "editorial_timing": dict(timing), "visual_layer_timing": dict(timing)})
        m["reel_plan"]["shots"].append(dict(shot, timeline_start_seconds=start, timeline_end_seconds=end,
                                          planned_duration_seconds=end-start))
    m["visual_plan"] = resolve_layouts(m, m["visual_plan"])
    return m


class MotionTests(unittest.TestCase):
    def resolve(self, m): return resolve_motion(m, m["visual_plan"])

    def test_push_hold_spaces_and_disable(self):
        m = fixture(); v = self.resolve(m)
        track = v["blocks"][0]["resolved_motion"]["tracks"][0]
        self.assertEqual(track["strategy"], "slow_push_in.v1")
        self.assertEqual(track["keyframes"][1]["transform"]["scale"], 1.04)
        m["visual_plan"]["blocks"][0]["motion"]["type"] = "none"
        v = self.resolve(m); track = v["blocks"][0]["resolved_motion"]["tracks"][0]
        self.assertEqual(track["strategy"], "hold.v1")
        track["space"] = "slot"
        validate_motion_plan(v, m["visual_plan"], m)
        self.assertEqual(resolve_motion(fixture(), fixture()["visual_plan"], enabled=False)["blocks"][0]["resolved_motion"]["tracks"][0]["strategy"], "hold.v1")

    def test_media_fallbacks(self):
        for mode in ("video", "unknown", "contain", "short"):
            with self.subTest(mode=mode):
                m = fixture(duration=.5 if mode == "short" else 6)
                b = m["visual_plan"]["blocks"][0]
                if mode == "video": m["videos"] = m.pop("photos"); m["photos"] = []
                if mode == "unknown": m["photos"][0].pop("width")
                if mode == "contain": b["resolved_layout"]["slots"][0]["fit_mode"] = "contain"
                self.assertEqual(self.resolve(m)["blocks"][0]["resolved_motion"]["tracks"][0]["strategy"], "hold.v1")

    def test_orientations(self):
        for orientation in ("portrait", "landscape", "square"):
            m = fixture(orientations=[orientation])
            self.assertEqual(self.resolve(m)["blocks"][0]["resolved_motion"]["tracks"][0]["strategy"], "slow_push_in.v1")

    def test_families_and_duration_independence(self):
        for kind in ("fullscreen_media", "hero_media", "two_up", "three_up", "grid", "collage", "layered_cards", "beat_montage", "closing_card"):
            for duration in (30, 56, 90):
                with self.subTest(kind=kind, duration=duration):
                    m = fixture(kind, duration); before = copy.deepcopy(m)
                    v = self.resolve(m); self.assertEqual(m, before); self.assertEqual(v, self.resolve(m))
                    b = v["blocks"][0]; tracks = b["resolved_motion"]["tracks"]
                    self.assertEqual(len(tracks), len(b["shot_ids"]))
                    for i, track in enumerate(tracks):
                        self.assertAlmostEqual(track["keyframes"][0]["t"], i/len(tracks))
                        self.assertAlmostEqual(track["keyframes"][-1]["t"], (i+1)/len(tracks))
                    validate_motion_plan(v, before["visual_plan"], before)

    def test_shifted_block_normalization(self):
        m = fixture("two_up")
        # Non-even inherited split proves joins use shot ID, not template slot names.
        b = m["visual_plan"]["blocks"][0]
        b["layout"]["layers"][0]["visual_layer_timing"]["end_seconds"] = 2
        b["layout"]["layers"][1]["visual_layer_timing"]["start_seconds"] = 2
        v = self.resolve(m); t = v["blocks"][0]["resolved_motion"]["tracks"]
        self.assertEqual(t[0]["keyframes"][-1]["t"], 1/3)
        self.assertEqual(t[1]["keyframes"][0]["t"], 1/3)

    def test_malformed_contracts(self):
        m = fixture("two_up"); original = self.resolve(m)
        changes = [
            lambda r: r.update(version="9"), lambda r: r.update(time_space="absolute"),
            lambda r: r.update(tracks=[]), lambda r: r["tracks"][0].update(target_slot_id="bad"),
            lambda r: r["tracks"].__setitem__(1, copy.deepcopy(r["tracks"][0])),
            lambda r: r["tracks"][0].update(space="bad"), lambda r: r["tracks"][0].update(strategy="pan.v1"),
            lambda r: r["tracks"][0]["keyframes"][0].update(easing_to_next="bounce"),
            lambda r: r["tracks"][0]["keyframes"][1].update(t=0),
            lambda r: r["tracks"][0]["keyframes"][1].update(t=.9),
            lambda r: r["tracks"][0]["keyframes"].reverse(),
            lambda r: r["tracks"][0]["keyframes"][0]["transform"].update(rotation=1),
        ]
        for value in (float("nan"), float("inf"), True, -1, 1.1):
            changes.append(lambda r, value=value: r["tracks"][0]["keyframes"][0].update(t=value))
        for key, value in (("scale", 0), ("scale", 1.05), ("scale", True), ("scale", float("nan")),
                           ("opacity", -1), ("opacity", 2), ("translate_x", .01)):
            changes.append(lambda r, key=key, value=value: r["tracks"][0]["keyframes"][1]["transform"].update({key: value}))
        for i, change in enumerate(changes):
            with self.subTest(case=i):
                v = copy.deepcopy(original); change(v["blocks"][0]["resolved_motion"])
                with self.assertRaises(MotionValidationError): validate_motion_plan(v, m["visual_plan"], m)

    def test_ownership_and_input_timing_rejected(self):
        for mode in ("slot", "layer", "window", "layout", "reel"):
            m = fixture("two_up"); b = m["visual_plan"]["blocks"][0]
            if mode == "slot": b["resolved_layout"]["slots"][0]["shot_id"] = "wrong"
            if mode == "layer": b["layout"]["layers"][0]["shot_id"] = "wrong"
            if mode == "window": b["layout"]["layers"][0]["visual_layer_timing"]["end_seconds"] = 10
            if mode == "layout": b.pop("resolved_layout")
            if mode == "reel": m["reel_plan"]["shots"][0]["media_id"] = "wrong"
            with self.subTest(mode=mode), self.assertRaises(MotionValidationError): self.resolve(m)

    def test_upstream_mutations_rejected(self):
        m = fixture(); v = self.resolve(m)
        for key, value in (("duration_seconds", 9), ("story_phase", "closing"), ("shot_ids", [])):
            changed = copy.deepcopy(v); changed["blocks"][0][key] = value
            with self.assertRaises(MotionValidationError): validate_motion_plan(changed, m["visual_plan"], m)

    def persist(self, root, m):
        (root / "output").mkdir(exist_ok=True)
        path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(m), encoding="utf-8")
        return path

    def test_pipeline_atomic_idempotent_preservation(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); m = fixture(); path = self.persist(root, m)
            with patch("travel_reel.manifest.os.replace", side_effect=OSError("failure")):
                with self.assertRaises(OSError): run_motion_planner(root, MotionConfig())
            self.assertEqual(json.loads(path.read_text()), m)
            run_motion_planner(root, MotionConfig()); result = json.loads(path.read_text())
            self.assertEqual(result["manifest_version"], "1.10"); self.assertNotIn("render", result)
            for key in m:
                if key not in {"manifest_version", "visual_plan", "render"}: self.assertEqual(m[key], result[key])
            result["render"] = {"new": True}; self.persist(root, result); before = path.read_bytes()
            run_motion_planner(root, MotionConfig()); self.assertEqual(path.read_bytes(), before)

    def test_cli_and_prerequisites(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(main(["motion-plan", str(root)]), 2)
            for visual in (None, {}):
                m = fixture(); m["visual_plan"] = visual; self.persist(root, m)
                with self.assertRaisesRegex(MotionValidationError, "layout-plan"): run_motion_planner(root, MotionConfig())
            self.persist(root, fixture()); self.assertEqual(main(["motion-plan", str(root)]), 0)

    def test_layout_invalidation_changed_and_identical(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); m = fixture(); m["visual_plan"] = self.resolve(m); self.persist(root, m)
            same = run_layout_planner(root, LayoutConfig())
            self.assertIn("resolved_motion", same["blocks"][0])
            changed = run_layout_planner(root, LayoutConfig(default_background="paper_white"))
            self.assertNotIn("resolved_motion", changed["blocks"][0])

    def test_dimension_invalidation_and_identical(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); m = fixture(); m["visual_plan"] = self.resolve(m); path = self.persist(root, m)
            item = m["photos"][0]; facts = {"width": item["width"], "height": item["height"], "orientation": "portrait"}
            with patch("travel_reel.pipeline.extract_media_dimensions", return_value=facts): run_media_metadata_enrichment(root)
            self.assertIn("resolved_motion", json.loads(path.read_text())["visual_plan"]["blocks"][0])
            with patch("travel_reel.pipeline.extract_media_dimensions", return_value=dict(facts, width=1200)): run_media_metadata_enrichment(root)
            b = json.loads(path.read_text())["visual_plan"]["blocks"][0]
            self.assertNotIn("resolved_layout", b); self.assertNotIn("resolved_motion", b)

    def test_template_identical_preserves_and_changed_invalidates(self):
        from travel_reel.pipeline import _semantic_visual
        with TemporaryDirectory() as directory:
            root = Path(directory); m = fixture(); m["visual_plan"] = self.resolve(m)
            m["template_definition"] = {"fixture": True}; self.persist(root, m)
            semantic = _semantic_visual(m["visual_plan"])
            with patch("travel_reel.pipeline.get_builtin_template", return_value=m["template_definition"]), patch("travel_reel.pipeline.resolve_visual_plan", return_value=semantic):
                same = run_template_planner(root, TemplateConfig()); self.assertIn("resolved_motion", same["blocks"][0])
                changed = copy.deepcopy(semantic); changed["blocks"][0]["motion"] = {"type": "none"}
                with patch("travel_reel.pipeline.resolve_visual_plan", return_value=changed):
                    result = run_template_planner(root, TemplateConfig())
                self.assertNotIn("resolved_motion", result["blocks"][0]); self.assertNotIn("resolved_layout", result["blocks"][0])

    def candidates(self, m, slot_index=0):
        block = m["visual_plan"]["blocks"][0]
        slot = block["resolved_layout"]["slots"][slot_index]
        layer = next(l for l in block["layout"]["layers"] if l["shot_id"] == slot["shot_id"])
        window = layer["visual_layer_timing"]
        start, duration = block["timeline_start_seconds"], block["duration_seconds"]
        bounds = ((window["start_seconds"]-start)/duration, (window["end_seconds"]-start)/duration,
                  window["end_seconds"]-window["start_seconds"])
        kind = "photo" if any(i["id"] == slot["media_id"] for i in m["photos"]) else "video"
        item = next(i for i in m["photos"]+m["videos"] if i["id"] == slot["media_id"])
        return _candidates(m, block, slot, kind, item, bounds, True)

    def use_strategy(self, m, strategy):
        v = self.resolve(m)
        candidate = next(c for c in self.candidates(m) if c["track"]["strategy"] == strategy)
        v["blocks"][0]["resolved_motion"]["tracks"][0] = copy.deepcopy(candidate["track"])
        validate_motion_plan(v, m["visual_plan"], m)
        return v

    def test_pull_out_and_directional_pan_families(self):
        for strategy in ("slow_pull_out.v1", "pan_horizontal_left.v1", "pan_horizontal_right.v1"):
            m = fixture(orientations=["landscape"])
            v = self.use_strategy(m, strategy)
            states = [f["transform"] for f in v["blocks"][0]["resolved_motion"]["tracks"][0]["keyframes"]]
            if strategy == "slow_pull_out.v1": self.assertGreater(states[0]["scale"], states[-1]["scale"])
            else: self.assertNotEqual(states[0]["translate_x"], states[-1]["translate_x"])
        for strategy in ("pan_vertical_up.v1", "pan_vertical_down.v1"):
            m = fixture(); m["photos"][0].update(width=100, height=500)
            self.use_strategy(m, strategy)

    def test_geometry_not_orientation_selects_pan_axis(self):
        m = fixture(); m["photos"][0].update(width=300, height=400)  # Portrait source, narrower portrait slot.
        strategies = {c["track"]["strategy"] for c in self.candidates(m)}
        self.assertIn("pan_horizontal_left.v1", strategies)
        self.assertNotIn("pan_vertical_up.v1", strategies)
        m["photos"][0].update(width=100, height=500)
        strategies = {c["track"]["strategy"] for c in self.candidates(m)}
        self.assertIn("pan_vertical_up.v1", strategies)
        self.assertNotIn("pan_horizontal_left.v1", strategies)

    def test_zero_slack_and_extreme_slack(self):
        m = fixture(); slot = m["visual_plan"]["blocks"][0]["resolved_layout"]["slots"][0]
        self.assertEqual(crop_slack(m["photos"][0], slot), (0, 0))
        self.assertFalse(any(c["track"]["strategy"].startswith("pan_") for c in self.candidates(m)))
        m["photos"][0].update(width=100000, height=100)
        v = self.use_strategy(m, "pan_horizontal_right.v1")
        for f in v["blocks"][0]["resolved_motion"]["tracks"][0]["keyframes"]:
            self.assertLessEqual(abs(f["transform"]["translate_x"]), .025)

    def test_drift_is_small_and_coverage_safe_through_interpolation(self):
        m = fixture(); v = self.use_strategy(m, "subtle_drift.v1")
        frames = v["blocks"][0]["resolved_motion"]["tracks"][0]["keyframes"]
        slot = v["blocks"][0]["resolved_layout"]["slots"][0]
        for i in range(101):
            q = i/100; q = 3*q*q-2*q*q*q
            state = {k: (1-q)*frames[0]["transform"][k]+q*frames[1]["transform"][k] for k in frames[0]["transform"]}
            slack = crop_slack(m["photos"][0], slot, state["scale"])
            self.assertLessEqual(abs(state["translate_x"]), min(.006, slack[0])+1e-9)
            self.assertLessEqual(abs(state["translate_y"]), min(.006, slack[1])+1e-9)

    def test_duration_classes_and_adaptive_excursion(self):
        excursions = []
        for seconds, label in ((.5, "extremely_short"), (1.1, "short"), (3, "medium"), (8, "long")):
            m = fixture(duration=seconds); self.assertEqual(duration_class(seconds), label)
            track = self.resolve(m)["blocks"][0]["resolved_motion"]["tracks"][0]
            if seconds == .5: self.assertEqual(track["strategy"], "hold.v1")
            else:
                self.assertEqual(track["strategy"], "slow_push_in.v1")
                excursions.append(track["keyframes"][-1]["transform"]["scale"]-1)
        self.assertLess(excursions[0], excursions[1]); self.assertLess(excursions[1], excursions[2])
        self.assertLessEqual(excursions[2], .06)

    def test_pacing_phase_and_style(self):
        amplitudes = {}
        for pace in ("cinematic", "balanced", "dynamic", "fast"):
            for phase in ("hook", "exploration", "experience", "highlight", "closing"):
                m = fixture(duration=1.2); m["creative_direction"] = {"pacing": {"overall": pace}}
                m["visual_plan"]["blocks"][0]["story_phase"] = phase
                track = self.resolve(m)["blocks"][0]["resolved_motion"]["tracks"][0]
                amplitudes[pace, phase] = max(f["transform"]["scale"] for f in track["keyframes"])-1
        self.assertLess(amplitudes["fast", "hook"], amplitudes["balanced", "hook"])
        self.assertLess(amplitudes["balanced", "closing"], amplitudes["balanced", "exploration"])
        m = fixture(); m["creative_direction"] = {"style": "cinematic_travel"}
        reasons = self.resolve(m)["blocks"][0]["resolved_motion"]["selection_reasons"]
        self.assertTrue(any("pacing:cinematic" in r for r in reasons))
        m["creative_direction"]["pacing"] = {"overall": "fast", "phases": {"body": "balanced"}}
        self.assertTrue(any("pacing:balanced" in r for r in self.resolve(m)["blocks"][0]["resolved_motion"]["selection_reasons"]))

    def test_card_strategies_keyframes_and_visibility(self):
        for strategy in ("card_enter.v1", "card_exit.v1", "card_emphasis.v1"):
            m = fixture("hero_media", duration=1.2); v = self.use_strategy(m, strategy)
            track = v["blocks"][0]["resolved_motion"]["tracks"][0]
            self.assertEqual(track["space"], "slot"); self.assertEqual(len(track["keyframes"]), 3)
            self.assertEqual(track["keyframes"][0]["t"], 0); self.assertEqual(track["keyframes"][-1]["t"], 1)
            self.assertEqual(v["blocks"][0]["layout"], m["visual_plan"]["blocks"][0]["layout"])

    def test_video_slot_behavior_and_trims(self):
        m = fixture("hero_media"); m["videos"] = m["photos"]; m["photos"] = []
        m["reel_plan"]["shots"][0].update(source_trim_start_seconds=2, source_trim_end_seconds=8)
        m["visual_plan"]["blocks"][0]["motion"] = {"type": "slide_in"}
        m["visual_plan"]["blocks"][0]["story_phase"] = "hook"
        m["creative_direction"] = {"pacing": {"overall": "fast"}}
        before = copy.deepcopy(m); track = self.resolve(m)["blocks"][0]["resolved_motion"]["tracks"][0]
        self.assertEqual(track["strategy"], "card_enter.v1"); self.assertEqual(track["space"], "slot")
        self.assertEqual(m, before)
        self.assertFalse(any(c["track"]["strategy"].startswith("pan_") for c in self.candidates(m)))
        m["visual_plan"]["blocks"][0]["motion"] = {"type": "push_in"}
        self.assertEqual(self.resolve(m)["blocks"][0]["resolved_motion"]["tracks"][0]["strategy"], "hold.v1")

    def test_contain_card_does_not_change_fit(self):
        m = fixture("hero_media", orientations=["landscape"])
        self.assertEqual(m["visual_plan"]["blocks"][0]["resolved_layout"]["slots"][0]["fit_mode"], "contain")
        self.assertFalse(any(c["track"]["strategy"] == "slow_push_in.v1" for c in self.candidates(m)))
        self.use_strategy(m, "card_enter.v1")

    def test_collage_grid_layered_and_montage_visibility(self):
        for family in ("two_up", "collage", "layered_cards", "grid", "beat_montage"):
            m = fixture(family, duration=5); before = copy.deepcopy(m)
            v = self.resolve(m); self.assertEqual(m, before)
            tracks = v["blocks"][0]["resolved_motion"]["tracks"]
            for left, right in zip(tracks, tracks[1:]):
                self.assertEqual(left["keyframes"][-1]["t"], right["keyframes"][0]["t"])
            if family == "beat_montage": self.assertTrue(all(t["space"] == "media_content" for t in tracks))
            if family == "layered_cards":
                for slot, track in zip(v["blocks"][0]["resolved_layout"]["slots"], tracks):
                    if slot["role"] != "primary":
                        self.assertEqual(track["space"], "media_content")
                        # Quiet background is half-strength content motion or hold,
                        # not a forced quota of static cards.
                        self.assertLessEqual(max(f["transform"]["scale"] for f in track["keyframes"]), 1.02)

    def test_repetition_soft_and_stable(self):
        m = fixture(orientations=["landscape"]); candidates = self.candidates(m)
        first, _ = _rank(candidates, [])
        alternative, reasons = _rank(candidates, [first["strategy"]]*3)
        self.assertNotEqual(first["strategy"], alternative["strategy"])
        self.assertTrue(any("alternative" in r or "penalty" in r for r in reasons))
        # A large suitability gap remains stronger than the bounded repetition penalty.
        superior = copy.deepcopy(candidates)
        next(c for c in superior if c["track"]["strategy"] == first["strategy"])["score"] = 100
        self.assertEqual(_rank(superior, [first["strategy"]]*3)[0]["strategy"], first["strategy"])
        self.assertEqual(_rank(list(reversed(candidates)), [first["strategy"]]), _rank(candidates, [first["strategy"]]))
        unknown = fixture(); unknown["photos"][0].pop("width")
        self.assertEqual(_rank(self.candidates(unknown), ["hold.v1"]*3)[0]["strategy"], "hold.v1")

    def test_unsafe_translation_and_rotation_rejected(self):
        m = fixture(); v = self.use_strategy(m, "subtle_drift.v1")
        track = v["blocks"][0]["resolved_motion"]["tracks"][0]
        track["keyframes"][0]["transform"].update(scale=1, translate_x=.001)
        with self.assertRaisesRegex(MotionValidationError, "crop slack"): validate_motion_plan(v, m["visual_plan"], m)
        v = self.use_strategy(m, "slow_pull_out.v1")
        v["blocks"][0]["resolved_motion"]["tracks"][0]["keyframes"][0]["transform"]["rotation"] = 1
        with self.assertRaises(MotionValidationError): validate_motion_plan(v, m["visual_plan"], m)

    def test_middle_keyframe_swept_escape_rejected(self):
        m = fixture("hero_media"); b = m["visual_plan"]["blocks"][0]
        # Base rectangle fits exactly; emphasis's middle keyframe escapes while endpoints fit.
        b["resolved_layout"]["slots"][0].update(x=.04, y=.04, width=.92, height=.92)
        roomy = fixture("hero_media"); v = self.use_strategy(roomy, "card_emphasis.v1")
        v["blocks"][0]["resolved_layout"] = copy.deepcopy(b["resolved_layout"])
        with self.assertRaisesRegex(MotionValidationError, "safe area"): validate_motion_plan(v, m["visual_plan"], m)
        self.assertNotIn("card_emphasis.v1", {c["track"]["strategy"] for c in self.candidates(m)})

    def test_static_rotation_in_swept_card_bounds(self):
        m = fixture("hero_media"); b = m["visual_plan"]["blocks"][0]
        b["resolved_layout"]["slots"][0].update(x=.04, y=.04, width=.92, height=.92, rotation_deg=8)
        self.assertFalse(any(c["track"]["space"] == "slot" for c in self.candidates(m)))
        # Content hold/motion remains valid: no new card geometry is introduced.
        self.resolve(m)

    def test_prohibited_swept_collision_and_sequential_exception(self):
        m = fixture("two_up", duration=6); block = m["visual_plan"]["blocks"][0]
        for i, slot in enumerate(block["resolved_layout"]["slots"]):
            slot.update(x=.05+i*.4505, y=.1, width=.45, height=.8)
        v = self.use_strategy(m, "card_emphasis.v1")  # sequential: no new co-visibility
        for plan in (m["visual_plan"], v):
            for layer in plan["blocks"][0]["layout"]["layers"]:
                layer["visual_layer_timing"] = {"start_seconds": 0, "end_seconds": 6}
        for track in v["blocks"][0]["resolved_motion"]["tracks"]:
            old_end = track["keyframes"][-1]["t"]; old_start = track["keyframes"][0]["t"]
            for f in track["keyframes"]: f["t"] = (f["t"]-old_start)/(old_end-old_start)
        with self.assertRaisesRegex(MotionValidationError, "non-overlap"): validate_motion_plan(v, m["visual_plan"], m)
        safe = self.resolve(m); validate_motion_plan(safe, m["visual_plan"], m)

    def test_no_music_probing_or_randomness_dependency(self):
        m = fixture(duration=1.2); before = copy.deepcopy(m)
        with patch("travel_reel.media_preprocess.probe_video", side_effect=AssertionError("probe")), patch("random.random", side_effect=AssertionError("random")):
            first = self.resolve(m)
        m["music_analysis"] = {"sync_anchors": [{"time": .4}]}
        self.assertEqual(first, self.resolve(m))
        self.assertEqual(before["visual_plan"], m["visual_plan"])

    def test_motion_change_invalidates_only_downstream_overlays(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); m = fixture(); m["visual_plan"] = self.resolve(m)
            m["overlay_plan"] = {"dependent": True}; m["visual_plan"]["blocks"][0]["resolved_overlay"] = {"dependent": True}
            m["visual_plan"]["blocks"][0]["typography"] = [{"intent": "preserve"}]
            path = self.persist(root, m); run_motion_planner(root, MotionConfig(enabled=False))
            result = json.loads(path.read_text()); self.assertNotIn("render", result); self.assertNotIn("overlay_plan", result)
            self.assertNotIn("resolved_overlay", result["visual_plan"]["blocks"][0])
            self.assertEqual(result["visual_plan"]["blocks"][0]["typography"], [{"intent": "preserve"}])
            self.assertEqual(result["visual_plan"]["blocks"][0]["resolved_layout"], m["visual_plan"]["blocks"][0]["resolved_layout"])

    def test_reel_time_anchor_refines_content_once(self):
        m = fixture(duration=6)
        m["reel_plan"]["music_intelligence"] = {"consumed": True, "sync_anchors": [
            {"time": 3.0, "provenance": "detected_beat", "confidence": .9},
            {"time": 3.0004, "provenance": "heuristic_subdivision", "confidence": .99},
            {"time": 0.01, "provenance": "detected_beat", "confidence": .99},
        ]}
        v = self.resolve(m); track = v["blocks"][0]["resolved_motion"]["tracks"][0]
        self.assertEqual(track["strategy"], "slow_push_in.v1")
        self.assertEqual(len(track["keyframes"]), 3)
        self.assertEqual(track["beat_alignment"]["anchor_time_seconds"], 3.0)
        self.assertAlmostEqual(track["beat_alignment"]["normalized_time"], .5)
        self.assertEqual(track["keyframes"][1]["t"], .5)
        self.assertEqual(track["beat_alignment"]["provenance"], "detected_beat")

    def test_anchor_source_precedence_filtering_and_determinism(self):
        from travel_reel.motion import normalize_reel_anchors
        m = fixture(duration=6)
        m["music_analysis"] = {"beats": [{"time": 2, "confidence": 1}]}
        m["reel_plan"]["music_intelligence"] = {"sync_anchors": [
            {"time": 2, "provenance": "detected_beat", "confidence": .5},
            {"time": 2.0004, "provenance": "heuristic_accent", "confidence": .8},
            {"time": 1, "provenance": "heuristic_subdivision", "confidence": 1},
            {"time": -1, "provenance": "detected_beat", "confidence": 1},
            {"time": 7, "provenance": "detected_beat", "confidence": 1},
            {"time": float("nan"), "provenance": "detected_beat", "confidence": 1},
            {"time": 4, "provenance": "unknown", "confidence": 1},
            {"time": 5, "provenance": "detected_beat", "confidence": float("inf")},
        ]}
        anchors = normalize_reel_anchors(m)
        self.assertEqual([a["time_seconds"] for a in anchors], [1.0, 2.0])
        self.assertEqual(anchors[1]["provenance"], "heuristic_accent")
        self.assertEqual(normalize_reel_anchors(m), anchors)
        # Source-local beats do not participate when reel-time anchors are absent.
        m["reel_plan"].pop("music_intelligence")
        self.assertEqual(normalize_reel_anchors(m), [])
        before = copy.deepcopy(m); self.assertEqual(self.resolve(m), self.resolve(m)); self.assertEqual(m, before)

    def test_anchor_rejection_boundaries_and_provenance(self):
        m = fixture(duration=1.2)
        m["reel_plan"]["music_intelligence"] = {"sync_anchors": [
            {"time": 0.1, "provenance": "detected_beat", "confidence": .9},
            {"time": .6, "provenance": "heuristic_subdivision", "confidence": .99},
            {"time": 1.1, "provenance": "detected_beat", "confidence": .9},
            {"time": .6, "provenance": "detected_beat", "confidence": .49},
        ]}
        from travel_reel.motion import _eligible_anchors
        self.assertEqual(_eligible_anchors(m, 0, 1.2), [])
        self.assertEqual(self.resolve(m)["blocks"][0]["resolved_motion"]["tracks"][0]["strategy"], "slow_push_in.v1")

    def test_card_beat_refines_existing_peak_without_visibility_change(self):
        m = fixture("hero_media", duration=6)
        m["visual_plan"]["blocks"][0]["motion"] = {"type": "pop"}
        m["reel_plan"]["music_intelligence"] = {"sync_anchors": [{"time": 1.5, "provenance": "detected_beat", "confidence": .8}]}
        v = self.resolve(m); track = v["blocks"][0]["resolved_motion"]["tracks"][0]
        self.assertEqual(track["strategy"], "card_emphasis.v1")
        self.assertEqual(track["space"], "slot")
        self.assertAlmostEqual(track["keyframes"][1]["t"], .25)
        self.assertEqual(track["beat_alignment"]["normalized_time"], .25)
        self.assertEqual(v["blocks"][0]["layout"], m["visual_plan"]["blocks"][0]["layout"])

    def test_card_enter_exit_use_boundary_anchors_inside_layer(self):
        for strategy, anchor_time, expected_range in (
            ("card_enter.v1", .4, (.05, .5)),
            ("card_exit.v1", 5.6, (.5, .95)),
        ):
            m = fixture("hero_media", duration=6)
            m["visual_plan"]["blocks"][0]["motion"] = {"type": "slide_in" if strategy == "card_enter.v1" else "slide_out"}
            m["reel_plan"]["music_intelligence"] = {"sync_anchors": [
                {"time": anchor_time, "provenance": "detected_beat", "confidence": .9}
            ]}
            v = self.resolve(m)
            track = v["blocks"][0]["resolved_motion"]["tracks"][0]
            self.assertEqual(track["strategy"], strategy)
            self.assertIn("beat_alignment", track)
            t = track["beat_alignment"]["normalized_time"]
            self.assertGreaterEqual(t, expected_range[0])
            self.assertLessEqual(t, expected_range[1])
            self.assertGreaterEqual(t, track["keyframes"][0]["t"])
            self.assertLessEqual(t, track["keyframes"][-1]["t"])

    def test_beat_never_changes_hold_or_short_visibility(self):
        for duration in (.5, 1.2):
            m = fixture(duration=duration)
            m["reel_plan"]["music_intelligence"] = {"sync_anchors": [{"time": duration/2, "provenance": "detected_beat", "confidence": 1}]}
            v = self.resolve(m); track = v["blocks"][0]["resolved_motion"]["tracks"][0]
            if duration == .5: self.assertEqual(track["strategy"], "hold.v1")
            self.assertNotIn("beat_alignment", track)

    def test_beat_aligned_contract_safety_and_malformed_evidence(self):
        m = fixture(duration=6); m["reel_plan"]["music_intelligence"] = {"sync_anchors": [{"time": 3, "provenance": "detected_beat", "confidence": .9}]}
        v = self.resolve(m); track = v["blocks"][0]["resolved_motion"]["tracks"][0]
        for field, value in (("anchor_time_seconds", 9), ("normalized_time", .1), ("confidence", .1), ("provenance", "heuristic_subdivision")):
            changed = copy.deepcopy(v); changed["blocks"][0]["resolved_motion"]["tracks"][0]["beat_alignment"][field] = value
            with self.assertRaises(MotionValidationError): validate_motion_plan(changed, m["visual_plan"], m)
        changed = copy.deepcopy(v); changed["blocks"][0]["resolved_motion"]["tracks"][0]["keyframes"][1]["t"] = .8
        with self.assertRaises(MotionValidationError): validate_motion_plan(changed, m["visual_plan"], m)

    def test_layout_preserved_when_only_consumed_anchors_change(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); m = fixture(duration=6); m["reel_plan"]["music_intelligence"] = {"sync_anchors": [{"time": 3, "provenance": "detected_beat", "confidence": .9}]}; m["visual_plan"] = self.resolve(m); self.persist(root, m)
            before = json.loads((root/"output"/"trip_manifest.json").read_text())
            m2 = json.loads((root/"output"/"trip_manifest.json").read_text()); m2["reel_plan"]["music_intelligence"]["sync_anchors"][0]["time"] = 2.5; (root/"output"/"trip_manifest.json").write_text(json.dumps(m2))
            result = run_motion_planner(root, MotionConfig())
            self.assertEqual(result["blocks"][0]["resolved_layout"], before["visual_plan"]["blocks"][0]["resolved_layout"])
            self.assertEqual(result["blocks"][0]["resolved_motion"]["tracks"][0]["beat_alignment"]["anchor_time_seconds"], 2.5)

    def test_malformed_card_ramp_easing_and_scale(self):
        m = fixture("hero_media"); original = self.use_strategy(m, "card_enter.v1")
        for key, value in (("t", .8), ("easing_to_next", "elastic")):
            v = copy.deepcopy(original); v["blocks"][0]["resolved_motion"]["tracks"][0]["keyframes"][1][key] = value
            with self.assertRaises(MotionValidationError): validate_motion_plan(v, m["visual_plan"], m)
        v = copy.deepcopy(original); v["blocks"][0]["resolved_motion"]["tracks"][0]["keyframes"][0]["transform"]["scale"] = .8
        with self.assertRaises(MotionValidationError): validate_motion_plan(v, m["visual_plan"], m)

    def test_intentional_occlusion_blocks_unsafe_slot_variation(self):
        from travel_reel.motion import _swept_block, _track, _transform
        m = fixture("collage"); b = m["visual_plan"]["blocks"][0]
        # Test the conservative safety proof directly for nearly coincident cards.
        slots = b["resolved_layout"]["slots"]
        slots[1].update(x=slots[0]["x"], y=slots[0]["y"], width=slots[0]["width"], height=slots[0]["height"])
        tracks = [_track(s, "card_emphasis.v1", [_transform(), _transform(scale=1.01), _transform()], (0, 1, 4), [0, .5, 1]) for s in slots]
        with self.assertRaisesRegex(MotionValidationError, "occlusion"): _swept_block(b, tracks, 9/16)

    def test_card_swept_samples_fit_physical_canvas(self):
        m = fixture("hero_media"); v = self.use_strategy(m, "card_emphasis.v1")
        block = v["blocks"][0]; slot = block["resolved_layout"]["slots"][0]
        frames = block["resolved_motion"]["tracks"][0]["keyframes"]
        for first, last in zip(frames, frames[1:]):
            for index in range(51):
                q = index/50; q = q*q*(3-2*q)
                state = {k: first["transform"][k]*(1-q)+last["transform"][k]*q for k in first["transform"]}
                x0, y0, x1, y1 = _slot_bounds(slot, state, 9/16)
                self.assertGreaterEqual(x0, .04*9/16); self.assertGreaterEqual(y0, .04)
                self.assertLessEqual(x1, .96*9/16); self.assertLessEqual(y1, .96)

    def test_local_excursion_independent_of_plan_length_and_position(self):
        results = []
        for total in (30, 56, 90):
            m = fixture(duration=total-1.2); tail = fixture(duration=1.2)
            # First block is video hold so history cannot bias the identical photo.
            m["videos"] = m["photos"]; m["photos"] = []
            shot = tail["reel_plan"]["shots"][0]; block = tail["visual_plan"]["blocks"][0]
            new_id = "shot-tail"; new_media = "photo-tail"
            tail["photos"][0]["id"] = new_media
            shot.update(shot_id=new_id, media_id=new_media, timeline_start_seconds=total-1.2, timeline_end_seconds=total)
            block.update(visual_block_id="visual-tail", timeline_start_seconds=total-1.2, timeline_end_seconds=total, shot_ids=[new_id])
            block["shots"][0].update(shot_id=new_id, media_id=new_media)
            block["resolved_layout"]["slots"][0].update(shot_id=new_id, media_id=new_media)
            layer = block["layout"]["layers"][0]; layer["shot_id"] = new_id
            for key in ("editorial_timing", "visual_layer_timing"):
                layer[key] = {"start_seconds": total-1.2, "end_seconds": total}
            m["photos"] = tail["photos"]; m["reel_plan"]["shots"].append(shot)
            m["reel_plan"]["actual_duration_seconds"] = total
            m["visual_plan"]["duration_seconds"] = total; m["visual_plan"]["blocks"].append(block)
            track = self.resolve(m)["blocks"][-1]["resolved_motion"]["tracks"][0]
            results.append(track)
        self.assertEqual(results[0], results[1]); self.assertEqual(results[1], results[2])
