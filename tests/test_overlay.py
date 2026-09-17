import copy, json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from travel_reel.overlay import OverlayValidationError, resolve_overlay, validate_overlay_plan, _presentation_safe_location_label, _presentation_safe_title
from travel_reel.pipeline import run_overlay_planner


def manifest(block_type="hero_media", phase="hook", title="Taipei 旅程", landmark="台北 101"):
    shot = {"shot_id":"shot-001","media_id":"photo-001","media_type":"photo","event_id":"event-001","story_section":phase}
    block = {"visual_block_id":"visual-block-001","definition_block_id":block_type,"block_type":block_type,
             "timeline_start_seconds":0.0,"timeline_end_seconds":6.0,"duration_seconds":6.0,
             "shot_ids":["shot-001"],"shots":[shot],"story_phase":phase,
             "layout":{"layers":[{"shot_id":"shot-001","slot_id":"slot-001","visual_layer_timing":{"start_seconds":0.0,"end_seconds":6.0}}]},
             "resolved_layout":{"safe_area":{"x":.04,"y":.04,"width":.92,"height":.92},"slots":[{"slot_id":"slot-001","shot_id":"shot-001","media_id":"photo-001","x":.1,"y":.1,"width":.8,"height":.8}]},
             "resolved_motion":{"version":"1.0","time_space":"block_normalized","tracks":[{"target_slot_id":"slot-001","space":"media_content","strategy":"hold.v1","keyframes":[{"t":0,"transform":{"translate_x":0,"translate_y":0,"scale":1,"opacity":1},"easing_to_next":"linear"},{"t":1,"transform":{"translate_x":0,"translate_y":0,"scale":1,"opacity":1}}]}],"selection_reasons":[]}}
    return {"manifest_version":"1.10","trip":{},"photos":[{"id":"photo-001","path":"photo.jpg","vision":{"landmark_hint":{"name":landmark},"description":"A concise view"}}],"videos":[],"events":{"items":[{"event_id":"event-001","label":"taipei_visit"}]},"story":{"title":title},"reel_plan":{"actual_duration_seconds":6.0},"visual_plan":{"duration_seconds":6.0,"blocks":[block]}}


class OverlayTests(unittest.TestCase):
    def test_sources_types_and_unicode(self):
        m=manifest(); out=resolve_overlay(m,m["visual_plan"]); o=out["blocks"][0]["resolved_overlay"]["overlays"][0]
        self.assertEqual(o["type"],"title"); self.assertEqual(o["content"]["text"],"Taipei 旅程"); self.assertEqual(o["target"],{"scope":"block"})
        self.assertEqual(m["visual_plan"]["blocks"][0].get("resolved_overlay"),None)

    def test_closing_and_zero_overlay(self):
        m=manifest("closing_card","closing",title="旅程終章"); out=resolve_overlay(m,m["visual_plan"]); self.assertEqual(out["blocks"][0]["resolved_overlay"]["overlays"][0]["type"],"closing_title")
        m=manifest(); m["story"].pop("title"); m["photos"][0]["vision"].pop("landmark_hint"); m["events"]["items"][0].pop("label"); m["visual_plan"]["blocks"][0].pop("story_phase"); m["visual_plan"]["blocks"][0]["shots"][0].pop("story_section"); out=resolve_overlay(m,m["visual_plan"]); self.assertEqual(out["blocks"][0]["resolved_overlay"]["overlays"],[])

    def test_validation_rejects_bad_contract(self):
        m=manifest(); out=resolve_overlay(m,m["visual_plan"]); bad=copy.deepcopy(out); bad["blocks"][0]["resolved_overlay"]["overlays"][0]["placement"]["x"]=-.1
        with self.assertRaises(OverlayValidationError): validate_overlay_plan(bad,m["visual_plan"],m)

    def test_idempotent_pipeline_and_prerequisite(self):
        # Pipeline now validates real Layout/Motion contracts before typography.
        from tests.test_motion import fixture
        from travel_reel.motion import resolve_motion
        m = fixture("hero_media")
        m["story"] = {"title": "Summer in Taipei"}
        m["visual_plan"]["blocks"][0]["story_phase"] = "hook"
        m["visual_plan"] = resolve_motion(m, m["visual_plan"])
        with TemporaryDirectory() as d:
            root=Path(d); (root/"output").mkdir(); p=root/"output"/"trip_manifest.json"; p.write_text(json.dumps(m,ensure_ascii=False),encoding="utf-8")
            first=run_overlay_planner(root); before=p.read_bytes(); second=run_overlay_planner(root)
            self.assertEqual(first,second); self.assertEqual(before,p.read_bytes())

    def test_motion_required(self):
        m=manifest(); m["visual_plan"]["blocks"][0].pop("resolved_motion")
        with self.assertRaises(OverlayValidationError): resolve_overlay(m,m["visual_plan"])

    def test_editorial_source_eligibility(self):
        self.assertIsNone(_presentation_safe_location_label("transportation"))
        self.assertIsNone(_presentation_safe_location_label("cityscape_exploration"))
        self.assertEqual(_presentation_safe_location_label("LOTTE WORLD ADVENTURE"), "LOTTE WORLD ADVENTURE")
        self.assertEqual(_presentation_safe_location_label("台北 101"), "台北 101")
        self.assertIsNone(_presentation_safe_title({"title": "VisionBenchmark"}))
        self.assertEqual(_presentation_safe_title({"title": "Summer in Taipei"}), "Summer in Taipei")

    def test_internal_phase_is_not_section_overlay(self):
        m=manifest(); m["story"].pop("title"); m["photos"][0]["vision"].pop("landmark_hint"); m["events"]["items"][0].pop("label"); m["visual_plan"]["blocks"][0]["story_phase"]="highlight"; m["visual_plan"]["blocks"][0]["shots"][0].pop("story_section")
        self.assertEqual(resolve_overlay(m,m["visual_plan"])["blocks"][0]["resolved_overlay"]["overlays"], [])

    def test_global_duplicate_overlay_id_rejected(self):
        m = manifest()
        second = copy.deepcopy(m["visual_plan"]["blocks"][0])
        second["visual_block_id"] = "visual-block-002"
        second["block_type"] = "closing_card"
        m["visual_plan"]["blocks"].append(second)
        resolved = resolve_overlay(m, m["visual_plan"])
        first_id = resolved["blocks"][0]["resolved_overlay"]["overlays"][0]["overlay_id"]
        resolved["blocks"][1]["resolved_overlay"]["overlays"][0]["overlay_id"] = first_id
        with self.assertRaises(OverlayValidationError):
            validate_overlay_plan(resolved, m["visual_plan"], m)


if __name__ == "__main__": unittest.main()
