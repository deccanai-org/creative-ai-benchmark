"""Round 5 code conversions (2026-10-29): close calls (rules whose code already decided some rows with no wrong answer)
that code now settles with full confidence. R5 = {(task, rule): handler(row, ctx) -> assertion or None};
HOW = {op: sentence}. Ops live in tools/auto_verifier/ops_r5_code.py (names end _r5c). Several handlers wrap the
earlier conversion of the same rule unchanged and add the one decision it could not make.

Converted: PHOTO-04 R080 (the dot of an i split the letter count), PHOTO-06 R058 (the keyline round the photograph
is one ring-shaped piece), PHOTO-08 R047 (the price set in old-style figures is read at 60% confidence, its figures
matching the record's price exactly) and R060 (labels set exactly in Graphite or Steel Grey), PHOTO-10 R063 (no
Club Navy anywhere on the image) and R079 (the fine print line read below 80%), PHOTO-24 R048 and R055 (the small
reference label OCR missed, read by the round-4 multi-pass reading) and R069 (a faint serial confirmed by the
record; marks that are the photograph's own pixels), PHOTO-28 R068 (a short label in Sage on a page with no body
size). The rules left out and why are in the round-5 code report.
"""
from __future__ import annotations

import re

import round3_photo_a as ra
import round3_photo_b as rb
from round3_photo_a import CNAVY, GRAPHITE, LINEN, NAVY, SGREY, TEAL, p06_src


def pal(ctx, *names):
    return [ctx.palette[n] for n in names]


def earlier(task, rule, table):
    """The earlier (round 3) assertion for the same row, wrapped unchanged by the round-5 op."""
    return lambda row, ctx: table[(task, rule)](row, ctx)


def p04_c(row, ctx):
    m = re.search(r'opening “C” of “(Casa \w+)”', row['check'])
    return {'op': 'v2_cap_ratio_r5c', 'line': m.group(1), 'word': 1, 'ratio': 2.0} if m else None


def p06_keyline(row, ctx):
    src = p06_src(row)
    return {'op': 'v2_keyline_only_r5c', 'hexes': [LINEN], 'photo': src} if src else None


def p08_price(row, ctx):
    a = ra.R3[('PHOTO-08', 'R047')](row, ctx)
    # the price's figures are old-style (Georgia): OCR reads them at 60 to 85% confidence; a line whose figures
    # match the record's price exactly is the price, and its colour does not depend on every figure being read
    return dict(a, min_conf=60) if a else None


def p08_labels(row, ctx):
    a = ra.R3[('PHOTO-08', 'R060')](row, ctx)
    return {'op': 'v2_named_colour_r5c', 'check': a, 'colors': [NAVY], 'others': [GRAPHITE, TEAL, SGREY]} if a else None


def p10_navy(row, ctx):
    a = ra.R3[('PHOTO-10', 'R063')](row, ctx)
    return {'op': 'v2_ground_absent_r5c', 'grounds': [CNAVY], 'then': a} if a else None


def p24_labels(rule, colours):
    def h(row, ctx):
        a = rb.R3[('PHOTO-24', rule)](row, ctx)
        if a is None:
            return None
        # the LUNARA CHRONOMETRY wordmark and the reference names (headings) are never labels
        out = {'op': 'v2_small_labels_r5c', 'check': a, 'extra_ocr': True, 'not_labels': rb.P24_MARK + rb.P24_REFS}
        if colours:
            out['label_colors'] = pal(ctx, *colours)
        return out
    return h


def p28_labels(row, ctx):
    a = rb.R3[('PHOTO-28', 'R068')](row, ctx)
    return {'op': 'v2_small_labels_r5c', 'check': a, 'label_colors': pal(ctx, 'Soft Ink', 'Sage'), 'max_words': 3,
            'not_labels': ['Verda', 'VERDA REFORMER STUDIO']} if a else None


def p24_lining(row, ctx):
    """Every figure a lining figure (round 4's limits), with the record's serial and caliber confirming a
    low-confidence read, and marks that are the supplied photo's own pixels left out."""
    rec = ctx.records.get(row['output_id']) or {}
    a = {'op': 'v2_lining_r5c', 'pass_tol': 0.06, 'fail_short': 0.85, 'fail_drop': 0.12, 'photo_digit_max': 0.03,
         'known': [rec[k] for k in ('serial', 'caliber') if rec.get(k)]}
    if not row['file'].endswith('.pdf'):
        a['photos'] = rb.p24_photos(row, ctx)
    return a


def p10_fine_smaller(row, ctx):
    """Round 3's two readings of fine print (narrow and broad; both must agree), with lines picked at 60%."""
    a = ra.R3[('PHOTO-10', 'R079')](row, ctx)
    return dict(a, checks=[dict(c, op='v2_sizes_vs_r5c', min_conf=60) for c in a['checks']])


R5 = {
    ('PHOTO-04', 'R080'): p04_c,
    ('PHOTO-10', 'R079'): p10_fine_smaller,
    ('PHOTO-24', 'R069'): p24_lining,
    ('PHOTO-06', 'R058'): p06_keyline,
    ('PHOTO-08', 'R047'): p08_price,
    ('PHOTO-08', 'R060'): p08_labels,
    ('PHOTO-10', 'R063'): p10_navy,
    ('PHOTO-24', 'R048'): p24_labels('R048', ('Warm near-black', 'Tempered steel', 'Oxblood')),
    ('PHOTO-24', 'R055'): p24_labels('R055', ()),
    ('PHOTO-28', 'R068'): p28_labels,
}

HOW = {
    'v2_cap_ratio_r5c': 'Splits the line into letter shapes, joining the dot of an i or j to its letter, and divides the height of '
                        'its opening letter by the height of the capital that starts the later word.',
    'v2_keyline_only_r5c': 'Finds the supplied photo, then checks every piece of the colour outside it runs along its edge as a line '
                           'no thicker than a hairline.',
    'v2_named_colour_r5c': 'Reads each selected text line by OCR and the colour of its letters; a line set exactly in another '
                           'palette colour fails, anything unclear goes to a person.',
    'v2_ground_absent_r5c': 'Looks for the ground colour in every pixel of the image; with none there, no type sits on it; '
                            'otherwise reads each text line on that ground and the colour of its letters.',
    'v2_small_labels_r5c': 'Reads each text line and the colour of its letters and ground; a small line in capitals (a label) may use '
                           'the label colours, and a label OCR missed is read again from a contrast-stretched copy.',
    'v2_lining_r5c': 'Measures every figure glyph against the tallest capital or figure beside it and their common baseline; a '
                     'serial read faintly counts when it matches the record exactly, and marks matching the supplied photo are left out.',
    'v2_sizes_vs_r5c': 'Finds the named lines by their words and compares their letter heights.',
}
