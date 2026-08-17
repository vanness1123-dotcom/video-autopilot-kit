"""Command-line interface for the Trip Analyzer MVP."""
from __future__ import annotations
import argparse
from pathlib import Path
from .config import load_vision_config
from .pipeline import run_analysis, run_vision

def build_parser() -> argparse.ArgumentParser:
    """Build the travel-reel command parser."""
    parser = argparse.ArgumentParser(prog="travel-reel")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="scan trip media and create analysis.json")
    analyze.add_argument("trip_folder", type=Path)
    vision = commands.add_parser("vision", help="enrich an existing Trip Manifest using local Vision")
    vision.add_argument("trip_folder", type=Path)
    vision.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
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
    elif args.command == "vision":
        trip_folder = args.trip_folder
        try:
            summary = run_vision(
                trip_folder,
                config=load_vision_config(args.config),
                progress=print,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"Vision prerequisite error: {exc}")
            return 2
        print(
            "Vision complete: "
            f"{summary['processed']} processed, "
            f"{summary['skipped']} skipped, "
            f"{summary['failed']} failed"
        )
        return 1 if summary["failed"] else 0
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
