"""Deterministic, provider-neutral narrative construction for selected travel media."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .config import StoryConfig

STORY_VERSION = "1.0"
STORY_ROLES = frozenset({
    "hook", "arrival", "establishing", "exploration", "experience",
    "food", "transition", "highlight", "detail", "closing",
})
SECTION_ORDER = ("hook", "arrival", "establishing", "exploration", "experience", "highlight", "closing")


class StoryError(ValueError):
    """Base class for deterministic Story Engine contract failures."""


class StoryPrerequisiteError(StoryError):
    pass


class StoryValidationError(StoryError):
    pass


@runtime_checkable
class StoryProvider(Protocol):
    """Provider-neutral Story Engine boundary; no network provider is required."""

    name: str
    version: str

    def build(self, manifest: dict[str, Any], config: StoryConfig) -> dict[str, Any]: ...


class DeterministicStoryProvider:
    """Local zero-cost Story provider using only persisted candidate metadata."""

    name = "deterministic-local"
    version = STORY_VERSION

    def build(self, manifest: dict[str, Any], config: StoryConfig) -> dict[str, Any]:
        story = build_story(manifest, config)
        validate_story(story, manifest)
        return story


def build_story(manifest: dict[str, Any], config: StoryConfig) -> dict[str, Any]:
    """Build a grounded story from Sprint 4 primary candidates and justified alternates."""
    selection = manifest.get("selection")
    if not isinstance(selection, dict) or not isinstance(selection.get("primary_ids"), list):
        raise StoryPrerequisiteError("Trip Manifest has no Sprint 4 selection. Run 'select' first.")
    by_id = _media_by_id(manifest)
    primary_ids = _valid_candidate_ids(selection.get("primary_ids"), by_id, "primary")
    alternate_ids = _valid_candidate_ids(selection.get("alternate_ids", []), by_id, "alternate")
    if not primary_ids:
        raise StoryPrerequisiteError("Sprint 4 selection has no primary candidates")
    pool = [by_id[media_id] for media_id in primary_ids[: config.max_story_items]]
    alternate_uses = _add_justified_alternates(pool, alternate_ids, by_id, config)
    if not pool:
        raise StoryPrerequisiteError("Story candidate pool is empty")

    hook = max(pool, key=lambda item: (_hook_strength(item), _stable_inverse_id(item)))
    closing_candidates = [item for item in pool if item["id"] != hook["id"]]
    closing = max(
        closing_candidates or [hook],
        key=lambda item: (_closing_strength(item), _stable_inverse_id(item)),
    )
    reserved = {hook["id"], closing["id"]}
    middle = [item for item in pool if item["id"] not in reserved]
    highlight_count = min(config.highlight_target, max(0, len(middle) // 4 or (1 if middle else 0)))
    highlights = _choose_highlights(middle, highlight_count)
    highlight_ids = {item["id"] for item in highlights}
    body = [item for item in middle if item["id"] not in highlight_ids]
    grouped = _group_body(body)
    sections: list[dict[str, Any]] = []
    sections.append(_section("hook", [hook], config, 1))
    for role in ("arrival", "establishing", "exploration", "experience"):
        items = grouped.get(role, [])
        if items:
            sections.append(_section(role, _order_items(items, config), config, len(sections) + 1))
    if highlights:
        sections.append(_section("highlight", _order_items(highlights, config), config, len(sections) + 1))
    if closing["id"] != hook["id"]:
        sections.append(_section("closing", [closing], config, len(sections) + 1))

    alternate_reason_by_id = {entry["media_id"]: entry["reason"] for entry in alternate_uses}
    sequence: list[dict[str, Any]] = []
    for section in sections:
        for media_id in section["media_ids"]:
            item = by_id[media_id]
            role = _editorial_role(item, section["role"])
            reasons = _item_reasons(item, section["role"])
            if media_id in alternate_reason_by_id:
                reasons.append(alternate_reason_by_id[media_id])
            sequence.append({
                "position": len(sequence) + 1,
                "media_id": media_id,
                "scene_id": section["scene_id"],
                "section": section["role"],
                "editorial_role": role,
                "source_selection": "alternate" if media_id in alternate_reason_by_id else "primary",
                "reasons": reasons,
            })
    categories = Counter(_category(by_id[entry["media_id"]]) for entry in sequence)
    photo_count = sum(entry["media_id"].startswith("photo-") for entry in sequence)
    ordered_highlight_ids = [
        media_id for section in sections if section["role"] == "highlight"
        for media_id in section["media_ids"]
    ]
    story = {
        "story_version": STORY_VERSION,
        "provider": DeterministicStoryProvider.name,
        "title": _trip_title(manifest),
        "style": config.style,
        "structure": [section["role"] for section in sections],
        "hook_media_id": hook["id"],
        "highlight_media_ids": ordered_highlight_ids,
        "closing_media_id": closing["id"],
        "scenes": sections,
        "sequence": sequence,
        "alternate_uses": alternate_uses,
        "summary": {
            "item_count": len(sequence),
            "section_count": len(sections),
            "primary_count": len(sequence) - len(alternate_uses),
            "alternate_count": len(alternate_uses),
            "photos": photo_count,
            "videos": len(sequence) - photo_count,
            "categories": dict(sorted(categories.items())),
        },
    }
    return story


def validate_story(story: object, manifest: dict[str, Any]) -> None:
    """Reject invalid story references, roles, ordering, and media reuse."""
    if not isinstance(story, dict) or story.get("story_version") != STORY_VERSION:
        raise StoryValidationError("Invalid or unsupported Story schema version")
    scenes = story.get("scenes"); sequence = story.get("sequence")
    if not isinstance(scenes, list) or not scenes or not isinstance(sequence, list) or not sequence:
        raise StoryValidationError("Story requires non-empty scenes and sequence")
    existing = set(_media_by_id(manifest))
    scene_ids: set[str] = set(); sequence_ids: list[str] = []
    scene_media: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict) or scene.get("role") not in STORY_ROLES:
            raise StoryValidationError("Story scene has an invalid role")
        scene_id = scene.get("scene_id"); media_ids = scene.get("media_ids")
        if not isinstance(scene_id, str) or scene_id in scene_ids:
            raise StoryValidationError("Story scene IDs must be unique strings")
        if not isinstance(media_ids, list) or not media_ids:
            raise StoryValidationError("Story scenes cannot be empty")
        scene_ids.add(scene_id); scene_media.extend(media_ids)
    for expected_position, entry in enumerate(sequence, 1):
        if not isinstance(entry, dict) or entry.get("position") != expected_position:
            raise StoryValidationError("Story sequence positions must be contiguous")
        media_id = entry.get("media_id")
        if media_id not in existing:
            raise StoryValidationError(f"Story references unknown media ID: {media_id}")
        if entry.get("editorial_role") not in STORY_ROLES or entry.get("scene_id") not in scene_ids:
            raise StoryValidationError("Story sequence has invalid role or scene reference")
        sequence_ids.append(media_id)
    if len(sequence_ids) != len(set(sequence_ids)):
        raise StoryValidationError("Story cannot reuse media in V1")
    if sequence_ids != scene_media:
        raise StoryValidationError("Story scenes and sequence media must agree")
    allowed = set(manifest["selection"].get("primary_ids", [])) | set(
        manifest["selection"].get("alternate_ids", [])
    )
    if not set(sequence_ids) <= allowed:
        raise StoryValidationError("Story may use only Sprint 4 primary or alternate candidates")
    if story.get("hook_media_id") != sequence_ids[0] or story.get("closing_media_id") != sequence_ids[-1]:
        raise StoryValidationError("Story must begin with its hook and end with its closing media")


def _add_justified_alternates(
    pool: list[dict[str, Any]], alternate_ids: list[str], by_id: dict[str, dict[str, Any]],
    config: StoryConfig,
) -> list[dict[str, str]]:
    uses: list[dict[str, str]] = []
    remaining = [by_id[media_id] for media_id in alternate_ids]
    requirements = (
        ("hook_candidate", "alternate_used:missing_hook_candidate"),
        ("establishing", "alternate_used:missing_context_candidate"),
        ("closing_candidate", "alternate_used:missing_closing_candidate"),
    )
    for role, reason in requirements:
        if len(uses) >= config.max_alternates or _has_candidate_role(pool, role):
            continue
        choices = [item for item in remaining if role in _candidate_roles(item)]
        if choices:
            chosen = max(choices, key=lambda item: (_general_strength(item), _stable_inverse_id(item)))
            _insert_alternate(pool, chosen, config)
            remaining.remove(chosen)
            uses.append({"media_id": chosen["id"], "reason": reason})
    while len(pool) < config.min_story_items and remaining and len(uses) < config.max_alternates:
        chosen = max(remaining, key=lambda item: (_general_strength(item), _stable_inverse_id(item)))
        pool.append(chosen); remaining.remove(chosen)
        uses.append({"media_id": chosen["id"], "reason": "alternate_used:minimum_story_coverage"})
    return uses


def _insert_alternate(pool: list[dict[str, Any]], chosen: dict[str, Any], config: StoryConfig) -> None:
    pool.append(chosen)
    if len(pool) <= config.max_story_items:
        return
    protected = {"hook_candidate", "establishing", "closing_candidate"}
    removable = [item for item in pool if item["id"] != chosen["id"] and not (set(_candidate_roles(item)) & protected)]
    target = min(removable or [item for item in pool if item["id"] != chosen["id"]], key=lambda item: (_general_strength(item), item["id"]))
    pool.remove(target)


def _group_body(items: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {role: [] for role in ("arrival", "establishing", "exploration", "experience")}
    for item in items:
        category, scene = _category(item), _scene(item)
        roles = _candidate_roles(item)
        if category in {"arrival", "transportation", "accommodation", "transition"} or scene in {"airport", "station", "hotel"}:
            result["arrival"].append(item)
        elif category in {"food", "cafe", "activity", "theme_park", "nightlife", "group", "portrait", "selfie"}:
            result["experience"].append(item)
        elif category in {"street", "shopping", "cityscape", "nature", "landmark", "detail"}:
            result["exploration"].append(item)
        elif "activity" in roles:
            result["experience"].append(item)
        else:
            result["exploration"].append(item)
    if not result["arrival"]:
        establishing = [item for item in result["exploration"] if "establishing" in _candidate_roles(item)]
        for item in establishing[:2]:
            result["exploration"].remove(item); result["establishing"].append(item)
    return result


def _choose_highlights(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []; remaining = list(items)
    while remaining and len(chosen) < count:
        categories = {_category(item) for item in chosen}
        ranked = sorted(
            remaining,
            key=lambda item: (-(_highlight_strength(item) + (8 if _category(item) not in categories else 0)), item["id"]),
        )
        chosen.append(ranked[0]); remaining.remove(ranked[0])
    return chosen


def _order_items(items: list[dict[str, Any]], config: StoryConfig) -> list[dict[str, Any]]:
    timestamped = [(item, _capture_time(item)) for item in items]
    reliable = sum(value is not None for _, value in timestamped) / len(items) >= config.chronology_min_ratio
    if reliable:
        return sorted(items, key=lambda item: (_capture_time(item) is None, _capture_time(item) or datetime.max, item["id"]))
    ordered: list[dict[str, Any]] = []; remaining = list(items)
    while remaining:
        previous = ordered[-1] if ordered else None
        pick = max(
            remaining,
            key=lambda item: (_rhythm_utility(item, previous), _stable_inverse_id(item)),
        )
        ordered.append(pick); remaining.remove(pick)
    return ordered


def _section(role: str, items: list[dict[str, Any]], config: StoryConfig, number: int) -> dict[str, Any]:
    priorities = [_general_strength(item) for item in items]
    section_bonus = {"hook": 10, "highlight": 8, "closing": 5, "arrival": 4}.get(role, 0)
    return {
        "scene_id": f"story-scene-{number:02d}",
        "title": {
            "hook": "Opening Hook", "arrival": "Journey Context", "establishing": "Destination Context",
            "exploration": "Exploration", "experience": "Travel Experiences",
            "highlight": "Highlights", "closing": "Closing Memory",
        }[role],
        "role": role,
        "media_ids": [item["id"] for item in items],
        "reasons": _section_reasons(role, items),
        "priority": round(min(1.0, (sum(priorities) / len(priorities) + section_bonus) / 100), 3),
        "pacing": {"hook": "dynamic", "arrival": "moderate", "establishing": "moderate", "exploration": "moderate", "experience": "dynamic", "highlight": "dynamic", "closing": "slow"}[role],
    }


def _editorial_role(item: dict[str, Any], section: str) -> str:
    category = _category(item); roles = _candidate_roles(item)
    if section in {"hook", "highlight", "closing", "arrival", "establishing"}: return section
    if category in {"food", "cafe"}: return "food"
    if category == "transition" or "transition" in roles: return "transition"
    if category == "detail": return "detail"
    return "experience" if section == "experience" else "exploration"


def _item_reasons(item: dict[str, Any], section: str) -> list[str]:
    reasons = [f"section_fit:{section}", f"category:{_category(item)}"]
    roles = _candidate_roles(item)
    matching = {"hook": "hook_candidate", "establishing": "establishing", "closing": "closing_candidate"}.get(section)
    if matching and matching in roles: reasons.append(f"candidate_role:{matching}")
    if item["id"].startswith("video-"): reasons.append("media_type:video")
    if _component(item, "story_value") >= 82: reasons.append("score:strong_story_value")
    return reasons[:4]


def _section_reasons(role: str, items: list[dict[str, Any]]) -> list[str]:
    categories = sorted({_category(item) for item in items})
    return [f"narrative_role:{role}", "categories:" + ",".join(categories)]


def _hook_strength(item: dict[str, Any]) -> float:
    value = 0.25 * _total(item) + 0.30 * _component(item, "story_value") + 0.20 * _component(item, "emotion") + 0.15 * _component(item, "uniqueness")
    if "hook_candidate" in _candidate_roles(item): value += 14
    if item["id"].startswith("video-"): value += 8
    if _category(item) in {"landmark", "theme_park", "cityscape", "nightlife", "activity"}: value += 5
    people = _vision(item).get("people")
    if isinstance(people, dict) and (people.get("group_photo") is True or people.get("selfie") is True): value -= 8
    if _vision(item).get("mood") in {"calm", "romantic", "nostalgic"}: value -= 3
    return value


def _highlight_strength(item: dict[str, Any]) -> float:
    value = 0.20 * _total(item) + 0.35 * _component(item, "story_value") + 0.25 * _component(item, "emotion") + 0.15 * _component(item, "uniqueness")
    if _category(item) in {"landmark", "theme_park", "activity", "nightlife"}: value += 8
    if item["id"].startswith("video-"): value += 5
    return value


def _closing_strength(item: dict[str, Any]) -> float:
    value = 0.20 * _total(item) + 0.25 * _component(item, "story_value") + 0.25 * _component(item, "emotion") + 0.15 * _component(item, "uniqueness")
    if "closing_candidate" in _candidate_roles(item): value += 18
    if _vision(item).get("mood") in {"calm", "romantic", "nostalgic"}: value += 8
    if _category(item) in {"nightlife", "cityscape", "group", "transportation"}: value += 6
    return value


def _general_strength(item: dict[str, Any]) -> float:
    return 0.45 * _total(item) + 0.30 * _component(item, "story_value") + 0.15 * _component(item, "uniqueness") + 0.10 * _component(item, "emotion")


def _rhythm_utility(item: dict[str, Any], previous: dict[str, Any] | None) -> float:
    value = _general_strength(item)
    if previous:
        if _category(item) == _category(previous): value -= 10
        if _scene(item) == _scene(previous): value -= 6
        if item["id"].split("-", 1)[0] == previous["id"].split("-", 1)[0]: value -= 3
    return value


def _valid_candidate_ids(value: object, by_id: dict[str, dict[str, Any]], label: str) -> list[str]:
    if not isinstance(value, list):
        raise StoryPrerequisiteError(f"Sprint 4 {label} candidate IDs must be an array")
    result: list[str] = []
    for media_id in value:
        if not isinstance(media_id, str) or media_id not in by_id:
            raise StoryPrerequisiteError(f"Sprint 4 selection references unknown media ID: {media_id}")
        if media_id not in result: result.append(media_id)
    return result


def _media_by_id(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for collection in ("photos", "videos"):
        for item in manifest.get(collection, []):
            if isinstance(item, dict) and isinstance(item.get("id"), str): result[item["id"]] = item
    return result


def _candidate_roles(item: dict[str, Any]) -> list[str]:
    selection = item.get("selection")
    value = selection.get("candidate_roles") if isinstance(selection, dict) else None
    return [role for role in value if isinstance(role, str)] if isinstance(value, list) else []


def _has_candidate_role(items: list[dict[str, Any]], role: str) -> bool:
    return any(role in _candidate_roles(item) for item in items)


def _vision(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("vision") if isinstance(item.get("vision"), dict) else {}


def _score(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("score") if isinstance(item.get("score"), dict) else {}


def _total(item: dict[str, Any]) -> float:
    value = _score(item).get("total"); return float(value) if isinstance(value, (int, float)) else 50.0


def _component(item: dict[str, Any], name: str) -> float:
    value = _score(item).get(name); return float(value) if isinstance(value, (int, float)) else 50.0


def _category(item: dict[str, Any]) -> str:
    value = _vision(item).get("travel_category"); return value if isinstance(value, str) else "other"


def _scene(item: dict[str, Any]) -> str:
    value = _vision(item).get("scene_type"); return value if isinstance(value, str) else "unknown"


def _capture_time(item: dict[str, Any]) -> datetime | None:
    value = item.get("captured_at")
    if not isinstance(value, str) or not value: return None
    try: return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError: return None


def _stable_inverse_id(item: dict[str, Any]) -> tuple[int, ...]:
    return tuple(-ord(character) for character in item["id"])


def _trip_title(manifest: dict[str, Any]) -> str:
    trip = manifest.get("trip"); name = trip.get("name") if isinstance(trip, dict) else None
    return name if isinstance(name, str) and name.strip() else "Travel Highlights"
