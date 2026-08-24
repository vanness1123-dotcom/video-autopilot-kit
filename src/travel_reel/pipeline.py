"""Orchestration for persisting trip-analysis and canonical manifest results."""
from __future__ import annotations
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Callable
from .analyzer import analyze_trip_folder
from .config import ScoringConfig, SelectionConfig, StoryConfig, VisionConfig, load_vision_config
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
)
from .models import Trip
from .scoring import score_manifest
from .selector import select_manifest
from .story import DeterministicStoryProvider, StoryProvider, validate_story
from .vision import (
    VisionError,
    VisionProvider,
    metadata_for_result,
    validate_vision_result,
    vision_cache_key,
)
from .vision_local import LocalVisionProvider

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
    counts = {"processed": 0, "skipped": 0, "failed": 0, "errors": []}

    for media_type, collection in (("photo", "photos"), ("video", "videos")):
        for item in manifest[collection]:
            media_id = item.get("id", "unknown")
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
                    _progress(progress, f"SKIP {media_id} (unchanged)")
                    continue

                _progress(progress, f"VISION {media_id}")
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
                counts["processed"] += 1
                save_trip_manifest_atomic(manifest_path, manifest)
            except (VisionError, VisionPreprocessError, OSError, ValueError) as exc:
                counts["failed"] += 1
                error = {"media_id": media_id, "type": type(exc).__name__, "message": str(exc)}
                counts["errors"].append(error)
                item["vision_error"] = error
                save_trip_manifest_atomic(manifest_path, manifest)
                _progress(progress, f"ERROR {media_id}: {type(exc).__name__}: {exc}")
    return counts


def run_scoring(trip_folder: Path, config: ScoringConfig) -> dict[str, object]:
    """Recompute deterministic scores from manifest Vision and read-only media facts."""
    root = trip_folder.resolve()
    manifest_path = root / "output" / "trip_manifest.json"
    manifest = load_trip_manifest(manifest_path)
    facts = _derive_scoring_facts(root, manifest)
    summary = score_manifest(manifest, config, facts)
    advance_manifest_version(manifest, "1.2")
    save_trip_manifest_atomic(manifest_path, manifest)
    return summary


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
    selection = select_manifest(manifest, config)
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
    advance_manifest_version(manifest, "1.3")
    save_trip_manifest_atomic(manifest_path, manifest)
    return story


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
