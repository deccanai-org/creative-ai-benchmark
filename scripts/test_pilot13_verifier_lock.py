"""Regressions for the final verifier audit, independent of prior repair success claims."""
import copy
import json
import re
import subprocess
import unittest
from collections import Counter

from build_v7_annotation_pilot import TASK_IDS, TASKS, OUT, ROOT, SHEET_EXPORT
from finalize_pilot13_verifiers import split_checks, measurements, reconcile_verda, complete_coverage


class VerifierLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.specs = {tid: json.loads((TASKS / tid / 'TASK_SPEC.json').read_text()) for tid in TASK_IDS}
        cls.coverage = {tid: json.loads((OUT / 'coverage' / (tid + '.json')).read_text()) for tid in TASK_IDS}

    def test_every_live_check_is_mapped_to_its_own_file(self):
        for tid, spec in self.specs.items():
            checks = {c['check_id']: c for c in spec['verifiers_human'] + spec['verifiers_auto']}
            seen = set()
            for rule in self.coverage[tid]['rules']:
                for oid, cell in rule['cells'].items():
                    for cid in cell.get('checks', []):
                        self.assertEqual(checks[cid]['output_id'], oid)
                        seen.add(cid)
            self.assertEqual(seen, set(checks))

    def test_unverifiable_targets_are_excluded_not_passed(self):
        total = 0
        for tid, spec in self.specs.items():
            targets = spec['evaluation']['unscored_design_targets']
            cells = [c for r in self.coverage[tid]['rules'] for c in r['cells'].values() if 'not_verified' in c]
            self.assertEqual(len(targets), len(cells))
            for cell in cells:
                self.assertEqual(cell['scoring'], 'excluded')
                self.assertNotIn('checks', cell)
            total += len(targets)
        self.assertEqual(total, 1190)

    def test_no_fuzzy_measurement_methods(self):
        for spec in self.specs.values():
            for c in spec['verifiers_human']:
                self.assertIn(c['method'], ('look', 'measure'), c['check_id'])
                if c['method'] == 'measure':
                    self.assertNotRegex(c['method_note'], r'\bnearer\b|clearly under|clearly over|clearly coloured')
                if c.get('measurement', {}).get('kind') in ('area_ratio', 'area_comparison'):
                    self.assertIn('within ', c['method_note'])

    def test_split_checks_keep_ids_and_are_individually_mapped(self):
        for spec in self.specs.values():
            checks = {c['check_id']: c for c in spec['verifiers_human']}
            for c in checks.values():
                if 'split_from' in c:
                    self.assertIn(c['split_from'], checks)
            self.assertEqual(len(checks), len(spec['verifiers_human']))
        portrait = self.specs['PHOTO-20']['verifiers_human']
        self.assertTrue(any('retains natural skin colour' in c['check'] for c in portrait))
        self.assertFalse(any('natural skin and hair colour' in c['check'] for c in portrait))

    def test_verda_exception_matches_brand_and_coverage(self):
        spec = self.specs['PHOTO-28']
        for key in ('distribution', 'opacity', 'forbidden'):
            self.assertIn('#222724', spec['brand_identity']['palette_rules'][key])
        self.assertNotIn('verda_logo_web.png', json.dumps(spec['brand_identity']['type_system']))
        for r in self.coverage['PHOTO-28']['rules']:
            if r['rule_id'] in ('B01', 'B04', 'B05'):
                self.assertIn('original ink #222724', r['rule'])
        inks = [c for c in spec['verifiers_human'] if '#222724' in c['check']]
        self.assertEqual(len(inks), 6)
        self.assertTrue(all('within 4' in c['method_note'] for c in inks))

    def test_sheet_has_all_checks_policy_and_no_timing_claim(self):
        rows = json.loads(SHEET_EXPORT.read_text())
        headers = rows[0]
        for r in rows[1:]:
            self.assertEqual(len(r), len(headers))
            self.assertEqual(r[headers.index('estimated_minutes')], '')
            self.assertIn('excluded from the score denominator', r[headers.index('scoring_policy')])
        total = sum(len(json.loads(r[2])) for r in rows[1:])
        self.assertEqual(total, sum(len(s['verifiers_human']) for s in self.specs.values()))

    def test_coverage_lists_do_not_duplicate_check_ids(self):
        for tid, spec in self.specs.items():
            page = (OUT / 'coverage' / (tid + '.html')).read_text()
            rendered = re.findall(r'<code>([^<]+) · (?:auto|human)</code>', page)
            self.assertEqual(Counter(rendered), Counter(c['check_id'] for c in spec['verifiers_human'] + spec['verifiers_auto']))
            self.assertIn('Not scored', page)

    def test_repair_is_idempotent(self):
        for tid, original in self.specs.items():
            spec, cov = copy.deepcopy(original), copy.deepcopy(self.coverage[tid])
            self.assertEqual(split_checks(spec, cov), (0, 0))
            self.assertEqual(dict(measurements(spec)), {})
            reconcile_verda(spec, cov)
            added, _ = complete_coverage(spec, cov)
            self.assertEqual(added, 0)
            self.assertEqual(spec, original)
            self.assertEqual(cov, self.coverage[tid])

    def test_nonpilot_tasks_unchanged(self):
        path = 'docs/gatsby-v7/TASKS_V5_ALL100.json'
        before = json.loads(subprocess.check_output(['git', 'show', '6d1ce5b:' + path], cwd=ROOT))
        after = json.loads((ROOT / path).read_text())
        self.assertEqual([s for s in before if s['new_id'] not in TASK_IDS], [s for s in after if s['new_id'] not in TASK_IDS])


if __name__ == '__main__':
    unittest.main()
