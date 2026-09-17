"""Read-only geometry/collision foundation; no placement search or persistence.

All polygons are convex, canvas design-pixel polygons. Normalized rectangles
enter only through Canvas. Motion fractions enter only through slot_polygon.
EPS_PX is a distance tolerance: penetration <= EPS_PX is contact, not overlap.
Time windows are exact half-open intervals; no time epsilon extends visibility.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from .motion import STRATEGIES, validate_motion_plan
from .typography import validate_typography

EPS_PX = 1e-7
# Deliberately fixed proof vocabulary, not automatically widened by upstream enums.
AFFINE_TRANSFORMS = frozenset({'translate_x', 'translate_y', 'scale', 'opacity'})
PROVEN_EASINGS = frozenset({'linear', 'smoothstep'})
Point = tuple[float, float]
Polygon = tuple[Point, ...]


class GeometryError(ValueError):
    """Missing/unsupported geometry cannot establish collision safety."""


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GeometryError("Expected finite non-boolean number")
    return float(value)


@dataclass(frozen=True)
class Rect:
    """Canvas pixels unless explicitly returned by Canvas.to_normalized."""
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self):
        for v in (self.x, self.y, self.width, self.height):
            number(v)
        if self.width <= 0 or self.height <= 0:
            raise GeometryError("Rectangle must have positive extent")

    @property
    def corners(self) -> Polygon:
        x, y, w, h = self.x, self.y, self.width, self.height
        return ((x, y), (x+w, y), (x+w, y+h), (x, y+h))


@dataclass(frozen=True)
class Canvas:
    width: float
    height: float

    def __post_init__(self):
        if number(self.width) <= 0 or number(self.height) <= 0:
            raise GeometryError("Invalid design canvas")

    @classmethod
    def from_typography_config(cls, config):
        return cls(config.design_width, config.design_height)

    def from_normalized(self, rect) -> Rect:
        return Rect(number(rect['x'])*self.width, number(rect['y'])*self.height,
                    number(rect['width'])*self.width, number(rect['height'])*self.height)

    def to_normalized(self, rect: Rect) -> Rect:
        return Rect(rect.x/self.width, rect.y/self.height,
                    rect.width/self.width, rect.height/self.height)

    @property
    def bounds(self):
        return Rect(0, 0, self.width, self.height)


def transform_polygon(points, *, center=(0, 0), scale=1, translation=(0, 0), rotation_deg=0):
    """Scale then translate in local pixels, then rotate about declared center."""
    scale = number(scale)
    if scale <= 0:
        raise GeometryError("Non-positive uniform scale")
    cx, cy = map(number, center)
    dx, dy = map(number, translation)
    angle = math.radians(number(rotation_deg))
    c, s = math.cos(angle), math.sin(angle)
    result = []
    for x, y in points:
        x, y = (number(x)-cx)*scale+dx, (number(y)-cy)*scale+dy
        result.append((cx+c*x-s*y, cy+s*x+c*y))
    return tuple(result)


def slot_polygon(slot, canvas: Canvas, transform=None) -> Polygon:
    """Base-slot fractions -> slot-local pixels -> rotated canvas pixels."""
    r = canvas.from_normalized(slot)
    t = transform or dict(translate_x=0, translate_y=0, scale=1, opacity=1)
    return transform_polygon(r.corners, center=(r.x+r.width/2, r.y+r.height/2),
                             scale=t['scale'],
                             translation=(number(t['translate_x'])*r.width,
                                          number(t['translate_y'])*r.height),
                             rotation_deg=slot['rotation_deg'])


def aabb(points) -> Rect:
    if not points:
        raise GeometryError("Empty polygon")
    xs, ys = zip(*points)
    return Rect(min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def convex_hull(points) -> Polygon:
    """Canonical CCW hull; exact collinearity removal, no coordinate rounding."""
    points = sorted(set((number(x), number(y)) for x, y in points))
    if len(points) < 3:
        raise GeometryError("Degenerate polygon")
    def half(values):
        result = []
        for p in values:
            while len(result) >= 2 and _cross(result[-2], result[-1], p) <= 0:
                result.pop()
            result.append(p)
        return result
    hull = tuple(half(points)[:-1]+half(reversed(points))[:-1])
    if len(hull) < 3:
        raise GeometryError("Collinear polygon")
    return hull


def positive_overlap(first: Polygon, second: Polygon) -> bool:
    """Convex SAT with unit axes: all penetrations must exceed EPS_PX."""
    first, second = convex_hull(first), convex_hull(second)
    for polygon in (first, second):
        for a, b in zip(polygon, polygon[1:]+polygon[:1]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            length = math.hypot(dx, dy)
            axis = (-dy/length, dx/length)
            one = [x*axis[0]+y*axis[1] for x, y in first]
            two = [x*axis[0]+y*axis[1] for x, y in second]
            if min(max(one), max(two))-max(min(one), min(two)) <= EPS_PX:
                return False
    return True


def intersection(first: Polygon, second: Polygon) -> Polygon:
    """Convex clipping; returns empty for contact under the distance policy."""
    if not positive_overlap(first, second):
        return ()
    output = list(convex_hull(first))
    clip = convex_hull(second)
    for a, b in zip(clip, clip[1:]+clip[:1]):
        source, output = output, []
        if not source:
            break
        p = source[-1]
        for q in source:
            dp, dq = _cross(a, b, p), _cross(a, b, q)
            if (dp >= 0) != (dq >= 0):
                f = dp/(dp-dq)
                output.append((p[0]+f*(q[0]-p[0]), p[1]+f*(q[1]-p[1])))
            if dq >= 0:
                output.append(q)
            p = q
    return convex_hull(output) if len(output) >= 3 else ()


def inside(points: Polygon, bounds: Rect) -> bool:
    return all(bounds.x-EPS_PX <= x <= bounds.x+bounds.width+EPS_PX and
               bounds.y-EPS_PX <= y <= bounds.y+bounds.height+EPS_PX for x, y in points)


def contains_polygon(outer: Polygon, inner: Polygon) -> bool:
    """Convex containment with the same pixel-distance tolerance as collision."""
    outer = convex_hull(outer)
    return all(_cross(a, b, p)/math.dist(a, b) >= -EPS_PX
               for a, b in zip(outer, outer[1:]+outer[:1]) for p in inner)


def required_host_contains(block, overlay, reservation, canvas):
    """Optional placement policy: static text stays inside its explicit host.

    This does not change Overlay v1.0 target semantics. Block-target overlays
    have no containment requirement. For slot targets, test all clipped segment
    endpoints: fixed-angle halfspaces are affine in the shared easing scalar.
    """
    if overlay['target']['scope'] != 'slot':
        return True
    target = overlay['target']['target_slot_id']
    slot = next(s for s in block['resolved_layout']['slots'] if s['slot_id'] == target)
    track = next(t for t in block['resolved_motion']['tracks'] if t['target_slot_id'] == target)
    _proof_track(track)
    visible = inherited_visibility(block, slot)
    lo, hi = reservation.visibility
    if lo < visible[0] or hi > visible[1]:
        raise GeometryError('Overlay extends beyond target visibility')
    times = sorted({lo, hi, *(f['t'] for f in track['keyframes'] if lo < f['t'] < hi)})
    for time in times:
        transform = transform_at(track, time) if track['space'] == 'slot' else None
        polygon = slot_polygon(slot, canvas, transform)
        if any(not contains_polygon(polygon, p) for p in reservation.polygons):
            return False
    return True


def window(start, end):
    start, end = number(start), number(end)
    if not 0 <= start < end <= 1:
        raise GeometryError("Invalid block-normalized visibility")
    return start, end


def co_visible(first, second):
    first, second = window(*first), window(*second)
    lo, hi = max(first[0], second[0]), min(first[1], second[1])
    return (lo, hi) if lo < hi else None


@dataclass(frozen=True)
class TextLine:
    text: str
    ink: Rect
    advance: Rect
    baseline: Point


@dataclass(frozen=True)
class TextReservation:
    overlay_id: str
    visibility: tuple[float, float]
    lines: tuple[TextLine, ...]
    ink_union: Rect
    advance_union: Rect

    def __post_init__(self):
        window(*self.visibility)
        if not self.lines:
            raise GeometryError("Text reservation needs lines")

    @property
    def polygons(self):
        # Never use either broad union as painted or reserved interline space.
        return tuple(r.corners for line in self.lines for r in (line.ink, line.advance))


def text_reservation(overlay, canvas: Canvas) -> TextReservation:
    value = overlay.get('resolved_typography')
    validate_typography(value, overlay)
    if value['design_canvas'] != dict(width=canvas.width, height=canvas.height):
        raise GeometryError("Typography canvas mismatch")
    measured = value.get('measured_layout')
    if measured is None:
        raise GeometryError("Measured layout required")
    lines = tuple(TextLine(row['text'], canvas.from_normalized(row['ink_box']),
                           canvas.from_normalized(row['advance_box']),
                           (row['baseline_x']*canvas.width, row['baseline_y']*canvas.height))
                  for row in measured['lines'])
    return TextReservation(overlay['overlay_id'], window(**overlay['visibility']), lines,
                           canvas.from_normalized(measured['resolved_text_bounds']),
                           canvas.from_normalized(measured['layout_bounds']))


@dataclass(frozen=True)
class HostPolicy:
    state: str
    host_slot_id: str | None
    protected_slot_ids: tuple[str, ...]


def classify_host(overlay, slots):
    ids = [slot['slot_id'] for slot in slots]
    if len(ids) != len(set(ids)):
        raise GeometryError("Duplicate slot IDs")
    target = overlay['target']
    if target.get('scope') == 'slot':
        host = target.get('target_slot_id')
        if host not in ids:
            raise GeometryError("Unknown explicit host")
        state = 'explicit'
    elif target.get('scope') == 'block':
        primary = [s['slot_id'] for s in slots if s.get('role') == 'primary']
        host = primary[0] if len(primary) == 1 else None
        state = 'unique_primary' if host else ('ambiguous' if primary else 'no_host')
    else:
        raise GeometryError("Unsupported overlay target")
    return HostPolicy(state, host, tuple(sorted(s for s in ids if s != host)))


def inherited_visibility(block, slot):
    """Same shot-ID join and seconds -> block normalization as Motion._context."""
    start, end = number(block['timeline_start_seconds']), number(block['timeline_end_seconds'])
    if end <= start:
        raise GeometryError("Invalid block interval")
    layers = [l for l in block['layout']['layers'] if l['shot_id'] == slot['shot_id']]
    if len(layers) != 1:
        raise GeometryError("Missing/ambiguous inherited visibility")
    timing = layers[0]['visual_layer_timing']
    return window((number(timing['start_seconds'])-start)/(end-start),
                  (number(timing['end_seconds'])-start)/(end-start))


def _proof_track(track):
    """Reject transforms/easing outside the affine-corner sweep assumptions.

    Full strategy eligibility belongs to validate_motion_plan, called by the
    public block adapter. This low-level guard also protects direct sweep use.
    """
    if track.get('space') not in {'slot', 'media_content'} or track.get('strategy') not in STRATEGIES:
        raise GeometryError("Unsupported Motion strategy/space")
    frames = track.get('keyframes')
    if not isinstance(frames, list) or len(frames) not in (2, 3):
        raise GeometryError("Unsupported Motion keyframes")
    previous = -1
    for i, frame in enumerate(frames):
        expected = {'t', 'transform'} | ({'easing_to_next'} if i < len(frames)-1 else set())
        if set(frame) != expected or not 0 <= number(frame['t']) <= 1 or frame['t'] <= previous:
            raise GeometryError("Malformed Motion frame")
        previous = frame['t']
        t = frame['transform']
        if set(t) != AFFINE_TRANSFORMS or any(not math.isfinite(number(v)) for v in t.values()):
            raise GeometryError("Unsupported Motion transform")
        if t['scale'] <= 0 or not 0 <= t['opacity'] <= 1:
            raise GeometryError("Invalid Motion scale/opacity")
        if i < len(frames)-1 and frame['easing_to_next'] not in PROVEN_EASINGS:
            raise GeometryError("Sweep requires shared monotone easing")


def transform_at(track, time):
    _proof_track(track)
    time = number(time)
    frames = track['keyframes']
    if not frames[0]['t'] <= time <= frames[-1]['t']:
        raise GeometryError("Motion evaluation outside inherited window")
    for a, b in zip(frames, frames[1:]):
        if a['t'] <= time <= b['t']:
            q = (time-a['t'])/(b['t']-a['t'])
            if a['easing_to_next'] == 'smoothstep':
                q = q*q*(3-2*q)
            return {k: a['transform'][k]+q*(b['transform'][k]-a['transform'][k])
                    for k in sorted(AFFINE_TRANSFORMS)}
    raise GeometryError("Missing Motion segment")


@dataclass(frozen=True)
class Sweep:
    interval: tuple[float, float]
    polygon: Polygon


def swept_slot(slot, track, canvas, visibility):
    """Continuous conservative sweeps, never a frame-sampling safety claim.

    Fixed rotation and shared monotone easing make each corner affine in q.
    The endpoint hull contains every intermediate polygon. Half-open interval
    end geometry is included as a conservative limiting boundary.
    """
    _proof_track(track)
    frames = track['keyframes']
    visible = co_visible(visibility, (frames[0]['t'], frames[-1]['t']))
    if visible is None or number(slot['opacity']) == 0:
        return ()
    lo, hi = visible
    cuts = sorted({lo, hi, *(f['t'] for f in frames if lo < f['t'] < hi)})
    result = []
    for a, b in zip(cuts, cuts[1:]):
        ta, tb = transform_at(track, a), transform_at(track, b)
        if ta['opacity'] == tb['opacity'] == 0:
            continue
        if track['space'] == 'media_content':
            polygon = slot_polygon(slot, canvas)
        else:
            polygon = convex_hull(slot_polygon(slot, canvas, ta)+slot_polygon(slot, canvas, tb))
        result.append(Sweep((a, b), polygon))
    return tuple(result)


@dataclass(frozen=True)
class Observation:
    classification: str
    reason: str
    target_id: str
    interval: tuple[float, float]


@dataclass(frozen=True)
class CollisionResult:
    status: str
    host: HostPolicy
    observations: tuple[Observation, ...]
    unassessed: tuple[str, ...] = ('subject_safety', 'decorations', 'platform_ui', 'background_plates')


def evaluate_collision(manifest, plan, block_index, overlay, canvas: Canvas, *,
                       motion=True, other_texts=()) -> CollisionResult:
    """Validate frozen upstream contracts, then inspect; never mutate inputs.

    motion=False evaluates static Layout footprints with inherited visibility.
    motion=True tests continuous external Motion sweeps. Other text reservations
    are supplied static canvas fixtures, gated by their half-open visibility.
    """
    validate_motion_plan(plan, plan, manifest)
    if not math.isclose(canvas.width/canvas.height, 9/16, rel_tol=0, abs_tol=0):
        raise GeometryError("Motion v1.0 requires a 9:16 design canvas")
    block = plan['blocks'][block_index]
    slots = block['resolved_layout']['slots']
    reservation = text_reservation(overlay, canvas)
    host = classify_host(overlay, slots)
    if overlay['target']['scope'] == 'slot':
        target = next(s for s in slots if s['slot_id'] == host.host_slot_id)
        interval = inherited_visibility(block, target)
        if reservation.visibility[0] < interval[0] or reservation.visibility[1] > interval[1]:
            raise GeometryError("Overlay extends beyond target visibility")
    observations = []
    for name, boundary in (('canvas', canvas.bounds),
                           ('design_safe_area', canvas.from_normalized(block['resolved_layout']['safe_area']))):
        if any(not inside(p, boundary) for p in reservation.polygons):
            observations.append(Observation('HARD', 'outside_boundary', name, reservation.visibility))
    tracks = {t['target_slot_id']: t for t in block['resolved_motion']['tracks']}
    for slot in sorted(slots, key=lambda s: s['slot_id']):
        visible = co_visible(reservation.visibility, inherited_visibility(block, slot))
        if visible is None or slot['opacity'] == 0:
            continue
        sweeps = swept_slot(slot, tracks[slot['slot_id']], canvas, visible) if motion else (
            Sweep(visible, slot_polygon(slot, canvas)),)
        for sweep in sweeps:
            if any(positive_overlap(p, sweep.polygon) for p in reservation.polygons):
                permitted = slot['slot_id'] == host.host_slot_id
                observations.append(Observation('PERMITTED' if permitted else 'HARD',
                                    'host_overlap' if permitted else 'protected_slot_overlap',
                                    slot['slot_id'], sweep.interval))
    for other in sorted(other_texts, key=lambda r: r.overlay_id):
        visible = co_visible(reservation.visibility, other.visibility)
        if visible and any(positive_overlap(a, b) for a in reservation.polygons for b in other.polygons):
            observations.append(Observation('HARD', 'text_overlap', other.overlay_id, visible))
    status = ('HARD' if any(o.classification == 'HARD' for o in observations) else
              'UNKNOWN' if host.state in {'ambiguous', 'no_host'} else
              'PERMITTED' if observations else 'NONE')
    return CollisionResult(status, host, tuple(observations))
