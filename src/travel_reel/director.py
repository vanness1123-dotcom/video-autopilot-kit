"""Deterministic, provider-neutral Creative Director editorial reasoning."""
from __future__ import annotations

import math
from collections import Counter
from statistics import mean, median
from typing import Any, Protocol, runtime_checkable

from .config import CreativeDirectorConfig
from .timing import clamp_feasible_duration, duration_bounds, expected_mix

DIRECTOR_VERSION = "1.1"
STYLES = {
    "cinematic_travel": ("cinematic", 2.55, .28),
    "travel_story": ("balanced", 2.05, .24),
    "dynamic_travel_highlight": ("dynamic", 1.60, .20),
    "beat_montage": ("fast", 1.25, .15),
}

class DirectorPrerequisiteError(ValueError): pass

@runtime_checkable
class CreativeDirectorProvider(Protocol):
    name: str
    version: str
    def direct(self, manifest: dict[str, Any], config: CreativeDirectorConfig) -> dict[str, Any]: ...

class DeterministicCreativeDirector:
    name = "deterministic-local"
    version = DIRECTOR_VERSION
    def direct(self, manifest: dict[str, Any], config: CreativeDirectorConfig) -> dict[str, Any]:
        return build_creative_direction(manifest, config)

def build_content_profile(manifest: dict[str, Any]) -> dict[str, Any]:
    items = _media(manifest); scored = [x for x in items if _score(x) is not None]
    events = manifest.get("events", {}).get("items", [])
    categories = Counter(str(_vision(x).get("travel_category") or "other") for x in items)
    scenes = Counter(str(_vision(x).get("scene_type") or "unknown") for x in items)
    activities = Counter(str(_vision(x).get("activity")) for x in items if _vision(x).get("activity"))
    event_importance = [round(float(event.get("evidence_score", 0)), 3)
                        for event in events if isinstance(event, dict)]
    scores = [_score(x) for x in scored]
    quality_floor = max(65.0, (median(scores) - 8.0) if scores else 65.0)
    fingerprints = []
    for item in scored:
        metadata = _vision(item).get("vision_metadata")
        fingerprint = metadata.get("source_fingerprint") if isinstance(metadata, dict) else None
        if isinstance(fingerprint, str) and fingerprint: fingerprints.append(fingerprint)
    suppressed_count = sum(count-1 for count in Counter(fingerprints).values() if count > 1)
    def prevalence(predicate: Any) -> float:
        return round(sum(bool(predicate(x)) for x in items) / len(items), 3) if items else 0.0
    profile = {
        "source_media_count": len(items), "usable_scored_media_count": len(scored),
        "photo_count": len(manifest.get("photos", [])), "video_count": len(manifest.get("videos", [])),
        "event_count": len(events), "event_sizes": sorted(len(e.get("media_ids", [])) for e in events if isinstance(e, dict)),
        "category_distribution": dict(sorted(categories.items())), "scene_distribution": dict(sorted(scenes.items())),
        "activity_distribution": dict(sorted(activities.items())),
        "event_importance_distribution": sorted(event_importance, reverse=True),
        "people_prevalence": prevalence(lambda x: _people(x).get("visible") is True),
        "selfie_prevalence": prevalence(lambda x: _people(x).get("selfie") is True),
        "group_photo_prevalence": prevalence(lambda x: _people(x).get("group_photo") is True),
        "landmark_prevalence": prevalence(lambda x: _category(x) == "landmark" or _landmark(x)),
        "activity_prevalence": prevalence(lambda x: bool(_vision(x).get("activity")) or _category(x) == "activity"),
        "food_prevalence": prevalence(lambda x: _category(x) in {"food", "cafe"}),
        "transportation_prevalence": prevalence(lambda x: _category(x) in {"transportation", "arrival"}),
        "theme_park_prevalence": prevalence(lambda x: _category(x) in {"theme_park", "attraction"}),
        "nightlife_prevalence": prevalence(lambda x: _category(x) == "nightlife"),
        "motion_density": round(len(manifest.get("videos", [])) / len(items), 3) if items else 0.0,
        "score_distribution": {"minimum": round(min(scores), 3), "mean": round(mean(scores), 3), "median": round(median(scores), 3), "maximum": round(max(scores), 3)} if scores else {},
        "duplicate_pressure": round(suppressed_count / len(scored), 3) if scored else 0.0,
        "editorial_capacity": max(0, len(scored)-suppressed_count),
        "quality_floor": round(quality_floor, 3),
        "strong_usable_capacity": sum(value >= quality_floor for value in scores),
        "event_diversity": round(min(1.0, len(events) / max(1, math.sqrt(len(items)))), 3),
        "content_diversity": round(min(1.0, (len(categories) + len(scenes) + min(6, len(activities))) / 18), 3),
    }
    profile["editorial_density"] = round(min(1.0, .45 * profile["content_diversity"] + .35 * profile["event_diversity"] + .20 * (1-profile["duplicate_pressure"])), 3)
    return profile

def build_creative_direction(manifest: dict[str, Any], config: CreativeDirectorConfig) -> dict[str, Any]:
    events = manifest.get("events")
    if not isinstance(events, dict) or not isinstance(events.get("items"), list) or not events["items"]:
        raise DirectorPrerequisiteError("Event intelligence not found. Run 'events' first.")
    profile = build_content_profile(manifest)
    if profile["usable_scored_media_count"] <= 0: raise DirectorPrerequisiteError("Scored media not found. Run 'score' first.")
    style = config.style if config.style != "auto" else _recommend(profile)
    pacing, _, _ = STYLES[style]
    usable = min(profile["editorial_capacity"], max(1, profile["strong_usable_capacity"]))
    event_coverage = min(usable, profile["event_count"])
    density_rate = {"cinematic_travel": .55, "travel_story": .75,
                    "dynamic_travel_highlight": .90, "beat_montage": 1.05}[style]
    diversity_capacity = round(6 + 18 * profile["editorial_density"] + 12 * profile["event_diversity"])
    target = max(1, min(usable, max(event_coverage, round(diversity_capacity * density_rate))))
    minimum = min(target, max(1, round(target * .82)))
    maximum = min(usable, max(target, round(target * 1.18)))
    preferred_photos, preferred_videos = expected_mix(target, profile["video_count"], style)
    safe_low, editorial_preferred, safe_high = duration_bounds(preferred_photos, preferred_videos, style)
    if config.duration_mode == "fixed":
        resolved = clamp_feasible_duration(config.target_duration_seconds, safe_low, safe_high,
                                            config.target_duration_seconds, config.target_duration_seconds)
        duration_min = duration_max = resolved
    elif safe_high < config.min_duration_seconds:
        resolved = safe_high
        duration_min, duration_max = safe_low, safe_high
    else:
        resolved = clamp_feasible_duration(editorial_preferred, safe_low, safe_high,
                                            config.min_duration_seconds, config.max_duration_seconds)
        duration_min = round(max(config.min_duration_seconds, safe_low), 3)
        duration_max = round(min(config.max_duration_seconds, safe_high), 3)
    videos_available = profile["video_count"]
    video_min, video_max = max(0, preferred_videos-1), min(videos_available, preferred_videos+2, target)
    photo_center = preferred_photos
    photo_min, photo_max = max(0, photo_center-2), min(profile["photo_count"], photo_center+2, target)
    duration_reasons = [
        f"strong_usable_capacity:{usable}", f"event_coverage:{event_coverage}",
        f"editorial_density:{profile['editorial_density']:.3f}",
        f"duplicate_pressure:{profile['duplicate_pressure']:.3f}",
        f"motion_density:{profile['motion_density']:.3f}", f"style_timing:{style}",
        f"safe_bounds_seconds:{safe_low:.3f}..{safe_high:.3f}", "viewer_fatigue_cap_applied",
    ]
    if safe_high < config.min_duration_seconds:
        duration_reasons.append("content_limited_below_configured_minimum")
    duration_strategy = {"mode": config.duration_mode, "minimum_seconds": duration_min,
        "preferred_seconds": round(editorial_preferred, 3), "resolved_seconds": resolved,
        "maximum_seconds": duration_max, "flexibility_seconds": round(min(5.0, resolved-duration_min, duration_max-resolved), 3),
        "safe_shot_bounds_seconds": {"minimum": safe_low, "maximum": safe_high}, "rationale": duration_reasons}
    budget = {"editorial_target": target, "final_target": target,
              "target_shots": target, "minimum_shots": minimum, "maximum_shots": maximum,
              "minimum_score": profile["quality_floor"],
              "preferred_photos": {"minimum": min(photo_min, photo_max), "maximum": photo_max},
              "preferred_videos": {"minimum": min(video_min, video_max), "maximum": video_max},
              "rationale": [f"{pacing} style-aware editorial density", "bounded by strong duplicate-adjusted media", "jointly feasible with resolved duration"]}
    event_strategy = _allocate_events(manifest, target)
    template = {"primary": {"cinematic_travel":"cinematic_sequence", "travel_story":"clean_cut", "dynamic_travel_highlight":"mixed_media_highlight", "beat_montage":"beat_montage"}[style],
                "beat_sync_intent": "high" if style == "beat_montage" else "medium" if pacing in {"dynamic","fast"} else "low",
                "photo_burst_allowed": config.allow_photo_burst and style in {"dynamic_travel_highlight","beat_montage"},
                "multi_frame_allowed": style == "beat_montage",
                "transition_intensity": "high" if pacing == "fast" else "medium" if pacing == "dynamic" else "low",
                "density_intent": pacing, "event_continuity": config.event_continuity,
                "breathing_points": style != "beat_montage"}
    return {"version":"1.1", "director_version":DIRECTOR_VERSION, "provider":"deterministic-local", "style":style,
            "content_profile":profile, "pacing":{"overall":pacing, "phases":{"hook":"fast", "body":pacing, "highlight":"fast", "closing":"balanced"}},
            "duration_strategy":duration_strategy, "media_budget":budget, "event_strategy":event_strategy, "template_strategy":template,
            "music_strategy":{"energy":"high" if pacing in {"dynamic","fast"} else "medium", "beat_driven":pacing in {"dynamic","fast"}, "pacing_alignment":"strong", "approximate_duration_seconds":resolved, "duration_flexibility_seconds":duration_strategy["flexibility_seconds"], "preferred_structure":["hook","build","peak","release"]},
            "rationale":[f"selected {style} from persisted content evidence" if config.style == "auto" else f"honored explicit style override: {style}"],
            "validation":{"valid":True, "target_feasible":target <= usable and safe_low <= resolved <= safe_high, "allocation_total":sum(x["target_representation"] for x in event_strategy.values())}}

def _recommend(p: dict[str, Any]) -> str:
    if p["usable_scored_media_count"] >= 30 and p["editorial_density"] >= .72 and p["duplicate_pressure"] < .35: return "beat_montage"
    if p["usable_scored_media_count"] >= 24 and (p["theme_park_prevalence"] + p["activity_prevalence"] >= .25 or p["motion_density"] >= .22): return "dynamic_travel_highlight"
    if p["event_count"] >= 4 and (p["people_prevalence"] >= .18 or p["content_diversity"] >= .55): return "travel_story"
    return "cinematic_travel"

def _allocate_events(manifest: dict[str, Any], target: int) -> dict[str, Any]:
    by_id = {x.get("id"):x for x in _media(manifest)}; ranked=[]
    events = manifest["events"]["items"]
    for event in events:
        media=[by_id[x] for x in event.get("media_ids",[]) if x in by_id]; scores=[_score(x) or 0 for x in media]
        capacity=_unique_capacity(media)
        unique_categories=len({_category(x) for x in media}); mix=event.get("media_mix",{})
        semantics = (bool(event.get("activities")) + (event.get("dominant_category") in {"landmark","activity","theme_park"}) + any(_people(x).get("visible") for x in media))
        value=(max(scores,default=0)*.38 + (mean(scores) if scores else 0)*.27 + min(12,capacity)*1.0 + unique_categories*3 + (bool(mix.get("photos")) and bool(mix.get("videos")))*5 + float(event.get("evidence_score",0))*8 + semantics*4)
        ranked.append((event["event_id"], value, capacity, event))
    ranked.sort(key=lambda x:(-x[1],x[0])); alloc={eid:1 for eid,_,size,_ in ranked[:target] if size}; remaining=max(0,target-sum(alloc.values()))
    while remaining:
        eligible=[x for x in ranked if alloc.get(x[0],0)<x[2]]
        if not eligible: break
        pick=max(eligible,key=lambda x:(x[1]/(1+alloc[x[0]]*.75),-alloc[x[0]],x[0])); alloc[pick[0]]+=1; remaining-=1
    result={}
    for index,(eid,value,size,event) in enumerate(ranked):
        role="major_experience" if index < max(1,len(ranked)//3) else "supporting_experience" if index < max(2,2*len(ranked)//3) else "context"
        result[eid]={"importance":"high" if role=="major_experience" else "supporting" if role=="supporting_experience" else "context", "importance_score":round(value,3), "target_representation":alloc.get(eid,0), "editorial_role":role, "available_media":size}
    return dict(sorted(result.items()))

def _media(m): return [x for k in ("photos","videos") for x in m.get(k,[]) if isinstance(x,dict)]
def _vision(x): return x.get("vision") if isinstance(x.get("vision"),dict) else {}
def _people(x):
    p=_vision(x).get("people"); return p if isinstance(p,dict) else {}
def _category(x): return str(_vision(x).get("travel_category") or "other")
def _landmark(x):
    h=_vision(x).get("landmark_hint"); return bool(h.get("name")) if isinstance(h,dict) else False
def _score(x):
    s=x.get("score"); return float(s["total"]) if isinstance(s,dict) and isinstance(s.get("total"),(int,float)) else None
def _unique_capacity(media):
    fingerprints=set(); anonymous=0
    for item in media:
        metadata=_vision(item).get("vision_metadata"); fingerprint=metadata.get("source_fingerprint") if isinstance(metadata,dict) else None
        if isinstance(fingerprint,str) and fingerprint: fingerprints.add(fingerprint)
        else: anonymous+=1
    return len(fingerprints)+anonymous
