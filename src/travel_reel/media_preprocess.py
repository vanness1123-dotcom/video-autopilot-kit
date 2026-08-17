"""Deterministic, source-safe preprocessing for local Vision analysis."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class VisionPreprocessError(RuntimeError):
    """Raised when source media cannot be prepared for Vision."""


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    width: int | None
    height: int | None
    rotation: int


def source_fingerprint(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Return a collision-resistant content fingerprint for one source file."""
    if not path.is_file():
        raise VisionPreprocessError(f"Media file does not exist: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(chunk_size):
                digest.update(chunk)
    except OSError as exc:
        raise VisionPreprocessError(f"Cannot read media file: {path}") from exc
    return digest.hexdigest()


def preprocess_photo(
    source: Path,
    output: Path,
    longest_edge: int = 768,
    jpeg_quality: int = 88,
) -> Path:
    """Apply EXIF orientation and create a deterministic RGB JPEG thumbnail."""
    if source.suffix.lower() not in {".jpg", ".jpeg", ".png", ".heic"}:
        raise VisionPreprocessError(f"Unsupported photo format: {source.suffix}")
    try:
        from PIL import Image, ImageCms, ImageOps
    except ImportError as exc:
        raise VisionPreprocessError("Pillow is required for photo preprocessing") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            icc_profile = image.info.get("icc_profile")
            if icc_profile:
                try:
                    image = ImageCms.profileToProfile(
                        image,
                        ImageCms.ImageCmsProfile(io.BytesIO(icc_profile)),
                        ImageCms.createProfile("sRGB"),
                        outputMode="RGB",
                    )
                except (OSError, TypeError, ValueError):
                    image = image.convert("RGB")
            else:
                image = image.convert("RGB")
            image.thumbnail((longest_edge, longest_edge), Image.Resampling.LANCZOS)
            image.save(
                output,
                format="JPEG",
                quality=jpeg_quality,
                optimize=False,
                progressive=False,
                subsampling=2,
                exif=b"",
            )
    except (OSError, SyntaxError, ValueError) as exc:
        raise VisionPreprocessError(f"Cannot preprocess photo: {source}") from exc
    return output


def probe_video(path: Path) -> VideoProbe:
    """Read video duration, dimensions, and rotation with FFprobe."""
    command = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:stream_tags=rotate:stream_side_data=rotation:format=duration",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise VisionPreprocessError("FFprobe is unavailable") from exc
    if result.returncode != 0:
        raise VisionPreprocessError(f"FFprobe failed for {path}: {result.stderr[-300:]}")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
        rotation = int(stream.get("tags", {}).get("rotate", 0))
        for side_data in stream.get("side_data_list", []):
            if "rotation" in side_data:
                rotation = int(side_data["rotation"])
        if duration <= 0:
            raise ValueError("non-positive duration")
        return VideoProbe(duration, stream.get("width"), stream.get("height"), rotation)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise VisionPreprocessError(f"Invalid FFprobe output for {path}") from exc


def representative_timestamps(duration: float) -> list[float]:
    """Return bounded deterministic representative timestamps for a video."""
    if duration <= 0:
        raise VisionPreprocessError("Video duration must be positive")
    if duration < 4:
        ratios = (0.25, 0.75)
    elif duration <= 15:
        ratios = (0.10, 0.50, 0.90)
    elif duration <= 60:
        ratios = (0.10, 0.35, 0.65, 0.90)
    else:
        ratios = (0.05, 0.275, 0.50, 0.725, 0.95)
    return [round(duration * ratio, 3) for ratio in ratios[:5]]


def extract_video_frames(
    source: Path,
    output_dir: Path,
    timestamps: list[float],
    longest_edge: int = 768,
) -> list[Path]:
    """Extract auto-rotated, aspect-preserving JPEG frames without overlays."""
    output_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Path] = []
    scale = (
        f"scale='if(gt(iw,ih),{longest_edge},-2)':"
        f"'if(gt(iw,ih),-2,{longest_edge})':flags=lanczos,format=yuvj420p"
    )
    for index, timestamp in enumerate(timestamps):
        output = output_dir / f"frame_{index:02d}_{timestamp:.3f}.jpg"
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(timestamp), "-i", str(source), "-vf", scale,
            "-frames:v", "1", "-q:v", "3", str(output),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except OSError as exc:
            raise VisionPreprocessError("FFmpeg is unavailable") from exc
        if result.returncode != 0 or not output.is_file():
            raise VisionPreprocessError(
                f"FFmpeg frame extraction failed at {timestamp:.3f}s: {result.stderr[-300:]}"
            )
        frames.append(output)
    return frames
