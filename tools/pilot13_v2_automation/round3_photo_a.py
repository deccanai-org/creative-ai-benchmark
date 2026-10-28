"""Round 3 conversions for PHOTO-04, PHOTO-06, PHOTO-08 and PHOTO-10 (2026-10-28): colour on images, rules that
needed a definition, and the measurable rules first sorted as judgement.

One handler per (task, rule), taking (row, ctx) and returning an assertion for tools/auto_verifier (round 3 ops in
objective_ops_r3.py and ops_r3_photo_a.py), or None when the row cannot be checked exactly; a rule moves only when
every row converts. Supplied photographs are passed as photos so they are left out of colour reads.

Definitions (the same on every file; see ops_r3_photo_a.py):
- Text roles as in objective_ops_r3._roles. Where a reviewer could read a role more widely, the check runs a narrow
  and a broad reading (v2_agree) and only answers when both agree: body text narrow = the body role, broad = every
  line with lowercase letters and four words or more set under heading size; display lines narrow = the heading
  role, broad = every line set 1 pt or more over the body size (rates left out).
- A label is a line with no lowercase letters; a small label is one no larger than the body size (PDF) or with
  letters no taller than 2.5% of the image height (images).
- A rule or hairline is a shape 2 pt or less across (PDF), or a piece 0.4% of the image's short side or less across
  (images); a ground or panel is an opaque filled area of 2% of the page or more (PDF) or a flat area of 0.3% of the
  image or more (images).
- Gold or metallic: hue 30 to 58 degrees, saturation 0.35 or more, value 0.4 to 0.95 (objective_ops_r3._gold).
"""
from __future__ import annotations

import re

from round2 import q

# ------------------------------------------------------------------ shared

LIME, BLUE, STONE, OLIVE_G, COVE, INK4 = '#EFE9DC', '#24425A', '#C4B5A0', '#6E7355', '#4C7A8C', '#2A2925'


def pal(ctx, *names):
    return [ctx.palette[n] for n in names]


def const(a):
    return lambda row, ctx: dict(a)


def num_rx(value) -> str:
    digits = str(value).replace(',', '').replace('$', '')
    if len(digits) > 3:
        digits = digits[:-3] + r',?\s?' + digits[-3:]
    return rf'(?<![\d,.]){digits}(?![\d]|,\d)'


# ------------------------------------------------------------------ PHOTO-04 villa collection

HOUSES = ['Casa Verranza', 'Casa Oliveto', 'Casa Scogliera']
P04_PHOTOS = [f'{h}_{k}.jpg' for h in ('oliveto', 'scogliera', 'verranza') for k in ('pool', 'terrace', 'bedroom', 'living')] + ['gate_plate.jpg']
P04_ACCENTS = [STONE, OLIVE_G, COVE]
P04_HOUSE_LINE = r'^\s*(?:Casa\s+)?(?:Verranza|Oliveto|Scogliera)\s*$'
P04_RATE = r'(?:EUR|€)\s?\d|\d\s?(?:EUR|€)|/\s*night'
P04_RUNNING = {'select': 'running_below_heading', 'min_words': 4}


def p04_raster(spec):
    return lambda row, ctx: dict(spec, photos=P04_PHOTOS)


def p04_body_style(**want):
    """Body text style: the body role, and every running line of four words or more under heading size."""
    return lambda row, ctx: {'op': 'v2_agree', 'checks': [
        dict({'op': 'v2_role_lines', 'role': 'body', 'optional': False}, **want),
        dict({'op': 'v2_pdf_lines_style', **P04_RUNNING}, **want)]}


P04 = {
    ('PHOTO-04', 'R034'): const({'op': 'v2_no_gold'}),
    ('PHOTO-04', 'R040'): const({'op': 'v2_pdf_colour_roles', 'hexes': P04_ACCENTS, 'text': 'labels'}),
    ('PHOTO-04', 'R041'): p04_raster({'op': 'v2_palette_raster_x', 'hexes': [BLUE, LIME, STONE, OLIVE_G, COVE, INK4], 'photo_touch': True}),
    ('PHOTO-04', 'R042'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_colour_present_raster', 'hexes': [BLUE], 'photos': P04_PHOTOS},
                                                               {'op': 'v2_colour_present_raster', 'hexes': [LIME], 'photos': P04_PHOTOS}]}),
    ('PHOTO-04', 'R044'): p04_raster({'op': 'v2_no_gold'}),
    ('PHOTO-04', 'R045'): p04_raster({'op': 'v2_line_colour_raster', 'all_text': True, 'grounds': [BLUE], 'colors': [LIME], 'optional': True,
                                      'split_gaps': True}),
    ('PHOTO-04', 'R046'): p04_raster({'op': 'v2_colour_roles_raster', 'hexes': P04_ACCENTS, 'allowed': ['thin', 'label']}),
    ('PHOTO-04', 'R047'): const({'op': 'v2_no_overlay', 'photos': P04_PHOTOS[:-1]}),
    ('PHOTO-04', 'R048'): p04_raster({'op': 'v2_grounds_raster', 'hexes': [LIME, BLUE]}),
    # R049 and R050 (heroes): which line is a display line and which is body text is not readable from pixels here (a
    # bold sans standfirst can be either), so these stay with people.
    ('PHOTO-04', 'R051'): const({'op': 'v2_mark_colour_raster', 'asset': 'verranza_monogram_transparent.png', 'pairs': [[BLUE, LIME], [LIME, BLUE]]}),
    ('PHOTO-04', 'R052'): const({'op': 'v2_pdf_no_overlay'}),
    ('PHOTO-04', 'R053'): const({'op': 'v2_pdf_grounds', 'hexes': [LIME, BLUE]}),
    ('PHOTO-04', 'R054'): const({'op': 'v2_agree', 'checks': [
        {'op': 'v2_role_colour_pdf', 'roles': ['heading'], 'patterns': [P04_HOUSE_LINE], 'grounds': [LIME], 'colors': [BLUE]},
        {'op': 'v2_pdf_text_on_grounds', 'select': 'above_body', 'patterns': [P04_HOUSE_LINE], 'except': [P04_RATE], 'grounds': [LIME], 'colors': [BLUE]}]}),
    ('PHOTO-04', 'R055'): const({'op': 'v2_agree', 'checks': [
        {'op': 'v2_role_colour_pdf', 'roles': ['body', 'caption'], 'patterns': [P04_RATE], 'grounds': [LIME], 'colors': [INK4]},
        {'op': 'v2_all_of', 'checks': [
            {'op': 'v2_pdf_text_on_grounds', 'select': ['caption'], 'patterns': [P04_RATE], 'grounds': [LIME], 'colors': [INK4]},
            {'op': 'v2_pdf_text_on_grounds', **P04_RUNNING, 'except': [P04_HOUSE_LINE], 'grounds': [LIME], 'colors': [INK4]}]}]}),
    ('PHOTO-04', 'R056'): lambda row, ctx: ({'op': 'v2_pdf_area_share_pages', 'hexes': P04_ACCENTS, 'max_pct': 5} if row['file'].endswith('.pdf')
                                            else {'op': 'v2_area_share_raster', 'hexes': P04_ACCENTS, 'max_pct': 5, 'photos': P04_PHOTOS}),
    ('PHOTO-04', 'R057'): p04_raster({'op': 'v2_colour_roles_raster', 'hexes': [STONE], 'allowed': ['thin']}),
    ('PHOTO-04', 'R058'): const({'op': 'v2_pdf_colour_roles', 'hexes': [STONE], 'text': 'none'}),
    ('PHOTO-04', 'R060'): p04_body_style(family='Source Sans 3', weight='Regular'),
    ('PHOTO-04', 'R063'): const({'op': 'v2_agree', 'checks': [{'op': 'v2_max_line_chars', 'role': 'body', 'max_chars': 65},
                                                              {'op': 'v2_max_line_chars', **P04_RUNNING, 'max_chars': 65}]}),
    ('PHOTO-04', 'R067'): p04_raster({'op': 'v2_max_line_chars', 'max_chars': 65}),
    ('PHOTO-04', 'R068'): p04_body_style(size=10),
    ('PHOTO-04', 'R069'): p04_body_style(leading=15),
    ('PHOTO-04', 'R073'): const({'op': 'v2_agree', 'checks': [
        {'op': 'v2_pdf_lines_style', 'select': ['heading'], 'except': [P04_HOUSE_LINE, r'^[^a-z]*$'], 'family': 'Cormorant Garamond', 'weight': 'Light', 'except_digits': True},
        {'op': 'v2_pdf_lines_style', 'select': ['heading'], 'except': [P04_HOUSE_LINE], 'family': 'Cormorant Garamond', 'weight': 'Light', 'except_digits': True}]}),
    ('PHOTO-04', 'R074'): const({'op': 'v2_all_of', 'checks': [
        {'op': 'v2_style_lines', 'patterns': [P04_RATE, r'\bsleeps?\b', r'\bmin(?:imum|\.)?\b.*\bnights?\b'], 'optional': True, 'family': 'Source Sans 3', 'weight': 'Regular'},
        {'op': 'v2_role_lines', 'role': 'caption', 'family': 'Source Sans 3', 'weight': 'Regular'}]}),
    # R084 (monogram opacity on an image): opacity cannot be told from a solid colour on pixels alone.
    ('PHOTO-04', 'R120'): const({'op': 'v2_pdf_role_vs_lines', 'role': 'heading', 'names': [r'^\s*Casa\s+(?:Verranza|Oliveto|Scogliera)\s*$']}),
}

# ------------------------------------------------------------------ PHOTO-06 family archive

PAPER, ABLACK, MGREY, LINEN, INK6 = '#F5F1E9', '#191613', '#6F6B64', '#D9D0C1', '#33302B'
P06_PROVENANCE = r'\b(?:studio|kodak|drugstore|print|card|portrait)\b[^/]*\.?\s*$'
P06_PLACE_DATE = r'\b1[89]\d\d\b.*[A-Za-z]{4,}|[A-Za-z]{4,}.*\b1[89]\d\d\b'


def p06_src(row):
    """The supplied scan a deliverable is made from (named in the row, else by its number)."""
    v = (row.get('values') or {}).get('1')
    if v and v.endswith('.jpg'):
        return v
    m = re.search(r'scan-(\d\d)', row['output_id'])
    return f'hollis_scan_{m.group(1)}.jpg' if m else None


def p06(spec):
    def h(row, ctx):
        src = p06_src(row)
        return dict(spec, photos=[src]) if src else None
    return h


def p06_photo(op):
    def h(row, ctx):
        src = p06_src(row)
        return {'op': op, 'photo': src} if src else None
    return h


P06 = {
    ('PHOTO-06', 'R021'): p06_photo('v2_chroma_kept'),
    ('PHOTO-06', 'R046'): p06_photo('v2_no_overlay'),
    # R048 (margin, type and rules flat and solid, no tints): a see-through or tinted small type cannot be told from a
    # solid lighter colour on a JPEG, so this stays with people.
    ('PHOTO-06', 'R050'): p06({'op': 'v2_main_ground_raster', 'main': PAPER}),
    ('PHOTO-06', 'R051'): p06({'op': 'v2_palette_raster_x', 'hexes': [PAPER, ABLACK, MGREY, LINEN, INK6], 'skip_ground': True}),
    # the sitter's title line: a line in capitals carrying the sitter's first name (ADA HOLLIS); read at 60 or more,
    # since its colour does not depend on every letter
    ('PHOTO-06', 'R052'): p06({'op': 'v2_line_colour_raster', 'patterns': [r'(?-i:\bADA\b)'], 'min_conf': 60, 'colors': [ABLACK]}),
    ('PHOTO-06', 'R053'): p06({'op': 'v2_colour_absent_raster', 'hexes': [MGREY], 'except_lines': [P06_PROVENANCE]}),
    ('PHOTO-06', 'R054'): p06_photo('v2_no_overlay'),
    ('PHOTO-06', 'R055'): p06({'op': 'v2_line_colour_raster', 'patterns': [r'\bHollis\b', r'\b1[89]\d\d\b', r'\bARCHIVE\b', P06_PROVENANCE],
                               'min_conf': 60, 'ground_must': [PAPER]}),
    ('PHOTO-06', 'R056'): p06({'op': 'v2_line_colour_raster', 'patterns': [P06_PLACE_DATE], 'except': [r'(?i)\bPLATE\b|ARCHIVE'], 'colors': [INK6]}),
    ('PHOTO-06', 'R057'): p06({'op': 'v2_line_colour_raster', 'patterns': [r'(?-i:[a-z])'], 'except': [P06_PROVENANCE], 'colors': [INK6], 'optional': True}),
    ('PHOTO-06', 'R058'): p06({'op': 'v2_colour_roles_raster', 'hexes': [LINEN], 'allowed': ['thin'], 'thin_near_photo': True}),
    ('PHOTO-06', 'R059'): p06({'op': 'v2_area_share_raster', 'hexes': [MGREY, LINEN], 'max_pct': 5}),
    ('PHOTO-06', 'R061'): p06({'op': 'v2_max_line_chars', 'max_chars': 65}),
}

# ------------------------------------------------------------------ PHOTO-08 vehicle cards

NAVY, SWHITE, GRAPHITE, TEAL, SGREY = '#1F2A3A', '#F6F7F8', '#2E3237', '#3C6E71', '#9AA1A8'
P08_ROUNDELS = ['meridian_roundel.png', 'meridian_roundel_transparent.png', 'meridian_roundel_reversed.png']
P08_STOCKS = {'M3082': 'norsted_alta', 'M3091': 'ardmoor_ridge', 'M2417': 'calder_vireo', 'M3105': 'brookmere_sable',
              'M2471': 'calder_kestrel', 'M3119': 'norsted_fjord'}
P08_ALL = [f'{s}_{m}_{v}.jpg' for s, m in P08_STOCKS.items() for v in ('front34', 'rear34', 'side')]
P08_FRONT = [f'{s}_{m}_front34.jpg' for s, m in P08_STOCKS.items()]
PRICE_ANY = r'\$\s?\d'
DISCLOSURE = r'excludes\s+tax|title\s+and\s+registration'
MILEAGE_ANY = r'\b\d{1,3},?\d{3}\s*(?:mi|miles)\b'
CAPTIONS = [f'{y} {m}' for y, m in (('2019', 'Norsted Alta'), ('2018', 'Ardmoor Ridge'), ('2017', 'Calder Vireo'), ('2020', 'Brookmere Sable'),
                                    ('2017', 'Calder Kestrel'), ('2019', 'Norsted Fjord'))]
CAPTION_RX = r'\b(?:20[12]\d)\s+(?:Norsted|Ardmoor|Calder|Brookmere)\s+\w+'


def p08_rec(ctx, row):
    return ctx.records.get(row['output_id']) or {}


def p08_photos(ctx, row):
    """The card's own vehicle photos (every angle), else every vehicle photo (the campaign); roundels kept apart."""
    rec = p08_rec(ctx, row)
    if rec.get('stock_no') in P08_STOCKS:
        return [p for p in P08_ALL if p.startswith(rec['stock_no'])]
    return list(P08_ALL)


def p08(spec, roundels=True):
    def h(row, ctx):
        return dict(spec, photos=p08_photos(ctx, row) + (P08_ROUNDELS if roundels else []))
    return h


def p08_detail_patterns(rec):
    """Mileage and listing detail of a card: the mileage figure, trim and certification tier from its record."""
    pats = [num_rx(rec['mileage']) + r'|' + MILEAGE_ANY]
    if rec.get('trim'):
        pats.append(r'(?<!\w)' + re.escape(rec['trim']).replace(r'\ ', r'\s+') + r'(?!\w)')
    pats.append(r'\bCertified\b')
    return pats


def p08_card(fn):
    def h(row, ctx):
        rec = p08_rec(ctx, row)
        if not rec:
            return None
        return dict(fn(rec, row, ctx), photos=p08_photos(ctx, row) + P08_ROUNDELS)
    return h


P08_CANDIDATES = [NAVY, GRAPHITE, TEAL, SGREY]
P08 = {
    ('PHOTO-08', 'R023'): const({'op': 'v2_text_present', 'if_any': PRICE_ANY, 'expected': [{'regex': r'excludes\s+tax,?\s+title,?\s+and\s+registration'}]}),
    ('PHOTO-08', 'R046'): p08({'op': 'v2_palette_raster_x', 'hexes': [NAVY, SWHITE, GRAPHITE, TEAL, SGREY], 'photo_touch': True}),
    ('PHOTO-08', 'R047'): p08_card(lambda rec, row, ctx: {'op': 'v2_line_colour_raster', 'patterns': [num_rx(rec['asking_price'])], 'colors': [NAVY],
                                                          'split_gaps': True}),
    ('PHOTO-08', 'R048'): p08({'op': 'v2_colour_roles_raster', 'hexes': [TEAL], 'allowed': ['thin']}),
    ('PHOTO-08', 'R049'): p08({'op': 'v2_palette_raster_x', 'hexes': [NAVY, SWHITE, GRAPHITE, TEAL, SGREY], 'photo_touch': True}),
    ('PHOTO-08', 'R050'): p08({'op': 'v2_line_colour_raster', 'patterns': [PRICE_ANY], 'colors': [NAVY], 'optional': True}),
    ('PHOTO-08', 'R051'): p08_card(lambda rec, row, ctx: {'op': 'v2_rule_colour_raster', 'below': num_rx(rec['asking_price']),
                                                          'candidates': P08_CANDIDATES, 'colors': [TEAL]}),
    ('PHOTO-08', 'R052'): lambda row, ctx: {'op': 'v2_no_overlay', 'photos': p08_photos(ctx, row)},
    ('PHOTO-08', 'R053'): p08_card(lambda rec, row, ctx: {'op': 'v2_line_colour_raster', 'patterns': [num_rx(rec['asking_price'])] + p08_detail_patterns(rec),
                                                          'ground_must': [SWHITE], 'split_gaps': True}),
    ('PHOTO-08', 'R054'): lambda row, ctx: ({'op': 'v2_behind_subject_raster', 'photos': [p08_rec(ctx, row)['photo']], 'forbidden': [NAVY]}
                                            if p08_rec(ctx, row).get('photo') else None),
    ('PHOTO-08', 'R055'): p08_card(lambda rec, row, ctx: {'op': 'v2_line_colour_raster', 'patterns': p08_detail_patterns(rec), 'colors': [GRAPHITE],
                                                          'split_gaps': True}),
    ('PHOTO-08', 'R056'): p08_card(lambda rec, row, ctx: {'op': 'v2_line_colour_raster', 'texts': [q(row['values']['1'])], 'each': True,
                                                          'pairs': [[NAVY, SWHITE], [SWHITE, NAVY]]}),
    ('PHOTO-08', 'R057'): p08({'op': 'v2_line_colour_raster', 'patterns': [DISCLOSURE], 'colors': [GRAPHITE, SGREY]}),
    ('PHOTO-08', 'R058'): p08({'op': 'v2_colour_roles_raster', 'hexes': [SGREY], 'allowed': ['thin', 'label']}),
    ('PHOTO-08', 'R059'): p08({'op': 'v2_area_share_raster', 'hexes': [TEAL, SGREY], 'max_pct': 5}),
    ('PHOTO-08', 'R060'): p08({'op': 'v2_line_colour_raster', 'patterns': [r'(?-i:^\W*(?:STOCK|MILEAGE|CERTIFICATION|PRICE|TRIM|YEAR|VIN|ODOMETER)\b)'],
                               'grounds': [SWHITE], 'colors': [NAVY], 'optional': True, 'split_gaps': True}),
    ('PHOTO-08', 'R061'): p08({'op': 'v2_line_colour_raster', 'all_text': True, 'grounds': [NAVY], 'colors': [SWHITE], 'optional': True, 'split_gaps': True}),
    ('PHOTO-08', 'R062'): p08({'op': 'v2_if_then', 'if': PRICE_ANY, 'then': {'op': 'v2_rule_colour_raster', 'below': PRICE_ANY, 'candidates': P08_CANDIDATES,
                                                                              'colors': [TEAL]}}),
    ('PHOTO-08', 'R063'): p08({'op': 'v2_colour_roles_raster', 'hexes': [SGREY], 'allowed': ['thin', 'label']}),
    ('PHOTO-08', 'R064'): lambda row, ctx: {'op': 'v2_for_each_photo', 'photos': P08_ALL, 'then': {'op': 'v2_no_overlay'}},
    ('PHOTO-08', 'R065'): p08({'op': 'v2_line_colour_raster', 'patterns': [PRICE_ANY, MILEAGE_ANY, r'(?-i:\bSTOCK\b)'], 'ground_must': [SWHITE],
                               'optional': True, 'split_gaps': True}),
    ('PHOTO-08', 'R066'): lambda row, ctx: {'op': 'v2_for_each_photo', 'photos': P08_ALL, 'then': {'op': 'v2_behind_subject_raster', 'forbidden': [NAVY]}},
    ('PHOTO-08', 'R067'): p08({'op': 'v2_line_colour_raster', 'patterns': [MILEAGE_ANY, r'(?-i:\bSTOCK\b)'], 'colors': [GRAPHITE], 'optional': True,
                               'split_gaps': True}),
    ('PHOTO-08', 'R068'): p08({'op': 'v2_all_of', 'checks': [
        {'op': 'v2_line_colour_raster', 'patterns': [r'^\W*MERIDIAN\s+MOTORS\W*$'], 'pairs': [[NAVY, SWHITE], [SWHITE, NAVY]], 'split_gaps': True},
        {'op': 'v2_line_colour_raster', 'patterns': [r'\S.*MERIDIAN\s+MOTORS|MERIDIAN\s+MOTORS.*\S'], 'except': [r'^\W*MERIDIAN\s+MOTORS\W*$'],
         'pairs': [[NAVY, SWHITE], [SWHITE, NAVY]], 'optional': True, 'soft': True}]}),
    ('PHOTO-08', 'R069'): p08({'op': 'v2_line_colour_raster', 'texts': CAPTIONS, 'each': True, 'pairs': [[NAVY, SWHITE], [SWHITE, NAVY]]}),
    ('PHOTO-08', 'R070'): p08({'op': 'v2_line_colour_raster', 'patterns': [DISCLOSURE], 'colors': [GRAPHITE, SGREY], 'optional': True}),
    ('PHOTO-08', 'R071'): p08({'op': 'v2_grounds_raster', 'hexes': [SWHITE, NAVY]}),
    ('PHOTO-08', 'R072'): p08({'op': 'v2_grounds_raster', 'hexes': [SWHITE, NAVY]}),
    ('PHOTO-08', 'R073'): p08({'op': 'v2_line_colour_raster', 'patterns': [r'^\W*MERIDIAN\s+MOTORS\W*$'], 'grounds': [SWHITE], 'colors': [NAVY],
                               'optional': True, 'split_gaps': True}),
    ('PHOTO-08', 'R080'): p08({'op': 'v2_max_line_chars', 'max_chars': 65}),
    ('PHOTO-08', 'R085'): p08({'op': 'v2_max_line_chars', 'max_chars': 65}),
    ('PHOTO-08', 'R157'): p08_card(lambda rec, row, ctx: {'op': 'v2_sizes_vs', 'rel': 'smaller', 'a': [DISCLOSURE], 'b': p08_detail_patterns(rec)}),
    ('PHOTO-08', 'R159'): const({'op': 'v2_sizes_vs', 'rel': 'larger', 'a': [PRICE_ANY], 'b': [CAPTION_RX], 'optional': True}),
    ('PHOTO-08', 'R160'): const({'op': 'v2_sizes_vs', 'rel': 'smaller', 'a': [DISCLOSURE], 'b': [CAPTION_RX], 'optional': True}),
    ('PHOTO-08', 'R161'): const({'op': 'v2_sizes_vs', 'rel': 'smaller', 'a': [DISCLOSURE], 'b': [MILEAGE_ANY, r'\bCertified\b'], 'optional': True}),
    ('PHOTO-08', 'R162'): const({'op': 'v2_sizes_vs', 'rel': 'smaller', 'a': [MILEAGE_ANY, r'(?-i:\bSTOCK\b)'], 'b': [CAPTION_RX], 'optional': True}),
}

# ------------------------------------------------------------------ PHOTO-10 Northgrove

CHAR, WGP, OLIVE, OAT, CNAVY, OFFW = '#2E2E2C', '#C9C4BA', '#6B7248', '#E4DCCB', '#1B2A44', '#F5F2EC'
COLOURWAYS = ['Moss', 'Bark', 'Slate', 'Oat', 'Ink', 'Clay', 'Fern']
STORIES = {'Moss': 'a soft grey-green, dyed in small lots.', 'Bark': 'a warm mid brown that wears in.', 'Slate': 'a quiet blue-grey.',
           'Oat': 'an undyed-looking pale neutral.', 'Ink': 'a deep near-black charcoal.', 'Clay': 'a muted terracotta.',
           'Fern': 'a deeper forest green.'}
P10_PHOTOS = ['northgrove_style_01_loopback_crew.jpg', 'northgrove_style_02_heavy_tee.jpg', 'northgrove_style_03_raglan.jpg',
              'northgrove_style_04_henley.jpg', 'northgrove_style_05_zip_hoodie.jpg', 'northgrove_style_06_supporters_crew.jpg']
CLOTH = r'\bgsm\b|\d\s?%|\bcotton\b|\bjersey\b|\bloopback\b|\bfleece\b|\bterry\b|\bwool\b|\bpolyester\b|\bnylon\b|\blinen\b|\belastane\b|\bfabric\b|\bcloth\b'
LIGHT = [OFFW, OAT, WGP]
WORDMARK = r'NORTHGROVE'


def p10(spec):
    return lambda row, ctx: dict(spec, photos=P10_PHOTOS)


P10 = {
    ('PHOTO-10', 'R001'): const({'op': 'v2_text_absent', 'texts': [c for c in COLOURWAYS if c != 'Oat']}),
    ('PHOTO-10', 'R006'): const({'op': 'v2_spelled', 'names': COLOURWAYS}),
    ('PHOTO-10', 'R007'): const({'op': 'v2_paired', 'anchor': ['Loopback Crew'], 'whole_line': False, 'kind': rf'\b(?:{"|".join(COLOURWAYS)})\b',
                                 'value': {'regex': r'\bOat\b'}, 'where': 'beside', 'empty_ok': True, 'optional': True}),
    ('PHOTO-10', 'R008'): const({'op': 'v2_verbatim_if_any', 'texts': STORIES}),
    ('PHOTO-10', 'R011'): const({'op': 'v2_verbatim_if_any', 'texts': STORIES}),
    ('PHOTO-10', 'R013'): const({'op': 'v2_verbatim_if_any', 'texts': STORIES}),
    ('PHOTO-10', 'R019'): const({'op': 'v2_text_absent', 'patterns': {'a cloth named': CLOTH}}),
    ('PHOTO-10', 'R023'): const({'op': 'v2_if_then', 'if': r"\bsupporters'?\s*crew\b",
                                 'then': {'op': 'v2_text_absent', 'patterns': {'a cloth named on the page': CLOTH}, 'found_is': 'person'}}),
    ('PHOTO-10', 'R031'): const({'op': 'v2_text_absent', 'texts': COLOURWAYS, 'found_is': 'person'}),
    # R032 and R035 (which fabric line belongs to which style on a carousel page) and R043, R045 (a pale rim round a cut-out)
    # are not read exactly here; R078 (foil or gloss effects) and R082, R105 to R107 (which line is the headline or body
    # text, without a circular size definition) stay with people.
    ('PHOTO-10', 'R051'): p10({'op': 'v2_main_ground_raster', 'main': OFFW, 'ignore': [CNAVY]}),
    ('PHOTO-10', 'R052'): p10({'op': 'v2_palette_raster_x', 'hexes': [CHAR, WGP, OLIVE, OAT, CNAVY, OFFW], 'photo_touch': True}),
    ('PHOTO-10', 'R053'): p10({'op': 'v2_colour_roles_raster', 'hexes': [OLIVE], 'allowed': ['mark', 'thin', 'label'], 'mark_word': WORDMARK}),
    ('PHOTO-10', 'R054'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': LIGHT, 'leaf_colors': [OLIVE]}),
    ('PHOTO-10', 'R055'): p10({'op': 'v2_main_ground_raster', 'main': OFFW, 'ignore': [CNAVY]}),
    ('PHOTO-10', 'R056'): p10({'op': 'v2_main_ground_raster', 'main': OFFW}),
    ('PHOTO-10', 'R057'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': LIGHT, 'leaf_colors': [OLIVE]}),
    ('PHOTO-10', 'R058'): p10({'op': 'v2_line_colour_raster', 'all_text': True, 'colors': [CHAR], 'allow_label_colors': [OLIVE], 'split_gaps': True}),
    ('PHOTO-10', 'R059'): lambda row, ctx: {'op': 'v2_for_each_photo', 'photos': P10_PHOTOS, 'then': {'op': 'v2_no_overlay'}},
    ('PHOTO-10', 'R060'): p10({'op': 'v2_line_colour_raster', 'all_text': True, 'grounds': LIGHT, 'colors': [CHAR], 'allow_label_colors': [OLIVE],
                               'split_gaps': True}),
    ('PHOTO-10', 'R061'): p10({'op': 'v2_area_share_raster', 'hexes': [OLIVE], 'max_pct': 5}),
    ('PHOTO-10', 'R062'): p10({'op': 'v2_rule_colour_raster', 'candidates': [CHAR, WGP, OLIVE, OAT, CNAVY], 'colors': [CHAR]}),
    ('PHOTO-10', 'R063'): p10({'op': 'v2_line_colour_raster', 'all_text': True, 'grounds': [CNAVY], 'colors': [OFFW], 'optional': True, 'split_gaps': True}),
    ('PHOTO-10', 'R064'): p10({'op': 'v2_rule_colour_raster', 'candidates': [CHAR, WGP, OLIVE, OAT, CNAVY, OFFW], 'colors': [CHAR], 'on': {CNAVY: [OFFW]}}),
    ('PHOTO-10', 'R065'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': LIGHT, 'word_colors': [CHAR]}),
    ('PHOTO-10', 'R066'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': [CNAVY], 'word_colors': [OFFW], 'leaf_colors': [OFFW],
                               'pass_if_no_colour': [CNAVY]}),
    ('PHOTO-10', 'R067'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': LIGHT, 'word_colors': [CHAR]}),
    ('PHOTO-10', 'R068'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': [CNAVY], 'word_colors': [OFFW], 'leaf_colors': [OFFW],
                               'pass_if_no_colour': [CNAVY]}),
    ('PHOTO-10', 'R069'): p10({'op': 'v2_colour_absent_raster', 'hexes': [CNAVY]}),
    ('PHOTO-10', 'R070'): p10({'op': 'v2_colour_only_by_raster', 'hexes': [CNAVY], 'assets': ['northgrove_style_06_supporters_crew.jpg'],
                               'texts': ['Made with Rowanfield Athletic', "Supporters' Crew", 'Supporters Crew']}),
    ('PHOTO-10', 'R073'): p10({'op': 'v2_max_line_chars', 'max_chars': 65}),
    ('PHOTO-10', 'R079'): const({'op': 'v2_agree', 'checks': [
        {'op': 'v2_sizes_vs', 'rel': 'smaller', 'a': [r'\bBurlington\b|\bVermont\b|\bterms\b|\brequest\b'], 'b': [CLOTH, rf'\b(?:{"|".join(COLOURWAYS)})\b'], 'optional': True},
        {'op': 'v2_sizes_vs', 'rel': 'smaller', 'a': [r'\bBurlington\b|\bVermont\b|\bterms\b|\brequest\b|\bwash\b|\bdry\b|\bsize run\b'],
         'b': [CLOTH, rf'\b(?:{"|".join(COLOURWAYS)})\b'], 'optional': True}]}),
}

R3 = {**P04, **P06, **P08, **P10}

# ------------------------------------------------------------------ measurable rules first sorted as judgement

def vs(test, **kw):
    """The placed photograph against its supplied file: photo from the row (a .jpg value) or the given list."""
    def h(row, ctx):
        vals = [v for v in (row.get('values') or {}).values() if isinstance(v, str) and v.endswith('.jpg')]
        photos = kw.pop('photos_fn')(row, ctx) if 'photos_fn' in kw else (vals[:1] if vals else None)
        if not photos:
            return None
        return dict({'op': 'v2_vs_source', 'test': test, 'photos': photos}, **{k: v for k, v in kw.items() if k != 'photos_fn'})
    return h


def vs_list(test, photos_fn, **kw):
    return lambda row, ctx: (dict({'op': 'v2_vs_source', 'test': test, 'photos': photos_fn(row, ctx)}, **kw) if photos_fn(row, ctx) else None)


def soft_present(rx):
    return {'op': 'v2_limit', 'fail_as': 'person', 'check': {'op': 'v2_text_present', 'expected': [{'regex': rx}]}}


def fail_only_absent(patterns):
    return {'op': 'v2_limit', 'pass_as': 'person', 'check': {'op': 'v2_text_absent', 'patterns': patterns}}


P04_FRAMES = {h: [f'{h.split()[-1].lower()}_{k}.jpg' for k in ('pool', 'terrace', 'bedroom', 'living')] for h in HOUSES}
P04_RATES = {'Casa Verranza': (520, 680, 560), 'Casa Oliveto': (590, 740, 620), 'Casa Scogliera': (640, 780, 690)}
SEASONS = ['Spring', 'High Summer', 'Autumn']
STONE_RX, WATER_RX, LIGHT_RX = r'\b(?:stone|stones|wall|walls)\b', r'\b(?:water|pool|cove)\b', r'\b(?:light|daylight|sunlight)\b'
OVERSELL = r'\b(?:luxury|luxurious|stunning|breathtaking|exclusive)\b'


def p04_rates_labelled(row, ctx):
    checks = []
    for house, rates in P04_RATES.items():
        short = house.split()[-1]
        rivals = [x for h in HOUSES if h != house for x in (h, h.split()[-1])]
        for season, rate in zip(SEASONS, rates):
            checks.append({'op': 'v2_paired', 'anchor': [house, short], 'rivals': rivals, 'label': [season],
                           'label_rivals': [x for x in SEASONS if x != season], 'kind': P04_RATE, 'value': {'regex': num_rx(rate)},
                           'where': 'section'})
    return {'op': 'v2_all_of', 'checks': checks}


def p04_section(house, op, **kw):
    others = [h for h in HOUSES if h != house]
    if op == 'photos':
        return const({'op': 'v2_section_photos', 'heading': house, 'other_headings': others, 'own': P04_FRAMES[house],
                      'others': [f for h in others for f in P04_FRAMES[h]], 'ignore': ['gate_plate.jpg']})
    return const({'op': 'v2_section_text', 'heading': house, 'other_headings': others, 'pattern': kw['pattern']})


def p04_hero_house(row):
    for h in HOUSES:
        if h.split()[-1].lower() in row['output_id']:
            return h
    return None


def p04_hero_frames(row, ctx):
    h = p04_hero_house(row)
    return P04_FRAMES[h] if h else None


ALL_P04 = [f for h in HOUSES for f in P04_FRAMES[h]]

P04J = {
    ('PHOTO-04', 'R002'): const({'op': 'v2_inside_all', 'patterns': [r'\bbook\b|\breserve\b|\benquir']}),
    ('PHOTO-04', 'R004'): p04_rates_labelled,
    ('PHOTO-04', 'R016'): lambda row, ctx: {'op': 'v2_limit', 'fail_as': 'person', 'check': {
        'op': 'v2_text_present', 'expected': [{'regex': r'\bfrom\b\W*(?:EUR|€)?\s*' + num_rx(re.sub(r'\D', '', row['values']['1']))}]}},
    ('PHOTO-04', 'R022'): p04_section('Casa Verranza', 'photos'),
    ('PHOTO-04', 'R023'): p04_section('Casa Oliveto', 'photos'),
    ('PHOTO-04', 'R024'): p04_section('Casa Scogliera', 'photos'),
    ('PHOTO-04', 'R025'): const({'op': 'v2_same_photo', 'asset': 'verranza_monogram_transparent.png', 'min_ncc': 0.9}),
    ('PHOTO-04', 'R026'): const({'op': 'v2_vs_source', 'test': 'mean_de', 'max_de': 3, 'photo': 'scogliera_pool.jpg'}),
    ('PHOTO-04', 'R027'): const({'op': 'v2_vs_source', 'test': 'mean_de', 'max_de': 3, 'photo': 'verranza_pool.jpg'}),
    ('PHOTO-04', 'R028'): const({'op': 'v2_vs_source', 'test': 'mean_de', 'max_de': 3, 'photo': 'oliveto_pool.jpg'}),
    ('PHOTO-04', 'R029'): const({'op': 'v2_vs_source', 'test': 'mean_de', 'max_de': 3, 'photo': 'oliveto_pool.jpg'}),
    ('PHOTO-04', 'R030'): const({'op': 'v2_vs_source', 'test': 'mean_de', 'max_de': 3, 'photo': 'verranza_pool.jpg'}),
    ('PHOTO-04', 'R031'): const({'op': 'v2_vs_source', 'test': 'mean_de', 'max_de': 3, 'photo': 'scogliera_pool.jpg'}),
    ('PHOTO-04', 'R032'): const({'op': 'v2_same_photo', 'asset': 'verranza_monogram_transparent.png', 'min_ncc': 0.93}),
    ('PHOTO-04', 'R035'): const({'op': 'v2_mark_colour_raster', 'asset': 'verranza_monogram_transparent.png', 'pairs': [[BLUE, LIME], [LIME, BLUE]]}),
    ('PHOTO-04', 'R038'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_solid_pdf'}, {'op': 'v2_pdf_no_overlay'}]}),
    ('PHOTO-04', 'R079'): p04_section('Casa Verranza', 'text', pattern=STONE_RX),
    ('PHOTO-04', 'R081'): const(soft_present(STONE_RX)),
    ('PHOTO-04', 'R082'): const(fail_only_absent({'an overselling word': OVERSELL})),
    ('PHOTO-04', 'R083'): const(fail_only_absent({'an overselling word': OVERSELL})),
    ('PHOTO-04', 'R086'): p04_section('Casa Oliveto', 'text', pattern=STONE_RX),
    ('PHOTO-04', 'R087'): p04_section('Casa Scogliera', 'text', pattern=STONE_RX),
    ('PHOTO-04', 'R089'): p04_section('Casa Verranza', 'text', pattern=WATER_RX),
    ('PHOTO-04', 'R090'): p04_section('Casa Verranza', 'text', pattern=LIGHT_RX),
    ('PHOTO-04', 'R091'): const(soft_present(WATER_RX)),
    ('PHOTO-04', 'R092'): const(soft_present(LIGHT_RX)),
    ('PHOTO-04', 'R093'): p04_section('Casa Oliveto', 'text', pattern=WATER_RX),
    ('PHOTO-04', 'R094'): p04_section('Casa Oliveto', 'text', pattern=LIGHT_RX),
    ('PHOTO-04', 'R095'): p04_section('Casa Scogliera', 'text', pattern=WATER_RX),
    ('PHOTO-04', 'R096'): p04_section('Casa Scogliera', 'text', pattern=LIGHT_RX),
    ('PHOTO-04', 'R097'): const({'op': 'v2_vs_source', 'every': True, 'test': 'cast_left', 'photos': P04_FRAMES['Casa Verranza']}),
    ('PHOTO-04', 'R098'): const({'op': 'v2_vs_source', 'every': True, 'test': 'tiles', 'min_cover': 0.98, 'photos': P04_FRAMES['Casa Verranza']}),
    ('PHOTO-04', 'R099'): const({'op': 'v2_vs_source', 'every': True, 'test': 'cast_left', 'photos': P04_FRAMES['Casa Oliveto']}),
    ('PHOTO-04', 'R100'): const({'op': 'v2_vs_source', 'every': True, 'test': 'tiles', 'min_cover': 0.98, 'photos': P04_FRAMES['Casa Oliveto']}),
    ('PHOTO-04', 'R101'): const({'op': 'v2_vs_source', 'every': True, 'test': 'warm_shift', 'photos': P04_FRAMES['Casa Scogliera']}),
    ('PHOTO-04', 'R102'): const({'op': 'v2_vs_source', 'every': True, 'test': 'tiles', 'min_cover': 0.98, 'photos': P04_FRAMES['Casa Scogliera']}),
    ('PHOTO-04', 'R103'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': P04_FRAMES['Casa Oliveto']}),
    ('PHOTO-04', 'R104'): vs_list('tiles', p04_hero_frames, min_cover=0.98),
    ('PHOTO-04', 'R105'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': P04_FRAMES['Casa Verranza']}),
    ('PHOTO-04', 'R106'): const({'op': 'v2_vs_source', 'test': 'warm_shift', 'photos': P04_FRAMES['Casa Scogliera']}),
    ('PHOTO-04', 'R107'): const({'op': 'v2_vs_source', 'every': True, 'test': 'mean_de', 'max_de': 3, 'photos': ALL_P04}),
    ('PHOTO-04', 'R108'): const({'op': 'v2_vs_source', 'every': True, 'test': 'glow', 'photos': ALL_P04}),
    ('PHOTO-04', 'R109'): const({'op': 'v2_vs_source', 'every': True, 'test': 'crush', 'photos': ALL_P04}),
    ('PHOTO-04', 'R110'): const({'op': 'v2_vs_source', 'every': True, 'test': 'mean_de', 'max_de': 3, 'photos': ALL_P04}),
    ('PHOTO-04', 'R111'): const({'op': 'v2_vs_source', 'every': True, 'test': 'glow', 'photos': ALL_P04}),
    ('PHOTO-04', 'R112'): const({'op': 'v2_vs_source', 'every': True, 'test': 'crush', 'photos': ALL_P04}),
    ('PHOTO-04', 'R113'): const({'op': 'v2_vs_source', 'every': True, 'test': 'detail', 'photos': ALL_P04}),
    ('PHOTO-04', 'R114'): const({'op': 'v2_vs_source', 'every': True, 'test': 'detail', 'photos': ALL_P04}),
    ('PHOTO-04', 'R118'): const({'op': 'v2_sizes_vs', 'rel': 'smaller', 'a': [r'(?:EUR|€)\s?\d{3}'], 'b': [r'\bbook\b|\breserve\b']}),
}

P06_SCANS = [f'hollis_scan_0{i}.jpg' for i in range(1, 10)]
FAMILY = ['Ruth', 'Walter', 'Frank', 'Carol', 'Tom', 'Dale']


def p06_vs(test, **kw):
    def h(row, ctx):
        src = p06_src(row)
        return dict({'op': 'v2_vs_source', 'test': test, 'photo': src}, **kw) if src else None
    return h


def p06_names_only(allowed):
    def h(row, ctx):
        ok = set(allowed) | {w for w in re.findall(r'[A-Z][a-z]+', (row.get('values') or {}).get('1', ''))}
        others = [n for n in FAMILY if n not in ok]
        return {'op': 'v2_limit', 'pass_as': 'person', 'check': {'op': 'v2_text_absent', 'patterns': {'another person named': rf'\b(?:{"|".join(others)})\b'}}}
    return h


P06J = {
    ('PHOTO-06', 'R001'): p06_vs('whole'), ('PHOTO-06', 'R002'): p06_vs('whole'), ('PHOTO-06', 'R003'): p06_vs('whole'),
    ('PHOTO-06', 'R004'): p06_vs('whole'), ('PHOTO-06', 'R008'): p06_vs('whole'),
    ('PHOTO-06', 'R005'): p06_names_only(['Ada']),
    ('PHOTO-06', 'R007'): p06_names_only(['Ada']),
    ('PHOTO-06', 'R009'): p06_names_only(['Ada', 'Ruth', 'Frank', 'Carol']),
    ('PHOTO-06', 'R010'): p06_vs('changed'), ('PHOTO-06', 'R011'): p06_vs('changed'), ('PHOTO-06', 'R012'): p06_vs('changed'),
    ('PHOTO-06', 'R013'): p06_vs('changed'), ('PHOTO-06', 'R016'): p06_vs('changed'), ('PHOTO-06', 'R017'): p06_vs('changed'),
    ('PHOTO-06', 'R014'): const({'op': 'v2_limit', 'fail_as': 'person', 'check': {'op': 'v2_inside_all', 'patterns': [r'[A-Za-z]{3,}']}}),
    ('PHOTO-06', 'R019'): p06_vs('tiles'), ('PHOTO-06', 'R024'): p06_vs('tiles'), ('PHOTO-06', 'R026'): p06_vs('tiles'),
    ('PHOTO-06', 'R069'): p06_vs('tiles'), ('PHOTO-06', 'R079'): p06_vs('tiles'), ('PHOTO-06', 'R022'): p06_vs('tiles'),
    ('PHOTO-06', 'R029'): p06_vs('tiles'), ('PHOTO-06', 'R040'): p06_vs('tiles'),
    ('PHOTO-06', 'R020'): p06_vs('mono'),
    ('PHOTO-06', 'R023'): p06_vs('whole'), ('PHOTO-06', 'R080'): p06_vs('whole'), ('PHOTO-06', 'R081'): p06_vs('whole'),
    ('PHOTO-06', 'R032'): lambda row, ctx: {'op': 'v2_made_from', 'photos': P06_SCANS, 'expected': p06_src(row)} if p06_src(row) else None,
    ('PHOTO-06', 'R033'): p06_vs('detail', full=True), ('PHOTO-06', 'R034'): p06_vs('detail', full=True), ('PHOTO-06', 'R035'): p06_vs('detail', full=True),
    ('PHOTO-06', 'R038'): p06_vs('detail'), ('PHOTO-06', 'R043'): p06_vs('detail'),
    ('PHOTO-06', 'R041'): p06_vs('b_drop'), ('PHOTO-06', 'R042'): p06_vs('range'), ('PHOTO-06', 'R047'): p06_vs('tile_de'),
    ('PHOTO-06', 'R049'): lambda row, ctx: ({'op': 'v2_all_of', 'checks': [
        {'op': 'v2_vs_source', 'test': 'tile_de', 'photo': p06_src(row)},
        {'op': 'v2_limit', 'fail_as': 'person', 'check': {'op': 'v2_palette_raster', 'hexes': [PAPER, ABLACK, MGREY, LINEN, INK6], 'photos': [p06_src(row)]}}]}
        if p06_src(row) else None),
    ('PHOTO-06', 'R071'): p06_vs('sepia'), ('PHOTO-06', 'R078'): p06_vs('no_warmer'),
}

CLAIMS = r'172[- ]?point|\bwarrant\w*|\bone[- ]owner\b|\binspect\w*|3,000[- ]?mi|accident[- ]free|clean title|service history'


def p08_photo(row, ctx):
    rec = p08_rec(ctx, row)
    return [rec['photo']] if rec.get('photo') else None


def p08_angles(stock):
    return [p for p in P08_ALL if p.startswith(stock)]


def p08_rule_below(**kw):
    return p08_card(lambda rec, row, ctx: dict({'op': 'v2_rule_colour_raster', 'below': num_rx(rec['asking_price']), 'candidates': P08_CANDIDATES,
                                                'colors': P08_CANDIDATES}, **kw))


P08J = {
    ('PHOTO-08', 'R018'): const({'op': 'v2_inside_all', 'patterns': [r'\b(?:enquir|inquir)\w*']}),
    ('PHOTO-08', 'R019'): const(fail_only_absent({'a claim beyond the record': CLAIMS})),
    ('PHOTO-08', 'R021'): const(soft_present(r'exclud\w*\s+tax,?\s+title,?\s+and\s+registration')),
    ('PHOTO-08', 'R022'): const(fail_only_absent({'a claim beyond the record': CLAIMS})),
    ('PHOTO-08', 'R026'): lambda row, ctx: ({'op': 'v2_made_from', 'photos': P08_ALL, 'expected': p08_rec(ctx, row)['photo']}
                                            if p08_rec(ctx, row).get('photo') else None),
    ('PHOTO-08', 'R028'): lambda row, ctx: {'op': 'v2_contains_asset', 'assets': [row['values'][k] for k in ('4', '5', '6')]},
    ('PHOTO-08', 'R045'): const({'op': 'v2_contains_asset', 'assets': P08_ROUNDELS}),
    ('PHOTO-08', 'R098'): vs_list('cast_left', p08_photo), ('PHOTO-08', 'R103'): vs_list('cast_left', p08_photo),
    ('PHOTO-08', 'R105'): vs_list('cast_left', p08_photo), ('PHOTO-08', 'R106'): vs_list('cast_left', p08_photo),
    ('PHOTO-08', 'R111'): vs_list('cast_left', p08_photo), ('PHOTO-08', 'R124'): vs_list('cast_left', p08_photo),
    ('PHOTO-08', 'R127'): vs_list('cast_left', p08_photo), ('PHOTO-08', 'R129'): vs_list('cast_left', p08_photo),
    ('PHOTO-08', 'R130'): vs_list('cast_left', p08_photo), ('PHOTO-08', 'R143'): vs_list('cast_left', p08_photo),
    ('PHOTO-08', 'R145'): vs_list('cast_left', p08_photo),
    ('PHOTO-08', 'R108'): const({'op': 'v2_vs_source', 'every': True, 'test': 'cast_left', 'photos': [p for p in P08_ALL if not p.startswith('M3082')]}),
    ('PHOTO-08', 'R134'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': p08_angles('M3091')}),
    ('PHOTO-08', 'R136'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': p08_angles('M2417')}),
    ('PHOTO-08', 'R138'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': p08_angles('M3105')}),
    ('PHOTO-08', 'R140'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': p08_angles('M2471')}),
    ('PHOTO-08', 'R142'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': p08_angles('M3119')}),
    ('PHOTO-08', 'R147'): const({'op': 'v2_vs_source', 'test': 'cast_left', 'photos': p08_angles('M3119')}),
    ('PHOTO-08', 'R099'): p08_rule_below(),
    ('PHOTO-08', 'R101'): p08({'op': 'v2_limit', 'fail_as': 'person', 'check': {'op': 'v2_grounds_raster', 'hexes': [NAVY, SWHITE], 'min_share': 0.01}}),
    ('PHOTO-08', 'R109'): p08({'op': 'v2_if_then', 'if': PRICE_ANY, 'then': {'op': 'v2_rule_colour_raster', 'below': PRICE_ANY, 'candidates': P08_CANDIDATES,
                                                                              'colors': P08_CANDIDATES}}),
    ('PHOTO-08', 'R115'): p08_rule_below(max_rows=2),
    ('PHOTO-08', 'R116'): p08({'op': 'v2_if_then', 'if': PRICE_ANY, 'then': {'op': 'v2_rule_colour_raster', 'below': PRICE_ANY, 'candidates': P08_CANDIDATES,
                                                                              'colors': P08_CANDIDATES, 'max_rows': 2}}),
    ('PHOTO-08', 'R117'): p08_rule_below(full_width=True),
    ('PHOTO-08', 'R120'): vs_list('tiles', p08_photo), ('PHOTO-08', 'R121'): vs_list('tiles', p08_photo),
    ('PHOTO-08', 'R122'): vs_list('tiles', p08_photo), ('PHOTO-08', 'R123'): vs_list('tiles', p08_photo),
    ('PHOTO-08', 'R125'): vs_list('tiles', p08_photo), ('PHOTO-08', 'R126'): vs_list('tiles', p08_photo),
    ('PHOTO-08', 'R128'): vs_list('warm_shift', p08_photo),
    ('PHOTO-08', 'R131'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photos': p08_angles('M3082')}),
    ('PHOTO-08', 'R132'): const({'op': 'v2_vs_source', 'test': 'warm_shift', 'photos': p08_angles('M3082')}),
    ('PHOTO-08', 'R133'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photos': p08_angles('M3091')}),
    ('PHOTO-08', 'R135'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photos': p08_angles('M2417')}),
    ('PHOTO-08', 'R137'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photos': p08_angles('M3105')}),
    ('PHOTO-08', 'R139'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photos': p08_angles('M2471')}),
    ('PHOTO-08', 'R141'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photos': p08_angles('M3119')}),
    ('PHOTO-08', 'R144'): vs_list('mean_de', p08_photo, max_de=3),
    ('PHOTO-08', 'R146'): const({'op': 'v2_vs_source', 'every': True, 'test': 'mean_de', 'max_de': 3, 'photos': P08_ALL}),
    ('PHOTO-08', 'R148'): lambda row, ctx: {'op': 'v2_contains_asset', 'assets': p08_photo(row, ctx)} if p08_photo(row, ctx) else None,
    ('PHOTO-08', 'R154'): const({'op': 'v2_for_each_photo', 'photos': P08_ALL, 'then': {'op': 'v2_contains_asset'}}),
    ('PHOTO-08', 'R156'): const({'op': 'v2_inside_all', 'texts': ['Meridian Motors']}),
}
for _r in ('R149', 'R150', 'R151', 'R152', 'R153'):
    P08J[('PHOTO-08', _r)] = P08J[('PHOTO-08', 'R148')]


def p10_photo(row, ctx):
    for i, f in enumerate(P10_PHOTOS, 1):
        if f'style-0{i}' in row['output_id']:
            return [f]
    v = [x for x in (row.get('values') or {}).values() if isinstance(x, str) and x.endswith('.jpg')]
    return v[:1] or None


P10J = {
    ('PHOTO-10', 'R036'): lambda row, ctx: {'op': 'v2_made_from', 'photos': P10_PHOTOS, 'expected': p10_photo(row, ctx)[0]} if p10_photo(row, ctx) else None,
    ('PHOTO-10', 'R038'): vs_list('detail', p10_photo, full=True),
    ('PHOTO-10', 'R041'): const({'op': 'v2_vs_source', 'every': True, 'test': 'detail', 'full': True, 'photos': P10_PHOTOS}),
    ('PHOTO-10', 'R039'): vs_list('tiles', p10_photo, min_cover=0.98),
    ('PHOTO-10', 'R042'): const({'op': 'v2_vs_source', 'every': True, 'test': 'tiles', 'min_cover': 0.98, 'photos': P10_PHOTOS}),
    ('PHOTO-10', 'R049'): vs_list('detail', p10_photo, full=True, max_scale=1.05),
    ('PHOTO-10', 'R050'): const({'op': 'v2_vs_source', 'every': True, 'test': 'detail', 'full': True, 'max_scale': 1.05, 'photos': P10_PHOTOS}),
    ('PHOTO-10', 'R080'): const(fail_only_absent({'an overselling or bargain word': r'\b(?:luxury|luxurious|exclusive|cheap|sale|bargain|discount|stunning)\b'})),
    ('PHOTO-10', 'R083'): lambda row, ctx: {'op': 'v2_contains_asset', 'assets': p10_photo(row, ctx)} if p10_photo(row, ctx) else None,
    ('PHOTO-10', 'R084'): vs_list('cast_left', p10_photo),
    ('PHOTO-10', 'R094'): vs_list('warm_shift', p10_photo),
    ('PHOTO-10', 'R085'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photo': 'northgrove_style_06_supporters_crew.jpg'}),
    ('PHOTO-10', 'R092'): const({'op': 'v2_vs_source', 'test': 'tiles', 'photo': 'northgrove_style_06_supporters_crew.jpg'}),
    ('PHOTO-10', 'R086'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': LIGHT, 'leaf_colors': [OLIVE]}),
    ('PHOTO-10', 'R095'): p10({'op': 'v2_leaf_mark_raster', 'word': WORDMARK, 'on': LIGHT, 'leaf_colors': [OLIVE]}),
    ('PHOTO-10', 'R089'): const({'op': 'v2_limit', 'fail_as': 'person', 'check': {'op': 'v2_text_present', 'expected': ['NORTHGROVE'], 'whole_line': True}}),
    ('PHOTO-10', 'R098'): const({'op': 'v2_limit', 'fail_as': 'person', 'check': {'op': 'v2_text_present', 'expected': ['NORTHGROVE'], 'whole_line': True}}),
    ('PHOTO-10', 'R091'): const({'op': 'v2_vs_source', 'every': True, 'test': 'tiles', 'photos': P10_PHOTOS}),
}

R3.update(P04J)
R3.update(P06J)
R3.update(P08J)
R3.update(P10J)

HOW = {
    'v2_agree': 'Runs the check under a narrow and a broad reading of the definition and answers only when both agree.',
    'v2_pdf_colour_roles': 'Reads every shape and text span drawn in the colour from the PDF and checks each is a thin rule or a small label.',
    'v2_pdf_grounds': 'Reads each page\'s ground from the rendered page and every opaque filled panel from the PDF, and checks their colours.',
    'v2_pdf_text_on_grounds': 'Sorts the PDF text by size and case, reads the colour behind each selected line and checks its type colour.',
    'v2_pdf_area_share_pages': 'Measures the share of each page outside the placed pictures in the colours, page by page and over the whole file.',
    'v2_pdf_no_overlay': 'Reads the shapes, pictures and graphics states drawn over each placed photograph for transparency, shading or blending.',
    'v2_pdf_role_vs_lines': 'Reads the PDF font sizes of the headings and of the named lines and compares them.',
    'v2_max_line_chars': 'Counts the characters of every line (PDF text, or OCR lines outside the photographs).',
    'v2_line_colour_raster': 'Reads each selected text line by OCR, then the colour of its letters and of the ground behind it.',
    'v2_colour_roles_raster': 'Finds every piece in the colour outside the photographs and checks it is a thin rule or sits inside a small label.',
    'v2_colour_absent_raster': 'Looks for the colour as a flat area or as the ink of a text line outside the photographs.',
    'v2_colour_only_by_raster': 'Finds every flat area in the colour and checks it sits by the named photograph or line.',
    'v2_grounds_raster': 'Finds every ground, band, panel and button (flat areas outside the photographs) and reads its colour.',
    'v2_main_ground_raster': 'Finds the largest flat area outside the photographs and reads its colour.',
    'v2_palette_raster_x': 'Reads every flat colour outside the photographs, the margin left out, and checks each is a palette colour.',
    'v2_rule_colour_raster': 'Finds the thin horizontal rules and tells their colour by the direction it takes from the ground.',
    'v2_behind_subject_raster': 'Finds the supplied photo and reads the colour of the ground directly round it.',
    'v2_leaf_mark_raster': 'Reads the wordmark by OCR, then the colour of its letters and of the symbol beside it.',
    'v2_verbatim_if_any': 'Reads the text and checks any line close to, or describing, an approved text holds it word for word.',
    'v2_if_then': 'Reads the text; where the named item appears, runs the check on it.',
    'v2_sizes_vs': 'Compares the sizes of every line of one kind with every line of the other.',
    'v2_for_each_photo': 'Runs the check for every supplied photo found in the deliverable.',
    'v2_pdf_lines_style': 'Reads the font, size or line spacing of the selected PDF lines.',
    'v2_vs_source': 'Finds the supplied photo in the deliverable, maps the placement back onto it and compares tiles, colour, tone or fine detail.',
    'v2_made_from': 'Searches the deliverable for every supplied photo and checks only the expected one is found.',
    'v2_section_photos': 'Matches every picture on the section\'s pages against the supplied photos of each section.',
    'v2_limit': 'Runs the check and lets it decide only in the direction it is sure of; the other answer goes to a person.',
    'v2_section_text': 'Reads the live text of the section\'s pages for the named words.',
}


def convert(tid, rid, row, ctx):
    h = R3.get((tid, rid))
    return h(row, ctx) if h else None
