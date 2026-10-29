"""Round 4 type conversions (2026-10-28): PHOTO-04 R080, PHOTO-06 R072 to R076, R083, R084, PHOTO-08 R091 to R093,
PHOTO-24 R069 and LAYOUT-12 R162. R4 = {(task, rule): handler(row, ctx) -> assertion or None}; HOW = {op: sentence}.
Ops live in tools/auto_verifier/ops_r4_type.py.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- part A
def pa_p08_price(test):
    def h(row, ctx):
        rec = (ctx.records.get(row['output_id']) or {})
        if not rec.get('asking_price'):
            return None
        return {'op': 'v2_price_figures_r4t', 'price': rec['asking_price'], 'test': test}
    return h


def pa_p06(test, **kw):
    def h(row, ctx):
        m = re.search(r'hollis-scan-(\d\d)', row['output_id'])
        return dict({'op': 'v2_caption_r4t', 'test': test, 'asset': f'hollis_scan_{m.group(1)}.jpg'}, **kw) if m else None
    return h


def pa_p04_c(row, ctx):
    m = re.search(r'opening “C” of “(Casa \w+)”', row['check'])
    return {'op': 'v2_cap_ratio_r4t', 'line': m.group(1), 'word': 1, 'ratio': 2.0} if m else None


P06_PLACE = r'\b(?:18|19|20)\d\d\s*/\s*[A-Z][a-z]+'

_R4_A = {
    ('PHOTO-08', 'R091'): pa_p08_price('lining'),
    ('PHOTO-08', 'R092'): pa_p08_price('dollar_ratio'),
    ('PHOTO-08', 'R093'): pa_p08_price('dollar_top'),
    ('PHOTO-08', 'R115'): lambda row, ctx: ({'op': 'v2_rule_under_r4t', 'price': ctx.records[row['output_id']]['asking_price']}
                                            if (ctx.records.get(row['output_id']) or {}).get('asking_price') else None),
    ('PHOTO-04', 'R080'): pa_p04_c,
    # the offer price's figures: every figure on the hero being a lining figure settles it (v2_lining_r4t, part B)
    ('PHOTO-04', 'R075'): lambda row, ctx: {'op': 'v2_pass_only_r4t', 'check': {'op': 'v2_lining_r4t', 'pass_tol': 0.06, 'fail_short': 0.85,
                                                                              'fail_drop': 0.12, 'photo_digit_max': 0.03}},
    ('PHOTO-06', 'R072'): pa_p06('numeral_margin'),
    ('PHOTO-06', 'R073'): pa_p06('rule_single'),
    ('PHOTO-06', 'R074'): pa_p06('numeral_larger'),
    ('PHOTO-06', 'R075'): pa_p06('numeral_top'),
    ('PHOTO-06', 'R076'): pa_p06('rule_edges'),
    ('PHOTO-06', 'R083'): pa_p06('caption_area'),
    ('PHOTO-06', 'R084'): pa_p06('place_below', place=P06_PLACE),
}

_HOW_A = {
    'v2_price_figures_r4t': 'Finds the price by OCR, splits its figures and dollar sign into ink shapes and compares their heights, '
                            'baselines and tops.',
    'v2_rule_under_r4t': 'Finds the price by OCR and the first long run of ink under it, and counts the rows of that rule.',
    'v2_pass_only_r4t': 'Runs a wider check (every figure on the file) and passes only when it passes; anything else goes to a person.',
    'v2_cap_ratio_r4t': 'Splits the line into letter shapes and divides the height of its opening letter by the height of the '
                        'capital that starts the later word.',
    'v2_caption_r4t': 'Finds the picture block, the rules and the first text line under it from ink, and measures the numeral, '
                      'the name, the rule and the caption block against the picture.',
}


# ---------------------------------------------------------------- part B
def pb_lining_rule(row, ctx):
    return {'op': 'v2_lining_r4t', 'pass_tol': 0.06, 'fail_short': 0.85, 'fail_drop': 0.12, 'photo_digit_max': 0.03}


_R4_B = {
    ('PHOTO-24', 'R069'): pb_lining_rule,
}

_HOW_B = {
    'v2_lining_r4t': 'Measures every figure glyph (PDF: rendered glyph ink; images: ink pieces inside each word OCR reads) '
                     'against the tallest capital or figure beside it and their common baseline.',
}


# ---------------------------------------------------------------- part L12
L12_ARCHIVO = [['Archivo Narrow', [400, 500, 600, 700]]]


def l12_rec(row, ctx):
    return ctx.records.get(row['output_id']) or {}


def l12_r162(row, ctx):
    """The door line (DOORS <door>, SETS <set>) against the support line (with <support>), from the post's record."""
    v = l12_rec(row, ctx)
    if not (v.get('support') and v.get('door') and v.get('set')):
        return None
    door = v['door'].replace('&nbsp;', ' ')
    return {'op': 'v2_track_vs_r4t', 'a': {'text': f"DOORS {door}, SETS {v['set']}"}, 'b': {'text': f"with {v['support']}"},
            'fonts_a': L12_ARCHIVO, 'fonts_b': L12_ARCHIVO}


_R4_L12 = {('LAYOUT-12', 'R162'): l12_r162}

_HOW_L12 = {'v2_track_vs_r4t': 'Finds both lines by OCR, takes each letter\'s ink centre and fits the letter positions to the '
                          'font\'s own letter widths to read each line\'s letter spacing, then compares the two lines.'}


R4 = {**_R4_A, **_R4_B, **_R4_L12}
HOW = {**_HOW_A, **_HOW_B, **_HOW_L12}
