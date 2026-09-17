"""Dependency-free tests for compliant local music intake and ranking."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from travel_reel.cli import build_parser
from travel_reel.config import MusicConfig
from travel_reel.music import music_fingerprint
from travel_reel.music_library import (
    MusicLibraryError, build_music_profile, import_track, rank_library,
    scan_library, score_candidate,
)
from travel_reel.pipeline import run_music_selection


def direction(style="beat_montage", pacing="fast"):
    return {
        "style": style, "pacing": {"overall": pacing},
        "duration_strategy": {
            "resolved_seconds": 55.5, "minimum_seconds": 43.0,
            "maximum_seconds": 90.0, "flexibility_seconds": 5.0,
            "safe_shot_bounds_seconds": {"minimum": 43.0, "maximum": 90.0},
        },
        "content_profile": {"event_diversity": .9, "motion_density": .25},
        "music_strategy": {"energy": "high", "beat_driven": True,
                           "preferred_structure": ["hook", "build", "peak", "release"]},
        "template_strategy": {"primary": "beat_montage"},
    }


def manifest():
    return {
        "manifest_version": "1.7", "trip": {"name": "Music Library Test"},
        "photos": [], "videos": [], "events": {"upstream": True},
        "creative_direction": direction(),
        "story": {"sequence": [{"section": value} for value in
                  ("hook", "exploration", "experience", "highlight", "closing")]},
        "reel_plan": {"stale": True}, "render": {"stale": True},
    }


def analysis(bpm=126.0, confidence=.8, energetic=True, cache_key="analysis-a"):
    curve = ([{"time": 0.0, "energy": .1}, {"time": 20.0, "energy": .5},
              {"time": 45.0, "energy": 1.0}, {"time": 56.0, "energy": .3}]
             if energetic else [{"time": 0.0, "energy": .4}, {"time": 56.0, "energy": .4}])
    return {
        "version": "1.0", "analyzer": {"name": "test", "version": "1"},
        "source": {"cache_key": cache_key}, "duration_seconds": 80.0,
        "tempo": {"bpm": bpm, "confidence": confidence, "ambiguity": False},
        "beats": [{"time": float(value), "index": value} for value in range(0, 80)],
        "phrases": [{"index": 0, "start": 0.0, "end": 20.0, "type": "intro", "energy": .1},
                    {"index": 1, "start": 20.0, "end": 40.0, "type": "build", "energy": .5},
                    {"index": 2, "start": 40.0, "end": 56.0, "type": "peak", "energy": 1.0},
                    {"index": 3, "start": 56.0, "end": 80.0, "type": "release", "energy": .3}],
        "energy_curve": curve,
        "structure": [{"type": name, "start": start, "end": end} for name, start, end in
                      (("intro", 0, 20), ("build", 20, 40), ("peak", 40, 56), ("release", 56, 80))],
        "sync_anchors": [{"time": 56.0, "type": "peak", "confidence": .8},
                         {"time": 56.0, "type": "final_resolving_beat", "confidence": .8}],
        "validation": {},
    }


class MusicLibraryTests(unittest.TestCase):
    def test_empty_library_and_supported_discovery(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(scan_library(root), [])
            tracks = root / "tracks"; tracks.mkdir()
            for name in ("a.mp3", "b.M4A", "c.aac", "d.wav", "e.flac", "ignored.txt"):
                (tracks / name).write_bytes(name.encode())
            self.assertEqual(len(scan_library(root)), 5)
            self.assertNotIn("ignored.txt", {item["file_name"] for item in scan_library(root)})

    def test_import_preserves_source_deduplicates_and_round_trips_metadata(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); source = root / "download.wav"; source.write_bytes(b"audio")
            before = music_fingerprint(source)
            metadata = {"title": "Pulse", "creator": "Owner", "source_name": "manual",
                        "source_page": "https://example.invalid/item", "license_name": "Test license",
                        "license_url": "https://example.invalid/license", "attribution_required": False}
            first = import_track(source, root / "library", metadata)
            second = import_track(source, root / "library", metadata)
            self.assertTrue(first["imported"]); self.assertTrue(second["duplicate"])
            self.assertEqual(music_fingerprint(source), before)
            discovered = scan_library(root / "library")
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0]["title"], "Pulse")
            self.assertEqual(discovered[0]["metadata_status"], "verified_metadata")
            self.assertTrue(discovered[0]["production_ready"])

    def test_missing_metadata_is_engineering_only_and_unsupported_import_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); source = root / "local.mp3"; source.write_bytes(b"local")
            track = import_track(source, root / "library", {})["track"]
            self.assertEqual(track["metadata_status"], "local_only")
            self.assertTrue(track["engineering_usable"]); self.assertFalse(track["production_ready"])
            bad = root / "bad.exe"; bad.write_bytes(b"bad")
            with self.assertRaisesRegex(MusicLibraryError, "Unsupported"):
                import_track(bad, root / "library", {})

    def test_fingerprint_deduplicates_different_filenames(self):
        with TemporaryDirectory() as directory:
            tracks = Path(directory) / "tracks"; tracks.mkdir()
            (tracks / "first.mp3").write_bytes(b"same-audio")
            (tracks / "renamed.mp3").write_bytes(b"same-audio")
            self.assertEqual(len(scan_library(Path(directory))), 1)

    def test_attribution_requirement_needs_attribution_text(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); source = root / "track.flac"; source.write_bytes(b"audio")
            values = {"source_name": "source", "source_page": "page", "license_name": "license",
                      "license_url": "license-page", "attribution_required": True}
            track = import_track(source, root / "library", values)["track"]
            self.assertEqual(track["metadata_status"], "incomplete_metadata")
            self.assertFalse(track["production_ready"])

    def test_duplicate_import_can_fill_unknown_metadata_without_replacing_audio(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); source = root / "track.wav"; source.write_bytes(b"audio")
            first = import_track(source, root / "library", {})
            enriched = import_track(source, root / "library", {
                "source_name": "manual", "source_page": "page", "license_name": "license",
                "license_url": "license-page", "attribution_required": False,
            })
            self.assertTrue(enriched["duplicate"]); self.assertTrue(enriched["track"]["production_ready"])
            self.assertEqual(first["managed_path"], enriched["managed_path"])

    def test_profiles_are_director_and_style_aware(self):
        fast = build_music_profile(manifest())
        cinematic_manifest = manifest(); cinematic_manifest["creative_direction"] = direction("cinematic_travel", "measured")
        cinematic = build_music_profile(cinematic_manifest)
        self.assertEqual(fast["story_phases"], ["hook", "exploration", "experience", "highlight", "closing"])
        self.assertGreater(fast["preferred_tempo_bpm"]["maximum"], cinematic["preferred_tempo_bpm"]["maximum"])
        self.assertTrue(fast["beat_driven"])

    def test_candidate_scoring_is_deterministic_and_multidimensional(self):
        profile = build_music_profile(manifest())
        ready = {"metadata_status": "verified_metadata", "production_ready": True}
        local = {"metadata_status": "local_only", "production_ready": False}
        aligned = {"usable_for_planning": True, "delta_seconds": .5, "alignment_reason": "phrase_boundary"}
        strong = score_candidate(ready, analysis(), profile, aligned)
        repeated = score_candidate(ready, analysis(), profile, aligned)
        weak = score_candidate(local, analysis(145, .2, False), profile,
                               {"usable_for_planning": False, "delta_seconds": 30,
                                "alignment_reason": "music_too_short_for_director_envelope"})
        self.assertEqual(strong, repeated)
        self.assertGreater(strong["music_match_score"], weak["music_match_score"])
        self.assertGreater(strong["components"]["ending_quality"], weak["components"]["ending_quality"])
        self.assertGreater(strong["components"]["beat_confidence"], weak["components"]["beat_confidence"])
        self.assertIn("metadata_readiness", strong["components"])

    def test_overall_structure_can_beat_nearest_bpm(self):
        profile = build_music_profile(manifest()); track = {"metadata_status": "local_only", "production_ready": False}
        aligned = {"usable_for_planning": True, "delta_seconds": .5, "alignment_reason": "phrase_boundary"}
        structured = score_candidate(track, analysis(120, .9, True), profile, aligned)
        nearest = analysis(135, .3, False)
        nearest["structure"] = []; nearest["sync_anchors"] = []
        plain = score_candidate(track, nearest, profile,
                                {"usable_for_planning": True, "delta_seconds": 3,
                                 "alignment_reason": "editorial_duration_retained"})
        self.assertGreater(structured["music_match_score"], plain["music_match_score"])

    def test_ranking_reuses_analysis_cache_and_is_stable(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); tracks = root / "library" / "tracks"; tracks.mkdir(parents=True)
            (tracks / "b.wav").write_bytes(b"b"); (tracks / "a.wav").write_bytes(b"a")
            calls = []
            def fake(path, config, cache):
                calls.append(path.name)
                return analysis(cache_key=path.name), path.name == "b.wav"
            with patch("travel_reel.music_library.analyze_music_cached", side_effect=fake):
                ranked = rank_library(root / "library", manifest(), MusicConfig(), root / "cache")
            self.assertEqual(ranked["summary"], {"candidates": 2, "eligible": 2, "analyzed": 1, "cached": 1})
            self.assertEqual(sorted(calls), ["a.wav", "b.wav"])
            scores = [item["music_match_score"] for item in ranked["ranked"]]
            self.assertEqual(scores, sorted(scores, reverse=True))
            first_order = [item["track"]["track_id"] for item in ranked["ranked"]]
            with patch("travel_reel.music_library.analyze_music_cached", side_effect=fake):
                repeated = rank_library(root / "library", manifest(), MusicConfig(), root / "cache")
            self.assertEqual(first_order, [item["track"]["track_id"] for item in repeated["ranked"]])
            self.assertEqual(scores, [item["music_match_score"] for item in repeated["ranked"]])
            self.assertEqual(ranked["ranked"][0]["track"]["track_id"],
                             repeated["ranked"][0]["track"]["track_id"])

    def test_selection_persists_planner_contract_and_only_invalidates_downstream(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir(); library = root / "library"
            source = root / "candidate.wav"; source.write_bytes(b"candidate")
            import_track(source, library, {})
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(manifest()))
            with patch("travel_reel.music_library.analyze_music_cached", return_value=(analysis(), False)):
                result = run_music_selection(root, MusicConfig(), library)
            saved = json.loads(path.read_text())
            self.assertIsNotNone(result["selected"])
            self.assertEqual(saved["music_selection"]["selected_track_id"], result["selected"]["track_id"])
            self.assertEqual(saved["music_analysis"]["selected_track"]["track_id"], result["selected"]["track_id"])
            self.assertNotIn("reel_plan", saved); self.assertNotIn("render", saved)
            self.assertEqual(saved["events"], {"upstream": True})

    def test_empty_selection_remains_valid_no_music_state(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            payload = manifest(); payload.pop("reel_plan"); payload.pop("render")
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(payload))
            result = run_music_selection(root, MusicConfig(), root / "empty")
            saved = json.loads(path.read_text())
            self.assertEqual(result["candidates"], 0)
            self.assertIsNone(saved["music_selection"]["selected_track_id"])
            self.assertNotIn("music_analysis", saved)

    def test_windows_cli_paths_and_local_only_commands(self):
        parser = build_parser()
        imported = parser.parse_args(["music-import", "--file", r"C:\Downloads\track.mp3",
                                      "--library", r"C:\Music Pool"])
        selected = parser.parse_args(["music-select", r"C:\Trips\Taipei", "--library", r"C:\Music Pool"])
        self.assertEqual(str(imported.music_file), r"C:\Downloads\track.mp3")
        self.assertEqual(str(selected.library), r"C:\Music Pool")

    def test_intake_and_discovery_need_no_network(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); source = root / "track.aac"; source.write_bytes(b"local")
            with patch("socket.create_connection", side_effect=AssertionError("network used")):
                import_track(source, root / "library", {})
                self.assertEqual(len(scan_library(root / "library")), 1)


if __name__ == "__main__":
    unittest.main()
