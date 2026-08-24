"""Small dependency-free configuration layer for travel-reel stages."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


DEFAULT_SCORING_WEIGHTS = {
    "technical_quality": 0.15,
    "composition": 0.15,
    "travel_relevance": 0.20,
    "story_value": 0.20,
    "uniqueness": 0.10,
    "emotion": 0.10,
    "vertical_suitability": 0.10,
}


@dataclass(frozen=True)
class VisionConfig:
    """Runtime settings for the provider-neutral Vision stage."""

    provider: str = "local"
    model: str = "qwen3-vl:4b-instruct"
    endpoint: str = "http://localhost:11434"
    timeout_seconds: float = 120.0
    retries: int = 1
    longest_edge: int = 768
    jpeg_quality: int = 88
    cache_dir_name: str = ".travel_reel_cache/vision"

    def __post_init__(self) -> None:
        if self.provider != "local":
            raise ValueError(f"Unsupported Vision provider: {self.provider}")
        if not self.model or not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("Vision model and HTTP endpoint are required")
        if self.timeout_seconds <= 0 or self.retries < 0:
            raise ValueError("Vision timeout must be positive and retries cannot be negative")
        if self.longest_edge <= 0 or not 1 <= self.jpeg_quality <= 100:
            raise ValueError("Invalid Vision image preprocessing configuration")


@dataclass(frozen=True)
class ScoringConfig:
    """Weights for deterministic editorial scoring."""

    technical_quality: float = 0.15
    composition: float = 0.15
    travel_relevance: float = 0.20
    story_value: float = 0.20
    uniqueness: float = 0.10
    emotion: float = 0.10
    vertical_suitability: float = 0.10

    def __post_init__(self) -> None:
        values = self.weights.values()
        if any(value < 0 for value in values):
            raise ValueError("Scoring weights cannot be negative")
        if abs(sum(values) - 1.0) > 0.001:
            raise ValueError(f"Scoring weights must sum to 1.0; got {sum(values):.6f}")

    @property
    def weights(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in DEFAULT_SCORING_WEIGHTS}


@dataclass(frozen=True)
class SelectionConfig:
    """Candidate-pool targets and soft diversity controls."""

    primary_target: int = 20
    alternate_target: int = 10
    min_video_target: int = 4
    max_video_target: int = 8
    selfie_soft_ratio: float = 0.25
    people_soft_ratio: float = 0.40
    category_soft_ratio: float = 0.30
    duplicate_time_seconds: float = 180.0
    duplicate_similarity: float = 0.72
    duplicate_similarity_without_time: float = 0.53
    minimum_video_score: float = 45.0

    def __post_init__(self) -> None:
        if self.primary_target <= 0 or self.alternate_target < 0:
            raise ValueError("Selection targets must be positive (alternate may be zero)")
        if not 0 <= self.min_video_target <= self.max_video_target <= self.primary_target:
            raise ValueError("Video targets must satisfy 0 <= min <= max <= primary target")
        ratios = (
            self.selfie_soft_ratio,
            self.people_soft_ratio,
            self.category_soft_ratio,
            self.duplicate_similarity,
            self.duplicate_similarity_without_time,
        )
        if any(not 0 <= value <= 1 for value in ratios):
            raise ValueError("Selection ratios and similarity thresholds must be within 0..1")
        if self.duplicate_time_seconds < 0 or not 0 <= self.minimum_video_score <= 100:
            raise ValueError("Invalid duplicate window or minimum video score")


def load_vision_config(path: Path | None = None) -> VisionConfig:
    """Load the known `vision:` YAML keys without requiring PyYAML."""
    config = VisionConfig()
    config_path = path or Path("configs/default.yaml")
    if config_path.is_file():
        values = _vision_yaml_values(config_path.read_text(encoding="utf-8-sig"))
        conversions = {
            "provider": str,
            "model": str,
            "endpoint": str,
            "timeout_seconds": float,
            "retries": int,
            "longest_edge": int,
            "jpeg_quality": int,
            "cache_dir_name": str,
        }
        updates = {key: conversions[key](value) for key, value in values.items() if key in conversions}
        config = replace(config, **updates)
    env_updates = {
        "model": os.getenv("TRAVEL_REEL_VISION_MODEL"),
        "endpoint": os.getenv("TRAVEL_REEL_OLLAMA_ENDPOINT"),
    }
    return replace(config, **{key: value for key, value in env_updates.items() if value})


def load_scoring_config(path: Path | None = None) -> ScoringConfig:
    """Load the dependency-free ``scoring:`` section."""
    values = _yaml_section_values(_config_text(path), "scoring")
    known = DEFAULT_SCORING_WEIGHTS.keys()
    return ScoringConfig(**{key: float(values[key]) for key in known if key in values})


def load_selection_config(path: Path | None = None) -> SelectionConfig:
    """Load the dependency-free ``selection:`` section."""
    values = _yaml_section_values(_config_text(path), "selection")
    integer_keys = {"primary_target", "alternate_target", "min_video_target", "max_video_target"}
    known = SelectionConfig.__dataclass_fields__
    updates = {
        key: (int(value) if key in integer_keys else float(value))
        for key, value in values.items()
        if key in known
    }
    return SelectionConfig(**updates)


def _vision_yaml_values(text: str) -> dict[str, str]:
    return _yaml_section_values(text, "vision")


def _config_text(path: Path | None) -> str:
    config_path = path or Path("configs/default.yaml")
    return config_path.read_text(encoding="utf-8-sig") if config_path.is_file() else ""


def _yaml_section_values(text: str, section: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_section = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            in_section = line.strip() == f"{section}:"
            continue
        if in_section and ":" in line:
            key, value = line.strip().split(":", 1)
            values[key] = value.strip().strip('"\'')
    return values
