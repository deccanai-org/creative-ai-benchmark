#!/usr/bin/env python3
"""Apply a per-task verifier patch (2026-10-21 pilot-13 A+B fixes) to TASK_SPEC.json.

Library use (validator, agents):   from apply_patch import load_spec, apply
CLI (final write, orchestrator):   python3 apply_patch.py --write PHOTO-04 [...]   (default: dry run)

Patch schema (JSON):
{
  "task_id": "PHOTO-04",
  "retire": [{"check_id": "...", "why": "...", "covered_by": ["<check_id>" | "new:<key>", ...]}],
  "modify": [{"check_id": "...", "check": "<new text>", "k_id": "K2_Q3"?, "evidence_reference": "..."?,
              "reference_assets": ["<asset filename>", ...]?, "why": "..."}],
  "add":    [{"key": "<unique key>", "output_id": "...", "type": "human" | "auto", "check": "<text>",
              "k_id": "K2_Q3" (human only), "assertion": {"op": "pdf_text_style", ...} (auto only),
              "evidence_reference": "...", "reference_assets": ["<asset filename>", ...], "why": "..."}]
}
New ids continue each output's H### / A### numbering after the highest id ever used for that output.
"""
import copy
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / 'docs/gatsby-v7/tasks'
# Round 1 (A+B, 2026-10-21) used reviews/pilot13-ab-fixes-2026-10-21; round 2 (2026-10-22) sets PILOT_FIX_WORK.
WORK = Path(os.environ.get('PILOT_FIX_WORK', ROOT.parents[1] / 'reviews/pilot13-ab-fixes-2026-10-21'))
REV = os.environ.get('PILOT_FIX_REV', 'pilot13_ab_2026_10_21')
METHODS = ('look', 'measure', 'estimate')
K_LABELS = {
    'K1_Q1': 'Content completeness', 'K1_Q2': 'Specification accuracy', 'K1_Q3': 'Constraint compliance',
    'K1_Q4': 'Deliverable completeness', 'K1_Q5': 'Critical failure check', 'K2_Q1': 'Asset selection',
    'K2_Q2': 'Asset preservation', 'K2_Q3': 'Brand-system compliance', 'K2_Q4': 'Identity fidelity',
    'K5_Q1': 'Primary-message recovery', 'K5_Q2': 'Information hierarchy',
}
TEXT_FIELDS = ('check', 'source_statement', 'requirement', 'pass_condition')


class PatchError(ValueError):
    pass


def base_path(task_id):
    """Patches always apply to the frozen post-pre-edit base, so the final write can be re-run."""
    base = WORK / 'base' / task_id / 'TASK_SPEC.json'
    return base if base.is_file() else TASKS / task_id / 'TASK_SPEC.json'


def load_spec(task_id):
    return json.loads(base_path(task_id).read_text())


def _refs(spec, filenames):
    urls = {a['filename']: a['public_url'] for a in spec['assets']}
    missing = [f for f in filenames if f not in urls]
    if missing:
        raise PatchError(f'unknown reference asset(s): {missing}')
    return [{'filename': f, 'url': urls[f]} for f in filenames]


def _next_number(spec, output_id, letter):
    used = [int(m.group(1)) for c in spec['verifiers_auto'] + spec['verifiers_human']
            if c['output_id'] == output_id for m in [re.search(rf'/{letter}(\d+)$', c['check_id'])] if m]
    return max(used or [0]) + 1


def _set_method(c, item):
    """look = judge by eye; measure = needs a ruler or tool (say what); estimate = an approximate visual estimate."""
    if 'method' not in item:
        return
    if item['method'] not in METHODS:
        raise PatchError(f'{c.get("check_id")}: method must be one of {METHODS}')
    c['method'] = item['method']
    if item['method'] == 'look':
        c.pop('method_note', None)
    else:
        note = str(item.get('how', '')).strip()
        if not note:
            raise PatchError(f'{c.get("check_id")}: method {item["method"]} needs "how"')
        c['method_note'] = note


def apply(spec, patch):
    """Return (new_spec, key_to_id). Raises PatchError on structural problems."""
    spec = copy.deepcopy(spec)
    tid = spec['new_id']
    if patch.get('task_id') != tid:
        raise PatchError(f'patch task_id {patch.get("task_id")} != {tid}')
    outputs = {o['output_id']: o for o in spec['deliverables']}
    by_id = {c['check_id']: c for c in spec['verifiers_auto'] + spec['verifiers_human']}
    touched = {}
    for op in ('retire', 'modify'):
        for item in patch.get(op, []):
            cid = item.get('check_id')
            if cid not in by_id:
                raise PatchError(f'{op}: unknown check_id {cid}')
            if cid in touched:
                raise PatchError(f'{cid} appears in both {touched[cid]} and {op}')
            if by_id[cid]['type'] == 'auto':
                raise PatchError(f'{op}: {cid} is an auto check; auto checks are not edited by this patch')
            touched[cid] = op
    counters = {}
    key_to_id = {}
    new_checks = []
    for item in patch.get('add', []):
        key, oid, kind = item.get('key'), item.get('output_id'), item.get('type')
        if not key or key in key_to_id:
            raise PatchError(f'add: missing or duplicate key {key!r}')
        if oid not in outputs:
            raise PatchError(f'add {key}: unknown output_id {oid}')
        if kind not in ('human', 'auto'):
            raise PatchError(f'add {key}: type must be human or auto')
        letter = 'H' if kind == 'human' else 'A'
        counters.setdefault((oid, letter), _next_number(spec, oid, letter))
        number = counters[(oid, letter)]
        counters[(oid, letter)] += 1
        o = outputs[oid]
        text = item['check'].strip()
        c = {'task_id': tid, 'output_id': oid, 'check_id': f'{tid}/{oid}/{letter}{number:03}', 'type': kind,
             'output_reference': o['path'], 'check': text, 'answer_type': 'yes_no', 'allowed_answers': ['Yes', 'No'],
             'pass_answer': 'Yes', 'answer': None, 'status': 'not_assessed', 'source_statement': text,
             'evidence_reference': item.get('evidence_reference') or ('Automatic check.' if kind == 'auto' else 'Current brief, brand identity and supplied assets.'),
             'artifact_name': o['name'], 'artifact_file': Path(o['path']).name, 'requirement': text, 'pass_condition': text,
             'reference_assets': _refs(spec, item.get('reference_assets', [])), 'revision': REV, 'origin': REV}
        if kind == 'human':
            k = item.get('k_id')
            if k not in K_LABELS:
                raise PatchError(f'add {key}: invalid k_id {k!r}')
            c.update(k_id=k, k_label=K_LABELS[k])
            _set_method(c, item)
        else:
            if not isinstance(item.get('assertion'), dict) or 'op' not in item['assertion']:
                raise PatchError(f'add {key}: auto check needs an assertion with op')
            c['assertion'] = item['assertion']
        key_to_id[key] = c['check_id']
        new_checks.append(c)

    def resolve(ref):
        if isinstance(ref, str) and ref.startswith('new:'):
            if ref[4:] not in key_to_id:
                raise PatchError(f'unknown new key reference {ref}')
            return key_to_id[ref[4:]]
        return ref

    retired = {}
    for item in patch.get('retire', []):
        retired[item['check_id']] = [resolve(r) for r in item.get('covered_by', [])]
    for item in patch.get('modify', []):
        c = by_id[item['check_id']]
        if 'check' in item:
            text = item['check'].strip()
            for f in TEXT_FIELDS:
                c[f] = text
        _set_method(c, item)
        if 'k_id' in item:
            if item['k_id'] not in K_LABELS:
                raise PatchError(f'modify {c["check_id"]}: invalid k_id')
            c.update(k_id=item['k_id'], k_label=K_LABELS[item['k_id']])
        if item.get('evidence_reference'):
            c['evidence_reference'] = item['evidence_reference']
        if 'reference_assets' in item:
            c['reference_assets'] = _refs(spec, item['reference_assets'])
        c.pop('typography_key', None)
        c.update(revision=REV, status='not_assessed', answer=None)
    spec['verifiers_human'] = [c for c in spec['verifiers_human'] if c['check_id'] not in retired]
    for c in spec['verifiers_human']:
        c.setdefault('method', 'look')
    spec['verifiers_human'] += [c for c in new_checks if c['type'] == 'human']
    spec['verifiers_auto'] += [c for c in new_checks if c['type'] == 'auto']
    live = {c['check_id']: c for c in spec['verifiers_auto'] + spec['verifiers_human']}
    for cid, targets in retired.items():
        if by_id[cid].get('platform_priority'):
            for t in targets:
                if t in live and live[t]['type'] == 'human':
                    live[t]['platform_priority'] = True
    for cid, targets in retired.items():
        for t in targets:
            if t not in live:
                raise PatchError(f'retire {cid}: covered_by {t} does not exist after the patch')
    return spec, key_to_id


def resolve_coverage(coverage, key_to_id):
    coverage = copy.deepcopy(coverage)
    for rule in coverage.get('rules', []):
        for cell in rule.get('cells', {}).values():
            if 'checks' in cell:
                cell['checks'] = [key_to_id.get(c[4:], c) if c.startswith('new:') else c for c in cell['checks']]
    return coverage


def main(argv):
    write = '--write' in argv
    ids = [a for a in argv if not a.startswith('--')]
    for tid in ids:
        patch = json.loads((WORK / 'patches' / f'{tid}.json').read_text())
        original_text = base_path(tid).read_text()
        spec, key_to_id = apply(json.loads(original_text), patch)
        coverage = resolve_coverage(json.loads((WORK / 'coverage' / f'{tid}.json').read_text()), key_to_id)
        print(tid, 'human', len(spec['verifiers_human']), 'auto', len(spec['verifiers_auto']), 'new ids', len(key_to_id))
        if write:
            (TASKS / tid / 'TASK_SPEC.json').write_text(json.dumps(spec, ensure_ascii=False, indent=1) + ('\n' if original_text.endswith('\n') else ''))
            out = ROOT / 'docs/gatsby-v7/annotation-pilot/coverage'
            out.mkdir(parents=True, exist_ok=True)
            (out / f'{tid}.json').write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + '\n')
            (WORK / 'applied').mkdir(exist_ok=True)
            (WORK / 'applied' / f'{tid}.idmap.json').write_text(json.dumps(key_to_id, indent=2) + '\n')


if __name__ == '__main__':
    main(sys.argv[1:])
