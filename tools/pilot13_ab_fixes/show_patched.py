#!/usr/bin/env python3
"""Print a task's checks after its patch, grouped by output, plus the coverage table.

Usage: python3 show_patched.py PHOTO-19 [--retired] [--coverage]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_patch import WORK, apply, load_spec, resolve_coverage  # noqa: E402


def main(argv):
    tid = argv[0]
    patch = json.loads((WORK / 'patches' / f'{tid}.json').read_text())
    spec0 = load_spec(tid)
    spec, key_to_id = apply(spec0, patch)
    new_ids = set(key_to_id.values())
    modified = {m['check_id'] for m in patch.get('modify', [])}
    for o in spec['deliverables']:
        oid = o['output_id']
        print(f'\n## {oid}  ({o["name"]}, {Path(o["path"]).name})')
        for c in spec['verifiers_auto'] + spec['verifiers_human']:
            if c['output_id'] != oid:
                continue
            tag = 'NEW' if c['check_id'] in new_ids else 'MOD' if c['check_id'] in modified else '   '
            extra = f' {json.dumps(c["assertion"])}' if c['type'] == 'auto' else f' [{c.get("k_id")}]'
            print(f'{tag} {c["check_id"].split("/")[-1]:>5} {c["type"][:4]}{extra} {c["check"]}')
    if '--retired' in argv:
        print('\n## Retired')
        for r in patch.get('retire', []):
            old = next(c for c in spec0['verifiers_human'] if c['check_id'] == r['check_id'])
            print(f'- {r["check_id"]} -> {r.get("covered_by")} | {r["why"]} | WAS: {old["check"]}')
    if '--coverage' in argv:
        cov = resolve_coverage(json.loads((WORK / 'coverage' / f'{tid}.json').read_text()), key_to_id)
        print('\n## Coverage')
        for rule in cov['rules']:
            print(f'\n{rule["rule_id"]} [{rule["kind"]}] {rule["rule"]}  (source: {rule["source"]})')
            for oid, cell in rule['cells'].items():
                if 'checks' in cell:
                    print(f'   {oid}: ' + ', '.join(x.split('/')[-1] for x in cell['checks']))
                elif 'not_verified' in cell:
                    print(f'   {oid}: NOT VERIFIED: ' + cell['not_verified'])
                else:
                    print(f'   {oid}: NA: ' + cell.get('na', ''))


if __name__ == '__main__':
    main(sys.argv[1:])
