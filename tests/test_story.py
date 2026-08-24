"""Deterministic Story Engine narrative and validation tests."""
import copy
import unittest

from travel_reel.config import StoryConfig
from travel_reel.story import STORY_ROLES, StoryPrerequisiteError, StoryValidationError, build_story, validate_story


def candidate(
    media_id, category="street", *, total=80, story_value=80, emotion=70,
    uniqueness=70, roles=None, mood="neutral", scene=None, captured=None,
):
    return {
        "id": media_id,
        "path": f"Media/{media_id}.jpg",
        "captured_at": captured,
        "vision": {
            "description": f"Visible {category} travel scene",
            "tags": [category], "objects": [category], "travel_category": category,
            "scene_type": scene or ("station" if category == "transportation" else "street"),
            "activity": "riding" if category in {"activity", "theme_park"} else None,
            "mood": mood,
            "people": {"visible": category in {"activity", "theme_park", "group"}, "selfie": False, "group_photo": category == "group"},
            "landmark_hint": {"name": None, "confidence": None},
        },
        "score": {
            "total": total, "story_value": story_value, "emotion": emotion,
            "uniqueness": uniqueness, "version": "1.0",
        },
        "selection": {
            "status": "primary", "candidate_roles": roles or [], "version": "1.0",
        },
        "selected": True,
    }


def story_manifest(primary, alternates=None):
    alternates = alternates or []
    for item in alternates:
        item["selection"]["status"] = "alternate"; item["selected"] = False
    items = [*primary, *alternates]
    return {
        "manifest_version": "1.2", "trip": {"name": "Fixture Trip"},
        "photos": [copy.deepcopy(item) for item in items if item["id"].startswith("photo-")],
        "videos": [copy.deepcopy(item) for item in items if item["id"].startswith("video-")],
        "selection": {
            "version": "1.0", "primary_ids": [item["id"] for item in primary],
            "alternate_ids": [item["id"] for item in alternates],
        },
        "story": {}, "timeline": {"keep": True}, "render": {"keep": True},
    }


def standard_candidates():
    return [
        candidate("video-hook", "theme_park", total=96, story_value=95, emotion=92, roles=["hook_candidate", "activity"]),
        candidate("photo-arrival", "transportation", roles=["hook_candidate", "transition"]),
        candidate("photo-street", "street", roles=["establishing"]),
        candidate("photo-food", "food", story_value=86, roles=["food"]),
        candidate("photo-activity", "activity", story_value=90, emotion=88, roles=["activity"]),
        candidate("photo-landmark", "landmark", story_value=92, roles=["hook_candidate", "establishing", "landmark"]),
        candidate("photo-close", "cityscape", mood="calm", roles=["closing_candidate", "establishing"]),
    ]


class StoryTests(unittest.TestCase):
    def test_prerequisite_validation(self):
        with self.assertRaisesRegex(StoryPrerequisiteError, "Run 'select' first"):
            build_story({"photos": [], "videos": []}, StoryConfig())

    def test_config_validation(self):
        with self.assertRaises(ValueError): StoryConfig(min_story_items=8, max_story_items=4)
        with self.assertRaises(ValueError): StoryConfig(chronology_min_ratio=1.5)

    def test_strong_hook_closing_sections_and_controlled_roles(self):
        manifest = story_manifest(standard_candidates())
        story = build_story(manifest, StoryConfig(max_story_items=10))
        validate_story(story, manifest)
        self.assertEqual(story["hook_media_id"], "video-hook")
        self.assertEqual(story["closing_media_id"], "photo-close")
        self.assertEqual(story["structure"][0], "hook")
        self.assertEqual(story["structure"][-1], "closing")
        self.assertIn("highlight", story["structure"])
        highlight_scene = next(scene for scene in story["scenes"] if scene["role"] == "highlight")
        self.assertEqual(story["highlight_media_ids"], highlight_scene["media_ids"])
        self.assertTrue(all(entry["editorial_role"] in STORY_ROLES for entry in story["sequence"]))

    def test_static_group_photo_does_not_displace_comparable_motion_hook(self):
        group = candidate("photo-group", "landmark", total=92, story_value=92, emotion=90, roles=["hook_candidate"])
        group["vision"]["people"]["group_photo"] = True
        motion = candidate("video-motion", "landmark", total=91, story_value=91, emotion=85, roles=["hook_candidate", "activity"])
        closing = candidate("photo-close", "cityscape", roles=["closing_candidate"])
        story = build_story(story_manifest([group, motion, closing]), StoryConfig(min_story_items=2))
        self.assertEqual(story["hook_media_id"], "video-motion")

    def test_section_assignment_and_category_diversity(self):
        story = build_story(story_manifest(standard_candidates()), StoryConfig(max_story_items=10))
        sections = {scene["role"]: scene for scene in story["scenes"]}
        self.assertIn("arrival", sections)
        self.assertIn("exploration", sections)
        self.assertIn("experience", sections)
        self.assertGreaterEqual(len(story["summary"]["categories"]), 5)

    def test_chronology_when_reliable_within_section(self):
        primary = standard_candidates()
        primary.extend([
            candidate("photo-z", "shopping", captured="2026-01-03T10:00:00"),
            candidate("photo-a", "shopping", captured="2026-01-01T10:00:00"),
            candidate("photo-m", "shopping", captured="2026-01-02T10:00:00"),
        ])
        story = build_story(story_manifest(primary), StoryConfig(max_story_items=12, chronology_min_ratio=0.6))
        exploration = next(scene for scene in story["scenes"] if scene["role"] == "exploration")
        shopping = [media_id for media_id in exploration["media_ids"] if media_id in {"photo-a", "photo-m", "photo-z"}]
        self.assertEqual(shopping, ["photo-a", "photo-m", "photo-z"])

    def test_missing_timestamp_fallback_is_deterministic(self):
        manifest = story_manifest(standard_candidates())
        self.assertEqual(build_story(manifest, StoryConfig()), build_story(copy.deepcopy(manifest), StoryConfig()))

    def test_primary_preferred_and_no_unnecessary_alternate(self):
        alternate = candidate("photo-alt", "nightlife", total=99, roles=["closing_candidate"])
        story = build_story(story_manifest(standard_candidates(), [alternate]), StoryConfig(max_story_items=10))
        self.assertEqual(story["alternate_uses"], [])
        self.assertNotIn("photo-alt", [entry["media_id"] for entry in story["sequence"]])

    def test_alternate_used_only_for_missing_role(self):
        primary = [
            candidate("video-hook", "theme_park", roles=["hook_candidate", "activity"]),
            candidate("photo-context", "street", roles=["establishing"]),
            candidate("photo-food", "food", roles=["food"]),
            candidate("photo-detail", "detail", roles=["detail"]),
        ]
        alternate = candidate("photo-alt-close", "cityscape", mood="calm", roles=["closing_candidate"])
        story = build_story(story_manifest(primary, [alternate]), StoryConfig(max_story_items=5, max_alternates=1))
        self.assertEqual(story["alternate_uses"], [{"media_id": "photo-alt-close", "reason": "alternate_used:missing_closing_candidate"}])
        self.assertEqual(story["closing_media_id"], "photo-alt-close")

    def test_small_trip_degrades_without_empty_sections_or_reuse(self):
        primary = [
            candidate("photo-open", "landmark", roles=["hook_candidate", "establishing"]),
            candidate("photo-close", "cityscape", mood="calm", roles=["closing_candidate"]),
        ]
        manifest = story_manifest(primary)
        story = build_story(manifest, StoryConfig(min_story_items=2, max_story_items=4))
        validate_story(story, manifest)
        ids = [entry["media_id"] for entry in story["sequence"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(scene["media_ids"] for scene in story["scenes"]))

    def test_validation_rejects_unknown_and_reused_media(self):
        manifest = story_manifest(standard_candidates())
        story = build_story(manifest, StoryConfig(max_story_items=10))
        unknown = copy.deepcopy(story)
        unknown["sequence"][0]["media_id"] = "photo-unknown"
        with self.assertRaisesRegex(StoryValidationError, "unknown media ID"):
            validate_story(unknown, manifest)
        reused = copy.deepcopy(story)
        reused["sequence"][1]["media_id"] = reused["sequence"][0]["media_id"]
        with self.assertRaisesRegex(StoryValidationError, "reuse media"):
            validate_story(reused, manifest)


if __name__ == "__main__":
    unittest.main()
