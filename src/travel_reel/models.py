"""Canonical Python domain models for the AI Travel Reel Generator."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

@dataclass
class GpsLocation:
    """A geographic coordinate attached to captured media."""
    latitude: float
    longitude: float

@dataclass
class Photo:
    """A photo asset in a trip, with reserved future-enrichment fields."""
    id: str
    path: Path
    filename: str
    width: int | None = None
    height: int | None = None
    orientation: str | None = None
    camera: str | None = None
    capture_time: datetime | None = None
    gps: GpsLocation | None = None
    size_bytes: int = 0
    score: float | None = None
    selected: bool = False
    scene_id: str | None = None
    tags: list[str] = field(default_factory=list)
    description: str | None = None
    objects: list[str] = field(default_factory=list)
    emotion: str | None = None

@dataclass
class Video:
    """A video asset in a trip, with reserved future-enrichment fields."""
    id: str
    path: Path
    filename: str
    duration: float | None = None
    fps: float | None = None
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    orientation: str | None = None
    capture_time: datetime | None = None
    gps: GpsLocation | None = None
    size_bytes: int = 0
    score: float | None = None
    selected: bool = False
    scene_id: str | None = None
    tags: list[str] = field(default_factory=list)
    description: str | None = None
    objects: list[str] = field(default_factory=list)
    emotion: str | None = None

@dataclass
class Scene:
    """A future grouping of related trip media."""
    id: str
    name: str
    media_ids: list[str] = field(default_factory=list)
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    summary: str | None = None

@dataclass
class Timeline:
    """A future ordered sequence of scenes for a reel."""
    ordered_scene_ids: list[str] = field(default_factory=list)
    estimated_duration: float | None = None

@dataclass
class ReelPlan:
    """Future rendering intent for a travel reel."""
    style: str | None = None
    target_duration: float | None = None
    aspect_ratio: str | None = None
    resolution: str | None = None
    fps: float | None = None
    bgm: str | None = None
    subtitle_style: str | None = None

@dataclass
class FolderSummary:
    """Analyzer-owned direct media counts for one source directory."""
    path: str
    photos: int
    videos: int
    size_bytes: int

@dataclass
class Trip:
    """Canonical in-memory project state shared by all future modules."""
    id: str
    name: str
    source_folder: Path
    photos: list[Photo] = field(default_factory=list)
    videos: list[Video] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=list)
    timeline: Timeline | None = None
    reel_plan: ReelPlan | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
