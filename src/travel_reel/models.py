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
    """Photo with original display-oriented pixels and portrait/landscape/square orientation."""
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
    """Video with original display-oriented pixels and portrait/landscape/square orientation."""
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

@dataclass(frozen=True)
class TripSummary:
    """Derived analyzer summary for CLI and analysis.json compatibility."""
    total_photos: int
    total_videos: int
    total_size_bytes: int
    gps_available: bool
    date_range_start: str | None
    date_range_end: str | None

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

    @property
    def folders(self) -> list[FolderSummary]:
        """Return analyzer folder summaries stored with the canonical trip."""
        return self.metadata.get("folder_structure", [])

    @property
    def generated_at(self) -> datetime:
        """Return the timestamp captured by the analyzer."""
        return self.metadata["generated_at"]

    @property
    def summary(self) -> TripSummary:
        """Derive the stable Sprint 1 summary from canonical media objects."""
        media = [*self.photos, *self.videos]
        capture_dates = sorted(
            item.capture_time.date().isoformat()
            for item in media
            if item.capture_time is not None
        )
        return TripSummary(
            total_photos=len(self.photos),
            total_videos=len(self.videos),
            total_size_bytes=sum(item.size_bytes for item in media),
            gps_available=any(item.gps is not None for item in media),
            date_range_start=capture_dates[0] if capture_dates else None,
            date_range_end=capture_dates[-1] if capture_dates else None,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the canonical trip using the Sprint 1 analysis.json schema."""
        def media_item(item: Photo | Video, kind: str) -> dict[str, Any]:
            return {
                "path": item.path.as_posix(),
                "kind": kind,
                "width": item.width,
                "height": item.height,
                "orientation": item.orientation,
                "size_bytes": item.size_bytes,
                "captured_at": item.capture_time.isoformat() if item.capture_time else None,
                "gps": {
                    "latitude": item.gps.latitude,
                    "longitude": item.gps.longitude,
                } if item.gps else None,
            }

        return {
            "trip_folder": str(self.source_folder),
            "generated_at": self.generated_at.isoformat(),
            "summary": {
                "total_photos": self.summary.total_photos,
                "total_videos": self.summary.total_videos,
                "total_size_bytes": self.summary.total_size_bytes,
                "gps_available": self.summary.gps_available,
                "date_range_start": self.summary.date_range_start,
                "date_range_end": self.summary.date_range_end,
            },
            "folder_structure": [
                {
                    "path": folder.path,
                    "photos": folder.photos,
                    "videos": folder.videos,
                    "size_bytes": folder.size_bytes,
                }
                for folder in self.folders
            ],
            "media": [
                *(media_item(item, "photo") for item in self.photos),
                *(media_item(item, "video") for item in self.videos),
            ],
        }
