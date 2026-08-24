"""Deterministic Sprint 4 scoring tests."""
import unittest
from collections import Counter

from travel_reel.config import ScoringConfig
from travel_reel.scoring import NEUTRAL_SCORE, score_media


def media(quality=None, mood="neutral", category="street", people=None):
    return {"id": "photo-1", "vision": {
        "description": "A travel scene", "tags": ["travel"], "objects": ["street"],
        "travel_category": category, "scene_type": "street", "activity": None,
        "mood": mood, "people": people or {"visible": False, "selfie": False, "group_photo": False},
        "landmark_hint": {"name": None, "confidence": None},
        "quality_observations": quality or {}, "confidence": {}, "vision_metadata": {},
    }}


class ScoringTests(unittest.TestCase):
    def test_weight_validation(self):
        with self.assertRaisesRegex(ValueError, "sum to 1.0"):
            ScoringConfig(technical_quality=0.5)
        with self.assertRaisesRegex(ValueError, "negative"):
            ScoringConfig(technical_quality=-0.1, composition=0.4)

    def test_deterministic_score_and_visible_components(self):
        item = media({"subject_clear": True, "composition_strength": "high", "visual_clutter": "low", "subject_prominence": "high"})
        args = (item, "photo", ScoringConfig(), {"width": 1080, "height": 1920})
        first = score_media(*args); second = score_media(*args)
        self.assertEqual(first, second)
        self.assertTrue(0 <= first["total"] <= 100)
        self.assertEqual(set(ScoringConfig().weights), set(first) & set(ScoringConfig().weights))

    def test_missing_metadata_is_neutral(self):
        result = score_media(media(), "photo", ScoringConfig(), {})
        self.assertEqual(result["technical_quality"], NEUTRAL_SCORE)
        self.assertEqual(result["composition"], NEUTRAL_SCORE)
        self.assertEqual(result["vertical_suitability"], NEUTRAL_SCORE)

    def test_portrait_is_more_vertically_suitable_than_landscape(self):
        item = media()
        portrait = score_media(item, "photo", ScoringConfig(), {"width": 1080, "height": 1920})
        landscape = score_media(item, "photo", ScoringConfig(), {"width": 1920, "height": 1080})
        self.assertGreater(portrait["vertical_suitability"], landscape["vertical_suitability"])
        self.assertGreater(landscape["vertical_suitability"], 0)

    def test_emotion_and_controlled_category_signals(self):
        joyful = score_media(media(mood="joyful", category="landmark"), "photo", ScoringConfig(), {})
        neutral = score_media(media(mood="neutral", category="other"), "photo", ScoringConfig(), {})
        self.assertGreater(joyful["emotion"], neutral["emotion"])
        self.assertGreater(joyful["travel_relevance"], neutral["travel_relevance"])

    def test_trip_relative_uniqueness(self):
        counts = Counter({"street": 9, "food": 1})
        scenes = Counter({"street": 9, "restaurant": 1})
        common = score_media(media(category="street"), "photo", ScoringConfig(), {}, counts, scenes, 10)
        rare_item = media(category="food"); rare_item["vision"]["scene_type"] = "restaurant"
        rare = score_media(rare_item, "photo", ScoringConfig(), {}, counts, scenes, 10)
        self.assertGreater(rare["uniqueness"], common["uniqueness"])


if __name__ == "__main__":
    unittest.main()
