"""Command-line interface for the Trip Analyzer MVP."""
from __future__ import annotations
import argparse
from pathlib import Path
from .pipeline import run_analysis

def build_parser() -> argparse.ArgumentParser:
    """Build the travel-reel command parser."""
    parser = argparse.ArgumentParser(prog="travel-reel")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="scan trip media and create analysis.json")
    analyze.add_argument("trip_folder", type=Path)
    return parser

def main(argv: list[str] | None = None) -> int:
    """Run the requested travel-reel command."""
    args = build_parser().parse_args(argv)
    if args.command == "analyze":
        trip_folder: Path = args.trip_folder
        print(f"Scanning {trip_folder.name}...")
        analysis, output_path = run_analysis(trip_folder)
        summary = analysis.summary
        print(f"\nPhotos : {summary.total_photos}\nVideos : {summary.total_videos}")
        print(f"GPS : {'Available' if summary.gps_available else 'Unavailable'}")
        print("Date Range :")
        print(summary.date_range_start or "Unavailable")
        print("~")
        print(summary.date_range_end or "Unavailable")
        print(f"\nOutput:\n{output_path.relative_to(trip_folder)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
