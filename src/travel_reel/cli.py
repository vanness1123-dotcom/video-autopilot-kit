"""Command-line interface for the Trip Analyzer MVP."""
from __future__ import annotations
import argparse
from pathlib import Path
from .config import load_planner_config, load_renderer_config, load_scoring_config, load_selection_config, load_story_config, load_vision_config
from .pipeline import run_analysis, run_planner, run_renderer, run_scoring, run_selection, run_story, run_vision
from .renderer import RendererPrerequisiteError

def build_parser() -> argparse.ArgumentParser:
    """Build the travel-reel command parser."""
    parser = argparse.ArgumentParser(prog="travel-reel")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="scan trip media and create analysis.json")
    analyze.add_argument("trip_folder", type=Path)
    vision = commands.add_parser("vision", help="enrich an existing Trip Manifest using local Vision")
    vision.add_argument("trip_folder", type=Path)
    vision.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    score = commands.add_parser("score", help="score Vision-enriched Trip Manifest media")
    score.add_argument("trip_folder", type=Path)
    score.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    select = commands.add_parser("select", help="build a diverse candidate pool from scores")
    select.add_argument("trip_folder", type=Path)
    select.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    story = commands.add_parser("story", help="build a narrative from Sprint 4 candidates")
    story.add_argument("trip_folder", type=Path)
    story.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    plan = commands.add_parser("plan", help="build a deterministic editing timeline from Story state")
    plan.add_argument("trip_folder", type=Path)
    plan.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    render = commands.add_parser("render", help="materialize the persisted Reel Plan as a local MP4")
    render.add_argument("trip_folder", type=Path)
    render.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
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
    elif args.command == "score":
        try:
            summary = run_scoring(args.trip_folder, load_scoring_config(args.config))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Scoring prerequisite error: {exc}")
            return 2
        distribution = summary["distribution"]
        print(
            f"Scoring complete: {summary['scored']} scored, {summary['unscoreable']} unscoreable\n"
            f"Distribution: min={distribution['minimum']} mean={distribution['mean']} "
            f"median={distribution['median']} max={distribution['maximum']}"
        )
    elif args.command == "select":
        try:
            summary = run_selection(args.trip_folder, load_selection_config(args.config))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Selection prerequisite error: {exc}")
            return 2
        details = summary["summary"]
        print(
            f"Selection complete: {details['primary_count']} primary, "
            f"{details['alternate_count']} alternates, "
            f"{len(summary['suppressed_ids'])} suppressed\n"
            f"Primary mix: {details['photos']} photos, {details['videos']} videos"
        )
    elif args.command == "story":
        try:
            story = run_story(args.trip_folder, load_story_config(args.config))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Story prerequisite error: {exc}")
            return 2
        summary = story["summary"]
        print(
            f"Story complete: {summary['item_count']} items, {summary['section_count']} sections, "
            f"{summary['alternate_count']} alternates\n"
            f"Arc: {' -> '.join(story['structure'])}"
        )
    elif args.command == "plan":
        try:
            plan = run_planner(args.trip_folder, load_planner_config(args.config))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Planner prerequisite error: {exc}")
            return 2
        summary = plan["summary"]
        print(
            f"Planning complete: {summary['planned_shot_count']} shots, "
            f"{summary['photos']} photos, {summary['videos']} videos, "
            f"{plan['actual_duration_seconds']:.3f}s"
        )
    elif args.command == "render":
        try:
            state, output_path = run_renderer(args.trip_folder, load_renderer_config(args.config))
        except (FileNotFoundError, RendererPrerequisiteError) as exc:
            print(f"Renderer prerequisite error: {exc}")
            return 2
        except (ValueError, RuntimeError) as exc:
            print(f"Renderer error: {exc}")
            return 1
        print(
            "Render complete:\n"
            f"Output: {output_path}\n"
            f"Duration: {state['duration_seconds']:.3f}s\n"
            f"Resolution: {state['width']}x{state['height']}\n"
            f"Shots: {state['shot_count']}\n"
            f"Photos: {state['photo_count']}\n"
            f"Videos: {state['video_count']}"
        )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
