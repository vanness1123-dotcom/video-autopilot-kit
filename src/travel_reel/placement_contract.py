"""Overlay 1.1 placement authority, compact persistence and validation.

Source overlays are retained, including omissions. Only selected_overlay() may
interpret a decision as renderable text; legacy safe flags are not collision proof.
Structural loading needs no local fonts. Live validation can replay resolution.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter

from . import placement, placement_geometry as geometry
from .typography import TypographyConfig, TypographyResolver, validate_typography
from .typography_layout import TypographyFitError

VERSION = '1.0'
POLICY = 'placement_collision.v1'
SAFETY_SCOPE = {
    'version': 'geometric_scope.v1',
    'checked': ['canvas_bounds', 'layout_design_margin', 'protected_layout_slots',
                'co_visible_text_reservations', 'supported_motion_sweeps', 'required_host_containment'],
    'unassessed': ['faces', 'people', 'landmarks', 'salient_subjects', 'unmeasured_decorations',
                   'platform_ui', 'rounded_corner_free_space', 'plates'],
}
REJECTIONS = {'invalid_candidate_geometry', 'typography_fit_failure', 'no_valid_host',
              'static_collision', 'motion_collision', 'host_containment_failure'}
OMISSIONS = {'no_valid_host', 'all_candidates_typography_failure', 'candidate_budget_exhausted',
             'all_candidates_collision', 'all_candidates_invalid'}
SHA = re.compile(r'[0-9a-f]{64}\Z')


class PlacementContractError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def dependency_fingerprint(block, manifest, canvas):
    """Project authoritative input only, never prior decisions or runtime state."""
    sources = []
    for o in block['resolved_overlay']['overlays']:
        sources.append({k: copy.deepcopy(o[k]) for k in
                        ('overlay_id','type','target','time_space','visibility','content','placement',
                         'style','z_order','resolved_typography') if k in o})
    layout = block['resolved_layout']
    slots = [{k:s[k] for k in ('slot_id','shot_id','media_id','x','y','width','height','z_index',
                               'role','fit_mode','rotation_deg','opacity','clip')} for s in layout['slots']]
    layers = [{k:l[k] for k in ('shot_id','editorial_timing','visual_layer_timing')}
              for l in block['layout']['layers']]
    ids = {s['media_id'] for s in slots}
    media = [{k:m.get(k) for k in ('id','width','height','orientation')}
             for collection in ('photos','videos') for m in manifest[collection] if m['id'] in ids]
    return digest({'version':VERSION,'policy':POLICY,'candidate_policy':placement.POLICY_VERSION,
                   'canvas':canvas,'sources':sources,'layout':{'version':layout['version'],
                   'safe_area':layout['safe_area'],'safe_area_policy':layout['safe_area_policy'],
                   'overlap_policy':layout['overlap_policy'],'slots':slots},
                   'motion':{'version':block['resolved_motion']['version'],
                             'time_space':block['resolved_motion']['time_space'],
                             'tracks':block['resolved_motion']['tracks']},
                   'layers':layers,'media':media,'block_type':block['block_type'],
                   'block_start':block['timeline_start_seconds'],'block_end':block['timeline_end_seconds']})


def selected_overlay(source, decision):
    """Return isolated final authority, or None for omitted editorial source."""
    outcome = decision['outcome']
    if outcome == 'omitted':
        return None
    if outcome not in {'preferred','alternate'}:
        raise PlacementContractError('Unknown placement outcome')
    result = copy.deepcopy(source)
    if outcome == 'alternate':
        result['placement'] = copy.deepcopy(decision['selected_placement'])
        result['style']['alignment'] = result['placement']['alignment']
        result['resolved_typography'] = copy.deepcopy(decision['selected_typography'])
    return result


def _serialize(source, decision):
    rejected = [e for e in decision.evaluations if not e.accepted]
    # One primary reason per rejected candidate: histogram sums exactly to rejected_count.
    counts = Counter(e.reasons[0] for e in rejected)
    selected = decision.selected
    record = {'overlay_id':source['overlay_id'],'outcome':decision.outcome.lower(),
              'preferred_placement_fingerprint':digest(source['placement']),
              'selected_candidate_id':selected.candidate.candidate_id if selected else None,
              'placement_authority':'preferred' if decision.outcome=='PREFERRED' else 'selected' if selected else 'none',
              'typography_authority':'preferred' if decision.outcome=='PREFERRED' else 'selected' if selected else 'none',
              'static_result':selected.static.status.lower() if selected else 'not_selected',
              'motion_result':selected.motion.status.lower() if selected else 'not_selected',
              'safety_status':'geometric_policy_pass' if selected else 'not_renderable',
              'reason_codes':[decision.reason], 'candidate_count':decision.candidate_count,
              'evaluated_count':len(decision.evaluations),'rejected_count':len(rejected),
              'rejected_counts':dict(sorted(counts.items())), 'truncated':decision.truncated}
    if decision.outcome=='ALTERNATE':
        record['selected_placement'] = selected.candidate.placement
        record['selected_typography'] = copy.deepcopy(selected.typography)
    return record


def resolve_plan_placement(manifest, plan, config=None):
    """Measure preferred text without dropping fit failures, then resolve in order."""
    from .motion import validate_motion_plan
    from .overlay import validate_overlay_plan
    validate_motion_plan(plan,plan,manifest)
    result = copy.deepcopy(plan)
    config = config or TypographyConfig()
    canvas = {'width':config.design_width,'height':config.design_height}
    resolver = TypographyResolver(config)
    for index, block in enumerate(result['blocks']):
        contract = block['resolved_overlay']
        contract.pop('placement_resolution',None)
        contract['version'] = '1.0'
        # Never keep stale preferred metrics after a fit failure.
        for source in contract['overlays']:
            source.pop('resolved_typography',None)
            try:
                source['resolved_typography'] = resolver.resolve(source)
            except TypographyFitError:
                pass
        records, reservations = [], []
        for source in contract['overlays']:
            decision = placement.resolve_placement(manifest,result,index,source,config,other_texts=reservations)
            record = _serialize(source,decision)
            records.append(record)
            final = selected_overlay(source,record)
            if final is not None:
                if decision.outcome=='PREFERRED' and source.get('resolved_typography') != decision.selected.typography:
                    raise PlacementContractError('Preferred Typography environment changed during resolution')
                reservations.append(geometry.text_reservation(final,geometry.Canvas(**canvas)))
        contract['version'] = '1.1'
        contract['placement_resolution'] = {
            'version':VERSION,'policy_version':POLICY,'candidate_policy_version':placement.POLICY_VERSION,
            'coordinate_space':'canvas_normalized','design_canvas':canvas.copy(),
            'dependency_fingerprint':dependency_fingerprint(block,manifest,canvas),
            'safety_scope':copy.deepcopy(SAFETY_SCOPE),'decisions':records}
    validate_overlay_plan(result,plan,manifest)
    return result


def validate_placement_resolution(block, manifest):
    """Strict structural/dependency/geometry validation without font filesystem I/O."""
    def need(ok,message):
        if not ok: raise PlacementContractError(message)
    def count(n): return type(n) is int and 0 <= n <= placement.MAX_CANDIDATES
    try:
        contract = block['resolved_overlay']; value = contract['placement_resolution']
        fields = {'version','policy_version','candidate_policy_version','coordinate_space','design_canvas',
                  'dependency_fingerprint','safety_scope','decisions'}
        need(isinstance(value,dict) and set(value)==fields,'Malformed Placement resolution')
        need(value['version']==VERSION and value['policy_version']==POLICY and
             value['candidate_policy_version']==placement.POLICY_VERSION,'Unsupported Placement policy/version')
        need(value['coordinate_space']=='canvas_normalized','Unsupported Placement coordinates')
        c=value['design_canvas']
        need(isinstance(c,dict) and set(c)=={'width','height'} and
             all(type(n) is int and n>0 for n in c.values()) and c['width']*16==c['height']*9,'Invalid Placement canvas')
        canvas=geometry.Canvas(**c)
        need(value['safety_scope']==SAFETY_SCOPE,'Invalid geometric safety scope')
        fp=value['dependency_fingerprint']
        need(isinstance(fp,str) and SHA.fullmatch(fp) is not None and
             fp==dependency_fingerprint(block,manifest,c),'Stale/malformed Placement dependency')
        sources=contract['overlays']; decisions=value['decisions']
        need(isinstance(decisions,list) and len(decisions)==len(sources),'Missing/extra Placement decision')
        ids=[d.get('overlay_id') for d in decisions if isinstance(d,dict)]
        need(ids==[o['overlay_id'] for o in sources] and len(ids)==len(set(ids)),'Unknown/duplicate/out-of-order decision ID')
        fields={'overlay_id','outcome','preferred_placement_fingerprint','selected_candidate_id',
                'placement_authority','typography_authority','static_result','motion_result','safety_status',
                'reason_codes','candidate_count','evaluated_count','rejected_count','rejected_counts','truncated'}
        reservations=[]
        for source,d in zip(sources,decisions):
            outcome=d['outcome']
            need(outcome in {'preferred','alternate','omitted'},'Invalid Placement outcome')
            need(set(d)==fields|({'selected_placement','selected_typography'} if outcome=='alternate' else set()),'Malformed Placement decision')
            need(d['preferred_placement_fingerprint']==digest(source['placement']),'Stale preferred placement identity')
            need(all(count(d[k]) for k in ('candidate_count','evaluated_count','rejected_count')) and
                 d['rejected_count']<=d['evaluated_count']<=d['candidate_count'],'Invalid candidate counts')
            counts=d['rejected_counts']
            need(isinstance(counts,dict) and set(counts)<=REJECTIONS and all(count(n) and n>0 for n in counts.values()) and
                 sum(counts.values())==d['rejected_count'],'Inconsistent rejection histogram')
            need(type(d['truncated']) is bool,'Invalid truncation evidence')
            host=geometry.classify_host(source,block['resolved_layout']['slots'])
            candidates=placement.generate_candidates(source,block) if host.host_slot_id else placement.CandidateSet((),False)
            need(d['candidate_count']==len(candidates.candidates) and d['truncated']==candidates.truncated,'Stale candidate budget')
            reasons=d['reason_codes']
            need(isinstance(reasons,list) and len(reasons)==1 and isinstance(reasons[0],str),'Invalid reason codes')
            if outcome=='omitted':
                need(reasons[0] in OMISSIONS and d['selected_candidate_id'] is None and
                     d['placement_authority']==d['typography_authority']=='none' and
                     d['static_result']==d['motion_result']=='not_selected' and
                     d['safety_status']=='not_renderable' and
                     d['rejected_count']==d['evaluated_count']==d['candidate_count'],'Invalid omission authority')
                need((reasons[0]=='no_valid_host')==(host.host_slot_id is None),'Inconsistent omitted host')
                if reasons[0]=='candidate_budget_exhausted': need(d['truncated'],'Unexhausted candidate budget')
                if reasons[0]=='all_candidates_typography_failure':
                    need(counts=={'typography_fit_failure':d['candidate_count']} and d['candidate_count']>0,'Invalid Typography failure evidence')
                continue
            need(host.host_slot_id is not None,'Selected placement lacks host')
            need(d['rejected_count']<d['evaluated_count'] and d['safety_status']=='geometric_policy_pass','Selected candidate not accepted')
            matches=[x for x in candidates.candidates if x.candidate_id==d['selected_candidate_id']]
            need(len(matches)==1,'Unknown selected candidate ID')
            candidate=matches[0]
            authority='preferred' if outcome=='preferred' else 'selected'
            need(d['placement_authority']==d['typography_authority']==authority,'Ambiguous selected authority')
            need(reasons==['preferred_valid' if outcome=='preferred' else 'alternate_valid'],'Invalid selected reason')
            if outcome=='preferred':
                need(candidate.preferred and d['evaluated_count']==1 and d['rejected_count']==0,'Preferred-first violation')
            else:
                need(not candidate.preferred and d['selected_placement']==candidate.placement and
                     d['evaluated_count']==d['candidate_count'],'Invalid alternate placement')
            final=selected_overlay(source,d)
            validate_typography(final.get('resolved_typography'),final)
            need(final['resolved_typography']['design_canvas']==c,'Selected Typography canvas mismatch')
            r=geometry.text_reservation(final,canvas)
            container=canvas.from_normalized(final['placement'])
            need(geometry.inside(container.corners,canvas.bounds) and geometry.inside(container.corners,canvas.from_normalized(block['resolved_layout']['safe_area'])),'Selected container outside boundary')
            # Core validates upstream and recomputes continuous geometric evidence.
            plan=manifest.get('visual_plan')
            if plan is not None:
                projected=copy.deepcopy(plan)
                index=next(i for i,b in enumerate(projected['blocks']) if b['visual_block_id']==block['visual_block_id'])
                projected['blocks'][index]=copy.deepcopy(block)
                for mode,key in ((False,'static_result'),(True,'motion_result')):
                    result=geometry.evaluate_collision(manifest,projected,index,final,canvas,motion=mode,other_texts=reservations)
                    need(result.status in {'NONE','PERMITTED'} and d[key]==result.status.lower(),'False/stale geometric collision evidence')
            else:
                need(d['static_result'] in {'none','permitted'} and d['motion_result'] in {'none','permitted'},'Invalid geometric result')
            need(geometry.required_host_contains(block,final,r,canvas),'Selected text escapes required host')
            reservations.append(r)
    except (KeyError,TypeError,StopIteration,IndexError,AttributeError) as exc:
        raise PlacementContractError('Malformed Placement contract inputs') from exc
    return True


def validate_live_placement(manifest, plan, config=None):
    """Optional font-backed replay also verifies omission and ranking evidence."""
    if resolve_plan_placement(manifest,plan,config)!=plan:
        raise PlacementContractError('Placement differs from deterministic live replay')
    return True
