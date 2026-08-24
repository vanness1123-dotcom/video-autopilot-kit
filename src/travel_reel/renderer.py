"""Local FFmpeg adapter that materializes a persisted Reel Plan without editorial changes."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import RendererConfig

RENDERER_VERSION = "1.0"
PHOTO_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".heic"})
VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".m4v"})
SUPPORTED_TRANSITIONS = frozenset({"cut"})
CommandRunner = Callable[[Sequence[object]], subprocess.CompletedProcess[str]]


class RendererError(RuntimeError):
    """Base class for local rendering failures."""


class RendererPrerequisiteError(RendererError):
    pass


class RendererSourceError(RendererError):
    pass


class RendererFFmpegError(RendererError):
    pass


class RendererValidationError(RendererError):
    pass


def render_reel(
    trip_folder: Path,
    manifest: dict[str, Any],
    config: RendererConfig,
    *,
    runner: CommandRunner | None = None,
) -> tuple[dict[str, Any], Path]:
    """Render, validate, and atomically publish one silent MP4 from persisted plan state."""
    root = trip_folder.resolve()
    plan = manifest.get("reel_plan")
    validate_render_plan(plan, config)
    shots = plan["shots"]
    sources = [resolve_shot_source(root, manifest, shot) for shot in shots]
    ffmpeg = _find_tool("ffmpeg")
    ffprobe = _find_tool("ffprobe")
    run = runner or _run_command
    for shot, source in zip(shots, sources):
        if shot["media_type"] == "video":
            source_duration = probe_source_duration(source, ffprobe=ffprobe, runner=run)
            if float(shot["source_trim_end_seconds"]) > source_duration + (1.0 / config.fps):
                raise RendererSourceError(
                    f"Planned trim exceeds source duration for {shot['shot_id']} / {shot['media_id']}"
                )
    output_dir = root / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    final_output = output_dir / config.output_filename
    pending_output = output_dir / f"{Path(config.output_filename).stem}.tmp.mp4"
    temp_root = (root / config.temp_directory_name).resolve()
    _assert_within(root, temp_root, "Temporary render directory escapes trip folder")
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True)
    try:
        segments: list[Path] = []
        for position, (shot, source) in enumerate(zip(shots, sources), 1):
            segment = temp_root / f"segment-{position:03d}.mp4"
            frame_count = _shot_frame_count(shot, config.fps)
            if shot["media_type"] == "photo":
                command = build_photo_command(ffmpeg, source, segment, frame_count, config)
            else:
                command = build_video_command(ffmpeg, source, segment, shot, frame_count, config)
            _execute(run, command, f"shot {shot['shot_id']} / {shot['media_id']}")
            if not segment.is_file() or segment.stat().st_size <= 0:
                raise RendererFFmpegError(f"FFmpeg produced no segment for {shot['shot_id']} / {shot['media_id']}")
            segments.append(segment)
        concat_file = temp_root / "segments.txt"
        concat_file.write_text(
            "".join(f"file '{_concat_escape(segment, ffmpeg)}'\n" for segment in segments), encoding="utf-8"
        )
        concat_command = build_concat_command(ffmpeg, concat_file, pending_output, config)
        _execute(run, concat_command, "final concatenation")
        probe = probe_render_output(pending_output, ffprobe=ffprobe, runner=run)
        validate_render_output(pending_output, probe, plan, config, len(segments))
        os.replace(pending_output, final_output)
        render_state = build_render_state(root, final_output, probe, plan, config)
        return render_state, final_output
    except Exception:
        pending_output.unlink(missing_ok=True)
        raise
    finally:
        if not config.keep_temp and temp_root.exists():
            shutil.rmtree(temp_root)


def validate_render_plan(plan: object, config: RendererConfig) -> None:
    """Validate only execution invariants; never repair or reinterpret editorial intent."""
    if not isinstance(plan, dict) or not isinstance(plan.get("shots"), list) or not plan["shots"]:
        raise RendererPrerequisiteError("Reel plan not found. Run 'plan' first.")
    if plan.get("aspect_ratio") != "9:16":
        raise RendererValidationError("Renderer requires a 9:16 Reel Plan")
    previous_end = 0.0
    seen_ids: set[str] = set()
    for expected_index, shot in enumerate(plan["shots"], 1):
        if not isinstance(shot, dict):
            raise RendererValidationError(f"Shot {expected_index} is not an object")
        if shot.get("shot_index") != expected_index or shot.get("media_id") in seen_ids:
            raise RendererValidationError("Reel Plan shot ordering or media identity is invalid")
        seen_ids.add(shot.get("media_id"))
        if shot.get("media_type") not in {"photo", "video"}:
            raise RendererValidationError(f"Unsupported media type in {shot.get('shot_id')}")
        if shot.get("transition_intent") not in SUPPORTED_TRANSITIONS:
            raise RendererValidationError(
                f"Unsupported transition '{shot.get('transition_intent')}' in {shot.get('shot_id')}"
            )
        start, end, duration = (
            shot.get("timeline_start_seconds"), shot.get("timeline_end_seconds"), shot.get("planned_duration_seconds")
        )
        if not all(isinstance(value, (int, float)) for value in (start, end, duration)):
            raise RendererValidationError(f"Invalid timing in {shot.get('shot_id')}")
        if abs(float(start) - previous_end) > 0.002 or duration <= 0 or abs((end - start) - duration) > 0.002:
            raise RendererValidationError(f"Non-continuous or inconsistent timing in {shot.get('shot_id')}")
        if shot["media_type"] == "video":
            trim_start, trim_end = shot.get("source_trim_start_seconds"), shot.get("source_trim_end_seconds")
            if not isinstance(trim_start, (int, float)) or not isinstance(trim_end, (int, float)):
                raise RendererValidationError(f"Missing video trim in {shot.get('shot_id')}")
            if trim_start < 0 or trim_end <= trim_start or abs((trim_end - trim_start) - duration) > 0.002:
                raise RendererValidationError(f"Invalid video trim in {shot.get('shot_id')}")
        previous_end = float(end)
    actual = plan.get("actual_duration_seconds")
    if not isinstance(actual, (int, float)) or abs(previous_end - actual) > 0.002:
        raise RendererValidationError("Reel Plan duration disagrees with its timeline")
    if round(actual * config.fps) <= 0:
        raise RendererValidationError("Reel Plan contains no renderable frames")


def resolve_shot_source(root: Path, manifest: dict[str, Any], shot: dict[str, Any]) -> Path:
    """Resolve an approved source reference under the trip root and reject substitutions."""
    media_id = shot.get("media_id")
    collection = "photos" if shot.get("media_type") == "photo" else "videos"
    matches = [
        item for item in manifest.get(collection, [])
        if isinstance(item, dict) and item.get("id") == media_id
    ]
    if len(matches) != 1:
        raise RendererSourceError(f"Manifest media not found or duplicated: {media_id}")
    manifest_path = matches[0].get("path")
    source_reference = shot.get("source_path")
    if not isinstance(source_reference, str) or not source_reference or source_reference != manifest_path:
        raise RendererSourceError(f"Planned source does not match manifest media: {media_id}")
    source = (root / Path(source_reference)).resolve()
    _assert_within(root, source, f"Source path escapes trip folder: {source_reference}")
    if not source.is_file():
        raise RendererSourceError(f"Source media is missing: {source_reference}")
    allowed = PHOTO_EXTENSIONS if shot.get("media_type") == "photo" else VIDEO_EXTENSIONS
    if source.suffix.lower() not in allowed:
        raise RendererSourceError(f"Unsupported source media for {media_id}: {source.suffix}")
    if any(part in {"output", ".travel_reel_cache", ".travel_reel_render"} for part in source.relative_to(root).parts[:-1]):
        raise RendererSourceError(f"Derived media cannot be a render source: {source_reference}")
    return source


def normalization_filter(config: RendererConfig) -> str:
    """Return deterministic aspect-preserving fit-and-pad normalization."""
    return (
        f"scale={config.width}:{config.height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
        f"pad={config.width}:{config.height}:(ow-iw)/2:(oh-ih)/2:{config.background_mode},"
        f"fps={config.fps},setsar=1,format={config.pixel_format}"
    )


def build_photo_command(
    ffmpeg: str, source: Path, output: Path, frame_count: int, config: RendererConfig,
) -> list[object]:
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", config.ffmpeg_loglevel,
        "-loop", "1", "-framerate", str(config.fps), "-i", source,
        "-vf", normalization_filter(config), "-an", "-frames:v", str(frame_count),
        "-c:v", config.video_codec, "-preset", config.preset, "-crf", str(config.crf),
        "-pix_fmt", config.pixel_format, "-movflags", "+faststart", output,
    ]


def build_video_command(
    ffmpeg: str, source: Path, output: Path, shot: dict[str, Any], frame_count: int, config: RendererConfig,
) -> list[object]:
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", config.ffmpeg_loglevel,
        "-ss", _seconds(shot["source_trim_start_seconds"]), "-i", source,
        "-vf", normalization_filter(config), "-an", "-frames:v", str(frame_count),
        "-c:v", config.video_codec, "-preset", config.preset, "-crf", str(config.crf),
        "-pix_fmt", config.pixel_format, "-movflags", "+faststart", output,
    ]


def build_concat_command(ffmpeg: str, concat_file: Path, output: Path, config: RendererConfig) -> list[object]:
    return [
        ffmpeg, "-y", "-hide_banner", "-loglevel", config.ffmpeg_loglevel,
        "-f", "concat", "-safe", "0", "-i", concat_file, "-c", "copy", "-an",
        "-movflags", "+faststart", output,
    ]


def probe_render_output(
    output: Path, *, ffprobe: str = "ffprobe", runner: CommandRunner | None = None,
) -> dict[str, Any]:
    run = runner or _run_command
    command: list[object] = [
        ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=codec_name,width,height,pix_fmt,avg_frame_rate:format=duration", "-of", "json", output,
    ]
    result = run(command)
    if result.returncode:
        raise RendererValidationError(f"FFprobe could not read rendered output: {_stderr_tail(result.stderr)}")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        numerator, denominator = stream["avg_frame_rate"].split("/", 1)
        return {
            "duration_seconds": float(payload["format"]["duration"]), "width": int(stream["width"]),
            "height": int(stream["height"]), "fps": float(numerator) / float(denominator),
            "video_codec": str(stream["codec_name"]), "pixel_format": str(stream["pix_fmt"]),
        }
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError, json.JSONDecodeError) as exc:
        raise RendererValidationError("FFprobe returned invalid video metadata") from exc


def probe_source_duration(
    source: Path, *, ffprobe: str = "ffprobe", runner: CommandRunner | None = None,
) -> float:
    """Preflight one planned video range before any expensive segment encoding."""
    run = runner or _run_command
    result = run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "json", source])
    if result.returncode:
        raise RendererSourceError(f"FFprobe could not read source video {source.name}: {_stderr_tail(result.stderr)}")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RendererSourceError(f"Source video duration is unavailable: {source.name}") from exc
    if duration <= 0:
        raise RendererSourceError(f"Source video duration is invalid: {source.name}")
    return duration


def validate_render_output(
    output: Path, probe: dict[str, Any], plan: dict[str, Any], config: RendererConfig, rendered_shots: int,
) -> None:
    if not output.is_file() or output.stat().st_size <= 0:
        raise RendererValidationError("Rendered MP4 is missing or empty")
    if (probe.get("width"), probe.get("height")) != (config.width, config.height):
        raise RendererValidationError("Rendered MP4 resolution is invalid")
    if probe.get("video_codec") != "h264" or probe.get("pixel_format") != config.pixel_format:
        raise RendererValidationError("Rendered MP4 codec or pixel format is invalid")
    if abs(float(probe.get("fps", 0)) - config.fps) > 0.01:
        raise RendererValidationError("Rendered MP4 frame rate is invalid")
    # One output frame plus 10 ms allows normal MP4 time-base/container rounding.
    tolerance = 1.0 / config.fps + 0.01
    if abs(float(probe.get("duration_seconds", -1)) - float(plan["actual_duration_seconds"])) > tolerance:
        raise RendererValidationError(f"Rendered MP4 duration exceeds frame-aware tolerance ({tolerance:.4f}s)")
    if rendered_shots != len(plan["shots"]):
        raise RendererValidationError("Rendered shot count does not match Reel Plan")


def build_render_state(
    root: Path, output: Path, probe: dict[str, Any], plan: dict[str, Any], config: RendererConfig,
) -> dict[str, Any]:
    shots = plan["shots"]
    return {
        "renderer_version": RENDERER_VERSION, "status": "completed",
        "output_path": output.relative_to(root).as_posix(),
        "duration_seconds": round(float(probe["duration_seconds"]), 3),
        "width": probe["width"], "height": probe["height"], "fps": round(float(probe["fps"]), 3),
        "video_codec": probe["video_codec"], "pixel_format": probe["pixel_format"],
        "shot_count": len(shots), "photo_count": sum(s["media_type"] == "photo" for s in shots),
        "video_count": sum(s["media_type"] == "video" for s in shots), "audio": False,
        "render_metadata": {"transition_types": sorted({s["transition_intent"] for s in shots}),
                            "photo_motion": config.photo_motion, "background_mode": config.background_mode},
    }


def _shot_frame_count(shot: dict[str, Any], fps: int) -> int:
    frames = round(float(shot["timeline_end_seconds"]) * fps) - round(float(shot["timeline_start_seconds"]) * fps)
    if frames <= 0:
        raise RendererValidationError(f"Shot is shorter than one output frame: {shot.get('shot_id')}")
    return frames


def _find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    windows = Path("C:/Tools/ffmpeg/bin") / f"{name}.exe"
    if windows.is_file():
        return str(windows)
    # Development under WSL may reuse the host installation without installing a second FFmpeg.
    wsl_host = Path("/mnt/c/Tools/ffmpeg/bin") / f"{name}.exe"
    if wsl_host.is_file():
        return str(wsl_host)
    raise RendererPrerequisiteError(f"{name} is unavailable on PATH")


def _run_command(command: Sequence[object]) -> subprocess.CompletedProcess[str]:
    try:
        executable = str(command[0])
        arguments = [executable, *[_path_for_tool(value, executable) for value in command[1:]]]
        return subprocess.run(
            arguments, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, shell=False,
        )
    except OSError as exc:
        raise RendererFFmpegError(f"Cannot execute {command[0]}: {exc}") from exc


def _execute(run: CommandRunner, command: Sequence[object], context: str) -> None:
    result = run(command)
    if result.returncode:
        raise RendererFFmpegError(f"FFmpeg failed during {context}: {_stderr_tail(result.stderr)}")


def _assert_within(root: Path, candidate: Path, message: str) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise RendererSourceError(message) from exc


def _concat_escape(path: Path, executable: str) -> str:
    return _path_for_tool(path.resolve(), executable).replace("\\", "/").replace("'", "'\\''")


def _path_for_tool(value: object, executable: str) -> str:
    if not isinstance(value, Path):
        return str(value)
    resolved = str(value)
    if os.name != "nt" and executable.lower().endswith(".exe") and resolved.startswith("/mnt/"):
        converted = subprocess.run(
            ["wslpath", "-w", resolved], capture_output=True, text=True, check=False, encoding="utf-8"
        )
        if converted.returncode == 0 and converted.stdout.strip():
            return converted.stdout.strip()
    return resolved


def _seconds(value: float) -> str:
    return f"{float(value):.3f}"


def _stderr_tail(stderr: str | None, limit: int = 600) -> str:
    clean = " ".join((stderr or "no diagnostic output").split())
    return clean[-limit:]
