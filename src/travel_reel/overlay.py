"""Deterministic static Overlay/Typography planning contract."""
from __future__ import annotations

import copy
import math
import re
from typing import Any

OVERLAY_VERSION = "1.0"
TYPES = {"title", "location_label", "section_label", "caption", "closing_title", "closing_subtitle"}
REGIONS = {"title_safe", "upper_safe", "center_safe", "lower_safe", "canvas"}
ANCHORS = {"top_left", "top_center", "top_right", "bottom_left", "bottom_center", "bottom_right", "center"}
ALIGNMENTS = {"left", "center", "right"}
FONT_ROLES = {"display", "headline", "body", "caption", "label"}
SIZE_CLASSES = {"display", "large", "medium", "small", "micro"}
WEIGHTS = {"regular", "medium", "semibold", "bold"}
BACKGROUNDS = {"none", "plate"}
EPSILON = 1e-9
LIMITS = {"title": 48, "location_label": 32, "section_label": 24, "caption": 90,
          "closing_title": 48, "closing_subtitle": 72}
GENERIC_LOCATION_LABELS = {"transportation", "food", "shopping", "cityscape", "nightlife", "street", "nature",
                           "exploration", "experience", "highlight", "hook", "closing", "cafe", "landmark",
                           "detail", "theme park", "other", "activity", "indoor", "outdoor"}
TECHNICAL_TITLE_RE = re.compile(r"^(?:visionbenchmark|benchmark|test\d*|sample|demo|output|untitled)$", re.I)
INTERNAL_PHASES = {"hook", "exploration", "experience", "highlight", "closing"}


class OverlayValidationError(ValueError):
    pass


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _text(value: Any) -> str | None:
    if not isinstance(value, str): return None
    value = re.sub(r"[ \t\r\n]+", " ", value).strip()
    return value or None


def _presentation_safe_location_label(value: Any) -> str | None:
    value = _text(value)
    if not value: return None
    comparable = value.casefold().replace("_", " ").strip()
    tokens = set(comparable.split())
    if comparable in GENERIC_LOCATION_LABELS or (tokens and tokens.issubset(GENERIC_LOCATION_LABELS | INTERNAL_PHASES)): return None
    return value


def _presentation_safe_title(story: Any) -> str | None:
    if not isinstance(story, dict): return None
    value = _text(story.get("title"))
    if not value or TECHNICAL_TITLE_RE.fullmatch(value.strip()): return None
    return value


def _event_map(manifest):
    events = manifest.get("events", {}).get("items", []) if isinstance(manifest.get("events"), dict) else []
    return {x.get("event_id"): x for x in events if isinstance(x, dict) and isinstance(x.get("event_id"), str)}


def _media_map(manifest):
    return {x.get("id"): x for k in ("photos", "videos") for x in manifest.get(k, []) if isinstance(x, dict) and isinstance(x.get("id"), str)}


def _safe_rect(block):
    layout = block.get("resolved_layout", {})
    safe = layout.get("safe_area") if isinstance(layout, dict) else None
    if isinstance(safe, dict) and all(_finite(safe.get(k)) for k in ("x", "y", "width", "height")):
        return {k: float(safe[k]) for k in ("x", "y", "width", "height")}
    return {"x": .04, "y": .04, "width": .92, "height": .92}


def _source_candidates(manifest, block):
    shots = block.get("shots", []) if isinstance(block.get("shots"), list) else []
    media = _media_map(manifest); events = _event_map(manifest)
    first = shots[0] if shots and isinstance(shots[0], dict) else {}
    item = media.get(first.get("media_id"), {})
    vision = item.get("vision", {}) if isinstance(item.get("vision"), dict) else {}
    landmark = vision.get("landmark_hint")
    landmark_name = _presentation_safe_location_label(landmark.get("name")) if isinstance(landmark, dict) and (not _finite(landmark.get("confidence")) or landmark.get("confidence") >= .5) else None
    event = events.get(first.get("event_id"), {})
    event_label = _text(event.get("label"))
    if event_label and not _presentation_safe_location_label(event_label): event_label = None
    elif event_label: event_label = event_label.replace("_", " ")
    section = _text(first.get("story_section")) or _text(block.get("story_phase"))
    if section and section.casefold() in INTERNAL_PHASES: section = None
    title = _presentation_safe_title(manifest.get("story"))
    description = _text(vision.get("description"))
    return {"title": (title, "story.title"), "landmark": (landmark_name, "media.vision.landmark_hint.name"),
            "event": (event_label, "events.items[].label"), "section": (section, "reel_plan.shots[].story_section"),
            "description": (description, "media.vision.description")}


def _candidate(block, kind, text, source, safe, index):
    if not text or len(text) > LIMITS[kind]: return None
    closing = block.get("block_type") == "closing_card"
    if kind in {"title", "closing_title"}: region, anchor, align = "center_safe", "center", "center"
    elif kind == "closing_subtitle": region, anchor, align = "lower_safe", "bottom_center", "center"
    elif kind == "location_label": region, anchor, align = "title_safe", "top_left", "left"
    elif kind == "section_label": region, anchor, align = "upper_safe", "top_left", "left"
    else: region, anchor, align = "lower_safe", "bottom_center", "center"
    margin = .02
    width = min(.82, safe["width"] - 2*margin); height = .08 if kind != "caption" else .14
    x = safe["x"] + margin if "left" in anchor else safe["x"] + (safe["width"]-width)/2 if anchor == "center" or "center" in anchor else safe["x"] + safe["width"]-width-margin
    y = safe["y"] + margin if "top" in anchor else safe["y"] + (safe["height"]-height)/2 if anchor == "center" else safe["y"] + safe["height"]-height-margin
    return {"overlay_id": f"overlay-{index:03d}", "type": kind, "target": {"scope": "block"},
            "time_space": "block_normalized", "visibility": {"start": 0.0, "end": 1.0},
            "content": {"text": text, "source": source},
            "placement": {"region": region, "anchor": anchor, "x": round(x, 6), "y": round(y, 6),
                           "width": round(width, 6), "height": round(height, 6), "alignment": align},
            "style": {"font_role": "display" if kind in {"title", "closing_title"} else "label" if kind in {"location_label", "section_label"} else "caption",
                      "weight_role": "semibold" if kind in {"title", "closing_title"} else "regular", "size_class": "large" if kind in {"title", "closing_title"} else "small",
                      "line_height_class": "compact", "letter_spacing_class": "normal", "case_transform": "none", "max_lines": 2 if kind in {"title", "caption", "closing_title", "closing_subtitle"} else 1,
                      "opacity": 1.0, "background_treatment": "none"}, "z_order": 100,
            "validation": {"safe": True, "collision_policy": "static_basic"}}


def resolve_overlay(manifest: dict[str, Any], visual_plan: dict[str, Any], *, enabled: bool = True) -> dict[str, Any]:
    if not isinstance(visual_plan, dict) or not isinstance(visual_plan.get("blocks"), list) or not visual_plan["blocks"]:
        raise OverlayValidationError("Visual Plan missing. Run 'layout-plan' first.")
    result = copy.deepcopy(visual_plan)
    recent = set(); counter = 1
    for block in result["blocks"]:
        if not isinstance(block.get("resolved_layout"), dict): raise OverlayValidationError("Resolved Layout missing. Run 'layout-plan' first.")
        if not isinstance(block.get("resolved_motion"), dict): raise OverlayValidationError("Resolved Motion missing. Run 'motion-plan' first.")
        overlays = []
        if enabled:
            src = _source_candidates(manifest, block); phase = block.get("story_phase"); kind = block.get("block_type")
            choices = []
            if kind == "closing_card": choices = [("closing_title", *src["title"]), ("closing_subtitle", *src["section"])]
            elif phase == "hook": choices = [("title", *src["title"])]
            elif kind in {"hero_media"} or (phase == "exploration" and block.get("definition_block_id") in {"hero", "exploration"}): choices = [("location_label", *src["landmark"]), ("location_label", *src["event"]), ("section_label", *src["section"])]
            elif phase == "highlight": choices = [("location_label", *src["landmark"]), ("caption", *src["description"])]
            for candidate_kind, text, source in choices:
                key = (candidate_kind, text)
                if text and key in recent: continue
                overlay = _candidate(block, candidate_kind, text, source, _safe_rect(block), counter)
                if overlay:
                    overlays.append(overlay); recent.add(key); counter += 1; break
        block["resolved_overlay"] = {"version": OVERLAY_VERSION, "overlays": overlays, "selection_reasons": ["no_safe_text_source"] if not overlays else [f"{o['type']}_from_{o['content']['source']}" for o in overlays]}
    validate_overlay_plan(result, visual_plan, manifest)
    return result


def validate_overlay_plan(plan, source_plan, manifest):
    if _without_overlay(plan) != _without_overlay(source_plan): raise OverlayValidationError("Overlay changed upstream Visual Plan state")
    seen = set()
    for block in plan.get("blocks", []):
        contract = block.get("resolved_overlay")
        if not isinstance(contract, dict) or contract.get('version') not in {'1.0','1.1','1.2'} or set(contract) != ({"version", "overlays", "selection_reasons"} | ({'placement_resolution'} if contract.get('version') in {'1.1','1.2'} else set()) | ({'density_admission'} if contract.get('version')=='1.2' else set())):
            raise OverlayValidationError("Unsupported or malformed resolved Overlay contract")
        if not isinstance(contract["overlays"], list) or not isinstance(contract["selection_reasons"], list): raise OverlayValidationError("Invalid Overlay collections")
        safe = _safe_rect(block); slots = {s.get("slot_id"): s for s in block.get("resolved_layout", {}).get("slots", [])}
        for overlay in contract["overlays"]:
            if not isinstance(overlay, dict): raise OverlayValidationError("Invalid Overlay object")
            required = {"overlay_id","type","target","time_space","visibility","content","placement","style","z_order","validation"}
            if not required <= set(overlay) <= required | {"resolved_typography"} or not isinstance(overlay["overlay_id"], str) or not overlay["overlay_id"] or overlay["overlay_id"] in seen: raise OverlayValidationError("Invalid or duplicate Overlay ID")
            seen.add(overlay["overlay_id"])
            if overlay["type"] not in TYPES or overlay["time_space"] != "block_normalized": raise OverlayValidationError("Unsupported Overlay type/time space")
            target = overlay["target"]
            if not isinstance(target, dict) or target.get("scope") not in {"block","slot"}: raise OverlayValidationError("Invalid Overlay target")
            if target["scope"] == "block" and set(target) != {"scope"}: raise OverlayValidationError("Block target must not include slot")
            if target["scope"] == "slot" and (set(target) != {"scope","target_slot_id"} or target["target_slot_id"] not in slots): raise OverlayValidationError("Unknown Overlay slot target")
            vis = overlay["visibility"]
            if not isinstance(vis, dict) or set(vis) != {"start","end"} or not all(_finite(vis.get(k)) for k in vis) or not 0 <= vis["start"] < vis["end"] <= 1: raise OverlayValidationError("Invalid Overlay visibility")
            if target["scope"] == "slot":
                shot_id = slots[target["target_slot_id"]].get("shot_id")
                layer = next((x for x in block.get("layout", {}).get("layers", []) if isinstance(x, dict) and x.get("shot_id") == shot_id), None)
                timing = layer.get("visual_layer_timing") if isinstance(layer, dict) else None
                if not isinstance(timing, dict) or not all(_finite(timing.get(k)) for k in ("start_seconds", "end_seconds")):
                    raise OverlayValidationError("Slot target has no inherited visual-layer timing")
                bstart, bend = block.get("timeline_start_seconds"), block.get("timeline_end_seconds")
                if not _finite(bstart) or not _finite(bend) or bend <= bstart:
                    raise OverlayValidationError("Invalid block timing for slot Overlay")
                lower = (timing["start_seconds"] - bstart) / (bend - bstart)
                upper = (timing["end_seconds"] - bstart) / (bend - bstart)
                if vis["start"] < lower - EPSILON or vis["end"] > upper + EPSILON:
                    raise OverlayValidationError("Slot Overlay extends beyond inherited layer visibility")
            text = overlay["content"].get("text") if isinstance(overlay["content"], dict) else None
            if not isinstance(text, str) or not _text(text) or len(text) > LIMITS[overlay["type"]]: raise OverlayValidationError("Invalid or excessive Overlay text")
            placement = overlay["placement"]
            if not isinstance(placement, dict) or placement.get("region") not in REGIONS or placement.get("anchor") not in ANCHORS or placement.get("alignment") not in ALIGNMENTS: raise OverlayValidationError("Invalid Overlay placement")
            if not all(_finite(placement.get(k)) for k in ("x","y","width","height")) or not 0 <= placement["x"] <= 1 or not 0 <= placement["y"] <= 1 or not 0 < placement["width"] <= 1 or not 0 < placement["height"] <= 1 or placement["x"]+placement["width"] > 1+EPSILON or placement["y"]+placement["height"] > 1+EPSILON: raise OverlayValidationError("Overlay geometry outside canvas")
            if placement["x"] < safe["x"]-EPSILON or placement["y"] < safe["y"]-EPSILON or placement["x"]+placement["width"] > safe["x"]+safe["width"]+EPSILON or placement["y"]+placement["height"] > safe["y"]+safe["height"]+EPSILON: raise OverlayValidationError("Overlay outside safe area")
            style = overlay["style"]
            if not isinstance(style, dict) or style.get("font_role") not in FONT_ROLES or style.get("weight_role") not in WEIGHTS or style.get("size_class") not in SIZE_CLASSES or style.get("alignment", placement["alignment"]) not in ALIGNMENTS or style.get("case_transform") not in {"none","upper","lower"} or not isinstance(style.get("max_lines"), int) or isinstance(style.get("max_lines"), bool) or not 1 <= style["max_lines"] <= 2 or not _finite(style.get("opacity")) or not 0 <= style["opacity"] <= 1 or style.get("background_treatment") not in BACKGROUNDS: raise OverlayValidationError("Invalid Overlay style")
            if "resolved_typography" in overlay:
                from .typography import validate_typography
                validate_typography(overlay["resolved_typography"], overlay)
        if contract['version'] in {'1.1','1.2'}:
            from .placement_contract import validate_placement_resolution
            validate_placement_resolution(block,manifest)
    if any(b['resolved_overlay']['version'] == '1.2' for b in plan.get('blocks', [])):
        from .overlay_density import validate_density_plan
        validate_density_plan(plan)
    return True


def final_eligible_overlay(manifest, plan, overlay_id):
    """Validated final authority; legacy 1.0 has no geometric eligibility proof.

    Legacy 1.1 retains Placement-only semantics. Overlay 1.2 additionally requires
    density admission. Always return an isolated projection, never source state.
    """
    from .placement_contract import selected_overlay
    validate_overlay_plan(plan, plan, manifest)
    for block in plan['blocks']:
        contract = block['resolved_overlay']
        for index, source in enumerate(contract['overlays']):
            if source['overlay_id'] != overlay_id:
                continue
            if contract['version'] == '1.0':
                raise OverlayValidationError("Legacy Overlay requires Placement resolution")
            if contract['version'] == '1.2' and contract['density_admission']['decisions'][index]['state'] != 'admitted':
                return None
            return selected_overlay(source, contract['placement_resolution']['decisions'][index])
    raise OverlayValidationError("Unknown Overlay ID")


def _without_overlay(plan):
    result = copy.deepcopy(plan)
    for block in result.get("blocks", []) if isinstance(result, dict) else []: block.pop("resolved_overlay", None)
    return result
