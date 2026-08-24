"""Ollama-backed implementation of the provider-neutral Vision contract."""
from __future__ import annotations

import base64
import copy
import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .vision import (
    VisionProviderUnavailable,
    VisionResponseValidationError,
    VisionResult,
    VisionTimeoutError,
    normalize_vision_result,
)


class LocalVisionProvider:
    """Analyze local images through Ollama's HTTP API."""

    name = "local-ollama"

    def __init__(
        self,
        model: str = "qwen3-vl:4b-instruct",
        endpoint: str = "http://localhost:11434",
        timeout_seconds: float = 120,
        retries: int = 1,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.retries = max(0, retries)

    def analyze_photo(self, media_id: str, image: Path) -> VisionResult:
        return self._analyze(media_id, [image], _PHOTO_PROMPT)

    def analyze_video(
        self, media_id: str, frames: list[Path], timestamps: list[float]
    ) -> VisionResult:
        if not frames:
            raise VisionResponseValidationError("Video analysis requires representative frames")
        timestamp_text = ", ".join(f"{value:.3f}s" for value in timestamps)
        return self._analyze(media_id, frames, f"{_VIDEO_PROMPT}\nFrame timestamps: {timestamp_text}")

    def _analyze(self, media_id: str, images: list[Path], prompt: str) -> VisionResult:
        encoded_images = [base64.b64encode(path.read_bytes()).decode("ascii") for path in images]
        request_payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": _OLLAMA_SCHEMA,
            "options": {"temperature": 0, "num_predict": 450},
            "messages": [{
                "role": "user",
                "content": f"Media ID: {media_id}\n{prompt}",
                "images": encoded_images,
            }],
        }
        try:
            payload = _decode_ollama_content(self._post(request_payload))
        except VisionResponseValidationError:
            retry_payload = copy.deepcopy(request_payload)
            retry_payload["format"] = _BOUNDED_OLLAMA_SCHEMA
            retry_payload["messages"][0]["content"] += _STRUCTURED_RETRY_INSTRUCTION
            payload = _decode_ollama_content(self._post(retry_payload))
        return normalize_vision_result(payload)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                transient = exc.code == 429 or 500 <= exc.code < 600
                if transient and attempt < self.retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise VisionProviderUnavailable(f"Ollama HTTP error {exc.code}") from exc
            except (TimeoutError, socket.timeout) as exc:
                if attempt < self.retries:
                    continue
                raise VisionTimeoutError("Ollama Vision request timed out") from exc
            except (urllib.error.URLError, ConnectionError, OSError) as exc:
                if attempt < self.retries:
                    time.sleep(0.25 * (attempt + 1))
                    continue
                raise VisionProviderUnavailable(f"Cannot reach Ollama at {self.endpoint}") from exc
            except json.JSONDecodeError as exc:
                raise VisionResponseValidationError("Ollama HTTP response was not JSON") from exc
        raise VisionProviderUnavailable("Ollama request failed")


_BASE_PROMPT = """Observe the supplied travel media conservatively. Return only JSON matching the schema.
Describe visible facts in one concise sentence. Do not select media or tell a story. Do not infer a location from a folder or media ID.
Only name a landmark when visually distinctive and strongly supported; otherwise use null. Confidence is optional and must
be omitted or left empty unless meaningful. Use the supplied controlled vocabularies. count_estimate is approximate."""

_PHOTO_PROMPT = _BASE_PROMPT + "\nAnalyze this single photo."
_VIDEO_PROMPT = _BASE_PROMPT + "\nThe images are ordered representative frames from one video. Aggregate them into one video-level observation and mention visible change or action only when supported across frames."

_STRUCTURED_RETRY_INSTRUCTION = (
    "\nYour previous response was invalid or incomplete. Return the complete JSON object again. "
    "Return at most 16 unique concise tags and at most 20 unique concise objects. "
    "Never repeat list items."
)

_OLLAMA_SCHEMA = {
    "type": "object",
    "required": [
        "description", "tags", "travel_category", "scene_type", "activity",
        "mood", "people", "objects", "landmark_hint", "quality_observations", "confidence",
    ],
    "properties": {
        "description": {"type": "string", "maxLength": 500},
        "tags": {"type": "array", "items": {"type": "string"}},
        "travel_category": {"type": "string", "enum": [
            "arrival", "transportation", "landmark", "food", "cafe", "shopping",
            "street", "nature", "cityscape", "nightlife", "accommodation", "theme_park",
            "activity", "portrait", "selfie", "group", "detail", "transition", "other"
        ]},
        "scene_type": {"type": "string", "enum": [
            "indoor", "outdoor", "street", "restaurant", "cafe", "airport", "station",
            "hotel", "market", "park", "theme_park", "river", "mountain", "beach",
            "cityscape", "unknown"
        ]},
        "activity": {"type": ["string", "null"]},
        "mood": {"type": ["string", "null"], "enum": [
            "energetic", "joyful", "calm", "romantic", "luxurious", "playful",
            "adventurous", "nostalgic", "neutral", None
        ]},
        "people": {
            "type": "object",
            "required": ["visible", "group_photo", "selfie", "count_estimate"],
            "properties": {
                "visible": {"type": "boolean"},
                "group_photo": {"type": "boolean"},
                "selfie": {"type": "boolean"},
                "count_estimate": {"type": ["integer", "null"]},
            },
        },
        "objects": {"type": "array", "items": {"type": "string"}},
        "landmark_hint": {
            "type": "object",
            "required": ["name", "confidence"],
            "properties": {
                "name": {"type": ["string", "null"]},
                "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            },
        },
        "quality_observations": {
            "type": "object",
            "required": ["subject_clear", "composition_strength", "visual_clutter", "subject_prominence"],
            "properties": {
                "subject_clear": {"type": ["boolean", "null"]},
                "composition_strength": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                "visual_clutter": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
                "subject_prominence": {"type": ["string", "null"], "enum": ["low", "medium", "high", None]},
            },
        },
        "confidence": {"type": "object", "additionalProperties": {"type": "number"}},
    },
}

_BOUNDED_OLLAMA_SCHEMA = copy.deepcopy(_OLLAMA_SCHEMA)
_BOUNDED_OLLAMA_SCHEMA["properties"]["tags"]["maxItems"] = 16
_BOUNDED_OLLAMA_SCHEMA["properties"]["objects"]["maxItems"] = 20


def _decode_ollama_content(raw: object) -> dict[str, Any]:
    """Decode the assistant JSON while retaining safe diagnostic context."""
    done_reason = raw.get("done_reason") if isinstance(raw, dict) else None
    try:
        message = raw["message"]  # type: ignore[index]
        content = message["content"]
    except (KeyError, TypeError) as exc:
        raise VisionResponseValidationError(
            f"Ollama structured response is missing message.content (done_reason={done_reason!r})"
        ) from exc
    if not isinstance(content, str):
        raise VisionResponseValidationError(
            "Ollama structured response message.content must be a string "
            f"(done_reason={done_reason!r}, type={type(content).__name__})"
        )
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise VisionResponseValidationError(
            "Ollama returned invalid structured JSON "
            f"(done_reason={done_reason!r}, content_length={len(content)}, "
            f"parse_error={exc.msg!r}, line={exc.lineno}, column={exc.colno}, char={exc.pos})"
        ) from exc
    if not isinstance(payload, dict):
        raise VisionResponseValidationError(
            "Ollama structured JSON must be an object "
            f"(done_reason={done_reason!r}, type={type(payload).__name__})"
        )
    return payload
