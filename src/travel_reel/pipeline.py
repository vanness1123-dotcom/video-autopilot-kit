"""Orchestration for persisting trip-analysis and canonical manifest results."""
from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Callable
from .analyzer import analyze_trip_folder
from .config import CreativeDirectorConfig, LayoutConfig, MusicConfig, PlannerConfig, RendererConfig, ScoringConfig, SelectionConfig, StoryConfig, TemplateConfig, VisionConfig, load_vision_config
from .director import CreativeDirectorProvider, DeterministicCreativeDirector
from .manifest import (
    advance_manifest_version,
    build_trip_manifest,
    enrich_manifest_media,
    load_trip_manifest,
    save_trip_manifest_atomic,
)
from .media_preprocess import (
    VisionPreprocessError,
    extract_video_frames,
    preprocess_photo,
    probe_video,
    representative_timestamps,
    source_fingerprint,
    extract_media_dimensions,
    canonical_dimensions,
)
from .planner import build_reel_plan
from .events import group_manifest_events
from .renderer import render_reel
from .music_arrangement import assemble_music, generate_strategies
from .models import Trip
from .scoring import score_manifest
from .selector import select_manifest
from .story import DeterministicStoryProvider, StoryProvider, validate_story
from .config import EventConfig
from .vision import (
    VisionError,
    VisionProvider,
    metadata_for_result,
    validate_vision_result,
    vision_cache_key,
)
from .vision_local import LocalVisionProvider
from .music import analyze_music_cached, map_story_to_music, negotiate_duration
from .music_library import rank_library
from .templates import get_builtin_template, resolve_visual_plan
from .layout import resolve_layouts
from .motion import resolve_motion, validate_motion_plan
from .typography import TypographyConfig, resolve_plan_typography
from .config import MotionConfig
from .overlay import resolve_overlay, validate_overlay_plan
import copy


def _invalidate_motion_downstream(manifest):
    manifest.pop("render", None)
    # Reserved explicit resolved overlay state; template typography/decorations are intent.
    manifest.pop("overlay_plan", None)
    for block in (manifest.get("visual_plan") or {}).get("blocks", []):
        block.pop("resolved_overlay", None)


def _semantic_visual(plan):
    result = copy.deepcopy(plan)
    if isinstance(result, dict):
        for block in result.get("blocks", []):
            for key in ("resolved_layout", "resolved_motion", "resolved_overlay"):
                block.pop(key, None)
    return result


def run_motion_planner(trip_folder: Path, config: MotionConfig):
    path = trip_folder.resolve() / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(path)
    visual = manifest.get("visual_plan")
    resolved = resolve_motion(manifest, visual, enabled=config.enabled)
    changed = visual != resolved
    manifest["visual_plan"] = resolved
    if changed: _invalidate_motion_downstream(manifest)
    previous_version = manifest.get("manifest_version")
    advance_manifest_version(manifest, "1.10")
    if changed or manifest.get("manifest_version") != previous_version:
        save_trip_manifest_atomic(path, manifest)
    return resolved

def run_overlay_planner(trip_folder: Path, config: TypographyConfig | None = None) -> dict[str, object]:
    """Resolve static, renderer-independent overlays from existing contracts."""
    root = trip_folder.resolve(); manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    visual = manifest.get("visual_plan")
    if isinstance(visual, dict):
        for block in visual.get("blocks", []):
            if not isinstance(block.get("resolved_layout"), dict):
                raise ValueError("Resolved Layout missing. Run 'layout-plan' first.")
            if not isinstance(block.get("resolved_motion"), dict):
                raise ValueError("Resolved Motion missing. Run 'motion-plan' first.")
    # Motion validation also validates Layout and inherited Reel/layer ownership.
    validate_motion_plan(visual, visual, manifest)
    resolved = resolve_overlay(manifest, visual)
    validate_overlay_plan(resolved, visual, manifest)
    from .placement_contract import resolve_plan_placement
    resolved = resolve_plan_placement(manifest, resolved, config)
    from .overlay_density import resolve_density
    resolved = resolve_density(manifest, resolved)
    validate_overlay_plan(resolved, visual, manifest)
    changed = visual != resolved
    manifest["visual_plan"] = resolved
    if changed:
        manifest.pop("render", None); manifest.pop("overlay_plan", None)
    previous_version = manifest.get("manifest_version")
    advance_manifest_version(manifest, "1.15")
    if changed or manifest.get("manifest_version") != previous_version:
        save_trip_manifest_atomic(manifest_path, manifest)
    return resolved

def run_media_metadata_enrichment(trip_folder: Path) -> dict[str, object]:
    """Atomically enrich objective facts, preserving editorial state and Vision identity."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    summary = {"known": 0, "enriched": 0, "unchanged": 0, "failed": 0, "errors": []}
    spatial_changed = False
    for kind, collection in (("photo", "photos"), ("video", "videos")):
        for item in manifest[collection]:
            try:
                if not isinstance(item, dict):
                    raise VisionPreprocessError("Invalid canonical media record")
                source = _resolve_media_source(root, item.get("path"))
                dimensions = extract_media_dimensions(source, kind)
                if any(item.get(key) != value for key, value in dimensions.items()):
                    spatial_changed |= any(item.get(key) != dimensions[key] for key in ("width", "height"))
                    item.update(dimensions)
                    summary["enriched"] += 1
                else:
                    summary["unchanged"] += 1
            except (VisionPreprocessError, OSError, ValueError) as exc:
                summary["failed"] += 1
                summary["errors"].append({"media_id": item.get("id") if isinstance(item, dict) else None,
                                          "source_path": item.get("path") if isinstance(item, dict) else None,
                                          "error": str(exc)})
            if isinstance(item, dict):
                try:
                    canonical_dimensions(item.get("width"), item.get("height"))
                    summary["known"] += 1
                except VisionPreprocessError:
                    pass
    if spatial_changed:
        visual = manifest.get("visual_plan")
        if isinstance(visual, dict):
            for block in visual.get("blocks", []):
                if isinstance(block, dict):
                    block.pop("resolved_layout", None)
                    block.pop("resolved_motion", None)
        _invalidate_motion_downstream(manifest)
    if summary["enriched"]:
        save_trip_manifest_atomic(manifest_path, manifest)
    return summary


def run_analysis(trip_folder: Path) -> tuple[Trip, Path]:
    """Analyze a trip once and write analysis.json plus trip_manifest.json."""
    analysis = analyze_trip_folder(trip_folder)
    output_folder = trip_folder / "output"
    output_folder.mkdir(parents=True, exist_ok=True)
    output_path = output_folder / "analysis.json"
    output_path.write_text(json.dumps(analysis.to_dict(), indent=2) + "\n", encoding="utf-8")
    manifest_path = output_folder / "trip_manifest.json"
    manifest_path.write_text(json.dumps(build_trip_manifest(analysis).to_dict(), indent=2) + "\n", encoding="utf-8")
    return analysis, output_path


def run_vision(
    trip_folder: Path,
    config: VisionConfig | None = None,
    provider: VisionProvider | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Enrich an existing manifest with isolated, resumable Vision results."""
    config = config or load_vision_config()
    if config.provider != "local" and provider is None:
        raise ValueError(f"Unsupported Vision provider: {config.provider}")
    provider = provider or LocalVisionProvider(
        model=config.model,
        endpoint=config.endpoint,
        timeout_seconds=config.timeout_seconds,
        retries=config.retries,
    )
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    cache_root = root / Path(config.cache_dir_name)
    total = sum(len(manifest.get(key, [])) for key in ("photos", "videos"))
    counts = {
        "total": total, "processed": 0, "new_processed": 0,
        "retry_processed": 0, "retried": 0, "recovered": 0,
        "structured_recovered": 0,
        "cached": 0, "skipped": 0, "failed": 0, "errors": [],
    }
    position = 0

    for media_type, collection in (("photo", "photos"), ("video", "videos")):
        for item in manifest[collection]:
            position += 1
            media_id = item.get("id", "unknown")
            source_path = str(item.get("path", "unknown"))
            was_retry = isinstance(item.get("vision_error"), dict) or (
                "vision" in item and not validate_vision_result(item.get("vision"))
            )
            try:
                source = _resolve_media_source(root, item.get("path"))
                source_hash = source_fingerprint(source)
                cache_key = vision_cache_key(source_hash, provider.name, provider.model, media_type)
                existing = item.get("vision")
                metadata = existing.get("vision_metadata", {}) if isinstance(existing, dict) else {}
                if (
                    validate_vision_result(existing)
                    and metadata.get("cache_key") == cache_key
                    and metadata.get("source_fingerprint") == source_hash
                ):
                    counts["skipped"] += 1
                    counts["cached"] += 1
                    _vision_progress(progress, position, total, "CACHED", source_path, counts)
                    continue

                if was_retry:
                    counts["retried"] += 1
                if hasattr(provider, "last_recovery_attempted"):
                    provider.last_recovery_attempted = False  # type: ignore[attr-defined]
                if hasattr(provider, "last_recovered"):
                    provider.last_recovered = False  # type: ignore[attr-defined]
                _vision_progress(progress, position, total, "VISION", source_path, counts)
                if media_type == "photo":
                    prepared = cache_root / "photos" / f"{source_hash}.jpg"
                    preprocess_photo(source, prepared, config.longest_edge, config.jpeg_quality)
                    result = provider.analyze_photo(media_id, prepared)
                    timestamps = None
                else:
                    probe = probe_video(source)
                    timestamps = representative_timestamps(probe.duration_seconds)
                    frames = extract_video_frames(
                        source, cache_root / "videos" / cache_key, timestamps, config.longest_edge
                    )
                    result = provider.analyze_video(media_id, frames, timestamps)

                vision = result.to_dict()
                vision["vision_metadata"] = metadata_for_result(
                    source_hash,
                    cache_key,
                    provider,
                    datetime.now(UTC).isoformat(),
                    timestamps,
                )
                if not validate_vision_result(vision):
                    raise VisionError("Normalized Vision result failed persistence validation")
                enrich_manifest_media(manifest, media_id, vision)
                item.pop("score", None)
                for key in ("events", "creative_direction", "selection", "story", "music_selection", "music_analysis", "reel_plan", "template_definition", "visual_plan", "render"):
                    manifest.pop(key, None)
                for media in [x for key in ("photos", "videos") for x in manifest.get(key, []) if isinstance(x, dict)]:
                    media.pop("selection", None); media.pop("selected", None); media.pop("event", None)
                counts["processed"] += 1
                counts["retry_processed" if was_retry else "new_processed"] += 1
                if was_retry:
                    counts["recovered"] += 1
                if getattr(provider, "last_recovered", False):
                    counts["structured_recovered"] += 1
                save_trip_manifest_atomic(manifest_path, manifest)
            except (VisionError, VisionPreprocessError, OSError, ValueError) as exc:
                counts["failed"] += 1
                error = {
                    "media_id": media_id, "source_path": source_path,
                    "type": type(exc).__name__, "failure_type": _failure_type(exc),
                    "retry_attempted": was_retry,
                    "structured_retry_attempted": bool(
                        getattr(provider, "last_recovery_attempted", False)
                    ),
                    "message": str(exc),
                }
                counts["errors"].append(error)
                item["vision_error"] = error
                save_trip_manifest_atomic(manifest_path, manifest)
                _vision_progress(progress, position, total, "ERROR", source_path, counts)
    return counts


def _failure_type(exc: Exception) -> str:
    if isinstance(exc, VisionPreprocessError):
        return "preprocessing"
    if type(exc).__name__ == "VisionResponseValidationError":
        return "structured_output"
    return "provider_or_media"


def _vision_progress(
    progress: Callable[[str], None] | None,
    position: int,
    total: int,
    action: str,
    source_path: str,
    counts: dict[str, object],
) -> None:
    _progress(
        progress,
        f"[{position}/{total}] {action} {source_path} "
        f"processed={counts['processed']} cached={counts['cached']} "
        f"retried={counts['retried']} recovered={counts['recovered']} failed={counts['failed']}",
    )


def run_scoring(trip_folder: Path, config: ScoringConfig) -> dict[str, object]:
    """Recompute deterministic scores from manifest Vision and read-only media facts."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    facts = _derive_scoring_facts(root, manifest)
    summary = score_manifest(manifest, config, facts)
    for key in ("events", "creative_direction", "selection", "story", "music_selection", "music_analysis", "reel_plan", "template_definition", "visual_plan", "render"):
        manifest.pop(key, None)
    for item in [x for key in ("photos", "videos") for x in manifest.get(key, []) if isinstance(x, dict)]:
        item.pop("event", None); item.pop("selection", None); item.pop("selected", None)
    advance_manifest_version(manifest, "1.2")
    save_trip_manifest_atomic(manifest_path, manifest)
    return summary


def run_events(trip_folder: Path, config: EventConfig) -> dict[str, object]:
    """Recompute Event-owned state and invalidate every dependent editorial artifact."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    state = group_manifest_events(manifest, config)
    for key in ("creative_direction", "selection", "story", "music_selection", "music_analysis", "reel_plan", "template_definition", "visual_plan", "render"):
        manifest.pop(key, None)
    for item in [entry for key in ("photos", "videos") for entry in manifest.get(key, []) if isinstance(entry, dict)]:
        item.pop("selection", None); item.pop("selected", None)
    advance_manifest_version(manifest, "1.6")
    save_trip_manifest_atomic(manifest_path, manifest)
    return state


def run_director(trip_folder: Path, config: CreativeDirectorConfig,
                 provider: CreativeDirectorProvider | None = None) -> dict[str, object]:
    """Persist Director-owned strategy and invalidate only dependent editorial state."""
    root = trip_folder.resolve(); manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    direction = (provider or DeterministicCreativeDirector()).direct(manifest, config)
    manifest["creative_direction"] = direction
    for key in ("selection", "story", "music_selection", "music_analysis", "reel_plan", "template_definition", "visual_plan", "render"): manifest.pop(key, None)
    for item in [x for key in ("photos","videos") for x in manifest.get(key,[]) if isinstance(x,dict)]:
        item.pop("selection", None); item.pop("selected", None)
    advance_manifest_version(manifest, "1.7")
    save_trip_manifest_atomic(manifest_path, manifest)
    return direction


def run_selection(trip_folder: Path, config: SelectionConfig) -> dict[str, object]:
    """Recompute duplicate and candidate state from persisted Sprint 4 scores."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    scoreable = [
        item for collection in ("photos", "videos") for item in manifest[collection]
        if isinstance(item, dict) and isinstance(item.get("score"), dict)
    ]
    if not scoreable:
        raise ValueError("Trip Manifest has no Sprint 4 scores. Run 'score' first.")
    if not isinstance(manifest.get("creative_direction"), dict):
        raise ValueError("Creative Direction not found. Run 'direct' first.")
    selection = select_manifest(manifest, config)
    for key in ("story", "music_selection", "music_analysis", "reel_plan", "template_definition", "visual_plan", "render"): manifest.pop(key, None)
    advance_manifest_version(manifest, "1.2")
    save_trip_manifest_atomic(manifest_path, manifest)
    return selection


def run_story(
    trip_folder: Path,
    config: StoryConfig,
    provider: StoryProvider | None = None,
) -> dict[str, object]:
    """Replace only Story-owned state using the persisted Sprint 4 candidate pool."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    provider = provider or DeterministicStoryProvider()
    story = provider.build(manifest, config)
    validate_story(story, manifest)
    manifest["story"] = story
    for key in ("music_selection", "music_analysis", "reel_plan", "template_definition", "visual_plan", "render"): manifest.pop(key, None)
    advance_manifest_version(manifest, "1.3")
    save_trip_manifest_atomic(manifest_path, manifest)
    return story


def run_music(
    trip_folder: Path, config: MusicConfig, music_path: Path | None = None,
) -> dict[str, object]:
    """Analyze explicit local music, cache source facts, and persist editorial alignment."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    if music_path is None:
        return {"status": "no_music", "cache_hit": False, "music_analysis": None}
    direction = manifest.get("creative_direction")
    story = manifest.get("story")
    if not isinstance(direction, dict) or not isinstance(story, dict):
        raise ValueError("Music requires Creative Direction and Story. Run 'direct', 'select', and 'story' first.")
    source = music_path.resolve()
    analysis, cache_hit = analyze_music_cached(source, config, root / Path(config.cache_dir_name))
    persisted = dict(analysis)
    persisted["duration_alignment"] = negotiate_duration(direction, persisted)
    persisted["story_mapping"] = map_story_to_music(story, persisted)
    selection_was_present = "music_selection" in manifest
    manifest.pop("music_selection", None)
    previous = manifest.get("music_analysis")
    changed = previous != persisted
    manifest["music_analysis"] = persisted
    if changed:
        manifest.pop("reel_plan", None)
        manifest.pop("template_definition", None); manifest.pop("visual_plan", None)
        manifest.pop("render", None)
    if changed or selection_was_present:
        save_trip_manifest_atomic(manifest_path, manifest)
    return {"status": "analyzed", "cache_hit": cache_hit,
            "invalidated_plan": changed, "music_analysis": persisted}


def run_music_selection(
    trip_folder: Path, config: MusicConfig, library_path: Path | None = None,
) -> dict[str, object]:
    """Rank a configured local library and persist the selected analysis for Planner."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    direction = manifest.get("creative_direction")
    story = manifest.get("story")
    if not isinstance(direction, dict) or not isinstance(story, dict):
        raise ValueError("Music selection requires Creative Direction and Story. Run 'direct', 'select', and 'story' first.")
    library = (library_path or Path(config.library_path)).resolve()
    ranked = rank_library(library, manifest, config, root / Path(config.cache_dir_name))
    previous_analysis = manifest.get("music_analysis")
    previous_arrangement = manifest.get("music_arrangement")
    candidates = ranked["ranked"]
    strategies = generate_strategies(candidates, ranked["profile"], direction, story, config)
    winner = strategies["winner"]
    compact_candidates = [
        {
            "track_id": candidate["track"]["track_id"],
            "file_name": candidate["track"]["file_name"],
            "title": candidate["track"].get("title"),
            "creator": candidate["track"].get("creator"),
            "metadata_status": candidate["track"]["metadata_status"],
            "production_ready": candidate["track"]["production_ready"],
            "music_match_score": candidate["music_match_score"],
            "bpm": candidate["analysis"].get("tempo", {}).get("bpm"),
            "detected_bpm": candidate["tempo_interpretation"]["detected_bpm"],
            "effective_bpm": candidate["tempo_interpretation"]["effective_bpm"],
            "tempo_interpretation": candidate["tempo_interpretation"]["tempo_interpretation"],
            "tempo_confidence": candidate["analysis"].get("tempo", {}).get("confidence"),
            "peak_region": next((region for region in candidate["analysis"].get("structure", [])
                                 if region.get("type") == "peak"), None),
            "components": candidate["components"],
            "aligned_duration_seconds": candidate["alignment"].get("music_aligned_duration"),
            **candidate["eligibility"],
            "reasons": candidate["reasons"],
        }
        for candidate in candidates
    ]
    selected = next((c for c in candidates if winner and c["track"]["track_id"] == winner["segments"][0]["track_id"]), None)
    selection = {
        "version": ranked["version"],
        "profile": ranked["profile"],
        "candidates": compact_candidates,
        "strategy_type": winner["strategy_type"] if winner else None,
        "strategy_score": winner["strategy_score"] if winner else None,
        "selected_track_id": selected["track"]["track_id"] if winner and winner["strategy_type"] == "single_track" else None,
        "selected_score": winner["strategy_score"] if winner else None,
        "reasons": strategies["decision_reasons"],
        "decision_margin": strategies["decision_margin"],
        "decision_reasons": strategies["decision_reasons"],
        "single_track_candidates": strategies["single_track_candidates"],
        "multi_track_candidates": strategies["multi_track_candidates"],
        "winner": winner,
        "alternatives": strategies["alternatives"],
        "validation": {
            "candidate_count": ranked["summary"]["candidates"],
            "eligible_count": ranked["summary"]["eligible"],
            "single_track_eligible_count": sum(c["eligibility"]["single_track_eligible"] for c in candidates),
            "multi_track_eligible_count": sum(c["eligibility"]["multi_track_eligible"] for c in candidates),
            "analysis_errors": ranked["errors"],
        },
    }
    manifest["music_selection"] = selection
    if winner:
        manifest["music_arrangement"] = winner
        # Real cached analyses contain matching source fingerprints. This guard keeps
        # pure mocked ranking tests independent of FFmpeg while production runs assemble.
        source_facts_valid = all(c["analysis"].get("source", {}).get("fingerprint") == c["track"]["fingerprint"]
                                 for c in candidates if c["track"]["track_id"] in {s["track_id"] for s in winner["segments"]})
        if source_facts_valid:
            prior_contract = ({k:v for k,v in previous_arrangement.items() if k != "assembly"}
                              if isinstance(previous_arrangement, dict) else None)
            prior_assembly = previous_arrangement.get("assembly") if isinstance(previous_arrangement, dict) else None
            prior_path = Path(str(prior_assembly.get("path"))) if isinstance(prior_assembly, dict) and prior_assembly.get("path") else None
            if prior_contract == winner and prior_path and prior_path.is_file():
                assembly = prior_assembly
            else:
                assembly = assemble_music(winner, root / "output" / config.arrangement_output_filename, config)
            manifest["music_arrangement"]["assembly"] = assembly
            selection["winner"]["assembly"] = assembly
    else:
        manifest.pop("music_arrangement", None)
    if selected and winner and winner["strategy_type"] == "single_track":
        persisted = dict(selected["analysis"])
        persisted["duration_alignment"] = selected["alignment"]
        persisted["story_mapping"] = map_story_to_music(story, persisted)
        persisted["selected_track"] = {
            key: selected["track"].get(key) for key in (
                "track_id", "file_name", "title", "creator", "source_name", "source_page",
                "license_name", "license_url", "attribution_required", "attribution_text",
                "metadata_status", "engineering_usable", "production_ready", "path",
            )
        }
        manifest["music_analysis"] = persisted
    else:
        manifest.pop("music_analysis", None)
    current_analysis = manifest.get("music_analysis")
    previous_identity = (
        previous_analysis.get("source", {}).get("cache_key"),
        previous_analysis.get("duration_alignment"),
    ) if isinstance(previous_analysis, dict) else None
    current_identity = (
        current_analysis.get("source", {}).get("cache_key"),
        current_analysis.get("duration_alignment"),
    ) if isinstance(current_analysis, dict) else None
    previous_contract = ({k:v for k,v in previous_arrangement.items() if k != "assembly"}
                         if isinstance(previous_arrangement, dict) else None)
    current_contract = ({k:v for k,v in winner.items() if k != "assembly"} if winner else None)
    changed = previous_identity != current_identity or previous_contract != current_contract
    if changed:
        manifest.pop("reel_plan", None)
        manifest.pop("template_definition", None); manifest.pop("visual_plan", None)
        manifest.pop("render", None)
    save_trip_manifest_atomic(manifest_path, manifest)
    selected_compact = next((c for c in compact_candidates if selected and c["track_id"] == selected["track"]["track_id"]), None)
    return {**ranked["summary"], "selected": selected_compact, "strategy": winner,
            "single_track_eligible": sum(c["single_track_eligible"] for c in compact_candidates),
            "multi_track_eligible": sum(c["multi_track_eligible"] for c in compact_candidates),
            "alternatives": strategies["alternatives"], "errors": ranked["errors"],
            "invalidated_plan": changed, "library": str(library)}


def run_planner(trip_folder: Path, config: PlannerConfig) -> dict[str, object]:
    """Replace only Planner-owned state from persisted Story state and local source facts."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    story = manifest.get("story")
    if not isinstance(story, dict) or not isinstance(story.get("sequence"), list) or not story["sequence"]:
        # Keep the stable CLI-facing prerequisite wording in the domain layer.
        return build_reel_plan(manifest, config)
    by_id = {
        item.get("id"): item for item in manifest.get("videos", []) if isinstance(item, dict)
    }
    durations: dict[str, float] = {}
    for entry in story["sequence"]:
        media_id = entry.get("media_id") if isinstance(entry, dict) else None
        item = by_id.get(media_id)
        if not item or isinstance(item.get("duration"), (int, float)):
            continue
        try:
            durations[str(media_id)] = probe_video(_resolve_media_source(root, item.get("path"))).duration_seconds
        except (OSError, ValueError, VisionPreprocessError):
            # Domain planning records this deterministic omission rather than failing unrelated shots.
            pass
    plan = build_reel_plan(manifest, config, durations)
    manifest["reel_plan"] = plan
    manifest.pop("template_definition", None); manifest.pop("visual_plan", None)
    manifest.pop("render", None)
    advance_manifest_version(manifest, "1.4")
    save_trip_manifest_atomic(manifest_path, manifest)
    return plan


def run_template_planner(trip_folder: Path, config: TemplateConfig) -> dict[str, object]:
    """Resolve visual presentation from existing editorial contracts only."""
    root=trip_folder.resolve(); manifest_path=root/"output"/"trip_manifest.json"
    manifest=load_trip_manifest(manifest_path)
    if not config.enabled: raise ValueError("Template Engine is disabled")
    definition=get_builtin_template(config.default_template)
    plan=resolve_visual_plan(manifest,definition,avoid_immediate_repeat=config.avoid_immediate_repeat,
                             max_complex_blocks_in_row=config.max_complex_blocks_in_row)
    if not config.motion_enabled:
        for block in plan["blocks"]: block["motion"]={"type":"none","start_time":0.0,"end_time":1.0,"easing":"linear","beat_alignment":"none"}
    if not config.typography_enabled:
        for block in plan["blocks"]: block["typography"]=[]
    if not config.decorations_enabled:
        for block in plan["blocks"]: block["decorations"]=[]
    previous=(manifest.get("template_definition"),manifest.get("visual_plan"))
    if previous[0] == definition and _semantic_visual(previous[1]) == plan:
        return previous[1]
    manifest["template_definition"]=definition; manifest["visual_plan"]=plan
    if previous!=(definition,plan): _invalidate_motion_downstream(manifest)
    advance_manifest_version(manifest,"1.8"); save_trip_manifest_atomic(manifest_path,manifest)
    return plan


def run_layout_planner(trip_folder: Path, config: LayoutConfig) -> dict[str, object]:
    """Embed static spatial layouts without changing upstream editorial contracts."""
    root=trip_folder.resolve(); manifest_path=root/"output"/"trip_manifest.json"
    manifest=load_trip_manifest(manifest_path)
    if not config.enabled: raise ValueError("Layout Engine is disabled")
    visual=manifest.get("visual_plan")
    resolved=resolve_layouts(manifest,visual,safe_area_margin=config.safe_area_margin,
                             background_token=config.default_background)
    manifest["visual_plan"]=resolved
    if visual!=resolved:
        for old, new in zip(visual["blocks"], resolved["blocks"]):
            if old.get("resolved_layout") != new.get("resolved_layout"):
                new.pop("resolved_motion", None)
        _invalidate_motion_downstream(manifest)
    advance_manifest_version(manifest,"1.9"); save_trip_manifest_atomic(manifest_path,manifest)
    return resolved


def run_renderer(trip_folder: Path, config: RendererConfig) -> tuple[dict[str, object], Path]:
    """Render persisted Planner state, then atomically persist only completed render state."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    render_state, output_path = render_reel(root, manifest, config)
    manifest["render"] = render_state
    advance_manifest_version(manifest, "1.5")
    save_trip_manifest_atomic(manifest_path, manifest)
    return render_state, output_path


def _derive_scoring_facts(root: Path, manifest: dict[str, object]) -> dict[str, dict[str, float | int | None]]:
    facts: dict[str, dict[str, float | int | None]] = {}
    for media_type, collection in (("photo", "photos"), ("video", "videos")):
        for item in manifest[collection]:  # type: ignore[index]
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            current: dict[str, float | int | None] = {
                "width": item.get("width") if isinstance(item.get("width"), (int, float)) else None,
                "height": item.get("height") if isinstance(item.get("height"), (int, float)) else None,
                "duration": item.get("duration") if isinstance(item.get("duration"), (int, float)) else None,
            }
            try:
                source = _resolve_media_source(root, item.get("path"))
                if media_type == "photo" and (current["width"] is None or current["height"] is None):
                    from PIL import Image, ImageOps
                    with Image.open(source) as image:
                        oriented = ImageOps.exif_transpose(image)
                        current["width"], current["height"] = oriented.size
                elif media_type == "video" and (
                    current["width"] is None or current["height"] is None or current["duration"] is None
                ):
                    probe = probe_video(source)
                    width, height = probe.width, probe.height
                    if probe.rotation % 180:
                        width, height = height, width
                    current.update(width=width, height=height, duration=probe.duration_seconds)
            except (ImportError, OSError, ValueError, VisionPreprocessError):
                pass
            facts[item["id"]] = current
    return facts


def _progress(callback: Callable[[str], None] | None, message: str) -> None:
    if callback:
        callback(message)


def _resolve_media_source(root: Path, stored_path: object) -> Path:
    if not isinstance(stored_path, str) or not stored_path:
        raise VisionPreprocessError("Manifest media path is missing")
    candidate = (root / Path(stored_path)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise VisionPreprocessError(f"Manifest media path escapes trip folder: {stored_path}") from exc
    return candidate
