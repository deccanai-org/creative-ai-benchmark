"""Round 3 conversions for LAYOUT-15, LAYOUT-12, VECTOR-04 and MOTION-11 (2026-10-28): colour on images and PDFs,
rules that needed a definition, and the measurable rules first sorted as judgement.

One handler per (task, rule), taking (row, ctx) and returning an assertion for objective_ops (rounds 1 to 3 and
tools/auto_verifier/ops_r3_layout.py), or None when the row cannot be checked exactly; a rule moves only when every
row converts. Values come from the row's own wording, the deliverable's source record or the task's supplied files.

Definitions used (read the same way every time; see OPS_REFERENCE.md and ops_r3_layout.py):
- Ground or panel: a flat area of one colour covering 1% of the page or image or more, both sides at least 3% of
  its short side, photographs and type left out (a forbidden colour: also any area of 0.2% or more holding a line of
  text).
- Hairline, divider: a straight line 6 pt wide or less (PDF), or a piece at most thin_px across and 8 times as long
  (images); keyline: any other stroke 3 pt wide or less; chart mark: three or more filled shapes in one colour, each
  no more than 3% of the page, on a shared baseline or left edge.
- Body text: running lines at the body size (objective_ops_r3._roles); billing: lines naming a support act.
- Title words (MOTION-11): the words of the deliverable's own title, or of the channel name and the six upload
  titles on the films; an "Inter line" is any other line (title words are Anton or Archivo Black by the type
  system), so a line in another colour fails only where it has lowercase letters (display faces are set in capitals).
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
HEX = r'#[0-9A-Fa-f]{6}'
DATE_RX = (r'(?<!\d)\d{1,2}\s*(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\b'
           r'|\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s*\d{1,2}(?!\d)')


def hexes(row) -> list[str]:
    return [h.upper() for h in re.findall(HEX, row['check'])]


def const(a):
    return lambda row, ctx: dict(a)


def by_format(pdf=None, png=None, svg=None, mp4=None):
    """One assertion maker per file format of the row (None: that format is not converted)."""
    def h(row, ctx):
        ext = row['file'].rsplit('.', 1)[-1].lower()
        maker = {'pdf': pdf, 'png': png, 'svg': svg, 'mp4': mp4}.get(ext)
        return maker(row, ctx) if maker else None
    return h


def gate(check, full_width_image=False):
    return {'op': 'v2_gate', 'check': check, 'full_width_image': full_width_image}


def record(ctx, row) -> dict:
    return ctx.records.get(row['output_id'], {})


# ------------------------------------------------------------------ LAYOUT-15 Aldervale Mutual counter cards

NAVY, SLATE, PAPER, MIST, GREEN = '#1E2A3A', '#4A5560', '#F4F2EC', '#C7CBC8', '#3C6B54'


def l15_field(field):
    return lambda ctx, row: record(ctx, row).get(field)


def l15_prefix(text: str, chars=90) -> str:
    """The opening words of a long text (a disclosure runs over many lines; its first lines mark where it starts)."""
    out = ''
    for w in text.split():
        if len(out) >= chars:
            break
        out = f'{out} {w}'.strip()
    return out


def l15_rule_on_name(row, ctx):
    name = record(ctx, row).get('Producer Name')
    return {'op': 'v2_pdf_rule_at_text', 'text': name, 'hexes': [GREEN], 'where': 'on'} if name else None


def l15_rule_above_disclosure(row, ctx):
    text = record(ctx, row).get('Disclosure Text')
    return {'op': 'v2_pdf_rule_at_text', 'text': l15_prefix(text), 'hexes': [GREEN], 'where': 'above'} if text else None


def l15_text_colour(fields, colour):
    def h(row, ctx):
        rec = record(ctx, row)
        if not all(rec.get(f) for f in fields):
            return None
        return {'op': 'v2_pdf_text_colour', 'texts': [rec[f] for f in fields], 'colors': [colour]}
    return h


def l15_rules_match(row, ctx):
    ref = ctx.outputs.get('producer-card-r002', {}).get('path')
    return gate({'op': 'v2_pdf_rules_match', 'hexes': [GREEN], 'deliverable': ref}, full_width_image=True) if ref else None


# ------------------------------------------------------------------ LAYOUT-12 Umbra Loft

PITCH, ASH, SODIUM, COLD, BONE, BLOOD = '#0E0E10', '#2A2A2E', '#E4863B', '#3F7C8C', '#E9E4D8', '#8E2B24'
L12_PALETTE = [PITCH, ASH, SODIUM, COLD, BONE, BLOOD]
L12_PHOTOS = [f'umbra_archive_night_0{i}.jpg' for i in range(1, 7)]
SABLE, MERIDIAN = 'umbra_sable_wordmark_transparent.png', 'umbra_meridian_wordmark_transparent.png'
HEADLINERS = ['Sable Quartet', 'Meridian Brass', 'Night Ferry']


def l12_act(row, ctx):
    v = row.get('values') or {}
    return v['1'].strip().strip('“”"') if v.get('1') else record(ctx, row).get('headline')


def l12_supports(ctx) -> dict:
    return {r['values']['1']: r['values']['2'] for r in ctx.rules['R005']['rows'] if r.get('values')}


def l12_act_colour(row, ctx):
    act = l12_act(row, ctx)
    return {'op': 'v2_raster_text_colour', 'texts': [act], 'colors': [BONE], 'optional': False, 'exclude_assets': [SABLE, MERIDIAN]} if act else None


def l12_act_ground(row, ctx):
    act = l12_act(row, ctx)
    return {'op': 'v2_raster_text_colour', 'texts': [act], 'ground_must': [PITCH], 'optional': False, 'exclude_assets': [SABLE, MERIDIAN]} if act else None


def l12_other_lines(row, ctx):
    """Every line but the date line, the act name and the advance price (which may be Sodium) is Bone White."""
    act = record(ctx, row).get('headline')
    if not act:
        return None
    return {'op': 'v2_raster_text_colour', 'all_text': True, 'except': [act], 'except_patterns': [DATE_RX, r'\bADVANCE\b|[$€£]\s?\d'],
            'colors': [BONE], 'optional': False, 'exclude_assets': [SABLE, MERIDIAN]}


def l12_wordmark(mark, what):
    def pdf(row, ctx):
        return {'op': 'v2_asset_finish', 'asset': mark, 'ink' if what == 'ink' else 'ground': BONE if what == 'ink' else PITCH}
    def png(row, ctx):
        if what == 'ink':
            return {'op': 'v2_mark_colour_raster', 'asset': mark, 'colors': [BONE]}
        return {'op': 'v2_mark_on_ground', 'asset': mark, 'grounds': [PITCH]}
    return by_format(pdf=pdf, png=png)


def l12_headliners_larger(row, ctx):
    rest = [a for a in ctx.acts if a not in HEADLINERS]
    if len(rest) < 3:
        return None
    return {'op': 'v2_all_of', 'checks': [{'op': 'v2_size_vs', 'rel': 'larger', 'a': [h], 'b': rest} for h in HEADLINERS]}


# ------------------------------------------------------------------ VECTOR-04 Meridian & Ash stickers

ROAST, KRAFT, ASHG, CREAM, BRICK, INK = '#3E2A20', '#C8A97E', '#5B6B54', '#F3E7D3', '#A8442E', '#201914'
V04_PALETTE = [ROAST, KRAFT, ASHG, CREAM, BRICK, INK]


def v04_master(name=None):
    def h(row, ctx):
        file = name or (row.get('values') or {}).get('2')
        out = next((o for o in ctx.outputs.values() if o['path'].endswith('/' + file)), None) if file else None
        return {'op': 'v2_placed_master', 'deliverable': out['path'], 'hexes': V04_PALETTE} if out else None
    return h


def v04_main_ink(*inks):
    return const({'op': 'v2_main_ink', 'hexes': list(inks), 'grounds': [KRAFT, CREAM]})


# ------------------------------------------------------------------ MOTION-11 STATIC FOX

ORANGE, PURPLE, ACID, JET, WHITE = '#FF5A1F', '#7A2FF2', '#B6FF2E', '#101014', '#FFFFFF'
M11_PALETTE = [ORANGE, PURPLE, ACID, JET, WHITE]
FILLS = [WHITE, ACID, ORANGE]
SCRAP = 'staticfox_scrap_transparent.png'
UPLOADS = ['WE BROKE THE MAP', 'EVERYONE OFF THE PLATFORM', 'KITCHEN. GONE.', 'DO NOT OPEN THAT DOOR',
           'WE SPENT SIX HOURS BUILDING A BRIDGE AND THEN DROVE STRAIGHT PAST IT',
           'I GAVE MY TEAM ONE SIMPLE JOB AND THEY SET THE ENTIRE BASE ON FIRE']
ALL_TITLE_WORDS = sorted({w for t in UPLOADS + ['STATIC FOX'] for w in t.split()})


def m11_title(row, ctx):
    name = ctx.outputs[row['output_id']]['name']
    return name.split(' - ', 1)[1] if ' - ' in name and 'thumbnail' in row['output_id'] else None


def m11_capture(row, ctx):
    """The capture a thumbnail is built on: thumbnail titles 1 to 6 match captures 01 to 06 (the brief)."""
    title = m11_title(row, ctx)
    if title not in UPLOADS:
        return None
    return f'staticfox_captures/staticfox_capture_0{UPLOADS.index(title) + 1}.mp4'


def m11_title_letters(mode, title=None):
    def h(row, ctx):
        t = title or m11_title(row, ctx)
        if not t:
            return None
        return {'op': 'v2_title_letters', 'title': t, 'mode': mode, 'fills': FILLS, 'outline': JET}
    return h


def m11_with_capture(a):
    def h(row, ctx):
        cap = m11_capture(row, ctx)
        return dict(a, capture=cap) if cap else None
    return h


def m11_inter(grounds, colors):
    """Lines other than title words on the ground are in the colours; a line in another colour fails only where it
    has lowercase letters (so it cannot be a display-face title word), otherwise a person looks."""
    def h(row, ctx):
        title = m11_title(row, ctx)
        words = title.split() if title else ALL_TITLE_WORDS
        a = {'op': 'v2_raster_text_colour', 'all_text': True, 'except_words': words, 'grounds': grounds, 'colors': colors,
             'fail_if': r'[a-z]', 'photos': [SCRAP]}
        if m11_capture(row, ctx):
            a['capture'] = m11_capture(row, ctx)
        return a
    return h


# ------------------------------------------------------------------ new batch helpers (measurable judgement rules)

L15_ALLOWED_EXTRA = ['Aldervale Mutual']
PREMIUM = r'[$€£]\s?\d|\bper\s+month\b|/\s*mo(?:nth)?\b|\bmonthly\b'
RATE_VALUES = r'(?<![\d.])(?:1\.86|2\.41|41\.50?|46|2\.94|3\.72|54\.25|3\.87|4\.86|67(?:\.00)?|5\.12|6\.44|88\.50?|6\.98|8\.71|122)(?![\d.])'
PLANS = ['Heritage Whole Life', 'Evergreen Whole Life', 'Final Expense Direct']
LEXEND, SERIF4, PLEX = 'fonts/Lexend[wght].ttf', 'fonts/SourceSerif4[opsz,wght].ttf', 'fonts/IBMPlexSans[wdth,wght].ttf'


def l15_copy(row, ctx):
    rec = record(ctx, row)
    return [rec[f] for f in ('Producer Name', 'License Line', 'Office', 'Disclosure Text') if rec.get(f)] + L15_ALLOWED_EXTRA


def l15_photo(row, ctx):
    return (row.get('values') or {}).get('1') or ctx.outputs[row['output_id']].get('source_image')


def l15_only_supplied(row, ctx):
    photo = ctx.outputs[row['output_id']].get('source_image')
    return {'op': 'v2_only_supplied', 'texts': l15_copy(row, ctx), 'images': [photo] if photo else []}


def l15_roster(name):
    import csv
    for d in (REFRESH / 'sources/LAYOUT-15', ROOT.parents[1] / 'benchmark_runs/pilot_v7_hybrid_2026-09-28/LAYOUT-15/source'):
        f = d / 'producer_roster_northern.csv'
        if f.is_file():
            for r in csv.DictReader(f.open(encoding='utf-8-sig')):
                if r['Producer Name'] == name:
                    return r
    return None


def l15_resigned(row, ctx):
    r = l15_roster('Maureen Alcott')
    if not r:
        return None
    return {'op': 'v2_all_of', 'checks': [{'op': 'v2_text_absent', 'texts': ['Maureen Alcott', r['License Line'].split('#')[-1], r['Office'].split(',')[0]]},
                                          {'op': 'v2_lacks_asset', 'assets': [r['Photo File']]}]}


def l15_cards(ctx):
    return {o['source_record']['values']['Producer Name']: o['path'] for o in ctx.outputs.values()
            if (o.get('source_record') or {}).get('values', {}).get('Producer Name')}


def l15_font(field, font, wght, family, weight, **extra):
    def h(row, ctx):
        texts = [record(ctx, row)[f] for f in field if record(ctx, row).get(f)] if field else []
        if field and len(texts) != len(field):
            return None
        a = {'op': 'v2_font_is', 'font': font, 'axes': {'wght': wght}, 'family': family, 'weight': weight}
        if texts:
            a['texts'] = texts
        return dict(a, **extra)
    return h


def l15_vs_r002(row, ctx):
    ref = ctx.outputs.get('producer-card-r002')
    mine, theirs = record(ctx, row).get('Disclosure Text'), (ref or {}).get('source_record', {}).get('values', {}).get('Disclosure Text')
    if not (ref and mine and theirs):
        return None
    return {'op': 'v2_text_size_vs_file', 'text': mine, 'deliverable': ref['path'], 'other_text': theirs}


ARCHIVE_02_05 = ['umbra_archive_night_02.jpg', 'umbra_archive_night_05.jpg']
L12_POSTERS = ['deliverables/poster-direction-type-led.pdf', 'deliverables/poster-direction-image-led.pdf', 'deliverables/poster-direction-graphic-led.pdf']


def l12_record_act(row, ctx):
    return record(ctx, row).get('headline')


def l12_mark_beside(row, ctx):
    a = {'op': 'v2_mark_beside', 'assets': [SABLE, 'umbra_wordmark_nightferry.jpg'], 'acts': list(ctx.acts), 'own': 'Sable Quartet', 'forbid': 'Night Ferry'}
    if row['file'].endswith('.png'):
        a.update(text_absent=True, words=['SABLE', 'QUARTET'])
    return a



def v04_path(ctx, name):
    out = next((o for o in ctx.outputs.values() if name and o['path'].endswith('/' + name)), None)
    return out['path'] if out else None


def v04_proof_master(ctx, row):
    """The SVG master of a proof: sticker-proof-<x>.png is recovered-sticker-<x>.svg or new-sticker-<x>.svg."""
    stem = row['output_id'].replace('sticker-proof-', '')
    return v04_path(ctx, f'recovered-sticker-{stem}.svg') or v04_path(ctx, f'new-sticker-{stem}.svg')



def m11_final(row, ctx):
    v = (row.get('values') or {}).get('1')
    if v:
        return v.strip().strip('“”"')
    t = m11_title(row, ctx)
    return t.split()[-1] if t else None


def m11_setup(row, ctx):
    t = m11_title(row, ctx)
    return [w for w in t.split()[:-1] if len(re.sub(r'\W', '', w)) >= 2] if t else None


R3 = {
    # LAYOUT-15
    ('LAYOUT-15', 'R025'): l15_rule_on_name,
    ('LAYOUT-15', 'R026'): lambda row, ctx: gate({'op': 'v2_palette_only', 'hexes': hexes(row)}) if len(hexes(row)) == 5 else None,
    ('LAYOUT-15', 'R027'): const({'op': 'v2_grounds', 'hexes': [PAPER]}),
    ('LAYOUT-15', 'R028'): const({'op': 'v2_pdf_colour_use', 'hexes': [GREEN], 'mode': 'only', 'allow': ['rule'], 'full_width': True, 'count': 2}),
    ('LAYOUT-15', 'R030'): const({'op': 'v2_pdf_colour_use', 'hexes': [GREEN], 'mode': 'only', 'allow': ['rule'], 'full_width': True, 'count': 2}),
    ('LAYOUT-15', 'R032'): l15_rule_above_disclosure,
    ('LAYOUT-15', 'R033'): l15_text_colour(['Producer Name'], NAVY),
    ('LAYOUT-15', 'R034'): l15_text_colour(['Disclosure Text'], NAVY),
    ('LAYOUT-15', 'R035'): l15_text_colour(['License Line', 'Office'], SLATE),
    ('LAYOUT-15', 'R036'): const({'op': 'v2_pdf_colour_use', 'hexes': [MIST], 'mode': 'only', 'allow': ['rule', 'keyline']}),
    ('LAYOUT-15', 'R037'): const({'op': 'v2_pdf_photo_overlay'}),
    ('LAYOUT-15', 'R038'): l15_rules_match,
    ('LAYOUT-15', 'R039'): const({'op': 'v2_pdf_colour_use', 'hexes': [MIST], 'mode': 'only', 'allow': ['rule', 'keyline']}),
    ('LAYOUT-15', 'R040'): const({'op': 'v2_pdf_colour_use', 'hexes': [GREEN], 'mode': 'thickness', 'thickness': 1.0}),
    ('LAYOUT-15', 'R041'): const({'op': 'v2_pdf_area_share', 'hexes': [GREEN, MIST], 'max_pct': 5}),
    ('LAYOUT-15', 'R042'): const({'op': 'v2_pdf_text_colour', 'all_text': True, 'colors': [NAVY, SLATE]}),
    ('LAYOUT-15', 'R043'): const({'op': 'v2_pdf_colour_use', 'hexes': [NAVY, SLATE, PAPER], 'mode': 'none_of', 'forbid': ['rule', 'keyline', 'frame']}),
    # LAYOUT-12
    ('LAYOUT-12', 'R079'): const({'op': 'v2_grounds', 'hexes': [PITCH, ASH], 'photos': L12_PHOTOS}),
    ('LAYOUT-12', 'R080'): by_format(pdf=const({'op': 'v2_pdf_colour_use', 'hexes': [COLD, BLOOD], 'mode': 'only', 'allow': ['rule']}),
                                     png=const({'op': 'v2_raster_roles', 'hexes': [COLD, BLOOD], 'photos': L12_PHOTOS})),
    ('LAYOUT-12', 'R082'): l12_act_colour,
    ('LAYOUT-12', 'R083'): const({'op': 'v2_raster_palette', 'hexes': L12_PALETTE, 'photos': L12_PHOTOS}),
    ('LAYOUT-12', 'R088'): const({'op': 'v2_grounds', 'hexes': [PITCH, ASH]}),
    ('LAYOUT-12', 'R090'): const({'op': 'v2_pdf_colour_use', 'hexes': [COLD, BLOOD], 'mode': 'only', 'allow': ['rule', 'chart']}),
    ('LAYOUT-12', 'R093'): by_format(pdf=const({'op': 'v2_pdf_area_share', 'hexes': [COLD, BLOOD], 'max_pct': 5}),
                                     png=const({'op': 'v2_raster_share', 'hexes': [COLD, BLOOD], 'max_pct': 5, 'photos': L12_PHOTOS})),
    ('LAYOUT-12', 'R094'): l12_wordmark(SABLE, 'ink'),
    ('LAYOUT-12', 'R095'): l12_wordmark(MERIDIAN, 'ink'),
    ('LAYOUT-12', 'R096'): by_format(pdf=const(gate({'op': 'v2_main_ground', 'hex': PITCH})),
                                     png=const({'op': 'v2_grounds', 'hexes': [PITCH], 'main': True, 'main_only': True, 'photos': L12_PHOTOS})),
    ('LAYOUT-12', 'R102'): const({'op': 'v2_raster_text_colour', 'patterns': [DATE_RX], 'colors': [SODIUM], 'optional': False, 'largest_only': True}),
    ('LAYOUT-12', 'R103'): l12_other_lines,
    ('LAYOUT-12', 'R104'): lambda row, ctx: {'op': 'v2_photo_pair_same', 'deliverable': ctx.outputs['release-post-r002']['path'], 'hexes': L12_PALETTE,
                                             'assets': L12_PHOTOS, 'exclude': [SABLE, MERIDIAN]} if 'release-post-r002' in ctx.outputs else None,
    ('LAYOUT-12', 'R107'): l12_act_ground,
    ('LAYOUT-12', 'R108'): l12_wordmark(SABLE, 'ground'),
    ('LAYOUT-12', 'R109'): l12_wordmark(MERIDIAN, 'ground'),
    # body and billing on a poster: the support-act lines and every line at their size (the brief sets both at 14 pt)
    ('LAYOUT-12', 'R113'): lambda row, ctx: {'op': 'v2_line_chars', 'max_chars': 65, 'scope': 'billing', 'texts': list(l12_supports(ctx).values())},
    ('LAYOUT-12', 'R114'): const({'op': 'v2_line_chars', 'max_chars': 65, 'scope': 'body'}),
    ('LAYOUT-12', 'R116'): lambda row, ctx: {'op': 'v2_role_font', 'texts': list(l12_supports(ctx).values()), 'family': 'Archivo Narrow', 'weight': 'Regular'},
    ('LAYOUT-12', 'R119'): lambda row, ctx: {'op': 'v2_role_font', 'roles': ['body', 'chart'], 'texts': list(l12_supports(ctx).values()), 'optional': True,
                                             'except_patterns': [DATE_RX, r'\bDOORS?\b'], 'family': 'Archivo Narrow', 'weight': 'Regular'},
    ('LAYOUT-12', 'R131'): const({'op': 'v2_line_chars', 'max_chars': 65, 'scope': 'body'}),
    ('LAYOUT-12', 'R159'): const({'op': 'v2_tracking_vs_body', 'pattern': r'\bDOORS?\b', 'optional': True}),
    ('LAYOUT-12', 'R166'): by_format(pdf=const({'op': 'v2_pdf_photo_overlay'}),
                                     png=const({'op': 'v2_raster_photo_overlay', 'photos': L12_PHOTOS})),
    ('LAYOUT-12', 'R177'): l12_headliners_larger,
    # VECTOR-04
    ('VECTOR-04', 'R030'): const({'op': 'v2_pdf_cut_spot'}),
    ('VECTOR-04', 'R047'): v04_master('recovered-sticker-window-mark.svg'),
    ('VECTOR-04', 'R048'): v04_master(),
    ('VECTOR-04', 'R049'): v04_master(),
    ('VECTOR-04', 'R057'): const({'op': 'v2_raster_palette', 'hexes': V04_PALETTE, 'transparent_only': True}),
    ('VECTOR-04', 'R058'): v04_main_ink(ROAST),
    ('VECTOR-04', 'R059'): v04_main_ink(ASHG),
    ('VECTOR-04', 'R060'): v04_main_ink(BRICK),
    ('VECTOR-04', 'R061'): v04_main_ink(ROAST, ASHG, BRICK),
    ('VECTOR-04', 'R062'): const({'op': 'v2_raster_text_colour', 'all_text': True, 'grounds': [CREAM, KRAFT], 'colors': [ROAST, ASHG], 'primary': [ROAST]}),
    ('VECTOR-04', 'R063'): const({'op': 'v2_pdf_managed_palette', 'hexes': V04_PALETTE, 'icc': 'PSOcoated_v3.icc'}),
    ('VECTOR-04', 'R065'): const({'op': 'v2_pdf_labels_colour', 'colors': [ROAST], 'secondary': [ASHG]}),
    ('VECTOR-04', 'R070'): const({'op': 'v2_raster_text_colour', 'all_text': True, 'grounds': [CREAM, KRAFT], 'colors': [ROAST, ASHG], 'primary': [ROAST]}),
    ('VECTOR-04', 'R074'): const({'op': 'v2_ink_detail', 'hexes': [INK]}),
    ('VECTOR-04', 'R080'): const({'op': 'v2_pdf_process_only'}),
    ('VECTOR-04', 'R082'): const({'op': 'v2_raster_text_colour', 'all_text': True, 'grounds': [ROAST, ASHG], 'colors': [CREAM]}),
    ('VECTOR-04', 'R087'): const({'op': 'v2_line_chars', 'max_chars': 65, 'scope': 'all'}),
    # body copy: Libre Franklin; flat title: DM Serif Display under 14.5 pt; display lettering: DM Serif Display at
    # 14.5 pt or more (type scale steps 03, 02 and 01: 7, 11 and 18 pt); baselines within 0.1 mm of the leading
    ('VECTOR-04', 'R093'): const({'op': 'v2_svg_leading', 'family': r'libre\s*franklin', 'size_pt': [0, 999], 'leading_mm': 3.704}),
    ('VECTOR-04', 'R094'): const({'op': 'v2_svg_leading', 'family': r'dm\s*serif', 'size_pt': [0, 14.5], 'leading_mm': 4.586}),
    ('VECTOR-04', 'R096'): const({'op': 'v2_svg_leading', 'family': r'dm\s*serif', 'size_pt': [14.5, 999], 'leading_mm': 7.056}),
    # MOTION-11
    ('MOTION-11', 'R055'): m11_title_letters('outline'),
    ('MOTION-11', 'R056'): m11_title_letters('fill'),
    ('MOTION-11', 'R057'): m11_with_capture({'op': 'v2_raster_palette', 'hexes': M11_PALETTE, 'photos': [SCRAP]}),
    ('MOTION-11', 'R059'): m11_with_capture({'op': 'v2_raster_present', 'hexes': [ORANGE], 'photos': [SCRAP]}),
    ('MOTION-11', 'R060'): m11_inter([JET], [WHITE, ACID, ORANGE]),
    ('MOTION-11', 'R061'): m11_inter([PURPLE], [WHITE, ACID]),
    ('MOTION-11', 'R062'): m11_inter([WHITE], [JET, PURPLE]),
    ('MOTION-11', 'R063'): m11_inter([ORANGE], [JET]),
    ('MOTION-11', 'R064'): m11_with_capture({'op': 'v2_no_panel', 'hexes': [ACID], 'photos': [SCRAP]}),
    ('MOTION-11', 'R065'): m11_with_capture({'op': 'v2_raster_share', 'hexes': [ACID], 'max_pct': 10}),
    ('MOTION-11', 'R066'): m11_title_letters('outline', 'STATIC FOX'),
    ('MOTION-11', 'R067'): m11_title_letters('fill', 'STATIC FOX'),
    ('MOTION-11', 'R068'): const({'op': 'v2_raster_palette', 'hexes': M11_PALETTE, 'photos': [SCRAP]}),
    ('MOTION-11', 'R069'): const({'op': 'v2_raster_present', 'hexes': [ORANGE], 'photos': [SCRAP]}),
    ('MOTION-11', 'R070'): m11_inter([ORANGE], [JET]),
    ('MOTION-11', 'R071'): const({'op': 'v2_no_panel', 'hexes': [ACID], 'photos': [SCRAP]}),
    ('MOTION-11', 'R072'): const({'op': 'v2_raster_share', 'hexes': [ACID], 'max_pct': 10, 'whole_frame': True, 'except_words': ['STATIC', 'FOX'],
                                 'photos': [SCRAP]}),
    # every line of the teaser filled White, Acid or Orange covers every Anton or Archivo Black word; otherwise a person
    ('MOTION-11', 'R074'): const({'op': 'v2_raster_text_colour', 'all_text': True, 'colors': FILLS, 'fail_if': r'(?!)', 'need_confident': True,
                                 'optional': False}),
    ('MOTION-11', 'R075'): const({'op': 'v2_raster_palette', 'hexes': M11_PALETTE, 'photos': [SCRAP]}),
    ('MOTION-11', 'R076'): const({'op': 'v2_raster_present', 'hexes': [ORANGE], 'photos': [SCRAP]}),
    ('MOTION-11', 'R077'): const({'op': 'v2_raster_share', 'hexes': [ACID], 'max_pct': 10, 'except_words': ALL_TITLE_WORDS, 'photos': [SCRAP]}),
    ('MOTION-11', 'R078'): lambda row, ctx: {'op': 'v2_capture_wash', 'capture': m11_capture(row, ctx)} if m11_capture(row, ctx) else None,
    # a title stack: lines made only of the words of the channel name or of one upload title (staticfox_titles.txt)
    ('MOTION-11', 'R121'): const({'op': 'v2_title_largest', 'titles': ['STATIC FOX'] + UPLOADS}),
    # ---------------------------------------------------------------- new batch: LAYOUT-15
    ('LAYOUT-15', 'R002'): const({'op': 'v2_text_absent', 'patterns': {'premium': PREMIUM, 'rate value': RATE_VALUES}, 'found_is': 'person'}),
    ('LAYOUT-15', 'R003'): lambda row, ctx: {'op': 'v2_inside_trim', 'text': record(ctx, row)['Disclosure Text'], 'ending': 'claims-paying ability of the company.'}
                                            if record(ctx, row).get('Disclosure Text') else None,
    ('LAYOUT-15', 'R004'): lambda row, ctx: {'op': 'v2_combined_pages', 'width_mm': 148, 'height_mm': 210, 'cards': l15_cards(ctx)},
    ('LAYOUT-15', 'R007'): l15_only_supplied,
    ('LAYOUT-15', 'R008'): lambda row, ctx: {'op': 'v2_images_are', 'assets': [l15_photo(row, ctx)]} if l15_photo(row, ctx) else None,
    ('LAYOUT-15', 'R009'): lambda row, ctx: {'op': 'v2_all_of', 'checks': [{'op': 'v2_text_absent', 'texts': ['district', 'Central Vermont']}, l15_only_supplied(row, ctx)]},
    ('LAYOUT-15', 'R010'): l15_only_supplied,
    ('LAYOUT-15', 'R011'): const({'op': 'v2_images_are', 'assets': []}),
    ('LAYOUT-15', 'R012'): lambda row, ctx: {'op': 'v2_inside_trim', 'text': record(ctx, row)['Disclosure Text'], 'ending': row['values']['1'].strip('“”"')}
                                            if record(ctx, row).get('Disclosure Text') and (row.get('values') or {}).get('1') else None,
    ('LAYOUT-15', 'R013'): const({'op': 'v2_text_absent', 'texts': PLANS, 'patterns': {'premium': PREMIUM, 'rate value': RATE_VALUES}, 'found_is': 'person'}),
    ('LAYOUT-15', 'R015'): l15_resigned,
    ('LAYOUT-15', 'R016'): l15_only_supplied,
    ('LAYOUT-15', 'R019'): lambda row, ctx: {'op': 'v2_photo_proportions', 'asset': l15_photo(row, ctx)} if l15_photo(row, ctx) else None,
    # the sign (tree, PINEBROOK SAVINGS, Member Service Desk) in producer_headshot_08.jpg's own pixels, read by OCR
    ('LAYOUT-15', 'R023'): const({'op': 'v2_region_kept', 'asset': 'producer_headshot_08.jpg', 'box': [1700, 440, 2990, 1130]}),
    ('LAYOUT-15', 'R029'): lambda row, ctx: {'op': 'v2_photo_natural', 'photo': l15_photo(row, ctx)} if l15_photo(row, ctx) else None,
    ('LAYOUT-15', 'R031'): const({'op': 'v2_images_are', 'assets': []}),
    ('LAYOUT-15', 'R044'): l15_font(['Producer Name'], LEXEND, 600, 'Lexend', 'SemiBold'),
    ('LAYOUT-15', 'R045'): l15_font(['License Line', 'Office'], SERIF4, 400, 'Source Serif 4', 'Regular', skip_digits=True),
    ('LAYOUT-15', 'R046'): l15_font([], PLEX, 400, 'IBM Plex Sans', 'Regular', digits=True, digits_only=True),
    ('LAYOUT-15', 'R048'): l15_font(['Disclosure Text'], SERIF4, 400, 'Source Serif 4', 'Regular', skip_digits=True),
    ('LAYOUT-15', 'R049'): const({'op': 'v2_text_absent', 'patterns': {'premium': PREMIUM}, 'found_is': 'person'}),
    ('LAYOUT-15', 'R050'): lambda row, ctx: {'op': 'v2_digit_size', 'texts': [record(ctx, row)['License Line'], record(ctx, row)['Office']]}
                                            if record(ctx, row).get('License Line') else None,
    # 9 pt leading, read from glyph origins to within 0.25 pt
    ('LAYOUT-15', 'R051'): lambda row, ctx: {'op': 'v2_text_leading', 'text': record(ctx, row)['Disclosure Text'], 'leading_pt': 9, 'tol_pt': 0.25}
                                            if record(ctx, row).get('Disclosure Text') else None,
    ('LAYOUT-15', 'R053'): const({'op': 'v2_pdf_solid_all'}),
    # not letterspaced: 0.002 em or tighter passes (the type scale sets -5 units); +25 units (0.025 em) or more fails
    ('LAYOUT-15', 'R054'): lambda row, ctx: {'op': 'v2_tracking_of', 'text': record(ctx, row)['Producer Name'], 'pass_em': 0.002, 'fail_em': 0.025}
                                            if record(ctx, row).get('Producer Name') else None,
    ('LAYOUT-15', 'R055'): l15_only_supplied,
    ('LAYOUT-15', 'R056'): l15_vs_r002,
    ('LAYOUT-15', 'R057'): l15_only_supplied,
    ('LAYOUT-15', 'R060'): lambda row, ctx: {'op': 'v2_text_smallest', 'text': record(ctx, row)['Disclosure Text']} if record(ctx, row).get('Disclosure Text') else None,
    # ---------------------------------------------------------------- new batch: LAYOUT-12
    ('LAYOUT-12', 'R016'): const({'op': 'v2_text_anywhere', 'expected': [r'\btype[\s-]*led\b', r'\bimage[\s-]*led\b', r'\bgraphic[\s-]*led\b']}),
    ('LAYOUT-12', 'R040'): lambda row, ctx: {'op': 'v2_inside_all', 'texts': [l12_record_act(row, ctx)]} if l12_record_act(row, ctx) else None,
    ('LAYOUT-12', 'R044'): const({'op': 'v2_text_present', 'expected': ['Night Ferry'], 'any_case': True, 'forbidden': ['NightFerry']}),
    ('LAYOUT-12', 'R045'): lambda row, ctx: {'op': 'v2_artwork_only', 'texts': [a for a in ctx.acts if a not in HEADLINERS], 'assets': L12_PHOTOS + [SABLE, MERIDIAN]},
    ('LAYOUT-12', 'R048'): const({'op': 'v2_numbers_from', 'sources': ['umbra_room_specs.txt', 'umbra_billing_autumn.txt', 'umbra_nights_autumn.csv'],
                                 'extra': [2021, 18, 32, 250]}),
    ('LAYOUT-12', 'R052'): const({'op': 'v2_chart_scale', 'values': [168, 201, 187, 224, 142, 176]}),
    ('LAYOUT-12', 'R057'): l12_mark_beside,
    ('LAYOUT-12', 'R061'): l12_mark_beside,
    ('LAYOUT-12', 'R063'): const({'op': 'v2_images_are', 'assets': L12_PHOTOS + [SABLE, MERIDIAN]}),
    ('LAYOUT-12', 'R065'): const({'op': 'v2_photo_as_shot', 'assets': L12_PHOTOS, 'exclude': [SABLE, MERIDIAN], 'match_only': True}),
    ('LAYOUT-12', 'R066'): const({'op': 'v2_images_are', 'assets': L12_PHOTOS + [SABLE, MERIDIAN], 'deliverables': L12_POSTERS}),
    ('LAYOUT-12', 'R069'): const({'op': 'v2_mark_letters', 'asset': SABLE}),
    # proportions: aspect within 2% passes, 4% or more off fails
    ('LAYOUT-12', 'R070'): const({'op': 'v2_photo_proportions', 'asset': SABLE}),
    ('LAYOUT-12', 'R071'): const({'op': 'v2_photo_proportions', 'asset': MERIDIAN}),
    ('LAYOUT-12', 'R073'): const({'op': 'v2_mark_letters', 'asset': SABLE}),
    ('LAYOUT-12', 'R074'): lambda row, ctx: {'op': 'v2_photo_proportions', 'asset': row['values']['2']} if (row.get('values') or {}).get('2') else None,
    ('LAYOUT-12', 'R076'): const({'op': 'v2_photo_two_colour', 'hexes': L12_PALETTE, 'exclude': [SABLE, MERIDIAN], 'assets': L12_PHOTOS}),
    ('LAYOUT-12', 'R081'): const({'op': 'v2_photo_two_colour', 'hexes': L12_PALETTE, 'exclude': [SABLE, MERIDIAN], 'assets': L12_PHOTOS}),
    ('LAYOUT-12', 'R084'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_raster_palette', 'hexes': L12_PALETTE, 'photos': L12_PHOTOS},
                                                               {'op': 'v2_soft_edges', 'photos': L12_PHOTOS}]}),
    ('LAYOUT-12', 'R085'): const({'op': 'v2_photo_two_colour', 'hexes': L12_PALETTE, 'exclude': [SABLE, MERIDIAN], 'assets': L12_PHOTOS, 'deliverables': L12_POSTERS}),
    ('LAYOUT-12', 'R089'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_pdf_solid_all'}, {'op': 'v2_palette_only', 'hexes': L12_PALETTE},
                                                               {'op': 'v2_images_are', 'assets': L12_PHOTOS + [SABLE, MERIDIAN], 'deliverables': L12_POSTERS}]}),
    ('LAYOUT-12', 'R139'): const({'op': 'v2_caps', 'texts': ['UMBRA', 'LOFT'], 'largest_only': True}),
    ('LAYOUT-12', 'R144'): lambda row, ctx: {'op': 'v2_caps', 'texts': [l12_act(row, ctx)], 'largest_only': True} if l12_act(row, ctx) else None,
    ('LAYOUT-12', 'R145'): const({'op': 'v2_caps', 'patterns': [r'\bDOORS?\b']}),
    ('LAYOUT-12', 'R146'): const({'op': 'v2_caps', 'patterns': [DATE_RX]}),
    ('LAYOUT-12', 'R148'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_pdf_solid_all'}, {'op': 'v2_palette_only', 'hexes': L12_PALETTE},
                                                               {'op': 'v2_images_are', 'assets': L12_PHOTOS + [SABLE, MERIDIAN]}]}),
    ('LAYOUT-12', 'R156'): const({'op': 'v2_title_stack', 'top': 'UMBRA', 'bottom': 'LOFT'}),
    ('LAYOUT-12', 'R167'): const({'op': 'v2_mark_not_retyped', 'asset': MERIDIAN, 'text': 'Meridian Brass'}),
    ('LAYOUT-12', 'R168'): const({'op': 'v2_photo_as_shot', 'assets': L12_PHOTOS, 'exclude': [SABLE, MERIDIAN]}),
    ('LAYOUT-12', 'R169'): const({'op': 'v2_clipped_flat', 'assets': ARCHIVE_02_05}),
    ('LAYOUT-12', 'R170'): const({'op': 'v2_photo_as_shot', 'assets': L12_PHOTOS, 'exclude': [SABLE, MERIDIAN]}),
    ('LAYOUT-12', 'R171'): const({'op': 'v2_mark_not_retyped', 'asset': MERIDIAN, 'text': 'Meridian Brass'}),
    ('LAYOUT-12', 'R172'): const({'op': 'v2_photo_as_shot', 'assets': L12_PHOTOS, 'exclude': [SABLE, MERIDIAN], 'deliverables': L12_POSTERS}),
    ('LAYOUT-12', 'R173'): const({'op': 'v2_clipped_flat', 'assets': ARCHIVE_02_05, 'deliverables': L12_POSTERS}),
    ('LAYOUT-12', 'R174'): const({'op': 'v2_mark_not_retyped', 'asset': SABLE, 'text': 'Sable Quartet'}),
    # ---------------------------------------------------------------- new batch: VECTOR-04
    ('VECTOR-04', 'R001'): lambda row, ctx: {'op': 'v2_proof_vs_svg', 'deliverable': v04_path(ctx, row['values']['1']), 'mode': 'same'}
                                            if v04_path(ctx, (row.get('values') or {}).get('1')) else None,
    ('VECTOR-04', 'R009'): lambda row, ctx: {'op': 'v2_svg_cut_file', 'mode': 'one', 'deliverable': v04_path(ctx, row['values']['1'])}
                                            if v04_path(ctx, (row.get('values') or {}).get('1')) else None,
    ('VECTOR-04', 'R010'): const({'op': 'v2_sheet_cuts', 'mode': 'margin', 'min_mm': 10}),
    ('VECTOR-04', 'R011'): const({'op': 'v2_sheet_cuts', 'mode': 'gutter', 'min_mm': 6}),
    ('VECTOR-04', 'R012'): const({'op': 'v2_sheet_cuts', 'mode': 'art_margin', 'min_mm': 10}),
    ('VECTOR-04', 'R013'): const({'op': 'v2_sheet_cuts', 'mode': 'art_size', 'long_mm': 55}),
    ('VECTOR-04', 'R017'): const({'op': 'v2_svg_viewbox'}),
    ('VECTOR-04', 'R018'): lambda row, ctx: {'op': 'v2_proof_vs_svg', 'deliverable': v04_proof_master(ctx, row), 'mode': 'transparent'}
                                            if v04_proof_master(ctx, row) else None,
    ('VECTOR-04', 'R020'): const({'op': 'v2_svg_cut_file', 'mode': 'name'}),
    ('VECTOR-04', 'R021'): const({'op': 'v2_svg_cut_file', 'mode': 'only'}),
    ('VECTOR-04', 'R024'): const({'op': 'v2_sheet_cuts', 'mode': 'layer'}),
    ('VECTOR-04', 'R025'): const({'op': 'v2_sheet_cuts', 'mode': 'count', 'count': 6}),
    ('VECTOR-04', 'R028'): const({'op': 'v2_sheet_cuts', 'mode': 'count', 'count': 6}),
    ('VECTOR-04', 'R032'): const({'op': 'v2_sheet_cuts', 'mode': 'name'}),
    ('VECTOR-04', 'R035'): const({'op': 'v2_built_from_raster', 'photo': 'meridian_bag_moth.jpg', 'others': ['meridian_bag_pourover.jpg', 'meridian_bag_ridgeline.jpg']}),
    ('VECTOR-04', 'R036'): const({'op': 'v2_built_from_raster', 'photo': 'meridian_bag_pourover.jpg', 'others': ['meridian_bag_moth.jpg', 'meridian_bag_ridgeline.jpg']}),
    ('VECTOR-04', 'R037'): const({'op': 'v2_built_from_raster', 'photo': 'meridian_bag_ridgeline.jpg', 'others': ['meridian_bag_moth.jpg', 'meridian_bag_pourover.jpg']}),
    ('VECTOR-04', 'R038'): const({'op': 'v2_built_from_raster', 'photo': 'meridian_window_mark.jpg', 'others': ['meridian_shelfcard_2025.pdf']}),
    ('VECTOR-04', 'R039'): const({'op': 'v2_built_from_raster', 'photo': 'meridian_window_mark.jpg', 'others': ['meridian_shelfcard_2025.pdf']}),
    ('VECTOR-04', 'R064'): const({'op': 'v2_pdf_solid_all'}),
    ('VECTOR-04', 'R081'): const({'op': 'v2_raster_text_colour', 'all_text': True, 'grounds': [ROAST, ASHG], 'colors': [CREAM]}),
    ('VECTOR-04', 'R088'): const({'op': 'v2_font_is', 'labels': True, 'optional': True, 'font': 'fonts/LibreFranklin[wght].ttf', 'axes': {'wght': 700},
                                 'family': 'Libre Franklin', 'weight': 'Bold'}),
    ('VECTOR-04', 'R089'): const({'op': 'v2_svg_arch', 'text': r'MERIDIAN'}),
    # 8.5 pt leading, within 0.25 pt
    ('VECTOR-04', 'R095'): const({'op': 'v2_labels', 'mode': 'leading', 'leading_pt': 8.5}),
    ('VECTOR-04', 'R099'): const({'op': 'v2_labels', 'mode': 'caps'}),
    ('VECTOR-04', 'R100'): const({'op': 'v2_svg_solid', 'hexes': V04_PALETTE}),
    ('VECTOR-04', 'R101'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_soft_edges'}, {'op': 'v2_raster_palette', 'hexes': V04_PALETTE, 'transparent_only': True}]}),
    ('VECTOR-04', 'R103'): const({'op': 'v2_no_photo_texture'}),
    ('VECTOR-04', 'R105'): const({'op': 'v2_sheet_no_raster'}),
    # ---------------------------------------------------------------- new batch: MOTION-11
    ('MOTION-11', 'R005'): const({'op': 'v2_frame_text', 'text': 'NEW ONE EVERY OTHER DAY'}),
    ('MOTION-11', 'R007'): const({'op': 'v2_end_hold'}),
    ('MOTION-11', 'R011'): const({'op': 'v2_asset_found', 'asset': SCRAP}),
    ('MOTION-11', 'R012'): const({'op': 'v2_frame_text', 'text': '@STATICFOX'}),
    ('MOTION-11', 'R015'): const({'op': 'v2_frame_text', 'text': 'SUBSCRIBE OR DAVE WINS'}),
    ('MOTION-11', 'R016'): const({'op': 'v2_frame_text', 'text': '@STATICFOX'}),
    ('MOTION-11', 'R020'): const({'op': 'v2_frame_inside'}),
    ('MOTION-11', 'R025'): const({'op': 'v2_footage', 'mode': 'none'}),
    ('MOTION-11', 'R027'): const({'op': 'v2_footage', 'mode': 'min_captures', 'count': 4}),
    ('MOTION-11', 'R034'): const({'op': 'v2_asset_found', 'asset': SCRAP}),
    ('MOTION-11', 'R036'): const({'op': 'v2_footage', 'mode': 'only_captures'}),
    ('MOTION-11', 'R038'): const({'op': 'v2_asset_found', 'asset': SCRAP}),
    ('MOTION-11', 'R039'): m11_with_capture({'op': 'v2_capture_used'}),
    ('MOTION-11', 'R040'): m11_with_capture({'op': 'v2_capture_colour'}),
    ('MOTION-11', 'R041'): const({'op': 'v2_photo_proportions', 'asset': SCRAP}),
    ('MOTION-11', 'R043'): m11_with_capture({'op': 'v2_capture_colour'}),
    ('MOTION-11', 'R044'): m11_with_capture({'op': 'v2_capture_colour'}),
    ('MOTION-11', 'R045'): m11_with_capture({'op': 'v2_capture_colour'}),
    ('MOTION-11', 'R046'): m11_with_capture({'op': 'v2_capture_colour'}),
    ('MOTION-11', 'R047'): m11_with_capture({'op': 'v2_capture_colour'}),
    ('MOTION-11', 'R049'): const({'op': 'v2_photo_proportions', 'asset': SCRAP}),
    # setup capitals (title words before the last) measured by their fill, outline left out; "roughly": 5 px slack
    ('MOTION-11', 'R082'): lambda row, ctx: {'op': 'v2_cap_height', 'words': m11_setup(row, ctx), 'fills': FILLS, 'min_px': 70, 'max_px': 95}
                                            if m11_setup(row, ctx) else None,
    ('MOTION-11', 'R085'): lambda row, ctx: {'op': 'v2_cap_height', 'words': m11_setup(row, ctx), 'fills': FILLS, 'min_px': 145, 'max_px': 180}
                                            if m11_setup(row, ctx) else None,
    ('MOTION-11', 'R086'): lambda row, ctx: {'op': 'v2_word_shorter', 'word': m11_final(row, ctx), 'upper': m11_setup(row, ctx), 'fills': FILLS}
                                            if m11_setup(row, ctx) else None,
    ('MOTION-11', 'R089'): const({'op': 'v2_cap_height', 'words': ['STATIC'], 'fills': FILLS, 'min_px': 145, 'max_px': 180}),
    ('MOTION-11', 'R101'): lambda row, ctx: {'op': 'v2_caps', 'texts': [w for w in m11_title(row, ctx).split() if len(re.sub(r'\W', '', w)) >= 2]}
                                            if m11_title(row, ctx) else None,
    ('MOTION-11', 'R102'): const({'op': 'v2_word_shorter', 'word': 'FOX', 'upper': ['STATIC'], 'fills': FILLS}),
    ('MOTION-11', 'R105'): lambda row, ctx: {'op': 'v2_last_row', 'title': m11_title(row, ctx), 'word': m11_final(row, ctx)} if m11_title(row, ctx) else None,
    ('MOTION-11', 'R106'): const({'op': 'v2_asset_pixels', 'asset': SCRAP, 'select': 'all', 'tol': 5}),
    ('MOTION-11', 'R107'): const({'op': 'v2_last_row', 'title': 'STATIC FOX', 'word': 'FOX'}),
    ('MOTION-11', 'R108'): const({'op': 'v2_asset_pixels', 'asset': SCRAP, 'select': 'all', 'tol': 8}),
    ('MOTION-11', 'R110'): const({'op': 'v2_asset_pixels', 'asset': SCRAP, 'select': 'all', 'tol': 8}),
    ('MOTION-11', 'R112'): const({'op': 'v2_asset_pixels', 'asset': SCRAP, 'select': 'orange', 'tol': 8}),
    ('MOTION-11', 'R114'): const({'op': 'v2_asset_pixels', 'asset': SCRAP, 'select': 'orange', 'tol': 8}),
    ('MOTION-11', 'R115'): const({'op': 'v2_asset_pixels', 'asset': SCRAP, 'select': 'purple', 'tol': 8}),
    ('MOTION-11', 'R116'): const({'op': 'v2_asset_pixels', 'asset': SCRAP, 'select': 'purple', 'tol': 8}),
    ('MOTION-11', 'R120'): lambda row, ctx: {'op': 'v2_legible_at', 'text': m11_title(row, ctx), 'width': 320} if m11_title(row, ctx) else None,
    ('MOTION-11', 'R091'): const({'op': 'v2_line_chars', 'max_chars': 65, 'scope': 'all'}),
    ('MOTION-11', 'R129'): const({'op': 'v2_footage', 'mode': 'not_used', 'capture': 1}),
    ('MOTION-11', 'R130'): const({'op': 'v2_footage', 'mode': 'not_used', 'capture': 2}),
    ('MOTION-11', 'R131'): const({'op': 'v2_footage', 'mode': 'not_used', 'capture': 3}),
    ('MOTION-11', 'R132'): const({'op': 'v2_footage', 'mode': 'not_used', 'capture': 4}),
    ('MOTION-11', 'R133'): const({'op': 'v2_footage', 'mode': 'not_used', 'capture': 5}),
    ('MOTION-11', 'R134'): const({'op': 'v2_footage', 'mode': 'not_used', 'capture': 6}),
}

HOW = {
    'v2_gate': 'Checks the PDF page is drawn as vectors (not mostly a placed picture), then reads its colours, rules or ground from the drawings.',
    'v2_pdf_colour_use': 'Reads every shape drawn in the colour from the PDF in drawing order and sorts it into rules, keylines, chart marks and areas.',
    'v2_pdf_rule_at_text': 'Finds the text and the full-width rules in the PDF and checks a rule sits on its baseline or directly above it.',
    'v2_pdf_text_colour': 'Reads the colour of every span of the named text from the PDF.',
    'v2_pdf_photo_overlay': 'Reads the PDF in drawing order and checks nothing see-through or graded is drawn over a placed photograph.',
    'v2_pdf_area_share': 'Renders the PDF, leaves out the placed pictures and measures the share of the rest in the named colours.',
    'v2_grounds': 'Finds every flat area of one colour big enough to be a ground or panel (photographs and type left out) and reads its colour.',
    'v2_raster_palette': 'Reads every flat colour outside photographs, transparent parts and capture footage, and checks each is a palette colour.',
    'v2_raster_share': 'Measures the share of the designed area in the named colours.',
    'v2_raster_present': 'Looks for the colour as a flat area in the designed parts.',
    'v2_raster_text_colour': 'Reads each text line by OCR, then the colour of its letters and of the ground round it.',
    'v2_mark_on_ground': 'Finds the supplied mark and reads the colour round it.',
    'v2_line_chars': 'Reads the selected lines (live text where there is any) and counts their characters.',
    'v2_role_font': 'Sorts the PDF text into roles by size and reads the font of the selected lines.',
    'v2_tracking_vs_body': 'Measures letter spacing from the PDF\'s glyph positions and compares it with the body text.',
    'v2_svg_leading': 'Reads the SVG\'s live text lines and measures the distance between their baselines.',
    'v2_pdf_cut_spot': 'Reads the PDF\'s colour operators and checks the cut paths use a spot colour named CutContour.',
    'v2_pdf_process_only': 'Reads the colour space of every path, image and shading in the PDF.',
    'v2_pdf_managed_palette': 'Reads every colour in the PDF, converts CMYK through the supplied output profile, and compares with the palette.',
    'v2_pdf_labels_colour': 'Reads the colour of the type lying outside the stickers\' cut paths.',
    'v2_placed_master': 'Renders the delivered sticker, finds it on the sheet, and compares its proportions and colours.',
    'v2_ink_detail': 'Finds every piece in the colour on the proof and checks each is small detail, not a main shape, backing or type.',
    'v2_capture_wash': 'Finds the capture frame the thumbnail is built on and compares the tones of the visible capture with it.',
    'v2_title_letters': 'Reads the title words by OCR and checks each letter\'s fill colour, or the outline colour round it.',
    'v2_title_largest': 'Reads each held frame by OCR and compares the title\'s letter height with every other line.',
    'v2_raster_roles': 'Finds every piece in the colour outside photographs and checks it is a hairline or divider.',
    'v2_no_panel': 'Finds flat areas in the colour and checks none is a ground or a panel carrying text.',
    'v2_raster_photo_overlay': 'Looks for a photograph on the image and, where one is found, compares it with the supplied photo.',
    'v2_artwork_only': 'Reads the PDF and checks the named texts are live type and the only pictures and shapes are supplied ones.',
    'v2_asset_found': 'Searches the image, or every frame of the film, for the supplied file.',
    'v2_asset_pixels': 'Finds the supplied cut-out and compares its own pixels with the file.',
    'v2_built_from_raster': 'Compares the drawing with each supplied photo by feature matching.',
    'v2_cap_height': 'Reads the title words by OCR and measures the height of their letters\' fill.',
    'v2_caps': 'Reads the named text and checks it is set in capitals.',
    'v2_capture_colour': 'Finds the capture frame the thumbnail is built on and compares the colours of the visible capture with it.',
    'v2_capture_used': 'Finds the capture frame the thumbnail is built on and compares the visible capture with it cell by cell.',
    'v2_chart_scale': 'Finds the chart\'s bars in the PDF and compares their heights with the values.',
    'v2_clipped_flat': 'Finds the supplied photo, maps its clipped white areas into the deliverable and checks they stay flat.',
    'v2_combined_pages': 'Reads every page\'s trim and compares each page with its own card.',
    'v2_digit_size': 'Reads the font sizes of the figures and of the letters round them from the PDF.',
    'v2_end_hold': 'Compares the film\'s last frames at its own frame rate and measures how long it holds still.',
    'v2_font_is': 'Reads the glyphs\' advance widths from the PDF and compares them with the supplied font at every weight.',
    'v2_footage': 'Finds the footage in the film\'s frames and matches it to the supplied captures.',
    'v2_frame_inside': 'Reads the end card by OCR and checks no line touches the frame edge.',
    'v2_frame_text': 'Reads the end card (the last held frame) by OCR and looks for the line.',
    'v2_images_are': 'Matches every placed picture in the PDF with the supplied files.',
    'v2_inside_trim': 'Reads the text from the PDF, checks every line lies inside the trim, and reads its last words on the rendered page.',
    'v2_labels': 'Reads the type lying outside the stickers\' cut paths on the sheet.',
    'v2_last_row': 'Reads the title rows by OCR and checks the last row.',
    'v2_mark_beside': 'Finds the supplied lettering and reads which act name stands nearest to it.',
    'v2_mark_letters': 'Finds the supplied wordmark and checks every letter keeps its ink.',
    'v2_mark_not_retyped': 'Searches for the supplied wordmark and, if absent, reads whether the name was set again in another font.',
    'v2_no_photo_texture': 'Looks for photograph-like texture in the image.',
    'v2_numbers_from': 'Reads every figure in the PDF and looks for it in the supplied source files.',
    'v2_only_supplied': 'Reads the PDF\'s text, shapes and pictures and checks they are only the supplied copy and files.',
    'v2_pdf_solid_all': 'Reads the PDF for transparency, gradients, soft masks, blend modes and duplicated shadow type.',
    'v2_photo_as_shot': 'Matches each photograph with its supplied frame and checks nothing is extended, added or removed.',
    'v2_photo_natural': 'Compares the placed photo\'s colours with the supplied file.',
    'v2_photo_pair_same': 'Reads the two colours of the photograph on this image and on the reference image.',
    'v2_photo_proportions': 'Finds the supplied picture and measures whether it was stretched.',
    'v2_photo_two_colour': 'Checks the photograph\'s pixels lie between two palette colours.',
    'v2_proof_vs_svg': 'Renders the delivered SVG at the proof\'s size and compares shape, proportion, colour and transparency.',
    'v2_region_kept': 'Finds the supplied photo and compares a marked part of it with the deliverable.',
    'v2_sheet_cuts': 'Reads the cut paths on the sheet\'s cut layer and measures them.',
    'v2_sheet_no_raster': 'Reads the sheet for placed pictures and fields of tiny specks.',
    'v2_soft_edges': 'Measures how wide the colour transitions are and checks the artwork\'s transparency.',
    'v2_svg_arch': 'Reads the SVG\'s live wordmark and checks whether it is set on a straight line.',
    'v2_svg_cut_file': 'Reads the cut-contour SVG\'s groups and paths.',
    'v2_svg_solid': 'Reads the SVG\'s styles and renders it to check every colour is solid and from the palette.',
    'v2_svg_viewbox': 'Reads the SVG\'s viewBox.',
    'v2_text_anywhere': 'Looks for the words in the PDF\'s text and, failing that, by OCR of its pages.',
    'v2_text_leading': 'Reads the baselines of the text\'s lines from the PDF.',
    'v2_text_size_vs_file': 'Reads the text\'s font size in both PDFs.',
    'v2_text_smallest': 'Reads every font size in the PDF.',
    'v2_title_stack': 'Reads the series title\'s lines and measures their spacing.',
    'v2_tracking_of': 'Measures letter spacing from the PDF\'s glyph positions.',
    'v2_word_shorter': 'Reads the title words by OCR and compares the height of their letters\' fill.',
}
