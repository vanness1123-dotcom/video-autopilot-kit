"""Placement persistence: authority, validation, replay and atomic upgrade."""
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from travel_reel import placement_contract as pc
from travel_reel.overlay import validate_overlay_plan, resolve_overlay
from travel_reel.typography import TypographyResolver, TypographyConfig, TypographyError
from travel_reel.manifest import load_trip_manifest
from travel_reel.pipeline import run_overlay_planner
from tests.test_placement import scene, overlay
from tests import test_typography as fonts


def source_plan(overlays=None):
    m,v=scene();m.update(trip={},manifest_version='1.13')
    v['blocks'][0]['resolved_overlay']={'version':'1.0','overlays':overlays if overlays is not None else [overlay(text='SEOUL')], 'selection_reasons':['test_source']}
    m['visual_plan']=copy.deepcopy(v)
    return m,v


@unittest.skipUnless(fonts.CJK.is_file() and fonts.ARIAL.is_file(),'Existing local fonts unavailable')
class PlacementContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m,cls.v=source_plan()
        cls.resolved=pc.resolve_plan_placement(cls.m,cls.v,fonts.config())

    def fresh(self):return copy.deepcopy((self.m,self.resolved))
    def child(self,v):return v['blocks'][0]['resolved_overlay']['placement_resolution']
    def validate(self,m,v):return validate_overlay_plan(v,v,m)
    def reject(self,change):
        m,v=self.fresh();change(v)
        with self.assertRaises(ValueError):self.validate(m,v)

    def test_legacy_1_0_load(self):
        with TemporaryDirectory() as d:
            p=Path(d)/'manifest.json';p.write_text(json.dumps(self.m),encoding='utf-8')
            self.assertEqual(load_trip_manifest(p)['manifest_version'],'1.13')

    def test_valid_1_1_load(self):
        m,v=self.fresh();m.update(visual_plan=v,manifest_version='1.14')
        with TemporaryDirectory() as d:
            p=Path(d)/'manifest.json';p.write_text(json.dumps(m),encoding='utf-8')
            self.assertEqual(load_trip_manifest(p),m)

    def test_missing_overlay_version_not_silently_loaded(self):
        m,v=self.fresh();m.update(visual_plan=v,manifest_version='1.14')
        v['blocks'][0]['resolved_overlay'].pop('version')
        with TemporaryDirectory() as d:
            p=Path(d)/'manifest.json';p.write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaises(ValueError):load_trip_manifest(p)

    def test_unsupported_overlay_version(self):
        self.reject(lambda v:v['blocks'][0]['resolved_overlay'].update(version='2.0'))

    def test_supported_placement_contract(self):
        self.assertTrue(self.validate(*self.fresh()))
        self.assertEqual(self.child(self.resolved)['version'],'1.0')

    def test_unsupported_placement_versions(self):
        for field in ('version','policy_version','candidate_policy_version'):
            with self.subTest(field=field):self.reject(lambda v:self.child(v).update({field:'future'}))

    def test_malformed_decision(self):
        for field,value in (('outcome','render_anyway'),('extra',1),('selected_candidate_id','unknown'),
                            ('placement_authority','selected'),('typography_authority','none'),
                            ('static_result','safe'),('motion_result','none'),('safety_status','safe')):
            if field=='motion_result':value='hard'
            with self.subTest(field=field):self.reject(lambda v:self.child(v)['decisions'][0].update({field:value}))

    def test_duplicate_decisions(self):
        self.reject(lambda v:self.child(v)['decisions'].append(copy.deepcopy(self.child(v)['decisions'][0])))

    def test_missing_decision(self):self.reject(lambda v:self.child(v)['decisions'].clear())

    def test_unknown_overlay(self):
        self.reject(lambda v:self.child(v)['decisions'][0].update(overlay_id='unknown'))

    def test_invalid_fingerprint(self):
        for bad in ('invalid','a'*64,True):
            with self.subTest(bad=bad):self.reject(lambda v:self.child(v).update(dependency_fingerprint=bad))

    def test_invalid_scope(self):
        self.reject(lambda v:self.child(v)['safety_scope']['unassessed'].remove('faces'))

    def test_invalid_canvas(self):
        for bad in ({'width':True,'height':1920},{'width':1080,'height':960},{'width':float('nan'),'height':1920}):
            with self.subTest(bad=bad):self.reject(lambda v:self.child(v).update(design_canvas=bad))

    def test_invalid_counts(self):
        for field,value in (('candidate_count',13),('candidate_count',True),('evaluated_count',0),
                            ('rejected_count',1),('rejected_counts',{'static_collision':1}),('truncated',1)):
            with self.subTest(field=field):self.reject(lambda v:self.child(v)['decisions'][0].update({field:value}))

    def test_preferred_authority_and_no_duplicate_metrics(self):
        c=self.resolved['blocks'][0]['resolved_overlay'];d=c['placement_resolution']['decisions'][0]
        self.assertEqual(d['outcome'],'preferred');self.assertEqual(d['typography_authority'],'preferred')
        self.assertNotIn('selected_typography',d);self.assertNotIn('selected_placement',d)
        final=pc.selected_overlay(c['overlays'][0],d)
        self.assertEqual(final,c['overlays'][0])
        self.assertEqual(c['overlays'][0]['placement'],self.v['blocks'][0]['resolved_overlay']['overlays'][0]['placement'])

    def test_two_overlays_alternate_authority(self):
        a=overlay(text='SEOUL');b=copy.deepcopy(a);b['overlay_id']='overlay-B'
        m,v=source_plan([a,b]);before=copy.deepcopy(v)
        out=pc.resolve_plan_placement(m,v,fonts.config());c=out['blocks'][0]['resolved_overlay'];d=c['placement_resolution']['decisions']
        self.assertEqual([x['outcome'] for x in d],['preferred','alternate'])
        self.assertEqual(v,before);self.assertEqual(c['overlays'][1]['placement'],b['placement'])
        final=pc.selected_overlay(c['overlays'][1],d[1])
        self.assertEqual(final['resolved_typography'],d[1]['selected_typography'])
        self.assertEqual(final['placement'],d[1]['selected_placement'])
        self.assertEqual(final['resolved_typography']['measured_layout']['preferred_container'],
                         {k:final['placement'][k] for k in ('x','y','width','height')})
        broken=copy.deepcopy(out);self.child(broken)['decisions'][1]['selected_placement']['x']=float('nan')
        with self.assertRaises(ValueError):self.validate(m,broken)
        broken=copy.deepcopy(out);self.child(broken)['decisions'][1]['selected_typography']=copy.deepcopy(c['overlays'][1]['resolved_typography'])
        with self.assertRaises(ValueError):self.validate(m,broken)

    def test_omission_preserves_editorial_trace_and_ids(self):
        a=overlay(text='SUPERCALIFRAGILISTICEXPIALIDOCIOUS',width=.03)
        b=overlay(text='SEOUL');b['overlay_id']='keep-id'
        m,v=source_plan([a,b]);out=pc.resolve_plan_placement(m,v,fonts.config());c=out['blocks'][0]['resolved_overlay']
        first,second=c['placement_resolution']['decisions']
        self.assertEqual(first['outcome'],'omitted');self.assertEqual(first['reason_codes'],['all_candidates_typography_failure'])
        self.assertIsNone(pc.selected_overlay(c['overlays'][0],first))
        self.assertNotIn('resolved_typography',c['overlays'][0])
        self.assertEqual(c['overlays'][0]['content'],a['content'])
        self.assertEqual(second['overlay_id'],'keep-id');self.assertEqual(second['outcome'],'preferred')
        broken=copy.deepcopy(out);self.child(broken)['decisions'][0]['selected_placement']=a['placement']
        with self.assertRaises(ValueError):self.validate(m,broken)

    def test_disjoint_overlay_visibility(self):
        a=overlay(text='SEOUL');a['visibility']['end']=.5
        b=copy.deepcopy(a);b['overlay_id']='B';b['visibility']={'start':.5,'end':1}
        m,v=source_plan([a,b]);out=pc.resolve_plan_placement(m,v,fonts.config())
        self.assertEqual([d['outcome'] for d in self.child(out)['decisions']],['preferred','preferred'])

    def test_stable_order_no_backward_feedback(self):
        a=overlay(text='SEOUL');b=copy.deepcopy(a);b['overlay_id']='B'
        m,v=source_plan([a,b]);two=pc.resolve_plan_placement(m,v,fonts.config())
        m1,v1=source_plan([a]);one=pc.resolve_plan_placement(m1,v1,fonts.config())
        self.assertEqual(self.child(one)['decisions'][0],self.child(two)['decisions'][0])
        broken=copy.deepcopy(two);self.child(broken)['decisions'].reverse()
        with self.assertRaises(ValueError):self.validate(m,broken)

    def test_live_replay(self):
        self.assertTrue(pc.validate_live_placement(self.m,self.resolved,fonts.config()))

    def test_fingerprint_repeated(self):
        self.assertEqual(pc.resolve_plan_placement(self.m,self.v,fonts.config()),self.resolved)

    def test_layout_dependency(self):
        self.reject(lambda v:v['blocks'][0]['resolved_layout']['slots'][0].update(x=.09))

    def test_motion_dependency(self):
        self.reject(lambda v:v['blocks'][0]['resolved_motion']['tracks'][0]['keyframes'][0]['transform'].update(scale=1.001))

    def test_typography_dependency(self):
        self.reject(lambda v:v['blocks'][0]['resolved_overlay']['overlays'][0]['resolved_typography'].update(dependency_fingerprint='a'*64))

    def test_preferred_geometry_dependency(self):
        self.reject(lambda v:v['blocks'][0]['resolved_overlay']['overlays'][0]['placement'].update(x=.07))

    def test_policy_dependency(self):
        m,v=self.fresh();block=v['blocks'][0];canvas=self.child(v)['design_canvas']
        before=pc.dependency_fingerprint(block,m,canvas)
        with patch.object(pc,'POLICY','future'):
            self.assertNotEqual(before,pc.dependency_fingerprint(block,m,canvas))

    def test_irrelevant_metadata_and_previous_output_excluded(self):
        m,v=self.fresh();b=v['blocks'][0];c=self.child(v)['design_canvas']
        before=pc.dependency_fingerprint(b,m,c)
        m.update(render={'state':'irrelevant'},timestamp='tomorrow',runtime=999)
        b.update(debug={'trace':1},timestamp='tomorrow',runtime=999)
        b['resolved_overlay']['placement_resolution']['decisions']=[]
        self.assertEqual(before,pc.dependency_fingerprint(b,m,c))

    def test_upstream_exact_preservation(self):
        m,v=self.fresh();before=copy.deepcopy(m)
        result=pc.resolve_plan_placement(m,self.v,fonts.config())
        a,b=copy.deepcopy(self.v),copy.deepcopy(result)
        for plan in (a,b):plan['blocks'][0].pop('resolved_overlay')
        self.assertEqual(a,b);self.assertEqual(m,before)

    def test_atomic_validation_failure(self):
        with TemporaryDirectory() as d:
            root=Path(d);(root/'output').mkdir();path=root/'output/trip_manifest.json'
            m=fonts.valid_manifest();path.write_text(json.dumps(m),encoding='utf-8');before=path.read_bytes()
            with patch.object(pc,'validate_placement_resolution',side_effect=pc.PlacementContractError('forced')):
                with self.assertRaises(pc.PlacementContractError):run_overlay_planner(root)
            self.assertEqual(path.read_bytes(),before)

    def test_atomic_candidate_font_failure(self):
        m,v=self.fresh();before=copy.deepcopy((m,v))
        with patch('travel_reel.placement.TypographyResolver.resolve',side_effect=TypographyError('font failure')):
            with self.assertRaises(TypographyError):pc.resolve_plan_placement(m,v,fonts.config())
        self.assertEqual((m,v),before)

    def test_pipeline_upgrade_idempotency_and_render_invalidation(self):
        with TemporaryDirectory() as d:
            root=Path(d);(root/'output').mkdir();path=root/'output/trip_manifest.json'
            m=fonts.valid_manifest();m['manifest_version']='1.13'
            m['visual_plan']=resolve_overlay(m,m['visual_plan'])
            for b in m['visual_plan']['blocks']:
                for o in b['resolved_overlay']['overlays']:o['resolved_typography']=TypographyResolver().resolve(o)
            m['render']={'old':True};path.write_text(json.dumps(m),encoding='utf-8')
            run_overlay_planner(root);first=path.read_bytes();saved=load_trip_manifest(path)
            self.assertEqual(saved['manifest_version'],'1.15');self.assertNotIn('render',saved)
            self.assertEqual(saved['reel_plan'],m['reel_plan']);self.assertEqual(saved['story'],m['story'])
            run_overlay_planner(root);self.assertEqual(path.read_bytes(),first)
            saved['render']={'keep':True};path.write_text(json.dumps(saved),encoding='utf-8');before=path.read_bytes()
            run_overlay_planner(root);self.assertEqual(path.read_bytes(),before)

    def test_empty_block_has_explicit_empty_resolution(self):
        m,v=source_plan([]);out=pc.resolve_plan_placement(m,v,fonts.config())
        self.assertEqual(self.child(out)['decisions'],[])
        self.assertTrue(self.validate(m,out))


if __name__=='__main__':unittest.main()
