"""Independent geometry expectations and read-only frozen-contract adapters."""
import copy
import math
import unittest
from unittest.mock import patch

from travel_reel import placement_geometry as g
from travel_reel.motion import resolve_motion, _candidates
from travel_reel.typography import TypographyResolver
from tests.test_motion import fixture
from tests import test_typography as typography_fixtures
from tests.test_typography import CJK, ARIAL, config


def slot(**changes):
    value = dict(slot_id='s1', shot_id='shot-001', x=.25, y=.25, width=.5,
                 height=.5, rotation_deg=0, opacity=1, role='primary')
    value.update(changes)
    return value


def track(strategy='hold.v1', space='slot', peak=1.01, middle=.5):
    def state(scale=1, **kw):
        return dict(translate_x=kw.get('x', 0), translate_y=kw.get('y', 0),
                    scale=scale, opacity=kw.get('opacity', 1))
    states = [(0, state()), (1, state())]
    if strategy == 'card_emphasis.v1':
        states.insert(1, (middle, state(peak)))
    elif strategy == 'card_enter.v1':
        states = [(0, state(.99, opacity=.85)), (.05, state()), (1, state())]
    elif strategy == 'card_exit.v1':
        states = [(0, state()), (.95, state()), (1, state(.99, opacity=.85))]
    return dict(target_slot_id='s1', space=space, strategy=strategy,
                keyframes=[dict(t=t, transform=s, **({'easing_to_next':'smoothstep'}
                           if i < len(states)-1 else {})) for i, (t,s) in enumerate(states)])


def reservation(rect, visibility=(0,1), name='text'):
    return g.TextReservation(name, visibility,
                             (g.TextLine('fixture', rect, rect, (rect.x, rect.y)),), rect, rect)


class GeometryTests(unittest.TestCase):
    def test_canvas_conversion_and_config(self):
        c = g.Canvas.from_typography_config(config())
        r = c.from_normalized(dict(x=.1,y=.2,width=.5,height=.25))
        self.assertEqual(r, g.Rect(108,384,540,480))
        self.assertEqual(c.to_normalized(r), g.Rect(.1,.2,.5,.25))

    def test_rect_corners(self):
        self.assertEqual(g.Rect(2,3,4,5).corners, ((2,3),(6,3),(6,8),(2,8)))

    def test_rotation(self):
        result = g.transform_polygon(((2,1),(3,1),(3,2)), center=(1,1), rotation_deg=90)
        for actual, expected in zip(result, ((1,2),(1,3),(0,3))):
            for a,b in zip(actual,expected): self.assertAlmostEqual(a,b)

    def test_scale_translation_order(self):
        self.assertEqual(g.transform_polygon(((2,3),), center=(1,1), scale=2,
                                            translation=(5,7)), ((8,12),))

    def test_slot_transform_physical_aspect(self):
        # 200x100 pixels centered at (300,250); translation (20,20) rotates to (-20,20).
        s = slot(x=.2,y=.2,width=.2,height=.1,rotation_deg=90)
        p = g.slot_polygon(s,g.Canvas(1000,1000),
                           dict(scale=2,translate_x=.1,translate_y=.2))
        box = g.aabb(p)
        for a,b in zip((box.x,box.y,box.width,box.height),(180,70,200,400)):
            self.assertAlmostEqual(a,b)

    def test_non_square_canvas_rotation(self):
        p = g.slot_polygon(slot(rotation_deg=90),g.Canvas(1080,1920))
        b = g.aabb(p)
        self.assertAlmostEqual(b.width,960)
        self.assertAlmostEqual(b.height,540)

    def test_aabb_and_hull(self):
        points=((0,0),(2,0),(2,2),(0,2),(1,1),(0,0),(1,0))
        self.assertEqual(g.convex_hull(points),((0,0),(2,0),(2,2),(0,2)))
        self.assertEqual(g.aabb(points),g.Rect(0,0,2,2))

    def test_polygon_intersection(self):
        a,b=g.Rect(0,0,2,2).corners,g.Rect(1,1,2,2).corners
        self.assertEqual(g.intersection(a,b),g.Rect(1,1,1,1).corners)
        self.assertTrue(g.positive_overlap(a,b))

    def test_rotated_polygon_not_aabb_false_positive(self):
        diamond=((0,1),(1,0),(2,1),(1,2))
        corner=g.Rect(0,0,.1,.1).corners
        self.assertFalse(g.positive_overlap(diamond,corner))

    def test_contact_and_numeric_penetration(self):
        a=g.Rect(0,0,1,1).corners
        for offset, expected in ((0,False),(g.EPS_PX/2,False),(-g.EPS_PX/2,False),
                                 (-2*g.EPS_PX,True),(2*g.EPS_PX,False)):
            b=g.Rect(1+offset,0,1,1).corners
            self.assertEqual(g.positive_overlap(a,b),expected)
        self.assertEqual(g.intersection(a,g.Rect(1,0,1,1).corners),())

    def test_boundary_tolerance_and_rotation(self):
        bounds=g.Rect(0,0,10,10)
        for x, expected in ((0,True),(-g.EPS_PX/2,True),(-2*g.EPS_PX,False)):
            self.assertEqual(g.inside(g.Rect(x,1,1,1).corners,bounds),expected)
        p=g.transform_polygon(g.Rect(0,0,2,2).corners,center=(1,1),rotation_deg=45)
        self.assertFalse(g.inside(p,bounds))
        shifted=g.transform_polygon(p,translation=(math.sqrt(2)-1,1))
        self.assertTrue(g.inside(shifted,bounds))

    def test_invalid_numeric_geometry(self):
        for bad in (True,float('nan'),float('inf')):
            with self.assertRaises(g.GeometryError): g.Canvas(bad,1920)
        with self.assertRaises(g.GeometryError): g.Rect(0,0,0,1)
        with self.assertRaises(g.GeometryError): g.convex_hull(((0,0),(1,1),(2,2)))


class HostVisibilityTests(unittest.TestCase):
    def test_explicit_target(self):
        h=g.classify_host({'target':dict(scope='slot',target_slot_id='s2')},
                          [slot(),slot(slot_id='s2',role='supporting')])
        self.assertEqual(h,g.HostPolicy('explicit','s2',('s1',)))

    def test_unique_primary_and_secondary(self):
        h=g.classify_host({'target':dict(scope='block')},[slot(),slot(slot_id='s2',role='supporting')])
        self.assertEqual(h,g.HostPolicy('unique_primary','s1',('s2',)))

    def test_ambiguous_order_independent(self):
        slots=[slot(),slot(slot_id='s2')]; o={'target':dict(scope='block')}
        a=g.classify_host(o,slots)
        self.assertEqual(a,g.classify_host(o,list(reversed(slots))))
        self.assertEqual(a.state,'ambiguous'); self.assertIsNone(a.host_slot_id)

    def test_no_primary_and_unknown_target(self):
        self.assertEqual(g.classify_host({'target':dict(scope='block')},[slot(role='supporting')]).state,'no_host')
        with self.assertRaises(g.GeometryError):
            g.classify_host({'target':dict(scope='slot',target_slot_id='missing')},[slot()])

    def test_half_open_visibility(self):
        self.assertIsNone(g.co_visible((0,.5),(.5,1)))
        self.assertEqual(g.co_visible((.2,.7),(.5,.9)),(.5,.7))

    def test_inherited_shot_join(self):
        b=dict(timeline_start_seconds=10,timeline_end_seconds=20,
               layout={'layers':[dict(shot_id='shot-001',slot_id='different-template-id',
                 visual_layer_timing=dict(start_seconds=12,end_seconds=16))]})
        self.assertEqual(g.inherited_visibility(b,slot()),(.2,.6))


class SweepTests(unittest.TestCase):
    def test_hold(self):
        result=g.swept_slot(slot(),track(),g.Canvas(100,100),(0,1))
        self.assertEqual(g.aabb(result[0].polygon),g.Rect(25,25,50,50))

    def test_intermediate_only_collision(self):
        # Base edge x=75. Peak scale 1.01 expands it to x=75.25.
        # The independent fixture at x=75.1 misses both endpoint rectangles.
        obstacle=g.Rect(75.1,40,.1,10).corners
        base=g.Rect(25,25,50,50).corners
        self.assertFalse(g.positive_overlap(base,obstacle))
        sweeps=g.swept_slot(slot(),track('card_emphasis.v1'),g.Canvas(100,100),(0,1))
        self.assertTrue(any(g.positive_overlap(s.polygon,obstacle) for s in sweeps))

    def test_shifted_emphasis(self):
        sweeps=g.swept_slot(slot(),track('card_emphasis.v1',middle=.428980527),g.Canvas(100,100),(0,1))
        self.assertEqual(sweeps[0].interval,(0,.428980527))
        self.assertAlmostEqual(g.aabb(sweeps[0].polygon).x,24.75)

    def test_enter_exit(self):
        for name in ('card_enter.v1','card_exit.v1'):
            sweeps=g.swept_slot(slot(),track(name),g.Canvas(100,100),(0,1))
            self.assertEqual(len(sweeps),2)
            for s in sweeps: self.assertTrue(g.inside(s.polygon,g.Rect(25,25,50,50)))

    def test_clipped_interval_excludes_peak(self):
        t=track('card_emphasis.v1')
        sweeps=g.swept_slot(slot(),t,g.Canvas(100,100),(0,.1))
        self.assertEqual(len(sweeps),1)
        # smoothstep(.2)=.104; edge moves .25*.104=.026, not .25.
        self.assertAlmostEqual(g.aabb(sweeps[0].polygon).width,50.052)
        self.assertFalse(g.positive_overlap(sweeps[0].polygon,g.Rect(75.1,40,.1,10).corners))

    def test_disjoint_interval(self):
        t=track();t['keyframes'][0]['t']=.5
        self.assertEqual(g.swept_slot(slot(),t,g.Canvas(100,100),(0,.5)),())

    def test_easing_is_shared(self):
        t=track(); t['keyframes'][-1]['transform'].update(scale=2,translate_x=.2,translate_y=.4,opacity=.5)
        s=g.transform_at(t,.25)  # smoothstep(.25) = .15625
        self.assertEqual(s,dict(scale=1.15625,translate_x=.03125,translate_y=.0625,opacity=.921875))

    def test_affine_sweep_contains_intermediate_corners(self):
        t=track(); t['keyframes'][-1]['transform'].update(scale=1.01,translate_x=.01,translate_y=-.02)
        s=slot(rotation_deg=8); c=g.Canvas(1080,1920)
        sweep=g.swept_slot(s,t,c,(0,1))[0].polygon
        # Independent interpolation + point-in-convex-halfspaces, not sweep helpers.
        endpoints=[g.slot_polygon(s,c,f['transform']) for f in t['keyframes']]
        for q in (.1,.25,.5,.75,.9):
            for a,b in zip(*endpoints):
                p=(a[0]+q*(b[0]-a[0]),a[1]+q*(b[1]-a[1]))
                for u,v in zip(sweep,sweep[1:]+sweep[:1]):
                    signed=((v[0]-u[0])*(p[1]-u[1])-(v[1]-u[1])*(p[0]-u[0]))/math.dist(u,v)
                    self.assertGreaterEqual(signed,-g.EPS_PX)

    def test_unsupported_proof_assumptions_fail(self):
        for change in ('rotation','easing','nan','frame','space'):
            t=track()
            if change=='rotation':t['keyframes'][0]['transform']['rotation_deg']=1
            elif change=='easing':t['keyframes'][0]['easing_to_next']='spring'
            elif change=='nan':t['keyframes'][0]['transform']['scale']=float('nan')
            elif change=='frame':t['keyframes'][0]['easing_x']='linear'
            else:t['space']='source_pixels'
            with self.assertRaises(g.GeometryError):g.swept_slot(slot(),t,g.Canvas(100,100),(0,1))

    def test_all_content_strategies_do_not_expand(self):
        names=('slow_push_in.v1','slow_pull_out.v1','pan_horizontal_left.v1',
               'pan_horizontal_right.v1','pan_vertical_up.v1','pan_vertical_down.v1','subtle_drift.v1')
        for name in names:
            with self.subTest(strategy=name):
                t=track(name,space='media_content')
                t['keyframes'][0]['transform'].update(scale=1.04,translate_x=-.02,translate_y=.02)
                t['keyframes'][-1]['transform'].update(scale=1.02,translate_x=.02,translate_y=-.02)
                result=g.swept_slot(slot(),t,g.Canvas(100,100),(0,1))
                self.assertEqual(g.aabb(result[0].polygon),g.Rect(25,25,50,50))
                self.assertFalse(g.positive_overlap(result[0].polygon,g.Rect(75.1,40,.1,10).corners))

    def test_real_motion_candidates_satisfy_proof_guard(self):
        seen=set()
        for kind in ('fullscreen_media','hero_media','closing_card'):
            for orientation in ('portrait','landscape','square'):
                m=fixture(kind,orientations=[orientation]);b=m['visual_plan']['blocks'][0];s=b['resolved_layout']['slots'][0]
                if orientation=='portrait':m['photos'][0].update(width=1080,height=3840)
                s['fit_mode']='cover'
                for candidate in _candidates(m,b,s,'photo',m['photos'][0],(0,1,6),True):
                    t=candidate['track'];seen.add(t['strategy'])
                    sweeps=g.swept_slot(s,t,g.Canvas(1080,1920),(0,1))
                    if t['space']=='media_content':
                        base=g.slot_polygon(s,g.Canvas(1080,1920))
                        for sweep in sweeps:self.assertEqual(sweep.polygon,base)
        self.assertEqual(seen,set(g.STRATEGIES))


class CollisionTests(unittest.TestCase):
    def run_case(self, rect, *, kind='hero_media', visibility=(0,1), others=(), mutate=None, motion=False):
        m=fixture(kind); b=m['visual_plan']['blocks'][0];b['motion']['type']='none'
        if mutate:mutate(b)
        plan=resolve_motion(m,m['visual_plan']);before=copy.deepcopy((m,plan))
        o=dict(overlay_id='text',target=dict(scope='block'))
        with patch.object(g,'text_reservation',return_value=reservation(rect,visibility)):
            result=g.evaluate_collision(m,plan,0,o,g.Canvas(1080,1920),motion=motion,other_texts=others)
        self.assertEqual((m,plan),before)
        return result

    def test_preferred_geometry_safe(self):
        self.assertEqual(self.run_case(g.Rect(60,90,10,10)).status,'NONE')

    def test_canvas_violation(self):
        result=self.run_case(g.Rect(-1,90,10,10))
        self.assertEqual(result.status,'HARD')
        self.assertIn('canvas',[o.target_id for o in result.observations])

    def test_safe_area_violation(self):
        result=self.run_case(g.Rect(1,90,10,10))
        self.assertEqual(result.status,'HARD')
        self.assertNotIn('canvas',[o.target_id for o in result.observations])

    def test_host_static_card_overlap(self):
        self.assertEqual(self.run_case(g.Rect(200,400,10,10)).status,'PERMITTED')

    def test_protected_collage_overlap(self):
        def co_visible(b):
            for l in b['layout']['layers']:l['visual_layer_timing']=dict(start_seconds=0,end_seconds=6)
        # A large reservation intersects every card independently of slot ordering.
        r=self.run_case(g.Rect(50,80,950,1700),kind='collage',mutate=co_visible)
        self.assertEqual(r.status,'HARD')
        self.assertTrue(any(o.reason=='protected_slot_overlap' for o in r.observations))

    def test_text_collision_and_disjoint_visibility(self):
        rect=g.Rect(60,90,10,10)
        other=reservation(rect,(.5,1),'other')
        self.assertEqual(self.run_case(rect,visibility=(0,.5),others=(other,)).status,'NONE')
        self.assertEqual(self.run_case(rect,others=(other,)).status,'HARD')

    def test_determinism(self):
        self.assertEqual(self.run_case(g.Rect(200,400,10,10),motion=True),
                         self.run_case(g.Rect(200,400,10,10),motion=True))

    def test_interline_gap_not_reserved(self):
        a,b=g.Rect(60,90,10,10),g.Rect(60,120,10,10)
        other=g.TextReservation('other',(0,1),(g.TextLine('a',a,a,(60,99)),g.TextLine('b',b,b,(60,129))),
                                g.Rect(60,90,10,40),g.Rect(60,90,10,40))
        self.assertEqual(self.run_case(g.Rect(60,105,10,10),others=(other,)).status,'NONE')

    def test_temporally_disjoint_secondary_slot(self):
        # Two-up fixture inherits [0,.5) and [.5,1), even though both slots exist.
        rect=g.Rect(50,80,950,1700)
        first=self.run_case(rect,kind='two_up',visibility=(0,.5))
        whole=self.run_case(rect,kind='two_up')
        self.assertFalse(any(o.reason=='protected_slot_overlap' for o in first.observations))
        self.assertTrue(any(o.reason=='protected_slot_overlap' for o in whole.observations))

    def test_validated_intermediate_protected_card_collision(self):
        m=fixture('hero_media');plan=resolve_motion(m,m['visual_plan'])
        b=plan['blocks'][0];s=b['resolved_layout']['slots'][0]
        s.update(x=.25,y=.25,width=.5,height=.5,role='supporting')
        t=track('card_emphasis.v1');t['target_slot_id']=s['slot_id']
        b['resolved_motion']['tracks']=[t]
        o=dict(overlay_id='text',target=dict(scope='block'))
        # Static right edge=810px. Peak right edge=812.7px at scale 1.01.
        # x=811..812 is clear at both endpoints but covered at the peak.
        with patch.object(g,'text_reservation',return_value=reservation(g.Rect(811,800,1,10))):
            static=g.evaluate_collision(m,plan,0,o,g.Canvas(1080,1920),motion=False)
            swept=g.evaluate_collision(m,plan,0,o,g.Canvas(1080,1920))
        self.assertEqual(static.observations,())
        self.assertEqual(swept.status,'HARD')
        self.assertEqual(swept.observations[0].reason,'protected_slot_overlap')

    def test_missing_motion_rejected_before_text(self):
        m=fixture('hero_media')
        with self.assertRaises(ValueError):
            g.evaluate_collision(m,m['visual_plan'],0,{},g.Canvas(1080,1920))


@unittest.skipUnless(CJK.is_file() and ARIAL.is_file(),'Existing local font fixtures unavailable')
class TypographyAdapterTests(unittest.TestCase):
    def test_real_single_multiline_cjk_and_mixed(self):
        maker=typography_fixtures.MeasuredLayoutTests()
        for text,width,count in (('LOTTE WORLD ADVENTURE',886,1),
                                 ('A BEAUTIFUL DAY IN SEOUL',350,2),
                                 ('首爾自由行必去景點樂天世界冒險樂園',440,2),
                                 ('首爾 LOTTE WORLD ADVENTURE 樂天世界',490,2)):
            with self.subTest(text=text):
                o=maker.item(text,width=width);o['visibility']=dict(start=0,end=1)
                o['resolved_typography']=TypographyResolver(config()).resolve(o)
                before=copy.deepcopy(o);r=g.text_reservation(o,g.Canvas(1080,1920))
                self.assertEqual(o,before);self.assertEqual(len(r.lines),count)
                self.assertEqual(len(r.polygons),2*count)
                for line,row in zip(r.lines,o['resolved_typography']['measured_layout']['lines']):
                    self.assertEqual(line.text,row['text'])
                    self.assertAlmostEqual(line.baseline[1],row['baseline_y']*1920)

    def test_real_end_to_end_adapter(self):
        m=fixture('hero_media');plan=resolve_motion(m,m['visual_plan'])
        o=typography_fixtures.MeasuredLayoutTests().item();o.update(target=dict(scope='block'),visibility=dict(start=0,end=1))
        o['resolved_typography']=TypographyResolver(config()).resolve(o)
        before=copy.deepcopy((m,plan,o))
        r=g.evaluate_collision(m,plan,0,o,g.Canvas(1080,1920))
        self.assertIn(r.status,('NONE','PERMITTED'));self.assertIn('subject_safety',r.unassessed)
        self.assertEqual((m,plan,o),before)

    def test_mismatch_and_legacy_rejected(self):
        o=typography_fixtures.MeasuredLayoutTests().item();o['visibility']=dict(start=0,end=1)
        o['resolved_typography']=TypographyResolver(config()).resolve(o)
        with self.assertRaises(g.GeometryError):g.text_reservation(o,g.Canvas(540,960))
        o['resolved_typography']=TypographyResolver(config())._resolve_metrics(o)
        with self.assertRaises(g.GeometryError):g.text_reservation(o,g.Canvas(1080,1920))


if __name__=='__main__':unittest.main()
