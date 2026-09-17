"""Event-aware selection, Story, and Planner regression tests."""
import copy
import unittest
from travel_reel.config import PlannerConfig, SelectionConfig, StoryConfig
from travel_reel.events import coherence_metrics
from travel_reel.planner import build_reel_plan
from travel_reel.selector import select_manifest
from travel_reel.story import build_story, validate_story

def item(index, event_id, category, kind="photo", score=80):
    media_id = f"{kind}-{index:02d}"
    return {"id": media_id, "path": f"Media/{media_id}.{'mov' if kind == 'video' else 'jpg'}",
            "duration": 8.0 if kind == "video" else None, "captured_at": None,
            "event": {"event_id": event_id, "ordinal": index + 1, "scene_role": "motion" if kind == "video" else "activity"},
            "vision": {"travel_category": category, "scene_type": "outdoor", "activity": "tourism",
                       "description": f"{category} distinct scene {index}", "tags": [category, str(index)], "objects": [category, str(index)],
                       "mood": "neutral", "people": {"visible": False, "selfie": False, "group_photo": False},
                       "landmark_hint": {"name": None, "confidence": None}, "vision_metadata": {}},
            "score": {"version": "1.0", "total": score, "story_value": score, "emotion": 70, "uniqueness": 70}}

def event_manifest():
    values, events, index = [], [], 0
    for event_id, category, count in [("event-001", "transportation", 3), ("event-002", "landmark", 6), ("event-003", "theme_park", 7), ("event-004", "food", 4)]:
        ids = []
        for offset in range(count):
            kind = "video" if offset == 1 else "photo"
            values.append(item(index, event_id, category, kind, 75 + index)); ids.append(values[-1]["id"]); index += 1
        events.append({"event_id": event_id, "label": category, "dominant_category": category, "media_ids": ids})
    return {"manifest_version": "1.6", "trip": {"name": "Events"},
            "photos": [x for x in values if x["id"].startswith("photo-")], "videos": [x for x in values if x["id"].startswith("video-")],
            "events": {"version": "1.0", "items": events}, "story": {}, "timeline": {}, "render": {}}

class EventIntegrationTests(unittest.TestCase):
    def test_selection_preserves_event_diversity(self):
        manifest = event_manifest(); selection = select_manifest(manifest, SelectionConfig(primary_target=8, alternate_target=4, min_video_target=2, max_video_target=4, duplicate_similarity_without_time=.9))
        by_id = {x["id"]: x for x in manifest["photos"] + manifest["videos"]}
        self.assertEqual({by_id[mid]["event"]["event_id"] for mid in selection["primary_ids"]}, {"event-001", "event-002", "event-003", "event-004"})

    def test_story_and_planner_keep_event_blocks_with_hook_exception(self):
        manifest = event_manifest(); select_manifest(manifest, SelectionConfig(primary_target=18, alternate_target=2, min_video_target=3, max_video_target=4, duplicate_similarity_without_time=.9))
        story = build_story(manifest, StoryConfig(max_story_items=20)); validate_story(story, manifest)
        manifest["story"] = story
        manifest["music_analysis"] = {"version": "1.0", "duration_seconds": 45.0,
            "source": {"cache_key": "event-music"}, "tempo": {"bpm": 120},
            "duration_alignment": {"music_aligned_duration": 40.0},
            "beats": [{"time": value+.05} for value in range(2, 40, 2)],
            "phrases": [{"start": 0.0, "end": 45.0}], "sync_anchors": [], "story_mapping": []}
        self.assertLess(story["summary"]["section_count"], story["summary"]["item_count"])
        self.assertLessEqual(story["summary"]["section_count"], 6)
        self.assertEqual(coherence_metrics([e["event_id"] for e in story["sequence"]], story.get("hook_teaser_event_id"))["event_fragmentation_count"], 0)
        plan = build_reel_plan(manifest, PlannerConfig(min_shots=12, max_shots=18))
        self.assertEqual(plan["summary"]["event_fragmentation_count"], 0)
        self.assertEqual({s["event_id"] for s in plan["shots"]}, {"event-001", "event-002", "event-003", "event-004"})

    def test_rerun_determinism_and_small_trip(self):
        manifest = event_manifest(); select_manifest(manifest, SelectionConfig(primary_target=4, alternate_target=0, min_video_target=0, max_video_target=2, duplicate_similarity_without_time=.9))
        first = build_story(manifest, StoryConfig(min_story_items=2, max_story_items=4))
        self.assertEqual(first, build_story(copy.deepcopy(manifest), StoryConfig(min_story_items=2, max_story_items=4)))

if __name__ == "__main__": unittest.main()
