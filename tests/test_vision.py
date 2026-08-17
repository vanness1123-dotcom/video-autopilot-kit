"""Provider-neutral Vision schema and cache tests."""
import unittest

from travel_reel.vision import (
    VisionResponseValidationError,
    normalize_vision_result,
    vision_cache_key,
)


def valid_payload() -> dict:
    return {
        "description": "A lively city street with pedestrians.",
        "tags": ["City Street", "night-time", "City Street"],
        "travel_category": "STREET",
        "scene_type": "street",
        "activity": "walking",
        "mood": "Excited",
        "people": {"visible": True, "group_photo": False, "selfie": False, "count_estimate": 3},
        "objects": ["Building", "street light"],
        "landmark_hint": {"name": "Uncertain Tower", "confidence": 0.4},
        "quality_observations": {
            "subject_clear": True,
            "composition_strength": "HIGH",
            "visual_clutter": "medium",
            "subject_prominence": "high",
        },
        "confidence": {"scene_type": 0.9, "bad": 2.0},
    }


class VisionSchemaTests(unittest.TestCase):
    def test_normalizes_controlled_vocabulary_and_conservative_landmark(self) -> None:
        result = normalize_vision_result(valid_payload())
        self.assertEqual(result.travel_category, "street")
        self.assertEqual(result.scene_type, "street")
        self.assertIsNone(result.mood)
        self.assertEqual(result.tags, ["city_street", "night_time"])
        self.assertIsNone(result.landmark_hint.name)
        self.assertEqual(result.confidence, {"scene_type": 0.9})

    def test_unknown_values_degrade_safely(self) -> None:
        payload = valid_payload()
        payload["travel_category"] = "vacation_magic"
        payload["scene_type"] = "spaceship"
        result = normalize_vision_result(payload)
        self.assertEqual(result.travel_category, "other")
        self.assertEqual(result.scene_type, "unknown")

    def test_missing_description_is_invalid(self) -> None:
        payload = valid_payload()
        payload["description"] = ""
        with self.assertRaises(VisionResponseValidationError):
            normalize_vision_result(payload)

    def test_cache_identity_changes_only_for_vision_inputs(self) -> None:
        first = vision_cache_key("abc", "local", "model-a", "photo")
        self.assertEqual(first, vision_cache_key("abc", "local", "model-a", "photo"))
        self.assertNotEqual(first, vision_cache_key("changed", "local", "model-a", "photo"))
        self.assertNotEqual(first, vision_cache_key("abc", "local", "model-b", "photo"))


if __name__ == "__main__":
    unittest.main()
