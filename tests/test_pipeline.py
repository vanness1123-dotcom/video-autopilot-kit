"""Tests for persisted trip-analysis JSON output."""
import json
from pathlib import Path
from travel_reel.pipeline import run_analysis

def test_writes_clean_analysis_json(tmp_path: Path) -> None:
    (tmp_path / "arrival.png").write_bytes(b"not a real image")
    analysis, output_path = run_analysis(tmp_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert output_path == tmp_path / "output" / "analysis.json"
    assert payload["summary"]["total_photos"] == 1
    assert payload["media"][0]["path"] == "arrival.png"
    assert payload["media"][0]["size_bytes"] == 16
    assert analysis.to_dict() == payload
