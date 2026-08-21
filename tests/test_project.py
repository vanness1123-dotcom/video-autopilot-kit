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

def test_excludes_derived_directory_trees_and_preserves_media_ids(tmp_path: Path) -> None:
    source_photo = tmp_path / "Photos" / "day-one.jpg"
    source_video = tmp_path / "Videos" / "clip.mp4"
    source_photo.parent.mkdir(); source_video.parent.mkdir()
    source_photo.write_bytes(b"image"); source_video.write_bytes(b"video")

    before = analyze_trip_folder(tmp_path)
    original_ids = {item.path: item.id for item in [*before.photos, *before.videos]}

    cached_photo = tmp_path / ".travel_reel_cache" / "vision" / "photos" / "prepared.jpg"
    cached_frame = tmp_path / ".travel_reel_cache" / "vision" / "videos" / "clip" / "frame-001.jpg"
    rendered_photo = tmp_path / "output" / "nested" / "thumbnail.jpeg"
    for derived_file in (cached_photo, cached_frame, rendered_photo):
        derived_file.parent.mkdir(parents=True, exist_ok=True)
        derived_file.write_bytes(b"derived")

    after = analyze_trip_folder(tmp_path)
    assert {item.path for item in after.photos} == {Path("Photos/day-one.jpg")}
    assert {item.path for item in after.videos} == {Path("Videos/clip.mp4")}
    assert after.summary.total_photos == before.summary.total_photos == 1
    assert after.summary.total_videos == before.summary.total_videos == 1
    assert {item.path: item.id for item in [*after.photos, *after.videos]} == original_ids
    assert {folder.path for folder in after.folders} == {"Photos", "Videos"}
