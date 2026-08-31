"""Deterministic duplicate suppression and diversity-aware candidate selection."""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from datetime import datetime
from typing import Any

from .config import SelectionConfig

SELECTOR_VERSION = "1.0"


def select_manifest(manifest: dict[str, Any], config: SelectionConfig) -> dict[str, Any]:
    """Recompute selection state in-place without changing any media identity."""
    candidates = _eligible_media(manifest)
    groups, suppressed_by = group_duplicates(candidates, config)
    available = [item for item in candidates if item["id"] not in suppressed_by]
    primary = _choose(available, min(config.primary_target, len(available)), config, [])
    primary_ids = {item["id"] for item in primary}
    alternate_available = [item for item in available if item["id"] not in primary_ids]
    alternates = _choose(
        alternate_available,
        min(config.alternate_target, len(alternate_available)),
        config,
        primary,
    )
    alternate_ids = {item["id"] for item in alternates}
    group_by_id = {media_id: group_id for group_id, ids in groups.items() for media_id in ids}
    all_items = _all_media(manifest)
    primary_rank = {item["id"]: index + 1 for index, item in enumerate(primary)}
    alternate_rank = {item["id"]: index + 1 for index, item in enumerate(alternates)}
    for item in all_items:
        media_id = str(item.get("id", "unknown"))
        duplicate_group = group_by_id.get(media_id)
        if media_id in primary_ids:
            status, rank = "primary", primary_rank[media_id]
            reasons = _selection_reasons(item, primary[: rank - 1], "primary")
        elif media_id in alternate_ids:
            status, rank = "alternate", alternate_rank[media_id]
            reasons = _selection_reasons(item, primary, "alternate")
        elif media_id in suppressed_by:
            status, rank = "suppressed", None
            reasons = ["near-duplicate of stronger representative"]
        elif _valid_score(item):
            status, rank = "not_selected", None
            reasons = ["lower diversity-adjusted utility"]
        else:
            status, rank = "unscoreable", None
            reasons = ["missing valid Sprint 4 score"]
        item["selected"] = status == "primary"
        item["selection"] = {
            "status": status,
            "rank": rank,
            "candidate_roles": candidate_roles(item),
            "reasons": reasons,
            "duplicate_group": duplicate_group,
            "suppressed_by": suppressed_by.get(media_id),
            "suppression_reason": "near_duplicate" if media_id in suppressed_by else None,
            "version": SELECTOR_VERSION,
        }
    primary_plain = [_plain(item) for item in primary]
    alternate_plain = [_plain(item) for item in alternates]
    selection = {
        "version": SELECTOR_VERSION,
        "target_primary": config.primary_target,
        "target_alternate": config.alternate_target,
        "primary_ids": [item["id"] for item in primary],
        "alternate_ids": [item["id"] for item in alternates],
        "suppressed_ids": sorted(suppressed_by),
        "duplicate_groups": [
            {"id": group_id, "representative_id": ids[0], "media_ids": ids}
            for group_id, ids in sorted(groups.items())
        ],
        "summary": _summary(primary_plain, alternate_plain),
    }
    for item in all_items:
        item.pop("_media_type", None)
        item.pop("_ordinal_bucket", None)
    manifest["selection"] = selection
    return selection


def group_duplicates(
    candidates: list[dict[str, Any]], config: SelectionConfig
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Group explainable exact/near duplicates and retain the strongest member."""
    parent = {item["id"]: item["id"] for item in candidates}

    def find(media_id: str) -> str:
        while parent[media_id] != media_id:
            parent[media_id] = parent[parent[media_id]]
            media_id = parent[media_id]
        return media_id

    def union(first: str, second: str) -> None:
        a, b = find(first), find(second)
        if a != b:
            parent[max(a, b)] = min(a, b)

    ordered = sorted(candidates, key=lambda item: item["id"])
    for index, first in enumerate(ordered):
        for second in ordered[index + 1:]:
            first_event = (first.get("event") or {}).get("event_id")
            second_event = (second.get("event") or {}).get("event_id")
            if first_event and second_event and first_event != second_event:
                continue
            if first["_media_type"] != second["_media_type"]:
                continue
            if _exact_fingerprint(first) and _exact_fingerprint(first) == _exact_fingerprint(second):
                union(first["id"], second["id"])
                continue
            proximity = _time_distance(first, second)
            similarity = semantic_similarity(first, second)
            if proximity is not None:
                duplicate = proximity <= config.duplicate_time_seconds and similarity >= config.duplicate_similarity
            else:
                duplicate = similarity >= config.duplicate_similarity_without_time
            if duplicate:
                union(first["id"], second["id"])
    clusters: dict[str, list[dict[str, Any]]] = {}
    for item in ordered:
        clusters.setdefault(find(item["id"]), []).append(item)
    groups: dict[str, list[str]] = {}
    suppressed: dict[str, str] = {}
    for members in clusters.values():
        if len(members) < 2:
            continue
        ranked = sorted(members, key=lambda item: (-_score(item), item["id"]))
        ids = [item["id"] for item in ranked]
        digest = hashlib.sha256("\0".join(sorted(ids)).encode()).hexdigest()[:12]
        group_id = f"duplicate-{digest}"
        groups[group_id] = ids
        for media_id in ids[1:]:
            suppressed[media_id] = ids[0]
    return groups, suppressed


def semantic_similarity(first: dict[str, Any], second: dict[str, Any]) -> float:
    """Return a transparent 0..1 semantic similarity from persisted Vision fields."""
    a, b = _vision(first), _vision(second)
    score = 0.25 * _jaccard(_terms(a.get("tags")), _terms(b.get("tags")))
    score += 0.25 * _jaccard(_tokens(a.get("description")), _tokens(b.get("description")))
    score += 0.15 * _jaccard(_terms(a.get("objects")), _terms(b.get("objects")))
    score += 0.12 if a.get("travel_category") == b.get("travel_category") else 0.0
    score += 0.10 if a.get("scene_type") == b.get("scene_type") else 0.0
    score += 0.05 if a.get("activity") and a.get("activity") == b.get("activity") else 0.0
    people_a, people_b = a.get("people"), b.get("people")
    if isinstance(people_a, dict) and isinstance(people_b, dict):
        state_a = (people_a.get("visible"), people_a.get("selfie"), people_a.get("group_photo"))
        state_b = (people_b.get("visible"), people_b.get("selfie"), people_b.get("group_photo"))
        score += 0.08 if state_a == state_b else 0.0
    return round(min(1.0, score), 6)


def candidate_roles(item: dict[str, Any]) -> list[str]:
    vision = _vision(item); category = vision.get("travel_category"); scene = vision.get("scene_type")
    people = vision.get("people") if isinstance(vision.get("people"), dict) else {}
    roles: list[str] = []
    if category in {"arrival", "transportation", "landmark", "cityscape", "street"} or scene in {"airport", "station", "cityscape"}:
        roles.append("hook_candidate")
    if category in {"cityscape", "street", "nature", "landmark", "arrival", "accommodation"}:
        roles.append("establishing")
    if people.get("visible") is True: roles.append("people")
    if category in {"activity", "theme_park"} or vision.get("activity"): roles.append("activity")
    if category == "landmark" or _landmark_name(vision): roles.append("landmark")
    if category in {"food", "cafe"}: roles.append("food")
    if category == "detail" or scene in {"indoor", "market"}: roles.append("detail")
    if category in {"arrival", "transportation", "transition"}: roles.append("transition")
    if vision.get("mood") in {"calm", "romantic", "nostalgic"} or category in {"nightlife", "cityscape", "group"}:
        roles.append("closing_candidate")
    return roles or ["detail"]


def _choose(
    available: list[dict[str, Any]], target: int, config: SelectionConfig,
    seed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    remaining = list(available)
    while remaining and len(chosen) < target:
        context = [*seed, *chosen]
        slots = target - len(chosen)
        ranked = sorted(
            remaining,
            key=lambda item: (-_utility(item, context, slots, config), -_score(item), item["id"]),
        )
        pick = ranked[0]
        chosen.append(pick)
        remaining.remove(pick)
    return chosen


def _utility(item: dict[str, Any], chosen: list[dict[str, Any]], slots: int, config: SelectionConfig) -> float:
    vision = _vision(item); people = vision.get("people") if isinstance(vision.get("people"), dict) else {}
    categories = Counter(_vision(entry).get("travel_category") for entry in chosen)
    scenes = Counter(_vision(entry).get("scene_type") for entry in chosen)
    video_count = sum(entry["_media_type"] == "video" for entry in chosen)
    selfie_count = sum(_people(entry).get("selfie") is True for entry in chosen)
    people_count = sum(_people(entry).get("visible") is True for entry in chosen)
    value = _score(item)
    category, scene = vision.get("travel_category"), vision.get("scene_type")
    event_id = (item.get("event") or {}).get("event_id")
    chosen_events = {(entry.get("event") or {}).get("event_id") for entry in chosen}
    if event_id and event_id not in chosen_events: value += 14.0
    if category not in categories: value += 10.0
    if scene not in scenes: value += 6.0
    if _bucket(item) not in {_bucket(entry) for entry in chosen}: value += 5.0
    needed_videos = max(0, config.min_video_target - video_count)
    if item["_media_type"] == "video" and _score(item) >= config.minimum_video_score and needed_videos:
        value += 18.0
    if item["_media_type"] == "photo" and slots <= needed_videos:
        value -= 40.0
    if item["_media_type"] == "video" and video_count >= config.max_video_target:
        value -= 35.0
    prospective = len(chosen) + 1
    if people.get("selfie") is True and (selfie_count + 1) / prospective > config.selfie_soft_ratio:
        value -= 22.0
    if people.get("visible") is True and (people_count + 1) / prospective > config.people_soft_ratio:
        value -= 12.0
    category_limit = max(2, math.ceil(config.primary_target * config.category_soft_ratio))
    if categories[category] >= category_limit: value -= 18.0 + 3.0 * (categories[category] - category_limit)
    scene_limit = max(2, math.ceil(config.primary_target * 0.30))
    if scenes[scene] >= scene_limit: value -= 12.0
    return value


def _selection_reasons(item: dict[str, Any], chosen: list[dict[str, Any]], status: str) -> list[str]:
    vision = _vision(item); reasons = [f"{status} candidate score {_score(item):.2f}"]
    if vision.get("travel_category") not in {_vision(entry).get("travel_category") for entry in chosen}:
        reasons.append("adds category diversity")
    if item.get("_media_type") == "video": reasons.append("preserves motion coverage")
    if _people(item).get("visible") is not True: reasons.append("balances people and environment")
    return reasons[:3]


def _eligible_media(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    all_items = _all_media(manifest)
    total = max(1, len(all_items))
    for index, item in enumerate(all_items):
        if not _valid_score(item): continue
        item["_media_type"] = "video" if str(item.get("id", "")).startswith("video-") else "photo"
        item["_ordinal_bucket"] = min(3, index * 4 // total)
        result.append(item)
    return result


def _all_media(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for key in ("photos", "videos") for item in manifest.get(key, []) if isinstance(item, dict)]


def _plain(item: dict[str, Any]) -> dict[str, Any]:
    return item


def _summary(primary: list[dict[str, Any]], alternates: list[dict[str, Any]]) -> dict[str, Any]:
    categories = Counter(_vision(item).get("travel_category", "other") for item in primary)
    scenes = Counter(_vision(item).get("scene_type", "unknown") for item in primary)
    selfies = sum(_people(item).get("selfie") is True for item in primary)
    groups = sum(_people(item).get("group_photo") is True for item in primary)
    people = sum(_people(item).get("visible") is True for item in primary)
    count = len(primary)
    return {
        "primary_count": count, "alternate_count": len(alternates),
        "photos": sum(item["_media_type"] == "photo" for item in primary),
        "videos": sum(item["_media_type"] == "video" for item in primary),
        "categories": dict(sorted(categories.items())), "scene_types": dict(sorted(scenes.items())),
        "selfies": selfies, "groups": groups, "people": people,
        "selfie_ratio": round(selfies / count, 3) if count else 0.0,
        "group_ratio": round(groups / count, 3) if count else 0.0,
        "people_ratio": round(people / count, 3) if count else 0.0,
    }


def _valid_score(item: dict[str, Any]) -> bool:
    score = item.get("score")
    return isinstance(score, dict) and score.get("version") == "1.0" and isinstance(score.get("total"), (int, float))


def _score(item: dict[str, Any]) -> float:
    return float(item["score"]["total"])


def _vision(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("vision") if isinstance(item.get("vision"), dict) else {}


def _people(item: dict[str, Any]) -> dict[str, Any]:
    value = _vision(item).get("people")
    return value if isinstance(value, dict) else {}


def _landmark_name(vision: dict[str, Any]) -> object:
    value = vision.get("landmark_hint")
    return value.get("name") if isinstance(value, dict) else None


def _exact_fingerprint(item: dict[str, Any]) -> str | None:
    metadata = _vision(item).get("vision_metadata")
    value = metadata.get("source_fingerprint") if isinstance(metadata, dict) else None
    return value if isinstance(value, str) and value else None


def _time_distance(first: dict[str, Any], second: dict[str, Any]) -> float | None:
    try:
        a = datetime.fromisoformat(str(first["captured_at"]).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(second["captured_at"]).replace("Z", "+00:00"))
        return abs((a - b).total_seconds())
    except (KeyError, TypeError, ValueError):
        return None


def _bucket(item: dict[str, Any]) -> str:
    captured = item.get("captured_at")
    if isinstance(captured, str) and len(captured) >= 10: return captured[:10]
    return f"ordinal-{item.get('_ordinal_bucket', 0)}"


def _terms(value: object) -> set[str]:
    return {str(item).lower() for item in value} if isinstance(value, list) else set()


def _tokens(value: object) -> set[str]:
    if not isinstance(value, str): return set()
    stop = {"the", "a", "an", "and", "with", "of", "in", "on", "to", "is", "are", "visible"}
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2 and token not in stop}


def _jaccard(first: set[str], second: set[str]) -> float:
    return len(first & second) / len(first | second) if first or second else 0.0
