#!/usr/bin/env python3
"""Deterministic part of the 2026-10-21 pilot-13 fixes (items A1, A3, A4 and B5).

Edits docs/gatsby-v7/tasks/<ID>/TASK_SPEC.json (canonical) and, for PHOTO-10, ASSET_MANIFEST.json.
Mirrors are regenerated afterwards by scripts/sync_v7_pilot_content.py and
scripts/build_v7_annotation_pilot.py. Idempotent: running it twice changes nothing more.

  A1  PHOTO-10: record the rebuilt Northgrove mark files (bytes, sha256, description).
  A3  Retire the three checks that judged delivery of every file from one output.
  A4  Remove the obsolete "If a named font is unavailable, ask us..." sentence (fonts are now supplied).
  B5  Move machine facts from human to auto: sRGB colour, embedded fonts, PDF output intent / no CMYK.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / 'docs/gatsby-v7/tasks'
REV = 'pilot13_ab_2026_10_21'
IDS = ['PHOTO-04', 'PHOTO-06', 'PHOTO-08', 'PHOTO-10', 'PHOTO-19', 'PHOTO-20', 'PHOTO-24',
       'PHOTO-26', 'PHOTO-28', 'LAYOUT-15', 'LAYOUT-12', 'VECTOR-04', 'MOTION-11']
RETIRE = {
    'LAYOUT-12/release-post-r002/H009': 'Judged delivery of all nine posts from one post; auto file_exists checks cover every file.',
    'LAYOUT-12/poster-direction-type-led/H003': 'Judged delivery of all three directions from one file; auto file_exists checks cover every file.',
    'MOTION-11/thumbnail-we-broke-the-map/H004': 'Judged delivery of all six thumbnails from one thumbnail; auto file_exists checks cover every file.',
}
ASK_US = ' If a named font is unavailable, ask us before substituting it.'
LOGO_DIR = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parents[1] / 'reviews/pilot13-ab-fixes-2026-10-21/logo'
LOGO_TEXT = {
    'northgrove_mark_transparent.svg': 'Transparent vector master: olive leaf (Olive #6B7248) and NORTHGROVE wordmark (Charcoal #2E2E2C).',
    'northgrove_mark_transparent.png': '1600 px transparent raster companion of the vector master.',
    'northgrove_mark_reversed.svg': 'Off White #F5F2EC vector variant of the full mark, leaf included, for Club Navy grounds.',
    'northgrove_mark_reversed.png': '1600 px transparent Off White raster variant.',
}


def auto_check(spec, output, text, assertion, evidence):
    oid = output['output_id']
    used = [int(m.group(1)) for c in spec['verifiers_auto'] if c['output_id'] == oid for m in [re.search(r'/A(\d+)$', c['check_id'])] if m]
    number = max(used or [0]) + 1
    filename = Path(output['path']).name
    sentence = f'“{output["name"]}” ({filename}) {text}'
    return {'task_id': spec['new_id'], 'output_id': oid, 'check_id': f'{spec["new_id"]}/{oid}/A{number:03}', 'type': 'auto',
            'output_reference': output['path'], 'check': sentence, 'answer_type': 'yes_no', 'allowed_answers': ['Yes', 'No'],
            'pass_answer': 'Yes', 'answer': None, 'status': 'not_assessed', 'source_statement': sentence, 'assertion': assertion,
            'evidence_reference': evidence, 'artifact_name': output['name'], 'artifact_file': filename,
            'requirement': sentence, 'pass_condition': sentence, 'reference_assets': [], 'revision': REV, 'origin': REV}


def convert_machine_facts(spec):
    outputs = {o['output_id']: o for o in spec['deliverables']}
    kept = []
    for c in spec['verifiers_human']:
        m = re.search(r'/R13-(colour-profile|pdf-profile|pdf-fonts)$', c['check_id'])
        if not m:
            kept.append(c)
            continue
        o = outputs[c['output_id']]
        kind = m.group(1)
        if kind == 'colour-profile':
            new = auto_check(spec, o, 'is in sRGB colour: it carries an sRGB profile or no colour profile.',
                             {'op': 'icc_profile', 'expects': 'sRGB'}, 'Automatic check: embedded ICC profile or PNG sRGB chunk; untagged files count as sRGB.')
        elif kind == 'pdf-fonts':
            new = auto_check(spec, o, 'embeds every font it uses.', {'op': 'pdf_fonts_embedded'},
                             'Automatic check: every font resource carries an embedded font file; outlined lettering uses no fonts.')
        elif 'PSO Coated v3' in c['check']:
            new = auto_check(spec, o, 'carries the PSO Coated v3 output intent.', {'op': 'pdf_output_intent', 'contains': 'PSO Coated v3'},
                             'Automatic check: the PDF OutputIntents name or profile description includes PSO Coated v3.')
        else:
            new = auto_check(spec, o, 'uses RGB colour only, with no CMYK colour and no CMYK output intent.', {'op': 'pdf_no_cmyk'},
                             'Automatic check: no DeviceCMYK or four-channel ICC colour, no CMYK colour operators, no CMYK output intent.')
        new['replaces'] = c['check_id']
        spec['verifiers_auto'].append(new)
    spec['verifiers_human'] = kept


def update_logo_assets(spec):
    changed = False
    for a in spec['assets']:
        if a['filename'] in LOGO_TEXT:
            f = LOGO_DIR / a['filename']
            data = f.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            # Same S3 key (objects are replaced in place, bucket versioning keeps the old file). The objects are served
            # "immutable" for a year, so the link carries a version tag to defeat stale browser caches.
            url = a['public_url'].split('?')[0] + '?v=' + digest[:12]
            new = {'bytes': len(data), 'sha256': digest, 'description': LOGO_TEXT[a['filename']], 'revision': REV, 'public_url': url,
                   'revision_note': 'Rebuilt 2026-10-21 from the Adobe trace of northgrove_mark.png; the previous file had lost the leaf.'}
            if any(a.get(k) != v for k, v in new.items()):
                a.update(new)
                changed = True
    return changed


def main():
    for tid in IDS:
        path = TASKS / tid / 'TASK_SPEC.json'
        original = path.read_text()
        spec = json.loads(original)
        spec['verifiers_human'] = [c for c in spec['verifiers_human'] if c['check_id'] not in RETIRE]
        bi = spec['brand_identity']
        bi['typography'] = bi.get('typography', '').replace(ASK_US, '')
        ts = bi['type_system']
        ts['application'] = ts.get('application', '').replace(ASK_US, '')
        convert_machine_facts(spec)
        if tid == 'PHOTO-10' and update_logo_assets(spec):
            urls = {a['filename']: a['public_url'] for a in spec['assets'] if a['filename'] in LOGO_TEXT}
            for c in spec['verifiers_auto'] + spec['verifiers_human']:
                for ref in c.get('reference_assets', []):
                    if ref.get('filename') in urls:
                        ref['url'] = urls[ref['filename']]
            manifest = TASKS / tid / 'ASSET_MANIFEST.json'
            text = manifest.read_text()
            manifest.write_text(json.dumps(spec['assets'], ensure_ascii=False, indent=2) + ('\n' if text.endswith('\n') else ''))
        result = json.dumps(spec, ensure_ascii=False, indent=1) + ('\n' if original.endswith('\n') else '')
        if result != original:
            path.write_text(result)
        print(tid, 'auto', len(spec['verifiers_auto']), 'human', len(spec['verifiers_human']), 'ask-us left', json.dumps(spec).count('ask us before substituting'))


if __name__ == '__main__':
    main()
