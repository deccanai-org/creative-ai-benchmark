"""Round 2 conversions (2026-10-28): the automatic rules round 1 could not convert, one handler per rule.

Each handler turns one row (one check) into an assertion for tools/auto_verifier/objective_ops_r2.py, or returns
None when the row cannot be checked exactly; a rule moves only when every row converts. Handlers are keyed by task
and rule, so round-1 conversions never change. Values come from the row's own wording, the deliverable's source
record or the task's supplied data files.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
RUN = ROOT.parents[1] / 'benchmark_runs/pilot_v7_hybrid_2026-09-28'
MON = r'(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*'
DATE_ANY = rf'(?<!\d)\d{{1,2}}\s*{MON}\b|\b{MON}\.?\s*\d{{1,2}}(?!\d)'
PRICE_ANY = r'[$€£]\s?\d'
WEEKDAYS = {'Monday': 'MON', 'Tuesday': 'TUE', 'Wednesday': 'WED', 'Thursday': 'THU', 'Friday': 'FRI', 'Saturday': 'SAT', 'Sunday': 'SUN'}
MOVEMENT = r'hand-?\s?wound|automatic|self-?winding|manual(?:ly)?[- ]wound|power reserve|\breserve\b|small[- ]seconds'
TIMING = 'Timed by hand and signed. This piece was regulated to the result above and released by the named regulator.'


def q(v: str) -> str:
    return v.strip().strip('“”"')


def num(v) -> dict:
    digits = str(v).replace(',', '')
    if len(digits) > 3 and '.' not in digits:
        digits = digits[:-3] + ',?' + digits[-3:]
    return {'regex': rf'(?<![\d,.]){digits}(?![\d,.]|\d)'}


def source_file(tid: str, name: str) -> Path | None:
    for d in (REFRESH / 'upload' / tid, REFRESH / 'sources' / tid, RUN / tid / 'source'):
        if (d / name).is_file():
            return d / name
    return None


def read_csv(tid: str, name: str) -> list[dict]:
    f = source_file(tid, name)
    return list(csv.DictReader(f.open(encoding='utf-8-sig'))) if f else []


def palette(ctx, name: str) -> str:
    return ctx.palette[name]


def date_rx(day, mon) -> dict:
    from convert import date_regex
    return {'regex': date_regex(str(day), mon)}


def rows_values(ctx, rid):
    return [r['values'] for r in ctx.rules[rid]['rows'] if r.get('values')]


# ------------------------------------------------------------------ PHOTO-04 villa collection

HOUSES = ['Casa Verranza', 'Casa Oliveto', 'Casa Scogliera']
P04_KINDS = {'sleeps': r'\bsleeps?\b', 'season': r'^\s*(?:spring|high summer|autumn)\s*$', 'rate': r'(?:EUR|€)\s?\d|\d\s?(?:EUR|€)|/\s*night',
             'min': r'\bmin(?:imum|\.)?\b'}


def house(name):
    return [name, name.split()[-1]]


def rivals(name):
    return [x for h in HOUSES if h != name for x in house(h)]


def p04_rate(row, ctx):
    v = row['values']
    season = re.sub(r'^an? ', '', v['2'])
    kind, value = ((P04_KINDS['rate'], num(v['3'])) if 'nightly rate' in row['check']
                   else (r'\bmin(?:imum|\.)?\b.*\bnights?\b', {'regex': rf'\b{v["3"]}\s*nights?\b'}))
    return {'op': 'v2_paired', 'anchor': house(v['1']), 'rivals': rivals(v['1']), 'label': [season],
            'label_rivals': [s for s in ('Spring', 'High Summer', 'Autumn') if s != season], 'kind': kind, 'value': value, 'where': 'section'}


def p04_sleeps(row, ctx):
    v = row['values']
    return {'op': 'v2_paired', 'anchor': house(v['1']), 'rivals': rivals(v['1']), 'kind': r'\bsleeps?\b\W*\d',
            'value': {'regex': rf'\bsleeps?\W{{0,3}}{v["2"]}\b'}, 'where': 'section'}


def p04_sections(**checks):
    return lambda row, ctx: dict({'op': 'v2_sections', 'names': HOUSES, 'kinds': P04_KINDS, 'value_kinds': ['rate']}, **checks)


# ------------------------------------------------------------------ PHOTO-06 family archive

def p06_catalogue(row):
    rows = read_csv('PHOTO-06', 'photo_catalogue.csv')
    n = int(re.search(r'(\d+)$', row['output_id']).group(1))
    return rows[n - 1] if 0 < n <= len(rows) else None


def p06_names(row, ctx):
    full = row['values']['1']
    first, last = full.split()[0], full.split()[-1]
    return {'op': 'v2_text_present', 'expected': [[full, {'regex': rf'\b{first}(?:,| and| &) [\w ,&]*{last}\b'}]]}


def p06_accession(row, ctx):
    code = (r'\b(?:acc(?:ession)?\.?\s*(?:no\.?|number|#)|accession|cat(?:alogue)?\.?\s*(?:no\.?|#)|inv(?:entory)?\.?\s*no\.?|object\s+no\.?)'
            r'|\b[A-Z]{2,5}[-./]\d{2,4}(?:[-./]\d{1,4})+\b|\b(?:18|19|20)\d\d\.\d{1,4}\.\d{1,4}\b')
    return {'op': 'v2_all_of', 'checks': [{'op': 'v2_text_absent', 'patterns': {'accession code': code}},
                                          {'op': 'v2_text_absent', 'patterns': {'plate or number label': r'\b(?:plate|no\.)\s*\d+'}, 'found_is': 'person'}]}


def p06_name_larger(row, ctx):
    rec = p06_catalogue(row)
    if not rec:
        return None
    names = re.split(r',\s*|\s+and\s+', rec['Names'])
    first = names[0].strip()
    if len(first.split()) == 1:
        first = f'{first} {rec["Names"].split()[-1]}'
    place = re.sub(r'^\d{4},\s*', '', rec['Date and Place']).rsplit(' ', 1)[0]
    return {'op': 'v2_size_vs', 'rel': 'larger', 'a': [first, rec['Caption Title']], 'b': [place]}


# ------------------------------------------------------------------ PHOTO-08 vehicle cards

ENQUIRE = {'regex': r'\b(?:enquir|inquir)\w*'}


def p08_action(value):
    def h(row, ctx):
        v = q(row['values'].get('1', value)) if value is None else value
        rx = re.escape(v).replace(r'\ ', r'\s+').replace(',', ',?')
        return {'op': 'v2_paired', 'anchor': [ENQUIRE], 'whole_line': False, 'kind': rx, 'value': {'regex': rx}, 'where': 'beside'}
    return h


def p08_roundel(row, ctx):
    return {'op': 'v2_ground_mark', 'asset': 'meridian_roundel.png', 'ground': palette(ctx, 'Meridian Navy')}


def p08_title(row, ctx):
    rec = ctx.records.get(row['output_id'], {})
    if not rec:
        return None
    miles = f'{int(rec["mileage"]):,}'
    return {'op': 'v2_relation', 'rel': 'larger', 'a': q(row['values']['1']), 'b': [miles, rec['trim']]}


# ------------------------------------------------------------------ PHOTO-10 Northgrove

COLOURWAYS = ['Moss', 'Bark', 'Slate', 'Oat', 'Ink', 'Clay', 'Fern']
STYLES = ['Loopback Crew', 'Heavyweight Tee', 'Raglan', 'Henley', 'Hoodie', "Supporters' Crew"]


def p10_style_name(output_id):
    for key, name in (('loopback', 'Loopback Crew'), ('heavy', 'Heavyweight Tee'), ('raglan', 'Raglan'), ('henley', 'Henley'),
                      ('hoodie', 'Hoodie'), ('supporters', "Supporters' Crew")):
        if key in output_id:
            return name
    return None


# ------------------------------------------------------------------ PHOTO-20 Astrid Vellacourt

def p20_rec(ctx, row):
    return ctx.records.get(row['output_id'], {})


def p20_date(value: str) -> dict:
    """A record date in any clear form: "14 Feb 2026", "2026-03-03" shown as "3 Mar 2026" or "March 3"."""
    import datetime as dt
    try:
        d = dt.date.fromisoformat(value)
    except ValueError:
        m = re.match(r'(\d{1,2}) (\w{3})', value)
        return date_rx(m.group(1), m.group(2)) if m else {'regex': re.escape(value)}
    return {'regex': date_rx(d.day, d.strftime('%b'))['regex'] + '|' + re.escape(value)}     # or as the record writes it


def p20_events(ctx):
    events = sorted({v['Event Name'] for v in ctx.records.values() if v.get('Event Name')})
    return events


def p20_monogram_position(optional):
    def h(row, ctx):
        rec = p20_rec(ctx, row)
        b = {'image': 'largest'} if row['file'].endswith('.pdf') else ({'asset': rec['Portrait']} if rec.get('Portrait') else None)
        if b is None:
            return None
        a = {'op': 'v2_position', 'a': {'colour': palette(ctx, 'Ochre')}, 'b': b, 'rel': 'above_or_left'}
        if optional:
            a['optional_b'] = True
        return a
    return h


def p20_below_portrait(row, ctx):
    rec = p20_rec(ctx, row)
    if not rec:
        return None
    parts = [{'text': rec['Talk Title']}, {'text': rec['Event Name']}, {'pattern': p20_date(rec['Date'])['regex']}]
    return {'op': 'v2_all_of', 'checks': [{'op': 'v2_position', 'a': p, 'b': {'image': 'largest'}, 'rel': 'below'} for p in parts]}


def p20_event_date_ground(optional_all):
    def h(row, ctx):
        rec = p20_rec(ctx, row)
        light = [palette(ctx, 'Warm Neutral'), palette(ctx, 'Bone')]
        ink = [palette(ctx, 'Vellacourt Ink'), palette(ctx, 'Studio Slate')]
        if optional_all:
            return {'op': 'v2_text_on_ground', 'texts': p20_events(ctx), 'patterns': [DATE_ANY + r'|\b20\d\d-\d\d-\d\d\b'], 'grounds': light, 'colors': ink}
        if not rec:
            return None
        return {'op': 'v2_text_on_ground', 'texts': [rec['Event Name']], 'patterns': [p20_date(rec['Date'])['regex']], 'grounds': light,
                'colors': ink, 'optional': False}
    return h


# ------------------------------------------------------------------ PHOTO-24 Lunara

REFS = {'Meridian': 'LM-01', 'Selene': 'LM-02', 'Ardent': 'LM-01', 'Halcyon': 'LM-03', 'Vesper': 'LM-02'}
CALIBER = {'LM-01': {'required': [r'hand-?\s?wound'], 'forbidden': [r'\bautomatic\b', r'self-?winding', r'\b(?!42)\d{2}\s?-?\s?h(?:ours?|rs?)?\b']},
           'LM-02': {'required': [r'\bautomatic\b'], 'forbidden': [r'hand-?\s?wound', r'manual(?:ly)?[- ]wound', r'\b(?!48)\d{2}\s?-?\s?h(?:ours?|rs?)?\b']},
           'LM-03': {'required': [r'hand-?\s?wound'], 'forbidden': [r'\bautomatic\b', r'self-?winding']}}


def p24_movement(caliber, scoped=False):
    def h(row, ctx):
        a = {'op': 'v2_description', 'trigger': MOVEMENT, **CALIBER[caliber]}
        if scoped:
            a['scope_line'] = rf'\b{caliber}\b'
        return a
    return h


def p24_register(ctx):
    rows = read_csv('PHOTO-24', 'lunara_register.csv')
    first = {}
    for r in rows:
        first.setdefault(r['reference'], r)
    return first


# ------------------------------------------------------------------ PHOTO-26 Thornmere

def p26_products():
    return [r['product_name'] for r in read_csv('PHOTO-26', 'thornmere_autumn_skus.csv')]


P26_LINES = [r'[$€£]\s?\d', r'\d\s?mm\b|\bdia\s?\d|\d\s?cm\b', r'dishwasher|hand\s?wash|microwave|wash\b|oven|wipe|tumble|line dry|dry flat']


# ------------------------------------------------------------------ PHOTO-28 Verda

INSTRUCTORS = {'Priya Anand': 'Foundations', 'Dana Osei': 'Flow', 'Lena Brandt': 'Core & Restore', 'Tomas Reyes': 'Strength',
               'Yuki Sato': 'Prenatal', 'Nadia Haddad': 'Slow & Deep'}
PHOTOS = {f'verda_instructor_0{i}.jpg': n for i, n in enumerate(INSTRUCTORS, 1)}
CLASS_RX = '|'.join(re.escape(c).replace(r'\ ', r'\s+') for c in INSTRUCTORS.values())


def p28_class_beside(name):
    def h(row, ctx):
        cls = INSTRUCTORS[name]
        return {'op': 'v2_paired', 'anchor': [name], 'whole_line': False, 'kind': rf'\b(?:{CLASS_RX})\b',
                'value': {'regex': r'\b' + re.escape(cls).replace(r'\ ', r'\s+') + r'\b'}, 'where': 'beside', 'empty_ok': True, 'optional': True}
    return h


def p28_price(classes, price):
    def h(row, ctx):
        return {'op': 'v2_paired', 'anchor': classes, 'whole_line': False, 'kind': PRICE_ANY, 'value': {'regex': rf'\$\s?{price}(?![\d])'},
                'where': 'beside', 'empty_ok': True, 'optional': True}
    return h


def p28_pictured_class(row, ctx):
    who, cls = row['values']['1'], row['values']['2']
    others = [c for c in INSTRUCTORS.values() if c != cls]
    return {'op': 'v2_pictured', 'photos': PHOTOS, 'when': who,
            'then': {'op': 'v2_text_present', 'expected': [cls], 'forbidden': others}}


# ------------------------------------------------------------------ LAYOUT-12 Umbra Loft

def l12_supports(ctx):
    return {v['1']: v['2'] for v in rows_values(ctx, 'R005')}


def l12_paired_date(row, ctx):
    v = row['values']
    return {'op': 'v2_paired', 'anchor': [v['1']], 'rivals': [a for a in ctx.acts if a != v['1']], 'kind': DATE_ANY,
            'value': date_rx(v['2'], v['3']), 'where': 'above_or_same'}


def l12_paired_support(row, ctx):
    v = row['values']
    return {'op': 'v2_paired', 'anchor': [v['1']], 'kind': r'^\s*with\b', 'value': {'regex': rf'^\s*with\s+{re.escape(v["2"])}\b'},
            'where': 'below'}


def l12_weekday(row, ctx):
    day, short = row['values']['1'], row['values']['2']
    others = [w for w in WEEKDAYS if w != day] + [s for w, s in WEEKDAYS.items() if w != day]
    return {'op': 'v2_all_of', 'checks': [{'op': 'v2_weekdays', 'year': 2026},
                                          {'op': 'v2_text_absent', 'patterns': {'another weekday': rf'\b(?:{"|".join(others)})\b'}}]}


def l12_chart(row, ctx):
    v = row['values']
    months = ['Sep', 'Oct', 'Nov', 'Dec', 'Jan', 'Feb']
    full = {'Sep': 'September', 'Oct': 'October', 'Nov': 'November', 'Dec': 'December', 'Jan': 'January', 'Feb': 'February'}
    return {'op': 'v2_paired', 'anchor': [v['1'], full[v['1']]], 'rivals': [x for m in months if m != v['1'] for x in (m, full[m])],
            'kind': r'^\s*\d{2,3}\s*$', 'value': num(v['2']), 'where': 'column'}


def l12_capacity(field, value, pct=''):
    def h(row, ctx):
        key = {'standing': r'standing', 'attendance': r'attendance', 'cabaret': r'cabaret|seated', 'occupancy': r'occupancy'}[field]
        return {'op': 'v2_text_present', 'line_has': key, 'optional': True, 'expected': [{'regex': rf'(?<![\d.]){value}{re.escape(pct)}(?![\d])'}]}
    return h


def l12_style(**want):
    def h(row, ctx):
        optional = row['check'].startswith('Any')
        return dict({'op': 'v2_pdf_text_style', 'texts': list(ctx.acts), 'optional': optional}, **want)
    return h


def l12_wordmark(file, act, check):
    def h(row, ctx):
        if check == 'with_text':
            return {'op': 'v2_mark_with_text', 'asset': file, 'text': act}
        return dict({'op': 'v2_asset_finish', 'asset': file, 'optional': True}, **check)
    return h


def l12_date_track(pair):
    def h(row, ctx):
        a = {'op': 'v2_tracking', 'a': {'patterns': [DATE_ANY]}, 'b': {'texts': list(ctx.acts)}}
        if pair:
            a.update(pair='below', optional=True)
        return a
    return h


def l12_support_prefix(row, ctx):
    pats = {s: rf'(?<!with\s)(?<!with\s\s)\b{re.escape(s)}\b' for s in l12_supports(ctx).values()}
    return {'op': 'v2_text_absent', 'patterns': pats}


def l12_inside_poster(row, ctx):
    texts = list(ctx.acts) + list(l12_supports(ctx).values()) + [t for t in (ctx.licence, ctx.access) if t]
    return {'op': 'v2_inside_all', 'texts': texts, 'patterns': [DATE_ANY]}


def l12_support_smaller(row, ctx):
    return {'op': 'v2_all_of', 'checks': [{'op': 'v2_relation', 'rel': 'smaller', 'a': s, 'b': [act], 'optional': True}
                                          for act, s in l12_supports(ctx).items()]}


# ------------------------------------------------------------------ VECTOR-04 and MOTION-11

V04_GROUNDS = ['#C8A97E', '#F3E7D3']
BAGS = ['meridian_bag_moth.jpg', 'meridian_bag_pourover.jpg', 'meridian_bag_ridgeline.jpg']


def v04_built_from(photo):
    return lambda row, ctx: {'op': 'v2_built_from', 'photo': photo, 'others': [b for b in BAGS if b != photo], 'grounds': V04_GROUNDS}


def v04_ink(*names):
    return lambda row, ctx: {'op': 'v2_main_ink', 'hexes': [palette(ctx, n) for n in names], 'grounds': V04_GROUNDS}


def m11_capture(row, ctx):
    n = int(row['values']['2'])
    caps = [f'staticfox_captures/staticfox_capture_0{i}.mp4' for i in range(1, 7)]
    return {'op': 'v2_from_capture', 'capture': caps[n - 1], 'others': [c for i, c in enumerate(caps, 1) if i != n]}


# ------------------------------------------------------------------ the rule table

def const(a):
    return lambda row, ctx: dict(a)


R2 = {
    # PHOTO-04
    ('PHOTO-04', 'R005'): p04_rate,
    ('PHOTO-04', 'R006'): p04_rate,
    ('PHOTO-04', 'R007'): p04_sleeps,
    ('PHOTO-04', 'R039'): lambda row, ctx: {'op': 'v2_text_on_ground', 'all_text': True, 'grounds': [palette(ctx, 'Verranza Blue')],
                                            'colors': [palette(ctx, 'Lime Wash')]},
    ('PHOTO-04', 'R059'): const({'op': 'v2_style_lines', 'whole_lines': HOUSES + [h.split()[-1] for h in HOUSES], 'optional': False,
                                 'family': 'Cormorant Garamond', 'weight': 'Light', 'except_digits': True}),
    ('PHOTO-04', 'R061'): lambda row, ctx: {'op': 'v2_initial_ratio', 'heading': q(row['values']['1']), 'ratio': 2.0},
    ('PHOTO-04', 'R062'): const({'op': 'v2_figures', 'font_not': 'Cormorant Garamond'}),
    ('PHOTO-04', 'R070'): const({'op': 'v2_figures', 'tabular': True, 'lines_pattern': P04_KINDS['rate'] + r'|\bnights?\b|\bsleeps?\b'}),
    ('PHOTO-04', 'R076'): const({'op': 'v2_figures', 'lining': True, 'lines_pattern': P04_KINDS['rate']}),
    ('PHOTO-04', 'R085'): const({'op': 'v2_placed_opacity', 'asset': 'verranza_monogram_transparent.png'}),
    ('PHOTO-04', 'R088'): const({'op': 'v2_figures', 'same_size': True}),
    ('PHOTO-04', 'R116'): p04_sections(above=True),
    ('PHOTO-04', 'R117'): lambda row, ctx: {'op': 'v2_position', 'a': {'text': q(row['values']['1'])},
                                            'b': {'pattern': r'(?:EUR|€)\s?\d|\d\s?(?:EUR|€)|/\s*night|per night'}, 'rel': 'above'},
    ('PHOTO-04', 'R119'): p04_sections(same_order=True),
    ('PHOTO-04', 'R121'): p04_sections(larger=True),
    ('PHOTO-04', 'R122'): p04_sections(same_labels=True),
    # PHOTO-06
    ('PHOTO-06', 'R018'): p06_names,
    ('PHOTO-06', 'R027'): p06_accession,
    ('PHOTO-06', 'R082'): p06_name_larger,
    # PHOTO-08
    ('PHOTO-08', 'R008'): p08_action(None),
    ('PHOTO-08', 'R016'): p08_action('Meridian Motors'),
    ('PHOTO-08', 'R017'): p08_action('Portland, Maine'),
    ('PHOTO-08', 'R075'): p08_roundel,
    ('PHOTO-08', 'R077'): p08_roundel,
    ('PHOTO-08', 'R158'): p08_title,
    # PHOTO-10
    ('PHOTO-10', 'R002'): const({'op': 'v2_text_absent', 'texts': [c for c in COLOURWAYS if c not in ('Moss', 'Fern')]}),
    ('PHOTO-10', 'R009'): const({'op': 'v2_spelled', 'names': STYLES}),
    ('PHOTO-10', 'R015'): const({'op': 'v2_paired', 'anchor': ['Heavyweight Tee'], 'whole_line': False, 'kind': rf'\b(?:{"|".join(COLOURWAYS)})\b',
                                 'value': {'regex': r'\b(?:Moss|Fern)\b'}, 'where': 'beside', 'empty_ok': True, 'optional': True}),
    ('PHOTO-10', 'R027'): const({'op': 'v2_text_absent', 'texts': COLOURWAYS}),
    ('PHOTO-10', 'R103'): lambda row, ctx: ({'op': 'v2_largest_text', 'text': p10_style_name(row['output_id']), 'except': ['NORTHGROVE']}
                                            if p10_style_name(row['output_id']) else None),
    # PHOTO-20
    ('PHOTO-20', 'R002'): const({'op': 'v2_inside_all', 'texts': ['Astrid Vellacourt', 'Vellacourt & Sund']}),
    ('PHOTO-20', 'R021'): lambda row, ctx: {'op': 'v2_followed_by', 'a': q(row['values']['1']), 'b': q(row['values']['2'])},
    ('PHOTO-20', 'R027'): p20_below_portrait,
    ('PHOTO-20', 'R059'): lambda row, ctx: {'op': 'v2_mark', 'colour': palette(ctx, 'Ochre'), 'solid': True},
    ('PHOTO-20', 'R062'): lambda row, ctx: ({'op': 'v2_text_on_ground', 'texts': ['Astrid Vellacourt', p20_rec(ctx, row)['Talk Title']], 'optional': False,
                                             'grounds': [palette(ctx, 'Warm Neutral'), palette(ctx, 'Bone')], 'colors': [palette(ctx, 'Vellacourt Ink')]}
                                            if p20_rec(ctx, row) else None),
    ('PHOTO-20', 'R063'): lambda row, ctx: {'op': 'v2_text_on_ground', 'all_text': True, 'grounds': [palette(ctx, 'Deep Ground'), palette(ctx, 'Vellacourt Ink')],
                                            'colors': [palette(ctx, 'Warm Neutral'), palette(ctx, 'Bone')]},
    ('PHOTO-20', 'R069'): p20_event_date_ground(False),
    ('PHOTO-20', 'R070'): p20_event_date_ground(True),
    ('PHOTO-20', 'R082'): lambda row, ctx: {'op': 'v2_style_lines', 'texts': p20_events(ctx), 'patterns': [DATE_ANY + r'|\b20\d\d-\d\d-\d\d\b'],
                                            'optional': True, 'family': 'Inter', 'weight': 'Regular'},
    ('PHOTO-20', 'R092'): p20_monogram_position(False),
    ('PHOTO-20', 'R094'): p20_monogram_position(True),
    ('PHOTO-20', 'R095'): lambda row, ctx: {'op': 'v2_mark', 'colour': palette(ctx, 'Ochre'), 'min_mm': 18},
    # PHOTO-24
    ('PHOTO-24', 'R008'): p24_movement('LM-02'),
    ('PHOTO-24', 'R009'): p24_movement('LM-03'),
    ('PHOTO-24', 'R011'): p24_movement('LM-01'),
    ('PHOTO-24', 'R012'): lambda row, ctx: {'op': 'v2_paired', 'anchor': [row['values']['1']], 'rivals': [r for r in REFS if r != row['values']['1']],
                                            'kind': r'\bLM-\d{2}\b', 'value': {'regex': rf'\b{row["values"]["2"]}\b'}, 'where': 'below'},
    ('PHOTO-24', 'R014'): p24_movement('LM-01', scoped=True),
    ('PHOTO-24', 'R015'): const({'op': 'v2_description', 'trigger': r'\bLM-0\d\b',
                                 'scope_map': {r: {'required': [rf'\b{c}\b'], 'forbidden': [rf'\bLM-0(?!{c[-1]})\d\b']} for r, c in REFS.items()}}),
    ('PHOTO-24', 'R016'): const({'op': 'v2_description', 'trigger': MOVEMENT, 'scope_map': {r: CALIBER[c] for r, c in REFS.items()}}),
    ('PHOTO-24', 'R018'): p24_movement('LM-02', scoped=True),
    ('PHOTO-24', 'R019'): p24_movement('LM-03', scoped=True),
    ('PHOTO-24', 'R030'): const({'op': 'v2_text_present', 'expected': [TIMING], 'if_any': r'timed by hand|regulated to the result|named regulator'}),
    ('PHOTO-24', 'R036'): const({'op': 'v2_text_present', 'expected': [TIMING]}),
    ('PHOTO-24', 'R058'): lambda row, ctx: {'op': 'v2_text_on_ground', 'all_text': True, 'grounds': ['photo'],
                                            'colors': [palette(ctx, 'Bone cream'), palette(ctx, 'Warm near-black')]},
    ('PHOTO-24', 'R072'): const({'op': 'v2_style_lines', 'texts': [TIMING], 'family': 'Inter', 'weight': 'Regular'}),
    ('PHOTO-24', 'R083'): const({'op': 'v2_style_lines', 'whole_lines': ['LUNARA', 'CHRONOMETRY', 'LUNARA CHRONOMETRY'], 'optional': True,
                                 'family': 'Cormorant Garamond', 'weight': 'Medium'}),
    ('PHOTO-24', 'R089'): const({'op': 'v2_style_lines', 'font_family': 'Cormorant Garamond', 'optional': True, 'caps': True}),
    ('PHOTO-24', 'R094'): const({'op': 'v2_stacked', 'top': 'Lunara', 'bottom': 'Chronometry', 'stack': True, 'optional': True}),
    ('PHOTO-24', 'R112'): lambda row, ctx: {'op': 'v2_all_of', 'checks': [{'op': 'v2_relation', 'rel': 'larger', 'a': ref, 'b': [r['serial'], r['dial_finish']],
                                                                           'optional': True} for ref, r in p24_register(ctx).items()]},
    ('PHOTO-24', 'R113'): const({'op': 'v2_size_vs', 'rel': 'larger', 'a': ['Lunara', 'Chronometry'], 'b': list(REFS)}),
    ('PHOTO-24', 'R115'): lambda row, ctx: {'op': 'v2_size_vs', 'rel': 'larger', 'a': list(REFS),
                                            'b': sorted({v for r in p24_register(ctx).values() for v in (r['dial_finish'], r['case_metal'])}) +
                                            [{'regex': r'\bLM-0\d\b'}]},
    ('PHOTO-24', 'R116'): lambda row, ctx: {'op': 'v2_relation', 'rel': 'larger', 'a': 'Lunara', 'b': [q(row['values']['1'])], 'optional': True},
    # PHOTO-26
    ('PHOTO-26', 'R015'): lambda row, ctx: {'op': 'v2_page_size', 'width_mm': float(row['values']['1']), 'height_mm': float(row['values']['2']),
                                            'no_bleed': True},
    ('PHOTO-26', 'R032'): lambda row, ctx: {'op': 'v2_text_on_ground', 'all_text': True,
                                            'grounds': [palette(ctx, n) for n in ('Warm Paper Ground', 'Oatmeal Glaze', 'Soft Clay')],
                                            'colors': [palette(ctx, 'Stoneware Charcoal')], 'foot_ok': [palette(ctx, 'Soft Clay')]},
    ('PHOTO-26', 'R033'): lambda row, ctx: {'op': 'v2_text_on_ground', 'all_text': True, 'grounds': [palette(ctx, 'Indigo Dye')],
                                            'colors': [palette(ctx, 'Warm Paper Ground')]},
    ('PHOTO-26', 'R042'): const({'op': 'v2_style_lines', 'patterns': P26_LINES, 'optional': True, 'family': 'Inter', 'weight': 'Regular'}),
    ('PHOTO-26', 'R049'): const({'op': 'v2_style_lines', 'patterns': P26_LINES, 'optional': True, 'size': 8.5}),
    ('PHOTO-26', 'R051'): const({'op': 'v2_style_lines', 'patterns': P26_LINES, 'optional': True, 'size': 8.5}),
    ('PHOTO-26', 'R052'): lambda row, ctx: {'op': 'v2_style_lines', 'whole_lines': p26_products(), 'optional': True, 'max_size': 16},
    ('PHOTO-26', 'R055'): lambda row, ctx: {'op': 'v2_bare_below', 'names': p26_products(), 'min_mm': 40},
    ('PHOTO-26', 'R072'): lambda row, ctx: {'op': 'v2_size_pairs', 'names': p26_products(), 'kind': r'[$€£]\s?\d'},
    ('PHOTO-26', 'R073'): lambda row, ctx: {'op': 'v2_size_pairs', 'names': p26_products(), 'kind': r'[$€£]\s?\d'},
    # PHOTO-28
    ('PHOTO-28', 'R003'): p28_pictured_class,
    ('PHOTO-28', 'R004'): const({'op': 'v2_pictured', 'photos': PHOTOS, 'then': {'op': 'v2_text_present', 'expected': ['{name}'], 'any_case': True}}),
    ('PHOTO-28', 'R008'): const({'op': 'v2_all_of', 'checks': [
        {'op': 'v2_text_absent', 'patterns': {'street number': r'\b\d+[A-Za-z]?\s+Calloway\s+Row', 'postcode': r'\b\d{5}(?:-\d{4})?\b|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b'}},
        {'op': 'v2_text_absent', 'patterns': {'words after the street': r'Calloway\s+Row\s*,\s*[A-Za-z]+'}, 'found_is': 'person'}]}),
    ('PHOTO-28', 'R011'): const({'op': 'v2_names_full', 'names': list(INSTRUCTORS)}),
    ('PHOTO-28', 'R012'): p28_class_beside('Priya Anand'),
    ('PHOTO-28', 'R023'): p28_price(['Flow', 'Prenatal'], 36),
    ('PHOTO-28', 'R024'): p28_price(['Strength'], 38),
    ('PHOTO-28', 'R027'): p28_class_beside('Dana Osei'),
    ('PHOTO-28', 'R029'): p28_class_beside('Tomas Reyes'),
    ('PHOTO-28', 'R030'): p28_class_beside('Yuki Sato'),
    ('PHOTO-28', 'R031'): p28_class_beside('Nadia Haddad'),
    ('PHOTO-28', 'R034'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_inside_all', 'texts': ['Verda']},
                                                               {'op': 'v2_inside_all', 'texts': ['Verda Reformer Studio'], 'optional': True}]}),
    ('PHOTO-28', 'R050'): lambda row, ctx: {'op': 'v2_names_by_photo', 'photo': row['values']['1'], 'names': list(INSTRUCTORS),
                                            'expected': row['values']['2']},
    ('PHOTO-28', 'R090'): const({'op': 'v2_line_count', 'text': 'Verda', 'max_lines': 1}),
    # LAYOUT-15
    ('LAYOUT-15', 'R021'): lambda row, ctx: {'op': 'v2_no_added_detail', 'asset': row['values']['3']},
    ('LAYOUT-15', 'R058'): lambda row, ctx: {'op': 'v2_same_photo', 'asset': row['values']['1'], 'min_ncc': 0.9},
    # LAYOUT-12
    ('LAYOUT-12', 'R002'): l12_paired_date,
    ('LAYOUT-12', 'R005'): l12_paired_support,
    ('LAYOUT-12', 'R008'): const({'op': 'v2_no_blank_page'}),
    ('LAYOUT-12', 'R015'): l12_weekday,
    ('LAYOUT-12', 'R017'): l12_chart,
    ('LAYOUT-12', 'R018'): l12_capacity('standing', 250),
    ('LAYOUT-12', 'R019'): l12_capacity('attendance', 183),
    ('LAYOUT-12', 'R020'): const({'op': 'v2_shows_deliverable', 'deliverable': 'deliverables/poster-direction-type-led.pdf'}),
    ('LAYOUT-12', 'R024'): l12_wordmark('umbra_sable_wordmark_transparent.png', 'Sable Quartet', 'with_text'),
    ('LAYOUT-12', 'R025'): l12_wordmark('umbra_meridian_wordmark_transparent.png', 'Meridian Brass', 'with_text'),
    ('LAYOUT-12', 'R026'): l12_support_prefix,
    ('LAYOUT-12', 'R027'): const({'op': 'v2_shows_deliverable', 'deliverable': 'deliverables/poster-direction-image-led.pdf'}),
    ('LAYOUT-12', 'R028'): const({'op': 'v2_shows_deliverable', 'deliverable': 'deliverables/poster-direction-graphic-led.pdf'}),
    ('LAYOUT-12', 'R032'): l12_wordmark('umbra_sable_wordmark_transparent.png', 'Sable Quartet', 'with_text'),
    ('LAYOUT-12', 'R033'): l12_wordmark('umbra_meridian_wordmark_transparent.png', 'Meridian Brass', 'with_text'),
    ('LAYOUT-12', 'R036'): l12_capacity('cabaret', 120),
    ('LAYOUT-12', 'R037'): l12_capacity('occupancy', 73, '%'),
    ('LAYOUT-12', 'R038'): l12_inside_poster,
    ('LAYOUT-12', 'R039'): lambda row, ctx: ({'op': 'v2_text_inside', 'texts': [ctx.records[row['output_id']]['price']]}
                                             if ctx.records.get(row['output_id'], {}).get('price') else None),
    ('LAYOUT-12', 'R059'): lambda row, ctx: {'op': 'v2_text_present', 'expected': [date_rx(row['values']['1'], 'Oct')],
                                             'forbidden': [date_rx(row['values']['3'], 'Oct')]},
    ('LAYOUT-12', 'R077'): l12_style(colors=['#E9E4D8']),
    ('LAYOUT-12', 'R086'): l12_style(colors=['#E9E4D8']),
    ('LAYOUT-12', 'R101'): l12_wordmark('umbra_sable_wordmark_transparent.png', 'Sable Quartet', {'ink': '#E9E4D8'}),
    ('LAYOUT-12', 'R105'): lambda row, ctx: {'op': 'v2_text_on_ground', 'texts': list(ctx.acts), 'ground_must': ['#0E0E10'], 'optional': False},
    ('LAYOUT-12', 'R106'): lambda row, ctx: {'op': 'v2_text_on_ground', 'texts': list(ctx.acts), 'ground_must': ['#0E0E10'], 'optional': True},
    ('LAYOUT-12', 'R110'): l12_wordmark('umbra_meridian_wordmark_transparent.png', 'Meridian Brass', {'ink': '#E9E4D8'}),
    ('LAYOUT-12', 'R111'): l12_wordmark('umbra_sable_wordmark_transparent.png', 'Sable Quartet', {'ground': '#0E0E10'}),
    ('LAYOUT-12', 'R112'): l12_wordmark('umbra_meridian_wordmark_transparent.png', 'Meridian Brass', {'ground': '#0E0E10'}),
    ('LAYOUT-12', 'R115'): l12_style(family='Sora', weight='ExtraBold'),
    ('LAYOUT-12', 'R135'): l12_style(caps=True),
    ('LAYOUT-12', 'R147'): l12_date_track(False),
    ('LAYOUT-12', 'R150'): l12_date_track(True),
    ('LAYOUT-12', 'R153'): lambda row, ctx: {'op': 'v2_directly_above', 'texts': list(ctx.acts), 'pattern': DATE_ANY},
    ('LAYOUT-12', 'R154'): lambda row, ctx: {'op': 'v2_tracking', 'a': {'patterns': [r'\bDOORS?\b']}, 'b': {'texts': list(l12_supports(ctx).values())},
                                             'optional': True},
    ('LAYOUT-12', 'R158'): lambda row, ctx: {'op': 'v2_directly_above', 'texts': list(ctx.acts), 'pattern': DATE_ANY, 'optional': True},
    ('LAYOUT-12', 'R161'): lambda row, ctx: {'op': 'v2_directly_above', 'texts': [ctx.records[row['output_id']]['headline']], 'pattern': DATE_ANY}
                                            if ctx.records.get(row['output_id'], {}).get('headline') else None,
    ('LAYOUT-12', 'R164'): lambda row, ctx: {'op': 'v2_all_of', 'checks': [{'op': 'v2_line_count', 'text': x, 'max_lines': 2, 'optional': True} for x in ctx.acts]},
    ('LAYOUT-12', 'R176'): l12_support_smaller,
    # VECTOR-04
    ('VECTOR-04', 'R016'): const({'op': 'v2_svg_size', 'long_mm': 55, 'tol': 0.5}),
    ('VECTOR-04', 'R019'): const({'op': 'v2_svg_no_cutline'}),
    ('VECTOR-04', 'R033'): v04_built_from('meridian_bag_pourover.jpg'),
    ('VECTOR-04', 'R034'): v04_built_from('meridian_bag_ridgeline.jpg'),
    ('VECTOR-04', 'R040'): v04_built_from('meridian_bag_moth.jpg'),
    ('VECTOR-04', 'R043'): const({'op': 'v2_no_halftone', 'max_dots': 40}),
    ('VECTOR-04', 'R055'): v04_ink('Ash Green'),
    ('VECTOR-04', 'R056'): v04_ink('Brick Red'),
    ('VECTOR-04', 'R068'): v04_ink('Roast Brown'),
    ('VECTOR-04', 'R069'): v04_ink('Roast Brown', 'Ash Green', 'Brick Red'),
    ('VECTOR-04', 'R090'): const({'op': 'v2_svg_glyph_ratio', 'glyph': '&', 'family': 'DM Serif Display', 'ratio': 1.6}),
    # MOTION-11
    ('MOTION-11', 'R018'): lambda row, ctx: {'op': 'v2_text_inside', 'texts': [q(row['values']['1']).split(' - ', 1)[-1]]},
    ('MOTION-11', 'R033'): m11_capture,
    ('MOTION-11', 'R119'): const({'op': 'v2_largest_last_frame', 'text': 'STATIC FOX'}),
}

HOW = {
    'v2_paired': 'Reads where each value stands and checks the value that belongs to this name (by its section, column or line) is the expected one.',
    'v2_followed_by': 'Reads the text and checks the second text comes directly after the first.',
    'v2_text_on_ground': 'Reads each line\'s colour from the PDF and the colour behind it from the rendered page, and checks the pairing.',
    'v2_position': 'Finds both elements (by their colour, the supplied file, the placed photo or the text) and compares their positions.',
    'v2_mark': 'Finds the shapes drawn in the mark\'s colour and measures them or checks they are drawn solid.',
    'v2_page_size': 'Reads every page\'s size from the PDF.',
    'v2_no_blank_page': 'Checks every page of the PDF carries text, a picture or a shape.',
    'v2_bare_below': 'Measures the clear paper below the heading on each single-product page.',
    'v2_tracking': 'Measures letter spacing from the PDF\'s glyph positions.',
    'v2_description': 'Reads the text; where a description of this kind appears, checks it carries the right terms and no contradicting ones.',
    'v2_names_full': 'Reads the text and checks every name that appears is given in full.',
    'v2_spelled': 'Reads the text and flags any name close to, but not exactly, the listed spelling.',
    'v2_directly_above': 'Reads the text and checks the line directly above each name is the expected kind of line.',
    'v2_stacked': 'Reads the text and checks how the two words of the wordmark are set: stacked, or on one line.',
    'v2_inside_all': 'Checks each named text lies fully inside the page or image.',
    'v2_figures': 'Reads the figures\' fonts, sizes and glyph shapes from the PDF.',
    'v2_initial_ratio': 'Reads the font sizes of the heading\'s letters from the PDF.',
    'v2_sections': 'Reads each house section of the PDF: positions, sizes, order and labels of its entries.',
    'v2_placed_opacity': 'Finds the supplied picture in the PDF and reads the transparency and blend mode it is drawn with.',
    'v2_pictured': 'Finds which supplied photo is shown, then checks the text for that person.',
    'v2_names_by_photo': 'Finds the supplied photo, then reads the names standing beside it.',
    'v2_same_photo': 'Finds the supplied photo and measures how closely the placed pixels match it.',
    'v2_no_added_detail': 'Finds the supplied photo in the placed picture and checks it is not enlarged or extended beyond the file.',
    'v2_mark_with_text': 'Finds the supplied wordmark, then checks the act name is also typeset beside it.',
    'v2_asset_finish': 'Finds the supplied wordmark and reads its ink and the ground around it.',
    'v2_shows_deliverable': 'Renders the delivered poster and searches the deck for it.',
    'v2_ground_mark': 'Finds the mark, reads the ground around it, and checks its ink on that ground.',
    'v2_svg_size': 'Reads the SVG\'s physical size and measures the drawn artwork.',
    'v2_svg_no_cutline': 'Reads the SVG\'s layers and strokes for a cut line drawn into the artwork.',
    'v2_main_ink': 'Renders the artwork and finds the colour covering most of it, grounds left out.',
    'v2_svg_glyph_ratio': 'Reads the SVG\'s live text sizes for the glyph and the capitals beside it.',
    'v2_built_from': 'Compares the drawing\'s silhouette with the printed motif of each supplied photo.',
    'v2_no_halftone': 'Counts tiny dot shapes in the SVG.',
    'v2_from_capture': 'Searches the thumbnail for frames of each capture video.',
    'v2_largest_last_frame': 'Reads the held last frame of the video and compares text sizes.',
    'v2_style_lines': 'Reads the font, size or letter case of the selected lines from the PDF.',
    'v2_size_vs': 'Compares the text sizes (font size in PDFs, letter height on images).',
    'v2_size_pairs': 'Pairs each name with its own value and compares their sizes.',
}


def convert(tid, rid, row, ctx):
    h = R2.get((tid, rid))
    return h(row, ctx) if h else None
