"""Sprint 11.1 dynamic template contracts and resolver tests."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_reel.config import TemplateConfig
from travel_reel.pipeline import run_template_planner
from travel_reel.templates import (TemplateValidationError, get_builtin_template, resolve_visual_plan,
                                   travel_daily_record_v1, validate_template_definition, validate_visual_plan)


def manifest(count=18,duration=30.0,media="mixed",music=True):
    phases=("hook","exploration","experience","highlight","closing"); shots=[]; cursor=0.0
    for i in range(count):
        end=duration if i==count-1 else round(duration*(i+1)/count,3)
        kind="photo" if media=="photo" else "video" if media=="video" else "video" if i%5==0 else "photo"
        phase=phases[min(4,i*5//count)]
        shots.append({"shot_id":f"shot-{i+1:03d}","shot_index":i+1,"media_id":f"media-{i:03d}","media_type":kind,
                      "story_section":phase,"event_id":f"event-{i//4:02d}","timeline_start_seconds":cursor,
                      "timeline_end_seconds":end,"planned_duration_seconds":round(end-cursor,3)})
        cursor=end
    reel={"actual_duration_seconds":duration,"shots":shots,"aspect_ratio":"9:16"}
    if music: reel["music_intelligence"]={"sync_anchors":[{"time":round(i*.5,3)} for i in range(int(duration*2)+1)]}
    return {"manifest_version":"1.7","trip":{},"photos":[],"videos":[],"events":{"keep":True},
            "creative_direction":{"keep":True},"selection":{"keep":True},"story":{"keep":True},
            "music_analysis":{"keep":True},"reel_plan":reel,"render":{"old":True}}


def add_affinity_media(source, *, strong):
    source["photos"]=[]; source["videos"]=[]
    for index,shot in enumerate(source["reel_plan"]["shots"]):
        shared=strong or index%2==0
        vision={"travel_category":"food" if shared else "cityscape",
                "activity":"eating" if shared else "walking",
                "scene_type":"indoor" if shared else "outdoor",
                "mood":"joyful" if shared else "neutral",
                "tags":["market","family"] if shared else [f"unrelated-{index}"],
                "landmark_hint":{"name":"Market" if shared else None}}
        item={"id":shot["media_id"],"vision":vision,"captured_at":f"2026-07-24T10:{index:02d}:00+00:00"}
        source["photos" if shot["media_type"]=="photo" else "videos"].append(item)
    return source


class TemplateTests(unittest.TestCase):
    def test_builtin_loads_and_is_adaptive(self):
        value=get_builtin_template("travel_daily_record_v1")
        self.assertEqual(value["template_schema_version"],"1.0")
        self.assertEqual(value["adaptation_rules"]["duration_mode"],"consume_reel_plan")
        self.assertNotIn("17",json.dumps(value))

    def test_block_vocabulary_complete(self):
        kinds={x["block_type"] for x in travel_daily_record_v1()["block_library"]}
        self.assertEqual(kinds,{"fullscreen_media","hero_media","two_up","three_up","grid","collage",
                                "layered_cards","beat_montage","title_card","closing_card"})

    def test_geometry_valid_and_invalid_rejected(self):
        value=travel_daily_record_v1(); validate_template_definition(value)
        value["block_library"][0]["layout"]["slots"][0]["width"]=1.1
        with self.assertRaisesRegex(TemplateValidationError,"geometry"): validate_template_definition(value)

    def test_unknown_block_motion_transition_and_version_rejected(self):
        for path,value,message in (("block_type","unknown","Unknown visual"),("motion","warp","Unsupported motion"),
                                   ("transition","wipe","Unsupported transition")):
            definition=travel_daily_record_v1()
            if path=="block_type": definition["block_library"][0][path]=value
            else: definition["block_library"][0][path]["type"]=value
            with self.assertRaisesRegex(TemplateValidationError,message): validate_template_definition(definition)
        definition=travel_daily_record_v1(); definition["template_schema_version"]="99"
        with self.assertRaisesRegex(TemplateValidationError,"version"): validate_template_definition(definition)

    def test_unknown_template_rejected(self):
        with self.assertRaisesRegex(TemplateValidationError,"Unknown template"): get_builtin_template("missing")

    def test_deterministic_resolution_and_traceability(self):
        source=manifest(); definition=travel_daily_record_v1()
        first=resolve_visual_plan(source,definition); second=resolve_visual_plan(copy.deepcopy(source),travel_daily_record_v1())
        self.assertEqual(first,second)
        self.assertEqual([x["shot_id"] for x in first["shot_assignments"]],
                         [x["shot_id"] for x in source["reel_plan"]["shots"]])

    def test_duration_independent_30_56_90(self):
        for duration in (30.0,56.0,90.0):
            result=resolve_visual_plan(manifest(39,duration),travel_daily_record_v1())
            self.assertEqual(result["duration_seconds"],duration)
            self.assertEqual(result["blocks"][-1]["timeline_end_seconds"],duration)

    def test_photo_video_and_mixed_media(self):
        for media in ("photo","video","mixed"):
            result=resolve_visual_plan(manifest(media=media),travel_daily_record_v1())
            self.assertEqual(result["validation"]["assigned_shot_count"],18)

    def test_no_music_and_beat_aware_modes(self):
        quiet=resolve_visual_plan(manifest(music=False),travel_daily_record_v1())
        beat=resolve_visual_plan(manifest(music=True),travel_daily_record_v1())
        self.assertEqual(quiet["validation"]["beat_aware_block_count"],0)
        self.assertGreater(beat["validation"]["beat_aware_block_count"],0)

    def test_phase_adaptation_and_closing(self):
        result=resolve_visual_plan(manifest(),travel_daily_record_v1()); by_phase={}
        for block in result["blocks"]: by_phase.setdefault(block["story_phase"],set()).add(block["block_type"])
        self.assertTrue(by_phase["hook"] & {"hero_media","fullscreen_media","title_card"})
        self.assertTrue(by_phase["exploration"] & {"two_up","three_up","grid","collage"})
        self.assertIn(result["blocks"][-1]["block_type"],{"closing_card","layered_cards","hero_media"})

    def test_event_aware_grouping(self):
        result=resolve_visual_plan(manifest(),travel_daily_record_v1())
        multi=[block for block in result["blocks"] if len(block["shot_ids"])>1]
        self.assertTrue(multi)
        self.assertTrue(any(len(block["event_ids"])==1 for block in multi))

    def test_fragmented_events_do_not_disable_phase_multi_layouts(self):
        source=add_affinity_media(manifest(24,56,"photo"),strong=True)
        for index,shot in enumerate(source["reel_plan"]["shots"]): shot["event_id"]=f"event-{index:03d}"
        result=resolve_visual_plan(source,travel_daily_record_v1())
        multi_types={block["block_type"] for block in result["blocks"] if len(block["shot_ids"])>1}
        self.assertTrue(multi_types & {"two_up","three_up","grid","collage","layered_cards","beat_montage"})
        self.assertEqual(result["validation"]["assigned_shot_count"],24)

    def test_weak_affinity_cross_event_and_phase_alone_remain_separate(self):
        source=add_affinity_media(manifest(20,30,"photo"),strong=False)
        for index,shot in enumerate(source["reel_plan"]["shots"]): shot["event_id"]=f"event-{index:03d}"
        result=resolve_visual_plan(source,travel_daily_record_v1())
        self.assertFalse(any(block["editorial_affinity"]["cross_event"] for block in result["blocks"] if len(block["shot_ids"])>1))

    def test_strong_affinity_cross_event_may_group_with_reasons(self):
        source=add_affinity_media(manifest(20,30,"photo"),strong=True)
        for index,shot in enumerate(source["reel_plan"]["shots"]): shot["event_id"]=f"event-{index:03d}"
        result=resolve_visual_plan(source,travel_daily_record_v1())
        cross=[block for block in result["blocks"] if block["editorial_affinity"]["cross_event"]]
        self.assertTrue(cross)
        self.assertTrue(all("cross_event_affinity_threshold_met" in block["editorial_affinity"]["reasons"] for block in cross))
        self.assertTrue(all("strong_semantic_evidence" in block["editorial_affinity"]["reasons"] for block in cross))

    def test_same_event_multi_is_preferred_when_feasible(self):
        source=manifest(2,4,"photo",music=False)
        for shot in source["reel_plan"]["shots"]: shot["story_section"]="exploration"; shot["event_id"]="event-shared"
        result=resolve_visual_plan(source,travel_daily_record_v1())
        self.assertEqual(len(result["blocks"]),1)
        self.assertEqual(result["blocks"][0]["editorial_affinity"],
                         {"score":100.0,"reasons":["same_event"],"cross_event":False})

    def test_same_event_multi_is_not_forced_across_incompatible_media(self):
        source=manifest(2,4,"mixed",music=False)
        source["reel_plan"]["shots"][0]["media_type"]="photo"
        source["reel_plan"]["shots"][1]["media_type"]="video"
        for shot in source["reel_plan"]["shots"]: shot["story_section"]="exploration"; shot["event_id"]="event-shared"
        result=resolve_visual_plan(source,travel_daily_record_v1())
        self.assertEqual([len(block["shot_ids"]) for block in result["blocks"]],[1,1])

    def test_rich_exploration_has_meaningful_multi_layout_diversity(self):
        source=add_affinity_media(manifest(24,56,"photo"),strong=True)
        for shot in source["reel_plan"]["shots"]: shot["story_section"]="exploration"; shot["event_id"]="event-shared"
        result=resolve_visual_plan(source,travel_daily_record_v1())
        multi_types={block["block_type"] for block in result["blocks"] if len(block["shot_ids"])>1}
        self.assertIn("three_up",multi_types)
        self.assertGreaterEqual(len(multi_types),3)

    def test_layered_cards_can_independently_become_eligible_and_win(self):
        source=add_affinity_media(manifest(3,6,"photo",music=False),strong=True)
        for shot in source["reel_plan"]["shots"]: shot["story_section"]="experience"; shot["event_id"]="event-shared"
        definition=travel_daily_record_v1()
        definition["sequencing_rules"]["phase_preferences"]["experience"]=["layered_cards"]
        result=resolve_visual_plan(source,definition)
        self.assertEqual(result["blocks"][0]["block_type"],"layered_cards")
        self.assertEqual(result["blocks"][0]["shot_ids"],["shot-001","shot-002","shot-003"])

    def test_three_up_can_independently_become_eligible_and_win(self):
        source=add_affinity_media(manifest(3,6,"photo",music=False),strong=True)
        for shot in source["reel_plan"]["shots"]: shot["story_section"]="exploration"; shot["event_id"]="event-shared"
        definition=travel_daily_record_v1()
        definition["sequencing_rules"]["phase_preferences"]["exploration"]=["three_up"]
        result=resolve_visual_plan(source,definition)
        self.assertEqual(result["blocks"][0]["block_type"],"three_up")
        self.assertEqual(result["blocks"][0]["shot_ids"],["shot-001","shot-002","shot-003"])

    def test_generic_mood_does_not_promote_category_only_cross_event_grouping(self):
        for mood in ("neutral","calm"):
            source=manifest(2,4,"photo",music=False)
            source["photos"]=[]
            for index,shot in enumerate(source["reel_plan"]["shots"]):
                shot["story_section"]="exploration"; shot["event_id"]=f"event-{index}"
                source["photos"].append({"id":shot["media_id"],"vision":{
                    "travel_category":"landmark","activity":f"activity-{index}",
                    "scene_type":f"scene-{index}","mood":mood,"tags":[]}})
            result=resolve_visual_plan(source,travel_daily_record_v1())
            self.assertFalse(any(len(block["shot_ids"])>1 for block in result["blocks"]))

    def test_beat_montage_wins_with_fast_pacing_and_anchor_support(self):
        source=add_affinity_media(manifest(12,30,"mixed",music=True),strong=True)
        source["creative_direction"]={"pacing":{"overall":"fast"}}
        for shot in source["reel_plan"]["shots"]: shot["story_section"]="highlight"; shot["event_id"]="event-shared"
        result=resolve_visual_plan(source,travel_daily_record_v1())
        self.assertIn("beat_montage",{block["block_type"] for block in result["blocks"]})

    def test_beat_montage_does_not_override_weak_cross_event_affinity(self):
        source=manifest(4,8,"photo",music=True)
        source["creative_direction"]={"pacing":{"overall":"fast"}}; source["photos"]=[]
        for index,shot in enumerate(source["reel_plan"]["shots"]):
            shot["story_section"]="highlight"; shot["event_id"]=f"event-{index}"
            source["photos"].append({"id":shot["media_id"],"vision":{
                "travel_category":"cityscape","activity":f"activity-{index}",
                "scene_type":f"scene-{index}","mood":"neutral","tags":[]}})
        result=resolve_visual_plan(source,travel_daily_record_v1())
        self.assertNotIn("beat_montage",{block["block_type"] for block in result["blocks"]})
        self.assertFalse(any(len(block["shot_ids"])>1 for block in result["blocks"]))

    def test_complex_blocks_do_not_repeat_immediately(self):
        result=resolve_visual_plan(manifest(30,56),travel_daily_record_v1())
        complex_types={"three_up","grid","collage","layered_cards","beat_montage"}
        types=[x["block_type"] for x in result["blocks"]]
        self.assertFalse(any(a==b and a in complex_types for a,b in zip(types,types[1:])))

    def test_missing_duplicate_unknown_shot_detected(self):
        source=manifest(); definition=travel_daily_record_v1(); plan=resolve_visual_plan(source,definition)
        missing=copy.deepcopy(plan); missing["blocks"][-1]["shot_ids"].pop()
        with self.assertRaisesRegex(TemplateValidationError,"every planned shot"): validate_visual_plan(missing,source["reel_plan"],definition)
        duplicate=copy.deepcopy(plan); duplicate["blocks"][-1]["shot_ids"].append(duplicate["blocks"][0]["shot_ids"][0])
        with self.assertRaisesRegex(TemplateValidationError,"duplicates"): validate_visual_plan(duplicate,source["reel_plan"],definition)
        unknown=copy.deepcopy(plan); unknown["blocks"][-1]["shot_ids"][-1]="shot-unknown"
        with self.assertRaisesRegex(TemplateValidationError,"unknown"): validate_visual_plan(unknown,source["reel_plan"],definition)

    def test_empty_fails_and_one_shot_is_safe(self):
        empty=manifest(1); empty["reel_plan"]["shots"]=[]
        with self.assertRaisesRegex(TemplateValidationError,"empty"): resolve_visual_plan(empty,travel_daily_record_v1())
        one=resolve_visual_plan(manifest(1,30),travel_daily_record_v1())
        self.assertEqual(one["validation"]["assigned_shot_count"],1)

    def test_manifest_additive_and_invalidation_scope(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); (root/"output").mkdir(); source=manifest()
            (root/"output"/"trip_manifest.json").write_text(json.dumps(source),encoding="utf-8")
            run_template_planner(root,TemplateConfig())
            saved=json.loads((root/"output"/"trip_manifest.json").read_text(encoding="utf-8"))
            self.assertIn("template_definition",saved); self.assertIn("visual_plan",saved); self.assertNotIn("render",saved)
            for key in ("events","creative_direction","selection","story","music_analysis","reel_plan"):
                self.assertEqual(saved[key],source[key])

    def test_config_feature_flags_are_resolution_only(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); (root/"output").mkdir()
            (root/"output"/"trip_manifest.json").write_text(json.dumps(manifest()),encoding="utf-8")
            result=run_template_planner(root,TemplateConfig(motion_enabled=False,typography_enabled=False,decorations_enabled=False))
            self.assertTrue(all(x["motion"]["type"]=="none" for x in result["blocks"]))


if __name__=="__main__": unittest.main()
