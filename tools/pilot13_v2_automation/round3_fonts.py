"""Round 3 conversions, typefaces on images (2026-10-28): which font, weight and slant a line of type is set in, whether
it is stretched, and how open its letter spacing is, read from raster deliverables and held video frames.

One handler per (task, rule), taking (row, ctx) and returning an assertion for tools/auto_verifier/ops_r3_fonts.py, or
None when the row cannot be checked exactly. Lines are picked by the wording the check names (the row's values, the
deliverable's record or name), by pattern, or by text role (objective_ops_r3._roles: body, heading, main, secondary,
fine). Supplied artwork that happens to read as text (logos, wordmark drawings, the CFS mark) is left out by its
wording.

Left as they were: PHOTO-04 R071 (which line is a standfirst is not defined on these heroes), PHOTO-06 R070
(ornaments, frames, shadows and monograms are not type), PHOTO-08 R082 (whether a label sits beside the roundel needs
the roundel's position, not a font reading).
"""
from __future__ import annotations

import re

from round2 import DATE_ANY, MON, q

TF = 'v2_typeface_raster'
PRICE = r'[$€£]\s?\d|\b(?:EUR|USD|GBP)\s?\d|\d\s?(?:EUR|€)'
YEAR = r'\b(?:18|19|20)\d\d\b'
DATE_LONG = rf'\b\d{{1,2}}\s+{MON}\.?,?\s+\d{{4}}\b|\b{MON}\.?\s+\d{{1,2}},?\s+\d{{4}}\b'
MILEAGE = r'\b\d{1,3}(?:,\d{3})+\s*(?:mi|miles|km)\b|\b\d+\s*(?:mi|miles|km)\b|\bmileage\b'
DISCLOSURE = r'\bexclud|\bsubject to\b|\bplus tax\b|\btax\b|\bregistration\b|\bAPR\b|\bterms\b|\bfees?\b'


def tf(fonts, **sel):
    return lambda row, ctx: dict({'op': TF, 'fonts': fonts}, **sel)


def const(a):
    return lambda row, ctx: dict(a)


def v1(row):
    return q(row['values']['1'])


# ------------------------------------------------------------------ PHOTO-04 villa booking heroes

CG_LIGHT = [['Cormorant Garamond', ['Light']]]
SS3_REG = [['Source Sans 3', ['Regular']]]
P04 = {
    ('PHOTO-04', 'R064'): lambda row, ctx: {'op': TF, 'whole': [v1(row)], 'fonts': CG_LIGHT},
    ('PHOTO-04', 'R065'): tf(SS3_REG, roles=['body']),
    # every figure in Source Sans 3 (any weight): the words holding figures, line by line
    ('PHOTO-04', 'R066'): tf([['Source Sans 3', None]], all_text=True, figures_only=True, words={'digits': True}, optional=True),
    ('PHOTO-04', 'R071'): lambda row, ctx: None,
    ('PHOTO-04', 'R072'): tf(SS3_REG, patterns=[PRICE, r'/\s*night', r'\bsleeps?\b', r'\bmin(?:imum|\.)?\b.*\bnights?\b'], roles=['caption']),
    ('PHOTO-04', 'R078'): tf(SS3_REG, patterns=[r'\b(?:book|reserve|enquire|inquire|check availability)\b']),
}

# ------------------------------------------------------------------ PHOTO-06 family archive share images

# the title: the largest heading line of two words or more, its words without figures (a numeral OCR merges in left out)
TITLE06 = dict(patterns=[r'[A-Za-z]{2,}\W+[A-Za-z]{2,}'], within_roles=['heading'], largest_only=True, words={'no_figures': True},
               min_chars=3)
PLACE06 = dict(patterns=[YEAR + r'.*[A-Za-z]{3}|[A-Za-z]{3}.*' + YEAR])
P06 = {
    ('PHOTO-06', 'R060'): const(dict({'op': 'v2_upright_raster'}, **TITLE06)),
    ('PHOTO-06', 'R062'): const(dict({'op': TF, 'fonts': CG_LIGHT}, **TITLE06)),
    ('PHOTO-06', 'R063'): const(dict({'op': TF, 'fonts': CG_LIGHT}, **PLACE06)),
    # caption body: lines in lowercase (the names line, provenance), not the place and date line
    ('PHOTO-06', 'R064'): tf([['Source Serif 4', ['Regular']]], patterns=[r'[a-z]{2}'], except_patterns=[YEAR], optional=True),
    ('PHOTO-06', 'R066'): tf([['Cormorant Garamond', None], ['Source Serif 4', None], ['Source Sans 3', None]], all_text=True, italic='any'),
    ('PHOTO-06', 'R067'): const(dict({'op': 'v2_upright_raster'}, **PLACE06)),
    # a plate numeral OCR misses or merges cannot be told from an absent one: no numeral found goes to a person
    ('PHOTO-06', 'R068'): tf(CG_LIGHT, patterns=[r'^\s*(?:no\.?\s*)?\d{1,3}\s*$']),
    ('PHOTO-06', 'R070'): lambda row, ctx: None,
}

# ------------------------------------------------------------------ PHOTO-08 vehicle cards and campaign

SS4_BOLD = [['Source Serif 4', ['Bold']]]


def p08_detail(row, ctx):
    rec = ctx.records.get(row['output_id']) or {}
    texts = [x for x in (rec.get('trim'), rec.get('cert_tier')) if x]
    return {'op': TF, 'fonts': SS3_REG, 'patterns': [MILEAGE, r'\bSTOCK\b'], 'texts': texts,
            'except_whole': ['MILEAGE', 'CERTIFICATION', 'TRIM', 'STOCK']}


P08 = {
    ('PHOTO-08', 'R078'): lambda row, ctx: {'op': TF, 'fonts': SS4_BOLD, 'whole': [v1(row)], 'words': {'digits': True}},
    ('PHOTO-08', 'R079'): p08_detail,
    ('PHOTO-08', 'R081'): tf([['Source Serif 4', None], ['Source Sans 3', None]], all_text=True),
    ('PHOTO-08', 'R082'): lambda row, ctx: None,
    ('PHOTO-08', 'R083'): tf(SS4_BOLD, whole=['Meridian Motors'], largest_only=True),
    ('PHOTO-08', 'R084'): tf(SS3_REG, patterns=[MILEAGE], optional=True),
    ('PHOTO-08', 'R086'): lambda row, ctx: {'op': TF, 'fonts': SS4_BOLD, 'whole': [v1(row)]},
    ('PHOTO-08', 'R087'): tf(SS3_REG, patterns=[DISCLOSURE]),
    ('PHOTO-08', 'R088'): tf(SS4_BOLD, patterns=[r'\$\s?\d'], words={'digits': True}, optional=True),
    ('PHOTO-08', 'R089'): tf(SS4_BOLD, patterns=[r'\b(?:19|20)\d\d\s+[A-Z][A-Za-z]+\s+[A-Z][A-Za-z]+']),
    ('PHOTO-08', 'R090'): tf(SS3_REG, patterns=[DISCLOSURE], optional=True),
}

# ------------------------------------------------------------------ PHOTO-10 product pages and carousel

LF_REG = [['Libre Franklin', ['Regular']]]
STYLES = ['Loopback Crew', 'Heavy Tee', 'Raglan', 'Henley', 'Zip Hoodie', 'Supporters Crew']
CLOTH = [r'\bgsm\b', r'\bcotton\b', r'\bwash\b', r'\bdry\b', r'\bjersey\b', r'\bfleece\b', r'\d\s?%']


def p10_style(row, ctx):
    m = re.search(r'northgrove_style_\d+_(\w+)$', ctx.outputs[row['output_id']]['name'])
    return {'op': TF, 'fonts': SS4_BOLD, 'texts': [m.group(1).replace('_', ' ')], 'largest_only': True,
            'except_whole': ['NORTHGROVE']} if m else None


P10 = {
    ('PHOTO-10', 'R071'): p10_style,
    ('PHOTO-10', 'R072'): tf(LF_REG, roles=['body'], patterns=CLOTH, except_roles=['heading'], except_whole=['NORTHGROVE'], optional=True),
    ('PHOTO-10', 'R074'): tf(SS4_BOLD, roles=['main'], except_whole=['NORTHGROVE'], optional=True),
    ('PHOTO-10', 'R075'): tf(LF_REG, roles=['fine'], except_whole=['NORTHGROVE'], optional=True),
    ('PHOTO-10', 'R076'): tf(SS4_BOLD, texts=STYLES, except_roles=['body', 'fine'], except_whole=['NORTHGROVE'], optional=True),
    ('PHOTO-10', 'R081'): const({'op': 'v2_not_stretched_raster', 'all_text': True, 'except_whole': ['NORTHGROVE'],
                                 'fonts': [['Source Serif 4', ['Bold']], ['Libre Franklin', ['Regular']]]}),
}

# ------------------------------------------------------------------ PHOTO-19 summit cards and announcement

INTER_TEXT = [['Inter', ['Regular', 'Medium']], ['IBM Plex Mono', ['Regular']]]
INTER_REG = [['Inter', ['Regular']]]
SUMMIT = ['Cascadia Founders Summit', 'Cascadia', 'Founders', 'Summit', 'Cascadia Founders', 'Founders Summit']
CFS = ['CFS', 'C F S']


def p19_value(field, fonts):
    def h(row, ctx):
        rec = ctx.records.get(row['output_id']) or {}
        value = v1(row) if row.get('values', {}).get('1') else rec.get(field)
        return {'op': TF, 'fonts': fonts, 'part_of': [value]} if value else None
    return h


def p19_host_affiliation(row, ctx):
    rec = ctx.records.get(row['output_id']) or {}
    return {'op': TF, 'fonts': INTER_REG, 'whole': ['Cascadia Founders Summit'], 'below': [rec['Name']]} if rec.get('Name') else None


P19 = {
    ('PHOTO-19', 'R054'): tf(INTER_TEXT, all_text=True, except_whole=CFS + ['Cascadia Founders Summit']),
    ('PHOTO-19', 'R056'): tf([['Piazzolla', ['Medium']]], whole=SUMMIT, largest_only=True),
    ('PHOTO-19', 'R057'): tf(INTER_TEXT, all_text=True, except_whole=CFS + SUMMIT),
    ('PHOTO-19', 'R059'): tf([['Piazzolla', ['Medium']]], whole=SUMMIT, largest_only=True, opsz={'Piazzolla': [8]}),
    ('PHOTO-19', 'R061'): p19_value('Name', [['Inter', ['Medium']]]),
    ('PHOTO-19', 'R062'): p19_value('Role Line', INTER_REG),
    ('PHOTO-19', 'R063'): p19_value('Affiliation', INTER_REG),
    ('PHOTO-19', 'R064'): p19_value('Session', INTER_REG),
    ('PHOTO-19', 'R065'): p19_host_affiliation,
    ('PHOTO-19', 'R066'): tf(INTER_REG, patterns=[r'\bregist']),
}

# ------------------------------------------------------------------ PHOTO-20 talk announcement and banner


def p20_title(row, ctx):
    rec = ctx.records.get(row['output_id']) or {}
    return rec.get('Talk Title')


def p20_body(row, ctx):
    title = p20_title(row, ctx)
    return {'op': TF, 'fonts': INTER_REG, 'patterns': [r'\bspeaking at\b', r'Vellacourt\s*[-\u2013\u2014,]\s*Vellacourt'],
            'words': {'drop': title}} if title else None


def p20_event(row, ctx):
    rec = ctx.records.get(row['output_id']) or {}
    pats = [DATE_LONG] + ([re.escape(rec['Event Name'])] if rec.get('Event Name') else [])
    return {'op': TF, 'fonts': INTER_REG, 'patterns': pats}


def p20_talk(row, ctx):
    title = v1(row) if row.get('values', {}).get('1') else p20_title(row, ctx)
    return {'op': TF, 'fonts': [['Inter', ['Medium']]], 'shares': [title], 'words': {'phrase': title}} if title else None


P20 = {
    ('PHOTO-20', 'R073'): p20_body,
    ('PHOTO-20', 'R075'): p20_event,
    ('PHOTO-20', 'R083'): p20_talk,
}

# ------------------------------------------------------------------ PHOTO-24 watch key visual and product pages

CG_MED = [['Cormorant Garamond', ['Medium']]]
WORDMARK24 = ['Lunara', 'Chronometry', 'Lunara Chronometry']
REFERENCES = ['Meridian', 'Selene', 'Ardent', 'Halcyon', 'Vesper']
P24 = {
    ('PHOTO-24', 'R065'): tf(CG_MED, all_text=True, except_whole=WORDMARK24, except_roles=['body'], if_family=['Cormorant Garamond'],
                             optional=True),
    ('PHOTO-24', 'R073'): tf(CG_MED, whole=WORDMARK24),
    ('PHOTO-24', 'R074'): tf(CG_MED, whole=REFERENCES, largest_only=True),
    ('PHOTO-24', 'R079'): lambda row, ctx: {'op': TF, 'fonts': CG_MED, 'whole': [v1(row)], 'largest_only': True},
}

# ------------------------------------------------------------------ PHOTO-28 studio launch, class post, booking story

ARCHIVO_REG = [['Archivo', ['Regular']]]
INTER_MED = [['Inter', ['Medium']]]
FINE28 = dict(patterns=[PRICE, r'\bvalid\b', r'\bthrough\b', r'\buntil\b', r'\bexpires?\b'], roles=['fine'], except_whole=['Verda'])
P28 = {
    ('PHOTO-28', 'R080'): tf(ARCHIVO_REG, roles=['main'], except_whole=['Verda']),
    ('PHOTO-28', 'R081'): tf(INTER_REG, roles=['body'], except_whole=['Verda'], optional=True),
    ('PHOTO-28', 'R082'): const(dict({'op': TF, 'fonts': INTER_MED}, **FINE28)),
    ('PHOTO-28', 'R083'): tf([['Archivo', ['Regular']], ['Inter', ['Regular', 'Medium']]], all_text=True, except_whole=['Verda']),
    ('PHOTO-28', 'R085'): const(dict({'op': TF, 'fonts': INTER_MED, 'optional': True}, **FINE28)),
    ('PHOTO-28', 'R086'): tf(ARCHIVO_REG, roles=['main'], except_whole=['Verda']),
    ('PHOTO-28', 'R087'): const(dict({'op': TF, 'fonts': INTER_MED}, **FINE28)),
    ('PHOTO-28', 'R088'): tf(ARCHIVO_REG, roles=['secondary'], except_whole=['Verda'], optional=True),
}

# ------------------------------------------------------------------ LAYOUT-12 release posts

SORA_EB = [['Sora', ['ExtraBold']]]
DOORS = r'\bDOORS?\b'


def l12_rec(row, ctx):
    return ctx.records.get(row['output_id']) or {}


L12 = {
    ('LAYOUT-12', 'R121'): lambda row, ctx: {'op': TF, 'fonts': SORA_EB, 'whole': [v1(row)]},
    ('LAYOUT-12', 'R122'): lambda row, ctx: {'op': TF, 'fonts': [['Archivo Narrow', ['Regular']]], 'whole': [v1(row)]},
    ('LAYOUT-12', 'R123'): tf([['Archivo Narrow', ['SemiBold']]], patterns=[DOORS]),
    ('LAYOUT-12', 'R128'): tf(SORA_EB, patterns=[DATE_ANY]),
    ('LAYOUT-12', 'R129'): tf([['Archivo Narrow', ['Regular']]], patterns=[r'\bADVANCE\b']),
    ('LAYOUT-12', 'R149'): lambda row, ctx: {'op': 'v2_tracking_raster', 'a': {'patterns': [DATE_ANY]},
                                             'b': {'whole': [l12_rec(row, ctx)['headline']]}} if l12_rec(row, ctx).get('headline') else None,
    ('LAYOUT-12', 'R162'): lambda row, ctx: {'op': 'v2_tracking_raster', 'a': {'patterns': [DOORS]},
                                             'b': {'whole': ['with ' + l12_rec(row, ctx)['support']]}} if l12_rec(row, ctx).get('support') else None,
}

# ------------------------------------------------------------------ MOTION-11 thumbnails and channel videos


def m11_title(row, ctx):
    return ctx.suffix(row['output_id'])


def m11_words(which):
    def h(row, ctx):
        final = v1(row)
        family = 'Anton' if which == 'before' else 'Archivo Black'
        return {'op': TF, 'fonts': [[family, None]], 'part_of': [m11_title(row, ctx)], 'words': {which: final}}
    return h


def m11_name_word(row, ctx):
    family = re.sub(r'\s+Regular$', '', row['values']['2'].strip())
    return {'op': TF, 'fonts': [[family, None]], 'whole': [v1(row)]}


ANTON_AB = ['Anton', 'Archivo Black']
INTER_SB = [['Inter', ['SemiBold']]]
M11 = {
    ('MOTION-11', 'R080'): m11_words('before'),
    ('MOTION-11', 'R081'): m11_words('only'),
    ('MOTION-11', 'R087'): const({'op': TF, 'forbid': ANTON_AB, 'all_text': True, 'lowercase_only': True, 'optional': True}),
    ('MOTION-11', 'R088'): m11_name_word,
    ('MOTION-11', 'R090'): const({'op': TF, 'fonts': INTER_SB, 'all_text': True, 'frames': 'last',
                                 'except_whole': ['STATIC', 'FOX', 'STATIC FOX']}),
    ('MOTION-11', 'R096'): const({'op': TF, 'fonts': INTER_SB, 'all_text': True, 'unless_families': ANTON_AB}),
}

R3 = {**P04, **P06, **P08, **P10, **P19, **P20, **P24, **P28, **L12, **M11}

HOW = {
    'v2_typeface_raster': 'Reads each named line by OCR, renders its own text in every brand font and weight and in common stand-in fonts, '
                          'and compares the letter shapes and stroke thickness with the image; only a clear best match counts.',
    'v2_upright_raster': 'Reads each named line by OCR and measures the slant of its vertical strokes (upright, or leaning like italics).',
    'v2_tracking_raster': 'Fits each line\'s letter spacing from its letter positions in its best-matching font and compares the two lines.',
    'v2_not_stretched_raster': 'Fits each line in its best-matching fonts at natural width and at horizontal scales from 80% to 125%; '
                               'passes when natural width fits clearly best, otherwise a person looks.',
}


def convert(tid, rid, row, ctx):
    h = R3.get((tid, rid))
    return h(row, ctx) if h else None
