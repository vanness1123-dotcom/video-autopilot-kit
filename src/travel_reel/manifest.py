"""Canonical Trip Manifest construction from analyzer output."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Literal
from uuid import NAMESPACE_URL, uuid5
from .models import MediaFile, TripAnalysis

@dataclass(frozen=True)
class ManifestMedia:
    """A media asset plus reserved fields for future AI enrichment."""
    id: str
    path: str
    size_bytes: int
    captured_at: str | None
    gps: dict[str, float] | None
    score: None = None
    selected: bool = False
    scene_id: None = None
    tags: tuple[str, ...] = ()
    description: None = None
    objects: tuple[str, ...] = ()
    emotion: None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-ready representation with list-valued placeholders."""
        item = asdict(self)
        item["tags"] = list(self.tags)
        item["objects"] = list(self.objects)
        return item

@dataclass(frozen=True)
class TripManifest:
    """The canonical project representation for downstream travel-reel modules."""
    manifest_version: str
    trip: dict[str, object]
    photos: list[ManifestMedia]
    videos: list[ManifestMedia]
    scenes: list[object]
    story: dict[str, object]
    timeline: dict[str, object]
    render: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """Return the stable manifest JSON schema."""
        return {
            "manifest_version": self.manifest_version,
            "trip": self.trip,
            "photos": [photo.to_dict() for photo in self.photos],
            "videos": [video.to_dict() for video in self.videos],
            "scenes": self.scenes,
            "story": self.story,
            "timeline": self.timeline,
            "render": self.render,
        }

def build_trip_manifest(analysis: TripAnalysis) -> TripManifest:
    """Derive the SSOT manifest from one completed analysis without rescanning files."""
    photos = [_manifest_media(analysis, item) for item in analysis.media if item.kind == "photo"]
    videos = [_manifest_media(analysis, item) for item in analysis.media if item.kind == "video"]
    trip = {
        "name": analysis.trip_folder.rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
        "source_folder": analysis.trip_folder,
        "generated_at": analysis.generated_at.isoformat(),
        "summary": asdict(analysis.summary),
        "folder_structure": [asdict(folder) for folder in analysis.folders],
    }
    return TripManifest("1.0", trip, photos, videos, [], {}, {}, {})

def _manifest_media(analysis: TripAnalysis, item: MediaFile) -> ManifestMedia:
    """Convert analyzer media to a deterministically identified manifest asset."""
    asset_id = f"{item.kind}-{uuid5(NAMESPACE_URL, f'{analysis.trip_folder}/{item.path}')}"
    gps = asdict(item.gps) if item.gps else None
    captured_at = item.captured_at.isoformat() if item.captured_at else None
    return ManifestMedia(asset_id, item.path, item.size_bytes, captured_at, gps)
