"""Compliant local music intake, metadata, compatibility scoring, and ranking."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .config import MusicConfig
from .music import (
    SUPPORTED_AUDIO, MusicAnalysisError, analyze_music_cached, map_story_to_music,
    music_fingerprint, negotiate_duration,
    interpret_tempo,
)

MUSIC_LIBRARY_VERSION = "1.0"
MUSIC_SELECTION_VERSION = "1.0"
METADATA_FIELDS = (
    "title", "creator", "source_name", "source_page", "license_name", "license_url",
    "attribution_required", "attribution_text", "downloaded_at", "source_notes",
)


class MusicLibraryError(ValueError):
    pass


def import_track(source: Path, library: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    """Copy one explicit local track into managed storage without overwriting anything."""
    source = source.resolve(); library = library.resolve()
    if not source.is_file(): raise MusicLibraryError(f"Music file not found: {source}")
    if source.suffix.lower() not in SUPPORTED_AUDIO:
        raise MusicLibraryError(f"Unsupported music format {source.suffix!r}")
    fingerprint = music_fingerprint(source); track_id = f"track-{fingerprint[:20]}"
    tracks = library / "tracks"; metadata_dir = library / "metadata"
    tracks.mkdir(parents=True, exist_ok=True); metadata_dir.mkdir(parents=True, exist_ok=True)
    existing_copies = sorted(tracks.glob(f"{track_id}.*"))
    destination = existing_copies[0] if existing_copies else tracks / f"{track_id}{source.suffix.lower()}"
    imported = False
    if not destination.exists():
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=f".{track_id}-", suffix=".tmp",
                                             dir=tracks, delete=False) as temporary:
                temporary_path = Path(temporary.name)
            shutil.copy2(source, temporary_path)
            if music_fingerprint(temporary_path) != fingerprint:
                raise MusicLibraryError("Managed music copy failed fingerprint verification")
            temporary_path.replace(destination)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        imported = True
    elif music_fingerprint(destination) != fingerprint:
        raise MusicLibraryError(f"Refusing to overwrite conflicting managed track: {destination}")
    metadata_path = metadata_dir / f"{track_id}.json"
    if metadata_path.is_file():
        record = _load_metadata(metadata_path, track_id, destination, fingerprint)
        merged = {field: record.get(field) for field in METADATA_FIELDS}
        for field in METADATA_FIELDS:
            if merged[field] in (None, "") and metadata.get(field) not in (None, ""):
                merged[field] = metadata[field]
        enriched = _metadata_record(track_id, destination.name, fingerprint, merged)
        if enriched != record:
            _write_json_atomic(metadata_path, enriched)
            record = enriched
    else:
        record = _metadata_record(track_id, destination.name, fingerprint, metadata)
        _write_json_atomic(metadata_path, record)
    return {"track": record, "managed_path": str(destination), "imported": imported,
            "duplicate": not imported, "source_preserved": music_fingerprint(source) == fingerprint}


def scan_library(library: Path) -> list[dict[str, Any]]:
    """Discover supported files only in the configured managed tracks directory."""
    library = library.resolve(); tracks = library / "tracks"; metadata_dir = library / "metadata"
    if not tracks.is_dir(): return []
    unique: dict[str, dict[str, Any]] = {}
    for path in sorted(tracks.iterdir(), key=lambda value: value.name.lower()):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_AUDIO: continue
        fingerprint = music_fingerprint(path); track_id = f"track-{fingerprint[:20]}"
        if fingerprint in unique: continue
        metadata_path = metadata_dir / f"{track_id}.json"
        record = (_load_metadata(metadata_path, track_id, path, fingerprint)
                  if metadata_path.is_file() else _metadata_record(track_id, path.name, fingerprint, {}))
        record["path"] = str(path); unique[fingerprint] = record
    return [unique[key] for key in sorted(unique, key=lambda value: unique[value]["track_id"])]


def build_music_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    direction = manifest.get("creative_direction") if isinstance(manifest.get("creative_direction"), dict) else {}
    story = manifest.get("story") if isinstance(manifest.get("story"), dict) else {}
    content = direction.get("content_profile", {}) if isinstance(direction.get("content_profile"), dict) else {}
    strategy = direction.get("music_strategy", {}) if isinstance(direction.get("music_strategy"), dict) else {}
    duration = direction.get("duration_strategy", {}) if isinstance(direction.get("duration_strategy"), dict) else {}
    style = str(direction.get("style") or "travel_story")
    pacing_value = direction.get("pacing")
    pacing = str(pacing_value.get("overall") if isinstance(pacing_value, dict) else pacing_value or "balanced")
    tempo_ranges = {"cinematic_travel": (70, 115), "travel_story": (80, 130),
                    "dynamic_travel_highlight": (95, 150), "beat_montage": (105, 165)}
    phases = list(dict.fromkeys(entry.get("section") for entry in story.get("sequence", [])
                               if isinstance(entry, dict) and entry.get("section")))
    return {"version": "1.0", "style": style, "pacing": pacing,
            "editorial_duration_seconds": duration.get("resolved_seconds"),
            "duration_flexibility_seconds": duration.get("flexibility_seconds"),
            "story_phases": phases, "event_diversity": content.get("event_diversity"),
            "motion_density": content.get("motion_density"),
            "desired_energy": strategy.get("energy", "medium"),
            "beat_driven": bool(strategy.get("beat_driven")),
            "preferred_tempo_bpm": {"minimum": tempo_ranges.get(style, tempo_ranges["travel_story"])[0],
                                    "maximum": tempo_ranges.get(style, tempo_ranges["travel_story"])[1]},
            "desired_structure": list(strategy.get("preferred_structure", ["hook", "build", "peak", "release"])),
            "template_intent": (direction.get("template_strategy") or {}).get("primary")}


def score_candidate(
    track: dict[str, Any], analysis: dict[str, Any], profile: dict[str, Any], alignment: dict[str, Any],
) -> dict[str, Any]:
    tempo = analysis.get("tempo", {}); bpm = analysis.get("_editorial_effective_bpm", tempo.get("bpm")); confidence = float(tempo.get("confidence", 0))
    preferred = profile["preferred_tempo_bpm"]; center = (preferred["minimum"]+preferred["maximum"])/2
    tempo_score = 20.0 if not isinstance(bpm, (int, float)) else max(0.0, 100-abs(float(bpm)-center)*2)
    duration_score = 100.0 if alignment.get("usable_for_planning") and abs(float(alignment.get("delta_seconds", 0))) <= .75 else (
        75.0 if alignment.get("usable_for_planning") else 10.0)
    energies = [float(point.get("energy", 0)) for point in analysis.get("energy_curve", [])]
    energy_range = max(energies, default=0)-min(energies, default=0)
    desired_high = profile.get("desired_energy") == "high"
    energy_score = min(100.0, energy_range*125 + (25 if desired_high and max(energies, default=0) >= .8 else 10))
    labels = {str(region.get("type")) for region in analysis.get("structure", []) if region.get("type")}
    arc_score = min(100.0, 20 + 20*len(labels & {"intro", "build", "peak", "release", "outro"}))
    peak_score = 100.0 if "peak" in labels and any(anchor.get("type") == "peak" for anchor in analysis.get("sync_anchors", [])) else 35.0
    ending_score = 100.0 if alignment.get("alignment_reason") in {"phrase_boundary", "final_resolving_beat", "editorial_duration_already_aligned"} else 45.0
    beat_density = len(analysis.get("beats", []))/max(1.0, float(analysis.get("duration_seconds", 1)))
    density_target = 1.8 if profile.get("beat_driven") else 1.0
    density_score = max(0.0, 100-abs(beat_density-density_target)*45)
    status = track["metadata_status"]; metadata_score = 100.0 if track["production_ready"] else 50.0 if status == "incomplete_metadata" else 10.0
    penalty = (18.0 if bpm is None else 0.0) + (10.0 if tempo.get("ambiguity") else 0.0) + (12.0 if not analysis.get("beats") else 0.0)
    components = {"duration_compatibility": duration_score, "tempo_pacing": tempo_score,
        "beat_confidence": confidence*100, "energy_profile": energy_score,
        "story_arc": arc_score, "peak_usefulness": peak_score, "ending_quality": ending_score,
        "beat_density": density_score, "style_compatibility": (energy_score+tempo_score+density_score)/3,
        "metadata_readiness": metadata_score, "reliability_penalty": penalty}
    weights = {"duration_compatibility": .17, "tempo_pacing": .08, "beat_confidence": .12,
        "energy_profile": .12, "story_arc": .14, "peak_usefulness": .12,
        "ending_quality": .12, "beat_density": .05, "style_compatibility": .04,
        "metadata_readiness": .04}
    total = sum(components[key]*weight for key, weight in weights.items())-penalty
    return {"music_match_score": round(max(0.0, min(100.0, total)), 3),
            "components": {key: round(value, 3) for key, value in components.items()},
            "reasons": _score_reasons(components, alignment)}


def rank_library(library: Path, manifest: dict[str, Any], config: MusicConfig, cache_root: Path) -> dict[str, Any]:
    profile = build_music_profile(manifest); candidates = []; errors = []; analyzed = cached_count = 0
    discovered = scan_library(library)
    for track in discovered:
        try:
            analysis, cache_hit = analyze_music_cached(Path(track["path"]), config, cache_root)
            cached_count += int(cache_hit); analyzed += int(not cache_hit)
            alignment = negotiate_duration(manifest["creative_direction"], analysis)
            interpretation = interpret_tempo(analysis, profile)
            analysis_for_score = dict(analysis)
            analysis_for_score["_editorial_effective_bpm"] = interpretation["effective_bpm"]
            scoring = score_candidate(track, analysis_for_score, profile, alignment)
            candidates.append({"track": track, "analysis": analysis, "alignment": alignment,
                               "tempo_interpretation": interpretation, **scoring})
        except (MusicAnalysisError, OSError, ValueError) as exc:
            errors.append({"track_id": track["track_id"], "file_name": track["file_name"],
                           "type": type(exc).__name__, "message": str(exc)})
    candidates.sort(key=lambda value: (-value["music_match_score"], value["track"]["track_id"]))
    return {"version": MUSIC_SELECTION_VERSION, "profile": profile, "ranked": candidates,
            "errors": errors, "summary": {"candidates": len(discovered),
                "eligible": len(candidates), "analyzed": analyzed, "cached": cached_count}}


def _metadata_record(track_id: str, file_name: str, fingerprint: str, values: dict[str, Any]) -> dict[str, Any]:
    record = {"version": MUSIC_LIBRARY_VERSION, "track_id": track_id, "file_name": file_name,
              "fingerprint": fingerprint}
    for field in METADATA_FIELDS: record[field] = values.get(field)
    required = all(record.get(key) for key in ("source_name", "source_page", "license_name", "license_url"))
    attribution_ok = record.get("attribution_required") is not True or bool(record.get("attribution_text"))
    production_ready = bool(required and attribution_ok)
    any_metadata = any(record.get(key) not in (None, "") for key in METADATA_FIELDS)
    record.update(metadata_status="verified_metadata" if production_ready else "incomplete_metadata" if any_metadata else "local_only",
                  engineering_usable=True, production_ready=production_ready)
    return record


def _load_metadata(path: Path, track_id: str, audio: Path, fingerprint: str) -> dict[str, Any]:
    try: values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise MusicLibraryError(f"Invalid track metadata: {path}") from exc
    if not isinstance(values, dict): raise MusicLibraryError(f"Invalid track metadata object: {path}")
    return _metadata_record(track_id, audio.name, fingerprint, values)


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
        temporary.replace(path)
    finally: temporary.unlink(missing_ok=True)


def _score_reasons(components: dict[str, float], alignment: dict[str, Any]) -> list[str]:
    ranked = sorted((key for key in components if key != "reliability_penalty"),
                    key=lambda key: (-components[key], key))
    reasons = [f"strongest:{ranked[0]}={components[ranked[0]]:.1f}",
               f"duration:{alignment.get('alignment_reason')}"]
    if components["reliability_penalty"]: reasons.append(f"reliability_penalty:{components['reliability_penalty']:.1f}")
    return reasons
