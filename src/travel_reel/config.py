"""Small dependency-free configuration layer for travel-reel stages."""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


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


def _vision_yaml_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    in_vision = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            in_vision = line.strip() == "vision:"
            continue
        if in_vision and ":" in line:
            key, value = line.strip().split(":", 1)
            values[key] = value.strip().strip('"\'')
    return values
