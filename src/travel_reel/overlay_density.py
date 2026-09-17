"""Overlay-owned, post-Placement admission; never changes geometric authority."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from fractions import Fraction

VERSION = "1.0"
POLICY = "overlay_minimum_gap.v1"
MINIMUM_GAP_SECONDS = 0.5


class DensityValidationError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise DensityValidationError("Invalid density timing number")
    # Exact rational arithmetic on persisted decimal spellings: no epsilon,
    # frame snapping, binary-float arithmetic, or Decimal context dependence.
    return Fraction(str(value))


def _expected(plan):
    """Replay from ordered source/Placement inputs only, excluding prior density."""
    try:
        inputs = []
        seen_blocks, seen_overlays = set(), set()
        prior_end = Fraction(0)
        for block in plan['blocks']:
            bid = block['visual_block_id']
            start, end = (_number(block[k]) for k in ('timeline_start_seconds', 'timeline_end_seconds'))
            if not isinstance(bid, str) or not bid or bid in seen_blocks or start < prior_end or end <= start:
                raise DensityValidationError("Invalid density block order/identity/timing")
            seen_blocks.add(bid); prior_end = end
            contract = block['resolved_overlay']
            if contract['version'] not in {'1.1', '1.2'}:
                raise DensityValidationError("Density requires Placement-backed Overlay")
            sources = contract['overlays']
            placement = contract['placement_resolution']
            decisions = placement['decisions']
            if len(sources) != len(decisions):
                raise DensityValidationError("Missing Placement decision for density")
            entries = []
            for source, decision in zip(sources, decisions):
                oid = source['overlay_id']
                if not isinstance(oid, str) or not oid or oid in seen_overlays or decision['overlay_id'] != oid:
                    raise DensityValidationError("Invalid density source identity/order")
                seen_overlays.add(oid)
                u, v = (_number(source['visibility'][k]) for k in ('start', 'end'))
                if source['time_space'] != 'block_normalized' or not 0 <= u < v <= 1:
                    raise DensityValidationError("Invalid density visibility")
                if decision['outcome'] not in {'preferred', 'alternate', 'omitted'}:
                    raise DensityValidationError("Invalid density Placement outcome")
                entries.append({'source': source, 'placement_decision': decision})
            inputs.append({'visual_block_id': bid, 'start': block['timeline_start_seconds'],
                           'end': block['timeline_end_seconds'],
                           'placement_dependency': placement['dependency_fingerprint'], 'entries': entries})
        policy = {'version': VERSION, 'policy_version': POLICY, 'minimum_gap_seconds': MINIMUM_GAP_SECONDS}
        fingerprint = hashlib.sha256(_canonical({'policy': policy, 'blocks': inputs}).encode('utf-8')).hexdigest()
        results = []
        last_end = None
        for block in inputs:
            records = []
            start, end = _number(block['start']), _number(block['end'])
            for entry in block['entries']:
                source, placement = entry['source'], entry['placement_decision']
                left = start + _number(source['visibility']['start']) * (end-start)
                right = start + _number(source['visibility']['end']) * (end-start)
                if placement['outcome'] == 'omitted':
                    state, reason = 'not_eligible', 'placement_omitted'
                elif last_end is None:
                    state, reason = 'admitted', 'first_selected'
                elif left >= last_end + _number(MINIMUM_GAP_SECONDS):
                    state, reason = 'admitted', 'minimum_gap_satisfied'
                else:
                    state, reason = 'suppressed', 'minimum_gap_not_met'
                if state == 'admitted':
                    last_end = right
                records.append({'overlay_id': source['overlay_id'], 'state': state, 'reason': reason})
            results.append({**policy, 'dependency_fingerprint': fingerprint, 'decisions': records})
        return results
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise DensityValidationError("Malformed density inputs") from exc


def validate_density_plan(plan):
    """Strict full-reel replay; source order and all cross-block inputs are bound."""
    expected = _expected(plan)
    for block, result in zip(plan['blocks'], expected):
        contract = block['resolved_overlay']
        if contract['version'] != '1.2':
            raise DensityValidationError("Mixed legacy/density Overlay versions")
        try:
            if _canonical(contract.get('density_admission')) != _canonical(result):
                raise DensityValidationError("Malformed, stale, or unsupported density admission")
        except (TypeError, ValueError) as exc:
            raise DensityValidationError("Malformed, stale, or unsupported density admission") from exc
    return True


def resolve_density(manifest, plan):
    """Validate Placement, then attach admission without changing source evidence."""
    from .overlay import validate_overlay_plan
    validate_overlay_plan(plan, plan, manifest)
    expected = _expected(plan)
    result = copy.deepcopy(plan)
    for block, child in zip(result['blocks'], expected):
        block['resolved_overlay']['version'] = '1.2'
        block['resolved_overlay']['density_admission'] = child
    validate_overlay_plan(result, plan, manifest)
    return result
