"""Non-persistent candidate policy, reflow, selection and preservation."""
import copy
import unittest
from unittest.mock import patch

from travel_reel import placement as p
from travel_reel import placement_geometry as g
from travel_reel.motion import resolve_motion
from travel_reel.typography import TypographyResolver, TypographyError
from tests.test_motion import fixture
from tests import test_typography as fonts
from tests.test_placement_geometry import reservation, track


def scene(kind='hero_media'):
    m=fixture(kind);m['story']={'title':'Preserve editorial meaning'}
    m['visual_plan']['blocks'][0]['motion']['type']='none'
    v=resolve_motion(m,m['visual_plan'])
    return m,v


def overlay(kind='caption',text='A BEAUTIFUL DAY IN SEOUL',width=.82):
    o=fonts.MeasuredLayoutTests().item(text,width=width*1080,height=.14*1920,kind=kind,
                                       lines=1 if kind in ('section_label','location_label') else 2,
                                       size='large' if kind in ('title','closing_title') else 'small')
    o.update(target={'scope':'block'},time_space='block_normalized',visibility={'start':0,'end':1},
             z_order=100,validation={'safe':True,'collision_policy':'static_basic'})
    o['placement'].update(region='upper_safe',anchor='top_left')
    o['style'].update(opacity=1,background_treatment='none')
    return o


class CandidateTests(unittest.TestCase):
    def candidates(self,kind='caption'):
        m,v=scene();o=overlay(kind)
        return o,p.generate_candidates(o,v['blocks'][0])

    def test_preferred_first(self):
        o,c=self.candidates()
        self.assertTrue(c.candidates[0].preferred)
        self.assertEqual(c.candidates[0].placement,o['placement'])
        self.assertEqual(c.candidates[0].order,0)

    def test_deterministic_ids_order_and_no_history(self):
        o,c=self.candidates();m,v=scene()
        o['resolved_placement']={'old':'ignored'}
        self.assertEqual(c,p.generate_candidates(dict(reversed(list(o.items()))),v['blocks'][0]))
        self.assertEqual(len({x.candidate_id for x in c.candidates}),len(c.candidates))

    def test_duplicate_removal(self):
        o,c=self.candidates('location_label')
        keys=[(x.anchor,x.alignment,x.container) for x in c.candidates]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertEqual(sum(x.container==c.candidates[0].container and x.anchor=='top_left' for x in c.candidates),1)

    def test_cap_and_truncation(self):
        for kind in p.TYPES:
            o,c=self.candidates(kind)
            self.assertLessEqual(len(c.candidates),12)
            self.assertEqual([x.order for x in c.candidates],list(range(len(c.candidates))))
        self.assertTrue(self.candidates('location_label')[1].truncated)

    def test_semantic_order(self):
        for kind in p.TYPES:
            o,c=self.candidates(kind)
            expected=[a for a in p.ANCHOR_ORDERS[kind] if a!='top_left']
            actual=[x.anchor for x in c.candidates[1:] if x.width_variant==1]
            self.assertEqual(actual,expected)

    def test_coherent_alignment(self):
        for kind in p.TYPES:
            for c in self.candidates(kind)[1].candidates:
                expected='left' if c.anchor.endswith('left') else 'right' if c.anchor.endswith('right') else 'center'
                self.assertEqual(c.alignment,expected)

    def test_width_rounds(self):
        o,c=self.candidates('title')
        widths=[x.width_variant for x in c.candidates[1:]]
        self.assertEqual(widths,sorted(widths,reverse=True))
        self.assertEqual(set(widths),{1,.85,.7})
        for x in c.candidates:self.assertAlmostEqual(x.container.width,round(.82*x.width_variant,6))

    def test_slot_bounded_containers(self):
        m,v=scene();o=overlay();s=v['blocks'][0]['resolved_layout']['slots'][0]
        o['target']={'scope':'slot','target_slot_id':s['slot_id']}
        c=p.generate_candidates(o,v['blocks'][0])
        for x in c.candidates[1:]:
            self.assertGreaterEqual(x.container.x,s['x'])
            self.assertLessEqual(x.container.x+x.container.width,s['x']+s['width']+1e-9)

    def test_projection_only_changes_placement_alignment(self):
        o,c=self.candidates();candidate=next(x for x in c.candidates if x.anchor=='bottom_right')
        o['resolved_typography']={'sentinel':'preserve'};before=copy.deepcopy(o)
        q=p.candidate_projection(o,candidate)
        self.assertEqual(o,before);self.assertNotIn('resolved_typography',q)
        self.assertEqual(q['content'],o['content']);self.assertEqual(q['style']['alignment'],'right')
        self.assertEqual({k:v for k,v in q['style'].items() if k!='alignment'},
                         {k:v for k,v in o['style'].items() if k!='alignment'})


@unittest.skipUnless(fonts.CJK.is_file() and fonts.ARIAL.is_file(),'Local font fixtures unavailable')
class ResolverTests(unittest.TestCase):
    def resolve(self,m,v,o,**kw):return p.resolve_placement(m,v,0,o,fonts.config(),**kw)

    def test_preferred_immediate_even_with_host_overlap(self):
        m,v=scene();o=overlay();o['placement'].update(x=.15,y=.3)
        o['placement']['width']=.7
        with patch.object(p,'evaluate_candidate',wraps=p.evaluate_candidate) as evaluate:
            d=self.resolve(m,v,o)
        self.assertEqual(d.outcome,'PREFERRED');self.assertEqual(evaluate.call_count,1)
        self.assertEqual(d.selected.motion.status,'PERMITTED')

    def test_repeated_preferred_result(self):
        m,v=scene();o=overlay()
        self.assertEqual(self.resolve(m,v,o),self.resolve(m,v,o))

    def test_prior_overlay_forces_alternate(self):
        m,v=scene();o=overlay()
        a=reservation(g.Rect(43.2,76.8,993.6,400),name='A')
        d=self.resolve(m,v,o,other_texts=(a,))
        self.assertEqual(d.outcome,'ALTERNATE')
        self.assertTrue(d.selected.candidate.anchor.startswith('bottom'))
        self.assertIn('static_collision',d.evaluations[0].reasons)

    def test_all_prior_overlay_collisions_omit_without_deletion(self):
        m,v=scene();o=overlay('title',text='Travel')
        before=copy.deepcopy(o)
        a=reservation(g.Rect(0,0,1080,1920),name='A')
        d=self.resolve(m,v,o,other_texts=(a,))
        self.assertEqual(d.outcome,'OMITTED');self.assertEqual(d.reason,'all_candidates_collision')
        self.assertEqual(o,before)

    def test_budget_exhausted_deterministic(self):
        m,v=scene();o=overlay('location_label',text='SEOUL')
        a=reservation(g.Rect(0,0,1080,1920),name='A')
        d=self.resolve(m,v,o,other_texts=(a,))
        self.assertEqual(d.reason,'candidate_budget_exhausted');self.assertEqual(len(d.evaluations),12)
        self.assertEqual(d,self.resolve(m,v,o,other_texts=(a,)))

    def test_all_typography_failure(self):
        m,v=scene();o=overlay(text='SUPERCALIFRAGILISTICEXPIALIDOCIOUS',width=.03)
        d=self.resolve(m,v,o)
        self.assertEqual(d.outcome,'OMITTED');self.assertEqual(d.reason,'all_candidates_typography_failure')

    def test_no_valid_host(self):
        m,v=scene();v['blocks'][0]['resolved_layout']['slots'][0]['role']='supporting'
        d=self.resolve(m,v,overlay())
        self.assertEqual(d.reason,'no_valid_host');self.assertEqual(d.evaluations,())

    def test_malformed_motion_not_candidate_failure(self):
        m,v=scene();v['blocks'][0]['resolved_motion']['version']='future'
        with self.assertRaises(ValueError):self.resolve(m,v,overlay())

    def test_font_failure_not_candidate_rejection(self):
        m,v=scene()
        with patch.object(p.TypographyResolver,'resolve',side_effect=TypographyError('font missing')):
            with self.assertRaises(TypographyError):self.resolve(m,v,overlay())

    def test_preserve_all_input_and_isolate_alternate(self):
        m,v=scene();o=overlay();o['resolved_typography']=TypographyResolver(fonts.config()).resolve(o)
        before=copy.deepcopy((m,v,o));a=reservation(g.Rect(43.2,76.8,993.6,400),name='A')
        d=self.resolve(m,v,o,other_texts=(a,))
        self.assertEqual((m,v,o),before)
        self.assertIsNot(d.selected.typography,o['resolved_typography'])
        d.selected.typography['measured_layout']['lines'][0]['text']='mutated result only'
        self.assertEqual((m,v,o),before)

    def test_protected_static_card_to_alternate(self):
        m,v=scene('two_up');b=v['blocks'][0]
        # Legal nonoverlapping layout: primary low, supporting high.
        b['resolved_layout']['slots'][0].update(x=.1,y=.5,width=.3,height=.4)
        b['resolved_layout']['slots'][1].update(x=.1,y=.08,width=.8,height=.3)
        for l in b['layout']['layers']:l['visual_layer_timing']=dict(start_seconds=0,end_seconds=6)
        for t in b['resolved_motion']['tracks']:
            t['keyframes'][0]['t']=0;t['keyframes'][-1]['t']=1
        d=self.resolve(m,v,overlay(text='SEOUL'))
        self.assertEqual(d.outcome,'ALTERNATE')
        self.assertTrue(any(x.reason=='protected_slot_overlap' for x in d.evaluations[0].static.observations))

    def test_motion_only_collision_to_alternate(self):
        m,v=scene('two_up');b=v['blocks'][0];b['motion']['type']='scale'
        b['resolved_layout']['slots'][0].update(x=.1,y=.6,width=.3,height=.3)
        b['resolved_layout']['slots'][1].update(x=.2,y=.2,width=.5,height=.2)
        for l in b['layout']['layers']:l['visual_layer_timing']=dict(start_seconds=0,end_seconds=6)
        for t in b['resolved_motion']['tracks']:
            t['keyframes'][0]['t']=0;t['keyframes'][-1]['t']=1
        t=track('card_emphasis.v1');t['target_slot_id']='slot-002';b['resolved_motion']['tracks'][1]=t
        o=overlay(text='SEOUL',width=.2)
        # Top of static card=384px, peak top=382.08px. Font advance box ends at 383px.
        metrics=TypographyResolver(fonts.config()).resolve(o)['measured_layout']
        h=metrics['line_height']*1920
        o['placement'].update(x=.3,y=(383-h)/1920)
        d=self.resolve(m,v,o)
        self.assertEqual(d.outcome,'ALTERNATE')
        self.assertNotEqual(d.evaluations[0].static.status,'HARD')
        self.assertEqual(d.evaluations[0].motion.status,'HARD')

    def test_content_pan_preferred_retained(self):
        m=fixture('fullscreen_media',orientations=['landscape']);m['visual_plan']['blocks'][0]['motion']['type']='pan_left'
        v=resolve_motion(m,m['visual_plan'])
        self.assertEqual(v['blocks'][0]['resolved_motion']['tracks'][0]['space'],'media_content')
        self.assertEqual(self.resolve(m,v,overlay()).outcome,'PREFERRED')

    def test_collage_uses_existing_collision_policy(self):
        m,v=scene('collage');o=overlay(text='SEOUL')
        d=self.resolve(m,v,o)
        self.assertIn(d.outcome,('PREFERRED','ALTERNATE','OMITTED'))
        for e in d.evaluations:
            if e.accepted:self.assertNotEqual(e.motion.status,'HARD')

    def test_explicit_host_containment_rejects_preferred(self):
        m,v=scene();o=overlay(text='SEOUL');o['target']={'scope':'slot','target_slot_id':'slot-001'}
        d=self.resolve(m,v,o)
        self.assertEqual(d.outcome,'ALTERNATE')
        self.assertIn('host_containment_failure',d.evaluations[0].reasons)

    def test_other_reservations_disjoint_in_time(self):
        m,v=scene();o=overlay();o['visibility']['end']=.5
        a=reservation(g.Rect(0,0,1080,1920),(.5,1),'A')
        self.assertEqual(self.resolve(m,v,o,other_texts=(a,)).outcome,'PREFERRED')


@unittest.skipUnless(fonts.CJK.is_file() and fonts.ARIAL.is_file(),'Local font fixtures unavailable')
class ReflowTests(unittest.TestCase):
    def evaluate(self,text,width):
        m,v=scene();o=overlay(text=text,width=width/1080)
        candidates=p.generate_candidates(o,v['blocks'][0]).candidates
        resolver=TypographyResolver(fonts.config());canvas=g.Canvas(1080,1920)
        first=p.evaluate_candidate(m,v,0,o,candidates[0],resolver,canvas)
        narrow=next(c for c in candidates if c.width_variant==.85)
        second=p.evaluate_candidate(m,v,0,o,narrow,resolver,canvas)
        return o,first,second

    def test_latin_narrower_wrap(self):
        o,a,b=self.evaluate('A BEAUTIFUL DAY IN SEOUL',550)
        self.assertTrue(a.accepted and b.accepted)
        self.assertEqual(len(a.typography['measured_layout']['lines']),1)
        self.assertEqual(len(b.typography['measured_layout']['lines']),2)

    def test_cjk_reflow(self):
        o,a,b=self.evaluate('首爾自由行必去景點樂天世界冒險樂園',750)
        self.assertTrue(b.accepted)
        self.assertEqual(len(a.typography['measured_layout']['lines']),1)
        self.assertEqual(len(b.typography['measured_layout']['lines']),2)
        self.assertEqual(''.join(x['text'] for x in b.typography['measured_layout']['lines']),o['content']['text'])

    def test_mixed_reflow(self):
        o,a,b=self.evaluate('首爾 LOTTE WORLD ADVENTURE 樂天世界',750)
        self.assertTrue(b.accepted)
        self.assertEqual(len(b.typography['measured_layout']['lines']),2)
        for token in ('LOTTE','WORLD','ADVENTURE'):
            self.assertTrue(any(token in x['text'] for x in b.typography['measured_layout']['lines']))

    def test_right_alignment_fresh_metrics(self):
        m,v=scene();o=overlay(text='SEOUL')
        c=next(c for c in p.generate_candidates(o,v['blocks'][0]).candidates if c.anchor=='bottom_right')
        with patch.object(p.TypographyResolver,'resolve',wraps=TypographyResolver(fonts.config()).resolve) as resolve:
            e=p.evaluate_candidate(m,v,0,o,c,TypographyResolver(fonts.config()),g.Canvas(1080,1920))
        self.assertEqual(resolve.call_count,1)
        measured=e.typography['measured_layout'];line=measured['lines'][0]
        self.assertEqual(measured['alignment'],'right')
        self.assertGreater(line['baseline_x'],c.container.x)
        self.assertEqual(measured['preferred_container']['y'],c.container.y)


class RankingTests(unittest.TestCase):
    def value(self,ellipsis=False,size=40,step=0,priority=1,distance=.1,identity='b'):
        c=p.Candidate(identity,'o',1,'lower_safe','bottom_center','center',g.Rect(.1,.8,.8,.1),False,1,priority)
        return p.Evaluation(c,True,(),{'measured_layout':{'ellipsis':ellipsis,'resolved_font_size':size,'size_step':step}},None,None,distance)

    def test_full_text_before_ellipsis(self):
        self.assertLess(p.rank_key(self.value(size=34)),p.rank_key(self.value(ellipsis=True)))

    def test_larger_size_before_anchor(self):
        self.assertLess(p.rank_key(self.value(size=40,priority=5)),p.rank_key(self.value(size=38,priority=0)))

    def test_anchor_before_distance(self):
        self.assertLess(p.rank_key(self.value(priority=0,distance=.9)),p.rank_key(self.value(priority=1,distance=.01)))

    def test_distance_before_identity(self):
        self.assertLess(p.rank_key(self.value(distance=.1,identity='z')),p.rank_key(self.value(distance=.2,identity='a')))

    def test_id_final_tie(self):
        self.assertLess(p.rank_key(self.value(identity='a')),p.rank_key(self.value(identity='b')))

    def test_distance_pixel_diagonal(self):
        c=self.value().candidate
        preferred=dict(x=.1,y=.1,width=.8,height=.1)
        self.assertAlmostEqual(p.placement_distance(c,preferred,g.Canvas(1080,1920)),.7*1920/(1080**2+1920**2)**.5)


class HostContainmentTests(unittest.TestCase):
    def test_convex_containment_contact_and_rotation(self):
        diamond=((0,1),(1,0),(2,1),(1,2))
        self.assertTrue(g.contains_polygon(diamond,g.Rect(.5,.5,1,1).corners))
        self.assertFalse(g.contains_polygon(diamond,g.Rect(0,0,.1,.1).corners))

    def test_shrinking_host_requires_entire_interval(self):
        m,v=scene();b=v['blocks'][0];s=b['resolved_layout']['slots'][0]
        s.update(x=.25,y=.25,width=.5,height=.5)
        t=track('card_enter.v1');t['target_slot_id']=s['slot_id'];b['resolved_motion']['tracks']=[t]
        o=overlay();o['target']={'scope':'slot','target_slot_id':s['slot_id']}
        # Left edge is 270px normally, 272.7px at the initial scale .99.
        r=reservation(g.Rect(271,800,1,10))
        self.assertFalse(g.required_host_contains(b,o,r,g.Canvas(1080,1920)))
        r=reservation(g.Rect(271,800,1,10),(.1,1))
        self.assertTrue(g.required_host_contains(b,o,r,g.Canvas(1080,1920)))


if __name__=='__main__':unittest.main()
