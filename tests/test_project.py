"""Tests for recursive trip-directory scanning."""
from pathlib import Path
from travel_reel.analyzer import analyze_trip_folder

def test_scans_media_recursively(tmp_path: Path) -> None:
    (tmp_path / "Photos").mkdir(); (tmp_path / "Videos").mkdir()
    (tmp_path / "Photos" / "day-one.jpg").write_bytes(b"image")
    (tmp_path / "Videos" / "clip.mp4").write_bytes(b"video")
    (tmp_path / "notes.txt").write_text("ignore me")
    analysis = analyze_trip_folder(tmp_path)
    assert analysis.summary.total_photos == 1
    assert analysis.summary.total_videos == 1
    assert {folder.path for folder in analysis.folders} == {"Photos", "Videos"}
