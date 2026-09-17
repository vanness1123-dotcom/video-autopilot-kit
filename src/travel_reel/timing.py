"""Shared deterministic editorial timing and feasibility policy."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimingProfile:
    photo_seconds: float
    video_seconds: float
    minimum_photo_seconds: float = 1.0
    minimum_video_seconds: float = 1.5
    maximum_photo_seconds: float = 2.5
    maximum_video_seconds: float = 4.0


STYLE_TIMING = {
    "cinematic_travel": TimingProfile(2.30, 3.40),
    "travel_story": TimingProfile(1.95, 3.10),
    "dynamic_travel_highlight": TimingProfile(1.50, 2.55),
    "beat_montage": TimingProfile(1.20, 2.10),
}


def expected_mix(shot_count: int, videos_available: int, style: str) -> tuple[int, int]:
    """Return a feasible style-aware photo/video editorial mix."""
    ratio = {"cinematic_travel": .22, "travel_story": .25,
             "dynamic_travel_highlight": .30, "beat_montage": .20}[style]
    videos = min(videos_available, shot_count, round(shot_count * ratio))
    return shot_count - videos, videos


def duration_bounds(photo_count: int, video_count: int, style: str) -> tuple[float, float, float]:
    """Return minimum, editorially preferred, and maximum safe durations."""
    timing = STYLE_TIMING[style]
    low = photo_count * timing.minimum_photo_seconds + video_count * timing.minimum_video_seconds
    preferred = photo_count * timing.photo_seconds + video_count * timing.video_seconds
    high = photo_count * timing.maximum_photo_seconds + video_count * timing.maximum_video_seconds
    if photo_count + video_count:
        preferred += 1.4  # hook/highlight/closing breathing allowance
    return tuple(round(value, 3) for value in (low, preferred, high))


def clamp_feasible_duration(
    preferred: float, safe_low: float, safe_high: float, envelope_low: float, envelope_high: float,
) -> float:
    """Quantize to half seconds inside both product and shot-safety envelopes."""
    low, high = max(safe_low, envelope_low), min(safe_high, envelope_high)
    if low > high:
        raise ValueError(
            f"No duration satisfies product envelope {envelope_low:.3f}..{envelope_high:.3f}s "
            f"and safe shot bounds {safe_low:.3f}..{safe_high:.3f}s"
        )
    value = max(low, min(preferred, high))
    quantized = round(value * 2) / 2
    return round(max(low, min(quantized, high)), 3)
