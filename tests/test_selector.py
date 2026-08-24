"""Duplicate and diversity-aware selector tests."""
import copy
import unittest

from travel_reel.config import SelectionConfig
from travel_reel.selector import group_duplicates, select_manifest


def candidate(media_id, score, category="street", scene="street", *, video=False, selfie=False, people=False, description=None, captured="2026-01-01T10:00:00"):
    return {
        "id": media_id, "captured_at": captured, "selected": False,
        "score": {"total": score, "version": "1.0"},
        "vision": {
            "description": description or f"Unique view {media_id}", "tags": [media_id, category],
            "objects": [media_id], "travel_category": category, "scene_type": scene,
            "activity": "walking" if video else None, "mood": "neutral",
            "people": {"visible": people or selfie, "selfie": selfie, "group_photo": False},
            "landmark_hint": {"name": None}, "vision_metadata": {"source_fingerprint": media_id},
        },
        "_media_type": "video" if video else "photo",
    }


def manifest(items):
    payload = {"manifest_version": "1.1", "photos": [], "videos": [], "story": {"keep": True}, "timeline": {}, "render": {}}
    for item in items:
        clean = copy.deepcopy(item); clean.pop("_media_type", None)
        payload["videos" if item["_media_type"] == "video" else "photos"].append(clean)
    return payload


class SelectorTests(unittest.TestCase):
    def test_duplicate_group_retains_stronger_representative(self):
        first = candidate("photo-a", 91, description="Busy market street with red signs")
        second = candidate("photo-b", 72, description="Busy market street with red signs")
        for item in (first, second):
            item["vision"]["tags"] = ["market", "street", "red_signs"]
            item["vision"]["objects"] = ["market", "signs", "people"]
        groups, suppressed = group_duplicates([first, second], SelectionConfig(duplicate_similarity=0.6))
        self.assertEqual(len(groups), 1)
        self.assertEqual(suppressed["photo-b"], "photo-a")

    def test_no_timestamp_semantic_burst_is_grouped(self):
        first = candidate("photo-a", 70, description="Group posing in a restaurant kitchen", captured=None)
        second = candidate("photo-b", 90, description="Group posing in a restaurant kitchen", captured=None)
        for item in (first, second):
            item["vision"]["tags"] = ["group", "restaurant", "kitchen"]
            item["vision"]["objects"] = ["people", "pans", "kitchen"]
        groups, suppressed = group_duplicates([first, second], SelectionConfig())
        self.assertEqual(len(groups), 1)
        self.assertEqual(suppressed["photo-a"], "photo-b")

    def test_targets_media_mix_caps_and_category_diversity(self):
        items = []
        categories = ["street", "street", "street", "food", "landmark", "nature", "cafe", "activity"]
        for index, category in enumerate(categories):
            items.append(candidate(f"photo-{index}", 95 - index, category, selfie=index < 3, people=index < 5, captured=None))
        for index in range(3):
            items.append(candidate(f"video-{index}", 70 - index, "transportation" if index == 0 else "activity", video=True, captured=None))
        payload = manifest(items)
        config = SelectionConfig(primary_target=6, alternate_target=2, min_video_target=2, max_video_target=3)
        result = select_manifest(payload, config)
        summary = result["summary"]
        self.assertEqual(len(result["primary_ids"]), 6)
        self.assertEqual(len(result["alternate_ids"]), 2)
        self.assertGreaterEqual(summary["videos"], 2)
        self.assertLessEqual(summary["selfies"], 2)
        self.assertGreaterEqual(len(summary["categories"]), 3)

    def test_deterministic_selection_and_id_preservation(self):
        items = [candidate(f"photo-{i}", 80 - i, ["street", "food", "nature"][i % 3], captured=None) for i in range(8)]
        first = manifest(items); second = copy.deepcopy(first)
        config = SelectionConfig(primary_target=4, alternate_target=2, min_video_target=0, max_video_target=0)
        expected_ids = [item["id"] for item in first["photos"]]
        self.assertEqual(select_manifest(first, config), select_manifest(second, config))
        self.assertEqual([item["id"] for item in first["photos"]], expected_ids)
        self.assertEqual(first["story"], {"keep": True})

    def test_small_trip_degrades_gracefully(self):
        payload = manifest([candidate("photo-a", 80), candidate("video-a", 70, video=True)])
        result = select_manifest(payload, SelectionConfig(primary_target=20, alternate_target=10, min_video_target=4, max_video_target=8))
        self.assertEqual(len(result["primary_ids"]), 2)
        self.assertEqual(result["alternate_ids"], [])


if __name__ == "__main__":
    unittest.main()
