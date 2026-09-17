"""Deterministic, source-safe preprocessing for local Vision analysis."""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tempfile
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


def canonical_dimensions(width: object, height: object) -> dict[str, int | str]:
    """Validate original display pixels; orientation uses strict axis comparison."""
    if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in (width, height)):
        raise VisionPreprocessError("Source dimensions must be positive integer pixels")
    return {"width": width, "height": height,
            "orientation": "square" if width == height else "portrait" if height > width else "landscape"}


def extract_media_dimensions(source: Path, media_type: str) -> dict[str, int | str]:
    """Read display-oriented original pixels without touching source or Vision cache."""
    try:
        if media_type == "video":
            probe = probe_video(source)
            if probe.rotation % 90:
                raise VisionPreprocessError("Unsupported non-quarter-turn video rotation")
            width, height = probe.width, probe.height
            if probe.rotation % 180:
                width, height = height, width
            return canonical_dimensions(width, height)
        if media_type != "photo":
            raise VisionPreprocessError(f"Unsupported media type: {media_type}")
        from PIL import Image
        heif = source.suffix.lower() in {".heic", ".heif"}
        if heif:
            try:
                from pillow_heif import register_heif_opener
            except ImportError:
                pass
            else:
                register_heif_opener()

        def read(path: Path) -> dict[str, int | str]:
            with Image.open(path) as image:
                width, height = image.size
                if image.getexif().get(274) in {5, 6, 7, 8}:
                    width, height = height, width
                return canonical_dimensions(width, height)

        try:
            return read(source)
        except (OSError, SyntaxError, ValueError):
            if not heif:
                raise
        # Same full-resolution, auto-oriented decoder fallback as photo preprocessing.
        with tempfile.TemporaryDirectory(prefix="travel_reel_dimensions_") as directory:
            decoded = Path(directory) / "decoded.png"
            result = subprocess.run(
                ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
                 "-frames:v", "1", str(decoded)], capture_output=True, text=True, check=False)
            if result.returncode != 0 or not decoded.is_file():
                raise VisionPreprocessError(f"HEIC/HEIF dimension decode failed: {result.stderr.strip()[-300:]}")
            return read(decoded)
    except (ImportError, OSError, SyntaxError, ValueError, TypeError, OverflowError) as exc:
        raise VisionPreprocessError(f"Cannot read source dimensions: {source}: {exc}") from exc


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
    if source.suffix.lower() == ".heic":
        try:
            from pillow_heif import register_heif_opener
        except ImportError:
            pass
        else:
            register_heif_opener()
    output.parent.mkdir(parents=True, exist_ok=True)
    def prepare(open_path: Path) -> None:
        with Image.open(open_path) as image:
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

    primary_error: Exception | None = None
    try:
        prepare(source)
    except (OSError, SyntaxError, ValueError) as exc:
        primary_error = exc
    if primary_error is not None:
        if source.suffix.lower() != ".heic":
            raise VisionPreprocessError(f"Cannot preprocess photo: {source}") from primary_error
        with tempfile.TemporaryDirectory(prefix="travel_reel_heic_") as directory:
            decoded = Path(directory) / "decoded.png"
            command = [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(source), "-frames:v", "1", str(decoded),
            ]
            try:
                result = subprocess.run(command, capture_output=True, text=True, check=False)
            except OSError as exc:
                raise VisionPreprocessError(
                    f"Cannot decode HEIC with Pillow; FFmpeg is unavailable: {source}"
                ) from exc
            if result.returncode != 0 or not decoded.is_file():
                detail = result.stderr.strip()[-300:] or "no output image was produced"
                raise VisionPreprocessError(
                    f"Cannot decode HEIC with Pillow or FFmpeg: {source} (FFmpeg: {detail})"
                )
            try:
                prepare(decoded)
            except (OSError, SyntaxError, ValueError) as exc:
                raise VisionPreprocessError(
                    f"FFmpeg decoded HEIC but image normalization failed: {source}"
                ) from exc
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
