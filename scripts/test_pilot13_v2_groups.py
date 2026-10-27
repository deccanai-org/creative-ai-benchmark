#!/usr/bin/env python3
"""Regression checks for annotation-pilot-v2 (grouped human verifiers, 2026-10-27).

Grouping must lose nothing: every human check appears in exactly one rule row, every row rebuilds its check and
method note word for word, and checks only share a rule when method, scoring dimension and answer match.
"""
import csv
import html
import json
import re
import unittest
from collections import Counter

from build_v7_annotation_pilot import ROOT, TASK_IDS, TASKS
from build_v7_annotation_pilot_v2 import AUTO2K, CONDITIONAL, OUT, build_rules, export_rule, fill, k_catalog

LOGIC = re.compile(r'(?i)\b(if|any|no|not|never|only|unless|except|without|all|every|each|none|neither|nor)\b')


def load(task_id):
    spec = json.loads((TASKS / task_id / 'TASK_SPEC.json').read_text(encoding='utf-8'))
    groups = json.loads((OUT / 'groups' / f'{task_id}.json').read_text(encoding='utf-8'))
    return spec, groups


class GroupedVerifierTests(unittest.TestCase):
    def test_every_check_appears_once_and_rebuilds_exactly(self):
        for tid in TASK_IDS:
            spec, groups = load(tid)
            checks = {c['check_id']: c for c in spec['verifiers_human']}
            seen = Counter(row['check_id'] for rule in groups['rules'] for row in rule['rows'])
            with self.subTest(task=tid):
                self.assertEqual(set(seen), set(checks))
                self.assertEqual(max(seen.values()), 1)
                self.assertEqual(groups['check_count'], len(checks))
                for rule in groups['rules']:
                    for row in rule['rows']:
                        check = checks[row['check_id']]
                        self.assertEqual(fill(rule['template'], row['values'], row['deliverable_ref']), check['check'])
                        self.assertEqual(fill(rule['note_template'], row['values'], row['deliverable_ref']), check['method_note'])
                        self.assertEqual(row['check'], check['check'])
                        self.assertEqual(row['output_id'], check['output_id'])

    def test_rules_share_method_dimension_and_answer(self):
        for tid in TASK_IDS:
            spec, groups = load(tid)
            checks = {c['check_id']: c for c in spec['verifiers_human']}
            for rule in groups['rules']:
                members = [checks[row['check_id']] for row in rule['rows']]
                with self.subTest(task=tid, rule=rule['rule_id']):
                    for field in ('method', 'k_id', 'answer_type', 'pass_answer'):
                        self.assertEqual(len({m[field] for m in members}), 1, field)
                    self.assertEqual(len({tuple(m['allowed_answers']) for m in members}), 1)
                    self.assertEqual(rule['method'], members[0]['method'])
                    self.assertEqual(rule['k_id'], members[0]['k_id'])
                    self.assertEqual(rule['critical'], members[0]['k_id'] == 'K1_Q5')

    def test_values_never_carry_conditions_or_negations(self):
        for tid in TASK_IDS:
            _, groups = load(tid)
            for rule in groups['rules']:
                for row in rule['rows']:
                    for value in row['values'].values():
                        if not value.startswith('“'):
                            self.assertNotRegex(value, LOGIC, f"{tid} {rule['rule_id']}")
                    text = fill(rule['template'], row['values'], 'X')
                    self.assertEqual(bool(CONDITIONAL.match(text)), rule['only_if_present'], f"{tid} {rule['rule_id']}")

    def test_published_rules_match_current_specs(self):
        for tid in TASK_IDS:
            spec, groups = load(tid)
            with self.subTest(task=tid):
                self.assertEqual(json.loads(json.dumps([export_rule(tid, r) for r in build_rules(spec)])), groups['rules'])

    def test_pages_and_exports_list_every_check_once(self):
        with (OUT / 'export' / 'grouped_human_rule_rows.csv').open(encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        with (OUT / 'export' / 'grouped_human_rules.csv').open(encoding='utf-8') as f:
            rules = list(csv.DictReader(f))
        for tid in TASK_IDS:
            spec, groups = load(tid)
            ids = {c['check_id'] for c in spec['verifiers_human']}
            page = (OUT / f'{tid}-verifiers.html').read_text(encoding='utf-8')
            with self.subTest(task=tid):
                on_page = Counter(re.findall(r'data-check="([^"]+)"', page))
                self.assertEqual(set(on_page), ids)
                self.assertEqual(max(on_page.values()), 1)
                exported = Counter(r['check_id'] for r in rows if r['task_id'] == tid)
                self.assertEqual(set(exported), ids)
                self.assertEqual(max(exported.values()), 1)
                listed = Counter(i for r in rules if r['task_id'] == tid for i in r['check_ids'].split())
                self.assertEqual(set(listed), ids)
                self.assertEqual(max(listed.values()), 1)
                self.assertEqual(sum(1 for r in rules if r['task_id'] == tid), groups['rule_count'])

    def test_pages_keep_the_v7_k_structure(self):
        v7 = (ROOT / 'docs/gatsby-v7/index.html').read_text(encoding='utf-8')
        mapping = re.search(r'const AUTO2K=(\{[^}]*\})', v7).group(1)
        self.assertEqual(dict(re.findall(r"(\w+):'(K\d_Q\d)'", mapping)), AUTO2K)
        catalog = k_catalog()
        for tid in TASK_IDS:
            _, groups = load(tid)
            page = (OUT / f'{tid}-verifiers.html').read_text(encoding='utf-8')
            with self.subTest(task=tid):
                for cap in catalog:
                    self.assertIn(f'<h2>{html.escape(cap["id"])} · {html.escape(cap["name"])}</h2>', page)
                starts = {q['id']: page.index(f'<div class="kq" id="{q["id"]}">') for cap in catalog for q in cap['questions']}
                ordered = sorted(starts.values())
                for rule in groups['rules']:
                    at = page.index(f'<article class="rule" id="{rule["rule_id"]}">')
                    start = starts[rule['k_id']]
                    end = min([v for v in ordered if v > start], default=len(page))
                    self.assertTrue(start < at < end, f"{rule['rule_id']} is not under {rule['k_id']}")

    def test_no_long_dashes(self):
        # Brief pages reproduce v1, including excerpts of client-supplied files, so only generated pages are checked.
        for path in [*OUT.glob('*-verifiers.html'), OUT / 'index.html', *(OUT / 'export').glob('*.csv')]:
            self.assertNotRegex(path.read_text(encoding='utf-8'), '[–—]', path.name)


if __name__ == '__main__':
    unittest.main()
