"""Deterministic bounded Motion. Visibility and base geometry stay upstream-owned."""
from __future__ import annotations

import copy
import math
from typing import Any

from .layout import LayoutValidationError, validate_layout_plan

MOTION_VERSION = "1.0"
SPACES = frozenset({"media_content", "slot"})
EASINGS = frozenset({"linear", "smoothstep"})
TRANSFORMS = frozenset({"translate_x", "translate_y", "scale", "opacity"})
CONTENT_STRATEGIES = frozenset({"slow_push_in.v1", "slow_pull_out.v1",
    "pan_horizontal_left.v1", "pan_horizontal_right.v1", "pan_vertical_up.v1",
    "pan_vertical_down.v1", "subtle_drift.v1"})
CARD_STRATEGIES = frozenset({"card_enter.v1", "card_exit.v1", "card_emphasis.v1"})
STRATEGIES = CONTENT_STRATEGIES | CARD_STRATEGIES | {"hold.v1"}
CARD_BLOCKS = frozenset({"hero_media", "two_up", "three_up", "grid", "collage", "layered_cards", "closing_card"})
PACE_FACTORS = {"cinematic": .7, "balanced": 1.0, "dynamic": .9, "fast": .75}
STYLE_PACING = {"cinematic_travel": "cinematic", "travel_story": "balanced",
                "dynamic_travel_highlight": "dynamic", "beat_montage": "fast"}
EPSILON = 1e-9
KNOWN_ANCHOR_PROVENANCE = frozenset({"detected_beat", "heuristic_accent", "heuristic_subdivision",
    "opening_accent", "final_resolving_beat", "phrase_boundary", "peak", "release"})
SUPPORTED_ANCHOR_PROVENANCE = frozenset({"detected_beat", "heuristic_accent", "opening_accent", "final_resolving_beat"})
MIN_ANCHOR_CONFIDENCE = .5
MIN_ANCHOR_MARGIN_SECONDS = .15


class MotionValidationError(ValueError):
    pass


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize_reel_anchors(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only explicitly persisted reel-time anchors; never inspect source-local music."""
    reel = manifest.get("reel_plan") if isinstance(manifest, dict) else None
    intelligence = reel.get("music_intelligence") if isinstance(reel, dict) else None
    anchors = intelligence.get("sync_anchors") if isinstance(intelligence, dict) else None
    duration = reel.get("actual_duration_seconds") if isinstance(reel, dict) else None
    if not isinstance(anchors, list) or not _finite(duration) or duration <= 0:
        return []
    dedup: dict[float, dict[str, Any]] = {}
    for anchor in anchors:
        if not isinstance(anchor, dict) or not _finite(anchor.get("time")):
            continue
        time = float(anchor["time"])
        if time < 0 or time > float(duration):
            continue
        provenance = anchor.get("provenance")
        if not isinstance(provenance, str) or provenance not in KNOWN_ANCHOR_PROVENANCE:
            continue
        confidence = anchor.get("confidence", 0.0)
        if not _finite(confidence):
            continue
        value = {"time_seconds": round(time, 3), "provenance": provenance,
                 "confidence": round(float(confidence), 3)}
        old = dedup.get(value["time_seconds"])
        rank = (value["provenance"] in SUPPORTED_ANCHOR_PROVENANCE, value["confidence"], value["provenance"])
        old_rank = (old["provenance"] in SUPPORTED_ANCHOR_PROVENANCE, old["confidence"], old["provenance"]) if old else None
        if old is None or rank > old_rank:
            dedup[value["time_seconds"]] = value
    return [dedup[key] for key in sorted(dedup)]


def _eligible_anchors(manifest, start, end):
    values = []
    for anchor in normalize_reel_anchors(manifest):
        if anchor["provenance"] not in SUPPORTED_ANCHOR_PROVENANCE: continue
        if anchor["confidence"] < MIN_ANCHOR_CONFIDENCE: continue
        if start + MIN_ANCHOR_MARGIN_SECONDS <= anchor["time_seconds"] <= end - MIN_ANCHOR_MARGIN_SECONDS:
            values.append(anchor)
    return values


def _beat_refine(manifest, block, slot, track, window):
    """Refine one existing progression point; return (track, evidence) or unchanged."""
    if track["strategy"] == "hold.v1" or window[2] < 1.5: return track, None
    start = float(block["timeline_start_seconds"]); end = float(block["timeline_end_seconds"])
    left, right, seconds = window
    anchors = _eligible_anchors(manifest, start + left*(end-start), start + right*(end-start))
    if not anchors: return track, None
    strategy = track["strategy"]
    layer_start = start + left * (end - start)
    layer_end = start + right * (end - start)
    if strategy == "card_enter.v1":
        # Entrance may settle on a trusted anchor near the beginning, while
        # retaining enough lead time for a visible but bounded ramp.
        candidates = [a for a in anchors if a["time_seconds"] <= layer_start + .5 * seconds]
        anchor = min(candidates, key=lambda a: (a["time_seconds"], a["provenance"])) if candidates else None
    elif strategy == "card_exit.v1":
        candidates = [a for a in anchors if a["time_seconds"] >= layer_end - .5 * seconds]
        anchor = min(candidates, key=lambda a: (-a["time_seconds"], a["provenance"])) if candidates else None
    else:
        midpoint = start + ((left+right)/2)*(end-start)
        anchor = min(anchors, key=lambda a: (abs(a["time_seconds"]-midpoint), a["time_seconds"], a["provenance"]))
    if anchor is None:
        return track, None
    u = (anchor["time_seconds"]-start)/(end-start)
    if strategy == "card_enter.v1":
        if not left + .05*(right-left) <= u <= left + .5*(right-left): return track, None
    elif strategy == "card_exit.v1":
        if not right - .5*(right-left) <= u <= right - .05*(right-left): return track, None
    elif not left + .2*(right-left) <= u <= right - .2*(right-left):
        return track, None
    frames = track["keyframes"]
    if len(frames) == 2:
        a, b = frames
        if abs(b["t"]-a["t"]) < EPSILON: return track, None
        q = (u-a["t"])/(b["t"]-a["t"])
        q = max(0.0, min(1.0, q))
        state = {key: round(a["transform"][key]*(1-q)+b["transform"][key]*q, 9) for key in TRANSFORMS}
        frames.insert(1, {"t": round(u, 9), "transform": state, "easing_to_next": "smoothstep"})
    elif len(frames) == 3:
        frames[1]["t"] = round(u, 9)
    track["beat_alignment"] = {"anchor_time_seconds": anchor["time_seconds"], "normalized_time": round(u, 9),
                                "provenance": anchor["provenance"], "confidence": anchor["confidence"]}
    return track, {"anchor_time": anchor["time_seconds"], "anchor_provenance": anchor["provenance"]}


def without_motion(plan):
    result = copy.deepcopy(plan)
    if isinstance(result, dict):
        for block in result.get("blocks", []):
            block.pop("resolved_motion", None)
    return result


def _context(manifest, plan):
    if not isinstance(plan, dict) or not isinstance(plan.get("blocks"), list) or not plan["blocks"]:
        raise MotionValidationError("Visual Plan missing. Run 'layout-plan' first.")
    media = {}
    for kind, collection in (("photo", "photos"), ("video", "videos")):
        for item in manifest.get(collection, []):
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in media:
                raise MotionValidationError("Invalid or duplicate canonical media identity")
            media[item["id"]] = (kind, item)
    try:
        validate_layout_plan(plan, plan, {key: value[1] for key, value in media.items()})
    except (LayoutValidationError, KeyError, TypeError, AttributeError) as exc:
        raise MotionValidationError(f"Invalid or missing resolved Layout. Run 'layout-plan' first. {exc}") from exc
    duration = plan.get("duration_seconds")
    if not _finite(duration) or duration <= 0:
        raise MotionValidationError("Invalid Visual Plan duration")
    reel = manifest.get("reel_plan", {})
    if reel.get("actual_duration_seconds") != duration:
        raise MotionValidationError("Visual Plan duration disagrees with Reel Plan")
    shots = reel.get("shots", [])
    if not isinstance(shots, list) or not shots:
        raise MotionValidationError("Reel Plan shots missing")
    by_shot = {shot.get("shot_id"): shot for shot in shots if isinstance(shot, dict)}
    owned = [sid for block in plan["blocks"] for sid in block["shot_ids"]]
    if len(by_shot) != len(shots) or owned != [s.get("shot_id") for s in shots]:
        raise MotionValidationError("Visual/Reel shot ownership or order mismatch")
    cursor = 0.0
    for shot in shots:
        left, right, span = (shot.get(k) for k in ("timeline_start_seconds", "timeline_end_seconds", "planned_duration_seconds"))
        if not all(_finite(v) for v in (left, right, span)) or not left < right or span <= 0:
            raise MotionValidationError("Invalid Reel shot timing")
        if abs(left-cursor) > .002 or abs(right-left-span) > .002:
            raise MotionValidationError("Inconsistent Reel shot timing")
        cursor = right
    windows = {}
    prior = 0.0
    for index, block in enumerate(plan["blocks"]):
        start, end, length = (block.get(k) for k in ("timeline_start_seconds", "timeline_end_seconds", "duration_seconds"))
        if not all(_finite(v) for v in (start, end, length)) or length <= 0 or end <= start:
            raise MotionValidationError("Invalid block timing")
        if abs(start-prior) > .002 or abs(end-start-length) > .002 or end > duration+.002:
            raise MotionValidationError("Inconsistent block timing")
        prior = end
        if abs(start-by_shot[block["shot_ids"][0]]["timeline_start_seconds"]) > .002 or abs(end-by_shot[block["shot_ids"][-1]]["timeline_end_seconds"]) > .002:
            raise MotionValidationError("Block bounds disagree with assigned Reel shots")
        layers = (block.get("layout") or {}).get("layers")
        if not isinstance(layers, list) or len(layers) != len(block["shot_ids"]):
            raise MotionValidationError("Inherited visual-layer timing missing")
        layer_map = {layer.get("shot_id"): layer for layer in layers if isinstance(layer, dict)}
        if len(layer_map) != len(layers) or set(layer_map) != set(block["shot_ids"]):
            raise MotionValidationError("Layer/slot shot ownership mismatch")
        for slot in block["resolved_layout"]["slots"]:
            shot = by_shot[slot["shot_id"]]
            if shot.get("media_id") != slot["media_id"]:
                raise MotionValidationError("Slot/Reel media ownership mismatch")
            layer = layer_map[slot["shot_id"]]
            editorial = layer.get("editorial_timing", {})
            if not isinstance(editorial, dict) or not all(_finite(editorial.get(k)) for k in ("start_seconds", "end_seconds")) or editorial != {"start_seconds": shot.get("timeline_start_seconds"), "end_seconds": shot.get("timeline_end_seconds")}:
                raise MotionValidationError("Inherited editorial timing disagrees with Reel Plan")
            window = layer.get("visual_layer_timing", {})
            left, right = window.get("start_seconds"), window.get("end_seconds")
            if not all(_finite(v) for v in (left, right)) or not start <= left < right <= end:
                raise MotionValidationError("Invalid inherited visibility window")
            windows[index, slot["slot_id"]] = ((left-start)/(end-start), (right-start)/(end-start), right-left)
    if abs(prior-duration) > .002:
        raise MotionValidationError("Blocks do not span Visual Plan duration")
    return media, windows


def duration_class(seconds):
    if seconds < .75: return "extremely_short"
    if seconds < 2: return "short"
    if seconds < 6: return "medium"
    return "long"


def _intent(manifest, block, slot, seconds):
    direction = manifest.get("creative_direction") or {}
    pacing = direction.get("pacing") or {}
    phase = block.get("story_phase")
    phases = pacing.get("phases") or {}
    phase_pace = phases.get(phase, phases.get("body") if phase in {"exploration", "experience"} else None)
    pace = phase_pace or pacing.get("overall") or STYLE_PACING.get(direction.get("style"), "balanced")
    if pace not in PACE_FACTORS: pace = "balanced"
    if seconds < .75: excursion = 0.0
    elif seconds < 2: excursion = .01 + .015 * (seconds-.75)/1.25
    elif seconds < 6: excursion = .025 + .015 * (seconds-2)/4
    else: excursion = min(.06, .04 + .005*(seconds-6))
    excursion *= PACE_FACTORS[pace]
    if phase == "closing": excursion *= .65
    if block.get("block_type") == "layered_cards" and slot.get("role") != "primary": excursion *= .5
    return pace, round(excursion, 6)


def _known(item):
    return all(_finite(item.get(k)) and item[k] > 0 for k in ("width", "height"))


def _canvas_aspect(manifest):
    # Current Layout contract is explicitly 9:16. Never guess a new coordinate system.
    ratio = (manifest.get("reel_plan") or {}).get("aspect_ratio", "9:16")
    if ratio != "9:16": raise MotionValidationError("Motion requires the current 9:16 Layout canvas")
    return 9/16


def cover_fit(item, slot, aspect=9/16):
    """Fitted source width/height in base-slot units, before content scaling."""
    source_ratio = item["width"] / item["height"]
    slot_ratio = slot["width"] * aspect / slot["height"]
    return max(1.0, source_ratio/slot_ratio), max(1.0, slot_ratio/source_ratio)


def crop_slack(item, slot, scale=1.0, aspect=9/16):
    width, height = cover_fit(item, slot, aspect)
    return (width*scale-1)/2, (height*scale-1)/2


def _transform(x=0.0, y=0.0, scale=1.0, opacity=1.0):
    return {"translate_x": x, "translate_y": y, "scale": scale, "opacity": opacity}


def _track(slot, strategy, states, window, positions=None):
    left, right, _ = window
    positions = positions or [0.0, 1.0]
    frames = []
    for index, (q, state) in enumerate(zip(positions, states)):
        frame = {"t": left if q == 0 else right if q == 1 else left+(right-left)*q, "transform": state}
        if index < len(states)-1: frame["easing_to_next"] = "linear" if strategy == "hold.v1" else "smoothstep"
        frames.append(frame)
    return {"target_slot_id": slot["slot_id"], "space": "slot" if strategy in CARD_STRATEGIES else "media_content",
            "strategy": strategy, "keyframes": frames}


def motion_family(strategy):
    if strategy.startswith("pan_horizontal"): return "pan_horizontal"
    if strategy.startswith("pan_vertical"): return "pan_vertical"
    return strategy.removesuffix(".v1")


def _rank(candidates, recent):
    """Soft penalty limited to the preceding three tracks; hold is never penalized."""
    ranked = []
    for candidate in candidates:
        strategy = candidate["track"]["strategy"]
        penalty = 0 if strategy == "hold.v1" else sum(
            4 * (motion_family(old) == motion_family(strategy)) + 2 * (old == strategy)
            for old in recent[-3:])
        ranked.append((candidate["score"]-penalty, strategy, candidate, penalty))
    score, _, selected, penalty = sorted(ranked, key=lambda c: (-c[0], c[1]))[0]
    reasons = list(selected["reasons"])
    if penalty: reasons.append(f"recent_family_direction_penalty:{penalty}")
    elif any(entry[3] for entry in ranked): reasons.append("comparable_safe_alternative")
    reasons.append(f"selection_score:{round(score, 3)}")
    return selected["track"], reasons


def _slot_bounds(slot, transform, aspect):
    """Rotated card AABB in physical canvas-height units, including local translation."""
    w, h = slot["width"]*aspect, slot["height"]
    angle = math.radians(slot["rotation_deg"])
    c, s = math.cos(angle), math.sin(angle)
    tx, ty = transform["translate_x"]*w, transform["translate_y"]*h
    cx = (slot["x"]+slot["width"]/2)*aspect + c*tx-s*ty
    cy = slot["y"]+slot["height"]/2 + s*tx+c*ty
    ex = (abs(c)*w+abs(s)*h)*transform["scale"]/2
    ey = (abs(s)*w+abs(c)*h)*transform["scale"]/2
    return cx-ex, cy-ey, cx+ex, cy+ey


def _envelope(slot, track, aspect):
    states = [f["transform"] for f in track["keyframes"]] if track["space"] == "slot" else [_transform()]
    bounds = [_slot_bounds(slot, state, aspect) for state in states]
    return min(b[0] for b in bounds), min(b[1] for b in bounds), max(b[2] for b in bounds), max(b[3] for b in bounds)


def _swept_block(block, tracks, aspect):
    """Conservative swept AABBs prove no new prohibited collision during co-visibility."""
    slots = {s["slot_id"]: s for s in block["resolved_layout"]["slots"]}
    policy = block["resolved_layout"]["overlap_policy"]
    for i, first in enumerate(tracks):
        for second in tracks[i+1:]:
            if not any(t["space"] == "slot" and t["strategy"] != "hold.v1" for t in (first, second)): continue
            if min(first["keyframes"][-1]["t"], second["keyframes"][-1]["t"]) <= max(first["keyframes"][0]["t"], second["keyframes"][0]["t"]): continue
            a = _envelope(slots[first["target_slot_id"]], first, aspect)
            b = _envelope(slots[second["target_slot_id"]], second, aspect)
            overlap_x = max(0, min(a[2], b[2])-max(a[0], b[0]))
            overlap_y = max(0, min(a[3], b[3])-max(a[1], b[1]))
            if policy in {"prohibited", "temporal_replacement"} and overlap_x > EPSILON and overlap_y > EPSILON:
                raise MotionValidationError("Swept slot motion violates non-overlap policy")
            if policy == "intentional":
                # The swept intersection bounds overlap from above; the smallest
                # possible actual card area bounds the denominator from below.
                areas = []
                for track in (first, second):
                    slot = slots[track["target_slot_id"]]
                    states = [f["transform"] for f in track["keyframes"]] if track["space"] == "slot" else [_transform()]
                    for state in states:
                        areas.append(slot["width"]*aspect*slot["height"]*state["scale"]**2)
                if overlap_x*overlap_y >= .9*min(areas):
                    raise MotionValidationError("Swept card motion risks excessive intentional occlusion")


def _geometry(block, slot, track, item, aspect):
    if track["strategy"] == "hold.v1": return  # Identity must remain a universal fallback.
    for frame in track["keyframes"]:
        transform = frame["transform"]
        if track["space"] == "media_content":
            sx, sy = crop_slack(item, slot, transform["scale"], aspect)
            if abs(transform["translate_x"]) > sx+EPSILON or abs(transform["translate_y"]) > sy+EPSILON:
                raise MotionValidationError("Content path exceeds cover crop slack")
        else:
            area = block["resolved_layout"]["safe_area"] if block["resolved_layout"]["safe_area_policy"] == "inside" else {"x": 0, "y": 0, "width": 1, "height": 1}
            bounds = _slot_bounds(slot, transform, aspect)
            if bounds[0] < area["x"]*aspect-EPSILON or bounds[1] < area["y"]-EPSILON or bounds[2] > (area["x"]+area["width"])*aspect+EPSILON or bounds[3] > area["y"]+area["height"]+EPSILON:
                raise MotionValidationError("Swept slot motion escapes canvas/safe area")
    # Every channel uses the SAME segment easing scalar q. All cover inequalities
    # and rotated-corner halfspaces are affine in scale/translation. Their values
    # are convex combinations of consecutive keyframe values, so checking ALL
    # keyframes proves the entire path (not merely the first and last frame).


def _candidates(manifest, block, slot, kind, item, window, enabled):
    seconds = window[2]; hint = (block.get("motion") or {}).get("type")
    pace, excursion = _intent(manifest, block, slot, seconds)
    phase = block.get("story_phase"); family = block.get("block_type")
    reasons = [f"duration_class:{duration_class(seconds)}", f"pacing:{pace}"]
    if not enabled or hint == "none": reasons.append("motion_disabled")
    if seconds < .75: reasons.append("extremely_short_visibility")
    if not _known(item): reasons.append("unknown_dimensions")
    if kind == "video": reasons.append("video_content_identity")
    if slot["fit_mode"] == "contain": reasons.append("contain_content_identity")
    hold_score = 20 + (6 if phase == "closing" else 0) + (4 if family == "beat_montage" else 0)
    if kind == "video": hold_score = 38
    if family == "layered_cards" and slot.get("role") != "primary": hold_score += 12
    candidates = [{"score": hold_score, "track": _track(slot, "hold.v1", [_transform(), _transform()], window),
                   "reasons": reasons+["safe_identity_fallback"]}]
    if not enabled or hint == "none" or seconds < .75 or not _known(item): return candidates
    aspect = _canvas_aspect(manifest)
    hints = {"slow_push_in.v1": {"push_in", "scale"}, "slow_pull_out.v1": {"pull_out"},
             "pan_horizontal_left.v1": {"pan_left"}, "pan_horizontal_right.v1": {"pan_right"},
             "pan_vertical_up.v1": {"pan_up"}, "pan_vertical_down.v1": {"pan_down"},
             "subtle_drift.v1": {"translate"}, "card_enter.v1": {"slide_in", "fade"},
             "card_exit.v1": {"slide_out"}, "card_emphasis.v1": {"pop", "scale"}}

    def add(strategy, states, score, evidence, positions=None):
        track = _track(slot, strategy, states, window, positions)
        try: _geometry(block, slot, track, item, aspect)
        except MotionValidationError: return
        matching = hint in hints[strategy]
        if matching: score += 8
        if phase == "closing" and strategy == "slow_pull_out.v1": score += 4
        if phase in {"hook", "highlight"} and strategy == "slow_push_in.v1": score += 2
        candidates.append({"score": score, "track": track,
            "reasons": reasons[:2]+evidence+([f"template_hint:{hint}"] if matching else [])})

    if kind == "photo" and slot["fit_mode"] == "cover":
        add("slow_push_in.v1", [_transform(), _transform(scale=1+excursion)], 30, ["photo_cover", "adaptive_scale"])
        add("slow_pull_out.v1", [_transform(scale=1+excursion), _transform()], 29, ["photo_cover", "coverage_safe_pull_out"])
        sx, sy = crop_slack(item, slot, aspect=aspect)
        # Pans require natural fit slack; do not zoom solely to manufacture a pan.
        for axis, slack, directions in (("x", sx, ("left", "right")), ("y", sy, ("up", "down"))):
            amount = min(excursion*.5, slack*.6, .025)
            if slack < .005 or amount < .0025: continue
            for sign, direction in zip((-1, 1), directions):
                start = _transform(**{axis: -sign*amount}); end = _transform(**{axis: sign*amount})
                name = f"pan_{'horizontal' if axis == 'x' else 'vertical'}_{direction}.v1"
                add(name, [start, end], 28+min(slack, .1)*30, [f"natural_{axis}_crop_slack", "bounded_pan"])
        start_scale = 1+excursion*.5
        sx, sy = crop_slack(item, slot, start_scale, aspect)
        dx, dy = min(excursion*.12, sx*.5, .006), min(excursion*.12, sy*.5, .006)
        if min(dx, dy) >= .0005:
            add("subtle_drift.v1", [_transform(x=-dx, y=dy, scale=start_scale),
                _transform(x=dx, y=-dy, scale=1+excursion*.8)], 27, ["small_coupled_translation_scale", "crop_slack_proven"])
    if family in CARD_BLOCKS:
        quiet_background = family == "layered_cards" and slot.get("role") != "primary"
        strength = min(.012, excursion*.4)
        ramp = min(.25, .3/seconds)
        if family in {"hero_media", "layered_cards", "closing_card"} and not quiet_background:
            add("card_enter.v1", [_transform(scale=1-strength, opacity=.85), _transform(), _transform()],
                24+(5 if phase == "hook" else 0)+(4 if pace in {"dynamic", "fast"} else 0), ["inherited_window_entrance", "scale_fade_only"], [0, ramp, 1])
            add("card_exit.v1", [_transform(), _transform(), _transform(scale=1-strength, opacity=.85)],
                23+(6 if phase == "closing" else 0), ["inherited_window_exit", "scale_fade_only"], [0, 1-ramp, 1])
        if not quiet_background:
            add("card_emphasis.v1", [_transform(), _transform(scale=1+strength), _transform()],
                25+(5 if slot.get("role") == "primary" else 0), ["bounded_card_emphasis", "static_rotation_preserved"], [0, .5, 1])
    return candidates


def resolve_motion(manifest: dict[str, Any], visual_plan: dict[str, Any], *, enabled: bool = True) -> dict[str, Any]:
    """Return resolved tracks without writes, probes, music processing, or input mutation."""
    if not isinstance(enabled, bool): raise MotionValidationError("Motion enabled must be boolean")
    media, windows = _context(manifest, visual_plan)
    aspect = _canvas_aspect(manifest)
    result = copy.deepcopy(visual_plan)
    recent = []
    for index, block in enumerate(result["blocks"]):
        tracks, reasons = [], []
        for slot in block["resolved_layout"]["slots"]:
            left, right, seconds = windows[index, slot["slot_id"]]
            kind, item = media[slot["media_id"]]
            candidates = _candidates(manifest, block, slot, kind, item, (left, right, seconds), enabled)
            safe = []
            for candidate in candidates:
                pending = [_track(s, "hold.v1", [_transform(), _transform()], windows[index, s["slot_id"]])
                           for s in block["resolved_layout"]["slots"][len(tracks)+1:]]
                try: _swept_block(block, tracks+[candidate["track"]]+pending, aspect)
                except MotionValidationError: continue
                safe.append(candidate)
            track, evidence = _rank(safe, recent)
            track, beat_evidence = _beat_refine(manifest, block, slot, track, windows[index, slot["slot_id"]])
            tracks.append(track); recent = (recent+[track["strategy"]])[-3:]
            reasons.extend(f"{slot['slot_id']}:{reason}" for reason in evidence)
            if beat_evidence:
                reasons.append(f"{slot['slot_id']}:beat_aligned")
        block["resolved_motion"] = {"version": MOTION_VERSION, "time_space": "block_normalized", "tracks": tracks, "selection_reasons": reasons}
    validate_motion_plan(result, visual_plan, manifest, enabled=enabled)
    return result


def validate_motion_plan(plan, source_plan, manifest, *, enabled=True):
    """Validate strategy shapes and analytically safe interpolation paths."""
    if without_motion(plan) != without_motion(source_plan):
        raise MotionValidationError("Motion changed semantic, timing, ownership, or Layout state")
    media, windows = _context(manifest, plan)
    aspect = _canvas_aspect(manifest)
    for index, block in enumerate(plan["blocks"]):
        motion = block.get("resolved_motion")
        if not isinstance(motion, dict) or set(motion) != {"version", "time_space", "tracks", "selection_reasons"}:
            raise MotionValidationError("Invalid resolved Motion contract")
        if motion["version"] != MOTION_VERSION or motion["time_space"] != "block_normalized":
            raise MotionValidationError("Unsupported Motion version/time_space")
        if not isinstance(motion["selection_reasons"], list) or not all(isinstance(r, str) for r in motion["selection_reasons"]):
            raise MotionValidationError("Invalid Motion reasons")
        slots = {s["slot_id"]: s for s in block["resolved_layout"]["slots"]}
        tracks = motion["tracks"]
        if not isinstance(tracks, list) or len(tracks) != len(slots):
            raise MotionValidationError("Motion requires exactly one track per owned slot")
        seen = set()
        for track in tracks:
            if not isinstance(track, dict) or not set(track).issubset({"target_slot_id", "space", "strategy", "keyframes", "beat_alignment"}) or not {"target_slot_id", "space", "strategy", "keyframes"}.issubset(track):
                raise MotionValidationError("Invalid Motion track")
            target = track["target_slot_id"]
            if not isinstance(target, str) or target not in slots or target in seen:
                raise MotionValidationError("Unknown or duplicate Motion target")
            seen.add(target)
            if not isinstance(track["space"], str) or track["space"] not in SPACES: raise MotionValidationError("Unsupported transform space")
            slot = slots[target]; left, right, seconds = windows[index, target]
            kind, item = media[slot["media_id"]]
            strategy = track["strategy"]
            if not isinstance(strategy, str) or strategy not in STRATEGIES:
                raise MotionValidationError("Unsupported or inapplicable Motion strategy")
            frames = track["keyframes"]
            beat = track.get("beat_alignment")
            if beat is not None:
                if strategy == "hold.v1": raise MotionValidationError("Hold cannot consume a beat")
                if not isinstance(beat, dict) or set(beat) != {"anchor_time_seconds", "normalized_time", "provenance", "confidence"}:
                    raise MotionValidationError("Invalid beat alignment evidence")
                if not _finite(beat["anchor_time_seconds"]) or not _finite(beat["normalized_time"]) or not _finite(beat["confidence"]):
                    raise MotionValidationError("Invalid beat alignment number")
                if beat["anchor_time_seconds"] < 0 or beat["anchor_time_seconds"] > manifest["reel_plan"]["actual_duration_seconds"]:
                    raise MotionValidationError("Beat anchor outside Reel duration")
                if not isinstance(beat["provenance"], str) or beat["provenance"] not in SUPPORTED_ANCHOR_PROVENANCE:
                    raise MotionValidationError("Unsupported beat provenance")
                if beat["confidence"] < MIN_ANCHOR_CONFIDENCE: raise MotionValidationError("Beat confidence below eligibility")
                if abs(beat["normalized_time"]-((beat["anchor_time_seconds"]-block["timeline_start_seconds"])/(block["timeline_end_seconds"]-block["timeline_start_seconds"]))) > 1e-6:
                    raise MotionValidationError("Beat normalized time mismatch")
                if not left <= beat["normalized_time"] <= right:
                    raise MotionValidationError("Beat outside inherited visibility window")
                if not any(abs(a["time_seconds"]-beat["anchor_time_seconds"]) < .001 and a["provenance"] == beat["provenance"] for a in _eligible_anchors(manifest, block["timeline_start_seconds"]+left*(block["timeline_end_seconds"]-block["timeline_start_seconds"]), block["timeline_start_seconds"]+right*(block["timeline_end_seconds"]-block["timeline_start_seconds"]))):
                    raise MotionValidationError("Beat evidence is not an eligible persisted anchor")
            if not isinstance(frames, list) or len(frames) not in ({3} if strategy in CARD_STRATEGIES else {2, 3}):
                raise MotionValidationError("Invalid strategy keyframe count")
            previous = -1.0
            for position, frame in enumerate(frames):
                keys = {"t", "transform", "easing_to_next"} if position < len(frames)-1 else {"t", "transform"}
                if not isinstance(frame, dict) or set(frame) != keys: raise MotionValidationError("Invalid keyframe fields")
                t = frame["t"]
                if not _finite(t) or not 0 <= t <= 1 or not left <= t <= right or t <= previous:
                    raise MotionValidationError("Unordered or out-of-window keyframe")
                if position in (0, len(frames)-1) and abs(t-(left if position == 0 else right)) > 1e-10:
                    raise MotionValidationError("Keyframes must cover inherited visibility exactly")
                previous = t
                if position < len(frames)-1 and (not isinstance(frame["easing_to_next"], str) or frame["easing_to_next"] not in EASINGS): raise MotionValidationError("Unsupported easing")
                transform = frame["transform"]
                if not isinstance(transform, dict) or set(transform) != TRANSFORMS or not all(_finite(v) for v in transform.values()):
                    raise MotionValidationError("Invalid transform vocabulary or non-finite number")
                if not 0 <= transform["opacity"] <= 1 or transform["scale"] <= 0:
                    raise MotionValidationError("Invalid scale/opacity")
            if beat is not None and not any(abs(frame["t"]-beat["normalized_time"]) < 1e-6 for frame in frames):
                raise MotionValidationError("Beat evidence does not match keyframe")
            _validate_strategy(manifest, block, slot, track, kind, item, seconds, enabled)
            _geometry(block, slot, track, item, aspect)
        _swept_block(block, tracks, aspect)


def _validate_strategy(manifest, block, slot, track, kind, item, seconds, enabled):
    strategy = track["strategy"]; states = [f["transform"] for f in track["keyframes"]]
    beat = track.get("beat_alignment")
    if strategy == "hold.v1":
        if any(state != _transform() for state in states): raise MotionValidationError("Hold must be identity")
        return
    if not enabled or (block.get("motion") or {}).get("type") == "none" or seconds < .75 or not _known(item):
        raise MotionValidationError("Active motion ineligible for disable/duration/unknown dimensions")
    _, excursion = _intent(manifest, block, slot, seconds)
    if strategy in CONTENT_STRATEGIES:
        if kind != "photo" or slot["fit_mode"] != "cover" or track["space"] != "media_content":
            raise MotionValidationError("Content motion requires cover-fitted photo")
        for state in states:
            if not 1 <= state["scale"] <= 1+excursion+EPSILON or state["scale"] > 1.06+EPSILON or state["opacity"] != 1:
                raise MotionValidationError("Content motion exceeds adaptive scale/opacity bounds")
        if strategy in {"slow_push_in.v1", "slow_pull_out.v1"}:
            if any(s["translate_x"] != 0 or s["translate_y"] != 0 for s in states): raise MotionValidationError("Push/pull cannot translate")
            first, last = states[0]["scale"], states[-1]["scale"]
            if not (first == 1 and last > first if strategy == "slow_push_in.v1" else last == 1 and first > last):
                raise MotionValidationError("Invalid push/pull endpoints")
        elif strategy.startswith("pan_"):
            axis = "x" if "horizontal" in strategy else "y"; other = "y" if axis == "x" else "x"
            slack = crop_slack(item, slot, aspect=_canvas_aspect(manifest))[0 if axis == "x" else 1]
            limit = min(excursion*.5, slack*.6, .025)
            if slack < .005 or limit < .0025: raise MotionValidationError("Pan lacks meaningful natural crop slack")
            if any(s["scale"] != 1 or s[f"translate_{other}"] != 0 or abs(s[f"translate_{axis}"]) > limit+EPSILON for s in states):
                raise MotionValidationError("Invalid bounded pan")
            delta = states[1][f"translate_{axis}"]-states[0][f"translate_{axis}"]
            if delta == 0 or (delta < 0) != ("left" in strategy or "up" in strategy): raise MotionValidationError("Pan direction mismatch")
        else:
            if any(abs(s[k]) > min(.006, excursion*.12)+EPSILON for s in states for k in ("translate_x", "translate_y")):
                raise MotionValidationError("Drift excursion too large")
    else:
        if track["space"] != "slot" or block["block_type"] not in CARD_BLOCKS:
            raise MotionValidationError("Card strategy requires a card block/space")
        if block["block_type"] == "layered_cards" and slot.get("role") != "primary":
            raise MotionValidationError("Background card must remain quiet")
        if strategy != "card_emphasis.v1" and block["block_type"] not in {"hero_media", "layered_cards", "closing_card"}:
            raise MotionValidationError("Entrance/exit ineligible for structured block")
        strength = min(.012, excursion*.4)
        for state in states:
            if state["translate_x"] != 0 or state["translate_y"] != 0 or not 1-strength-EPSILON <= state["scale"] <= 1+strength+EPSILON or not .85 <= state["opacity"] <= 1:
                raise MotionValidationError("Card motion exceeds bounded scale/fade contract")
        if strategy == "card_enter.v1":
            if states[1:] != [_transform(), _transform()] or states[0]["scale"] > 1 or states[0]["opacity"] >= 1:
                raise MotionValidationError("Invalid card entrance")
        elif strategy == "card_exit.v1":
            if states[:2] != [_transform(), _transform()] or states[-1]["scale"] > 1 or states[-1]["opacity"] >= 1:
                raise MotionValidationError("Invalid card exit")
        elif states[0] != _transform() or states[-1] != _transform() or states[1]["scale"] <= 1 or states[1]["opacity"] != 1:
            raise MotionValidationError("Invalid card emphasis")
        frames = track["keyframes"]; span = frames[-1]["t"]-frames[0]["t"]
        q = (frames[1]["t"]-frames[0]["t"])/span
        ramp = min(.25, .3/seconds)
        expected = ramp if strategy == "card_enter.v1" else 1-ramp if strategy == "card_exit.v1" else .5
        if beat is None and abs(q-expected) > EPSILON: raise MotionValidationError("Invalid card settle/emphasis timing")
        if beat is not None and strategy == "card_emphasis.v1" and abs(q-.5) > .3:
            raise MotionValidationError("Beat emphasis moved too far from midpoint")
