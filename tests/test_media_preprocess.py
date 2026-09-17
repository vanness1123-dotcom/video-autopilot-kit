"""Deterministic photo and video preprocessing tests."""
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

from travel_reel.media_preprocess import (
    VisionPreprocessError,
    extract_video_frames,
    preprocess_photo,
    probe_video,
    representative_timestamps,
    source_fingerprint,
)


class MediaPreprocessTests(unittest.TestCase):
    def test_photo_resize_and_fingerprint_invalidation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.png"
            output = root / "cache" / "prepared.jpg"
            Image.new("RGBA", (1200, 600), (20, 40, 60, 128)).save(source)
            first_hash = source_fingerprint(source)
            preprocess_photo(source, output)
            with Image.open(output) as prepared:
                self.assertEqual(prepared.size, (768, 384))
                self.assertEqual(prepared.mode, "RGB")
            Image.new("RGB", (1200, 600), "red").save(source)
            self.assertNotEqual(first_hash, source_fingerprint(source))

    def test_representative_timestamps(self) -> None:
        self.assertEqual(representative_timestamps(3), [0.75, 2.25])
        self.assertEqual(representative_timestamps(10), [1.0, 5.0, 9.0])
        self.assertEqual(representative_timestamps(20), [2.0, 7.0, 13.0, 18.0])
        self.assertEqual(len(representative_timestamps(90)), 5)

    def test_heic_primary_decoder_success_does_not_call_ffmpeg(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.HEIC"
            output = root / "cache" / "prepared.jpg"
            Image.new("RGB", (20, 10), "green").save(source, format="PNG")
            with patch("travel_reel.media_preprocess.subprocess.run") as run:
                preprocess_photo(source, output)
            self.assertTrue(output.is_file())
            run.assert_not_called()

    def test_heic_ffmpeg_fallback_is_temporary_and_source_safe(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.HEIC"
            output = root / "cache" / "prepared.jpg"
            source.write_bytes(b"not directly decodable")
            before = source_fingerprint(source)
            decoded_paths: list[Path] = []

            def fake_run(command, **_kwargs):
                decoded = Path(command[-1])
                decoded_paths.append(decoded)
                Image.new("RGB", (40, 20), "blue").save(decoded, format="PNG")
                return SimpleNamespace(returncode=0, stderr="")

            with patch("travel_reel.media_preprocess.subprocess.run", side_effect=fake_run):
                preprocess_photo(source, output)
            self.assertTrue(output.is_file())
            self.assertEqual(source_fingerprint(source), before)
            self.assertTrue(decoded_paths)
            self.assertFalse(decoded_paths[0].exists())
            self.assertNotEqual(decoded_paths[0].parent, source.parent)

    def test_heic_fallback_failure_is_actionable_and_cleans_temp(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.HEIC"
            source.write_bytes(b"invalid")
            decoded_paths: list[Path] = []

            def fake_run(command, **_kwargs):
                decoded_paths.append(Path(command[-1]))
                return SimpleNamespace(returncode=1, stderr="decoder rejected input")

            with patch("travel_reel.media_preprocess.subprocess.run", side_effect=fake_run):
                with self.assertRaisesRegex(VisionPreprocessError, "Pillow or FFmpeg"):
                    preprocess_photo(source, root / "out.jpg")
            self.assertTrue(decoded_paths)
            self.assertFalse(decoded_paths[0].parent.exists())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
    def test_ffmpeg_frame_extraction(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            video = root / "sample.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=640x360:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", video,
            ], check=True)
            probe = probe_video(video)
            timestamps = representative_timestamps(probe.duration_seconds)
            frames = extract_video_frames(video, root / "frames", timestamps)
            self.assertEqual(len(frames), 2)
            with Image.open(frames[0]) as frame:
                self.assertEqual(frame.size, (768, 432))


if __name__ == "__main__":
    unittest.main()
