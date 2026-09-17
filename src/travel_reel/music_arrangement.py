"""Deterministic, bounded music strategy generation and FFmpeg assembly."""
from __future__ import annotations

import itertools
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import MusicConfig
from .music import effective_beat_grid, interpret_tempo

ARRANGEMENT_VERSION = "1.0"


class MusicAssemblyError(RuntimeError):
    pass


def generate_strategies(candidates: list[dict[str, Any]], profile: dict[str, Any],
                        direction: dict[str, Any], story: dict[str, Any], config: MusicConfig) -> dict[str, Any]:
    target, low, high = _duration_envelope(direction)
    phases = list(dict.fromkeys(x.get("section") for x in story.get("sequence", []) if x.get("section")))
    prepared = []
    for candidate in candidates:
        analysis = candidate["analysis"]; track = candidate["track"]
        interpretation = interpret_tempo(analysis, profile)
        duration = float(analysis["duration_seconds"])
        single = duration >= low
        candidate["eligibility"] = {"engineering_usable": True, "single_track_eligible": single,
                                    "multi_track_eligible": duration >= 4.0,
                                    "production_ready": bool(track.get("production_ready"))}
        candidate["tempo_interpretation"] = interpretation
        if single:
            length = _single_length(candidate, target, low, high)
            segment = _segment(candidate, 0, length, 0, length, phases, interpretation, "complete_arc")
            prepared.append(_strategy("single_track", [segment], [], length,
                                      _single_score(candidate, interpretation), config))
    pool = sorted((c for c in candidates if c["eligibility"]["multi_track_eligible"]),
                  key=lambda c: (-c["music_match_score"], c["track"]["track_id"]))[:config.max_arrangement_pool]
    multi = []
    for count in range(2, min(config.max_arrangement_tracks, len(pool)) + 1):
        for combo in itertools.combinations(pool, count):
            # Evaluate one deterministic editorial order plus its energy-rising order.
            orders = [combo, tuple(sorted(combo, key=lambda c: (_mean_energy(c), c["track"]["track_id"])))]
            seen_orders = set()
            for order in orders:
                identity = tuple(c["track"]["fingerprint"] for c in order)
                if identity in seen_orders or len(set(identity)) != count: continue
                seen_orders.add(identity)
                built = _build_multi(order, target, low, high, phases, profile, config)
                if built: multi.append(built)
    multi.sort(key=lambda x: (-x["strategy_score"], x["strategy_id"]))
    singles = sorted(prepared, key=lambda x: (-x["strategy_score"], x["strategy_id"]))
    best_single = singles[0] if singles else None; best_multi = multi[0] if multi else None
    winner = best_single or best_multi
    reasons = []
    margin = None
    if best_single and best_multi:
        margin = round(best_multi["strategy_score"] - best_single["strategy_score"], 3)
        if margin >= config.multi_track_decision_margin:
            winner = best_multi; reasons.append(f"multi_exceeds_single_by_{margin:.3f}")
        else:
            winner = best_single; reasons.append(f"single_retained_margin_{margin:.3f}_below_{config.multi_track_decision_margin:.3f}")
    elif winner:
        reasons.append("only_feasible_strategy_type")
    alternatives = sorted([x for x in singles + multi if x is not winner],
                          key=lambda x: (-x["strategy_score"], x["strategy_id"]))[:5]
    return {"version": ARRANGEMENT_VERSION, "single_track_candidates": singles,
            "multi_track_candidates": multi, "winner": winner, "alternatives": alternatives,
            "decision_margin": margin, "decision_reasons": reasons,
            "validation": {"feasible_strategy_count": len(singles)+len(multi), "duration_envelope_seconds":
                           {"minimum": low, "target": target, "maximum": high}}}


def _build_multi(order, target, low, high, phases, profile, config):
    overlap = config.crossfade_seconds
    available = sum(float(c["analysis"]["duration_seconds"]) for c in order) - overlap*(len(order)-1)
    if available < low: return None
    timeline_duration = min(high, max(low, target))
    gross = timeline_duration + overlap*(len(order)-1)
    weights = [max(4.0, min(float(c["analysis"]["duration_seconds"]), gross/len(order))) for c in order]
    scale = gross/sum(weights); lengths = [w*scale for w in weights]
    if any(length > float(c["analysis"]["duration_seconds"])+1e-6 for length, c in zip(lengths, order)):
        remaining = gross; lengths=[]
        for index,c in enumerate(order):
            slots=len(order)-index; length=min(float(c["analysis"]["duration_seconds"]), remaining/max(1,slots))
            lengths.append(length); remaining-=length
        if remaining > .001: return None
    # Quantize the contribution budget once. Independently rounding repeating
    # thirds (for example 13.666...) can otherwise add a stray millisecond.
    lengths = [round(length, 3) for length in lengths]
    lengths[-1] = round(gross - sum(lengths[:-1]), 3)
    final_capacity = float(order[-1]["analysis"]["duration_seconds"])
    if lengths[-1] > final_capacity:
        excess = round(lengths[-1] - final_capacity, 3)
        for index in range(len(lengths) - 1):
            spare = round(float(order[index]["analysis"]["duration_seconds"]) - lengths[index], 3)
            shift = min(excess, max(0.0, spare))
            lengths[index] = round(lengths[index] + shift, 3)
            excess = round(excess - shift, 3)
            if not excess: break
        lengths[-1] = round(gross - sum(lengths[:-1]), 3)
    if lengths[-1] <= 0 or lengths[-1] > final_capacity:
        return None
    segments=[]; transitions=[]; cursor=0.0
    interpretations=[interpret_tempo(c["analysis"], profile) for c in order]
    for index,(c,length,interp) in enumerate(zip(order,lengths,interpretations)):
        source_start=_musical_start(c,length,index==len(order)-1)
        timeline_start=round(cursor,3)
        timeline_end=timeline_duration if index == len(order)-1 else round(timeline_start+length,3)
        role="opening" if index==0 else "closing" if index==len(order)-1 else "build"
        mapped=phases[round(index*(len(phases)-1)/max(1,len(order)-1)):] if index==len(order)-1 else phases[
            round(index*len(phases)/len(order)):round((index+1)*len(phases)/len(order))]
        segments.append(_segment(c,source_start,source_start+length,timeline_start,timeline_end,mapped,interp,role))
        if index:
            transition=_transition(order[index-1],c,interpretations[index-1],interp, timeline_start, overlap)
            transitions.append(transition)
        cursor=timeline_end-overlap
    timeline=round(timeline_duration,3)
    score=_multi_score(order,interpretations,transitions,segments,config)
    return _strategy("multi_track",segments,transitions,timeline,score,config)


def _segment(c,start,end,tstart,tend,phases,interp,role):
    analysis=c["analysis"]; track=c["track"]
    boundaries=[p for p in analysis.get("phrases",[]) if abs(float(p.get("start",0))-start)<.251 or abs(float(p.get("end",0))-end)<.251]
    return {"track_id":track["track_id"],"filename":track["file_name"],"fingerprint":track["fingerprint"],
            "path":track.get("path"),"source_duration_seconds":round(float(analysis["duration_seconds"]),3),
            "source_start_seconds":round(start,3),"source_end_seconds":round(end,3),
            "timeline_start_seconds":round(tstart,3),"timeline_end_seconds":round(tend,3),
            "detected_bpm":interp["detected_bpm"],"effective_bpm":interp["effective_bpm"],
            "tempo_provenance":interp["tempo_interpretation"],"tempo_interpretation_confidence":interp["tempo_interpretation_confidence"],
            "production_ready":bool(track.get("production_ready")),
            "story_phase_mapping":list(phases),"energy_role":role,
            "boundary_evidence":{"phrase_boundary":bool(boundaries),"basis":"phrase_or_source_boundary"},
            "_sync_anchors":_global_anchors(analysis,interp,start,tstart,end)}


def _global_anchors(analysis,interp,start,tstart,end):
    return [{"time":round(tstart+a["time"]-start,3),"provenance":a["provenance"],"confidence":a["confidence"]}
            for a in effective_beat_grid(analysis,interp) if start <= a["time"] <= end]


def _transition(left,right,li,ri,position,duration):
    lb,rb=li.get("effective_bpm"),ri.get("effective_bpm")
    tempo=50 if not lb or not rb else max(0,100-abs(float(lb)-float(rb))*2)
    energy=max(0,100-abs(_mean_energy(left)-_mean_energy(right))*100)
    score=round(.65*tempo+.35*energy,3)
    return {"from_track_id":left["track"]["track_id"],"to_track_id":right["track"]["track_id"],
            "timeline_position_seconds":round(position,3),"type":"short_crossfade" if duration else "cut",
            "duration_seconds":round(duration,3),"transition_score":score,
            "evidence":{"tempo_compatibility":round(tempo,3),"energy_continuity":round(energy,3),
                        "harmonic_compatibility":"not_analyzed"},"reason":"tempo_energy_phrase_boundary_evidence"}


def _strategy(kind,segments,transitions,duration,score,config):
    identity="|".join(s["track_id"] for s in segments)
    anchor_map={round(float(a["time"]),3):a for s in segments for a in s.get("_sync_anchors", [])
                if 0 <= float(a["time"]) <= float(duration)}
    transition_quality=(sum(t["transition_score"] for t in transitions)/len(transitions)) if transitions else 100.0
    production=sum(bool(s.get("production_ready")) for s in segments)/len(segments)*100 if segments else 0
    components={"duration_feasibility":100.0,"tempo_pacing_fit":score,"beat_confidence":
                sum(float(s.get("tempo_interpretation_confidence",0)) for s in segments)/max(1,len(segments))*100,
                "energy_arc":score,"story_arc_fit":100.0 if all(s["story_phase_mapping"] for s in segments) else 50.0,
                "peak_usefulness":score,"ending_quality":90.0,"transition_quality":transition_quality,
                "style_compatibility":score,"coverage_quality":100.0,"metadata_readiness":production,
                "analysis_reliability":score,"complexity_penalty":config.track_switch_penalty*(len(segments)-1)}
    public_segments=[{k:v for k,v in s.items() if k != "_sync_anchors"} for s in segments]
    return {"strategy_id":f"{kind}:{identity}","strategy_type":kind,"strategy_score":round(score,3),
            "timeline_duration_seconds":round(duration,3),"track_count":len(segments),"segments":public_segments,
            "transitions":transitions,"complexity_penalty":round(config.track_switch_penalty*(len(segments)-1),3),
            "score_components":{k:round(v,3) for k,v in components.items()},
            "feasible":True,"sync_anchors":[anchor_map[k] for k in sorted(anchor_map)]}


def _single_score(c,interp):
    bpm=interp.get("effective_bpm"); detected=(c["analysis"].get("tempo") or {}).get("bpm")
    adjustment=5 if bpm and detected and bpm != detected else 0
    return min(100,float(c["music_match_score"])+adjustment)


def _multi_score(order,interps,transitions,segments,config):
    base=sum(float(c["music_match_score"]) for c in order)/len(order)
    transition=sum(t["transition_score"] for t in transitions)/max(1,len(transitions))
    energies=[_mean_energy(c) for c in order]
    arc=100 if energies[-1]>=energies[0] else 65
    ending=90 if segments[-1]["source_end_seconds"] >= segments[-1]["source_duration_seconds"]-.25 else 55
    return max(0,min(100,.55*base+.2*transition+.15*arc+.1*ending-config.track_switch_penalty*(len(order)-1)))


def _single_length(c,target,low,high):
    alignment=c["alignment"].get("music_aligned_duration")
    return round(min(float(c["analysis"]["duration_seconds"]), high, float(alignment if alignment is not None else target)),3)


def _musical_start(c,length,closing):
    duration=float(c["analysis"]["duration_seconds"])
    if closing: return round(max(0,duration-length),3)
    options=[float(p.get("start",0)) for p in c["analysis"].get("phrases",[]) if float(p.get("start",0))+length<=duration+.001]
    return round(options[0] if options else 0,3)


def _mean_energy(c):
    values=[float(x.get("energy",0)) for x in c["analysis"].get("energy_curve",[])]
    return sum(values)/max(1,len(values))


def _duration_envelope(direction):
    d=direction.get("duration_strategy",{}); target=float(d.get("resolved_seconds",40)); flex=max(0,float(d.get("flexibility_seconds",0)))
    safe=d.get("safe_shot_bounds_seconds",{})
    low=max(float(d.get("minimum_seconds",target)),float(safe.get("minimum",0)),target-flex)
    high=min(float(d.get("maximum_seconds",target)),float(safe.get("maximum",target+flex)),target+flex)
    return round(target,3),round(low,3),round(high,3)


def build_assembly_command(ffmpeg: str, strategy: dict[str, Any], output: Path) -> list[object]:
    segments=strategy["segments"]; command: list[object]=[ffmpeg,"-y","-hide_banner","-loglevel","error"]
    for segment in segments: command += ["-i",segment["path"]]
    chains=[]
    for i,s in enumerate(segments):
        chains.append(f"[{i}:a]atrim=start={s['source_start_seconds']:.3f}:end={s['source_end_seconds']:.3f},asetpts=PTS-STARTPTS[a{i}]")
    if len(segments)==1: label="a0"
    else:
        label="a0"
        for i,t in enumerate(strategy["transitions"],1):
            out=f"mix{i}"
            if t["type"] == "short_crossfade":
                chains.append(f"[{label}][a{i}]acrossfade=d={t['duration_seconds']:.3f}:c1=tri:c2=tri[{out}]")
            else:
                chains.append(f"[{label}][a{i}]concat=n=2:v=0:a=1[{out}]")
            label=out
    chains.append(f"[{label}]atrim=duration={strategy['timeline_duration_seconds']:.3f},asetpts=PTS-STARTPTS[outa]")
    command += ["-filter_complex",";".join(chains),"-map","[outa]","-vn","-c:a","aac","-b:a","192k",output]
    return command


def assemble_music(strategy: dict[str, Any], output: Path, config: MusicConfig,
                   runner: Callable[[Sequence[object]], subprocess.CompletedProcess[str]] | None=None) -> dict[str, Any]:
    run=runner or (lambda c: subprocess.run([str(x) for x in c],capture_output=True,text=True,check=False))
    output.parent.mkdir(parents=True,exist_ok=True); pending=output.with_name(output.stem+".tmp"+output.suffix)
    command=build_assembly_command("ffmpeg",strategy,pending); result=run(command)
    if result.returncode or not pending.is_file() or pending.stat().st_size==0:
        pending.unlink(missing_ok=True); raise MusicAssemblyError(f"FFmpeg music assembly failed: {(result.stderr or '')[-500:]}")
    probe=run(["ffprobe","-v","error","-show_entries","format=duration","-of","json",pending])
    try: actual=float(json.loads(probe.stdout)["format"]["duration"])
    except Exception as exc:
        pending.unlink(missing_ok=True); raise MusicAssemblyError("Could not validate assembled music duration") from exc
    expected=float(strategy["timeline_duration_seconds"])
    if abs(actual-expected)>config.assembly_duration_tolerance_seconds:
        pending.unlink(missing_ok=True); raise MusicAssemblyError(f"Assembled duration {actual:.3f}s does not match {expected:.3f}s")
    os.replace(pending,output)
    return {"status":"assembled","path":str(output),"duration_seconds":round(actual,3),"expected_duration_seconds":expected,
            "tolerance_seconds":config.assembly_duration_tolerance_seconds}
