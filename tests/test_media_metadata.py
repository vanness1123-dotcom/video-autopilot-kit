"""Canonical original dimensions and narrowly scoped existing-manifest migration."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from travel_reel.analyzer import analyze_trip_folder
from travel_reel.cli import main
from travel_reel.layout import _orientation, resolve_layouts
from travel_reel.manifest import build_trip_manifest, load_trip_manifest
from travel_reel.media_preprocess import extract_media_dimensions, VideoProbe, VisionPreprocessError
from travel_reel.pipeline import run_media_metadata_enrichment


class MediaMetadataTests(unittest.TestCase):
    def test_photo_exif_axes_and_source_unchanged(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "photo.jpg"
            for orientation in range(1, 9):
                with self.subTest(exif=orientation):
                    exif = Image.Exif(); exif[274] = orientation
                    Image.new("RGB", (40, 20)).save(path, exif=exif)
                    before = path.read_bytes()
                    facts = extract_media_dimensions(path, "photo")
                    self.assertEqual((facts["width"], facts["height"]),
                                     (20, 40) if orientation >= 5 else (40, 20))
                    self.assertEqual(facts["orientation"], "portrait" if orientation >= 5 else "landscape")
                    self.assertEqual(path.read_bytes(), before)

    def test_portrait_square_and_missing_photo(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "photo.png"
            for size, orientation in (((20, 40), "portrait"), ((20, 20), "square")):
                Image.new("RGB", size).save(path)
                self.assertEqual(extract_media_dimensions(path, "photo")["orientation"], orientation)
            path.write_bytes(b"corrupt")
            with self.assertRaises(VisionPreprocessError):
                extract_media_dimensions(path, "photo")

    def test_video_rotation_and_failure(self):
        for rotation in (0, 90, -90, 180, 270):
            with self.subTest(rotation=rotation), patch("travel_reel.media_preprocess.probe_video",
                    return_value=VideoProbe(5, 3840, 2160, rotation)):
                result = extract_media_dimensions(Path("source.mov"), "video")
                self.assertEqual((result["width"], result["height"]),
                                 (2160, 3840) if rotation % 180 else (3840, 2160))
        for probe in (VideoProbe(5, None, 20, 0), VideoProbe(5, 20, 40, 45)):
            with patch("travel_reel.media_preprocess.probe_video", return_value=probe):
                with self.assertRaises(VisionPreprocessError):
                    extract_media_dimensions(Path("source.mov"), "video")
        with patch("travel_reel.media_preprocess.probe_video", side_effect=VisionPreprocessError("failed")):
            with self.assertRaises(VisionPreprocessError):
                extract_media_dimensions(Path("source.mov"), "video")

    def test_heif_fallback_full_size_and_cleanup(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "photo.heif"; path.write_bytes(b"unsupported")
            decoded = []
            def run(command, **kwargs):
                decoded.append(Path(command[-1]))
                Image.new("RGB", (1200, 2400)).save(decoded[-1])
                return SimpleNamespace(returncode=0, stderr="")
            with patch("travel_reel.media_preprocess.subprocess.run", side_effect=run):
                self.assertEqual(extract_media_dimensions(path, "photo")["height"], 2400)
            self.assertFalse(decoded[0].exists())
            self.assertEqual(path.read_bytes(), b"unsupported")
            with patch("travel_reel.media_preprocess.subprocess.run", return_value=SimpleNamespace(returncode=1, stderr="bad")):
                with self.assertRaises(VisionPreprocessError):
                    extract_media_dimensions(path, "photo")

    def test_analyzer_and_both_serializations(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            exif = Image.Exif(); exif[274] = 6
            Image.new("RGB", (40, 20)).save(root / "photo.jpg", exif=exif)
            (root / "clip.mov").write_bytes(b"fixture")
            with patch("travel_reel.media_preprocess.probe_video", return_value=VideoProbe(5, 80, 40, -90)):
                trip = analyze_trip_folder(root)
            self.assertEqual((trip.photos[0].width, trip.photos[0].height), (20, 40))
            self.assertEqual((trip.videos[0].width, trip.videos[0].height), (40, 80))
            analysis = trip.to_dict(); manifest = build_trip_manifest(trip).to_dict()
            for item in analysis["media"] + manifest["photos"] + manifest["videos"]:
                self.assertEqual(item["orientation"], "portrait")
                self.assertLess(item["width"], item["height"])

    def test_enrichment_preservation_invalidation_and_idempotence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            Image.new("RGB", (20, 40)).save(root / "photo.png")
            manifest = {"trip": {}, "photos": [{"id": "photo-1", "path": "photo.png",
                "vision": {"vision_metadata": {"cache_key": "unchanged", "source_fingerprint": "same"}},
                "score": {"total": 85}, "selection": {"status": "primary"}}], "videos": [],
                "visual_plan": {"blocks": [{"shots": [{"media_id": "photo-1"}], "resolved_layout": {"old": True}}]},
                "render": {"path": "reel.mp4"}}
            for key in ("events", "creative_direction", "selection", "story", "music_analysis", "music_selection", "reel_plan", "template_definition"):
                manifest[key] = {"preserved": [key]}
            path = root / "output" / "trip_manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(_orientation(load_trip_manifest(path)["photos"][0]), "unknown")
            summary = run_media_metadata_enrichment(root)
            self.assertEqual([summary[k] for k in ("known", "enriched", "unchanged", "failed")], [1, 1, 0, 0])
            enriched = load_trip_manifest(path)
            self.assertEqual(_orientation(enriched["photos"][0]), "portrait")
            expected = copy.deepcopy(manifest)
            expected["photos"][0].update(width=20, height=40, orientation="portrait")
            del expected["render"]; del expected["visual_plan"]["blocks"][0]["resolved_layout"]
            self.assertEqual(enriched, expected)
            # A subsequent layout/render must survive a no-change metadata run.
            enriched["visual_plan"]["blocks"][0]["resolved_layout"] = {"new": True}
            enriched["render"] = {"new": True}
            path.write_text(json.dumps(enriched), encoding="utf-8")
            before = path.read_bytes()
            second = run_media_metadata_enrichment(root)
            self.assertEqual([second[k] for k in ("known", "enriched", "unchanged", "failed")], [1, 0, 1, 0])
            self.assertEqual(path.read_bytes(), before)

    def test_partial_failure_preserves_valid_metadata_and_rejects_escape(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            Image.new("RGB", (40, 20)).save(root / "good.png")
            manifest = {"trip": {}, "photos": [
                {"id": "good", "path": "good.png"},
                {"id": "missing", "path": "missing.png", "width": 20, "height": 40, "orientation": "portrait"},
                {"id": "escape", "path": "../outside.png"}], "videos": []}
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(manifest), encoding="utf-8")
            summary = run_media_metadata_enrichment(root)
            self.assertEqual([summary[k] for k in ("known", "enriched", "unchanged", "failed")], [2, 1, 0, 2])
            result = load_trip_manifest(path)
            self.assertEqual(result["photos"][1:], manifest["photos"][1:])
            self.assertEqual(_orientation(result["photos"][0]), "landscape")
            self.assertIn("escapes", summary["errors"][1]["error"])
            self.assertFalse(path.with_name(".trip_manifest.json.tmp").exists())

    def test_cli_explicit_command(self):
        with patch("travel_reel.cli.run_media_metadata_enrichment", return_value={
                "known": 1, "enriched": 1, "unchanged": 0, "failed": 0, "errors": []}) as run:
            self.assertEqual(main(["enrich-media-metadata", "trip", "--config", "configs/default.yaml"]), 0)
            run.assert_called_once_with(Path("trip"))

    def test_enrichment_to_layout_uses_canonical_lookup(self):
        from tests.test_layout import fixture
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir(); (root / "Photos").mkdir()
            manifest = fixture("two_up", orientations=["unknown", "unknown"])
            manifest["visual_plan"] = resolve_layouts(manifest, manifest["visual_plan"])
            self.assertIn("orientation_signature:unknown+unknown",
                          manifest["visual_plan"]["blocks"][0]["resolved_layout"]["selection_reasons"])
            for item in manifest["photos"]:
                Image.new("RGB", (40, 20)).save(root / item["path"])
            path = root / "output" / "trip_manifest.json"; path.write_text(json.dumps(manifest), encoding="utf-8")
            run_media_metadata_enrichment(root)
            enriched = load_trip_manifest(path)
            resolved = resolve_layouts(enriched, enriched["visual_plan"])
            self.assertIn("orientation_signature:landscape+landscape",
                          resolved["blocks"][0]["resolved_layout"]["selection_reasons"])
            self.assertEqual(resolved["blocks"][0]["shots"], manifest["visual_plan"]["blocks"][0]["shots"])

    def test_analyzer_dimension_failure_is_explicit(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "bad.jpg").write_bytes(b"bad")
            with self.assertWarns(RuntimeWarning):
                trip = analyze_trip_folder(root)
            self.assertIsNone(trip.photos[0].width)
            self.assertIsNone(trip.photos[0].height)

    def test_atomic_failure_keeps_original_manifest(self):
        with TemporaryDirectory() as directory:
            root = Path(directory); (root / "output").mkdir()
            Image.new("RGB", (20, 40)).save(root / "photo.png")
            path = root / "output" / "trip_manifest.json"
            path.write_text(json.dumps({"trip": {}, "photos": [{"id": "p", "path": "photo.png"}], "videos": []}), encoding="utf-8")
            before = path.read_bytes()
            with patch("travel_reel.manifest.os.replace", side_effect=OSError("write failed")):
                with self.assertRaises(OSError):
                    run_media_metadata_enrichment(root)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(path.with_name(".trip_manifest.json.tmp").exists())
