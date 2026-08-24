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


@dataclass(frozen=True)
class StoryConfig:
    """Small deterministic policy surface for narrative construction."""

    style: str = "cinematic-travel"
    min_story_items: int = 4
    max_story_items: int = 20
    highlight_target: int = 3
    max_alternates: int = 2
    chronology_min_ratio: float = 0.70

    def __post_init__(self) -> None:
        if self.style != "cinematic-travel":
            raise ValueError(f"Unsupported Story style: {self.style}")
        if not 1 <= self.min_story_items <= self.max_story_items:
            raise ValueError("Story item targets must satisfy 1 <= min <= max")
        if not 1 <= self.highlight_target <= self.max_story_items:
            raise ValueError("Story highlight target must be within the story item limit")
        if not 0 <= self.max_alternates <= self.max_story_items:
            raise ValueError("Story max_alternates must be within the story item limit")
        if not 0 <= self.chronology_min_ratio <= 1:
            raise ValueError("Story chronology_min_ratio must be within 0..1")


@dataclass(frozen=True)
class PlannerConfig:
    """Deterministic editorial timing and renderer-intent policy."""

    target_duration_seconds: float = 40.0
    aspect_ratio: str = "9:16"
    duration_tolerance_seconds: float = 0.01
    min_shots: int = 15
    max_shots: int = 18
    photo_min_duration: float = 1.0
    photo_default_duration: float = 1.8
    photo_max_duration: float = 2.5
    video_min_duration: float = 1.5
    video_default_duration: float = 3.0
    video_max_duration: float = 4.0
    hook_bias_seconds: float = 0.5
    highlight_bias_seconds: float = 0.5
    closing_bias_seconds: float = 0.4
    default_transition: str = "cut"
    default_framing: str = "center"

    def __post_init__(self) -> None:
        if self.target_duration_seconds <= 0 or self.duration_tolerance_seconds < 0:
            raise ValueError("Planner target must be positive and tolerance cannot be negative")
        if self.aspect_ratio != "9:16":
            raise ValueError("Sprint 6 Planner supports only the 9:16 aspect ratio")
        if not 1 <= self.min_shots <= self.max_shots:
            raise ValueError("Planner shot limits must satisfy 1 <= min_shots <= max_shots")
        for kind in ("photo", "video"):
            low = getattr(self, f"{kind}_min_duration")
            default = getattr(self, f"{kind}_default_duration")
            high = getattr(self, f"{kind}_max_duration")
            if not 0 < low <= default <= high:
                raise ValueError(f"Planner {kind} durations must satisfy 0 < min <= default <= max")
        if any(value < 0 for value in (self.hook_bias_seconds, self.highlight_bias_seconds, self.closing_bias_seconds)):
            raise ValueError("Planner duration biases cannot be negative")
        if self.max_shots * max(self.photo_max_duration, self.video_max_duration) < self.target_duration_seconds:
            raise ValueError("Planner shot maxima cannot reach target duration")
        if self.min_shots * min(self.photo_min_duration, self.video_min_duration) > self.target_duration_seconds:
            raise ValueError("Planner shot minima exceed target duration")
        if self.default_transition not in {"cut", "crossfade", "fade", "dip_to_black", "match_motion"}:
            raise ValueError("Unsupported Planner transition intent")
        if self.default_framing not in {"center", "fit", "subject_centered", "top_safe", "bottom_safe", "face_safe", "blur_fill"}:
            raise ValueError("Unsupported Planner framing intent")


@dataclass(frozen=True)
class RendererConfig:
    """Local FFmpeg execution and delivery settings for planned Reels."""

    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "libx264"
    pixel_format: str = "yuv420p"
    preset: str = "medium"
    crf: int = 20
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    output_filename: str = "reel.mp4"
    temp_directory_name: str = ".travel_reel_render"
    keep_temp: bool = False
    photo_motion: str = "none"
    background_mode: str = "black"
    ffmpeg_loglevel: str = "error"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0 or self.fps <= 0:
            raise ValueError("Renderer dimensions and FPS must be positive")
        if self.width * 16 != self.height * 9:
            raise ValueError("Renderer dimensions must match the Planner 9:16 aspect ratio")
        if self.video_codec != "libx264" or self.pixel_format != "yuv420p":
            raise ValueError("Sprint 7 Renderer supports libx264 with yuv420p")
        if not 0 <= self.crf <= 51:
            raise ValueError("Renderer CRF must be within 0..51")
        if self.output_filename != Path(self.output_filename).name or Path(self.output_filename).suffix.lower() != ".mp4":
            raise ValueError("Renderer output_filename must be a safe MP4 filename")
        temp = Path(self.temp_directory_name)
        if temp.is_absolute() or temp.name != self.temp_directory_name or self.temp_directory_name in {"", ".", ".."}:
            raise ValueError("Renderer temp_directory_name must be one safe directory name")
        if self.photo_motion != "none":
            raise ValueError("Sprint 7 Renderer supports only photo_motion: none")
        if self.background_mode != "black":
            raise ValueError("Sprint 7 Renderer supports only background_mode: black")
        if not isinstance(self.keep_temp, bool):
            raise ValueError("Renderer keep_temp must be boolean")
        if self.ffmpeg_loglevel not in {"quiet", "panic", "fatal", "error", "warning", "info"}:
            raise ValueError("Unsupported FFmpeg log level")


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


def load_story_config(path: Path | None = None) -> StoryConfig:
    """Load the dependency-free ``story:`` section."""
    values = _yaml_section_values(_config_text(path), "story")
    integer_keys = {"min_story_items", "max_story_items", "highlight_target", "max_alternates"}
    known = StoryConfig.__dataclass_fields__
    updates = {
        key: int(value) if key in integer_keys else float(value) if key == "chronology_min_ratio" else value
        for key, value in values.items()
        if key in known
    }
    return StoryConfig(**updates)


def load_planner_config(path: Path | None = None) -> PlannerConfig:
    """Load the dependency-free ``planner:`` section."""
    values = _yaml_section_values(_config_text(path), "planner")
    integer_keys = {"min_shots", "max_shots"}
    string_keys = {"aspect_ratio", "default_transition", "default_framing"}
    updates = {
        key: int(value) if key in integer_keys else value if key in string_keys else float(value)
        for key, value in values.items() if key in PlannerConfig.__dataclass_fields__
    }
    return PlannerConfig(**updates)


def load_renderer_config(path: Path | None = None) -> RendererConfig:
    """Load the dependency-free ``renderer:`` section."""
    values = _yaml_section_values(_config_text(path), "renderer")
    integer_keys = {"width", "height", "fps", "crf"}
    boolean_keys = {"keep_temp"}
    updates = {}
    for key, value in values.items():
        if key not in RendererConfig.__dataclass_fields__:
            continue
        if key in integer_keys:
            updates[key] = int(value)
        elif key in boolean_keys:
            if value.lower() not in {"true", "false"}:
                raise ValueError(f"Renderer {key} must be true or false")
            updates[key] = value.lower() == "true"
        else:
            updates[key] = value
    return RendererConfig(**updates)


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
