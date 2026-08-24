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
            with patch("urllib.request.urlopen", return_value=_Response(response)) as call:
                with self.assertRaisesRegex(VisionResponseValidationError, "parse_error"):
                    LocalVisionProvider(retries=0).analyze_photo("photo-1", image)
            self.assertEqual(call.call_count, 2)

    def test_invalid_structured_json_gets_one_bounded_retry(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "frame.jpg"
            image.write_bytes(b"jpeg")
            invalid = {
                "done_reason": "length",
                "message": {"content": '{"objects": ["repeated"'},
            }
            valid = {"done_reason": "stop", "message": {"content": json.dumps(valid_payload())}}
            with patch(
                "urllib.request.urlopen",
                side_effect=[_Response(invalid), _Response(valid)],
            ) as call:
                result = LocalVisionProvider(retries=0).analyze_photo("photo-1", image)
            self.assertEqual(result.travel_category, "street")
            self.assertEqual(call.call_count, 2)
            retry_body = json.loads(call.call_args_list[1].args[0].data)
            self.assertEqual(retry_body["format"]["properties"]["tags"]["maxItems"], 16)
            self.assertEqual(retry_body["format"]["properties"]["objects"]["maxItems"], 20)
            self.assertIn("Never repeat list items", retry_body["messages"][0]["content"])

    def test_non_object_structured_json_is_rejected_after_retry(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "frame.jpg"
            image.write_bytes(b"jpeg")
            response = {"done_reason": "stop", "message": {"content": "[]"}}
            with patch("urllib.request.urlopen", return_value=_Response(response)):
                with self.assertRaisesRegex(VisionResponseValidationError, "must be an object"):
                    LocalVisionProvider(retries=0).analyze_photo("photo-1", image)


if __name__ == "__main__":
    unittest.main()
