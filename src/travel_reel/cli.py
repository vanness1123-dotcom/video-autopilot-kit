"""Command-line interface for the Trip Analyzer MVP."""
from __future__ import annotations
import argparse
from pathlib import Path
from .config import load_creative_director_config, load_event_config, load_layout_config, load_music_config, load_planner_config, load_renderer_config, load_scoring_config, load_selection_config, load_story_config, load_template_config, load_vision_config
from .pipeline import run_analysis, run_director, run_events, run_layout_planner, run_music, run_music_selection, run_planner, run_renderer, run_scoring, run_selection, run_story, run_template_planner, run_vision
from .music import MusicAnalysisError
from .music_library import MusicLibraryError, import_track
from .music_arrangement import MusicAssemblyError
from .renderer import RendererPrerequisiteError
from .templates import TemplateValidationError
from .layout import LayoutValidationError
from .pipeline import run_media_metadata_enrichment, run_overlay_planner
from .pipeline import run_motion_planner
from .config import load_motion_config, load_typography_config

def build_parser() -> argparse.ArgumentParser:
    """Build the travel-reel command parser."""
    parser = argparse.ArgumentParser(prog="travel-reel")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="scan trip media and create analysis.json")
    analyze.add_argument("trip_folder", type=Path)
    motion = commands.add_parser("motion-plan", help="resolve inherited-window Motion without rendering")
    motion.add_argument("trip_folder", type=Path)
    motion.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    overlay = commands.add_parser("overlay-plan", help="resolve static renderer-independent text overlays")
    overlay.add_argument("trip_folder", type=Path)
    overlay.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    enrich = commands.add_parser("enrich-media-metadata", help="enrich original source dimensions without rerunning editorial stages")
    enrich.add_argument("trip_folder", type=Path)
    enrich.add_argument("--config", type=Path, default=Path("configs/default.yaml"),
                        help="accepted for CLI consistency; source dimension extraction has no configurable policy")
    vision = commands.add_parser(
        "vision",
        help="enrich an existing Trip Manifest using local Vision",
        description=(
            "Analyze media locally. Ordinary reruns automatically reuse valid unchanged "
            "results and retry only failed, incomplete, changed, or invalid items."
        ),
    )
    vision.add_argument("trip_folder", type=Path)
    vision.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    score = commands.add_parser("score", help="score Vision-enriched Trip Manifest media")
    score.add_argument("trip_folder", type=Path)
    score.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    events = commands.add_parser("events", help="group Vision-enriched media into coherent travel events")
    events.add_argument("trip_folder", type=Path)
    events.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    direct = commands.add_parser("direct", help="derive editorial strategy from persisted Events")
    direct.add_argument("trip_folder", type=Path)
    direct.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    select = commands.add_parser("select", help="build a diverse candidate pool from scores")
    select.add_argument("trip_folder", type=Path)
    select.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    story = commands.add_parser("story", help="build a narrative from Sprint 4 candidates")
    story.add_argument("trip_folder", type=Path)
    story.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    music = commands.add_parser("music", help="analyze optional user-supplied local music")
    music.add_argument("trip_folder", type=Path)
    music.add_argument("--music", dest="music_path", type=Path)
    music.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    music_import = commands.add_parser("music-import", help="import one licensed or user-owned track into the local library")
    music_import.add_argument("--file", dest="music_file", type=Path, required=True)
    music_import.add_argument("--library", type=Path)
    music_import.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    music_import.add_argument("--title")
    music_import.add_argument("--creator")
    music_import.add_argument("--source", dest="source_name")
    music_import.add_argument("--source-page")
    music_import.add_argument("--license", dest="license_name")
    music_import.add_argument("--license-url")
    attribution = music_import.add_mutually_exclusive_group()
    attribution.add_argument("--attribution-required", action="store_true", dest="attribution_required")
    attribution.add_argument("--no-attribution-required", action="store_false", dest="attribution_required")
    music_import.set_defaults(attribution_required=None)
    music_import.add_argument("--attribution-text")
    music_import.add_argument("--downloaded-at")
    music_import.add_argument("--source-notes")
    music_select = commands.add_parser("music-select", help="rank and select tracks from a local managed library")
    music_select.add_argument("trip_folder", type=Path)
    music_select.add_argument("--library", type=Path)
    music_select.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    plan = commands.add_parser("plan", help="build a deterministic editing timeline from Story state")
    plan.add_argument("trip_folder", type=Path)
    plan.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    template_plan = commands.add_parser("template-plan", help="resolve a rendering-independent visual template plan")
    template_plan.add_argument("trip_folder", type=Path)
    template_plan.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    layout_plan = commands.add_parser("layout-plan", help="resolve static spatial layouts inside the Visual Plan")
    layout_plan.add_argument("trip_folder", type=Path)
    layout_plan.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    render = commands.add_parser("render", help="materialize the persisted Reel Plan as a local MP4")
    render.add_argument("trip_folder", type=Path)
    render.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    return parser

def main(argv: list[str] | None = None) -> int:
    """Run the requested travel-reel command."""
    args = build_parser().parse_args(argv)
    if args.command == "motion-plan":
        try:
            visual = run_motion_planner(args.trip_folder, load_motion_config(args.config))
        except (OSError, ValueError) as exc:
            print(f"Motion prerequisite/validation error: {exc}")
            return 2
        print(f"Motion planning complete: blocks={len(visual['blocks'])} "
              f"tracks={sum(len(b['resolved_motion']['tracks']) for b in visual['blocks'])} "
              f"duration={visual['duration_seconds']:.3f}s Validation: PASS")
    elif args.command == "overlay-plan":
        try:
            visual = run_overlay_planner(args.trip_folder, load_typography_config(args.config))
        except (OSError, ValueError) as exc:
            print(f"Overlay prerequisite/validation error: {exc}")
            return 2
        count = sum(len(b.get("resolved_overlay", {}).get("overlays", [])) for b in visual["blocks"])
        print(f"Overlay planning complete: blocks={len(visual['blocks'])} overlays={count} "
              f"duration={visual['duration_seconds']:.3f}s Validation: PASS")
    elif args.command == "enrich-media-metadata":
        try:
            summary = run_media_metadata_enrichment(args.trip_folder)
        except (OSError, ValueError) as exc:
            print(f"Media metadata prerequisite error: {exc}")
            return 2
        print("Media metadata: " + " ".join(f"{key}={summary[key]}" for key in ("known", "enriched", "unchanged", "failed")))
        for error in summary["errors"]:
            print(f"- {error['media_id']} | {error['source_path']} | {error['error']}")
        print("Existing Reel Plan is preserved. A future explicit replan may produce different framing decisions after canonical dimensions become available.")
        print("Changed dimensions invalidate resolved layouts and render state. Run layout-plan explicitly.")
        return 1 if summary["failed"] else 0
    elif args.command == "analyze":
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
            "Vision complete:\n"
            f"Total: {summary['total']}\nProcessed: {summary['processed']}\n"
            f"Cached: {summary['cached']}\nRetried: {summary['retried']}\n"
            f"Recovered: {summary['recovered']}\nFailed: {summary['failed']}"
        )
        if summary["errors"]:
            print("Failed media:")
            for error in summary["errors"]:
                retried = "yes" if error["retry_attempted"] else "no"
                print(
                    f"- {error['source_path']} | {error['media_id']} | "
                    f"{error['failure_type']} | retry attempted: {retried}"
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
    elif args.command == "direct":
        try:
            direction = run_director(args.trip_folder, load_creative_director_config(args.config))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Creative Director prerequisite error: {exc}")
            return 2
        budget = direction["media_budget"]
        duration = direction.get("duration_strategy", {})
        print(f"Creative Direction complete: {direction['style']}, {direction['pacing']['overall']} pacing, "
              f"target {budget['target_shots']} shots ({budget['minimum_shots']}..{budget['maximum_shots']}), "
              f"duration {duration.get('resolved_seconds')}s "
              f"({duration.get('minimum_seconds')}..{duration.get('maximum_seconds')}s)")
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
    elif args.command == "events":
        try:
            state = run_events(args.trip_folder, load_event_config(args.config))
        except (FileNotFoundError, ValueError) as exc:
            print(f"Events prerequisite error: {exc}")
            return 2
        print(f"Events complete: {state['summary']['event_count']} events, {state['summary']['media_count']} media grouped")
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
    elif args.command == "music":
        try:
            result = run_music(args.trip_folder, load_music_config(args.config), args.music_path)
        except (FileNotFoundError, ValueError, MusicAnalysisError) as exc:
            print(f"Music analysis error: {exc}")
            return 2
        if result["status"] == "no_music":
            print("Music analysis: no local music supplied; existing no-music planning remains active")
            return 0
        analysis = result["music_analysis"]
        tempo = analysis["tempo"]
        peak = next((region for region in analysis["structure"] if region["type"] == "peak"), None)
        print(
            "Music analysis complete\n"
            f"Duration: {analysis['duration_seconds']:.3f}s\n"
            f"BPM: {tempo['bpm']} (confidence {tempo['confidence']})\n"
            f"Beats: {len(analysis['beats'])}\nPhrases: {len(analysis['phrases'])}\n"
            f"Peak region: {peak['start'] if peak else 'unavailable'}..{peak['end'] if peak else 'unavailable'}\n"
            f"Music-aligned Reel duration: {analysis['duration_alignment']['music_aligned_duration']:.3f}s\n"
            f"Cache: {'hit' if result['cache_hit'] else 'miss'}"
        )
    elif args.command == "music-import":
        metadata = {
            key: getattr(args, key) for key in (
                "title", "creator", "source_name", "source_page", "license_name",
                "license_url", "attribution_required", "attribution_text", "downloaded_at",
                "source_notes",
            )
        }
        try:
            config = load_music_config(args.config)
            library = args.library or Path(config.library_path)
            result = import_track(args.music_file, library, metadata)
        except (MusicLibraryError, OSError, ValueError) as exc:
            print(f"Music import error: {exc}")
            return 2
        track = result["track"]
        print(
            "Music import complete\n"
            f"Track ID: {track['track_id']}\n"
            f"File: {result['managed_path']}\n"
            f"Status: {track['metadata_status']}\n"
            f"Engineering usable: {str(track['engineering_usable']).lower()}\n"
            f"Production ready: {str(track['production_ready']).lower()}\n"
            f"Import: {'duplicate' if result['duplicate'] else 'copied'}"
        )
    elif args.command == "music-select":
        try:
            result = run_music_selection(
                args.trip_folder, load_music_config(args.config), args.library,
            )
        except (FileNotFoundError, MusicLibraryError, MusicAssemblyError, ValueError) as exc:
            print(f"Music selection error: {exc}")
            return 2
        print(
            f"Music candidates: {result['candidates']}\nAnalyzable: {result['eligible']}\n"
            f"Single-track eligible: {result['single_track_eligible']}\n"
            f"Multi-track eligible: {result['multi_track_eligible']}\n"
            f"Analyzed: {result['analyzed']}\nCached: {result['cached']}"
        )
        strategy = result["strategy"]
        if strategy is None:
            print("No local music candidates found.\nAdd royalty-free/user-owned tracks to the configured music library.")
            return 0
        print(f"Selected strategy: {strategy['strategy_type']}\nStrategy score: {strategy['strategy_score']}\n"
              f"Timeline duration: {strategy['timeline_duration_seconds']}s\nTrack count: {strategy['track_count']}")
        for index, segment in enumerate(strategy["segments"], 1):
            print(f"{index}. {segment['track_id']}\n   source {segment['source_start_seconds']}..{segment['source_end_seconds']}\n"
                  f"   timeline {segment['timeline_start_seconds']}..{segment['timeline_end_seconds']}\n"
                  f"   detected BPM {segment['detected_bpm']}\n   effective BPM {segment['effective_bpm']}\n"
                  f"   story role {','.join(segment['story_phase_mapping']) or segment['energy_role']}")
            if index <= len(strategy["transitions"]):
                transition = strategy["transitions"][index-1]
                print(f"Transition: {transition['type']} {transition['duration_seconds']}s")
        if result["alternatives"]:
            print("Top strategy alternatives:")
            for alternative in result["alternatives"]:
                print(f"- {alternative['strategy_type']} {alternative['strategy_id']}: {alternative['strategy_score']}")
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
    elif args.command == "template-plan":
        try:
            visual=run_template_planner(args.trip_folder,load_template_config(args.config))
        except (FileNotFoundError,ValueError,TemplateValidationError) as exc:
            print(f"Template planning error: {exc}"); return 2
        validation=visual["validation"]
        print("Template planning complete:\n"
              f"Template: {visual['template_id']}\nDuration: {visual['duration_seconds']:.3f}s\n"
              f"Visual blocks: {len(visual['blocks'])}\nShots assigned: {validation['assigned_shot_count']}/{validation['planned_shot_count']}\n"
              f"Story phases: {len(visual['story_phases'])}\nBeat-aware blocks: {validation['beat_aware_block_count']}\nValidation: PASS")
    elif args.command == "layout-plan":
        try:
            visual=run_layout_planner(args.trip_folder,load_layout_config(args.config))
        except (FileNotFoundError,ValueError,LayoutValidationError) as exc:
            print(f"Layout planning error: {exc}"); return 2
        print("Layout planning complete:\n"
              f"Version: {visual['blocks'][0]['resolved_layout']['version']}\n"
              f"Visual blocks: {len(visual['blocks'])}\n"
              f"Spatial slots: {sum(len(block['resolved_layout']['slots']) for block in visual['blocks'])}\n"
              f"Duration: {visual['duration_seconds']:.3f}s\nValidation: PASS")
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
