"""Rendering-independent dynamic visual template contracts and resolver."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

TEMPLATE_SCHEMA_VERSION = "1.0"
VISUAL_PLAN_VERSION = "1.0"
SUPPORTED_MOTIONS = frozenset({"none", "push_in", "pull_out", "pan_left", "pan_right",
                               "pan_up", "pan_down", "slide_in", "slide_out", "scale",
                               "translate", "fade", "pop"})
SUPPORTED_TRANSITIONS = frozenset({"cut", "dissolve", "fade", "flash", "slide", "zoom", "mask_reveal"})
BLOCK_TYPES = frozenset({"fullscreen_media", "hero_media", "two_up", "three_up", "grid", "collage",
                         "layered_cards", "beat_montage", "title_card", "closing_card"})
STORY_PHASES = frozenset({"hook", "arrival", "establishing", "exploration", "experience", "highlight", "closing"})
COMPLEX_BLOCKS = frozenset({"three_up", "grid", "collage", "layered_cards", "beat_montage"})
GENERIC_MOODS = frozenset({"neutral", "calm"})


class TemplateValidationError(ValueError):
    pass


def _slot(slot_id: str, x: float, y: float, width: float, height: float, *, z: int = 0,
          rotation: float = 0, crop: str = "fill", opacity: float = 1) -> dict[str, Any]:
    return {"slot_id": slot_id, "x": x, "y": y, "width": width, "height": height, "z_order": z,
            "rotation_degrees": rotation, "media_fit": crop, "corner_radius_intent": "small", "opacity": opacity}


def _block(block_id: str, block_type: str, minimum: int, maximum: int, phases: list[str],
           slots: list[dict[str, Any]], motion: str, transition: str, weight: int,
           media: list[str] | None = None, energy: str = "medium") -> dict[str, Any]:
    return {"block_id": block_id, "block_type": block_type, "min_media": minimum, "max_media": maximum,
            "preferred_media_types": media or ["photo", "video"], "preferred_story_phases": phases,
            "preferred_event_density": "single_event", "preferred_energy": energy,
            "duration_policy": {"type": "consume_planned_shots", "minimum_seconds": .25},
            "layout": {"coordinate_space": "normalized", "canvas": [0.0, 0.0, 1.0, 1.0], "slots": slots},
            "layers": [{"role": "media", "slot_id": slot["slot_id"], "z_order": slot["z_order"]} for slot in slots],
            "motion": {"type": motion, "start_time": 0.0, "end_time": 1.0, "easing": "ease_in_out",
                       "start_state": {"scale": 1.0}, "end_state": {"scale": 1.06}, "beat_alignment": "optional"},
            "transition": {"type": transition, "duration_seconds": .2 if transition != "cut" else 0.0,
                           "beat_alignment": "prefer", "energy_preference": energy},
            "typography": [], "decorations": [], "beat_behavior": {"boundary": "prefer", "replacement": maximum > 1},
            "repeat_policy": {"allow": True, "avoid_immediate": block_type in COMPLEX_BLOCKS}, "weight": weight}


def travel_daily_record_v1() -> dict[str, Any]:
    """Return a fresh adaptive reference definition; it contains no fixed timeline."""
    full=[_slot("primary",0,0,1,1)]
    two=[_slot("left",.04,.08,.44,.84),_slot("right",.52,.08,.44,.84)]
    three=[_slot("hero",.04,.05,.92,.5),_slot("lower_left",.04,.59,.44,.36),_slot("lower_right",.52,.59,.44,.36)]
    grid=[_slot(f"cell_{i+1}",.04+(i%2)*.48,.04+(i//2)*.48,.44,.44) for i in range(4)]
    collage=[_slot("back",.08,.09,.78,.72,z=0,rotation=-3),_slot("front",.23,.28,.7,.64,z=1,rotation=3),
             _slot("accent",.04,.67,.38,.27,z=2,rotation=-2)]
    blocks=[
        _block("fullscreen","fullscreen_media",1,1,["hook","experience","highlight"],full,"push_in","cut",9),
        _block("hero","hero_media",1,1,["hook","highlight","closing"],[_slot("hero",.05,.08,.9,.78)],"push_in","dissolve",10),
        _block("two_up","two_up",2,2,["exploration","experience"],two,"pan_right","slide",8,["photo"]),
        _block("three_up","three_up",3,3,["exploration","experience"],three,"pop","cut",7,["photo"]),
        _block("grid","grid",2,4,["exploration"],grid,"none","cut",6,["photo"]),
        _block("collage","collage",2,3,["exploration","experience"],collage,"translate","dissolve",9,["photo"]),
        _block("layered","layered_cards",2,3,["experience","closing"],collage,"slide_in","dissolve",9,["photo"]),
        _block("montage","beat_montage",2,4,["experience","highlight"],full,"pop","flash",10,["photo","video"],"high"),
        _block("title","title_card",1,1,["hook"],[_slot("background",0,0,1,1)],"fade","fade",5),
        _block("closing","closing_card",1,1,["closing"],[_slot("memory",.12,.12,.76,.68)],"pull_out","fade",10),
    ]
    blocks[4]["decorations"]=[{"type":"line","style_token":"hand_drawn_line","position":{"x":.08,"y":.5}}]
    blocks[5]["decorations"]=[{"type":"tape","style_token":"paper_edge","position":{"x":.12,"y":.08}}]
    blocks[6]["decorations"]=[{"type":"frame","style_token":"paper_edge","position":{"x":.05,"y":.05}}]
    blocks[8]["typography"]=[{"role":"title","style_token":"travel_handwritten","position":{"x":.5,"y":.18},
                               "alignment":"center","scale":1.0,"rotation_degrees":0,"animation_intent":"fade","safe_area":"canvas"}]
    blocks[9]["typography"]=[{"role":"caption","style_token":"clean_sans","position":{"x":.5,"y":.86},
                               "alignment":"center","scale":.8,"rotation_degrees":0,"animation_intent":"fade","safe_area":"lower_safe"}]
    return {"template_schema_version":TEMPLATE_SCHEMA_VERSION,"template_id":"travel_daily_record_v1",
            "template_version":"1.0","name":"Travel Daily Record v1","family":"travel_diary",
            "description":"Adaptive bright scrapbook and travel-memory visual grammar.",
            "supported_media":["photo","video"],"supported_story_phases":sorted(STORY_PHASES),
            "supported_pacing":["slow","balanced","dynamic","fast"],
            "canvas":{"aspect_ratio":"9:16","coordinate_space":"normalized","background_token":"paper_white",
                      "safe_area":{"x":.04,"y":.04,"width":.92,"height":.92}},
            "typography_style":{"tokens":["travel_handwritten","clean_sans","editorial_serif","compact_label"],
                "roles":{"title":{"style_token":"travel_handwritten","alignment":"center","safe_area":"canvas"},
                         "location":{"style_token":"compact_label","alignment":"left","safe_area":"title_safe"},
                         "date":{"style_token":"clean_sans","alignment":"left","safe_area":"title_safe"},
                         "caption":{"style_token":"clean_sans","alignment":"center","safe_area":"lower_safe"},
                         "accent":{"style_token":"editorial_serif","alignment":"center","safe_area":"canvas"}}},
            "decoration_style":{"allowed_types":["sticker","doodle","frame","tape","paper","line","shape"],
                                "style_tokens":["generic_travel_mark","paper_edge","hand_drawn_line"]},
            "block_library":blocks,
            "sequencing_rules":{"phase_preferences":{
                "hook":["hero_media","fullscreen_media","title_card"],
                "arrival":["fullscreen_media","two_up"],"establishing":["fullscreen_media","hero_media"],
                "exploration":["two_up","three_up","grid","collage","layered_cards"],
                "experience":["layered_cards","collage","two_up","fullscreen_media","beat_montage"],
                "highlight":["hero_media","fullscreen_media","beat_montage","two_up","three_up"],
                "closing":["layered_cards","closing_card","hero_media"]}},
            "adaptation_rules":{"duration_mode":"consume_reel_plan","shot_count_mode":"consume_all",
                "event_boundary_preference":True,"beat_boundary_preference":True,"avoid_immediate_repeat":True,
                "max_complex_blocks_in_row":2,"title_card_maximum":1,"closing_card_phase_only":True}}


def get_builtin_template(template_id: str) -> dict[str, Any]:
    if template_id != "travel_daily_record_v1": raise TemplateValidationError(f"Unknown template: {template_id}")
    definition=travel_daily_record_v1(); validate_template_definition(definition); return definition


def validate_template_definition(value: object) -> None:
    _validate_finite_numbers(value)
    if not isinstance(value,dict) or value.get("template_schema_version") != TEMPLATE_SCHEMA_VERSION:
        raise TemplateValidationError("Unsupported template schema version")
    if not isinstance(value.get("template_id"),str) or not isinstance(value.get("template_version"),str):
        raise TemplateValidationError("Template identity is required")
    blocks=value.get("block_library")
    if not isinstance(blocks,list) or not blocks: raise TemplateValidationError("Template block library is empty")
    seen=set()
    for block in blocks:
        if not isinstance(block,dict) or block.get("block_type") not in BLOCK_TYPES: raise TemplateValidationError("Unknown visual block type")
        if block.get("block_id") in seen: raise TemplateValidationError("Duplicate block ID")
        seen.add(block.get("block_id"))
        if block.get("motion",{}).get("type") not in SUPPORTED_MOTIONS: raise TemplateValidationError("Unsupported motion intent")
        if block.get("transition",{}).get("type") not in SUPPORTED_TRANSITIONS: raise TemplateValidationError("Unsupported transition intent")
        if not 1 <= int(block.get("min_media",0)) <= int(block.get("max_media",0)): raise TemplateValidationError("Invalid block media bounds")
        for slot in block.get("layout",{}).get("slots",[]): _validate_slot(slot)
    safe=value.get("canvas",{}).get("safe_area"); _validate_slot({"slot_id":"safe","z_order":0,"rotation_degrees":0,
        "media_fit":"fit","opacity":1,**(safe if isinstance(safe,dict) else {})})


def resolve_visual_plan(manifest: dict[str, Any], definition: dict[str, Any], *,
                        avoid_immediate_repeat: bool=True, max_complex_blocks_in_row: int=2) -> dict[str, Any]:
    validate_template_definition(definition)
    reel=manifest.get("reel_plan")
    if not isinstance(reel,dict) or not isinstance(reel.get("shots"),list) or not reel["shots"]:
        raise TemplateValidationError("Reel Plan not found or empty. Run 'plan' first.")
    duration=float(reel.get("actual_duration_seconds",0)); shots=reel["shots"]
    if not _finite(duration) or duration <= 0: raise TemplateValidationError("Reel Plan duration is invalid")
    by_type={b["block_type"]:b for b in definition["block_library"]}; preferences=definition["sequencing_rules"]["phase_preferences"]
    anchors=_anchors(reel); blocks=[]; index=0; complex_run=0
    direction=manifest.get("creative_direction") if isinstance(manifest.get("creative_direction"),dict) else {}
    pacing_value=direction.get("pacing"); pacing=str(pacing_value.get("overall") if isinstance(pacing_value,dict) else pacing_value or "balanced")
    media_by_id={item.get("id"):item for key in ("photos","videos") for item in manifest.get(key,[]) if isinstance(item,dict)}
    while index < len(shots):
        shot=shots[index]; phase=str(shot.get("story_section") or "exploration")
        remaining=len(shots)-index; same_event=_same_run(shots,index,"event_id"); same_phase=_same_run(shots,index,"story_section")
        candidates=[by_type[k] for k in preferences.get(phase,["fullscreen_media"]) if k in by_type]
        phase_available=min(remaining,same_phase)
        feasible=[]
        for candidate in candidates:
            compatible=_compatible_run(shots,index,phase_available,set(candidate["preferred_media_types"]))
            grouping=_group_candidate(shots,index,compatible,candidate,media_by_id)
            if grouping and (candidate["block_type"] != "beat_montage" or
                             pacing in {"fast","dynamic"} and _beat_support(anchors,shots[index:index+grouping["count"]])):
                feasible.append((candidate,grouping))
        if not feasible: feasible=[(by_type["fullscreen_media"],{"count":1,"score":100.0,"reasons":["single_shot_fallback"]})]
        previous=blocks[-1]["block_type"] if blocks else None
        ranked=[]
        recent=[block["block_type"] for block in blocks[-3:]]
        for b,grouping in feasible:
            count=int(grouping["count"])
            assigned_events={s.get("event_id") for s in shots[index:index+count] if s.get("event_id")}
            score=int(b["weight"])+(4 if shot.get("media_type") in b["preferred_media_types"] else 0)
            score += 5 if phase in b["preferred_story_phases"] else 0
            score += 4 if len(assigned_events) <= 1 else -2*(len(assigned_events)-1)
            if avoid_immediate_repeat and b["block_type"]==previous and b["block_type"] in COMPLEX_BLOCKS: score-=100
            if b["block_type"] in recent: score-=5*(len(recent)-recent.index(b["block_type"]))
            if complex_run>=max_complex_blocks_in_row and b["block_type"] in COMPLEX_BLOCKS: score-=100
            if phase=="closing" and index+count==len(shots) and b["block_type"]=="closing_card": score+=20
            if anchors and b["beat_behavior"]["boundary"]=="prefer": score+=2
            if pacing in {"fast","dynamic"} and b["block_type"]=="beat_montage": score+=3
            if pacing in {"slow","balanced"} and b["block_type"] in {"hero_media","fullscreen_media"}: score+=2
            score += round(float(grouping["score"])/20)
            ranked.append((score,count,b["block_id"],b,grouping))
        _,count,_,chosen,grouping=max(ranked,key=lambda x:(x[0],x[1],x[2]))
        assigned=shots[index:index+count]; start=float(assigned[0]["timeline_start_seconds"]); end=float(assigned[-1]["timeline_end_seconds"])
        beat=next((a for a in anchors if abs(a-start)<=.125),None)
        blocks.append(_resolved_block(len(blocks)+1,chosen,assigned,start,end,phase,beat,grouping))
        complex_run=complex_run+1 if chosen["block_type"] in COMPLEX_BLOCKS else 0; index+=count
    plan={"visual_plan_version":VISUAL_PLAN_VERSION,"template_id":definition["template_id"],
          "template_version":definition["template_version"],"duration_seconds":round(duration,3),
          "blocks":blocks,"shot_assignments":[{"shot_id":s["shot_id"],"block_id":b["visual_block_id"]}
              for b in blocks for s in b["shots"]],
          "story_phases":list(dict.fromkeys(b["story_phase"] for b in blocks)),
          "validation":{"valid":True,"planned_shot_count":len(shots),"assigned_shot_count":sum(len(b["shot_ids"]) for b in blocks),
                        "beat_aware_block_count":sum(bool(b["beat_alignment"]["anchor_time_seconds"] is not None) for b in blocks)}}
    validate_visual_plan(plan,reel,definition); return plan


def validate_visual_plan(plan: object, reel: dict[str, Any], definition: dict[str, Any]) -> None:
    _validate_finite_numbers(plan)
    if not isinstance(plan,dict) or plan.get("visual_plan_version") != VISUAL_PLAN_VERSION: raise TemplateValidationError("Unsupported visual plan version")
    if plan.get("template_id") != definition.get("template_id"): raise TemplateValidationError("Visual plan template mismatch")
    duration=plan.get("duration_seconds"); expected=reel.get("actual_duration_seconds")
    if not _finite(duration) or float(duration)!=round(float(expected),3): raise TemplateValidationError("Visual plan duration must equal Reel Plan duration")
    known=[s.get("shot_id") for s in reel.get("shots",[])]; owned=[]; prior=-1.0
    definitions={b["block_id"]:b for b in definition["block_library"]}
    blocks=plan.get("blocks",[])
    for block in blocks:
        owned.extend(block.get("shot_ids",[]))
    if any(x not in known for x in owned): raise TemplateValidationError("Visual plan contains unknown shot ID")
    if len(owned)!=len(set(owned)): raise TemplateValidationError("Visual plan duplicates shot ownership")
    if any(x not in owned for x in known): raise TemplateValidationError("Visual plan does not account for every planned shot")
    if owned!=known: raise TemplateValidationError("Visual plan shot ownership is not in Reel Plan order")
    for block in blocks:
        if block.get("definition_block_id") not in definitions: raise TemplateValidationError("Unknown block reference")
        contract=definitions[block["definition_block_id"]]; assigned=len(block.get("shot_ids",[]))
        if not int(contract["min_media"]) <= assigned <= int(contract["max_media"]): raise TemplateValidationError("Resolved block violates media bounds")
        if block.get("story_phase") not in STORY_PHASES: raise TemplateValidationError("Invalid story phase")
        if block.get("motion",{}).get("type") not in SUPPORTED_MOTIONS: raise TemplateValidationError("Unsupported resolved motion intent")
        if block.get("transition",{}).get("type") not in SUPPORTED_TRANSITIONS: raise TemplateValidationError("Unsupported resolved transition intent")
        start,end=block.get("timeline_start_seconds"),block.get("timeline_end_seconds")
        if not _finite(start) or not _finite(end) or not 0 <= float(start) < float(end) <= float(duration): raise TemplateValidationError("Invalid visual block timing")
        if float(start)<prior: raise TemplateValidationError("Visual blocks are not deterministically ordered")
        prior=float(start)


def _resolved_block(number,definition,shots,start,end,phase,beat,grouping):
    slots=definition["layout"]["slots"]
    layers=[]
    for index,shot in enumerate(shots):
        slot=slots[index%len(slots)]
        layers.append({"shot_id":shot["shot_id"],"slot_id":slot["slot_id"],"geometry":dict(slot),
                       "editorial_timing":{"start_seconds":shot["timeline_start_seconds"],"end_seconds":shot["timeline_end_seconds"]},
                       "visual_layer_timing":{"start_seconds":shot["timeline_start_seconds"],"end_seconds":shot["timeline_end_seconds"]}})
    return {"visual_block_id":f"visual-block-{number:03d}","definition_block_id":definition["block_id"],
            "block_type":definition["block_type"],"timeline_start_seconds":round(start,3),"timeline_end_seconds":round(end,3),
            "duration_seconds":round(end-start,3),"shot_ids":[s["shot_id"] for s in shots],"shots":[{"shot_id":s["shot_id"],
            "media_id":s.get("media_id"),"media_type":s.get("media_type"),"event_id":s.get("event_id")} for s in shots],
            "story_phase":phase,"event_ids":list(dict.fromkeys(s.get("event_id") for s in shots if s.get("event_id"))),
            "editorial_affinity":{"score":grouping["score"],"reasons":grouping["reasons"],
                                  "cross_event":len({s.get("event_id") for s in shots if s.get("event_id")})>1},
            "layout":{"coordinate_space":"normalized","layers":layers},"motion":dict(definition["motion"]),
            "transition":dict(definition["transition"]),"typography":list(definition["typography"]),
            "decorations":list(definition["decorations"]),"beat_alignment":{"intent":definition["beat_behavior"],"anchor_time_seconds":beat}}


def _anchors(reel):
    values=(reel.get("music_intelligence") or {}).get("sync_anchors",[])
    return sorted({round(float(a["time"]),3) for a in values if isinstance(a,dict) and _finite(a.get("time"))})


def _same_run(shots,index,key):
    value=shots[index].get(key); count=1
    for shot in shots[index+1:]:
        if shot.get(key)!=value: break
        count+=1
    return count


def _compatible_run(shots,index,limit,media_types):
    count=0
    for shot in shots[index:index+limit]:
        if shot.get("media_type") not in media_types: break
        count+=1
    return count


def _group_candidate(shots,index,compatible,block,media_by_id):
    minimum=int(block["min_media"]); maximum=min(int(block["max_media"]),compatible)
    if maximum < minimum: return None
    for count in range(maximum,minimum-1,-1):
        group=shots[index:index+count]; events={s.get("event_id") for s in group if s.get("event_id")}
        if len(events)<=1:
            return {"count":count,"score":100.0,"reasons":["same_event"]}
        pair_scores=[]; pair_evidence=[]; reasons=[]
        for left,right in zip(group,group[1:]):
            score,evidence=_pair_affinity(media_by_id.get(left.get("media_id"),{}),media_by_id.get(right.get("media_id"),{}))
            pair_scores.append(score); pair_evidence.append(evidence); reasons.extend(evidence)
        # Every crossed boundary needs affirmative evidence; a strong average
        # cannot conceal one unrelated pair inside a larger collage.
        if pair_scores and all(_strong_cross_event_affinity(score,evidence)
                               for score,evidence in zip(pair_scores,pair_evidence)):
            return {"count":count,"score":round(sum(pair_scores)/len(pair_scores),3),
                    "reasons":sorted(set(["cross_event_affinity_threshold_met","strong_semantic_evidence",*reasons]))}
    return None


def _pair_affinity(left,right):
    lv=left.get("vision") if isinstance(left.get("vision"),dict) else {}; rv=right.get("vision") if isinstance(right.get("vision"),dict) else {}
    score=0.0; reasons=[]
    for key,weight in (("travel_category",24),("activity",22),("scene_type",16)):
        a,b=lv.get(key),rv.get(key)
        if a and b and str(a).lower()==str(b).lower(): score+=weight; reasons.append(f"same_{key}:{str(a).lower()}")
    left_mood,right_mood=str(lv.get("mood") or "").lower(),str(rv.get("mood") or "").lower()
    if left_mood and left_mood==right_mood and left_mood not in GENERIC_MOODS:
        score+=10; reasons.append(f"same_mood:{left_mood}")
    ll=lv.get("landmark_hint") if isinstance(lv.get("landmark_hint"),dict) else {}; rl=rv.get("landmark_hint") if isinstance(rv.get("landmark_hint"),dict) else {}
    if ll.get("name") and rl.get("name") and str(ll["name"]).casefold()==str(rl["name"]).casefold():
        score+=24; reasons.append(f"same_landmark:{str(ll['name']).casefold()}")
    lt={str(x).casefold() for x in (lv.get("tags") or left.get("tags") or [])}; rt={str(x).casefold() for x in (rv.get("tags") or right.get("tags") or [])}
    if lt and rt:
        overlap=len(lt&rt)/len(lt|rt); score+=20*overlap
        if overlap: reasons.append(f"tag_overlap:{overlap:.3f}")
    proximity=_chronology_affinity(left.get("captured_at"),right.get("captured_at"))
    if proximity: score+=proximity; reasons.append(f"chronological_proximity:{proximity:.1f}")
    return round(min(100.0,score),3),reasons


def _strong_cross_event_affinity(score,reasons):
    """Require qualifying semantics as well as enough accumulated affinity."""
    if score < 30.0: return False
    if any(reason.startswith(("same_activity:","same_landmark:")) for reason in reasons): return True
    if any(reason.startswith("tag_overlap:") and float(reason.split(":",1)[1])>=.5 for reason in reasons): return True
    semantic=[reason for reason in reasons if reason.startswith(("same_travel_category:","same_scene_type:",
                                                                  "same_mood:","tag_overlap:"))]
    if any(reason.startswith("same_scene_type:") for reason in reasons) and len(semantic)>=2: return True
    if any(reason.startswith("chronological_proximity:") and float(reason.split(":",1)[1])>=6.0 for reason in reasons) and semantic:
        return True
    return False


def _chronology_affinity(left,right):
    if not isinstance(left,str) or not isinstance(right,str): return 0.0
    try: seconds=abs((datetime.fromisoformat(right.replace("Z","+00:00"))-datetime.fromisoformat(left.replace("Z","+00:00"))).total_seconds())
    except ValueError: return 0.0
    return 10.0 if seconds<=120 else 6.0 if seconds<=600 else 3.0 if seconds<=1800 else 0.0


def _beat_support(anchors,shots):
    if not shots: return False
    start=float(shots[0]["timeline_start_seconds"]); end=float(shots[-1]["timeline_end_seconds"])
    return sum(start-.125<=anchor<=end+.125 for anchor in anchors)>=2


def _validate_slot(slot):
    for key in ("x","y","width","height","opacity"):
        if not _finite(slot.get(key)) or not 0 <= float(slot[key]) <= 1: raise TemplateValidationError("Normalized geometry must be finite within 0..1")
    if float(slot["width"])<=0 or float(slot["height"])<=0 or float(slot["x"])+float(slot["width"])>1.000001 or float(slot["y"])+float(slot["height"])>1.000001:
        raise TemplateValidationError("Normalized geometry exceeds canvas")
    if slot.get("media_fit") not in {"fill","fit"}: raise TemplateValidationError("Unsupported media fit")
    if not isinstance(slot.get("z_order"),int) or not _finite(slot.get("rotation_degrees")): raise TemplateValidationError("Invalid layer geometry")


def _finite(value): return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(float(value))


def _validate_finite_numbers(value):
    if isinstance(value,float) and not math.isfinite(value): raise TemplateValidationError("Contract contains NaN or infinity")
    if isinstance(value,dict):
        for child in value.values(): _validate_finite_numbers(child)
    elif isinstance(value,list):
        for child in value: _validate_finite_numbers(child)
