"""Deterministic, explainable scoring for Vision-enriched manifest media."""
from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from .config import ScoringConfig
from .vision import validate_vision_result

SCORING_VERSION = "1.0"
NEUTRAL_SCORE = 50.0

_TRAVEL_RELEVANCE = {
    "landmark": 95, "arrival": 90, "transportation": 88, "nature": 90,
    "cityscape": 90, "theme_park": 88, "food": 88, "cafe": 82,
    "street": 84, "activity": 88, "accommodation": 75, "nightlife": 82,
    "shopping": 72, "detail": 68, "transition": 65, "group": 62,
    "portrait": 55, "selfie": 55, "other": 45,
}
_STORY_VALUE = {
    "arrival": 95, "transportation": 90, "landmark": 90, "activity": 88,
    "food": 85, "cafe": 80, "theme_park": 86, "street": 80,
    "cityscape": 82, "nature": 82, "accommodation": 78, "nightlife": 82,
    "transition": 84, "detail": 72, "group": 78, "portrait": 66,
    "selfie": 65, "shopping": 72, "other": 50,
}
_EMOTION = {
    "joyful": 92, "energetic": 90, "playful": 88, "adventurous": 88,
    "romantic": 82, "calm": 76, "nostalgic": 74, "luxurious": 72,
    "neutral": 60,
}


def score_manifest(
    manifest: dict[str, Any],
    config: ScoringConfig,
    media_facts: dict[str, dict[str, float | int | None]] | None = None,
) -> dict[str, Any]:
    """Recompute all scoreable items in-place and return a distribution summary."""
    media_facts = media_facts or {}
    typed_items = [
        (item, media_type)
        for media_type, collection in (("photo", "photos"), ("video", "videos"))
        for item in manifest.get(collection, [])
        if isinstance(item, dict)
    ]
    scoreable = [(item, kind) for item, kind in typed_items if validate_vision_result(item.get("vision"))]
    category_counts = Counter(_vision(item).get("travel_category", "other") for item, _ in scoreable)
    scene_counts = Counter(_vision(item).get("scene_type", "unknown") for item, _ in scoreable)
    scored: list[dict[str, Any]] = []
    unscoreable: list[dict[str, str]] = []
    for item, media_type in typed_items:
        media_id = str(item.get("id", "unknown"))
        if not validate_vision_result(item.get("vision")):
            item["score"] = None
            item["score_error"] = "missing_or_invalid_vision"
            unscoreable.append({"media_id": media_id, "reason": "missing_or_invalid_vision"})
            continue
        result = score_media(
            item, media_type, config, media_facts.get(media_id, {}),
            category_counts, scene_counts, len(scoreable),
        )
        item["score"] = result
        item.pop("score_error", None)
        scored.append(item)
    totals = [float(item["score"]["total"]) for item in scored]
    ordered = sorted(scored, key=lambda item: (-item["score"]["total"], str(item["id"])))
    return {
        "version": SCORING_VERSION,
        "scored": len(scored),
        "unscoreable": len(unscoreable),
        "errors": unscoreable,
        "distribution": _distribution(totals),
        "top_ids": [item["id"] for item in ordered[:10]],
        "bottom_ids": [item["id"] for item in reversed(ordered[-10:])],
    }


def score_media(
    item: dict[str, Any], media_type: str, config: ScoringConfig,
    facts: dict[str, float | int | None], category_counts: Counter[str] | None = None,
    scene_counts: Counter[str] | None = None, trip_size: int = 1,
) -> dict[str, Any]:
    """Score one media record using only persisted Vision and supplied source facts."""
    vision = _vision(item)
    quality = vision.get("quality_observations")
    quality = quality if isinstance(quality, dict) else {}
    people = vision.get("people")
    people = people if isinstance(people, dict) else {}
    category = str(vision.get("travel_category") or "other")
    scene = str(vision.get("scene_type") or "unknown")
    technical = _technical_score(quality, media_type, facts)
    composition = _composition_score(quality, facts)
    travel = float(_TRAVEL_RELEVANCE.get(category, NEUTRAL_SCORE))
    if scene not in {"unknown", "indoor", "outdoor"}:
        travel = min(100.0, travel + 4.0)
    story = float(_STORY_VALUE.get(category, NEUTRAL_SCORE))
    activity = vision.get("activity")
    if isinstance(activity, str) and activity.strip():
        story = min(100.0, story + (7.0 if media_type == "video" else 4.0))
    if people.get("group_photo") is True:
        story = min(100.0, story + 5.0)
    uniqueness = _uniqueness_score(category, scene, category_counts, scene_counts, trip_size)
    emotion = float(_EMOTION.get(vision.get("mood"), NEUTRAL_SCORE))
    if people.get("visible") is True and vision.get("mood") not in {None, "neutral"}:
        emotion = min(100.0, emotion + 4.0)
    vertical = _vertical_score(facts.get("width"), facts.get("height"))
    components = {
        "technical_quality": technical, "composition": composition,
        "travel_relevance": travel, "story_value": story, "uniqueness": uniqueness,
        "emotion": emotion, "vertical_suitability": vertical,
    }
    penalties: list[dict[str, Any]] = []
    bonuses: list[dict[str, Any]] = []
    if not vision.get("tags") and not vision.get("objects"):
        penalties.append({"reason": "low_information", "points": 5.0})
    if media_type == "video" and isinstance(facts.get("duration"), (int, float)):
        duration = float(facts["duration"])
        if duration < 1.0:
            penalties.append({"reason": "very_short_video", "points": 8.0})
        elif 2.0 <= duration <= 30.0:
            bonuses.append({"reason": "usable_video_duration", "points": 2.0})
    weighted = sum(components[name] * weight for name, weight in config.weights.items())
    total = weighted - sum(entry["points"] for entry in penalties) + sum(
        entry["points"] for entry in bonuses
    )
    return {
        "total": _rounded(total),
        **{name: _rounded(value) for name, value in components.items()},
        "penalties": penalties, "bonuses": bonuses,
        "reasons": _score_reasons(components, media_type, people, category),
        "version": SCORING_VERSION,
    }


def _technical_score(quality: dict[str, Any], media_type: str, facts: dict[str, float | int | None]) -> float:
    values: list[float] = []
    if isinstance(quality.get("subject_clear"), bool):
        values.append(85.0 if quality["subject_clear"] else 25.0)
    level = {"low": 35.0, "medium": 65.0, "high": 90.0}
    if quality.get("visual_clutter") in level:
        values.append({"low": 85.0, "medium": 60.0, "high": 35.0}[quality["visual_clutter"]])
    if quality.get("subject_prominence") in level:
        values.append(level[quality["subject_prominence"]])
    width, height = facts.get("width"), facts.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)):
        short = min(float(width), float(height))
        values.append(90.0 if short >= 1080 else 75.0 if short >= 720 else 55.0 if short >= 480 else 35.0)
    if media_type == "video" and isinstance(facts.get("duration"), (int, float)):
        duration = float(facts["duration"])
        values.append(75.0 if 2 <= duration <= 60 else 55.0 if duration >= 1 else 30.0)
    return mean(values) if values else NEUTRAL_SCORE


def _composition_score(quality: dict[str, Any], facts: dict[str, float | int | None]) -> float:
    base = {"low": 30.0, "medium": 62.0, "high": 90.0}.get(quality.get("composition_strength"), NEUTRAL_SCORE)
    base += {"low": -8.0, "medium": 2.0, "high": 8.0}.get(quality.get("subject_prominence"), 0.0)
    base += {"low": 6.0, "medium": 0.0, "high": -8.0}.get(quality.get("visual_clutter"), 0.0)
    width, height = facts.get("width"), facts.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and height:
        ratio = float(width) / float(height)
        base += 4.0 if ratio < 1 else -3.0 if ratio > 1.8 else 0.0
    return _clamp(base)


def _vertical_score(width: object, height: object) -> float:
    if not isinstance(width, (int, float)) or not isinstance(height, (int, float)) or height <= 0:
        return NEUTRAL_SCORE
    ratio = float(width) / float(height)
    if ratio <= 0.75: return 95.0
    if ratio <= 1.1: return 82.0
    if ratio <= 1.5: return 68.0
    if ratio <= 1.9: return 55.0
    return 42.0


def _uniqueness_score(category: str, scene: str, category_counts: Counter[str] | None, scene_counts: Counter[str] | None, trip_size: int) -> float:
    if not category_counts or not scene_counts or trip_size <= 1:
        return 65.0
    return _clamp(82.0 - 32.0 * (category_counts[category] / trip_size) - 18.0 * (scene_counts[scene] / trip_size))


def _score_reasons(components: dict[str, float], media_type: str, people: dict[str, Any], category: str) -> list[str]:
    reasons = [f"strong {name.replace('_', ' ')}" for name, value in components.items() if value >= 82][:3]
    if media_type == "video" and components["technical_quality"] >= 60: reasons.append("usable motion source")
    if people.get("visible") is True and components["emotion"] >= 70: reasons.append("human interest")
    if category in {"arrival", "transportation", "transition"}: reasons.append("journey coverage")
    return reasons or ["balanced candidate value"]


def _vision(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("vision")
    return value if isinstance(value, dict) else {}


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values: return {"minimum": None, "maximum": None, "mean": None, "median": None}
    ordered = sorted(values); middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return {"minimum": _rounded(min(values)), "maximum": _rounded(max(values)), "mean": _rounded(mean(values)), "median": _rounded(median)}


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def _rounded(value: float) -> float:
    return round(_clamp(value), 2)
