#!/usr/bin/env python3
"""Apply the final verifier review to the current pilot without rewriting past runs."""
import copy
import hashlib
import json
import re
from collections import Counter

from build_v7_annotation_pilot import TASK_IDS, TASKS, OUT, ROOT
from repair_pilot13_review import COLOUR_NOTE, colour_tolerance

REVISION = 'pilot13_verifier_lock_2026_10_22'
POLICY = (
    'Score only the listed current Auto and Human verifiers. A design target marked '
    '"Not scored" in coverage remains a client instruction but is excluded from the score denominator: '
    'the requested delivery does not provide enough evidence to verify it. Do not infer a pass or failure. '
    'If a listed measurement cannot be completed, leave it unanswered and record the missing evidence; '
    'do not guess. Human answers remain Yes/No. Historical run results are not current scores.'
)
AREA_NOTE = (
    'Measure, do not estimate. On a measurement copy, mask the named area; exclude photographs and '
    'transparent canvas. Count the selected accent-colour pixels and divide by all pixels in that mask. '
    'Include text unless the condition excludes it. Test each PDF page or held video frame separately. '
    'Yes only when the unrounded percentage is at or below the stated limit. '
    'Use the linked measurement guide for rasterisation and colour matching.'
)
NEUTRAL_NOTE = (
    'Sample the flat ground beside the left shoulder, beside the right shoulder and above the head. '
    'Each sample must be within 5 in every RGB channel of one blend between Fog Grey (217,221,222) '
    'and Warm Paper (242,238,231). Use the neutral-range calculator in the measurement guide; '
    'all three samples must pass. Do not sample hair or anti-aliased edges.'
)


def wording(c, text):
    for key in ('check', 'pass_condition', 'requirement'):
        c[key] = text
    c['revision'] = REVISION


def reference(c):
    # The file uniquely identifies an output and avoids repeating long commission titles.
    return c['artifact_file']


def atomic_parts(c):
    t, f = c['check'], reference(c)
    if 'The d stem' in t and '#222724' in t and 'as placed' in t:
        return [f'On Warm Off White in {f}, the wordmark ink is #222724 or Soft Ink #33352E.',
                f'On Sage in {f}, the wordmark ink is #222724, Soft Ink #33352E or Warm Off White #F4F0E8.']
    if 'keeps her natural skin and hair colour, with no heavy filter' in t:
        parts = [f'The portrait in {f} retains natural skin colour from its source photograph.',
                f'The portrait in {f} retains the hair colour from its source photograph.',
                f'The portrait in {f} has no added creative colour filter or colour grade.',
                f'The facial skin texture in {f} has not been smoothed away.']
        if t.startswith('If '):
            parts = [f'If {f} carries a portrait, ' + p.replace('The portrait in ' + f, 'it').replace('The facial skin texture in ' + f, 'its facial skin texture') for p in parts]
        return parts
    if 'shows no pale or grey rim and no clipped curls' in t:
        return [f'The hair edge in {f} has no pale or grey fringe.', f'No source curls are clipped away in {f}.']
    if 'has no starburst and no slashed or struck-through price' in t:
        return [f'{f} contains no starburst graphic.', f'{f} contains no slashed or struck-through price.']
    if 'no hard flash shadow behind the head and no flat shine across the face' in t:
        return [f'No portrait in {f} has a hard flash shadow behind the head.',
                f'No portrait in {f} has a flat direct-flash shine across the face.']
    if "The print's white border and the skin" in t:
        return [t.replace("The print's white border and the skin", "The print's white border"),
                t.replace("The print's white border and the skin", 'The skin')]
    if 'Body text and the booking action' in t:
        return [t.replace('Body text and the booking action', 'Body text'),
                t.replace('Body text and the booking action', 'The booking action').replace('are set', 'is set')]
    if "names the house's stone, its water and its light" in t or re.search(r"names Casa \w+'s stone, its water and its light", t):
        prefix = t.split('names ')[0]
        house = re.search(r"names (Casa \w+)'s", t)
        subject = house[1] if house else 'the named house'
        return [prefix + f'mentions {subject}\'s {part}.' for part in ('stone or walls', 'water, pool or cove', 'light or daylight')]
    if 'The Ardent dial and strap' in t:
        return [t.replace('The Ardent dial and strap', 'The Ardent dial').replace('match their colour', 'matches its colour'),
                t.replace('The Ardent dial and strap', 'The Ardent strap').replace('match their colour', 'matches its colour')]
    if 'the handle loops of the mug from autumn_shoot_01.jpg and the teapot from autumn_shoot_13.jpg' in t:
        return [f'The cut-out {name} handle opening in {f} shows the background behind the product, not the studio sweep from {src}.'
                for name, src in [('mug', 'autumn_shoot_01.jpg'), ('teapot', 'autumn_shoot_13.jpg')]]
    if 'and no scrim or overlay on' in t or 'and no photograph carries a scrim or overlay' in t:
        a = re.split(r', and no (?:scrim|photograph)', t)[0].rstrip('.') + '.'
        return [a, f'No photograph in {f} carries a scrim or overlay.']
    if 'keeps the orange fur and purple headset' in t:
        return [t.replace('orange fur and purple headset', 'orange fur'),
                t.replace('orange fur and purple headset', 'purple headset')]
    if 'Any capacity figure' in t and '250 standing or 120 seated cabaret' in t:
        return [f'Any standing capacity in {f} is 250, as specified in umbra_room_specs.txt.',
                f'Any seated-cabaret capacity in {f} is 120, as specified in umbra_room_specs.txt.']
    if 'Any season-average draw' in t and '183 of 250, 73 percent' in t:
        return [f'Any season-average attendance in {f} is 183, as specified in umbra_room_specs.txt.',
                f'Any season-average occupancy percentage in {f} is 73%, as specified in umbra_room_specs.txt.']
    return None


def split_checks(spec, coverage):
    replacements = {}
    additions = []
    next_id = Counter()
    for c in spec['verifiers_human']:
        m = re.search(r'/H(\d+)$', c['check_id'])
        if m: next_id[c['output_id']] = max(next_id[c['output_id']], int(m[1]))
    for c in spec['verifiers_human']:
        parts = atomic_parts(c)
        if not parts: continue
        original = copy.deepcopy(c)
        c['split_from'] = original['check_id']
        wording(c, parts[0])
        ids = [c['check_id']]
        for part in parts[1:]:
            added = copy.deepcopy(original)
            next_id[c['output_id']] += 1
            added['check_id'] = f"{spec['new_id']}/{c['output_id']}/H{next_id[c['output_id']]:03d}"
            added['split_from'] = original['check_id']
            wording(added, part)
            additions.append(added)
            ids.append(added['check_id'])
        replacements[original['check_id']] = ids
    spec['verifiers_human'].extend(additions)
    for r in coverage['rules']:
        for cell in r['cells'].values():
            if cell.get('checks'):
                cell['checks'] = list(dict.fromkeys(x for cid in cell['checks'] for x in replacements.get(cid, [cid])))
    return len(replacements), len(additions)


def measurements(spec):
    counts = Counter()
    for c in spec['verifiers_human']:
        t, note = c['check'], c['method_note']
        if spec['new_id'] == 'PHOTO-06' and 'nearer' in note:
            c['method_note'] = COLOUR_NOTE
            c['measurement'] = {'kind': 'colour', 'channel_tolerance': 5}
            counts['nearest_colour_replaced'] += 1
        if spec['new_id'] == 'PHOTO-19' and 'HSB brightness' in note:
            c['method_note'] = NEUTRAL_NOTE
            c['measurement'] = {'kind': 'neutral_range', 'from_rgb': [217,221,222], 'to_rgb': [242,238,231], 'channel_tolerance': 5}
            counts['neutral_range_replaced'] += 1
        if c['method'] != 'estimate': continue
        counts['estimate_replaced'] += 1
        if 'draw chart' in t:
            c['method'] = 'look'
            c['method_note'] = 'Read the printed value label for the named month; it must match exactly. Do not estimate a value from bar height.'
            wording(c, t.replace('shows ', 'labels '))
            continue
        c['method'] = 'measure'
        t = t.replace('about 5%', '5%').replace('only a small share, 5% or less,', 'no more than 5%')
        wording(c, t)
        c['method_note'] = AREA_NOTE
        c['measurement'] = {'kind': 'area_ratio', 'channel_tolerance': 10 if c['artifact_file'].endswith('.mp4') else 5,
                            'max_percent': 10 if 'a tenth' in t or '10%' in t else 5}
        if 'covers more of every page' in t:
            c['measurement'] = {'kind': 'area_comparison', 'channel_tolerance': 5, 'comparison': 'strictly_greater'}
            c['method_note'] = ('Measure each PDF page separately. Exclude photographs. Count Warm Paper Ground pixels and '
                'compare with the combined Oatmeal Glaze, Soft Clay and Indigo Dye pixels. Yes only if Warm Paper Ground '
                'has strictly more pixels on every page. Use the measurement guide; do not estimate.')
        elif 'promoter-deck' == c['output_id']:
            c['method_note'] += ' Exclude the embedded poster previews; assess the surrounding deck graphics on each page.'
        elif spec['new_id'] == 'VECTOR-04':
            c['method_note'] += ' The mask is the visible inked artwork only, not the sticker background or transparent gaps.'
        elif spec['new_id'] == 'PHOTO-06':
            c['method_note'] += ' The mask is only the added caption margin, not the restored historical print.'
    return counts


def reconcile_verda(spec, coverage):
    if spec['new_id'] != 'PHOTO-28': return
    brand = spec['brand_identity']
    for key in ('typography', 'signature_type_move'):
        brand[key] = brand[key].replace('verda_logo_web.png', 'verda_wordmark_transparent.png')
    def replace_names(value):
        if isinstance(value, dict): return {k: replace_names(v) for k, v in value.items()}
        if isinstance(value, list): return [replace_names(v) for v in value]
        return value.replace('verda_logo_web.png', 'verda_wordmark_transparent.png') if isinstance(value, str) else value
    brand['type_system'] = replace_names(brand['type_system'])
    exception = (' The supplied verda_wordmark_transparent.png may retain its original dark ink (#222724 as placed) '
                 'on Warm Off White or Sage at 100% layer opacity. This exception applies only to that supplied wordmark, '
                 'not newly typeset text or other graphics. Intentional recolouring uses Soft Ink on Warm Off White, '
                 'or Soft Ink or Warm Off White on Sage.')
    for key in ('distribution', 'opacity', 'forbidden'):
        if exception.strip() not in brand['palette_rules'][key]: brand['palette_rules'][key] += exception
    for colour in brand['palette']:
        if colour['name'] == 'Soft Ink' and 'original dark ink' not in colour['usage']:
            colour['usage'] += ' The supplied wordmark may instead retain its original dark ink; see Colour rules.'
    for rule in coverage['rules']:
        if rule['rule_id'] in ('B01', 'B04', 'B05') and 'original ink #222724' not in rule['rule']:
            rule['rule'] += ' Exception: the supplied wordmark may retain original ink #222724 on Warm Off White or Sage.'
    for c in spec['verifiers_human']:
        if '#222724' in c['check']:
            c['evidence_reference'] = 'Brand identity, palette_rules: explicit original-ink exception for verda_wordmark_transparent.png.'
            c['method_note'] = ('If the named ground is absent, this conditional requirement passes. Otherwise sample the '
                'middle of the d stem. Each RGB channel must be within 4 of one colour stated in this check; '
                'do not sample anti-aliased edges.')
        # The blanket four-colour rule must not reject the explicitly permitted supplied ink.
        if 'only' in c['check'] and all(h in c['check'] for h in ('#9CA98F', '#C7A97A', '#F4F0E8', '#33352E')) and 'wordmark' in c['check']:
            wording(c, c['check'].replace('wordmark, ', '').replace('type, the wordmark', 'newly typeset text'))
        if 'wordmark' in c['check'].lower() and 'Soft Ink' in c['check'] and '#222724' not in c['check']:
            c['method_note'] += (' The supplied wordmark may retain #222724 on Warm Off White or Sage; '
                                 'this original-ink exception does not apply to newly typeset text.') if 'original-ink exception' not in c['method_note'] else ''


def complete_coverage(spec, coverage):
    checks = {c['check_id']: c for c in spec['verifiers_human'] + spec['verifiers_auto']}
    referenced = {cid for r in coverage['rules'] for cell in r['cells'].values() for cid in cell.get('checks', [])}
    groups = {}
    for c in checks.values():
        if c['check_id'] in referenced: continue
        template = c['check'].replace(c['artifact_file'], 'the named file')
        template = re.sub(r'“[^”]+” \(the named file\)', 'the named deliverable', template)
        groups.setdefault((c['type'], template), []).append(c)
    added = sum(len(g) for g in groups.values())
    for (kind, template), group in groups.items():
        key = hashlib.sha256((kind + template).encode()).hexdigest()[:12]
        by_output = {}
        for c in group: by_output.setdefault(c['output_id'], []).append(c['check_id'])
        coverage['rules'].append({'rule_id': 'C-' + key, 'kind': 'deliverable', 'rule': template,
            'source': '; '.join(c['check_id'] for c in group),
            'scope': sorted(by_output),
            'cells': {o['output_id']: {'checks': by_output[o['output_id']]} if o['output_id'] in by_output else
                      {'na': 'This output-specific requirement is scoped to the named files in this row; other outputs have their own requirement rows.'}
                      for o in spec['deliverables']}})
    excluded = []
    for r in coverage['rules']:
        for output_id, cell in r['cells'].items():
            if 'not_verified' in cell:
                cell['scoring'] = 'excluded'
                cell['scoring_reason'] = 'Design instruction retained; evidence is unavailable in the requested finished format. Excluded from the score denominator.'
                excluded.append({'rule_id': r['rule_id'], 'output_id': output_id, 'reason': cell['not_verified']})
    coverage['scoring_policy'] = POLICY
    coverage['revision'] = REVISION
    spec['evaluation']['objective_scoring_policy'] = POLICY
    spec['evaluation']['unscored_design_targets'] = excluded
    return added, len(excluded)


def main():
    totals = Counter()
    rows = []
    for tid in TASK_IDS:
        path = TASKS / tid / 'TASK_SPEC.json'
        raw = path.read_text()
        spec = json.loads(raw)
        cp = OUT / 'coverage' / f'{tid}.json'
        coverage = json.loads(cp.read_text())
        split, new = split_checks(spec, coverage)
        outputs = {o['output_id']: o for o in spec['deliverables']}
        assets = {a['filename']: a for a in spec['assets']}
        for c in spec['verifiers_human']:
            if c.get('split_from'):
                text = c['check']
                if text.startswith('Body text '): text = text.replace(' are set ', ' is set ')
                if text.startswith(("The print's white border ", 'The skin ')): text = text.replace(' show no ', ' shows no ')
                if text != c['check']: wording(c, text)
            source = outputs[c['output_id']].get('source_image')
            if c.get('split_from') and source and 'its source photograph' in c['check']:
                wording(c, c['check'].replace('its source photograph', source))
            if c.get('split_from') and source in assets and source in c['check']:
                c['reference_assets'] = [r for r in c['reference_assets'] if isinstance(r, dict)]
                if not any(r.get('filename') == source for r in c['reference_assets']):
                    c['reference_assets'].append({'filename': source, 'url': assets[source]['public_url']})
        counts = measurements(spec)
        for c in spec['verifiers_human']:
            m = c.get('measurement', {})
            if m.get('kind') in ('area_ratio', 'area_comparison') and 'Each RGB channel' not in c['method_note']:
                c['method_note'] += f" Each RGB channel must be within {m['channel_tolerance']} of a selected palette colour."
        reconcile_verda(spec, coverage)
        colour_tolerance(spec)
        if tid == 'PHOTO-19':
            clarification = (' The portrait-background neutral range is any single RGB blend from Fog Grey '
                             '(217,221,222) to Warm Paper (242,238,231); sampled flat areas allow 5 units per channel.')
            if clarification.strip() not in spec['brand_identity']['palette_rules']['photography']:
                spec['brand_identity']['palette_rules']['photography'] += clarification
        if tid == 'LAYOUT-12':
            output = next(o for o in spec['deliverables'] if o['output_id'] == 'promoter-deck')
            instruction = 'Label every monthly draw-chart value with its exact number from umbra_room_specs.txt; do not rely only on bar height.'
            if instruction not in output['commission']['content']: output['commission']['content'].append(instruction)
            if not any(r['rule_id'] == 'C-chart-value-labels' for r in coverage['rules']):
                coverage['rules'].append({'rule_id': 'C-chart-value-labels', 'kind': 'deliverable', 'rule': instruction,
                    'source': 'deliverables.promoter-deck.commission.content',
                    'cells': {o['output_id']: {'checks': [c['check_id'] for c in spec['verifiers_human']
                        if c['output_id'] == 'promoter-deck' and 'draw chart' in c['check']]} if o['output_id'] == 'promoter-deck'
                        else {'na': 'The monthly draw chart is requested only in the promoter deck.'} for o in spec['deliverables']}})
        added, excluded = complete_coverage(spec, coverage)
        totals.update(counts)
        totals.update(split_checks=split, added_atomic_checks=new, added_coverage_mappings=added)
        path.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + ('\n' if raw.endswith('\n') else ''))
        cp.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + '\n')
        rows.append({'task': tid, 'human': len(spec['verifiers_human']), 'auto': len(spec['verifiers_auto']),
                     'not_scored': excluded, 'methods': dict(Counter(c['method'] for c in spec['verifiers_human']))})
    report = ROOT / 'tools/pilot13_ab_fixes/round4'
    report.mkdir(exist_ok=True)
    (report / 'summary.json').write_text(json.dumps({'revision': REVISION, 'tasks': rows}, indent=2) + '\n')
    print(json.dumps(dict(totals), indent=2))


if __name__ == '__main__':
    main()
