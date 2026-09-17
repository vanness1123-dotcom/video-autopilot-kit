"""Deterministic conversion of persisted Story state into a render-neutral timeline."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from .config import PlannerConfig
from .story import SECTION_ORDER
from .events import coherence_metrics
from .music import validate_music_analysis

PLANNER_VERSION = "1.0"


class ReelPlanningError(ValueError):
    """Base class for explainable pre-render planning failures."""


class ReelPlanPrerequisiteError(ReelPlanningError):
    pass


class ReelPlanInsufficientMedia(ReelPlanningError):
    pass


class ReelPlanValidationError(ReelPlanningError):
    pass


def build_reel_plan(
    manifest: dict[str, Any], config: PlannerConfig, video_durations: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build one byte-stable plan from persisted story and objective source durations."""
    direction = manifest.get("creative_direction") if isinstance(manifest.get("creative_direction"), dict) else {}
    budget = direction.get("media_budget", {}) if isinstance(direction.get("media_budget"), dict) else {}
    duration_strategy = direction.get("duration_strategy", {}) if isinstance(direction.get("duration_strategy"), dict) else {}
    music_candidate = manifest.get("music_analysis")
    music = music_candidate if validate_music_analysis(music_candidate) else {}
    arrangement = manifest.get("music_arrangement") if isinstance(manifest.get("music_arrangement"), dict) else {}
    alignment = music.get("duration_alignment", {}) if isinstance(music.get("duration_alignment"), dict) else {}
    planning_music = music if alignment.get("usable_for_planning", True) else {}
    if arrangement:
        planning_music = {"beats": arrangement.get("sync_anchors", []), "sync_anchors": arrangement.get("sync_anchors", []),
                          "duration_seconds": arrangement.get("timeline_duration_seconds"), "phrases": []}
    music_duration = alignment.get("music_aligned_duration") if alignment.get("usable_for_planning", True) else None
    arrangement_duration = arrangement.get("timeline_duration_seconds") if arrangement.get("feasible") else None
    resolved_duration = arrangement_duration if isinstance(arrangement_duration, (int, float)) else music_duration if isinstance(music_duration, (int, float)) else duration_strategy.get("resolved_seconds")
    if isinstance(resolved_duration, (int, float)):
        config = replace(
            config,
            target_duration_seconds=float(resolved_duration),
            min_shots=max(1, int(budget.get("minimum_shots", config.min_shots))),
            max_shots=max(1, int(budget.get("maximum_shots", config.max_shots))),
        )
    pacing = (direction.get("pacing") or {}).get("overall") if isinstance(direction.get("pacing"), dict) else None
    available = len((manifest.get("story") or {}).get("sequence", []))
    effective_max = min(available, int(budget.get("maximum_shots", config.max_shots))) if budget else config.max_shots
    effective_min = min(effective_max, int(budget.get("minimum_shots", config.min_shots))) if budget else config.min_shots
    story = manifest.get("story")
    if not isinstance(story, dict) or not isinstance(story.get("sequence"), list) or not story["sequence"]:
        raise ReelPlanPrerequisiteError("Story plan not found. Run 'story' first.")
    by_id = {
        item["id"]: (item, kind)
        for kind, collection in (("photo", "photos"), ("video", "videos"))
        for item in manifest.get(collection, []) if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    durations = video_durations or {}
    dropped: list[dict[str, str]] = []
    candidates: list[dict[str, Any]] = []
    suppressed = set((manifest.get("selection") or {}).get("suppressed_ids", []))
    for entry in story["sequence"]:
        media_id = entry.get("media_id") if isinstance(entry, dict) else None
        if media_id not in by_id:
            dropped.append({"media_id": str(media_id), "reason": "unknown_manifest_media"}); continue
        item, kind = by_id[media_id]
        if media_id in suppressed or (item.get("selection") or {}).get("status") == "suppressed":
            dropped.append({"media_id": media_id, "reason": "upstream_duplicate_suppressed"}); continue
        source_duration = item.get("duration", durations.get(media_id))
        if kind == "video" and (not isinstance(source_duration, (int, float)) or source_duration <= 0):
            dropped.append({"media_id": media_id, "reason": "video_duration_unavailable_or_invalid"}); continue
        candidates.append({"entry": entry, "item": item, "kind": kind, "source_duration": float(source_duration) if kind == "video" else None})
    chosen, reduction = _choose_subset(candidates, config, effective_max)
    dropped.extend(reduction)
    if len(chosen) < effective_min:
        raise ReelPlanInsufficientMedia(
            f"Only {len(chosen)} safe Story candidates remain; planner requires at least {effective_min}"
        )
    lows, preferred, highs = zip(*[_duration_bounds(value, config) for value in chosen])
    if sum(lows) - config.duration_tolerance_seconds > config.target_duration_seconds or sum(highs) + config.duration_tolerance_seconds < config.target_duration_seconds:
        raise ReelPlanInsufficientMedia(
            f"Safe shot bounds {sum(lows):.3f}..{sum(highs):.3f}s cannot fill target {config.target_duration_seconds:.3f}s"
        )
    allocated = _allocate(config.target_duration_seconds, list(lows), list(preferred), list(highs))
    allocated, snapped_boundaries = _snap_to_music(
        allocated, list(lows), list(highs), chosen, planning_music, str(direction.get("style") or "travel_story")
    )
    shots, cursor = [], 0.0
    section_totals: dict[str, float] = defaultdict(float)
    for index, (candidate, duration) in enumerate(zip(chosen, allocated), 1):
        entry, item, kind = candidate["entry"], candidate["item"], candidate["kind"]
        start, end = round(cursor, 3), round(cursor + duration, 3)
        duration = round(end - start, 3); cursor = end
        source_in = source_out = None
        if kind == "video":
            source_duration = candidate["source_duration"]
            source_in = round(max(0.0, (source_duration - duration) / 2.0), 3)
            source_out = round(source_in + duration, 3)
            if source_out > source_duration:
                source_out = round(source_duration, 3); source_in = round(source_out - duration, 3)
        roles = list(dict.fromkeys([entry.get("editorial_role"), *((item.get("selection") or {}).get("candidate_roles") or [])]))
        roles = [role for role in roles if isinstance(role, str)]
        framing = _framing(item, config)
        shots.append({
            "shot_id": f"shot-{index:03d}", "shot_index": index, "media_id": item["id"],
            "media_type": kind, "source_path": item.get("path"), "scene_id": entry.get("scene_id"),
            "story_section": entry.get("section"), "candidate_roles": roles,
            "event_id": entry.get("event_id") or (item.get("event") or {}).get("event_id"),
            "scene_role": (item.get("event") or {}).get("scene_role"),
            "hook_teaser": bool(entry.get("hook_teaser")),
            "timeline_start_seconds": start, "timeline_end_seconds": end, "planned_duration_seconds": duration,
            "source_trim_start_seconds": source_in, "source_trim_end_seconds": source_out,
            "transition_intent": config.default_transition, "framing_intent": framing,
            "music_alignment": "snapped" if index in snapped_boundaries else "unsnapped",
            "planning_reason": _reason(candidate),
        })
        section_totals[str(entry.get("section"))] += duration
    # Remove accumulated millisecond rounding from the final shot and video trim.
    delta = round(config.target_duration_seconds - cursor, 3)
    if delta:
        final = shots[-1]; final["planned_duration_seconds"] = round(final["planned_duration_seconds"] + delta, 3)
        final["timeline_end_seconds"] = round(config.target_duration_seconds, 3)
        if final["media_type"] == "video": final["source_trim_end_seconds"] = round(final["source_trim_end_seconds"] + delta, 3)
        section_totals[final["story_section"]] += delta
    sections = []
    for section in SECTION_ORDER:
        section_shots = [shot for shot in shots if shot["story_section"] == section]
        if section_shots:
            sections.append({"section": section, "timeline_start_seconds": section_shots[0]["timeline_start_seconds"],
                             "timeline_end_seconds": section_shots[-1]["timeline_end_seconds"],
                             "duration_seconds": round(section_totals[section], 3), "shot_count": len(section_shots)})
    metrics = coherence_metrics([str(shot.get("event_id")) for shot in shots if shot.get("event_id")], story.get("hook_teaser_event_id"))
    event_blocks = []
    for shot in shots:
        event_id = shot.get("event_id")
        if not event_blocks or event_blocks[-1]["event_id"] != event_id:
            event_blocks.append({"event_id": event_id, "timeline_start_seconds": shot["timeline_start_seconds"],
                                 "timeline_end_seconds": shot["timeline_end_seconds"], "shot_count": 1,
                                 "hook_teaser": bool(shot.get("hook_teaser"))})
        else:
            event_blocks[-1]["timeline_end_seconds"] = shot["timeline_end_seconds"]
            event_blocks[-1]["shot_count"] += 1
    plan = {
        "plan_version": "1.0", "planner_version": PLANNER_VERSION,
        "target_duration_seconds": config.target_duration_seconds,
        "actual_duration_seconds": shots[-1]["timeline_end_seconds"], "aspect_ratio": config.aspect_ratio,
        "shots": shots, "sections": sections, "event_blocks": event_blocks,
        "creative_direction": {"consumed": bool(direction), "style": direction.get("style"), "pacing": pacing,
                               "template_intent": (direction.get("template_strategy") or {}).get("primary")},
        "validation": {"valid": True, "duration_tolerance_seconds": config.duration_tolerance_seconds,
                       "continuous_timeline": True, "story_sections_represented": [s["section"] for s in sections]},
        "summary": {"story_candidate_count": len(story["sequence"]), "planned_shot_count": len(shots),
                    "photos": sum(s["media_type"] == "photo" for s in shots),
                    "videos": sum(s["media_type"] == "video" for s in shots), "dropped_candidates": dropped, **metrics},
    }
    if music:
        plan["music_intelligence"] = {
            "consumed": bool(planning_music), "cache_key": (music.get("source") or {}).get("cache_key"),
            "tempo_bpm": (music.get("tempo") or {}).get("bpm"),
            "snapped_boundary_count": len(snapped_boundaries),
            "story_mapping": music.get("story_mapping", []),
            "alignment_reason": alignment.get("alignment_reason"),
        }
    if arrangement:
        transitions = arrangement.get("transitions", [])
        plan["music_intelligence"] = {
            "consumed": True, "strategy_id": arrangement.get("strategy_id"),
            "strategy_type": arrangement.get("strategy_type"),
            "timeline_duration_seconds": arrangement.get("timeline_duration_seconds"),
            "segments": arrangement.get("segments", []), "transitions": transitions,
            "sync_anchors": arrangement.get("sync_anchors", []),
            "transition_regions": [{"start": round(float(t["timeline_position_seconds"]), 3),
                                    "end": round(float(t["timeline_position_seconds"])+float(t["duration_seconds"]), 3)}
                                   for t in transitions],
            "snapped_boundary_count": len(snapped_boundaries),
        }
    validate_reel_plan(plan, manifest, config)
    return plan


def _choose_subset(candidates: list[dict[str, Any]], config: PlannerConfig, max_shots: int | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    max_shots = config.max_shots if max_shots is None else max_shots
    if len(candidates) <= max_shots:
        return candidates, []
    mandatory = {"hook", "arrival", "establishing", "exploration", "experience", "highlight", "closing"}
    present = {c["entry"].get("section") for c in candidates}
    mandatory &= present
    keep_ids: set[str] = set()
    for event_id in {c["entry"].get("event_id") for c in candidates if c["entry"].get("event_id")}:
        event_items = [c for c in candidates if c["entry"].get("event_id") == event_id]
        keep_ids.add(max(event_items, key=_strength)["item"]["id"])
    for section in mandatory:
        section_items = [c for c in candidates if c["entry"].get("section") == section]
        best = max(section_items, key=_strength)
        keep_ids.add(best["item"]["id"])
    ranked = sorted(candidates, key=lambda c: (_strength(c), -int(c["entry"].get("position", 0))), reverse=True)
    for candidate in ranked:
        if len(keep_ids) >= max_shots: break
        keep_ids.add(candidate["item"]["id"])
    chosen = [c for c in candidates if c["item"]["id"] in keep_ids]
    dropped = [{"media_id": c["item"]["id"], "reason": "editorial_subset_lower_strength"} for c in candidates if c["item"]["id"] not in keep_ids]
    return chosen, dropped


def _strength(candidate: dict[str, Any]) -> tuple[float, float, str]:
    score = candidate["item"].get("score") or {}
    section_bonus = 20.0 if candidate["entry"].get("section") in {"hook", "highlight", "closing"} else 0.0
    return (float(score.get("story_value", 0)) + section_bonus, float(score.get("total", 0)), candidate["item"]["id"])


def _duration_bounds(candidate: dict[str, Any], config: PlannerConfig) -> tuple[float, float, float]:
    kind, section = candidate["kind"], candidate["entry"].get("section")
    low, default, high = (config.photo_min_duration, config.photo_default_duration, config.photo_max_duration) if kind == "photo" else (config.video_min_duration, config.video_default_duration, config.video_max_duration)
    if kind == "video":
        high = min(high, candidate["source_duration"]); low = min(low, high); default = min(default, high)
    bias = {"hook": config.hook_bias_seconds, "highlight": config.highlight_bias_seconds, "closing": config.closing_bias_seconds}.get(section, 0.0)
    return low, min(high, default + bias), high


def _allocate(target: float, lows: list[float], preferred: list[float], highs: list[float]) -> list[float]:
    values = [max(low, min(want, high)) for low, want, high in zip(lows, preferred, highs)]
    remainder = target - sum(values)
    bounds = highs if remainder > 0 else lows
    while abs(remainder) > 1e-9:
        eligible = [i for i, value in enumerate(values) if (bounds[i] - value) * remainder > 1e-9]
        if not eligible: break
        share = remainder / len(eligible); moved = 0.0
        for i in eligible:
            change = max(bounds[i] - values[i], share) if remainder < 0 else min(bounds[i] - values[i], share)
            values[i] += change; moved += change
        remainder -= moved
    return values


def _snap_to_music(
    durations: list[float], lows: list[float], highs: list[float],
    candidates: list[dict[str, Any]], music: dict[str, Any], style: str,
) -> tuple[list[float], set[int]]:
    """Move selected internal boundaries toward musical evidence without violating shot bounds."""
    if not music or len(durations) < 2:
        return durations, set()
    policy = {
        "cinematic_travel": (999, .10), "travel_story": (8, .12),
        "dynamic_travel_highlight": (6, .16), "beat_montage": (4, .20),
    }
    stride, tolerance = policy.get(style, policy["travel_story"])
    phrase_times = [float(value["time"]) for value in music.get("sync_anchors", [])
                    if value.get("type") in {"phrase_boundary", "peak", "release"}]
    beat_times = [float(value["time"]) for value in music.get("beats", [])]
    values = list(durations); snapped: set[int] = set()
    for boundary in range(1, len(values)):
        left, right = candidates[boundary-1]["entry"], candidates[boundary]["entry"]
        important = left.get("section") != right.get("section") or left.get("event_id") != right.get("event_id")
        if not important and (stride == 999 or boundary % stride):
            continue
        current = sum(values[:boundary])
        anchors = phrase_times if important and phrase_times else beat_times
        if not anchors: continue
        target = min(anchors, key=lambda time: (abs(time-current), time))
        delta = target-current
        if abs(delta) > tolerance: continue
        if lows[boundary-1] <= values[boundary-1]+delta <= highs[boundary-1] and lows[boundary] <= values[boundary]-delta <= highs[boundary]:
            values[boundary-1] += delta; values[boundary] -= delta; snapped.add(boundary)
    return values, snapped


def _framing(item: dict[str, Any], config: PlannerConfig) -> str:
    width, height = item.get("width"), item.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and width > height:
        return "blur_fill"
    return config.default_framing


def _reason(candidate: dict[str, Any]) -> str:
    entry, item = candidate["entry"], candidate["item"]
    score = item.get("score") or {}
    return f"preserved {entry.get('section')} / {entry.get('editorial_role')}; story_value={score.get('story_value', 'unavailable')}"


def validate_reel_plan(plan: dict[str, Any], manifest: dict[str, Any], config: PlannerConfig) -> None:
    shots = plan.get("shots")
    if not isinstance(shots, list) or not shots: raise ReelPlanValidationError("Plan contains no shots")
    known = {item.get("id") for key in ("photos", "videos") for item in manifest.get(key, []) if isinstance(item, dict)}
    previous = 0.0; ids = set()
    for shot in shots:
        if shot["media_id"] not in known or shot["media_id"] in ids: raise ReelPlanValidationError("Unknown or reused media ID")
        ids.add(shot["media_id"])
        if abs(shot["timeline_start_seconds"] - previous) > config.duration_tolerance_seconds: raise ReelPlanValidationError("Timeline gap or overlap")
        if shot["planned_duration_seconds"] <= 0 or shot["timeline_end_seconds"] <= shot["timeline_start_seconds"]: raise ReelPlanValidationError("Non-positive shot duration")
        if abs((shot["timeline_end_seconds"] - shot["timeline_start_seconds"]) - shot["planned_duration_seconds"]) > .002: raise ReelPlanValidationError("Shot duration disagrees with timeline")
        if shot["media_type"] == "video":
            if shot["source_trim_start_seconds"] < 0 or shot["source_trim_end_seconds"] <= shot["source_trim_start_seconds"]: raise ReelPlanValidationError("Invalid video trim")
            if abs((shot["source_trim_end_seconds"] - shot["source_trim_start_seconds"]) - shot["planned_duration_seconds"]) > .002: raise ReelPlanValidationError("Video trim disagrees with duration")
        previous = shot["timeline_end_seconds"]
    if abs(previous - config.target_duration_seconds) > config.duration_tolerance_seconds: raise ReelPlanValidationError("Plan misses target duration")
