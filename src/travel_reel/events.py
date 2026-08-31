"""Deterministic event grouping and lightweight within-event scene intelligence."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import EventConfig

EVENTS_VERSION = "1.0"
SCENE_ROLE_ORDER = {"establishing": 0, "people": 1, "activity": 2, "detail": 3, "motion": 4, "highlight": 5, "closing": 6}
_STOP = {"the", "and", "with", "from", "into", "front", "visible", "people", "photo", "view", "large", "young"}


class EventPrerequisiteError(ValueError):
    pass


def group_manifest_events(manifest: dict[str, Any], config: EventConfig) -> dict[str, Any]:
    """Group every Vision-enriched asset and persist additive event membership."""
    items = _all_media(manifest)
    if not items or any(not isinstance(item.get("vision"), dict) for item in items):
        raise EventPrerequisiteError("Trip Manifest must contain Vision results for every media item. Run 'vision' first.")
    indexed = [(item, index) for index, item in enumerate(items)]
    parent = list(range(len(indexed)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]; value = parent[value]
        return value

    def union(a: int, b: int) -> None:
        a, b = find(a), find(b)
        if a != b: parent[max(a, b)] = min(a, b)

    for left in range(len(indexed)):
        for right in range(left + 1, len(indexed)):
            first, second = indexed[left][0], indexed[right][0]
            similarity, facts = event_similarity(first, second)
            time_gap = _time_gap(first, second)
            sequence_gap = _sequence_gap(first, second)
            supported = (
                time_gap is not None and time_gap <= config.time_gap_seconds
                or sequence_gap is not None and sequence_gap <= config.filename_sequence_gap
            )
            contradictory_time = time_gap is not None and time_gap > config.time_gap_seconds
            distinctive = facts["distinctive_overlap"] and similarity >= config.strong_semantic_threshold and not contradictory_time
            supported_semantics = (
                facts["distinctive_overlap"] and similarity >= config.semantic_similarity_threshold
                or facts["landmark"] or facts["activity"]
                or facts["category"] and similarity >= max(.34, config.semantic_similarity_threshold)
            )
            if supported and supported_semantics or distinctive:
                union(left, right)

    clusters: dict[int, list[tuple[dict[str, Any], int]]] = {}
    for index, pair in enumerate(indexed): clusters.setdefault(find(index), []).append(pair)
    ordered_clusters = sorted(clusters.values(), key=_event_order_key)
    event_items = []
    for number, members in enumerate(ordered_clusters, 1):
        event_id = f"event-{number:03d}"
        ordered = sorted(members, key=lambda pair: _within_event_key(pair[0], pair[1]))
        categories = [_category(item) for item, _ in members]
        dominant = _mode(categories, "other")
        activities = sorted({_activity(item) for item, _ in members if _activity(item)})
        scenes = sorted({_scene(item) for item, _ in members if _scene(item)})
        evidence = _event_evidence(members)
        for ordinal, (item, _) in enumerate(ordered, 1):
            item["event"] = {"event_id": event_id, "ordinal": ordinal, "scene_role": scene_role(item)}
        event_items.append({
            "event_id": event_id, "label": _label(members, dominant),
            "media_ids": [item["id"] for item, _ in ordered], "dominant_category": dominant,
            "scene_types": scenes, "activities": activities,
            "media_mix": {"photos": sum(str(item["id"]).startswith("photo-") for item, _ in members),
                          "videos": sum(str(item["id"]).startswith("video-") for item, _ in members)},
            "evidence": evidence, "evidence_score": round(min(1.0, .25 + .12 * len(evidence)), 3),
        })
    state = {"version": EVENTS_VERSION, "items": event_items, "summary": {
        "event_count": len(event_items), "media_count": len(items),
        "largest_event_size": max((len(event["media_ids"]) for event in event_items), default=0),
    }}
    manifest["events"] = state
    return state


def event_similarity(first: dict[str, Any], second: dict[str, Any]) -> tuple[float, dict[str, bool]]:
    """Return an explainable 0..1 semantic score independent of chronology."""
    a, b = _vision(first), _vision(second)
    category = _category(first) == _category(second) and _category(first) != "other"
    activity = bool(_activity(first) and _activity(first) == _activity(second))
    scene = bool(_scene(first) and _scene(first) == _scene(second))
    landmark = bool(_landmark(first) and _landmark(first) == _landmark(second))
    tokens_a, tokens_b = _semantic_tokens(first), _semantic_tokens(second)
    overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b) if tokens_a or tokens_b else 0.0
    distinctive_words = tokens_a & tokens_b - {"outdoor", "indoor", "street", "city", "tourism", "shopping", "building"}
    distinctive = landmark or bool(distinctive_words & {"church", "gothic", "stained", "amusement", "theme", "ride", "castle", "palace", "hanbok", "restaurant", "market", "nanta", "nania"})
    people_a, people_b = _people(first), _people(second)
    people = any(people_a.get(key) is True and people_b.get(key) is True for key in ("group_photo", "selfie"))
    score = .30 * category + .16 * activity + .10 * scene + .24 * landmark + .30 * overlap + .08 * people
    return min(1.0, score), {"category": category, "activity": activity, "scene": scene,
                             "landmark": landmark, "token_overlap": overlap > 0, "distinctive_overlap": distinctive}


def scene_role(item: dict[str, Any]) -> str:
    vision = _vision(item); people = _people(item); category = _category(item); activity = _activity(item)
    if str(item.get("id", "")).startswith("video-"): return "motion"
    if people.get("group_photo") is True or people.get("selfie") is True: return "people"
    if category in {"food", "detail"} or _scene(item) in {"indoor", "restaurant", "market"}: return "detail"
    if activity and activity not in {"tourism", "photography", "visiting"}: return "activity"
    if category in {"landmark", "cityscape", "nature", "transportation"}: return "establishing"
    if vision.get("mood") in {"calm", "nostalgic", "romantic"}: return "closing"
    return "activity"


def coherence_metrics(event_ids: list[str], teaser_event_id: str | None = None) -> dict[str, int]:
    collapsed = [value for index, value in enumerate(event_ids) if index == 0 or value != event_ids[index - 1]]
    switches = max(0, len(collapsed) - 1)
    fragments = 0
    for event_id in set(collapsed):
        appearances = collapsed.count(event_id)
        if teaser_event_id == event_id and collapsed and collapsed[0] == event_id: appearances -= 1
        fragments += max(0, appearances - 1)
    return {"event_switch_count": switches, "event_fragmentation_count": fragments}


def _event_order_key(members: list[tuple[dict[str, Any], int]]) -> tuple[Any, ...]:
    times = [_capture(item) for item, _ in members if _capture(item) is not None]
    sequences = [_sequence(item) for item, _ in members if _sequence(item) is not None]
    return (0 if times else 1, min(times) if times else datetime.max, 0 if sequences else 1,
            min(sequences) if sequences else 10**12, min(index for _, index in members))


def _within_event_key(item: dict[str, Any], index: int) -> tuple[Any, ...]:
    return (SCENE_ROLE_ORDER[scene_role(item)], _capture(item) is None, _capture(item) or datetime.max,
            _sequence(item) is None, _sequence(item) or 10**12, index, str(item.get("id")))


def _event_evidence(members: list[tuple[dict[str, Any], int]]) -> list[str]:
    evidence = []
    categories = [_category(item) for item, _ in members]
    if len(members) > 1 and len(set(categories)) == 1: evidence.append(f"shared_category:{categories[0]}")
    sequences = sorted(value for item, _ in members if (value := _sequence(item)) is not None)
    if len(sequences) > 1: evidence.append(f"filename_sequence:{sequences[0]}-{sequences[-1]}")
    times = sorted(value for item, _ in members if (value := _capture(item)) is not None)
    if len(times) > 1: evidence.append(f"capture_span_seconds:{int((times[-1]-times[0]).total_seconds())}")
    common = None
    for item, _ in members: common = _semantic_tokens(item) if common is None else common & _semantic_tokens(item)
    if common: evidence.append("shared_semantics:" + ",".join(sorted(common)[:5]))
    if any(str(item["id"]).startswith("photo-") for item, _ in members) and any(str(item["id"]).startswith("video-") for item, _ in members):
        evidence.append("mixed_media_continuity")
    return evidence or ["stable_source_context"]


def _label(members: list[tuple[dict[str, Any], int]], dominant: str) -> str:
    landmarks = [_landmark(item) for item, _ in members if _landmark(item)]
    if landmarks and landmarks.count(_mode(landmarks, "")) >= 2: return _slug(_mode(landmarks, "")) + "_visit"
    suffix = {"theme_park": "visit", "landmark": "visit", "food": "experience", "cityscape": "exploration"}.get(dominant)
    return _slug(dominant + ("_" + suffix if suffix else ""))


def _all_media(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for key in ("photos", "videos") for item in manifest.get(key, []) if isinstance(item, dict)]
def _vision(item: dict[str, Any]) -> dict[str, Any]: return item.get("vision") if isinstance(item.get("vision"), dict) else {}
def _category(item: dict[str, Any]) -> str: return str(_vision(item).get("travel_category") or "other").lower()
def _activity(item: dict[str, Any]) -> str: return str(_vision(item).get("activity") or "").lower()
def _scene(item: dict[str, Any]) -> str: return str(_vision(item).get("scene_type") or "").lower()
def _people(item: dict[str, Any]) -> dict[str, Any]:
    value = _vision(item).get("people"); return value if isinstance(value, dict) else {}
def _landmark(item: dict[str, Any]) -> str:
    value = _vision(item).get("landmark_hint"); name = value.get("name") if isinstance(value, dict) else None
    return _slug(str(name)) if name else ""
def _semantic_tokens(item: dict[str, Any]) -> set[str]:
    vision = _vision(item); values = [vision.get("description", ""), *vision.get("tags", []), *vision.get("objects", [])]
    return {token for token in re.findall(r"[a-z0-9]+", " ".join(map(str, values)).lower()) if len(token) > 2 and token not in _STOP}
def _sequence(item: dict[str, Any]) -> int | None:
    matches = re.findall(r"\d+", Path(str(item.get("path", ""))).stem)
    return int(matches[-1]) if matches else None
def _sequence_gap(a: dict[str, Any], b: dict[str, Any]) -> int | None:
    left, right = _sequence(a), _sequence(b); return abs(left-right) if left is not None and right is not None else None
def _capture(item: dict[str, Any]) -> datetime | None:
    try: return datetime.fromisoformat(str(item.get("captured_at")).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError): return None
def _time_gap(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    left, right = _capture(a), _capture(b); return abs((left-right).total_seconds()) if left and right else None
def _mode(values: list[str], default: str) -> str:
    return sorted(Counter(values).items(), key=lambda pair: (-pair[1], pair[0]))[0][0] if values else default
def _slug(value: str) -> str: return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "travel_event"
