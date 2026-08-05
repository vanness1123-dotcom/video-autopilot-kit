"""Data models for trip-media analysis results."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

MediaKind = Literal["photo", "video"]

@dataclass(frozen=True)
class GpsLocation:
    """A geographic coordinate extracted from media metadata."""
    latitude: float
    longitude: float

@dataclass(frozen=True)
class MediaFile:
    """One supported media file found in a trip folder."""
    path: str
    kind: MediaKind
    size_bytes: int
    captured_at: datetime | None = None
    gps: GpsLocation | None = None
    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["captured_at"] = self.captured_at.isoformat() if self.captured_at else None
        return data

@dataclass(frozen=True)
class FolderSummary:
    """Direct media counts and size for one directory."""
    path: str
    photos: int
    videos: int
    size_bytes: int

@dataclass(frozen=True)
class AnalysisSummary:
    """Aggregate counts and metadata availability for a trip."""
    total_photos: int
    total_videos: int
    total_size_bytes: int
    gps_available: bool
    date_range_start: str | None
    date_range_end: str | None

@dataclass(frozen=True)
class TripAnalysis:
    """The complete serializable result of scanning one trip folder."""
    trip_folder: str
    generated_at: datetime
    summary: AnalysisSummary
    folders: list[FolderSummary]
    media: list[MediaFile]
    def to_dict(self) -> dict[str, object]:
        return {"trip_folder": self.trip_folder, "generated_at": self.generated_at.isoformat(), "summary": asdict(self.summary), "folder_structure": [asdict(folder) for folder in self.folders], "media": [item.to_dict() for item in self.media]}
