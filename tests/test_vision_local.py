"""Ollama adapter tests without real network calls."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from travel_reel.vision import VisionResponseValidationError
from travel_reel.vision_local import LocalVisionProvider
from test_vision import valid_payload


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


class LocalVisionProviderTests(unittest.TestCase):
    def test_provider_contract_and_request_options(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "frame.jpg"
            image.write_bytes(b"jpeg")
            response = {"message": {"content": json.dumps(valid_payload())}}
            with patch("urllib.request.urlopen", return_value=_Response(response)) as call:
                provider = LocalVisionProvider(retries=0)
                result = provider.analyze_photo("photo-1", image)
            request_body = json.loads(call.call_args.args[0].data)
            self.assertEqual(result.travel_category, "street")
            self.assertEqual(request_body["model"], "qwen3-vl:4b-instruct")
            self.assertFalse(request_body["think"])
            self.assertEqual(request_body["options"]["temperature"], 0)
            self.assertIsInstance(request_body["format"], dict)

    def test_invalid_provider_json_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "frame.jpg"
            image.write_bytes(b"jpeg")
            response = {"message": {"content": "not-json"}}
            with patch("urllib.request.urlopen", return_value=_Response(response)):
                with self.assertRaises(VisionResponseValidationError):
                    LocalVisionProvider(retries=0).analyze_photo("photo-1", image)


if __name__ == "__main__":
    unittest.main()
