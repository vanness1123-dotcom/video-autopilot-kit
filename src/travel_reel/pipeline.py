"""Orchestration for persisting trip-analysis results."""
from __future__ import annotations
import json
from pathlib import Path
from .analyzer import analyze_trip_folder
from .models import TripAnalysis

def run_analysis(trip_folder: Path) -> tuple[TripAnalysis, Path]:
    """Analyze a trip folder and write output/analysis.json."""
    analysis = analyze_trip_folder(trip_folder)
    output_path = trip_folder / "output" / "analysis.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(analysis.to_dict(), indent=2) + "\n", encoding="utf-8")
    return analysis, output_path
