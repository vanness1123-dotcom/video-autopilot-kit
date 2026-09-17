"""Local font identity/metrics with optional bounded measured text layout."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

VERSION = "1.0"
PROFILE_VERSION = "local_fonts.v1"
SIZE_PROFILE_VERSION = "single_line_sizes.v1"
SIZE_CLASSES = {"display": 96, "large": 72, "medium": 52, "small": 40, "micro": 32}
STYLE_KEYS = ("font_role", "weight_role", "size_class", "line_height_class",
              "letter_spacing_class", "case_transform")
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class TypographyError(ValueError):
    """A font, coverage or metrics contract cannot be resolved/validated safely."""


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FontCandidate:
    logical_font_id: str
    path: Path
    face_index: int = 0
    weight: str = "regular"

    def __post_init__(self):
        if not isinstance(self.logical_font_id, str) or not ID_PATTERN.fullmatch(self.logical_font_id):
            raise TypographyError("Invalid logical font ID")
        if not isinstance(self.path, Path) or not _integer(self.face_index):
            raise TypographyError("Font candidate requires a Path and nonnegative face index")
        if self.weight not in {"regular", "bold"}:
            raise TypographyError("Font candidate weight must be regular or bold")


@dataclass(frozen=True)
class TypographyConfig:
    design_width: int = 1080
    design_height: int = 1920
    user_fonts: tuple[FontCandidate, ...] = ()
    system_fonts: bool = True
    profile_version: str = PROFILE_VERSION

    def __post_init__(self):
        if not all(_integer(v, 1) and v <= 16384 for v in (self.design_width, self.design_height)):
            raise TypographyError("Typography design canvas must contain positive integers <= 16384")
        if type(self.system_fonts) is not bool or not isinstance(self.user_fonts, tuple) or not all(isinstance(f, FontCandidate) for f in self.user_fonts):
            raise TypographyError("Invalid typography font profile")
        if not isinstance(self.profile_version, str) or not self.profile_version.strip():
            raise TypographyError("Typography font profile version is required")


def font_candidates(config: TypographyConfig) -> tuple[FontCandidate, ...]:
    """Explicit ordered candidates; no directory scan or arbitrary OS font selection."""
    result = list(config.user_fonts)
    if config.system_fonts and sys.platform == "win32":
        root = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        for weight, entries in (
            ("regular", (("latin_segoe_regular", "segoeui.ttf", 0), ("latin_arial_regular", "arial.ttf", 0),
                         ("cjk_jhenghei_regular", "msjh.ttc", 0), ("cjk_jhenghei_ui_regular", "msjh.ttc", 1),
                         ("cjk_mingliu_regular", "mingliu.ttc", 0), ("cjk_pmingliu_regular", "mingliu.ttc", 1),
                         ("cjk_yahei_regular", "msyh.ttc", 0))),
            ("bold", (("latin_segoe_bold", "segoeuib.ttf", 0), ("latin_arial_bold", "arialbd.ttf", 0),
                      ("cjk_jhenghei_bold", "msjhbd.ttc", 0), ("cjk_yahei_bold", "msyhbd.ttc", 0))),
        ):
            result.extend(FontCandidate(logical, root / filename, index, weight) for logical, filename, index in entries)
    # Non-Windows systems use explicit user candidates; there is no guessed fallback.
    return tuple(result)


def load_font_profile(path: Path) -> tuple[FontCandidate, ...]:
    """Optional ordered JSON array; paths resolve relative to the profile file."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(rows, list): raise ValueError("expected an array")
        values = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"logical_font_id", "path", "face_index", "weight"}:
                raise ValueError("invalid font candidate fields")
            if not isinstance(row["path"], str) or not row["path"]: raise ValueError("missing path")
            values.append(FontCandidate(row["logical_font_id"], (path.parent / row["path"]).resolve(), row["face_index"], row["weight"]))
        return tuple(values)
    except (OSError, ValueError, TypeError) as exc:
        raise TypographyError(f"Cannot load typography font profile: {path}: {exc}") from exc


def _dependencies():
    try:
        import fontTools
        from fontTools.ttLib import TTFont, TTCollection
        from PIL import ImageFont, features, __version__ as pillow_version
    except ImportError as exc:
        raise TypographyError("Typography requires local fontTools and Pillow; install requirements-typography.txt explicitly") from exc
    if not features.check("freetype2"):
        raise TypographyError("Pillow FreeType backend is unavailable")
    backend = {"id": "pillow_freetype", "pillow_version": pillow_version,
               "freetype_version": features.version("freetype2"), "layout_engine": "basic",
               "coverage_backend": "fonttools_unicode_cmap", "fonttools_version": fontTools.__version__}
    return TTFont, TTCollection, ImageFont, backend


def _supported_text(text):
    if not isinstance(text, str) or not text or not text.strip():
        raise TypographyError("Typography requires nonempty text")
    for char in text:
        cp = ord(char)
        # No invisible characters are silently removed. ASCII/NBSP/ideographic
        # spaces must themselves be covered by cmap. Combining marks are rejected
        # explicitly until a shaping policy is introduced, never dropped.
        allowed = (0x20 <= cp <= 0x7E or cp == 0xA0 or
                   (0xA1 <= cp <= 0xFF and cp != 0xAD) or
                   0x2000 <= cp <= 0x206F or 0x3000 <= cp <= 0x303F or
                   0x3400 <= cp <= 0x4DBF or 0x4E00 <= cp <= 0x9FFF or
                   0xF900 <= cp <= 0xFAFF or 0xFF01 <= cp <= 0xFF60)
        if not allowed or unicodedata.category(char)[0] in {"C", "M"} or cp in {0x2028, 0x2029}:
            raise TypographyError(f"Unsupported single-line script/control/combining character U+{cp:04X}")


def inspect_font(data: bytes, face_index: int, text: str) -> dict:
    """Inspect selected SFNT face; cmap coverage never uses rendered glyph masks."""
    TTFont, TTCollection, _, _ = _dependencies()
    if not _integer(face_index): raise TypographyError("Invalid font face index")
    try:
        with io.BytesIO(data) as stream:
            collection = TTCollection(stream, lazy=True) if data[:4] == b"ttcf" else None
            try:
                if collection is not None:
                    if face_index >= len(collection.fonts): raise TypographyError("TTC face index outside collection")
                    font = collection.fonts[face_index]
                else:
                    if face_index != 0: raise TypographyError("Non-collection font requires face index zero")
                    font = TTFont(stream, lazy=True)
                try:
                    if "fvar" in font: raise TypographyError("Variable fonts are outside the frozen-face profile")
                    cmap = font.getBestCmap()
                    if not cmap: raise TypographyError("Font has no readable Unicode cmap")
                    missing = []
                    for cp in sorted(set(map(ord, text))):
                        name = cmap.get(cp)
                        if name is None or name == ".notdef" or font.getGlyphID(name) == 0:
                            missing.append(cp)
                    family = font["name"].getDebugName(1)
                    style = font["name"].getDebugName(2)
                    if not family or not style: raise TypographyError("Selected face lacks family/style metadata")
                    return {"missing_codepoints": missing, "family": family, "style": style}
                finally:
                    if collection is None: font.close()
            finally:
                if collection is not None: collection.close()
    except TypographyError:
        raise
    except Exception as exc:
        raise TypographyError(f"Unreadable font/cmap face {face_index}: {type(exc).__name__}: {exc}") from exc


def _fingerprint_inputs(value, overlay):
    result = {"text": overlay["content"]["text"], "style": {k: overlay["style"].get(k) for k in STYLE_KEYS},
            **{k: value[k] for k in ("version", "design_canvas", "logical_font_id", "font_identity",
                                     "metrics_backend", "font_profile", "size_profile_version",
                                     "requested_size_class", "resolved_font_size", "line_spacing")}}
    if "measured_layout" in value:
        result["measured_layout_dependency"] = value["measured_layout"].get("dependency_fingerprint")
    return result


class TypographyResolver:
    """Per-run immutable font byte snapshots; no persistent cache or source-media I/O."""
    def __init__(self, config: TypographyConfig | None = None):
        self.config = config or TypographyConfig()
        self.candidates = font_candidates(self.config)
        self._bytes = {}

    def resolve(self, overlay: dict) -> dict:
        value = self._resolve_metrics(overlay)
        if "placement" in overlay:
            from .typography_layout import resolve_measured_layout
            data = next(data for data in self._bytes.values()
                        if hashlib.sha256(data).hexdigest() == value["font_identity"]["sha256"])
            value["measured_layout"] = resolve_measured_layout(value, overlay, data)
            value["dependency_fingerprint"] = _digest(_fingerprint_inputs(value, overlay))
            validate_typography(value, overlay)
        return value

    def _resolve_metrics(self, overlay: dict) -> dict:
        text = overlay["content"]["text"]
        _supported_text(text)
        _, _, ImageFont, backend = _dependencies()
        style = overlay["style"]
        if style.get("font_role") not in {"display", "headline", "body", "caption", "label"} or style.get("weight_role") not in {"regular", "medium", "semibold", "bold"}:
            raise TypographyError("Unsupported logical font role/weight")
        size_class = style.get("size_class")
        if size_class not in SIZE_CLASSES: raise TypographyError("Unsupported typography size class")
        if style.get("case_transform") != "none" or style.get("letter_spacing_class") != "normal" or style.get("line_height_class") != "compact":
            raise TypographyError("Single-line typography requires unchanged case, normal spacing, compact line height")
        # Scale the central 1920-high profile to the declared design canvas once.
        size = max(1, round(SIZE_CLASSES[size_class] * self.config.design_height / 1920))
        weight = "bold" if style["weight_role"] in {"semibold", "bold"} else "regular"
        failures = []
        for candidate in self.candidates:
            if candidate.weight != weight: continue
            try:
                if candidate.path not in self._bytes:
                    self._bytes[candidate.path] = candidate.path.read_bytes()
                data = self._bytes[candidate.path]
                inspection = inspect_font(data, candidate.face_index, text)
                if inspection["missing_codepoints"]:
                    failures.append(f"{candidate.logical_font_id}: missing " + ",".join(f"U+{c:04X}" for c in inspection["missing_codepoints"]))
                    continue
                # Both libraries consume the same byte snapshot and explicit face.
                font = ImageFont.truetype(io.BytesIO(data), size, index=candidate.face_index, layout_engine=ImageFont.Layout.BASIC)
                family, face_style = font.getname()
                if (family, face_style) != (inspection["family"], inspection["style"]):
                    raise TypographyError("Pillow/fontTools selected-face metadata disagree")
                ascent, descent = font.getmetrics()
                ink = font.getbbox(text, anchor="ls")
                w, h = self.config.design_width, self.config.design_height
                value = {"version": VERSION, "design_canvas": {"width": w, "height": h},
                         "logical_font_id": candidate.logical_font_id,
                         "font_identity": {"sha256": hashlib.sha256(data).hexdigest(), "face_index": candidate.face_index,
                                           "family": family, "style": face_style},
                         "metrics_backend": backend,
                         "font_profile": {"version": self.config.profile_version,
                                          "fingerprint": _digest([{ "logical_font_id": c.logical_font_id, "file_name": c.path.name,
                                              "face_index": c.face_index, "weight": c.weight} for c in self.candidates])},
                         "size_profile_version": SIZE_PROFILE_VERSION, "requested_size_class": size_class,
                         "resolved_font_size": size, "line_spacing": 0, "lines": [text],
                         "metrics": {"coordinate_space": "canvas_normalized", "origin": "left_baseline",
                                     "advance": font.getlength(text) / w,
                                     "ink_bounds": {"left": ink[0]/w, "top": ink[1]/h, "right": ink[2]/w, "bottom": ink[3]/h},
                                     "ascent": ascent/h, "descent": descent/h, "baseline_offset": ascent/h,
                                     "line_height": (ascent+descent)/h},
                         "validation": {"coverage": "complete_unicode_cmap", "checked_codepoints": len(set(text)),
                                        "collision_checked": False}}
                value["dependency_fingerprint"] = _digest(_fingerprint_inputs(value, overlay))
                validate_typography(value, overlay)
                return value
            except (OSError, TypographyError) as exc:
                failures.append(f"{candidate.logical_font_id}: {exc}")
        raise TypographyError("No configured font covers the complete text: " + ("; ".join(failures) or "no candidate for requested weight"))


def validate_typography(value, overlay, *, resolver: TypographyResolver | None = None):
    """Structural validation; resolver additionally verifies live identity/coverage/metrics."""
    if isinstance(value, dict) and "measured_layout" in value:
        from .typography_layout import validate_measured_layout
        base = copy.deepcopy(value)
        measured = base.pop("measured_layout")
        # Preserve and validate the legacy metrics contract without reinterpreting it.
        try:
            base["dependency_fingerprint"] = _digest(_fingerprint_inputs(base, overlay))
        except (KeyError, TypeError, ValueError) as exc:
            raise TypographyError("Malformed typography dependency inputs") from exc
        validate_typography(base, overlay)
        validate_measured_layout(measured, base, overlay)
        if value["dependency_fingerprint"] != _digest(_fingerprint_inputs(value, overlay)):
            raise TypographyError("Stale measured typography fingerprint")
        if resolver is not None and value != resolver.resolve(overlay):
            raise TypographyError("Stale font environment or fabricated typography metrics/coverage")
        return
    def require(condition, message):
        if not condition: raise TypographyError(message)
    required = {"version", "design_canvas", "logical_font_id", "font_identity", "metrics_backend", "font_profile",
                "size_profile_version", "requested_size_class", "resolved_font_size", "line_spacing", "lines",
                "metrics", "dependency_fingerprint", "validation"}
    require(isinstance(value, dict) and set(value) == required, "Malformed resolved typography")
    require(value["version"] == VERSION and value["size_profile_version"] == SIZE_PROFILE_VERSION, "Unsupported typography/profile version")
    require(isinstance(value["logical_font_id"], str) and bool(ID_PATTERN.fullmatch(value["logical_font_id"])), "Missing/invalid logical font ID")
    canvas = value["design_canvas"]
    require(isinstance(canvas, dict) and set(canvas) == {"width", "height"} and all(_integer(v, 1) and v <= 16384 for v in canvas.values()), "Invalid typography canvas")
    identity = value["font_identity"]
    require(isinstance(identity, dict) and set(identity) == {"sha256", "face_index", "family", "style"}, "Invalid font identity")
    require(isinstance(identity["sha256"], str) and bool(SHA_PATTERN.fullmatch(identity["sha256"])) and _integer(identity["face_index"]), "Invalid font SHA-256/face index")
    require(all(isinstance(identity[k], str) and identity[k].strip() for k in ("family", "style")), "Invalid font family/style")
    backend = value["metrics_backend"]
    require(isinstance(backend, dict) and set(backend) == {"id", "pillow_version", "freetype_version", "layout_engine", "coverage_backend", "fonttools_version"}, "Invalid metrics backend")
    require(backend["id"] == "pillow_freetype" and backend["layout_engine"] == "basic" and backend["coverage_backend"] == "fonttools_unicode_cmap", "Unsupported metrics backend")
    require(all(isinstance(v, str) and v.strip() for v in backend.values()), "Missing backend version")
    profile = value["font_profile"]
    require(isinstance(profile, dict) and set(profile) == {"version", "fingerprint"} and isinstance(profile["version"], str) and bool(profile["version"].strip()), "Invalid font profile")
    require(isinstance(profile["fingerprint"], str) and bool(SHA_PATTERN.fullmatch(profile["fingerprint"])), "Invalid font profile fingerprint")
    text = overlay.get("content", {}).get("text")
    _supported_text(text)
    require(value["lines"] == [text], "Typography lines disagree with authoritative content.text")
    size_class = value["requested_size_class"]
    require(isinstance(size_class, str) and size_class in SIZE_CLASSES and size_class == overlay["style"].get("size_class"), "Invalid requested size class")
    require(_integer(value["resolved_font_size"], 1) and value["resolved_font_size"] == max(1, round(SIZE_CLASSES[size_class]*canvas["height"]/1920)), "Invalid preferred font size")
    require(_finite(value["line_spacing"]) and value["line_spacing"] == 0, "Unsupported single-line spacing")
    metrics = value["metrics"]
    require(isinstance(metrics, dict) and set(metrics) == {"coordinate_space", "origin", "advance", "ink_bounds", "ascent", "descent", "baseline_offset", "line_height"}, "Invalid single-line metrics")
    require(metrics["coordinate_space"] == "canvas_normalized" and metrics["origin"] == "left_baseline", "Unsupported metrics units/origin")
    require(all(_finite(metrics[k]) for k in ("advance", "ascent", "descent", "baseline_offset", "line_height")), "Non-finite/bool metrics")
    require(metrics["advance"] > 0 and metrics["ascent"] > 0 and metrics["descent"] >= 0 and metrics["line_height"] > 0, "Invalid metrics extent")
    require(abs(metrics["line_height"]-metrics["ascent"]-metrics["descent"]) < 1e-12 and metrics["baseline_offset"] == metrics["ascent"], "Inconsistent baseline/line height")
    ink = metrics["ink_bounds"]
    require(isinstance(ink, dict) and set(ink) == {"left", "top", "right", "bottom"} and all(_finite(v) for v in ink.values()), "Invalid ink bounds")
    require(ink["left"] < ink["right"] and ink["top"] < ink["bottom"], "Inverted/empty ink bounds")
    evidence = value["validation"]
    require(isinstance(evidence, dict) and set(evidence) == {"coverage", "checked_codepoints", "collision_checked"}, "Invalid typography validation evidence")
    require(evidence["coverage"] == "complete_unicode_cmap" and _integer(evidence["checked_codepoints"], 1) and evidence["checked_codepoints"] == len(set(text)) and evidence["collision_checked"] is False, "Invalid coverage/collision evidence")
    require(isinstance(value["dependency_fingerprint"], str) and bool(SHA_PATTERN.fullmatch(value["dependency_fingerprint"])) and value["dependency_fingerprint"] == _digest(_fingerprint_inputs(value, overlay)), "Stale/malformed typography dependency fingerprint")
    if resolver is not None:
        require(value == resolver.resolve(overlay), "Stale font environment or fabricated typography metrics/coverage")


def resolve_plan_typography(plan, config=None):
    from .typography_layout import TypographyFitError
    result = copy.deepcopy(plan)
    resolver = TypographyResolver(config)
    for block in result["blocks"]:
        kept = []
        for overlay in block["resolved_overlay"]["overlays"]:
            try:
                overlay["resolved_typography"] = resolver.resolve(overlay)
                kept.append(overlay)
            except TypographyFitError as exc:
                block["resolved_overlay"]["selection_reasons"].append(
                    f"typography_omitted:{overlay['overlay_id']}:{exc}")
        block["resolved_overlay"]["overlays"] = kept
    return result
