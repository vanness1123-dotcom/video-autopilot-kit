"""Sprint 11.2a static Layout Contract and Resolver tests."""
import copy
import json
import math
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_reel.cli import build_parser, main
from travel_reel.config import LayoutConfig
from travel_reel.layout import LayoutValidationError, resolve_layouts, validate_resolved_layout
from travel_reel.pipeline import run_layout_planner


COUNTS={"fullscreen_media":1,"hero_media":1,"two_up":2,"three_up":3,"grid":4,"collage":3,
        "layered_cards":3,"beat_montage":3,"title_card":1,"closing_card":1}


def fixture(block_type="two_up",duration=6.0,orientations=None,count=None):
    count=count or COUNTS[block_type]; orientations=orientations or ["portrait"]*count
    shots=[]; media=[]; cursor=0.0
    for index,orientation in enumerate(orientations,1):
        end=duration if index==count else round(duration*index/count,3)
        media_id=f"photo-{index:03d}"; shot_id=f"shot-{index:03d}"
        width,height={"portrait":(1080,1920),"landscape":(1920,1080),"square":(1000,1000),"unknown":(None,None)}[orientation]
        item={"id":media_id,"path":f"Photos/{index}.jpg"}
        if width is not None: item.update(width=width,height=height)
        media.append(item)
        shots.append({"shot_id":shot_id,"media_id":media_id,"media_type":"photo","event_id":f"event-{index:03d}"})
        cursor=end
    block={"visual_block_id":"visual-block-001","definition_block_id":block_type,"block_type":block_type,
           "timeline_start_seconds":0.0,"timeline_end_seconds":duration,"duration_seconds":duration,
           "shot_ids":[shot["shot_id"] for shot in shots],"shots":shots,"story_phase":"exploration",
           "event_ids":[shot["event_id"] for shot in shots],"editorial_affinity":{"score":100.0,"reasons":["same_event"],"cross_event":False},
           "layout":{"legacy":True},"motion":{"type":"none"},"transition":{"type":"cut"},
           "typography":[],"decorations":[],"beat_alignment":{}}
    visual={"visual_plan_version":"1.0","template_id":"travel_daily_record_v1","template_version":"1.0",
            "duration_seconds":duration,"blocks":[block],"shot_assignments":[{"shot_id":s["shot_id"],"block_id":"visual-block-001"} for s in shots],
            "story_phases":["exploration"],"validation":{"valid":True,"planned_shot_count":count,"assigned_shot_count":count}}
    return {"manifest_version":"1.8","trip":{},"photos":media,"videos":[],"visual_plan":visual,
            "reel_plan":{"actual_duration_seconds":duration},"events":{"keep":True},"creative_direction":{"keep":True},
            "selection":{"keep":True},"story":{"keep":True},"music_analysis":{"keep":True},"music_selection":{"keep":True},"render":{"old":True}}


def sequence_fixture(block_type,orientation_groups):
    source=fixture(block_type,orientations=orientation_groups[0]); blocks=[]; media=[]; assignments=[]
    for block_index,orientations in enumerate(orientation_groups,1):
        part=fixture(block_type,duration=6.0,orientations=orientations,count=len(orientations)); block=part["visual_plan"]["blocks"][0]
        block["visual_block_id"]=f"visual-block-{block_index:03d}"
        block["timeline_start_seconds"]=(block_index-1)*6.0; block["timeline_end_seconds"]=block_index*6.0
        for shot_index,(shot,item) in enumerate(zip(block["shots"],part["photos"]),1):
            shot["shot_id"]=f"shot-{block_index:03d}-{shot_index:03d}"; shot["media_id"]=f"photo-{block_index:03d}-{shot_index:03d}"
            item["id"]=shot["media_id"]; block["shot_ids"][shot_index-1]=shot["shot_id"]
            media.append(item); assignments.append({"shot_id":shot["shot_id"],"block_id":block["visual_block_id"]})
        blocks.append(block)
    source["photos"]=media; source["visual_plan"]["blocks"]=blocks; source["visual_plan"]["shot_assignments"]=assignments
    source["visual_plan"]["duration_seconds"]=len(blocks)*6.0; source["reel_plan"]["actual_duration_seconds"]=len(blocks)*6.0
    return source


class LayoutTests(unittest.TestCase):
    def resolved(self,kind="two_up",duration=6.0,orientations=None,count=None):
        source=fixture(kind,duration,orientations,count)
        return source,resolve_layouts(source,source["visual_plan"])

    def test_all_current_block_types_resolve(self):
        for kind in COUNTS:
            with self.subTest(kind=kind):
                source,result=self.resolved(kind)
                layout=result["blocks"][0]["resolved_layout"]
                self.assertEqual(len(layout["slots"]),COUNTS[kind])
                self.assertTrue(layout["strategy"])

    def test_empty_block_is_rejected(self):
        source=fixture(); source["visual_plan"]["blocks"][0]["shots"]=[]
        with self.assertRaisesRegex(LayoutValidationError,"no media shots"):
            resolve_layouts(source,source["visual_plan"])

    def test_normalized_geometry_bounds(self):
        _,result=self.resolved("grid")
        for slot in result["blocks"][0]["resolved_layout"]["slots"]:
            self.assertGreater(slot["width"],0); self.assertGreater(slot["height"],0)
            self.assertGreaterEqual(slot["x"],0); self.assertGreaterEqual(slot["y"],0)
            self.assertLessEqual(slot["x"]+slot["width"],1); self.assertLessEqual(slot["y"]+slot["height"],1)

    def test_zero_negative_nonfinite_and_out_of_bounds_rejected(self):
        source,result=self.resolved()
        media={item["id"]:item for item in source["photos"]}; block=result["blocks"][0]
        for key,value in (("width",0),("height",-.1),("x",math.nan),("y",math.inf),("width",2)):
            broken=copy.deepcopy(block); broken["resolved_layout"]["slots"][0][key]=value
            with self.assertRaises(LayoutValidationError): validate_resolved_layout(broken,media)

    def test_duplicate_unknown_shot_and_unknown_media_rejected(self):
        source,result=self.resolved(); media={item["id"]:item for item in source["photos"]}; block=result["blocks"][0]
        duplicate=copy.deepcopy(block); duplicate["resolved_layout"]["slots"][1]["shot_id"]=duplicate["resolved_layout"]["slots"][0]["shot_id"]
        with self.assertRaisesRegex(LayoutValidationError,"duplicates"): validate_resolved_layout(duplicate,media)
        unknown=copy.deepcopy(block); unknown["resolved_layout"]["slots"][0]["shot_id"]="shot-unknown"
        with self.assertRaisesRegex(LayoutValidationError,"shot ownership"): validate_resolved_layout(unknown,media)
        unknown_media=copy.deepcopy(block); unknown_media["resolved_layout"]["slots"][0]["media_id"]="photo-unknown"
        with self.assertRaisesRegex(LayoutValidationError,"media ownership"): validate_resolved_layout(unknown_media,media)

    def test_duplicate_slot_invalid_z_fit_and_strategy_rejected(self):
        source,result=self.resolved(); media={item["id"]:item for item in source["photos"]}; block=result["blocks"][0]
        cases=(("slot_id",block["resolved_layout"]["slots"][0]["slot_id"]),("z_index",-1),("fit_mode","stretch"))
        for key,value in cases:
            broken=copy.deepcopy(block); broken["resolved_layout"]["slots"][1][key]=value
            with self.assertRaises(LayoutValidationError): validate_resolved_layout(broken,media)
        broken=copy.deepcopy(block); broken["resolved_layout"]["strategy"]="random-layout"
        with self.assertRaisesRegex(LayoutValidationError,"Unknown"): validate_resolved_layout(broken,media)
        broken=copy.deepcopy(block); broken["resolved_layout"]["strategy"]="two_up_horizontal.v1"
        with self.assertRaisesRegex(LayoutValidationError,"incompatible"): validate_resolved_layout(broken,media)

    def test_structured_layouts_do_not_overlap(self):
        for kind in ("two_up","three_up","grid"):
            _,result=self.resolved(kind)
            self.assertEqual(result["blocks"][0]["resolved_layout"]["overlap_policy"],"prohibited")

    def test_collage_and_layered_cards_require_and_accept_overlap(self):
        for kind in ("collage","layered_cards"):
            source,result=self.resolved(kind); block=result["blocks"][0]
            self.assertEqual(block["resolved_layout"]["overlap_policy"],"intentional")
            validate_resolved_layout(block,{item["id"]:item for item in source["photos"]})
            broken=copy.deepcopy(block)
            for slot,x in zip(broken["resolved_layout"]["slots"],(.04,.375,.71)):
                slot.update(x=x,y=.04,width=.25,height=.25)
            with self.assertRaisesRegex(LayoutValidationError,"requires intentional overlap"):
                validate_resolved_layout(broken,{item["id"]:item for item in source["photos"]})

    def test_layered_cards_have_unique_primary_foreground_hierarchy(self):
        source,result=self.resolved("layered_cards"); block=result["blocks"][0]
        slots=block["resolved_layout"]["slots"]
        self.assertEqual([slot["z_index"] for slot in slots],[2,0,1])
        self.assertEqual(slots[0]["role"],"primary"); self.assertEqual(slots[0]["z_index"],max(slot["z_index"] for slot in slots))
        broken=copy.deepcopy(block); broken["resolved_layout"]["slots"][1]["z_index"]=2
        with self.assertRaisesRegex(LayoutValidationError,"z-order|hierarchy"):
            validate_resolved_layout(broken,{item["id"]:item for item in source["photos"]})

    def test_portrait_landscape_mixed_and_unknown_are_deterministic(self):
        _,portrait=self.resolved("two_up",orientations=["portrait","portrait"])
        _,landscape=self.resolved("two_up",orientations=["landscape","landscape"])
        _,mixed=self.resolved("two_up",orientations=["portrait","landscape"])
        _,unknown=self.resolved("two_up",orientations=["unknown","unknown"])
        self.assertEqual(portrait["blocks"][0]["resolved_layout"]["strategy"],"two_up_vertical.v1")
        self.assertEqual(landscape["blocks"][0]["resolved_layout"]["strategy"],"two_up_horizontal.v1")
        self.assertEqual(mixed["blocks"][0]["resolved_layout"]["strategy"],"two_up_asymmetric_left.v1")
        self.assertEqual(unknown["blocks"][0]["resolved_layout"]["strategy"],"two_up_vertical.v1")

    def test_two_up_mixed_order_selects_explainable_asymmetric_side(self):
        _,left=self.resolved("two_up",orientations=["portrait","landscape"])
        _,right=self.resolved("two_up",orientations=["landscape","portrait"])
        self.assertEqual(left["blocks"][0]["resolved_layout"]["strategy"],"two_up_asymmetric_left.v1")
        self.assertEqual(right["blocks"][0]["resolved_layout"]["strategy"],"two_up_asymmetric_right.v1")
        self.assertIn("mixed_orientation",left["blocks"][0]["resolved_layout"]["selection_reasons"])

    def test_two_up_recent_repetition_prefers_comparable_alternative(self):
        source=sequence_fixture("two_up",[["portrait","portrait"],["portrait","portrait"]])
        result=resolve_layouts(source,source["visual_plan"]); strategies=[b["resolved_layout"]["strategy"] for b in result["blocks"]]
        self.assertEqual(strategies[0],"two_up_vertical.v1"); self.assertNotEqual(strategies[1],strategies[0])
        self.assertIn("compatible_alternative_preferred",result["blocks"][1]["resolved_layout"]["selection_reasons"])

    def test_two_up_inferior_alternative_is_not_forced(self):
        source=sequence_fixture("two_up",[["landscape","landscape"],["landscape","landscape"]])
        result=resolve_layouts(source,source["visual_plan"])
        self.assertEqual([b["resolved_layout"]["strategy"] for b in result["blocks"]],
                         ["two_up_horizontal.v1","two_up_horizontal.v1"])

    def test_three_up_orientation_families_and_dominant_hierarchy(self):
        _,portrait=self.resolved("three_up",orientations=["portrait"]*3)
        _,landscape=self.resolved("three_up",orientations=["landscape"]*3)
        _,mixed=self.resolved("three_up",orientations=["portrait","landscape","portrait"])
        self.assertEqual(portrait["blocks"][0]["resolved_layout"]["strategy"],"three_up_equal_portraits.v1")
        self.assertEqual(landscape["blocks"][0]["resolved_layout"]["strategy"],"three_up_landscape_stack.v1")
        layout=mixed["blocks"][0]["resolved_layout"]; self.assertEqual(layout["strategy"],"three_up_mixed_dominant.v1")
        areas=[slot["width"]*slot["height"] for slot in layout["slots"]]
        self.assertEqual(areas.index(max(areas)),1)

    def test_grid_two_three_four_are_bounded_and_deterministic(self):
        for count in (2,3,4):
            source=fixture("grid",orientations=["portrait"]*count,count=count)
            first=resolve_layouts(source,source["visual_plan"]); second=resolve_layouts(source,source["visual_plan"])
            self.assertEqual(first,second); self.assertEqual(len(first["blocks"][0]["resolved_layout"]["slots"]),count)
            self.assertEqual(first["blocks"][0]["resolved_layout"]["overlap_policy"],"prohibited")

    def test_collage_orientation_and_count_families(self):
        _,portrait=self.resolved("collage",orientations=["portrait","portrait"],count=2)
        _,mixed=self.resolved("collage",orientations=["portrait","landscape"],count=2)
        _,three=self.resolved("collage",orientations=["portrait","landscape","portrait"],count=3)
        self.assertEqual(portrait["blocks"][0]["resolved_layout"]["strategy"],"collage_staggered_2.v1")
        self.assertEqual(mixed["blocks"][0]["resolved_layout"]["strategy"],"collage_dominant_2.v1")
        self.assertEqual(three["blocks"][0]["resolved_layout"]["strategy"],"collage_asymmetric_3.v1")
        self.assertEqual([slot["z_index"] for slot in three["blocks"][0]["resolved_layout"]["slots"]],[0,1,2])

    def test_layered_card_families_are_distinct_from_collage(self):
        for count in (2,3):
            _,layered=self.resolved("layered_cards",orientations=["portrait"]*count,count=count)
            _,collage=self.resolved("collage",orientations=["portrait"]*count,count=count)
            left=layered["blocks"][0]["resolved_layout"]; right=collage["blocks"][0]["resolved_layout"]
            self.assertNotEqual(left["strategy"],right["strategy"]); self.assertNotEqual(left["slots"],right["slots"])
            self.assertEqual(left["slots"][0]["role"],"primary")

    def test_fit_modes_are_orientation_conservative_and_controlled(self):
        _,mixed=self.resolved("two_up",orientations=["portrait","landscape"])
        slots=mixed["blocks"][0]["resolved_layout"]["slots"]
        self.assertEqual(slots[0]["fit_mode"],"cover"); self.assertEqual(slots[1]["fit_mode"],"contain")
        self.assertTrue({slot["fit_mode"] for slot in slots}<={"cover","contain"})

    def test_resolution_is_deterministic_and_preserves_existing_contract(self):
        source=fixture("collage"); before=copy.deepcopy(source["visual_plan"])
        first=resolve_layouts(source,source["visual_plan"]); second=resolve_layouts(copy.deepcopy(source),copy.deepcopy(source["visual_plan"]))
        self.assertEqual(first,second); self.assertEqual(source["visual_plan"],before)
        resolved_block=copy.deepcopy(first["blocks"][0]); resolved_block.pop("resolved_layout")
        self.assertEqual(resolved_block,before["blocks"][0])

    def test_duration_independence(self):
        for duration in (30.0,56.0,90.0):
            source,result=self.resolved("three_up",duration)
            self.assertEqual(result["duration_seconds"],duration)
            self.assertEqual(result["blocks"][0]["timeline_end_seconds"],source["visual_plan"]["blocks"][0]["timeline_end_seconds"])

    def test_pipeline_persists_additively_and_invalidates_only_render(self):
        with TemporaryDirectory() as directory:
            root=Path(directory); (root/"output").mkdir(); source=fixture("two_up")
            path=root/"output/trip_manifest.json"; path.write_text(json.dumps(source),encoding="utf-8")
            upstream=copy.deepcopy({key:source[key] for key in ("photos","videos","events","creative_direction","selection","story","music_analysis","music_selection","reel_plan")})
            result=run_layout_planner(root,LayoutConfig())
            saved=json.loads(path.read_text(encoding="utf-8"))
            self.assertIn("resolved_layout",result["blocks"][0]); self.assertNotIn("render",saved)
            self.assertEqual({key:saved[key] for key in upstream},upstream); self.assertEqual(saved["manifest_version"],"1.9")

    def test_cli_and_missing_visual_plan_prerequisite(self):
        self.assertIn("layout-plan",build_parser().format_help())
        with TemporaryDirectory() as directory:
            root=Path(directory); (root/"output").mkdir()
            (root/"output/trip_manifest.json").write_text(json.dumps({"trip":{},"photos":[],"videos":[]}),encoding="utf-8")
            output=StringIO()
            with redirect_stdout(output): code=main(["layout-plan",str(root)])
            self.assertEqual(code,2); self.assertIn("Run 'template-plan' first",output.getvalue())


if __name__=="__main__": unittest.main()
