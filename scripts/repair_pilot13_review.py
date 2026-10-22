#!/usr/bin/env python3
"""Reconcile the Oct 22 follow-up review without changing check IDs or past run results."""
import json
import re
from collections import Counter

from build_v7_annotation_pilot import TASK_IDS, TASKS, OUT

LOOK_NOTE = 'Inspect the named output against this requirement and its linked references.'
# One shared colour tolerance: no two palette colours in the 13 pilot tasks are within 10 of each other in every
# channel, so a 5-unit window never matches two of them. Video stills keep the 10-unit window MOTION-11 already used.
TOLERANCE = 'A sample matches a stated hex when R, G and B are each within 5 of it.'
VIDEO_TOLERANCE = 'A sample matches a stated hex when R, G and B are each within 10 of it.'
COLOUR_NOTE = ('Sample flat colour interiors, not anti-aliased edges, in an image or PDF editor. '
               'Compare with the stated hex values in sRGB; convert CMYK objects through their embedded profile first. '
               + TOLERANCE)
GENERIC_COLOUR = COLOUR_NOTE.split('.')[0]
VIDEO_NOTE = ('Pause where the named element is fully shown and save that frame as a still. '
              'Sample flat colour interiors, not anti-aliased edges. ' + VIDEO_TOLERANCE)
VECTOR_EXACT = 'The hex read from the file must match exactly.'
VECTOR_NOTE = "Read the fill or stroke hex in the SVG code or a vector editor's colour panel. " + VECTOR_EXACT
# A palette colour converted to PSO Coated v3 and back reads within 4 of its hex only with these settings.
PRESS_NOTE = 'Convert with Relative Colorimetric and black point compensation, the Adobe default.'
HEX = re.compile(r'#[0-9A-Fa-f]{6}')
# The note already decides a sample: a numeric window, an exact vector read, or a nearest-colour or brightness rule.
DECIDED = re.compile(r'(?i)within \d+|exactly|must be #|\bnearer\b|HSB brightness')


def colour_tolerance(spec):
    """Make every exact-colour Measure check say how close a sampled colour must be; return the number changed."""
    formats = {o['output_id']: o['spec']['format'] for o in spec['deliverables']}
    press = {c['output_id'] for c in spec['verifiers_auto'] if c['assertion'].get('op') == 'pdf_output_intent'}
    changed = 0
    for c in spec['verifiers_human']:
        if c['method'] != 'measure' or not HEX.search(c['check']):
            continue
        fmt, note = formats[c['output_id']], c['method_note']
        # Earlier one-off rules (rounding only, "clearly differs") move to the shared window.
        note = re.sub(r'1-unit (?:channel )?differences are rounding\.', TOLERANCE[0].lower() + TOLERANCE[1:], note)
        note = re.sub(r'clearly differs from both (#[0-9A-Fa-f]{6}) and (#[0-9A-Fa-f]{6})', r'matches neither \1 nor \2', note)
        note = re.sub(r'clearly differs from (#[0-9A-Fa-f]{6})', r'does not match \1', note)
        note = note.replace('clearly matches none of', 'matches none of')
        note = re.sub(r'reads at or very near (#[0-9A-Fa-f]{6})', r'matches \1', note)
        if note.startswith(GENERIC_COLOUR) and fmt in ('mp4', 'svg'):
            note = VIDEO_NOTE if fmt == 'mp4' else VECTOR_NOTE
        if c['output_id'] in press and 'black point' not in note:
            note += ' ' + PRESS_NOTE
        if not DECIDED.search(note):
            note += ' ' + {'mp4': VIDEO_TOLERANCE, 'svg': VECTOR_EXACT}.get(fmt, TOLERANCE)
        if note != c['method_note']:
            c['method_note'] = note
            changed += 1
    return changed


def repair():
    methods = Counter()
    tolerances = 0
    for tid in TASK_IDS:
        path = TASKS / tid / 'TASK_SPEC.json'
        original = path.read_text()
        spec = json.loads(original)
        for c in spec['verifiers_auto']:
            if c.get('assertion',{}).get('op') == 'pdf_output_intent':
                profile = next(a for a in spec['assets'] if a['filename'] == 'PSOcoated_v3.icc')
                c['assertion']['profile_sha256'] = profile['sha256']
        for c in spec['verifiers_human']:
            # Photo colour-fidelity comparisons are visual, not exact palette samples.
            exact_colour = re.search(r'#[0-9A-Fa-f]{6}', c['check']) and 'shifted toward' not in c['check']
            if not c.get('method') or (c['method'] == 'look' and exact_colour):
                c['method'] = 'measure' if exact_colour else 'look'
                c['method_note'] = COLOUR_NOTE if exact_colour else LOOK_NOTE
            if c['method'] == 'look' and not c.get('method_note'):
                c['method_note'] = LOOK_NOTE
            if c['method'] not in ('look', 'measure', 'estimate') or not c.get('method_note'):
                raise ValueError(f"Incomplete method: {c['check_id']}")
            methods[c['method']] += 1
        tolerances += colour_tolerance(spec)
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
    print('Colour notes given a tolerance:', tolerances)


if __name__ == '__main__':
    repair()
