"""Bounded, non-persistent placement decisions over frozen upstream contracts.

Policy placement_candidates.v1: preferred first; then width-major rounds of
1.00, .85, .70 of min(preferred width, approved width), capped at 12 unique
projections. Existing .02 normalized Overlay inset is retained for generated
block containers. Explicit slot targets use the safe-area/base-slot intersection
without that extra inset; actual rotated/moving containment is checked separately.
No source overlay, typography, or upstream plan is ever changed.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import math

from . import placement_geometry as geometry
from .motion import validate_motion_plan
from .overlay import validate_overlay_plan, TYPES
from .typography import TypographyConfig, TypographyResolver
from .typography_layout import TypographyFitError

POLICY_VERSION = 'placement_candidates.v1'
WIDTH_VARIANTS = (1.0, .85, .70)
MAX_CANDIDATES = 12
UPPER = ('top_left', 'top_center', 'top_right')
LOWER = ('bottom_left', 'bottom_center', 'bottom_right')
ANCHOR_ORDERS = {
    'location_label': UPPER+LOWER, 'section_label': UPPER+LOWER,
    'caption': LOWER+UPPER, 'closing_subtitle': LOWER+UPPER,
    'title': ('center', 'top_center', 'bottom_center'),
    'closing_title': ('center', 'top_center', 'bottom_center'),
}


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    overlay_id: str
    order: int
    region: str
    anchor: str
    alignment: str
    container: geometry.Rect  # canvas_normalized, explicitly converted at evaluation
    preferred: bool
    width_variant: float
    anchor_priority: int
    policy_version: str = POLICY_VERSION
    coordinate_space: str = 'canvas_normalized'

    @property
    def placement(self):
        r = self.container
        return dict(region=self.region, anchor=self.anchor, alignment=self.alignment,
                    x=r.x, y=r.y, width=r.width, height=r.height)


@dataclass(frozen=True)
class CandidateSet:
    candidates: tuple[Candidate, ...]
    truncated: bool


@dataclass(frozen=True)
class Evaluation:
    candidate: Candidate
    accepted: bool
    reasons: tuple[str, ...]
    typography: dict | None
    static: geometry.CollisionResult | None
    motion: geometry.CollisionResult | None
    distance: float


@dataclass(frozen=True)
class Decision:
    overlay_id: str
    outcome: str
    reason: str
    selected: Evaluation | None
    evaluations: tuple[Evaluation, ...]
    candidate_count: int
    truncated: bool
    policy_version: str = POLICY_VERSION


def _alignment(anchor):
    return 'left' if anchor.endswith('left') else 'right' if anchor.endswith('right') else 'center'


def generate_candidates(overlay, block) -> CandidateSet:
    """Pure finite enumeration; IDs contain only versioned intent and geometry."""
    kind = overlay['type']
    if kind not in TYPES:
        raise geometry.GeometryError('Unsupported Overlay type')
    preferred = overlay['placement']
    order = ANCHOR_ORDERS[kind]
    candidates, seen = [], set()

    def add(p, is_preferred, variant, priority):
        # Region names do not alter identical geometric/alignment projections.
        key = tuple(p[k] for k in ('anchor','alignment','x','y','width','height'))
        if key in seen:
            return
        seen.add(key)
        identity = dict(policy=POLICY_VERSION, overlay_id=overlay['overlay_id'],
                        type=kind, placement=p)
        digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'),
                                           allow_nan=False).encode()).hexdigest()
        candidates.append(Candidate('placement-'+digest, overlay['overlay_id'],len(candidates),
                           p['region'],p['anchor'],p['alignment'],
                           geometry.Rect(*(p[k] for k in ('x','y','width','height'))),
                           is_preferred,variant,priority))

    add(copy.deepcopy(preferred), True, 1.0, -1)
    safe = block['resolved_layout']['safe_area']
    x, y, right, bottom = safe['x'], safe['y'], safe['x']+safe['width'], safe['y']+safe['height']
    target = overlay['target']
    if target['scope'] == 'slot':
        slot = next(s for s in block['resolved_layout']['slots'] if s['slot_id']==target['target_slot_id'])
        x,y,right,bottom = max(x,slot['x']),max(y,slot['y']),min(right,slot['x']+slot['width']),min(bottom,slot['y']+slot['height'])
    else:
        x,y,right,bottom = x+.02,y+.02,right-.02,bottom-.02
    available = min(preferred['width'],right-x)
    height = preferred['height']
    if available > 0 and bottom-y >= height:
        for variant in WIDTH_VARIANTS:
            width = available*variant
            if round(width,6) <= 0:
                continue
            for priority, anchor in enumerate(order):
                alignment = _alignment(anchor)
                px = x if alignment=='left' else right-width if alignment=='right' else (x+right-width)/2
                py = y if anchor.startswith('top') else bottom-height if anchor.startswith('bottom') else (y+bottom-height)/2
                region = ('title_safe' if kind=='location_label' else 'upper_safe') if anchor.startswith('top') else 'lower_safe' if anchor.startswith('bottom') else 'center_safe'
                # Match Overlay's existing six-decimal container precision.
                add(dict(region=region,anchor=anchor,alignment=alignment,
                         x=round(px,6),y=round(py,6),width=round(width,6),height=round(height,6)),
                    False,variant,priority)
    return CandidateSet(tuple(candidates[:MAX_CANDIDATES]),len(candidates)>MAX_CANDIDATES)


def candidate_projection(overlay, candidate):
    projection = copy.deepcopy(overlay)
    projection.pop('resolved_typography',None)
    projection['placement'] = candidate.placement
    projection['style']['alignment'] = candidate.alignment
    return projection


def placement_distance(candidate, preferred, canvas):
    a,b = canvas.from_normalized(candidate.placement),canvas.from_normalized(preferred)
    return math.hypot(a.x+a.width/2-b.x-b.width/2,a.y+a.height/2-b.y-b.height/2)/math.hypot(canvas.width,canvas.height)


def rank_key(evaluation):
    """Lower wins; host overlap deliberately has no aesthetic penalty."""
    if not evaluation.accepted:
        raise geometry.GeometryError('Cannot rank rejected candidate')
    m = evaluation.typography['measured_layout']
    return (m['ellipsis'], -m['resolved_font_size'], m['size_step'],
            evaluation.candidate.anchor_priority, evaluation.distance,
            evaluation.candidate.candidate_id)


def evaluate_candidate(manifest, plan, block_index, overlay, candidate, resolver, canvas, other_texts=()):
    """Only legitimate fit/geometric failures become candidate rejection."""
    distance = placement_distance(candidate,overlay['placement'],canvas)
    block = plan['blocks'][block_index]
    container = canvas.from_normalized(candidate.placement)
    if not geometry.inside(container.corners,canvas.bounds) or not geometry.inside(
            container.corners,canvas.from_normalized(block['resolved_layout']['safe_area'])):
        return Evaluation(candidate,False,('invalid_candidate_geometry',),None,None,None,distance)
    projection = candidate_projection(overlay,candidate)
    try:
        # Fresh resolution also validates the current font environment. No input
        # cached result is overwritten, including for candidate zero.
        typography = resolver.resolve(projection)
    except TypographyFitError:
        return Evaluation(candidate,False,('typography_fit_failure',),None,None,None,distance)
    projection['resolved_typography'] = typography
    static = geometry.evaluate_collision(manifest,plan,block_index,projection,canvas,motion=False,other_texts=other_texts)
    motion = geometry.evaluate_collision(manifest,plan,block_index,projection,canvas,motion=True,other_texts=other_texts)
    reasons = []
    if static.host.host_slot_id is None:
        reasons.append('no_valid_host')
    if static.status == 'HARD':
        reasons.append('static_collision')
    if motion.status == 'HARD':
        reasons.append('motion_collision')
    reservation = geometry.text_reservation(projection,canvas)
    if not geometry.required_host_contains(block,projection,reservation,canvas):
        reasons.append('host_containment_failure')
    return Evaluation(candidate,not reasons,tuple(reasons),typography,static,motion,distance)


def resolve_placement(manifest, plan, block_index, overlay, config=None, *, other_texts=()):
    """Return PREFERRED/ALTERNATE/OMITTED without mutating or persisting input.

    Frozen-contract errors and font/backend errors propagate. Only candidate
    fitting/collision failures participate in search. Prior reservations are
    caller supplied; there is no hidden multi-overlay ordering or run history.
    """
    validate_motion_plan(plan,plan,manifest)
    block = plan['blocks'][block_index]
    # Use the actual Overlay validator on a detached one-block projection.
    check = {'blocks':[copy.deepcopy(block)]}
    check['blocks'][0]['resolved_overlay'] = dict(version='1.0',overlays=[copy.deepcopy(overlay)],selection_reasons=[])
    validate_overlay_plan(check,check,manifest)
    if overlay['style'].get('alignment',overlay['placement']['alignment']) != overlay['placement']['alignment']:
        raise geometry.GeometryError('Inconsistent preferred alignment')
    if overlay['placement']['alignment'] != _alignment(overlay['placement']['anchor']):
        raise geometry.GeometryError('Incoherent preferred anchor/alignment')
    config = config or TypographyConfig()
    canvas = geometry.Canvas.from_typography_config(config)
    if canvas.width/canvas.height != 9/16:
        raise geometry.GeometryError('Motion v1.0 requires 9:16 canvas')
    others = tuple(other_texts)
    if any(r.overlay_id==overlay['overlay_id'] for r in others) or len({r.overlay_id for r in others})!=len(others):
        raise geometry.GeometryError('Duplicate/self prior text reservation')
    host = geometry.classify_host(overlay,block['resolved_layout']['slots'])
    if host.host_slot_id is None:
        return Decision(overlay['overlay_id'],'OMITTED','no_valid_host',None,(),0,False)
    candidates = generate_candidates(overlay,block)
    resolver = TypographyResolver(config)
    evaluations = []
    for candidate in candidates.candidates:
        value = evaluate_candidate(manifest,plan,block_index,overlay,candidate,resolver,canvas,others)
        evaluations.append(value)
        if candidate.preferred and value.accepted:
            return Decision(overlay['overlay_id'],'PREFERRED','preferred_valid',value,tuple(evaluations),
                            len(candidates.candidates),candidates.truncated)
    valid = [e for e in evaluations if e.accepted]
    if valid:
        selected = min(valid,key=rank_key)
        return Decision(overlay['overlay_id'],'ALTERNATE','alternate_valid',selected,tuple(evaluations),
                        len(candidates.candidates),candidates.truncated)
    reasons = {r for e in evaluations for r in e.reasons}
    reason = ('all_candidates_typography_failure' if reasons=={'typography_fit_failure'} else
              'candidate_budget_exhausted' if candidates.truncated else
              'all_candidates_collision' if reasons <= {'static_collision','motion_collision','host_containment_failure'} else
              'all_candidates_invalid')
    return Decision(overlay['overlay_id'],'OMITTED',reason,None,tuple(evaluations),len(candidates.candidates),candidates.truncated)
