"""Orchestration for persisting trip-analysis and canonical manifest results."""
from __future__ import annotations
import json
from pathlib import Path
from .analyzer import analyze_trip_folder
from .manifest import build_trip_manifest
from .models import TripAnalysis

def run_analysis(trip_folder: Path) -> tuple[TripAnalysis, Path]:
    """Analyze a trip once and write analysis.json plus trip_manifest.json."""
    analysis = analyze_trip_folder(trip_folder)
    output_folder = trip_folder / "output"
    output_folder.mkdir(parents=True, exist_ok=True)
    output_path = output_folder / "analysis.json"
    output_path.write_text(json.dumps(analysis.to_dict(), indent=2) + "\n", encoding="utf-8")
    manifest_path = output_folder / "trip_manifest.json"
    manifest_path.write_text(json.dumps(build_trip_manifest(analysis).to_dict(), indent=2) + "\n", encoding="utf-8")
    return analysis, output_path
