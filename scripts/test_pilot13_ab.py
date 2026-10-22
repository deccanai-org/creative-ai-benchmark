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
                        text = re.sub(r'^\d+\. (?:\[(?:Measure|Estimate): [^\]]*\] )?', '', item['verifier_question'])
                        self.assertNotIn(text, auto)
                        seen.append(text)
            self.assertEqual(sorted(seen), sorted(c['check'] for c in spec['verifiers_human']))
            for c in spec['verifiers_human']:
                if c.get('method') in ('measure', 'estimate'):
                    self.assertTrue(c.get('method_note'))

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
