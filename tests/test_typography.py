"""Local metadata/metrics tests; system fonts are read, never altered or copied."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from travel_reel.typography import (FontCandidate, TypographyConfig, TypographyError, TypographyResolver,
                                   inspect_font, validate_typography, resolve_plan_typography, load_font_profile)
from travel_reel.overlay import resolve_overlay, validate_overlay_plan
from travel_reel.pipeline import run_overlay_planner
from travel_reel.manifest import load_trip_manifest

FONT_ROOT = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
ARIAL = FONT_ROOT / "arial.ttf"
CJK = FONT_ROOT / "msjh.ttc"


def overlay(text="LOTTE WORLD ADVENTURE"):
    return {"content": {"text": text, "source": "media.vision.landmark_hint.name"},
            "style": {"font_role": "label", "weight_role": "regular", "size_class": "small",
                      "case_transform": "none", "letter_spacing_class": "normal", "line_height_class": "compact"}}


def config(*candidates):
    return TypographyConfig(user_fonts=tuple(candidates) or (FontCandidate("cjk_regular", CJK),), system_fonts=False)


def valid_manifest():
    from tests.test_motion import fixture
    from travel_reel.motion import resolve_motion
    m = fixture("hero_media")
    m["manifest_version"] = "1.11"
    m["visual_plan"]["blocks"][0]["story_phase"] = "hook"
    m["story"] = {"title": "LOTTE WORLD ADVENTURE"}
    m["visual_plan"] = resolve_motion(m, m["visual_plan"])
    return m


@unittest.skipUnless(CJK.is_file() and ARIAL.is_file(), "Windows JhengHei/Arial font fixtures unavailable")
class TypographyTests(unittest.TestCase):
    def test_latin_cmap_coverage(self):
        self.assertEqual(inspect_font(ARIAL.read_bytes(), 0, "LOTTE WORLD ADVENTURE")["missing_codepoints"], [])

    def test_traditional_chinese_cmap_coverage(self):
        self.assertEqual(inspect_font(CJK.read_bytes(), 0, "樂天世界")["missing_codepoints"], [])

    def test_mixed_cjk_latin_punctuation_coverage(self):
        text = "首爾 LOTTE WORLD，2026。"
        self.assertEqual(inspect_font(CJK.read_bytes(), 0, text)["missing_codepoints"], [])
        self.assertEqual(TypographyResolver(config()).resolve(overlay(text))["lines"], [text])

    def test_unsupported_codepoint_has_pillow_metrics_but_no_coverage(self):
        from PIL import ImageFont
        font = ImageFont.truetype(str(ARIAL), 40)
        self.assertGreater(font.getlength(chr(0x10FFFF)), 0)
        self.assertEqual(inspect_font(ARIAL.read_bytes(), 0, chr(0x10FFFF))["missing_codepoints"], [0x10FFFF])
        with self.assertRaises(TypographyError): TypographyResolver(config()).resolve(overlay(chr(0x10FFFF)))

    def test_fallback_requires_whole_string(self):
        c = config(FontCandidate("latin", ARIAL), FontCandidate("cjk", CJK))
        self.assertTrue(inspect_font(ARIAL.read_bytes(), 0, "樂天世界")["missing_codepoints"])
        self.assertEqual(TypographyResolver(c).resolve(overlay("樂天世界"))["logical_font_id"], "cjk")

    def test_missing_candidate_and_explicit_order(self):
        c = config(FontCandidate("missing", Path("missing-typography-font.ttf")), FontCandidate("second", ARIAL), FontCandidate("third", CJK))
        self.assertEqual(TypographyResolver(c).resolve(overlay())["logical_font_id"], "second")
        with self.assertRaises(TypographyError):
            TypographyResolver(config(FontCandidate("missing", Path("missing-font.ttf")))).resolve(overlay())

    def test_ttc_selected_face_identity(self):
        first = TypographyResolver(config(FontCandidate("cjk", CJK, 0))).resolve(overlay())
        second = TypographyResolver(config(FontCandidate("cjk", CJK, 1))).resolve(overlay())
        self.assertEqual(first["font_identity"]["sha256"], second["font_identity"]["sha256"])
        self.assertEqual(first["font_identity"]["family"], "Microsoft JhengHei")
        self.assertEqual(second["font_identity"]["family"], "Microsoft JhengHei UI")
        self.assertNotEqual(first["dependency_fingerprint"], second["dependency_fingerprint"])
        with self.assertRaises(TypographyError): inspect_font(CJK.read_bytes(), 99, "A")
        with self.assertRaises(TypographyError): inspect_font(ARIAL.read_bytes(), 1, "A")

    def test_ttc_cmap_is_selected_face_not_collection_union(self):
        # Controlled inspection doubles isolate selection even if real faces share cmap.
        class Face:
            def __init__(self, cp): self.cp = cp
            def __contains__(self, key): return False
            def getBestCmap(self): return {self.cp: "visible"}
            def getGlyphID(self, name): return 1
            def __getitem__(self, name): return self
            def getDebugName(self, index): return "Family" if index == 1 else "Regular"
        class Collection:
            fonts = [Face(ord("A")), Face(ord("中"))]
            def __init__(self, *args, **kwargs): pass
            def close(self): pass
        from travel_reel.typography import _dependencies
        TTFont, _, image, backend = _dependencies()
        with patch("travel_reel.typography._dependencies", return_value=(TTFont, Collection, image, backend)):
            self.assertEqual(inspect_font(b"ttcf", 0, "中")["missing_codepoints"], [ord("中")])
            self.assertEqual(inspect_font(b"ttcf", 1, "中")["missing_codepoints"], [])

    def test_exact_metrics_match_pillow_and_preserve_overhang(self):
        from PIL import ImageFont
        value = TypographyResolver(config(FontCandidate("latin", ARIAL))).resolve(overlay("AV j"))
        font = ImageFont.truetype(str(ARIAL), 40, layout_engine=ImageFont.Layout.BASIC)
        self.assertEqual(value["metrics"]["advance"], font.getlength("AV j") / 1080)
        l,t,r,b = font.getbbox("AV j", anchor="ls")
        self.assertEqual(value["metrics"]["ink_bounds"], {"left": l/1080,"top": t/1920,"right": r/1080,"bottom": b/1920})
        self.assertEqual(value["font_identity"]["sha256"], hashlib.sha256(ARIAL.read_bytes()).hexdigest())
        self.assertLess(value["metrics"]["ink_bounds"]["top"], 0)

    def test_cjk_metrics_are_actual_font_metrics(self):
        from PIL import ImageFont
        text = "樂天世界，2026。"
        result = TypographyResolver(config()).resolve(overlay(text))
        font = ImageFont.truetype(str(CJK), 40, index=0, layout_engine=ImageFont.Layout.BASIC)
        self.assertEqual(result["metrics"]["advance"], font.getlength(text)/1080)

    def test_different_strings_and_repeat(self):
        resolver = TypographyResolver(config())
        a = resolver.resolve(overlay("iiii")); b = resolver.resolve(overlay("WWWW"))
        self.assertLess(a["metrics"]["advance"], b["metrics"]["advance"])
        self.assertEqual(json.dumps(a), json.dumps(resolver.resolve(overlay("iiii"))))

    def test_missing_dependency_and_unreadable_cmap_fail(self):
        with patch.dict("sys.modules", {"fontTools": None}):
            with self.assertRaisesRegex(TypographyError, "requires local fontTools"):
                TypographyResolver(config()).resolve(overlay())
        with self.assertRaisesRegex(TypographyError, "Unreadable font/cmap"):
            inspect_font(b"not a font", 0, "text")
        from fontTools.ttLib import TTFont
        with patch.object(TTFont, "getBestCmap", return_value=None):
            with self.assertRaisesRegex(TypographyError, "no readable Unicode cmap"):
                inspect_font(ARIAL.read_bytes(), 0, "text")

    def test_whitespace_combining_controls_not_silently_removed(self):
        self.assertEqual(inspect_font(CJK.read_bytes(), 0, "A \u3000B")["missing_codepoints"], [])
        for text in ("a\u0301", "a\u200db", "a\nb", "a\tb", "مرحبا", "ไทย", "😀"):
            with self.subTest(text=text), self.assertRaises(TypographyError):
                TypographyResolver(config()).resolve(overlay(text))

    def test_contract_malformed_values_rejected(self):
        o=overlay(); value=TypographyResolver(config()).resolve(o)
        mutations = [("version", "9.0"), ("logical_font_id", ""), ("dependency_fingerprint", "fake"),
                     ("resolved_font_size", True), ("lines", ["changed"]), ("line_spacing", False)]
        for key, bad in mutations:
            changed=copy.deepcopy(value); changed[key]=bad
            with self.subTest(key=key), self.assertRaises(TypographyError): validate_typography(changed,o)
        for field, bad in (("advance",float("nan")),("ascent",True),("descent",float("inf")),("line_height",0)):
            changed=copy.deepcopy(value); changed["metrics"][field]=bad
            with self.subTest(field=field), self.assertRaises(TypographyError): validate_typography(changed,o)
        for field,bad in (("sha256","abc"),("face_index",-1),("family",None),("style",{})):
            changed=copy.deepcopy(value); changed["font_identity"][field]=bad
            with self.subTest(field=field), self.assertRaises(TypographyError): validate_typography(changed,o)

    def test_fabricated_coverage_and_metrics_rejected_by_live_validation(self):
        o=overlay(); value=TypographyResolver(config()).resolve(o)
        changed=copy.deepcopy(value); changed["validation"]["coverage"]="unresolved"
        with self.assertRaises(TypographyError): validate_typography(changed,o)
        changed=copy.deepcopy(value); changed["metrics"]["advance"]+=.01
        with self.assertRaises(TypographyError): validate_typography(changed,o,resolver=TypographyResolver(config()))

    def test_dependency_content_profile_backend_font_and_canvas(self):
        o=overlay(); base=TypographyResolver(config()).resolve(o)
        changed_content=overlay("Different text")
        with self.assertRaises(TypographyError): validate_typography(base,changed_content)
        c=TypographyConfig(user_fonts=config().user_fonts,system_fonts=False,profile_version="local_fonts.v2")
        self.assertNotEqual(base["dependency_fingerprint"],TypographyResolver(c).resolve(o)["dependency_fingerprint"])
        c=TypographyConfig(user_fonts=config().user_fonts,system_fonts=False,design_height=960)
        self.assertNotEqual(base["dependency_fingerprint"],TypographyResolver(c).resolve(o)["dependency_fingerprint"])
        changed=copy.deepcopy(base); changed["metrics_backend"]["pillow_version"]="future"
        with self.assertRaises(TypographyError): validate_typography(changed,o)
        resolver=TypographyResolver(config())
        # Different immutable byte snapshot simulates changed configured font bytes.
        resolver._bytes[CJK]=ARIAL.read_bytes()
        self.assertNotEqual(base["font_identity"]["sha256"],resolver.resolve(o)["font_identity"]["sha256"])

    def test_profile_file_relative_paths_and_order(self):
        with TemporaryDirectory() as d:
            p=Path(d)/"fonts.json"
            p.write_text(json.dumps([{"logical_font_id":"custom","path":str(CJK),"face_index":1,"weight":"regular"}]))
            candidates=load_font_profile(p)
            self.assertEqual(candidates[0].face_index,1)
            self.assertEqual(candidates[0].path,CJK)

    def test_empty_plan_needs_no_fonts(self):
        p={"blocks":[{"resolved_overlay":{"version":"1.0","overlays":[],"selection_reasons":[]}}]}
        with patch.dict("sys.modules",{"fontTools":None}):
            self.assertEqual(resolve_plan_typography(p,TypographyConfig(system_fonts=False)),p)

    def test_pipeline_preservation_versions_idempotence_and_atomic_failure(self):
        with TemporaryDirectory() as d:
            root=Path(d); (root/"output").mkdir(); p=root/"output"/"trip_manifest.json"
            m=valid_manifest(); p.write_text(json.dumps(m),encoding="utf-8")
            self.assertEqual(load_trip_manifest(p)["manifest_version"],"1.11")
            result=run_overlay_planner(root); first=p.read_bytes(); saved=json.loads(first)
            self.assertEqual(saved["manifest_version"],"1.15")
            self.assertEqual(saved["reel_plan"],m["reel_plan"])
            self.assertEqual(result["blocks"][0]["resolved_motion"],m["visual_plan"]["blocks"][0]["resolved_motion"])
            before=resolve_overlay(m,m["visual_plan"])
            resolved_overlay=result["blocks"][0]["resolved_overlay"]["overlays"][0]
            self.assertEqual({k:v for k,v in resolved_overlay.items() if k!="resolved_typography"},before["blocks"][0]["resolved_overlay"]["overlays"][0])
            run_overlay_planner(root); self.assertEqual(first,p.read_bytes())
            saved["render"]={"keep":True}; p.write_text(json.dumps(saved),encoding="utf-8"); old=p.read_bytes()
            run_overlay_planner(root); self.assertEqual(old,p.read_bytes())
            with patch("travel_reel.manifest.os.replace",side_effect=OSError("atomic failure")):
                with self.assertRaises(OSError): run_overlay_planner(root,TypographyConfig(design_width=540,design_height=960))
            self.assertEqual(old,p.read_bytes())
            self.assertFalse((p.parent/".trip_manifest.json.tmp").exists())
            run_overlay_planner(root,TypographyConfig(design_width=540,design_height=960))
            self.assertNotIn("render",load_trip_manifest(p))

    def test_pipeline_font_failure_preserves_manifest(self):
        with TemporaryDirectory() as d:
            root=Path(d); (root/"output").mkdir(); p=root/"output"/"trip_manifest.json"
            p.write_text(json.dumps(valid_manifest()),encoding="utf-8"); before=p.read_bytes()
            with self.assertRaises(TypographyError): run_overlay_planner(root,TypographyConfig(system_fonts=False))
            self.assertEqual(p.read_bytes(),before)

    def test_invalid_upstream_contract_rejected_before_font_access(self):
        for key in ("resolved_motion","resolved_layout"):
            with TemporaryDirectory() as d:
                root=Path(d); (root/"output").mkdir(); p=root/"output"/"trip_manifest.json"
                m=valid_manifest(); m["visual_plan"]["blocks"][0][key]["version"]="future"
                p.write_text(json.dumps(m)); before=p.read_bytes()
                with patch.object(TypographyResolver,"resolve",side_effect=AssertionError("font access")):
                    with self.assertRaises(ValueError): run_overlay_planner(root)
                self.assertEqual(p.read_bytes(),before)

    def test_input_immutable_and_irrelevant_render_metadata(self):
        m=valid_manifest(); v=resolve_overlay(m,m["visual_plan"]); before=copy.deepcopy(v)
        resolved=resolve_plan_typography(v); self.assertEqual(v,before)
        m["render"]={"unrelated":100}
        self.assertEqual(resolved,resolve_plan_typography(v))
        validate_overlay_plan(resolved,m["visual_plan"],m)


@unittest.skipUnless(CJK.is_file() and ARIAL.is_file(), "Windows JhengHei/Arial font fixtures unavailable")
class MeasuredLayoutTests(unittest.TestCase):
    def item(self, text="LOTTE WORLD ADVENTURE", width=886, height=250,
             kind="caption", lines=2, alignment="left", size="small"):
        result=overlay(text)
        result.update(type=kind,overlay_id="synthetic-001",placement={"x":.06,"y":.06,"width":width/1080,
                      "height":height/1920,"alignment":alignment})
        result["style"].update(max_lines=lines,alignment=alignment,size_class=size)
        return result

    def resolve(self, item):
        return TypographyResolver(config()).resolve(item)

    def test_preferred_single_line_and_legacy_metrics_retained(self):
        o=self.item(); value=self.resolve(o); layout=value["measured_layout"]
        self.assertEqual([r["text"] for r in layout["lines"]],[o["content"]["text"]])
        self.assertEqual(layout["resolved_font_size"],40)
        self.assertEqual(layout["fit_reason"],"preferred_size")
        self.assertEqual(value["lines"],[o["content"]["text"]])
        self.assertEqual(layout["preferred_container"]["x"],o["placement"]["x"])

    def test_latin_word_wrapping_balanced_at_preferred_size(self):
        o=self.item("A BEAUTIFUL DAY IN SEOUL",width=350)
        v=self.resolve(o)["measured_layout"]
        self.assertEqual(v["resolved_font_size"],40)
        self.assertEqual(len(v["lines"]),2)
        self.assertEqual(' '.join(r["text"] for r in v["lines"]),o["content"]["text"])
        self.assertGreater(min(r["advance"] for r in v["lines"])/max(r["advance"] for r in v["lines"]),.5)

    def test_traditional_chinese_character_wrapping_balance(self):
        text="首爾自由行必去景點樂天世界冒險樂園"
        o=self.item(text,width=440); value=self.resolve(o)["measured_layout"]
        self.assertEqual(len(value["lines"]),2)
        self.assertEqual(''.join(r["text"] for r in value["lines"]),text)
        self.assertLessEqual(abs(len(value["lines"][0]["text"])-len(value["lines"][1]["text"])),2)

    def test_mixed_wrapping_preserves_latin_runs(self):
        o=self.item("首爾 LOTTE WORLD ADVENTURE 樂天世界",width=490)
        v=self.resolve(o)["measured_layout"]
        self.assertEqual(len(v["lines"]),2)
        for word in ("LOTTE","WORLD","ADVENTURE"):
            self.assertTrue(any(word in r["text"] for r in v["lines"]))
        validate_typography(self.resolve(o),o)

    def test_opening_punctuation_never_ends_line(self):
        from travel_reel.typography_layout import break_positions,OPENING
        text="首爾（旅行）「樂天世界」真的很好玩！"
        for i in break_positions(text): self.assertNotIn(text[:i].rstrip()[-1],OPENING)

    def test_closing_punctuation_never_starts_line(self):
        from travel_reel.typography_layout import break_positions,CLOSING
        text="「首爾旅行」真的很好玩！"
        for i in break_positions(text): self.assertNotIn(text[i:].lstrip()[0],CLOSING)
        v=self.resolve(self.item(text,width=300))["measured_layout"]
        for row in v["lines"]: self.assertNotIn(row["text"][0],CLOSING)

    def test_mixed_punctuation_numerals(self):
        o=self.item("2026 首爾旅行：LOTTE WORLD！",width=360)
        v=self.resolve(o)
        validate_typography(v,o,resolver=TypographyResolver(config()))

    def test_whitespace_not_collapsed_inside_lines(self):
        o=self.item("A  BEAUTIFUL   DAY IN SEOUL",width=350)
        v=self.resolve(o)["measured_layout"]
        for r in v["lines"]:
            self.assertEqual(r["text"],r["text"].strip())
            a,b=r["source_span"]; self.assertEqual(r["text"],o["content"]["text"][a:b])

    def test_discrete_size_reduction_each_step(self):
        from PIL import ImageFont
        text="WWWWWWWWWWWW"
        for target in (38,36,34):
            font=ImageFont.truetype(str(CJK),target,index=0,layout_engine=ImageFont.Layout.BASIC)
            o=self.item(text,width=font.getlength(text)+.1,kind="section_label",lines=1)
            v=self.resolve(o)["measured_layout"]
            with self.subTest(target=target):
                self.assertEqual(v["resolved_font_size"],target)
                self.assertEqual(v["fit_reason"],"bounded_reduction")

    def test_minimum_size_and_long_token_omit(self):
        from travel_reel.typography_layout import TypographyFitError
        for o in (self.item("SUPERCALIFRAGILISTICEXPIALIDOCIOUS",width=40),
                  self.item("Title",kind="title",size="micro")):
            with self.assertRaises(TypographyFitError): self.resolve(o)

    def test_height_failure_and_character_limit(self):
        from travel_reel.typography_layout import TypographyFitError
        for o in (self.item("text",height=5),self.item("中"*257)):
            with self.assertRaises(TypographyFitError): self.resolve(o)

    def test_alignment_and_normalized_baseline_geometry(self):
        xs=[]
        for align in ("left","center","right"):
            o=self.item("AV j",alignment=align); v=self.resolve(o); m=v["measured_layout"];r=m["lines"][0]
            xs.append(r["baseline_x"])
            self.assertAlmostEqual(r["baseline_y"],.06+m["ascent"])
            self.assertAlmostEqual(r["advance_box"]["width"],r["advance"])
            self.assertAlmostEqual(r["ink_box"]["x"],r["baseline_x"]+r["relative_ink_bounds"]["left"])
            for key in r["ink_box"]: self.assertAlmostEqual(m["resolved_text_bounds"][key],r["ink_box"][key])
            validate_typography(v,o)
        self.assertEqual(xs,sorted(xs)); self.assertLess(xs[0],xs[-1])

    def test_multiline_metrics_match_selected_pillow_face(self):
        from PIL import ImageFont
        o=self.item("首爾自由行必去景點樂天世界冒險樂園",width=440)
        v=self.resolve(o)["measured_layout"]
        font=ImageFont.truetype(str(CJK),v["resolved_font_size"],index=0,layout_engine=ImageFont.Layout.BASIC)
        for row in v["lines"]:
            self.assertEqual(row["advance"],font.getlength(row["text"])/1080)
            l,t,r,b=font.getbbox(row["text"],anchor="ls")
            self.assertEqual(row["relative_ink_bounds"],{"left":l/1080,"top":t/1920,"right":r/1080,"bottom":b/1920})
        self.assertAlmostEqual(v["lines"][1]["baseline_y"]-v["lines"][0]["baseline_y"],v["line_height"]+v["line_spacing"])

    def ellipsized(self,text):
        # Derive a narrow fixture from real font advances, with no font copying.
        from PIL import ImageFont
        from travel_reel.typography_layout import break_positions
        font=ImageFont.truetype(str(CJK),34,index=0,layout_engine=ImageFont.Layout.BASIC)
        full=font.getlength(text)
        for end in reversed(break_positions(text)):
            prefix=text[:end].rstrip()
            width=font.getlength(prefix+"…")+.1
            if width<full and len(''.join(prefix.split()))>=.7*len(''.join(text.split())):
                o=self.item(text,width=width,lines=1);v=self.resolve(o)
                if v["measured_layout"]["ellipsis"]:return o,v
        self.fail("No ellipsis fixture found")

    def test_latin_ellipsis_removes_whole_trailing_word(self):
        o,v=self.ellipsized("ONE TWO THREE FOUR FIVE")
        m=v["measured_layout"];self.assertTrue(m["lines"][0]["text"].endswith("…"))
        self.assertEqual(o["content"]["text"][m["retained_source_end"]]," ")
        validate_typography(v,o,resolver=TypographyResolver(config()))

    def test_cjk_ellipsis_preserves_characters(self):
        o,v=self.ellipsized("首爾自由行必去景點樂天世界冒險樂園")
        m=v["measured_layout"];self.assertEqual(m["lines"][0]["text"],o["content"]["text"][:m["retained_source_end"]]+"…")

    def test_mixed_ellipsis(self):
        o,v=self.ellipsized("首爾 LOTTE WORLD 樂天世界旅行")
        validate_typography(v,o)
        self.assertTrue(v["measured_layout"]["ellipsis"])

    def test_venue_and_title_never_ellipsized(self):
        from travel_reel.typography_layout import TypographyFitError
        for kind in ("location_label","title","closing_title"):
            o=self.item("ONE TWO THREE FOUR FIVE",width=100,kind=kind,lines=1,size="large")
            with self.assertRaises(TypographyFitError): self.resolve(o)

    def test_uncovered_ellipsis_not_used(self):
        from travel_reel.typography_layout import TypographyFitError
        from travel_reel.typography import inspect_font as real
        o,_=self.ellipsized("ONE TWO THREE FOUR FIVE")
        def inspect(data,index,text):
            result=real(data,index,text)
            if "…" in text: result["missing_codepoints"]=[0x2026]
            return result
        with patch("travel_reel.typography_layout.inspect_font",side_effect=inspect):
            with self.assertRaises(TypographyFitError): self.resolve(o)

    def test_malformed_measured_contract_rejected(self):
        o=self.item("A BEAUTIFUL DAY IN SEOUL",width=350);v=self.resolve(o)
        for field,bad in (("max_lines",True),("policy_version","future"),("resolved_font_size",1),
                          ("fit_scale",float('nan')),("dependency_fingerprint","a"*64),("line_spacing",False),
                          ("retained_source_end",2),("lines",[])):
            changed=copy.deepcopy(v);changed["measured_layout"][field]=bad
            with self.subTest(field=field),self.assertRaises(TypographyError):validate_typography(changed,o)
        for field,bad in (("baseline_x",float('inf')),("baseline_y",True),("text","changed"),("advance",float('nan'))):
            changed=copy.deepcopy(v);changed["measured_layout"]["lines"][0][field]=bad
            with self.subTest(field=field),self.assertRaises(TypographyError):validate_typography(changed,o)

    def test_bad_boxes_union_and_line_overlap_rejected(self):
        o=self.item("A BEAUTIFUL DAY IN SEOUL",width=350);v=self.resolve(o)
        for where in ("ink_box","advance_box"):
            changed=copy.deepcopy(v);changed["measured_layout"]["lines"][0][where]["width"]+=.1
            with self.assertRaises(TypographyError):validate_typography(changed,o)
        changed=copy.deepcopy(v);changed["measured_layout"]["resolved_text_bounds"]["x"]=-1
        with self.assertRaises(TypographyError):validate_typography(changed,o)
        changed=copy.deepcopy(v);changed["measured_layout"]["lines"][1]["baseline_y"]=changed["measured_layout"]["lines"][0]["baseline_y"]
        with self.assertRaises(TypographyError):validate_typography(changed,o)

    def test_layout_dependencies_and_metadata_order(self):
        o=self.item();v=self.resolve(o)
        self.assertEqual(json.dumps(v),json.dumps(self.resolve(dict(reversed(list(o.items()))))))
        self.assertEqual(json.dumps(v),json.dumps(self.resolve(o)))
        for key in ("width","x"):
            changed=copy.deepcopy(o);changed["placement"][key]+=.01
            self.assertNotEqual(v["dependency_fingerprint"],self.resolve(changed)["dependency_fingerprint"])
            with self.assertRaises(TypographyError):validate_typography(v,changed)

    def test_legacy_single_line_record_still_valid(self):
        o=self.item();resolver=TypographyResolver(config());old=resolver._resolve_metrics(o)
        validate_typography(old,o)
        self.assertNotIn("measured_layout",old)
        self.assertIn("measured_layout",resolver.resolve(o))

    def test_omission_removes_only_unfittable_overlay(self):
        o=self.item("SUPERCALIFRAGILISTICEXPIALIDOCIOUS",width=10)
        p={"blocks":[{"resolved_overlay":{"version":"1.0","overlays":[o],"selection_reasons":[]}}]}
        before=copy.deepcopy(p);v=resolve_plan_typography(p,config())
        self.assertEqual(p,before)
        self.assertEqual(v["blocks"][0]["resolved_overlay"]["overlays"],[])
        self.assertIn("typography_omitted",v["blocks"][0]["resolved_overlay"]["selection_reasons"][0])

    def test_defaults_and_invalid_alignment(self):
        o=self.item("樂天世界");o["style"].pop("max_lines")
        self.assertEqual(self.resolve(o)["measured_layout"]["max_lines"],2)
        o["style"]["alignment"]="right"
        with self.assertRaises(TypographyError):self.resolve(o)

    def test_nbsp_and_latin_tokens_have_no_internal_break(self):
        from travel_reel.typography_layout import break_positions
        for text in ("SUPERCALIFRAGILISTICEXPIALIDOCIOUS","SEOUL-TRAVEL","中\u00a0文","SEOUL\u00a0TRAVEL"):
            self.assertEqual(break_positions(text),[])

    def test_line_count_and_boolean_box_rejected(self):
        o=self.item();v=self.resolve(o)
        changed=copy.deepcopy(v);changed["measured_layout"]["lines"]*=3
        with self.assertRaises(TypographyError):validate_typography(changed,o)
        changed=copy.deepcopy(v);changed["measured_layout"]["lines"][0]["ink_box"]["x"]=False
        with self.assertRaises(TypographyError):validate_typography(changed,o)

    def test_1_12_manifest_load_and_reresolve(self):
        with TemporaryDirectory() as d:
            root=Path(d);(root/"output").mkdir();p=root/"output"/"trip_manifest.json"
            m=valid_manifest();m["manifest_version"]="1.12"
            m["visual_plan"]=resolve_overlay(m,m["visual_plan"])
            for block in m["visual_plan"]["blocks"]:
                for o in block["resolved_overlay"]["overlays"]:
                    o["resolved_typography"]=TypographyResolver()._resolve_metrics(o)
            p.write_text(json.dumps(m),encoding="utf-8")
            self.assertEqual(load_trip_manifest(p)["manifest_version"],"1.12")
            run_overlay_planner(root)
            self.assertEqual(load_trip_manifest(p)["manifest_version"],"1.15")


if __name__ == "__main__": unittest.main()
