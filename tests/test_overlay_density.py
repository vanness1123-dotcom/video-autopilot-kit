"""Minimum-gap policy boundaries, evidence preservation and persistence."""
import copy
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from travel_reel import overlay_density as density
from travel_reel.overlay import final_eligible_overlay, validate_overlay_plan, resolve_overlay
from travel_reel.pipeline import run_overlay_planner
from travel_reel.manifest import load_trip_manifest
from travel_reel.placement_contract import resolve_plan_placement
from tests.test_placement_contract import source_plan
from tests.test_placement import overlay
from tests import test_typography as fonts


def policy_plan(windows, outcomes=None):
    outcomes = outcomes or ['preferred'] * len(windows)
    blocks = []
    for i, ((start, end), outcome) in enumerate(zip(windows, outcomes)):
        blocks.append({'visual_block_id': f'b{i}', 'timeline_start_seconds': start,
                       'timeline_end_seconds': end, 'resolved_overlay': {
            'version': '1.1', 'overlays': [{'overlay_id': f'o{i}', 'time_space': 'block_normalized',
                                         'visibility': {'start': 0, 'end': 1}}],
            'placement_resolution': {'dependency_fingerprint': 'test',
                                    'decisions': [{'overlay_id': f'o{i}', 'outcome': outcome}]}}})
    return {'blocks': blocks}


def attach(plan):
    result = copy.deepcopy(plan)
    for b, child in zip(result['blocks'], density._expected(plan)):
        b['resolved_overlay'].update(version='1.2', density_admission=child)
    return result


def states(plan):
    return [d['state'] for c in density._expected(plan) for d in c['decisions']]


class DensityPolicyTests(unittest.TestCase):
    def test_empty_overlay_set(self):
        p = policy_plan([(0, 1)])
        p['blocks'][0]['resolved_overlay']['overlays'] = []
        p['blocks'][0]['resolved_overlay']['placement_resolution']['decisions'] = []
        self.assertEqual(states(p), [])
        self.assertTrue(density.validate_density_plan(attach(p)))

    def test_single_selected(self):
        self.assertEqual(states(policy_plan([(51.251, 52.997)])), ['admitted'])

    def test_below_gap(self):
        self.assertEqual(states(policy_plan([(0, 1), (1.499999999, 2)])), ['admitted', 'suppressed'])

    def test_exact_gap(self):
        self.assertEqual(states(policy_plan([(0, 1), (1.5, 2)])), ['admitted', 'admitted'])

    def test_above_gap(self):
        self.assertEqual(states(policy_plan([(0, 1), (1.500000001, 2)])), ['admitted', 'admitted'])

    def test_adjacent_half_open(self):
        self.assertEqual(states(policy_plan([(0, 1), (1, 2)])), ['admitted', 'suppressed'])

    def test_absolute_conversion_and_decimal_equality(self):
        p = policy_plan([(10, 11), (11, 12)])
        p['blocks'][0]['resolved_overlay']['overlays'][0]['visibility'] = {'start': .1, 'end': .2}
        p['blocks'][1]['resolved_overlay']['overlays'][0]['visibility'] = {'start': .1, 'end': .2}
        self.assertEqual(states(p), ['admitted', 'admitted'])
        p = policy_plan([(0, .3), (.3, 1.3)])
        p['blocks'][1]['resolved_overlay']['overlays'][0]['visibility']['start'] = .5
        self.assertEqual(states(p), ['admitted', 'admitted'])

    def test_order_and_replay(self):
        p = policy_plan([(0, 1), (1, 2), (2, 3)])
        self.assertEqual(attach(p), attach(attach(p)))
        p['blocks'].reverse()
        with self.assertRaises(density.DensityValidationError): density._expected(p)

    def test_source_order_tie(self):
        p = policy_plan([(0, 1)])
        c = p['blocks'][0]['resolved_overlay']
        o = copy.deepcopy(c['overlays'][0]); o['overlay_id'] = 'second'
        c['overlays'].append(o)
        c['placement_resolution']['decisions'].append({'overlay_id': 'second', 'outcome': 'alternate'})
        self.assertEqual(states(p), ['admitted', 'suppressed'])

    def test_omitted_does_not_consume_gap(self):
        self.assertEqual(states(policy_plan([(0, 1), (1, 2), (2, 3)], ['preferred', 'omitted', 'preferred'])),
                         ['admitted', 'not_eligible', 'admitted'])

    def test_first_omitted_does_not_consume_gap(self):
        self.assertEqual(states(policy_plan([(0, 1), (1, 2)], ['omitted', 'alternate'])),
                         ['not_eligible', 'admitted'])

    def test_suppressed_does_not_extend_gap(self):
        self.assertEqual(states(policy_plan([(0, 1), (1, 2), (2, 3)])), ['admitted', 'suppressed', 'admitted'])

    def test_duplicate_missing_decisions(self):
        for duplicate in (True, False):
            p = attach(policy_plan([(0, 1)])); ds = p['blocks'][0]['resolved_overlay']['density_admission']['decisions']
            if duplicate: ds.append(copy.deepcopy(ds[0]))
            else: ds.clear()
            with self.assertRaises(density.DensityValidationError): density.validate_density_plan(p)

    def test_malformed_policy_parameters(self):
        for value in (True, None, '0.5', -1, 0, 1, float('nan'), float('inf')):
            with self.subTest(value=value):
                p = attach(policy_plan([(0, 1)]))
                p['blocks'][0]['resolved_overlay']['density_admission']['minimum_gap_seconds'] = value
                with self.assertRaises(density.DensityValidationError): density.validate_density_plan(p)

    def test_stale_cross_block(self):
        p = attach(policy_plan([(0, 1), (2, 3)]))
        p['blocks'][0]['resolved_overlay']['overlays'][0]['visibility']['end'] = .5
        # Even the later block's otherwise unchanged decision is now stale.
        p['blocks'][0]['resolved_overlay']['density_admission'] = density._expected(p)[0]
        with self.assertRaises(density.DensityValidationError): density.validate_density_plan(p)

    def test_unsupported_versions(self):
        for field in ('version', 'policy_version'):
            p = attach(policy_plan([(0, 1)]))
            p['blocks'][0]['resolved_overlay']['density_admission'][field] = 'future'
            with self.assertRaises(density.DensityValidationError): density.validate_density_plan(p)

    def test_forged_state_reason_and_identity(self):
        for field, value in [('state', 'suppressed'), ('reason', 'invented'), ('overlay_id', 'unknown')]:
            p = attach(policy_plan([(0, 1)]))
            p['blocks'][0]['resolved_overlay']['density_admission']['decisions'][0][field] = value
            with self.assertRaises(density.DensityValidationError): density.validate_density_plan(p)

    def test_prior_output_and_runtime_excluded(self):
        p = policy_plan([(0, 1)])
        before = density._expected(p)
        p['runtime'] = 'ignored'; p['blocks'][0]['resolved_overlay']['density_admission'] = {'garbage': True}
        self.assertEqual(density._expected(p), before)

    def test_invalid_numeric_inputs(self):
        for value in (True, float('nan'), float('inf'), '1'):
            p = policy_plan([(0, 1)])
            p['blocks'][0]['timeline_end_seconds'] = value
            with self.assertRaises(density.DensityValidationError): density._expected(p)


@unittest.skipUnless(fonts.CJK.is_file() and fonts.ARIAL.is_file(), 'Local fonts unavailable')
class DensityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        a = overlay(text='SEOUL'); b = copy.deepcopy(a); b['overlay_id'] = 'second'
        cls.m, p = source_plan([a, b])
        cls.placed = resolve_plan_placement(cls.m, p, fonts.config())

    def test_source_placement_typography_geometry_visibility_preserved(self):
        before = copy.deepcopy((self.m, self.placed))
        result = density.resolve_density(self.m, self.placed)
        self.assertEqual((self.m, self.placed), before)
        projected = copy.deepcopy(result)
        for b in projected['blocks']:
            b['resolved_overlay'].pop('density_admission'); b['resolved_overlay']['version'] = '1.1'
        self.assertEqual(projected, self.placed)

    def test_final_accessor_admitted_suppressed_and_isolation(self):
        p = density.resolve_density(self.m, self.placed)
        ids = [o['overlay_id'] for o in p['blocks'][0]['resolved_overlay']['overlays']]
        final = final_eligible_overlay(self.m, p, ids[0])
        self.assertIsNotNone(final)
        self.assertIsNone(final_eligible_overlay(self.m, p, ids[1]))
        final['content']['text'] = 'changed'
        self.assertEqual(p['blocks'][0]['resolved_overlay']['overlays'][0]['content']['text'], 'SEOUL')

    def test_legacy_loading_and_accessor(self):
        m, v = source_plan()
        for plan, version in ((v, '1.13'), (self.placed, '1.14')):
            data = copy.deepcopy(m); data.update(visual_plan=plan, manifest_version=version)
            with TemporaryDirectory() as d:
                path = Path(d)/'m.json'; path.write_text(json.dumps(data), encoding='utf-8')
                self.assertEqual(load_trip_manifest(path), data)
        oid = v['blocks'][0]['resolved_overlay']['overlays'][0]['overlay_id']
        with self.assertRaises(ValueError): final_eligible_overlay(m, v, oid)
        self.assertIsNotNone(final_eligible_overlay(self.m, self.placed, oid))

    def test_overlay_version_and_missing_child_rejected(self):
        for version in ('1.3', '1.2'):
            p = copy.deepcopy(self.placed); p['blocks'][0]['resolved_overlay']['version'] = version
            with self.assertRaises(ValueError): validate_overlay_plan(p, p, self.m)

    def test_pipeline_migration_idempotency_and_conditional_persistence(self):
        with TemporaryDirectory() as d:
            root = Path(d); (root/'output').mkdir(); path = root/'output/trip_manifest.json'
            m = fonts.valid_manifest(); m['manifest_version'] = '1.14'
            m['visual_plan'] = resolve_plan_placement(m, resolve_overlay(m, m['visual_plan']))
            m['render'] = {'old': True}; path.write_text(json.dumps(m), encoding='utf-8')
            run_overlay_planner(root)
            first = path.read_bytes(); saved = load_trip_manifest(path)
            self.assertEqual(saved['manifest_version'], '1.15'); self.assertNotIn('render', saved)
            self.assertEqual(saved['reel_plan'], m['reel_plan'])
            run_overlay_planner(root); self.assertEqual(first, path.read_bytes())
            saved['render'] = {'keep': True}; path.write_text(json.dumps(saved), encoding='utf-8')
            before = path.read_bytes()
            with patch('travel_reel.pipeline.save_trip_manifest_atomic') as save:
                run_overlay_planner(root); save.assert_not_called()
            self.assertEqual(path.read_bytes(), before)

    def test_density_failure_does_not_persist(self):
        with TemporaryDirectory() as d:
            root = Path(d); (root/'output').mkdir(); path = root/'output/trip_manifest.json'
            path.write_text(json.dumps(fonts.valid_manifest()), encoding='utf-8'); before = path.read_bytes()
            with patch.object(density, 'resolve_density', side_effect=density.DensityValidationError('forced')):
                with self.assertRaises(density.DensityValidationError): run_overlay_planner(root)
            self.assertEqual(path.read_bytes(), before)
