"""Tests for persisted trip-analysis and canonical manifest JSON output."""
import json
from pathlib import Path
from travel_reel.pipeline import run_analysis

def test_writes_analysis_and_trip_manifest(tmp_path: Path) -> None:
    """One analysis run preserves analysis.json and writes separated manifest assets."""
    (tmp_path / "Photos").mkdir(); (tmp_path / "Videos").mkdir()
    (tmp_path / "Photos" / "arrival.png").write_bytes(b"not a real image")
    (tmp_path / "Videos" / "clip.mov").write_bytes(b"not a real video")
    analysis, output_path = run_analysis(tmp_path)
    analysis_payload = json.loads(output_path.read_text(encoding="utf-8"))
    manifest_path = tmp_path / "output" / "trip_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert output_path == tmp_path / "output" / "analysis.json"
    assert analysis_payload == analysis.to_dict()
    assert analysis_payload["summary"]["total_photos"] == 1
    assert manifest["manifest_version"] == "1.0"
    assert len(manifest["photos"]) == 1 and len(manifest["videos"]) == 1
    assert manifest["photos"][0]["id"].startswith("photo-")
    assert manifest["photos"][0]["selected"] is False
    assert manifest["photos"][0]["score"] is None
    assert manifest["photos"][0]["tags"] == []
    assert manifest["scenes"] == [] and manifest["story"] == {}
