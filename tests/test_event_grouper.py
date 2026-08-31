"""Sprint 7.5 deterministic Event / Scene Intelligence tests."""
import copy
import unittest

from travel_reel.config import EventConfig
from travel_reel.events import coherence_metrics, event_similarity, group_manifest_events


def media(media_id, filename, category, *, scene="outdoor", activity="tourism", words=None, captured=None):
    words = words or [category]
    return {"id": media_id, "path": filename, "captured_at": captured, "score": {"version": "1.0", "total": 80},
            "vision": {"travel_category": category, "scene_type": scene, "activity": activity,
                       "description": " ".join(words), "tags": words, "objects": words,
                       "mood": "neutral", "people": {"visible": False, "group_photo": False, "selfie": False},
                       "landmark_hint": {"name": None, "confidence": None}}}


def manifest(items):
    return {"trip": {}, "photos": [x for x in items if x["id"].startswith("photo-")],
            "videos": [x for x in items if x["id"].startswith("video-")], "story": {"keep": True}}


class EventGrouperTests(unittest.TestCase):
    def test_filename_plus_semantics_merges_mixed_media_deterministically(self):
        items = [media("photo-a", "Photos/IMG_0245.JPG", "landmark", words=["gothic", "church"]),
                 media("video-b", "Videos/IMG_0248.MOV", "cityscape", scene="indoor", activity="worship", words=["gothic", "church", "stained"])]
        first = manifest(copy.deepcopy(items)); second = manifest(copy.deepcopy(items))
        self.assertEqual(group_manifest_events(first, EventConfig()), group_manifest_events(second, EventConfig()))
        self.assertEqual(len(first["events"]["items"]), 1)
        self.assertEqual(first["events"]["items"][0]["media_mix"], {"photos": 1, "videos": 1})
        self.assertEqual(set(first["events"]["items"][0]["media_ids"]), {"photo-a", "video-b"})

    def test_filename_proximity_alone_does_not_merge_incompatible_media(self):
        value = manifest([media("photo-a", "Photos/IMG_0100.JPG", "food", words=["restaurant", "meal"]),
                          media("photo-b", "Photos/IMG_0101.JPG", "transportation", scene="station", activity="waiting", words=["train", "platform"])])
        group_manifest_events(value, EventConfig())
        self.assertEqual(len(value["events"]["items"]), 2)

    def test_large_time_gap_splits_same_generic_category(self):
        value = manifest([media("video-a", "Videos/A.MOV", "street", words=["urban", "street"], captured="2026-01-01T10:00:00"),
                          media("video-b", "Videos/B.MOV", "street", words=["urban", "street"], captured="2026-01-04T10:00:00")])
        group_manifest_events(value, EventConfig())
        self.assertEqual(len(value["events"]["items"]), 2)

    def test_time_proximity_supports_semantic_grouping(self):
        value = manifest([media("video-a", "Videos/A.MOV", "theme_park", activity="ride", words=["amusement", "ride"], captured="2026-01-01T10:00:00"),
                          media("video-b", "Videos/B.MOV", "theme_park", activity="ride", words=["amusement", "ride"], captured="2026-01-01T10:10:00")])
        group_manifest_events(value, EventConfig())
        self.assertEqual(len(value["events"]["items"]), 1)

    def test_stable_ids_order_roles_and_media_preservation(self):
        items = [media("photo-2", "Photos/IMG_002.JPG", "theme_park", words=["amusement", "ride"]),
                 media("video-3", "Videos/IMG_003.MOV", "theme_park", activity="ride", words=["amusement", "ride"]),
                 media("photo-1", "Photos/IMG_001.JPG", "food", scene="restaurant", activity="eating", words=["restaurant", "meal"])]
        value = manifest(copy.deepcopy(items)); state = group_manifest_events(value, EventConfig())
        self.assertEqual({mid for event in state["items"] for mid in event["media_ids"]}, {x["id"] for x in items})
        self.assertEqual([event["event_id"] for event in state["items"]], ["event-001", "event-002"])
        self.assertTrue(all("scene_role" in x["event"] for x in value["photos"] + value["videos"]))

    def test_similarity_is_explainable_and_metrics_define_fragmentation(self):
        a = media("photo-a", "a.jpg", "theme_park", words=["amusement", "ride"])
        b = media("video-b", "b.mov", "theme_park", words=["amusement", "ride"])
        score, facts = event_similarity(a, b)
        self.assertGreater(score, 0); self.assertTrue(facts["category"]); self.assertTrue(facts["distinctive_overlap"])
        self.assertEqual(coherence_metrics(["A", "B", "A"]), {"event_switch_count": 2, "event_fragmentation_count": 1})
        self.assertEqual(coherence_metrics(["A", "B", "A"], "A")["event_fragmentation_count"], 0)


if __name__ == "__main__": unittest.main()
