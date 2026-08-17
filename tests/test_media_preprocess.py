"""Deterministic photo and video preprocessing tests."""
import shutil
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from travel_reel.media_preprocess import (
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
