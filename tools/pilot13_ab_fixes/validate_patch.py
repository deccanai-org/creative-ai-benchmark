#!/usr/bin/env python3
"""Validate one task's verifier patch + coverage table against the 2026-10-21 rules.

Usage: python3 validate_patch.py PHOTO-04 [--patch P] [--coverage C] [--quiet]
Exit 1 when any ERROR is found. Warnings are for reviewers.
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_patch import WORK, K_LABELS, PatchError, apply, load_spec, resolve_coverage  # noqa: E402

RASTER = {'png', 'jpg', 'jpeg', 'mp4', 'mov', 'webp', 'gif'}
SOURCES = WORK.parent / 'pilot13-refresh-2026-10-14'
CROSS = re.compile(r"\b(?:the\s+)?other\s+(?:\w+\s){0,3}?(?:speaker cards|cards|posts|pages|outputs|files|images|thumbnails|modules|slides|heroes|stills|frames|masters|share images|announcements|banners|directions|plates|clips|teasers|stickers|proofs)\b"
                   r"|delivery contains|delivered (?:together|alongside)|as separate files|\bsibling"
                   r"|\bthe (?:rest|remaining) (?:of the )?(?:\w+\s)?(?:cards|posts|outputs|files|images|thumbnails|modules|slides|heroes|stills|masters|announcements|banners|directions|plates|clips|teasers|stickers|proofs)\b", re.I)
MACHINE = re.compile(r"\bsRGB\b|colou?r profile|\bICC\b|embedded font|unembedded|output intent", re.I)
TYPE_MEASURE = re.compile(r"\bleading\b|\btracking\b|/1000|\bfont size\b|\b\d+(?:\.\d+)?\s?pt\b|\b(?:set at|set in \w+(?: \w+)? at|is|are|at)\s\d+(?:\.\d+)?\s?px\b|optical[- ]size", re.I)
PX = re.compile(r"\b\d+(?:\.\d+)?\s?px\b", re.I)
DASH = re.compile('[–—]')


def norm(text):
    return re.sub(r'\W+', ' ', text.lower()).strip()


def source_text(spec):
    blob = json.dumps(spec, ensure_ascii=False)
    for folder in (SOURCES / 'sources' / spec['new_id'], SOURCES / 'upload' / spec['new_id']):
        if folder.is_dir():
            for f in folder.rglob('*'):
                if f.suffix.lower() in ('.txt', '.csv', '.md', '.json'):
                    blob += '\n' + f.read_text(errors='ignore')
    return re.sub(r'\s+', ' ', blob)


def validate(tid, patch, coverage, spec0=None):
    """spec0: the spec to validate against (default: the frozen base the patch applies to)."""
    errors, warnings = [], []
    spec0 = spec0 if spec0 is not None else load_spec(tid)
    try:
        spec, key_to_id = apply(spec0, patch)
    except PatchError as e:
        return [f'PATCH: {e}'], [], {}
    outputs = {o['output_id']: o for o in spec['deliverables']}
    live = {c['check_id']: c for c in spec['verifiers_auto'] + spec['verifiers_human']}
    for item in patch.get('retire', []) + patch.get('modify', []) + patch.get('add', []):
        if not str(item.get('why', '')).strip():
            errors.append(f'{item.get("check_id") or item.get("key")}: missing "why"')
    seen = defaultdict(dict)
    for c in spec['verifiers_human']:
        cid, text, o = c['check_id'], c['check'], outputs[c['output_id']]
        fmt = o['spec'].get('format', '').lower()
        filename = Path(o['path']).name
        words = len(text.split())
        if words > 40: errors.append(f'{cid}: {words} words (max 40)')
        elif words > 30: warnings.append(f'{cid}: {words} words; aim for 25 or fewer')
        if DASH.search(text): errors.append(f'{cid}: contains an em or en dash')
        if filename not in text: errors.append(f'{cid}: does not name its output file {filename}')
        if '(when present)' in text.lower() or 'when present' in text.lower(): errors.append(f'{cid}: uses "when present"; state the requirement or write "If ... appears on ..."')
        if c.get('k_id') not in K_LABELS: errors.append(f'{cid}: invalid k_id {c.get("k_id")}')
        if CROSS.search(text): errors.append(f'{cid}: compares with other outputs or judges delivery of several files: "{CROSS.search(text).group(0)}"')
        if MACHINE.search(text): errors.append(f'{cid}: machine fact asked of a human ("{MACHINE.search(text).group(0)}"); these are auto checks now')
        if re.search(r'\bCMYK\b', text): warnings.append(f'{cid}: mentions CMYK; confirm a person can judge it by eye')
        if fmt in RASTER:
            stripped = re.sub(r'^Displayed \d+ px wide,?\s*', '', text)
            m = TYPE_MEASURE.search(stripped)
            if m: errors.append(f'{cid}: exact type measurement on a raster output ("{m.group(0)}"); use a visible relative check or drop it')
            elif PX.search(stripped): warnings.append(f'{cid}: pixel value on a raster output ("{PX.search(stripped).group(0)}"); confirm it can be judged by eye')
        n = norm(text)
        if n in seen[c['output_id']]: errors.append(f'{cid}: duplicates {seen[c["output_id"]][n]}')
        seen[c['output_id']][n] = cid
    blob = None
    for item in patch.get('add', []):
        if item.get('type') == 'auto':
            a = item.get('assertion', {})
            o = outputs.get(item.get('output_id'), {})
            if a.get('op') != 'pdf_text_style':
                errors.append(f'add {item["key"]}: only pdf_text_style may be added as an auto check')
                continue
            if o.get('spec', {}).get('format') != 'pdf':
                errors.append(f'add {item["key"]}: pdf_text_style on a non-PDF output')
            if not a.get('text') or not a.get('family'):
                errors.append(f'add {item["key"]}: pdf_text_style needs text and family')
                continue
            blob = blob or source_text(spec0)
            if re.sub(r'\s+', ' ', a['text']).strip() not in blob:
                errors.append(f'add {item["key"]}: text "{a["text"]}" is not found in the task brief, records or supplied text files')
            if Path(o.get('path', 'x')).name not in item.get('check', ''):
                errors.append(f'add {item["key"]}: auto check text must name {Path(o.get("path", "x")).name}')
    # Coverage table.
    if not coverage or not coverage.get('rules'):
        errors.append('COVERAGE: missing or empty')
        return errors, warnings, {}
    cov = resolve_coverage(coverage, key_to_id)
    ids = set(outputs)
    rule_ids = Counter(r.get('rule_id') for r in cov['rules'])
    for rid, n in rule_ids.items():
        if not rid or n > 1: errors.append(f'COVERAGE: rule_id {rid!r} missing or repeated')
    for r in cov['rules']:
        rid = r.get('rule_id')
        if r.get('kind') not in ('brand', 'brief', 'type', 'deliverable'):
            errors.append(f'COVERAGE {rid}: kind must be brand, brief, type or deliverable')
        if not r.get('rule') or not r.get('source'):
            errors.append(f'COVERAGE {rid}: needs rule text and source')
        cells = r.get('cells', {})
        if set(cells) != ids:
            errors.append(f'COVERAGE {rid}: cells must list every output exactly once (missing {sorted(ids - set(cells))[:4]}, unknown {sorted(set(cells) - ids)[:4]})')
        for oid, cell in cells.items():
            if 'checks' in cell:
                if not cell['checks']:
                    errors.append(f'COVERAGE {rid}/{oid}: empty checks list')
                for cid in cell['checks']:
                    if cid not in live:
                        errors.append(f'COVERAGE {rid}/{oid}: {cid} does not exist after the patch')
                    elif live[cid]['output_id'] != oid:
                        errors.append(f'COVERAGE {rid}/{oid}: {cid} belongs to {live[cid]["output_id"]}')
            elif len(str(cell.get('na', '')).split()) < 6:
                errors.append(f'COVERAGE {rid}/{oid}: needs checks or an "na" reason of at least six words')
    bullets = {(oid, b) for oid, o in outputs.items() for b in o.get('commission', {}).get('content', [])}
    deliverable_rules = defaultdict(dict)
    for r in cov['rules']:
        if r.get('kind') == 'deliverable':
            deliverable_rules[r['rule']].update(r.get('cells', {}))
    for oid, b in sorted(bullets):
        cell = deliverable_rules.get(b, {}).get(oid)
        if not cell or not cell.get('checks'):
            errors.append(f'COVERAGE: deliverable requirement for {oid} has no checks: "{b[:80]}"')
    scale = spec['brand_identity']['type_system'].get('scale', [])
    type_rules = sum(1 for r in cov['rules'] if r.get('kind') == 'type')
    if type_rules < len([s for s in scale if 'not used' not in s.get('role', '').lower()]):
        warnings.append(f'COVERAGE: {type_rules} type rules for {len(scale)} type-scale roles')
    for word in ('opacity', 'forbidden', 'distribution'):
        if not any(word in r.get('source', '').lower() for r in cov['rules']):
            warnings.append(f'COVERAGE: no rule sourced from palette_rules.{word}')
    summary = {'human_before': len(spec0['verifiers_human']), 'human_after': len(spec['verifiers_human']),
               'auto_before': len(spec0['verifiers_auto']), 'auto_after': len(spec['verifiers_auto']),
               'rules': len(cov['rules']), 'cells': sum(len(r['cells']) for r in cov['rules']),
               'na_cells': sum(1 for r in cov['rules'] for c in r['cells'].values() if 'na' in c)}
    return errors, warnings, summary


def main(argv):
    tid = argv[0]
    opt = dict(zip(argv[1::2], argv[2::2])) if len(argv) > 1 and argv[1].startswith('--') and argv[1] != '--quiet' else {}
    patch_path = Path(opt.get('--patch', WORK / 'patches' / f'{tid}.json'))
    cov_path = Path(opt.get('--coverage', WORK / 'coverage' / f'{tid}.json'))
    patch = json.loads(patch_path.read_text())
    coverage = json.loads(cov_path.read_text()) if cov_path.exists() else None
    errors, warnings, summary = validate(tid, patch, coverage)
    quiet = '--quiet' in argv
    print(json.dumps({'task': tid, 'errors': len(errors), 'warnings': len(warnings), **summary}))
    for e in errors[: (40 if quiet else 400)]:
        print('ERROR', e)
    if not quiet:
        for w in warnings[:200]:
            print('WARN ', w)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
