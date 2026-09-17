"""Renderer-independent static spatial layout resolution for Visual Plans."""
from __future__ import annotations

import copy
import hashlib
import math
from typing import Any

LAYOUT_VERSION = "1.0"
FIT_MODES = frozenset({"cover", "contain"})
OVERLAP_POLICIES = frozenset({"single", "prohibited", "intentional", "temporal_replacement"})
KNOWN_STRATEGIES = frozenset({
    "fullscreen.v1", "hero_inset.v1", "two_up_vertical.v1", "two_up_horizontal.v1",
    "two_up_asymmetric_left.v1", "two_up_asymmetric_right.v1", "three_up_hero_pair.v1",
    "three_up_equal_portraits.v1", "three_up_landscape_stack.v1", "three_up_mixed_dominant.v1",
    "grid_2.v1", "grid_2_dominant.v1", "grid_3.v1", "grid_3_dominant.v1", "grid_4.v1",
    "collage_staggered_2.v1", "collage_dominant_2.v1", "collage_asymmetric_3.v1",
    "collage_fan_3.v1", "layered_cards_offset_2.v1", "layered_cards_stack_3.v1",
    "beat_montage_fullscreen.v1", "title_shell.v1", "closing_shell.v1",
})


class LayoutValidationError(ValueError):
    pass


def resolve_layouts(manifest: dict[str, Any], visual_plan: dict[str, Any], *,
                    safe_area_margin: float=.04, background_token: str="canvas_light") -> dict[str, Any]:
    """Return a copy of a Visual Plan with deterministic static layouts embedded."""
    if not isinstance(visual_plan,dict) or not isinstance(visual_plan.get("blocks"),list) or not visual_plan["blocks"]:
        raise LayoutValidationError("Visual Plan not found or empty. Run 'template-plan' first.")
    if not _finite(safe_area_margin) or not 0 <= safe_area_margin < .25:
        raise LayoutValidationError("Layout safe-area margin must be within 0..0.25")
    if not isinstance(background_token,str) or not background_token:
        raise LayoutValidationError("Layout background token is required")
    result=copy.deepcopy(visual_plan)
    media={item.get("id"):item for key in ("photos","videos") for item in manifest.get(key,[]) if isinstance(item,dict)}
    safe={"x":safe_area_margin,"y":safe_area_margin,"width":1-2*safe_area_margin,"height":1-2*safe_area_margin}
    recent=[]
    for block in result["blocks"]:
        block["resolved_layout"]=_resolve_block(block,media,safe,background_token,recent)
        validate_resolved_layout(block,media)
        recent.append(block["resolved_layout"]["strategy"])
    validate_layout_plan(result,visual_plan,media)
    return result


def validate_layout_plan(plan: object, source_plan: dict[str, Any], media: dict[str, Any]) -> None:
    if not isinstance(plan,dict) or not isinstance(plan.get("blocks"),list):
        raise LayoutValidationError("Resolved Visual Plan is invalid")
    if plan.get("duration_seconds") != source_plan.get("duration_seconds"):
        raise LayoutValidationError("Layout resolution changed Visual Plan duration")
    if len(plan["blocks"]) != len(source_plan.get("blocks",[])):
        raise LayoutValidationError("Layout resolution changed Visual Block count")
    expected=[shot_id for block in source_plan["blocks"] for shot_id in block.get("shot_ids",[])]
    actual=[slot.get("shot_id") for block in plan["blocks"]
            for slot in (block.get("resolved_layout") or {}).get("slots",[]) if isinstance(slot,dict)]
    if len(actual)!=len(set(actual)): raise LayoutValidationError("Resolved Visual Plan duplicates shot ownership")
    if actual!=expected: raise LayoutValidationError("Resolved Visual Plan shot ownership mismatch")
    for resolved,source in zip(plan["blocks"],source_plan["blocks"]):
        for key in ("visual_block_id","block_type","shot_ids","shots","event_ids","story_phase",
                    "timeline_start_seconds","timeline_end_seconds","duration_seconds"):
            if resolved.get(key)!=source.get(key):
                raise LayoutValidationError(f"Layout resolution changed Visual Block {key}")
        validate_resolved_layout(resolved,media)


def validate_resolved_layout(block: dict[str, Any], media: dict[str, Any]) -> None:
    layout=block.get("resolved_layout")
    if not isinstance(layout,dict) or layout.get("version")!=LAYOUT_VERSION:
        raise LayoutValidationError("Missing or unsupported resolved layout version")
    strategy=layout.get("strategy")
    if strategy not in KNOWN_STRATEGIES: raise LayoutValidationError("Unknown layout strategy")
    slots=layout.get("slots")
    if not isinstance(slots,list) or not slots: raise LayoutValidationError("Resolved layout requires media slots")
    if any(not isinstance(slot,dict) for slot in slots): raise LayoutValidationError("Resolved layout slot must be an object")
    if layout.get("coordinate_space")!="normalized": raise LayoutValidationError("Unsupported layout coordinate space")
    if layout.get("safe_area_policy") not in {"inside","canvas"}: raise LayoutValidationError("Invalid layout safe-area policy")
    background=layout.get("background")
    if not isinstance(background,dict) or background.get("type")!="solid" or not isinstance(background.get("token"),str) or not background["token"]:
        raise LayoutValidationError("Invalid layout background intent")
    expected_shots=list(block.get("shot_ids") or [])
    actual_shots=[slot.get("shot_id") for slot in slots if isinstance(slot,dict)]
    if len(actual_shots)!=len(set(actual_shots)): raise LayoutValidationError("Resolved layout duplicates shot ownership")
    if actual_shots!=expected_shots: raise LayoutValidationError("Resolved layout shot ownership mismatch")
    expected_media=[shot.get("media_id") for shot in block.get("shots",[]) if isinstance(shot,dict)]
    actual_media=[slot.get("media_id") for slot in slots]
    if actual_media!=expected_media: raise LayoutValidationError("Resolved layout media ownership mismatch")
    if any(media_id not in media for media_id in actual_media): raise LayoutValidationError("Resolved layout contains unknown media ID")
    orientations=[_orientation(media[media_id]) for media_id in actual_media]
    compatible={candidate["strategy"] for candidate in _strategy_candidates(block.get("block_type"),len(slots),orientations,block)}
    if strategy not in compatible: raise LayoutValidationError("Layout strategy is incompatible with block media")
    slot_ids=[slot.get("slot_id") for slot in slots]
    if any(not isinstance(value,str) or not value for value in slot_ids) or len(slot_ids)!=len(set(slot_ids)):
        raise LayoutValidationError("Resolved layout slot IDs must be unique")
    safe=layout.get("safe_area")
    _validate_rect(safe,"safe area",canvas=True)
    policy=layout.get("overlap_policy")
    if policy not in OVERLAP_POLICIES: raise LayoutValidationError("Invalid layout overlap policy")
    for slot in slots:
        _validate_slot(slot,safe,layout.get("safe_area_policy"))
    overlaps=[_overlap(a,b) for index,a in enumerate(slots) for b in slots[index+1:]]
    if policy=="prohibited" and any(overlaps): raise LayoutValidationError("Layout strategy prohibits slot overlap")
    if policy=="intentional" and len(slots)>1 and not any(overlaps):
        raise LayoutValidationError("Layout strategy requires intentional overlap")
    if policy=="intentional" and any(_overlap_ratio(a,b)>=.9 for index,a in enumerate(slots) for b in slots[index+1:]):
        raise LayoutValidationError("Intentional layout overlap exceeds bounded hierarchy")
    if block.get("block_type") in {"collage","layered_cards"}:
        z=[slot["z_index"] for slot in slots]
        if len(z)!=len(set(z)): raise LayoutValidationError("Overlapping cards require deterministic unique z-order")
    if block.get("block_type")=="layered_cards":
        primary=[slot for slot in slots if slot.get("role")=="primary"]
        if len(primary)!=1 or primary[0]["z_index"]!=max(z):
            raise LayoutValidationError("Layered cards require deterministic unique hierarchy")


def _resolve_block(block,media,safe,background_token,recent):
    shots=block.get("shots") if isinstance(block.get("shots"),list) else []
    if not shots: raise LayoutValidationError("Visual Block contains no media shots")
    kind=block.get("block_type"); count=len(shots); orientations=[_orientation(media.get(s.get("media_id"),{})) for s in shots]
    candidates=_strategy_candidates(kind,count,orientations,block)
    chosen=_choose_strategy(candidates,block,orientations,recent)
    strategy,rects,policy=chosen["strategy"],chosen["rects"],chosen["overlap_policy"]
    slots=[]
    for index,(shot,rect) in enumerate(zip(shots,rects),1):
        rotation=chosen.get("rotations",[0.0]*count)[index-1]
        z=chosen.get("z_indices",list(range(count)))[index-1]
        roles=chosen.get("roles",["primary",*["supporting"]*(count-1)])
        fit=_fit_mode(kind,orientations[index-1],rect)
        slots.append({"slot_id":f"slot-{index:03d}","shot_id":shot.get("shot_id"),"media_id":shot.get("media_id"),
                      **rect,"z_index":z,"role":roles[index-1],"fit_mode":fit,"rotation_deg":rotation,"opacity":1.0,
                      "clip":{"type":"rounded_rect" if kind in {"hero_media","two_up","three_up","grid","collage","layered_cards","closing_card"} else "rect",
                              "corner_radius_intent":"small" if kind not in {"fullscreen_media","beat_montage","title_card"} else "none"}})
    return {"version":LAYOUT_VERSION,"strategy":strategy,"coordinate_space":"normalized",
            "safe_area":dict(safe),"safe_area_policy":"canvas" if kind in {"fullscreen_media","beat_montage","title_card"} else "inside",
            "background":{"type":"solid","token":background_token},"overlap_policy":policy,"slots":slots,
            "selection_reasons":chosen["selection_reasons"],"candidate_count":len(candidates)}


def _strategy_candidates(kind,count,orientations,block):
    values=[]
    def add(strategy,rects,policy,score,reasons,**extra):
        values.append({"strategy":strategy,"rects":rects,"overlap_policy":policy,"score":score,
                       "reasons":reasons,**extra})
    if kind=="fullscreen_media" and count==1: add("fullscreen.v1",[_rect(0,0,1,1)],"single",100,["stable_fullscreen_emphasis"])
    elif kind=="hero_media" and count==1: add("hero_inset.v1",[_rect(.08,.08,.84,.84)],"single",100,["stable_inset_hero"])
    if kind=="two_up" and count==2:
        pp=all(value=="portrait" for value in orientations); ll=all(value=="landscape" for value in orientations)
        conservative=all(value in {"portrait","square","unknown"} for value in orientations)
        add("two_up_vertical.v1",[_rect(.04,.08,.44,.84),_rect(.52,.08,.44,.84)],"prohibited",30 if conservative else 19,
            ["portrait_pair" if pp else "conservative_orientation_fallback" if conservative else "vertical_pair_fallback"])
        if ll: add("two_up_horizontal.v1",[_rect(.06,.08,.88,.40),_rect(.06,.52,.88,.40)],"prohibited",42,["landscape_pair"])
        if not ll:
            mixed="landscape" in orientations and "portrait" in orientations
            add("two_up_asymmetric_left.v1",[_rect(.04,.08,.56,.84),_rect(.64,.20,.32,.58)],"prohibited",36 if mixed and orientations[0]=="portrait" else 27,
                ["mixed_orientation","portrait_primary_left"] if mixed and orientations[0]=="portrait" else ["asymmetric_diary_pair"])
            add("two_up_asymmetric_right.v1",[_rect(.04,.20,.32,.58),_rect(.40,.08,.56,.84)],"prohibited",36 if mixed and orientations[1]=="portrait" else 27,
                ["mixed_orientation","portrait_primary_right"] if mixed and orientations[1]=="portrait" else ["asymmetric_diary_pair"])
    elif kind=="three_up" and count==3:
        if all(value=="portrait" for value in orientations):
            add("three_up_equal_portraits.v1",[_rect(.04,.14,.28,.72),_rect(.36,.14,.28,.72),_rect(.68,.14,.28,.72)],"prohibited",34,["three_portrait_cards"])
        add("three_up_hero_pair.v1",[_rect(.04,.05,.92,.50),_rect(.04,.59,.44,.36),_rect(.52,.59,.44,.36)],"prohibited",32,["primary_with_two_supporting"])
        if all(value=="landscape" for value in orientations):
            add("three_up_landscape_stack.v1",[_rect(.08,.04,.84,.27),_rect(.08,.365,.84,.27),_rect(.08,.69,.84,.27)],"prohibited",42,["landscape_stack_preserves_context"])
        elif "landscape" in orientations:
            dominant=orientations.index("landscape"); supports=iter([_rect(.04,.60,.44,.35),_rect(.52,.60,.44,.35)])
            rects=[_rect(.04,.05,.92,.50) if index==dominant else next(supports) for index in range(3)]
            add("three_up_mixed_dominant.v1",rects,"prohibited",40,["landscape_dominant","mixed_orientation"])
    elif kind=="grid" and count in {2,3,4}:
        equal={2:[_rect(.04,.08,.44,.84),_rect(.52,.08,.44,.84)],
               3:[_rect(.04,.05,.44,.42),_rect(.52,.05,.44,.42),_rect(.04,.51,.92,.44)],
               4:[_rect(.04,.04,.44,.44),_rect(.52,.04,.44,.44),_rect(.04,.52,.44,.44),_rect(.52,.52,.44,.44)]}[count]
        add(f"grid_{count}.v1",equal,"prohibited",34,[f"bounded_{count}_cell_grid"])
        if count==2: add("grid_2_dominant.v1",[_rect(.04,.08,.58,.84),_rect(.66,.20,.30,.58)],"prohibited",30,["dominant_cell_hierarchy"])
        if count==3: add("grid_3_dominant.v1",[_rect(.04,.05,.58,.90),_rect(.66,.05,.30,.43),_rect(.66,.52,.30,.43)],"prohibited",38 if orientations.count("portrait")>=2 else 30,["dominant_cell_hierarchy"])
    elif kind=="collage" and count in {2,3}:
        if count==2:
            add("collage_staggered_2.v1",[_rect(.06,.10,.62,.68),_rect(.36,.30,.58,.60)],"intentional",32,["staggered_editorial_pair"],rotations=[-3,3])
            add("collage_dominant_2.v1",[_rect(.06,.08,.76,.72),_rect(.48,.50,.46,.42)],"intentional",36 if "landscape" in orientations else 30,["dominant_card_preserves_context"],rotations=[-2,2])
        else:
            add("collage_asymmetric_3.v1",[_rect(.06,.08,.70,.64),_rect(.40,.29,.54,.54),_rect(.04,.67,.38,.27)],"intentional",36,["three_card_asymmetric_collage"],rotations=[-3,3,-2])
            add("collage_fan_3.v1",[_rect(.05,.13,.54,.66),_rect(.23,.10,.54,.68),_rect(.41,.15,.54,.64)],"intentional",32,["three_card_fan"],rotations=[-5,0,5])
    elif kind=="layered_cards" and count in {2,3}:
        if count==2:
            add("layered_cards_offset_2.v1",[_rect(.14,.12,.72,.70),_rect(.06,.22,.64,.66)],"intentional",38,["primary_foreground","secondary_offset_background"],
                rotations=[1,-3],z_indices=[1,0],roles=["primary","background"])
        else:
            add("layered_cards_stack_3.v1",[_rect(.16,.12,.72,.70),_rect(.06,.20,.62,.64),_rect(.30,.25,.62,.62)],"intentional",38,["primary_foreground","two_supporting_background_cards"],
                rotations=[0,-4,4],z_indices=[2,0,1],roles=["primary","background","supporting"])
    elif kind=="beat_montage" and 2<=count<=4: add("beat_montage_fullscreen.v1",[_rect(0,0,1,1) for _ in range(count)],"temporal_replacement",100,["stable_fullscreen_replacement"])
    elif kind=="title_card" and count==1: add("title_shell.v1",[_rect(0,0,1,1)],"single",100,["title_background_shell"])
    elif kind=="closing_card" and count==1: add("closing_shell.v1",[_rect(.12,.12,.76,.68)],"single",100,["closing_memory_card"])
    if not values: raise LayoutValidationError(f"Unsupported media count for layout block: {kind}/{count}")
    return values


def _choose_strategy(candidates,block,orientations,recent):
    recent_complex=recent[-2:]
    ranked=[]
    for candidate in candidates:
        repeat_penalty=8 if candidate["strategy"] in recent_complex and len(candidates)>1 else 0
        phase_bonus=2 if block.get("story_phase") in {"experience","closing"} and "asymmetric" in candidate["strategy"] else 0
        score=candidate["score"]+phase_bonus-repeat_penalty
        reasons=list(candidate["reasons"])
        if phase_bonus: reasons.append("phase_suits_asymmetry")
        if repeat_penalty: reasons.append("recent_strategy_repetition_penalty")
        tie=_stable_tie(block,candidate["strategy"])
        ranked.append((score,tie,candidate,reasons,repeat_penalty))
    score,_,selected,reasons,penalty=max(ranked,key=lambda value:(value[0],value[1]))
    chosen=dict(selected); chosen["selection_reasons"]=[*reasons,f"orientation_signature:{'+'.join(orientations)}",f"selection_score:{score}"]
    if any(item[4] for item in ranked) and not penalty: chosen["selection_reasons"].append("compatible_alternative_preferred")
    return chosen


def _stable_tie(block,strategy):
    identity="|".join([str(block.get("block_type")),str(block.get("story_phase")),strategy,
                       *map(str,block.get("shot_ids",[])),*map(str,block.get("event_ids",[]))])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _fit_mode(kind,orientation,rect):
    slot_ratio=rect["width"]/(rect["height"]*9/16)
    if orientation=="landscape" and slot_ratio<1.15: return "contain"
    if orientation=="portrait" and slot_ratio>1.8: return "contain"
    if kind in {"hero_media","closing_card"} and orientation=="landscape": return "contain"
    return "cover"


def _validate_slot(slot,safe,safe_policy):
    if not isinstance(slot,dict): raise LayoutValidationError("Resolved layout slot must be an object")
    _validate_rect(slot,"slot")
    if not isinstance(slot.get("z_index"),int) or isinstance(slot.get("z_index"),bool) or slot["z_index"]<0:
        raise LayoutValidationError("Invalid layout z_index")
    if slot.get("fit_mode") not in FIT_MODES: raise LayoutValidationError("Invalid layout fit_mode")
    if not _finite(slot.get("rotation_deg")) or not -8 <= float(slot["rotation_deg"]) <= 8:
        raise LayoutValidationError("Invalid static layout rotation")
    if not _finite(slot.get("opacity")) or not 0 <= float(slot["opacity"]) <= 1:
        raise LayoutValidationError("Invalid static layout opacity")
    clip=slot.get("clip")
    if not isinstance(clip,dict) or clip.get("type") not in {"rect","rounded_rect"}:
        raise LayoutValidationError("Invalid layout clipping intent")
    if safe_policy=="inside" and not _contains(safe,slot): raise LayoutValidationError("Layout slot exceeds composition safe area")


def _validate_rect(rect,label,canvas=False):
    if not isinstance(rect,dict): raise LayoutValidationError(f"Invalid layout {label}")
    values=[rect.get(key) for key in ("x","y","width","height")]
    if not all(_finite(value) for value in values): raise LayoutValidationError(f"Non-finite layout {label}")
    x,y,width,height=map(float,values)
    if not 0<=x<=1 or not 0<=y<=1 or not 0<width<=1 or not 0<height<=1:
        raise LayoutValidationError(f"Invalid normalized layout {label}")
    if x+width>1.000001 or y+height>1.000001: raise LayoutValidationError(f"Layout {label} exceeds canvas")


def _rect(x,y,width,height): return {"x":x,"y":y,"width":width,"height":height}
def _finite(value): return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(float(value))
def _contains(outer,inner,tolerance=1e-6):
    return (inner["x"]+tolerance>=outer["x"] and inner["y"]+tolerance>=outer["y"] and
            inner["x"]+inner["width"]<=outer["x"]+outer["width"]+tolerance and
            inner["y"]+inner["height"]<=outer["y"]+outer["height"]+tolerance)
def _overlap(left,right,tolerance=1e-6):
    return (min(left["x"]+left["width"],right["x"]+right["width"])-max(left["x"],right["x"])>tolerance and
            min(left["y"]+left["height"],right["y"]+right["height"])-max(left["y"],right["y"])>tolerance)
def _overlap_ratio(left,right):
    width=max(0.0,min(left["x"]+left["width"],right["x"]+right["width"])-max(left["x"],right["x"]))
    height=max(0.0,min(left["y"]+left["height"],right["y"]+right["height"])-max(left["y"],right["y"]))
    return width*height/min(left["width"]*left["height"],right["width"]*right["height"])
def _orientation(item):
    width,height=item.get("width"),item.get("height")
    if not _finite(width) or not _finite(height) or width<=0 or height<=0: return "unknown"
    ratio=float(width)/float(height)
    return "square" if .9<=ratio<=1.1 else "landscape" if ratio>1.1 else "portrait"
