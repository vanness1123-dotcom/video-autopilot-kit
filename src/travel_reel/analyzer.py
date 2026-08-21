"""Recursive trip-media scanning that produces canonical Trip objects."""
from __future__ import annotations
import struct
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from uuid import NAMESPACE_URL, uuid5
from .models import FolderSummary, GpsLocation, Photo, Trip, Video

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi"}
DERIVED_DIRECTORY_NAMES = frozenset({".travel_reel_cache", "output"})
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"meta"}

def detect_media_kind(path: Path) -> str | None:
    """Classify a path as supported photo, video, or unsupported."""
    suffix = path.suffix.lower()
    return "photo" if suffix in IMAGE_EXTENSIONS else "video" if suffix in VIDEO_EXTENSIONS else None

def is_source_media_path(path: Path, source_folder: Path) -> bool:
    """Return whether a discovered path is outside generated project directories."""
    return not DERIVED_DIRECTORY_NAMES.intersection(path.relative_to(source_folder).parts[:-1])

def analyze_trip_folder(trip_folder: Path) -> Trip:
    """Scan a trip folder once and build its canonical domain object."""
    if not trip_folder.is_dir():
        raise NotADirectoryError(f"Trip folder does not exist or is not a directory: {trip_folder}")
    source_folder = trip_folder.resolve()
    photos: list[Photo] = []; videos: list[Video] = []
    folders: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for path in sorted(source_folder.rglob("*")):
        if not path.is_file() or not is_source_media_path(path, source_folder) or not (kind := detect_media_kind(path)): continue
        capture_time, gps = extract_metadata(path, kind)
        relative_path = path.relative_to(source_folder)
        parent = relative_path.parent.as_posix() or "."
        size = path.stat().st_size; folders[parent][0 if kind == "photo" else 1] += 1; folders[parent][2] += size
        asset_id = f"{kind}-{uuid5(NAMESPACE_URL, f'{source_folder}/{relative_path.as_posix()}')}"
        if kind == "photo": photos.append(Photo(asset_id, relative_path, path.name, capture_time=capture_time, gps=gps, size_bytes=size))
        else: videos.append(Video(asset_id, relative_path, path.name, capture_time=capture_time, gps=gps, size_bytes=size))
    folder_structure = [FolderSummary(path, counts[0], counts[1], counts[2]) for path, counts in sorted(folders.items())]
    trip_id = f"trip-{uuid5(NAMESPACE_URL, str(source_folder))}"
    return Trip(trip_id, source_folder.name, source_folder, photos, videos, metadata={"generated_at": datetime.now(UTC), "folder_structure": folder_structure})

def extract_metadata(path: Path, kind: str) -> tuple[datetime | None, GpsLocation | None]:
    """Extract supported metadata without failing when it is absent."""
    return extract_image_metadata(path) if kind == "photo" else (extract_video_creation_time(path), None)

def extract_image_metadata(path: Path) -> tuple[datetime | None, GpsLocation | None]:
    """Read EXIF DateTimeOriginal and GPS data when Pillow supports the image."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            exif = image.getexif(); return _parse_exif_datetime(exif.get(36867)), _parse_gps(exif.get(34853))
    except (ImportError, OSError, SyntaxError, ValueError, TypeError): return None, None

def extract_video_creation_time(path: Path) -> datetime | None:
    """Read QuickTime or ISO-BMFF movie-header creation time when present."""
    if path.suffix.lower() == ".avi": return None
    try:
        with path.open("rb") as stream: return _find_movie_creation_time(stream, path.stat().st_size)
    except (OSError, ValueError, struct.error): return None

def _find_movie_creation_time(stream: BinaryIO, limit: int, start: int = 0) -> datetime | None:
    position = start
    while position + 8 <= limit:
        stream.seek(position); header = stream.read(8)
        if len(header) != 8: return None
        size, box_type = struct.unpack(">I4s", header); header_size = 8
        if size == 1:
            extended = stream.read(8)
            if len(extended) != 8: return None
            size, header_size = struct.unpack(">Q", extended)[0], 16
        elif size == 0: size = limit - position
        if size < header_size or position + size > limit: return None
        payload_start = position + header_size
        if box_type == b"mvhd":
            stream.seek(payload_start); payload = stream.read(min(size - header_size, 32))
            if len(payload) < 8: return None
            width = 8 if payload[0] == 1 else 4
            if len(payload) < 4 + width: return None
            return datetime(1904, 1, 1, tzinfo=UTC) + timedelta(seconds=int.from_bytes(payload[4:4 + width], "big"))
        if box_type in _CONTAINERS:
            found = _find_movie_creation_time(stream, position + size, payload_start)
            if found: return found
        position += size
    return None

def _parse_exif_datetime(value: object) -> datetime | None:
    try: return datetime.strptime(value, "%Y:%m:%d %H:%M:%S") if isinstance(value, str) else None
    except ValueError: return None

def _parse_gps(gps: object) -> GpsLocation | None:
    if not isinstance(gps, dict): return None
    try:
        latitude, longitude = _degrees(gps[2]), _degrees(gps[4])
        return GpsLocation(-latitude if gps.get(1) in ("S", b"S") else latitude, -longitude if gps.get(3) in ("W", b"W") else longitude)
    except (KeyError, TypeError, ValueError, ZeroDivisionError): return None

def _degrees(values: object) -> float:
    degrees, minutes, seconds = values  # type: ignore[misc]
    return _rational(degrees) + _rational(minutes) / 60 + _rational(seconds) / 3600

def _rational(value: object) -> float:
    return value[0] / value[1] if isinstance(value, tuple) else float(value)  # type: ignore[index]
