"""Local deterministic Music & Beat Intelligence using FFmpeg and stdlib DSP."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import subprocess
import sys
import tempfile
import wave
from array import array
from pathlib import Path
from typing import Any

from .config import MusicConfig

MUSIC_SCHEMA_VERSION = "1.0"
MUSIC_ANALYZER_VERSION = "1.0"
SUPPORTED_AUDIO = {".mp3", ".m4a", ".aac", ".wav", ".flac"}


class MusicAnalysisError(ValueError):
    pass


def music_fingerprint(path: Path) -> str:
    if not path.is_file():
        raise MusicAnalysisError(f"Music file not found: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    except OSError as exc:
        raise MusicAnalysisError(f"Cannot read music file: {path}") from exc
    return digest.hexdigest()


def music_cache_key(fingerprint: str, config: MusicConfig) -> str:
    identity = {"fingerprint": fingerprint, "schema": MUSIC_SCHEMA_VERSION,
                "analyzer": MUSIC_ANALYZER_VERSION, "sample_rate": config.sample_rate,
                "window_ms": config.window_ms, "bpm_min": config.bpm_min,
                "bpm_max": config.bpm_max,
                "minimum_tempo_confidence": config.minimum_tempo_confidence}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def analyze_music(path: Path, config: MusicConfig) -> dict[str, Any]:
    source = path.resolve()
    if source.suffix.lower() not in SUPPORTED_AUDIO:
        raise MusicAnalysisError(
            f"Unsupported music format {source.suffix!r}; use MP3, M4A/AAC, WAV, or FLAC"
        )
    fingerprint = music_fingerprint(source)
    key = music_cache_key(fingerprint, config)
    with tempfile.TemporaryDirectory(prefix="travel_reel_music_") as directory:
        normalized = Path(directory) / "normalized.wav"
        _normalize(source, normalized, config.sample_rate)
        rms, sample_rate, duration = _read_wav_envelope(normalized, config.window_ms)
    if duration < .5:
        raise MusicAnalysisError("Music must be at least 0.5 seconds for analysis")
    energy = _energy_curve(rms, config.window_ms / 1000, duration)
    tempo, beats = _tempo_and_beats(rms, config, duration)
    phrases = _phrases(energy, beats, duration)
    structure = _structure(phrases)
    anchors = _sync_anchors(beats, phrases, energy, duration)
    return {
        "version": MUSIC_SCHEMA_VERSION,
        "analyzer": {"name": "stdlib-onset-autocorrelation", "version": MUSIC_ANALYZER_VERSION,
                     "facts": ["decoded_duration", "sample_rate", "channels", "relative_rms"],
                     "heuristics": ["tempo", "beat_grid", "accents", "phrases", "structure"]},
        "source": {"path": str(source), "fingerprint": fingerprint, "cache_key": key,
                   "original_modified": False},
        "duration_seconds": round(duration, 3), "sample_rate": sample_rate, "channels": 1,
        "tempo": tempo, "beats": beats, "phrases": phrases, "energy_curve": energy,
        "structure": structure, "sync_anchors": anchors,
        "validation": {"valid": True, "beats_monotonic": _monotonic([x["time"] for x in beats]),
                       "phrases_non_overlapping": _phrases_valid(phrases, duration),
                       "downbeats_detected": False},
    }


def analyze_music_cached(path: Path, config: MusicConfig, cache_root: Path) -> tuple[dict[str, Any], bool]:
    """Reuse only strictly valid source-fact analysis from the independent music cache."""
    fingerprint = music_fingerprint(path)
    key = music_cache_key(fingerprint, config)
    cache_path = cache_root / f"{key}.json"
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if validate_music_analysis(cached, key):
                return cached, True
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    analysis = analyze_music(path, config)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    try:
        temporary.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
        temporary.replace(cache_path)
    finally:
        temporary.unlink(missing_ok=True)
    return analysis, False


def negotiate_duration(direction: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    strategy = direction.get("duration_strategy", {})
    editorial = float(strategy.get("resolved_seconds", 0))
    flexibility = max(0.0, float(strategy.get("flexibility_seconds", 0)))
    safe = strategy.get("safe_shot_bounds_seconds", {})
    lower = max(float(strategy.get("minimum_seconds", editorial)), float(safe.get("minimum", 0)), editorial-flexibility)
    upper = min(float(strategy.get("maximum_seconds", editorial)), float(safe.get("maximum", math.inf)), editorial+flexibility)
    music_duration = float(analysis.get("duration_seconds", 0))
    if music_duration and music_duration < lower:
        return {"editorial_duration": editorial, "music_aligned_duration": None,
                "delta_seconds": None, "alignment_reason": "music_too_short_for_director_envelope",
                "usable_for_planning": False, "music_covers_timeline": False,
                "allowed_range_seconds": {"minimum": round(lower, 3), "maximum": round(upper, 3)}}
    if music_duration:
        upper = min(upper, music_duration)
    candidates = []
    for phrase in analysis.get("phrases", []):
        candidates.append((float(phrase["end"]), 1.0, "phrase_boundary"))
    for anchor in analysis.get("sync_anchors", []):
        weight = 1.2 if anchor["type"] in {"release", "final_resolving_beat", "phrase_boundary"} else .7
        candidates.append((float(anchor["time"]), weight * float(anchor["confidence"]), anchor["type"]))
    viable = [(time, weight, reason) for time, weight, reason in candidates if lower <= time <= upper]
    if viable:
        time, weight, reason = max(viable, key=lambda x: (x[1] - abs(x[0]-editorial)/max(1, flexibility), x[0]))
        aligned = round(time, 3)
        if abs(aligned-editorial) < .1:
            aligned, reason = editorial, "editorial_duration_already_aligned"
    else:
        aligned, reason = editorial, "no_better_boundary_within_flexibility"
    return {"editorial_duration": editorial, "music_aligned_duration": aligned,
            "delta_seconds": round(aligned-editorial, 3), "alignment_reason": reason,
            "usable_for_planning": True, "music_covers_timeline": not music_duration or music_duration >= aligned,
            "allowed_range_seconds": {"minimum": round(lower, 3), "maximum": round(upper, 3)}}


def interpret_tempo(analysis: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    """Select an editorial tempo without mutating the detected analysis fact."""
    tempo = analysis.get("tempo", {})
    detected = tempo.get("bpm"); confidence = float(tempo.get("confidence", 0))
    candidates = []
    if isinstance(detected, (int, float)) and confidence >= .12:
        for value, provenance in ((float(detected), "detected_primary"),
                                  (float(detected) / 2, "heuristic_half_time"),
                                  (float(detected) * 2, "heuristic_double_time")):
            if 40 <= value <= 220:
                inferred = confidence if provenance == "detected_primary" else confidence * .85
                candidates.append({"bpm": round(value, 3), "provenance": provenance,
                                   "confidence": round(min(confidence, inferred), 3)})
    preferred = profile.get("preferred_tempo_bpm", {})
    low, high = float(preferred.get("minimum", 70)), float(preferred.get("maximum", 150))
    center = (low + high) / 2
    chosen = min(candidates, key=lambda x: (0 if low <= x["bpm"] <= high else 1,
                                             abs(x["bpm"] - center), x["provenance"])) if candidates else None
    return {"detected_bpm": detected, "effective_bpm": chosen["bpm"] if chosen else None,
            "tempo_interpretation": chosen["provenance"] if chosen else "unavailable",
            "tempo_interpretation_confidence": chosen["confidence"] if chosen else 0.0,
            "alternate_bpm_candidates": [x for x in candidates if x["provenance"] != "detected_primary"]}


def effective_beat_grid(analysis: dict[str, Any], interpretation: dict[str, Any]) -> list[dict[str, Any]]:
    """Return source-local anchors; subdivisions are timing aids, never claimed downbeats."""
    beats = analysis.get("beats", [])
    duration = float(analysis.get("duration_seconds", 0))
    anchors = [{"time": round(float(b["time"]), 3), "provenance": b.get("type", "detected_beat"),
                "confidence": b.get("confidence", 0)} for b in beats]
    if interpretation.get("tempo_interpretation") == "heuristic_double_time":
        for left, right in zip(beats, beats[1:]):
            midpoint = round((float(left["time"]) + float(right["time"])) / 2, 3)
            if 0 <= midpoint <= duration:
                anchors.append({"time": midpoint, "provenance": "heuristic_subdivision",
                                "confidence": round(float(interpretation.get("tempo_interpretation_confidence", 0)) * .8, 3)})
    unique = {
        round(float(a["time"]), 3): a
        for a in sorted(anchors, key=lambda a: (a["time"], a["provenance"]))
    }
    return [unique[key] for key in sorted(unique) if 0 <= key <= duration]


def validate_music_analysis(value: object, expected_cache_key: str | None = None) -> bool:
    """Validate persisted/cache music facts before downstream editorial use."""
    if not isinstance(value, dict) or value.get("version") != MUSIC_SCHEMA_VERSION:
        return False
    source = value.get("source"); tempo = value.get("tempo")
    beats = value.get("beats"); phrases = value.get("phrases")
    duration = value.get("duration_seconds")
    if not isinstance(source, dict) or not isinstance(tempo, dict): return False
    if expected_cache_key is not None and source.get("cache_key") != expected_cache_key: return False
    if not isinstance(duration, (int, float)) or duration <= 0: return False
    if not isinstance(beats, list) or not isinstance(phrases, list): return False
    try:
        beat_times = [float(beat["time"]) for beat in beats]
        if any(time < 0 or time > duration for time in beat_times): return False
        return _monotonic(beat_times) and _phrases_valid(phrases, float(duration))
    except (KeyError, TypeError, ValueError):
        return False


def map_story_to_music(story: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
    phases = list(dict.fromkeys(entry.get("section") for entry in story.get("sequence", []) if entry.get("section")))
    phrases = analysis.get("phrases", [])
    if not phases or not phrases:
        return []
    result = []
    for index, phase in enumerate(phases):
        position = round(index * (len(phrases)-1) / max(1, len(phases)-1))
        candidates = range(max(0, position-1), min(len(phrases), position+2))
        if phase == "highlight":
            pick = max(candidates, key=lambda i: (phrases[i]["energy"], -abs(i-position)))
        elif phase == "closing":
            pick = max(candidates)
        else:
            pick = min(candidates, key=lambda i: abs(i-position))
        phrase = phrases[pick]
        result.append({"story_phase": phase, "phrase_index": phrase["index"],
                       "start": phrase["start"], "end": phrase["end"],
                       "musical_role": phrase.get("type"), "mapping_basis": "ordered_energy_aware"})
    return result


def _normalize(source: Path, output: Path, sample_rate: int) -> None:
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
               "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(output)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise MusicAnalysisError("FFmpeg is required for music preprocessing") from exc
    if result.returncode or not output.is_file():
        raise MusicAnalysisError(f"FFmpeg could not decode music: {result.stderr.strip()[-300:]}")


def _read_wav_envelope(path: Path, window_ms: int) -> tuple[list[float], int, float]:
    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getsampwidth() != 2 or audio.getnchannels() != 1:
                raise MusicAnalysisError("Normalized music is not mono 16-bit PCM")
            rate = audio.getframerate(); frame_count = audio.getnframes()
            window = max(1, round(rate * window_ms / 1000)); rms = []
            while raw := audio.readframes(window):
                values = array("h"); values.frombytes(raw)
                if sys.byteorder != "little": values.byteswap()
                rms.append(math.sqrt(sum(value*value for value in values) / max(1, len(values))) / 32768.0)
    except (OSError, wave.Error) as exc:
        raise MusicAnalysisError("Cannot read normalized music audio") from exc
    return rms, rate, frame_count/rate


def _energy_curve(rms: list[float], step: float, duration: float) -> list[dict[str, Any]]:
    peak = max(rms, default=0)
    normalized = [value/peak if peak else 0.0 for value in rms]
    result = []
    group = max(1, round(.5/step))
    for start in range(0, len(normalized), group):
        value = statistics.mean(normalized[start:start+group])
        label = "peak" if value >= .82 else "high" if value >= .58 else "medium" if value >= .28 else "low"
        result.append({"time": round(start*step, 3), "end": round(min(duration, (start+group)*step), 3),
                       "energy": round(value, 4), "level": label})
    return result


def _tempo_and_beats(rms: list[float], config: MusicConfig, duration: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    step = config.window_ms/1000
    onset = [0.0] + [max(0.0, rms[i]-rms[i-1]) for i in range(1, len(rms))]
    if not onset or max(onset) <= 1e-8:
        return {"bpm": None, "confidence": 0.0, "beat_interval_seconds": None,
                "ambiguity": "insufficient_percussive_evidence", "alternate_bpm": []}, []
    low_lag = max(1, round(60/config.bpm_max/step)); high_lag = max(low_lag, round(60/config.bpm_min/step))
    correlations = []
    for lag in range(low_lag, min(high_lag+1, len(onset)//2+1)):
        score = sum(onset[i]*onset[i-lag] for i in range(lag, len(onset)))
        correlations.append((score, lag))
    if not correlations or max(score for score, _ in correlations) <= 1e-12:
        return {"bpm": None, "confidence": 0.0, "beat_interval_seconds": None,
                "ambiguity": "insufficient_periodic_evidence", "alternate_bpm": []}, []
    best_score, lag = max(correlations, default=(0.0, low_lag))
    baseline = statistics.mean(score for score, _ in correlations) if correlations else 0
    confidence = max(0.0, min(1.0, (best_score-baseline)/(best_score+1e-12)))
    interval = lag*step; bpm = 60/interval
    ambiguity = "half_or_double_time_possible" if confidence < .55 else None
    alternatives = [round(value, 3) for value in (bpm/2, bpm*2)
                    if config.bpm_min <= value <= config.bpm_max] if ambiguity else []
    tempo = {"bpm": round(bpm, 3), "confidence": round(confidence, 3),
             "beat_interval_seconds": round(interval, 4), "ambiguity": ambiguity,
             "alternate_bpm": alternatives}
    if confidence < config.minimum_tempo_confidence:
        return tempo, []
    phase = max(range(min(lag, len(onset))), key=lambda p: sum(onset[i] for i in range(p, len(onset), lag)))
    maximum = max(onset)
    beats = []
    for index, frame in enumerate(range(phase, len(onset), lag)):
        time = frame*step
        if time > duration: break
        strength = onset[frame]/maximum if maximum else 0
        accent = confidence >= .55 and index % 4 == 0
        beats.append({"index": index, "time": round(time, 3), "strength": round(strength, 3),
                      "type": "heuristic_accent" if accent else "detected_beat",
                      "bar_position": 1 if accent else None, "confidence": round(confidence*(.9 if accent else .75), 3),
                      "inference": "onset_autocorrelation_grid"})
    return tempo, beats


def _phrases(energy: list[dict[str, Any]], beats: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    interval = (beats[1]["time"]-beats[0]["time"])*8 if len(beats) > 1 else 8.0
    length = max(4.0, min(12.0, interval))
    boundaries = [0.0]
    while boundaries[-1]+length < duration-2:
        target = boundaries[-1]+length
        nearby = [beat["time"] for beat in beats if abs(beat["time"]-target) <= .5]
        boundaries.append(min(nearby, key=lambda x: abs(x-target)) if nearby else target)
    boundaries.append(duration)
    phrases = []
    for index, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        values = [point["energy"] for point in energy if start <= point["time"] < end]
        value = statistics.mean(values) if values else 0.0
        phrases.append({"index": index, "start": round(start, 3), "end": round(end, 3),
                        "type": None, "energy": round(value, 4), "confidence": .55,
                        "boundary_inference": "eight_beat_grid" if beats else "fixed_analysis_window"})
    return phrases


def _structure(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not phrases: return []
    peak = max(range(len(phrases)), key=lambda i: (phrases[i]["energy"], -i))
    result = []
    for index, phrase in enumerate(phrases):
        label = "peak" if index == peak else "intro" if index == 0 and phrase["energy"] < .6 else None
        if label is None and index == len(phrases)-1 and index > peak: label = "outro"
        if label is None and index < peak and index > 0: label = "build"
        if label is None and index > peak: label = "release"
        if label:
            phrase["type"] = label
            result.append({"type": label, "phrase_index": index, "start": phrase["start"], "end": phrase["end"],
                           "confidence": phrase["confidence"], "inference": "relative_energy_position"})
    return result


def _sync_anchors(beats: list[dict[str, Any]], phrases: list[dict[str, Any]], energy: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    anchors = [{"time": phrase["start"], "type": "phrase_boundary", "strength": phrase["energy"],
                "confidence": phrase["confidence"], "inference": phrase["boundary_inference"]} for phrase in phrases[1:]]
    if energy:
        point = max(energy, key=lambda value: (value["energy"], -value["time"]))
        anchors.append({"time": point["time"], "type": "peak", "strength": point["energy"],
                        "confidence": .6, "inference": "relative_rms_peak"})
    if beats:
        anchors.append({"time": beats[0]["time"], "type": "opening_accent", "strength": beats[0]["strength"],
                        "confidence": beats[0]["confidence"], "inference": beats[0]["inference"]})
        anchors.append({"time": beats[-1]["time"], "type": "final_resolving_beat", "strength": beats[-1]["strength"],
                        "confidence": beats[-1]["confidence"], "inference": beats[-1]["inference"]})
    return sorted(anchors, key=lambda value: (value["time"], value["type"]))


def _monotonic(values: list[float]) -> bool:
    return all(first < second for first, second in zip(values, values[1:]))


def _phrases_valid(phrases: list[dict[str, Any]], duration: float) -> bool:
    return all(0 <= phrase["start"] < phrase["end"] <= duration+.001 and
               (not index or phrases[index-1]["end"] <= phrase["start"])
               for index, phrase in enumerate(phrases))
