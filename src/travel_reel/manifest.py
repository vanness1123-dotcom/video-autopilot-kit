"""Canonical Trip Manifest construction from analyzer output."""
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from .models import Photo, Trip, Video

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
    width: int | None = None
    height: int | None = None
    orientation: str | None = None

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
    events: dict[str, object]
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
            "events": self.events,
            "scenes": self.scenes,
            "story": self.story,
            "timeline": self.timeline,
            "render": self.render,
        }

def build_trip_manifest(trip_state: Trip) -> TripManifest:
    """Derive the SSOT manifest from one completed analysis without rescanning files."""
    photos = [_manifest_media(item) for item in trip_state.photos]
    videos = [_manifest_media(item) for item in trip_state.videos]
    trip = {
        "name": trip_state.name,
        "source_folder": str(trip_state.source_folder),
        "generated_at": trip_state.generated_at.isoformat(),
        "summary": asdict(trip_state.summary),
        "folder_structure": [asdict(folder) for folder in trip_state.folders],
    }
    return TripManifest("1.0", trip, photos, videos, {}, [], {}, {}, {})

def _manifest_media(item: Photo | Video) -> ManifestMedia:
    """Convert analyzer media to a deterministically identified manifest asset."""
    gps = asdict(item.gps) if item.gps else None
    captured_at = item.capture_time.isoformat() if item.capture_time else None
    return ManifestMedia(item.id, item.path.as_posix(), item.size_bytes, captured_at, gps,
                         width=item.width, height=item.height, orientation=item.orientation)


def load_trip_manifest(path: Path) -> dict[str, Any]:
    """Load and minimally validate an existing Trip Manifest."""
    if not path.is_file():
        raise FileNotFoundError(f"Trip Manifest not found: {path}. Run 'analyze' first.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read Trip Manifest: {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("trip"), dict):
        raise ValueError("Invalid Trip Manifest: missing trip object")
    if not isinstance(payload.get("photos"), list) or not isinstance(payload.get("videos"), list):
        raise ValueError("Invalid Trip Manifest: photos/videos must be arrays")
    visual = payload.get('visual_plan')
    if isinstance(visual,dict) and any(isinstance(b.get('resolved_overlay'),dict) and
            ('version' in b['resolved_overlay'] or 'placement_resolution' in b['resolved_overlay'])
            for b in visual.get('blocks',[])):
        from .overlay import validate_overlay_plan
        validate_overlay_plan(visual,visual,payload)
    return payload


def find_manifest_media(manifest: dict[str, Any], media_id: str) -> dict[str, Any]:
    """Find one manifest media object without changing collection identity."""
    for collection in ("photos", "videos"):
        for item in manifest[collection]:
            if isinstance(item, dict) and item.get("id") == media_id:
                return item
    raise KeyError(f"Manifest media ID not found: {media_id}")


def enrich_manifest_media(
    manifest: dict[str, Any], media_id: str, vision: dict[str, Any]
) -> None:
    """Add Vision state while preserving Sprint 2 fields and all unrelated state."""
    item = find_manifest_media(manifest, media_id)
    item["vision"] = vision
    item["description"] = vision["description"]
    item["tags"] = list(vision["tags"])
    item["objects"] = list(vision["objects"])
    item["emotion"] = vision["mood"]
    item.pop("vision_error", None)
    if manifest.get("manifest_version") == "1.0":
        manifest["manifest_version"] = "1.1"


def save_trip_manifest_atomic(path: Path, manifest: dict[str, Any]) -> None:
    """Validate serialization and atomically replace the manifest sibling."""
    if not isinstance(manifest.get("photos"), list) or not isinstance(manifest.get("videos"), list):
        raise ValueError("Refusing to save invalid Trip Manifest")
    serialized = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    json.loads(serialized)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def advance_manifest_version(manifest: dict[str, Any], version: str) -> None:
    """Advance the additive schema version without downgrading newer manifests."""
    try:
        current = tuple(int(part) for part in str(manifest.get("manifest_version", "0")).split("."))
        requested = tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise ValueError("Invalid Trip Manifest version") from exc
    if current < requested:
        manifest["manifest_version"] = version
