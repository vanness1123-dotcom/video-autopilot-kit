import copy
import json
import tempfile
import unittest
from pathlib import Path

from travel_reel.config import CreativeDirectorConfig, SelectionConfig
from travel_reel.director import DirectorPrerequisiteError, build_content_profile, build_creative_direction
from travel_reel.pipeline import run_director
from travel_reel.selector import select_manifest
from travel_reel.cli import main


def media(mid, event, score=75, category="landmark", video=False, duplicate=None):
    vision={"description":f"{category} scene {mid}","tags":[category],"objects":[category],"travel_category":category,
            "scene_type":"outdoor","activity":"visiting" if category=="activity" else None,
            "people":{"visible":category=="people","selfie":False,"group_photo":False}}
    if duplicate: vision["vision_metadata"]={"source_fingerprint":duplicate}
    return {"id":mid,"path":mid+('.mp4' if video else '.jpg'),"score":{"version":"1.0","total":score},"vision":vision,
            "event":{"event_id":event,"ordinal":1,"scene_role":"motion" if video else "establishing"}}

def manifest():
    photos=[media(f"photo-{i:03}","event-001" if i<5 else "event-002",88-i, "landmark" if i<5 else "activity",
                  duplicate="same" if 1<i<5 else None) for i in range(1,9)]
    videos=[media("video-001","event-002",84,"activity",True)]
    events={"version":"1.0","items":[
        {"event_id":"event-001","media_ids":[x["id"] for x in photos[:4]],"dominant_category":"landmark","scene_types":["outdoor"],"activities":[],"media_mix":{"photos":4,"videos":0},"evidence_score":.7},
        {"event_id":"event-002","media_ids":[x["id"] for x in photos[4:]]+["video-001"],"dominant_category":"activity","scene_types":["outdoor"],"activities":["visiting"],"media_mix":{"photos":4,"videos":1},"evidence_score":.8}]}
    return {"manifest_version":"1.6","trip":{"name":"trip"},"photos":photos,"videos":videos,"events":events}

def rich_manifest(count=48):
    categories = ("landmark", "activity", "food", "transportation", "theme_park", "nightlife")
    items, events = [], []
    for index in range(count):
        event_index = index % len(categories)
        category = categories[event_index]
        item = media(f"media-{index:03}", f"event-{event_index + 1:03}", 95 - index % 20,
                     category, video=index % 5 == 0)
        items.append(item)
    for event_index, category in enumerate(categories):
        event_items = [item for index, item in enumerate(items) if index % len(categories) == event_index]
        events.append({"event_id": f"event-{event_index + 1:03}",
                       "media_ids": [item["id"] for item in event_items],
                       "dominant_category": category, "scene_types": ["outdoor"],
                       "activities": ["visiting"] if category in {"activity", "theme_park"} else [],
                       "media_mix": {"photos": sum(not item["path"].endswith(".mp4") for item in event_items),
                                     "videos": sum(item["path"].endswith(".mp4") for item in event_items)},
                       "evidence_score": .8})
    return {"manifest_version": "1.6", "trip": {"name": "rich trip"},
            "photos": [item for item in items if item["path"].endswith(".jpg")],
            "videos": [item for item in items if item["path"].endswith(".mp4")],
            "events": {"version": "1.0", "items": events}}

class DirectorTests(unittest.TestCase):
    def test_prerequisite(self):
        with self.assertRaises(DirectorPrerequisiteError): build_creative_direction({"photos":[],"videos":[]}, CreativeDirectorConfig())

    def test_profile_and_auto_are_deterministic_without_mutating_evidence(self):
        original=manifest(); before=copy.deepcopy(original)
        first=build_creative_direction(original,CreativeDirectorConfig()); second=build_creative_direction(original,CreativeDirectorConfig())
        self.assertEqual(first,second); self.assertEqual(original,before)
        self.assertEqual(build_content_profile(original)["usable_scored_media_count"],9)

    def test_rich_inventory_style_overrides_are_deterministic_and_change_feasible_budgets(self):
        m=rich_manifest(); budgets=[]
        for style in ("cinematic_travel","travel_story","dynamic_travel_highlight","beat_montage"):
            config = CreativeDirectorConfig(style=style)
            d=build_creative_direction(m,config)
            self.assertEqual(d, build_creative_direction(copy.deepcopy(m), config))
            budgets.append(d["media_budget"]["target_shots"])
            self.assertLessEqual(budgets[-1],d["content_profile"]["editorial_capacity"])
        self.assertEqual(budgets,sorted(budgets)); self.assertGreater(len(set(budgets)),1)

    def test_constrained_inventory_may_clamp_styles_to_same_feasible_budget(self):
        m=manifest()
        budgets = [build_creative_direction(m, CreativeDirectorConfig(style=style))["media_budget"]["target_shots"]
                   for style in ("cinematic_travel", "travel_story", "dynamic_travel_highlight", "beat_montage")]
        self.assertEqual(budgets, [build_content_profile(m)["editorial_capacity"]] * 4)

    def test_small_trip_degrades_to_available_media(self):
        m=manifest(); m["photos"]=m["photos"][:1]; m["videos"]=[]
        m["events"]["items"]=m["events"]["items"][:1]; m["events"]["items"][0]["media_ids"]=[m["photos"][0]["id"]]
        d=build_creative_direction(m,CreativeDirectorConfig(style="beat_montage"))
        self.assertEqual(d["media_budget"]["target_shots"],1)
        self.assertLess(d["duration_strategy"]["resolved_seconds"], 30)
        self.assertIn("content_limited_below_configured_minimum", d["duration_strategy"]["rationale"])

    def test_rich_trip_is_longer_than_sparse_trip_and_respects_envelope(self):
        sparse = build_creative_direction(manifest(), CreativeDirectorConfig())
        rich = build_creative_direction(rich_manifest(), CreativeDirectorConfig())
        self.assertGreater(rich["duration_strategy"]["resolved_seconds"], sparse["duration_strategy"]["resolved_seconds"])
        self.assertGreaterEqual(rich["duration_strategy"]["resolved_seconds"], 30)
        self.assertLessEqual(rich["duration_strategy"]["resolved_seconds"], 90)
        self.assertTrue(rich["validation"]["target_feasible"])

    def test_duplicate_heavy_inventory_does_not_inflate_duration(self):
        rich = rich_manifest(80)
        for item in rich["photos"] + rich["videos"]:
            item["vision"].setdefault("vision_metadata", {})["source_fingerprint"] = "same"
        direction = build_creative_direction(rich, CreativeDirectorConfig())
        self.assertEqual(direction["content_profile"]["editorial_capacity"], 1)
        self.assertEqual(direction["media_budget"]["target_shots"], 1)

    def test_style_changes_breathing_without_breaking_feasibility(self):
        rich = rich_manifest()
        cinematic = build_creative_direction(rich, CreativeDirectorConfig(style="cinematic_travel"))
        montage = build_creative_direction(rich, CreativeDirectorConfig(style="beat_montage"))
        self.assertGreater(
            cinematic["duration_strategy"]["preferred_seconds"] / cinematic["media_budget"]["target_shots"],
            montage["duration_strategy"]["preferred_seconds"] / montage["media_budget"]["target_shots"],
        )
        self.assertTrue(montage["music_strategy"]["beat_driven"])

    def test_fixed_duration_is_deterministic_when_feasible(self):
        config = CreativeDirectorConfig(style="beat_montage", duration_mode="fixed", target_duration_seconds=40)
        first = build_creative_direction(rich_manifest(), config)
        self.assertEqual(first, build_creative_direction(rich_manifest(), config))
        self.assertEqual(first["duration_strategy"]["resolved_seconds"], 40)

    def test_adaptive_minimum_and_maximum_are_respected(self):
        rich = rich_manifest()
        lower = build_creative_direction(
            rich, CreativeDirectorConfig(style="beat_montage", min_duration_seconds=50)
        )
        capped = build_creative_direction(
            rich, CreativeDirectorConfig(style="beat_montage", max_duration_seconds=40)
        )
        self.assertGreaterEqual(lower["duration_strategy"]["resolved_seconds"], 50)
        self.assertLessEqual(capped["duration_strategy"]["resolved_seconds"], 40)

    def test_event_diversity_quality_and_video_capacity_affect_decision(self):
        rich = rich_manifest()
        one_event = copy.deepcopy(rich)
        all_ids = [item["id"] for item in one_event["photos"] + one_event["videos"]]
        one_event["events"]["items"] = [{"event_id": "event-001", "media_ids": all_ids,
            "dominant_category": "landmark", "media_mix": {"photos": 38, "videos": 10}}]
        diverse = build_creative_direction(rich, CreativeDirectorConfig(style="travel_story"))
        flat = build_creative_direction(one_event, CreativeDirectorConfig(style="travel_story"))
        self.assertGreater(diverse["media_budget"]["target_shots"], flat["media_budget"]["target_shots"])

        low_quality = copy.deepcopy(rich)
        for item in low_quality["photos"] + low_quality["videos"]:
            item["score"]["total"] = 60
        low = build_creative_direction(low_quality, CreativeDirectorConfig(style="travel_story"))
        self.assertGreater(diverse["media_budget"]["target_shots"], low["media_budget"]["target_shots"])

        no_video = copy.deepcopy(rich); no_video["photos"].extend(no_video.pop("videos"))
        stills = build_creative_direction(no_video, CreativeDirectorConfig(style="travel_story"))
        self.assertGreater(diverse["duration_strategy"]["preferred_seconds"], stills["duration_strategy"]["preferred_seconds"])

    def test_event_allocation_feasible_and_not_size_only(self):
        d=build_creative_direction(manifest(),CreativeDirectorConfig(style="travel_story")); strategy=d["event_strategy"]
        self.assertEqual(sum(x["target_representation"] for x in strategy.values()),d["media_budget"]["target_shots"])
        self.assertGreaterEqual(strategy["event-002"]["importance_score"],strategy["event-001"]["importance_score"])

    def test_selection_consumes_budget_and_reports_duplicate_shortfall(self):
        m=manifest(); m["creative_direction"]=build_creative_direction(m,CreativeDirectorConfig(style="beat_montage"))
        m["creative_direction"]["event_strategy"]["event-001"]["target_representation"]=4
        selection=select_manifest(m,SelectionConfig())
        self.assertEqual(selection["summary"]["primary_count"],selection["target_primary"])
        self.assertTrue(selection["creative_direction"]["consumed"])
        self.assertTrue(any(x["event_id"]=="event-001" for x in selection["creative_direction"]["event_target_shortfalls"]))
        floor = m["creative_direction"]["media_budget"]["minimum_score"]
        by_id = {item["id"]: item for item in m["photos"] + m["videos"]}
        self.assertTrue(all(by_id[mid]["score"]["total"] >= floor for mid in selection["primary_ids"]))

    def test_pipeline_persists_and_invalidates_only_downstream(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"output").mkdir(); m=manifest(); m.update(selection={},story={},reel_plan={},render={})
            (root/"output"/"trip_manifest.json").write_text(json.dumps(m),encoding="utf-8")
            run_director(root,CreativeDirectorConfig())
            saved=json.loads((root/"output"/"trip_manifest.json").read_text())
            self.assertIn("creative_direction",saved); self.assertIn("events",saved); self.assertIn("vision",saved["photos"][0])
            for key in ("selection","story","reel_plan","render"): self.assertNotIn(key,saved)

    def test_cli_prerequisite_message_path(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); (root/"output").mkdir()
            (root/"output"/"trip_manifest.json").write_text(json.dumps({"trip":{},"photos":[],"videos":[]}),encoding="utf-8")
            self.assertEqual(main(["direct",str(root)]),2)

if __name__ == "__main__": unittest.main()
