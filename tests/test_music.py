"""Music Intelligence tests using generated, copyright-free pulse audio."""
import copy
import json
import math
import shutil
import struct
import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_reel.config import MusicConfig
from travel_reel.cli import build_parser
from travel_reel.music import (
    MusicAnalysisError, analyze_music, map_story_to_music, music_cache_key,
    music_fingerprint, negotiate_duration, validate_music_analysis,
)
from travel_reel.pipeline import run_music
from travel_reel.planner import _snap_to_music


def pulse_wav(path: Path, bpm: float = 120, seconds: float = 12) -> None:
    rate = 22050; interval = 60 / bpm
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        frames = bytearray()
        for index in range(round(rate * seconds)):
            time = index / rate; phase = time % interval
            region = .25 if time < seconds*.25 else .55 if time < seconds*.6 else .95 if time < seconds*.82 else .35
            value = region * math.sin(2*math.pi*880*time) * max(0, 1-phase/.035) if phase < .035 else 0
            frames.extend(struct.pack("<h", round(value*32767)))
        audio.writeframes(frames)


def manifest() -> dict:
    return {"manifest_version": "1.7", "trip": {"name": "music"}, "photos": [], "videos": [],
            "events": {"keep": True}, "creative_direction": {"duration_strategy": {
                "resolved_seconds": 10.0, "minimum_seconds": 8.0, "maximum_seconds": 12.0,
                "flexibility_seconds": 2.0, "safe_shot_bounds_seconds": {"minimum": 8.0, "maximum": 12.0}}},
            "story": {"sequence": [{"section": "hook"}, {"section": "exploration"},
                                    {"section": "highlight"}, {"section": "closing"}]},
            "reel_plan": {"stale": True}, "render": {"stale": True}}


class MusicTests(unittest.TestCase):
    def test_cli_accepts_windows_music_path(self):
        args = build_parser().parse_args(["music", r"C:\Trips\Taipei", "--music", r"C:\Music\track.mp3"])
        self.assertEqual(args.command, "music")
        self.assertEqual(str(args.music_path), r"C:\Music\track.mp3")

    def test_no_music_is_explicit_and_non_mutating(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir(); payload = manifest()
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(payload))
            result = run_music(root, MusicConfig(), None)
            self.assertEqual(result["status"], "no_music")
            self.assertEqual(json.loads(path.read_text()), payload)

    def test_path_validation_fingerprint_and_cache_identity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(MusicAnalysisError, "not found"):
                music_fingerprint(root / "missing.mp3")
            unsupported = root / "track.txt"; unsupported.write_text("x")
            with self.assertRaisesRegex(MusicAnalysisError, "Unsupported"):
                analyze_music(unsupported, MusicConfig())
            wav = root / "track.wav"; pulse_wav(wav, seconds=1)
            fingerprint = music_fingerprint(wav)
            self.assertEqual(music_cache_key(fingerprint, MusicConfig()), music_cache_key(fingerprint, MusicConfig()))
            self.assertNotEqual(music_cache_key(fingerprint, MusicConfig(window_ms=25)), music_cache_key(fingerprint, MusicConfig()))

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_synthetic_analysis_is_deterministic_and_valid(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "pulse.wav"; pulse_wav(source)
            before = music_fingerprint(source)
            first = analyze_music(source, MusicConfig()); second = analyze_music(source, MusicConfig())
            self.assertEqual(first, second); self.assertEqual(before, music_fingerprint(source))
            self.assertTrue(first["validation"]["beats_monotonic"])
            self.assertTrue(first["validation"]["phrases_non_overlapping"])
            self.assertTrue(all(0 <= beat["time"] <= first["duration_seconds"] for beat in first["beats"]))
            self.assertTrue(all(0 <= point["energy"] <= 1 for point in first["energy_curve"]))
            self.assertIn("confidence", first["tempo"])
            self.assertFalse(first["validation"]["downbeats_detected"])
            self.assertTrue(validate_music_analysis(first, first["source"]["cache_key"]))
            malformed = copy.deepcopy(first); malformed["beats"] = [{"time": 99}]
            self.assertFalse(validate_music_analysis(malformed))
            silence = Path(directory) / "silence.wav"
            with wave.open(str(silence), "wb") as audio:
                audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * 44100)
            quiet = analyze_music(silence, MusicConfig())
            self.assertIsNone(quiet["tempo"]["bpm"])
            self.assertEqual(quiet["beats"], [])

    def test_duration_negotiation_and_story_mapping(self):
        direction = manifest()["creative_direction"]
        analysis = {"phrases": [{"index": 0, "start": 0, "end": 8, "energy": .2, "type": "intro"},
                                {"index": 1, "start": 8, "end": 11, "energy": .9, "type": "peak"}],
                    "sync_anchors": [{"time": 11, "type": "final_resolving_beat", "confidence": .9}],}
        aligned = negotiate_duration(direction, analysis)
        self.assertEqual(aligned["music_aligned_duration"], 11)
        self.assertTrue(8 <= aligned["music_aligned_duration"] <= 12)
        mapping = map_story_to_music(manifest()["story"], analysis)
        self.assertEqual([value["story_phase"] for value in mapping], ["hook", "exploration", "highlight", "closing"])
        retained = negotiate_duration(direction, {"phrases": [], "sync_anchors": []})
        self.assertEqual(retained["music_aligned_duration"], 10)
        too_short = negotiate_duration(direction, {"duration_seconds": 6, "phrases": [], "sync_anchors": []})
        self.assertFalse(too_short["usable_for_planning"])
        self.assertEqual(too_short["alignment_reason"], "music_too_short_for_director_envelope")

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_cache_hit_and_music_change_invalidation_preserve_upstream(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir(); path = root / "output" / "trip_manifest.json"
            payload = manifest(); payload["vision_marker"] = {"keep": True}; path.write_text(json.dumps(payload))
            first_music = root / "first.wav"; pulse_wav(first_music)
            first = run_music(root, MusicConfig(), first_music)
            self.assertFalse(first["cache_hit"]); self.assertTrue(first["invalidated_plan"])
            saved = json.loads(path.read_text()); saved["reel_plan"] = {"fresh": True}; path.write_text(json.dumps(saved))
            second = run_music(root, MusicConfig(), first_music)
            self.assertTrue(second["cache_hit"]); self.assertFalse(second["invalidated_plan"])
            self.assertIn("reel_plan", json.loads(path.read_text()))
            changed_music = root / "changed.wav"; pulse_wav(changed_music, 100)
            third = run_music(root, MusicConfig(), changed_music)
            persisted = json.loads(path.read_text())
            self.assertTrue(third["invalidated_plan"]); self.assertNotIn("reel_plan", persisted)
            self.assertEqual(persisted["events"], {"keep": True})
            self.assertEqual(persisted["vision_marker"], {"keep": True})

    def test_beat_montage_alignment_is_stronger_without_microcuts(self):
        durations = [2.0] * 9; lows = [1.0] * 9; highs = [3.0] * 9
        candidates = [{"entry": {"section": "exploration", "event_id": "one"}} for _ in durations]
        music = {"beats": [{"time": value+.1} for value in range(2, 18, 2)], "sync_anchors": []}
        cinematic, cinematic_snaps = _snap_to_music(durations, lows, highs, candidates, music, "cinematic_travel")
        montage, montage_snaps = _snap_to_music(durations, lows, highs, candidates, music, "beat_montage")
        self.assertEqual(cinematic, durations); self.assertFalse(cinematic_snaps)
        self.assertGreater(len(montage_snaps), len(cinematic_snaps))
        self.assertLess(len(montage_snaps), len(durations)-1)
        self.assertTrue(all(low <= value <= high for value, low, high in zip(montage, lows, highs)))


if __name__ == "__main__": unittest.main()
