#!/usr/bin/env python3
"""Reconcile the Oct 22 follow-up review without changing check IDs or past run results."""
import json
import re
from collections import Counter

from build_v7_annotation_pilot import TASK_IDS, TASKS, OUT

LOOK_NOTE = 'Inspect the named output against this requirement and its linked references.'
COLOUR_NOTE = ('Sample flat colour interiors, not anti-aliased edges, in an image or PDF editor. '
               'Compare with the stated hex values in sRGB; convert CMYK objects through their embedded profile first.')


def repair():
    methods = Counter()
    for tid in TASK_IDS:
        path = TASKS / tid / 'TASK_SPEC.json'
        original = path.read_text()
        spec = json.loads(original)
        for c in spec['verifiers_auto']:
            if c.get('assertion',{}).get('op') == 'pdf_output_intent':
                profile = next(a for a in spec['assets'] if a['filename'] == 'PSOcoated_v3.icc')
                c['assertion']['profile_sha256'] = profile['sha256']
        for c in spec['verifiers_human']:
            if not c.get('method'):
                # Photo colour-fidelity comparisons are visual, not exact palette samples.
                exact_colour = re.search(r'#[0-9A-Fa-f]{6}', c['check']) and 'shifted toward' not in c['check']
                c['method'] = 'measure' if exact_colour else 'look'
                c['method_note'] = COLOUR_NOTE if exact_colour else LOOK_NOTE
            if c['method'] == 'look' and not c.get('method_note'):
                c['method_note'] = LOOK_NOTE
            if c['method'] not in ('look', 'measure', 'estimate') or not c.get('method_note'):
                raise ValueError(f"Incomplete method: {c['check_id']}")
            methods[c['method']] += 1
        if tid == 'LAYOUT-12':
            brand = spec['brand_identity']
            brand['typography'] = (
                'Use Sora ExtraBold caps for series titles, act names and date lines. '
                'The A2 series title is 180 pt / 148 pt with -10 tracking; the release-post title is 96 px. '
                'On A2 posters, Sable Quartet, Meridian Brass and Night Ferry are each larger than the remaining act names; '
                'choose their larger size to fit the direction. The remaining act names are 48 pt. '
                'All release-post act names are 76 px. Act names use -10 tracking and one or two lines; KOA stays on one line. '
                'Act names are Bone White on Pitch. Date lines are Sodium, immediately above their act, '
                'at 18 pt / 22 pt on posters and 30 px / 36 px on posts, with +20 tracking. '
                'Archivo Narrow Regular sets body, supporting billing and tables: 14 pt / 19 pt on posters, '
                '28 px / 38 px on posts and 18 pt / 25 pt in the deck, with 0 tracking and at most 65 characters per line. '
                'Poster licence and accessibility lines use Archivo Narrow Regular at 9 pt / 13 pt. '
                'Release-post fine print is at least 22 px / 30 px. Fine print uses +30 tracking. '
                'Archivo Narrow SemiBold is reserved for door-time information; other fine print is Regular.'
            )
            brand['type_system']['scale'][0]['note'] = (
                'A2 series title only, not every act in the schedule. Use 96 px for a release-post series title. '
                'On A2 posters, Sable Quartet, Meridian Brass and Night Ferry must each be larger than the remaining acts; '
                'choose their larger size. Remaining act names are 48 pt. All release-post act names are 76 px. '
                'Act names may occupy one or two lines; keep KOA on one line.'
            )
            choice = ' Choose the three poster headliner sizes above 48 pt; the remaining poster act names stay at 48 pt.'
            if choice.strip() not in brand['creative_scope']['designer_choices']:
                old = brand['creative_scope']['designer_choices']
                brand['creative_scope']['designer_choices'] += choice
                spec['client_brief'] = spec['client_brief'].replace(old, old + choice)
            coverage_path = OUT / 'coverage' / f'{tid}.json'
            coverage = json.loads(coverage_path.read_text())
            for rule in coverage['rules']:
                if rule['rule_id'] == 'T18':
                    rule['rule'] = ('On A2 posters, Sable Quartet, Meridian Brass and Night Ferry are each larger than '
                                    'the 48 pt remaining act names; the designer chooses the larger sizes.')
                    rule['source'] = 'brand_identity.typography; brand_identity.type_system.scale[0].note'
            coverage_path.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + '\n')
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + ('\n' if original.endswith('\n') else ''))
    print('Checking methods:', dict(methods))


if __name__ == '__main__':
    repair()
