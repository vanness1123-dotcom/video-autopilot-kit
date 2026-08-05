"""Tests for media detection and video-metadata extraction."""
from datetime import UTC, datetime
from pathlib import Path
from travel_reel.analyzer import detect_media_kind, extract_video_creation_time

def test_detects_supported_media_extensions() -> None:
    assert detect_media_kind(Path("photo.JPEG")) == "photo"
    assert detect_media_kind(Path("clip.mov")) == "video"
    assert detect_media_kind(Path("notes.txt")) is None

def test_extracts_mp4_movie_creation_time(tmp_path: Path) -> None:
    timestamp = int((datetime(2026, 7, 24, tzinfo=UTC) - datetime(1904, 1, 1, tzinfo=UTC)).total_seconds())
    payload = b"\x00\x00\x00\x00" + timestamp.to_bytes(4, "big") + b"\x00" * 12
    mvhd = (len(payload) + 8).to_bytes(4, "big") + b"mvhd" + payload
    moov = (len(mvhd) + 8).to_bytes(4, "big") + b"moov" + mvhd
    path = tmp_path / "clip.mp4"; path.write_bytes(moov)
    assert extract_video_creation_time(path) == datetime(2026, 7, 24, tzinfo=UTC)
