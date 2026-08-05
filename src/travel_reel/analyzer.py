"""Recursive trip-media scanning and metadata extraction."""
from __future__ import annotations
import struct
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import BinaryIO
from .models import AnalysisSummary, FolderSummary, GpsLocation, MediaFile, TripAnalysis

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi"}
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"udta", b"meta"}

def detect_media_kind(path: Path) -> str | None:
    """Classify a path as supported photo, video, or unsupported."""
    suffix = path.suffix.lower()
    return "photo" if suffix in IMAGE_EXTENSIONS else "video" if suffix in VIDEO_EXTENSIONS else None

def analyze_trip_folder(trip_folder: Path) -> TripAnalysis:
    """Scan a trip folder and collect supported media and metadata."""
    if not trip_folder.is_dir():
        raise NotADirectoryError(f"Trip folder does not exist or is not a directory: {trip_folder}")
    media: list[MediaFile] = []
    folders: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for path in sorted(trip_folder.rglob("*")):
        if not path.is_file() or not (kind := detect_media_kind(path)):
            continue
        captured_at, gps = extract_metadata(path, kind)
        parent = path.parent.relative_to(trip_folder).as_posix() or "."
        size = path.stat().st_size
        folders[parent][0 if kind == "photo" else 1] += 1
        folders[parent][2] += size
        media.append(MediaFile(path.relative_to(trip_folder).as_posix(), kind, size, captured_at, gps))
    media.sort(key=lambda item: item.path)
    dates = [item.captured_at.date().isoformat() for item in media if item.captured_at]
    summary = AnalysisSummary(sum(item.kind == "photo" for item in media), sum(item.kind == "video" for item in media), sum(item.size_bytes for item in media), any(item.gps for item in media), min(dates) if dates else None, max(dates) if dates else None)
    folder_summaries = [FolderSummary(path, counts[0], counts[1], counts[2]) for path, counts in sorted(folders.items())]
    return TripAnalysis(str(trip_folder.resolve()), datetime.now(UTC), summary, folder_summaries, media)

def extract_metadata(path: Path, kind: str) -> tuple[datetime | None, GpsLocation | None]:
    """Extract supported metadata without failing when it is absent."""
    return extract_image_metadata(path) if kind == "photo" else (extract_video_creation_time(path), None)

def extract_image_metadata(path: Path) -> tuple[datetime | None, GpsLocation | None]:
    """Read EXIF DateTimeOriginal and GPS data when Pillow supports the image."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            exif = image.getexif()
            return _parse_exif_datetime(exif.get(36867)), _parse_gps(exif.get(34853))
    except (ImportError, OSError, SyntaxError, ValueError, TypeError):
        return None, None

def extract_video_creation_time(path: Path) -> datetime | None:
    """Read QuickTime or ISO-BMFF movie-header creation time when present."""
    if path.suffix.lower() == ".avi":
        return None
    try:
        with path.open("rb") as stream:
            return _find_movie_creation_time(stream, path.stat().st_size)
    except (OSError, ValueError, struct.error):
        return None

def _find_movie_creation_time(stream: BinaryIO, limit: int, start: int = 0) -> datetime | None:
    position = start
    while position + 8 <= limit:
        stream.seek(position)
        header = stream.read(8)
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
