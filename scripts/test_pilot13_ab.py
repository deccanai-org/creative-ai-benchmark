#!/usr/bin/env python3
"""Regression checks for the 2026-10-21 pilot-13 verifier fixes (items A and B).

These enforce what the client, design team and creative expert asked for: every brief and brand constraint
checked on every deliverable it applies to, atomic plain-language human checks that name their output, no
machine facts or unjudgeable measurements asked of people, and auto checks kept out of the annotation sheet.
"""
import json
import re
import sys
import unittest
from pathlib import Path

from build_v7_annotation_pilot import OUT, ROOT, SHEET_EXPORT, TASK_IDS, TASKS, platform_verifiers

sys.path.insert(0, str(ROOT / 'tools/pilot13_ab_fixes'))
from validate_patch import validate  # noqa: E402


class AbFixTests(unittest.TestCase):
    def test_rules_and_full_coverage(self):
        for tid in TASK_IDS:
            with self.subTest(task=tid):
                coverage = json.loads((OUT / 'coverage' / f'{tid}.json').read_text())
                current = json.loads((TASKS / tid / 'TASK_SPEC.json').read_text())
                errors, _, summary = validate(tid, {'task_id': tid}, coverage, current)
                self.assertEqual(errors, [])
                self.assertGreater(summary['rules'], 0)
                self.assertTrue((OUT / 'coverage' / f'{tid}.html').is_file())
        self.assertTrue((OUT / 'coverage' / 'index.html').is_file())

    def test_machine_facts_are_automatic(self):
        for tid in TASK_IDS:
            spec = json.loads((TASKS / tid / 'TASK_SPEC.json').read_text())
            ops = {(c['output_id'], c['assertion']['op']) for c in spec['verifiers_auto']}
            for o in spec['deliverables']:
                fmt = o['spec']['format']
                if fmt in ('png', 'jpg', 'jpeg'):
                    self.assertIn((o['output_id'], 'icc_profile'), ops)
                if fmt == 'pdf':
                    self.assertIn((o['output_id'], 'pdf_fonts_embedded'), ops)
            for c in spec['verifiers_human']:
                self.assertNotRegex(c['check'], r'(?i)\bsRGB\b|colou?r profile|embedded font|output intent')

    def test_annotation_sheet_carries_every_human_check_once(self):
        rows = json.loads(SHEET_EXPORT.read_text())
        header, body = rows[0], rows[1:]
        kind, task_col = header.index('row_type'), header.index('task')
        for tid in TASK_IDS:
            spec = json.loads((TASKS / tid / 'TASK_SPEC.json').read_text())
            human = {c['check'] for c in spec['verifiers_human']}
            auto = {c['check'] for c in spec['verifiers_auto']}
            seen = []
            for r in body:
                if r[kind] == 'deliverable_verifiers' and r[task_col] == tid:
                    for item in json.loads(r[2]):
                        text = re.sub(r'^\d+\. \[(?:Look|(?:Measure|Estimate): [^\]]*)\] ', '', item['verifier_question'])
                        self.assertNotIn(text, auto)
                        seen.append(text)
            self.assertEqual(sorted(seen), sorted(c['check'] for c in spec['verifiers_human']))
            for c in spec['verifiers_human']:
                self.assertIn(c.get('method'), ('look', 'measure', 'estimate'), c['check_id'])
                self.assertTrue(c.get('method_note'), c['check_id'])
                if re.search(r'#[0-9A-Fa-f]{6}',c['check']) and 'shifted toward' not in c['check']:
                    self.assertNotEqual(c['method'],'look',c['check_id'])

    def test_colour_measurements_state_a_tolerance(self):
        for tid in TASK_IDS:
            spec = json.loads((TASKS / tid / 'TASK_SPEC.json').read_text())
            for c in spec['verifiers_human']:
                if c['method'] == 'measure' and re.search(r'#[0-9A-Fa-f]{6}', c['check']):
                    self.assertRegex(c['method_note'], r'(?i)within \d+|exactly|must be #|\bnearer\b|HSB brightness', c['check_id'])
                    self.assertNotRegex(c['method_note'], r'clearly differs|clearly matches|very near|1-unit', c['check_id'])

    def test_typography_prose_matches_current_scale(self):
        spec=json.loads((TASKS/'LAYOUT-12'/'TASK_SPEC.json').read_text())
        prose=spec['brand_identity']['typography']
        self.assertIn('remaining act names are 48 pt', prose)
        self.assertIn('choose their larger size', prose)
        self.assertIn('18 pt / 22 pt', prose)
        self.assertIn('14 pt / 19 pt', prose)
        self.assertIn('other fine print is Regular', prose)
        self.assertNotIn('exactly two lines', prose)
        self.assertNotIn('46 pt', prose)

    def test_method_rendering_is_visible_in_main_page(self):
        page=(ROOT/'docs/gatsby-v7/index.html').read_text()
        self.assertIn('conditionHTML(c)+checkingMethod(c)', page)
        self.assertIn('esc(c.method_note', page)

    def test_new_human_checks_receive_a_method(self):
        from apply_patch import apply
        spec=json.loads((TASKS/'PHOTO-04'/'TASK_SPEC.json').read_text())
        output=spec['deliverables'][0]
        result,_=apply(spec,{'task_id':'PHOTO-04','add':[{
            'key':'test','output_id':output['output_id'],'type':'human','k_id':'K1_Q1',
            'check':'A test requirement.', 'why':'Regression fixture.'
        }]})
        self.assertEqual(result['verifiers_human'][-1]['method'],'look')
        self.assertTrue(result['verifiers_human'][-1]['method_note'])

    def test_photo10_mark_rebuilt(self):
        spec = json.loads((TASKS / 'PHOTO-10' / 'TASK_SPEC.json').read_text())
        marks = {a['filename']: a for a in spec['assets'] if a['filename'].startswith('northgrove_mark_')}
        self.assertEqual(len(marks), 4)
        for name, a in marks.items():
            self.assertEqual(a.get('revision'), 'pilot13_ab_2026_10_21', name)
        self.assertIn('Olive #6B7248', marks['northgrove_mark_transparent.svg']['description'])

    def test_single_export_line(self):
        for tid in TASK_IDS:
            html = (OUT / f'{tid}.html').read_text()
            spec = json.loads((TASKS / tid / 'TASK_SPEC.json').read_text())
            self.assertEqual(html.count('<strong>Export:</strong>'), len(spec['deliverables']))


if __name__ == '__main__':
    unittest.main()
