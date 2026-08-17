"""Provider-neutral Vision contracts, normalization, and validation."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

VISION_SCHEMA_VERSION = "1.0"
PROMPT_VERSION = "1.1"
PREPROCESSING_VERSION = "1.0"
VIDEO_SAMPLING_VERSION = "1.0"

TRAVEL_CATEGORIES = {
    "arrival", "transportation", "landmark", "food", "cafe", "shopping",
    "street", "nature", "cityscape", "nightlife", "accommodation",
    "theme_park", "activity", "portrait", "selfie", "group", "detail",
    "transition", "other",
}
SCENE_TYPES = {
    "indoor", "outdoor", "street", "restaurant", "cafe", "airport",
    "station", "hotel", "market", "park", "theme_park", "river",
    "mountain", "beach", "cityscape", "unknown",
}
MOODS = {
    "energetic", "joyful", "calm", "romantic", "luxurious", "playful",
    "adventurous", "nostalgic", "neutral",
}
QUALITY_LEVELS = {"low", "medium", "high"}


class VisionError(RuntimeError):
    """Base class for isolated Vision-stage failures."""


class VisionProviderUnavailable(VisionError):
    pass


class VisionTimeoutError(VisionError):
    pass


class VisionResponseValidationError(VisionError):
    pass


class VisionMediaUnsupportedError(VisionError):
    pass


@dataclass(frozen=True)
class PeopleObservation:
    visible: bool = False
    group_photo: bool = False
    selfie: bool = False
    count_estimate: int | None = None


@dataclass(frozen=True)
class LandmarkHint:
    name: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class QualityObservations:
    subject_clear: bool | None = None
    composition_strength: str | None = None
    visual_clutter: str | None = None
    subject_prominence: str | None = None


@dataclass(frozen=True)
class VisionResult:
    description: str
    tags: list[str]
    travel_category: str
    scene_type: str
    activity: str | None
    mood: str | None
    people: PeopleObservation
    objects: list[str]
    landmark_hint: LandmarkHint
    quality_observations: QualityObservations
    confidence: dict[str, float] = field(default_factory=dict)
    vision_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@runtime_checkable
class VisionProvider(Protocol):
    """Provider-neutral interface consumed by the Vision pipeline."""

    name: str
    model: str

    def analyze_photo(self, media_id: str, image: Path) -> VisionResult: ...

    def analyze_video(
        self, media_id: str, frames: list[Path], timestamps: list[float]
    ) -> VisionResult: ...


def normalize_vision_result(payload: dict[str, Any]) -> VisionResult:
    """Normalize provider JSON into the strict internal Vision schema."""
    if not isinstance(payload, dict):
        raise VisionResponseValidationError("Vision response must be a JSON object")
    description = _clean_text(payload.get("description"), required=True, maximum=500)
    people_raw = payload.get("people") if isinstance(payload.get("people"), dict) else {}
    landmark_raw = payload.get("landmark_hint") if isinstance(payload.get("landmark_hint"), dict) else {}
    quality_raw = (
        payload.get("quality_observations")
        if isinstance(payload.get("quality_observations"), dict) else {}
    )
    count = people_raw.get("count_estimate")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        count = None
    confidence = _normalize_confidence(payload.get("confidence"))
    landmark_confidence = _confidence_value(landmark_raw.get("confidence"))
    landmark_name = _clean_text(landmark_raw.get("name"), maximum=120)
    if landmark_confidence is None or landmark_confidence < 0.7:
        landmark_name = None
    return VisionResult(
        description=description,
        tags=_normalize_terms(payload.get("tags"), 16),
        travel_category=_controlled(payload.get("travel_category"), TRAVEL_CATEGORIES, "other"),
        scene_type=_controlled(payload.get("scene_type"), SCENE_TYPES, "unknown"),
        activity=_clean_text(payload.get("activity"), maximum=80),
        mood=_controlled(payload.get("mood"), MOODS, None),
        people=PeopleObservation(
            visible=people_raw.get("visible") is True,
            group_photo=people_raw.get("group_photo") is True,
            selfie=people_raw.get("selfie") is True,
            count_estimate=count,
        ),
        objects=_normalize_terms(payload.get("objects"), 20),
        landmark_hint=LandmarkHint(landmark_name, landmark_confidence),
        quality_observations=QualityObservations(
            subject_clear=_optional_bool(quality_raw.get("subject_clear")),
            composition_strength=_controlled(
                quality_raw.get("composition_strength"), QUALITY_LEVELS, None
            ),
            visual_clutter=_controlled(quality_raw.get("visual_clutter"), QUALITY_LEVELS, None),
            subject_prominence=_controlled(
                quality_raw.get("subject_prominence"), QUALITY_LEVELS, None
            ),
        ),
        confidence=confidence,
    )


def validate_vision_result(payload: object) -> bool:
    """Return whether persisted data still satisfies the current schema."""
    try:
        if not isinstance(payload, dict):
            return False
        normalized = normalize_vision_result(payload)
        metadata = payload.get("vision_metadata")
        return bool(normalized.description and isinstance(metadata, dict))
    except VisionResponseValidationError:
        return False


def vision_cache_key(source_hash: str, provider: str, model: str, media_type: str) -> str:
    """Build a versioned cache identity independent of downstream stages."""
    identity = {
        "source_fingerprint": source_hash,
        "provider": provider,
        "model": model,
        "media_type": media_type,
        "vision_schema_version": VISION_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "video_sampling_version": VIDEO_SAMPLING_VERSION if media_type == "video" else None,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def metadata_for_result(
    source_hash: str,
    cache_key: str,
    provider: VisionProvider,
    analyzed_at: str,
    timestamps: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider.name,
        "model": provider.model,
        "vision_schema_version": VISION_SCHEMA_VERSION,
        "prompt_version": PROMPT_VERSION,
        "preprocessing_version": PREPROCESSING_VERSION,
        "video_sampling_version": VIDEO_SAMPLING_VERSION if timestamps is not None else None,
        "source_fingerprint": source_hash,
        "cache_key": cache_key,
        "analyzed_at": analyzed_at,
        "frame_timestamps": timestamps or [],
    }


def _clean_text(value: object, required: bool = False, maximum: int = 200) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip()[:maximum] if isinstance(value, str) else ""
    if required and not cleaned:
        raise VisionResponseValidationError("Vision description is required")
    return cleaned or None


def _normalize_terms(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    terms: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        term = re.sub(r"[^a-z0-9]+", "_", item.lower()).strip("_")[:60]
        if term and term not in terms:
            terms.append(term)
    return terms[:limit]


def _controlled(value: object, allowed: set[str], fallback: Any) -> Any:
    if not isinstance(value, str):
        return fallback
    normalized = re.sub(r"[\s-]+", "_", value.strip().lower())
    return normalized if normalized in allowed else fallback


def _optional_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _confidence_value(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if 0 <= value <= 1 else None


def _normalize_confidence(value: object) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): confidence
        for key, raw in value.items()
        if (confidence := _confidence_value(raw)) is not None
    }
