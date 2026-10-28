"""Round 3 conversions for PHOTO-19, 20, 24, 26 and 28 (2026-10-28): colour on images, rules that needed a definition,
and the measurable rules first sorted as judgement.

One handler per (task, rule): handler(row, ctx) returns an assertion for tools/auto_verifier (objective_ops_r3.py and
ops_r3_photo_b.py), or None where the row cannot be checked exactly. A rule moves only when every row converts.

Definitions used here (read from the file the same way every time):
- Text roles: ops_r3_photo_b._roles_b (objective_ops_r3._roles with tracked type closed up and a body size only where
  the running text holds a sentence). Running text and body text are the body role; a main heading is the main role
  (the largest heading size); a subheading is a secondary heading; fine print, captions and labels are the fine role.
- A running foot or footer: a line starting in the bottom 12% of its page or image.
- A panel (PDF): a filled shape of 2% of the page or more with both sides over 6 pt; a band: a filled shape across
  95% of the page width or height and 1.5% to 30% of the other side.
- An overlay on a PDF photo: a fill or picture drawn after the photo over 2% of it (semi-transparent or shaded fails;
  an opaque panel over part of a photo goes to a person).
- A product's care line or price is tied to the product named on its page (one product per page), else to the
  nearest product name above it.
Rules whose definition would be circular (the main heading defined as the largest text, checked for being larger than
the body) return None.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
RUN = ROOT.parents[1] / 'benchmark_runs/pilot_v7_hybrid_2026-09-28'
PERSON = 'person'


def source_file(tid: str, name: str) -> Path | None:
    for d in (REFRESH / 'upload' / tid, REFRESH / 'sources' / tid, RUN / tid / 'source'):
        if (d / name).is_file():
            return d / name
    return None


def read_csv(tid: str, name: str) -> list[dict]:
    f = source_file(tid, name)
    if not f:
        return []
    return [{(k or '').strip(): (v or '').strip() for k, v in r.items()} for r in csv.DictReader(f.open(encoding='utf-8-sig'))]


def rec(ctx, row) -> dict:
    return ctx.records.get(row['output_id'], {}) or {}


def pal(ctx, *names) -> list:
    return [ctx.palette[n] for n in names]


def const(a):
    return lambda row, ctx: dict(a)


def no_overlay(photo):
    """No scrim, tint or gradient over the placed photo: the shared check (objective_ops_r3.op_no_overlay), or, where
    that cannot see enough of a cropped photo, the same test over the shown part (one tone fit over the placed pixels:
    every channel's gain 0.92 or more and no band of the photo drifting 10 levels from it passes; an even fall in
    contrast under 0.7 fails). Either passing, with neither failing, passes."""
    return {'op': 'v2_any_of', 'checks': [{'op': 'v2_no_overlay', 'photo': photo},
                                          {'op': 'v2_photo_compare_pb', 'photo': photo, 'region': 'own', 'min_tiles': 0,
                                           'pass_if': [['gain_min', '>=', 0.92], ['drift', '<=', 10]],
                                           'fail_if': [['gain_min', '<=', 0.7], ['drift', '<=', 12]]}]}


def by_file(**handlers):
    """A different handler for PDFs and images (keys 'pdf' and 'image')."""
    def h(row, ctx):
        f = handlers['pdf' if row['file'].endswith('.pdf') else 'image']
        return f(row, ctx) if f else None
    return h


# ------------------------------------------------------------------ PHOTO-19 Cascadia Founders Summit

P19_PORTRAITS = [f'speaker_portrait_{i:02d}.jpg' for i in range(1, 15)] + [f'staff_portrait_{i:02d}.jpg' for i in range(1, 5)]
P19_ALL = ['venue_render.jpg'] + P19_PORTRAITS
SUMMIT = 'Cascadia Founders Summit'


def p19_palette(ctx):
    return pal(ctx, 'Cascadia Slate', 'Evergreen', 'Fog Grey', 'Warm Paper', 'Signal Copper', 'Near Black')


def p19_card(row) -> bool:
    return row['file'].startswith('speaker-card')


def p19_photos(row, ctx):
    """A card shows its speaker's cut-out portrait; the announcement may show the venue render and any portrait."""
    if p19_card(row):
        photo = rec(ctx, row).get('photo')
        return [photo] if photo else None
    return list(P19_ALL)


def p19_affiliations(row, ctx):
    """The affiliation lines a file may carry: on a card, the speaker's own (every spelling speakers.csv gives for
    that name); on the announcement, any speaker's, the summit's own name aside (it is the headline there)."""
    rows = read_csv('PHOTO-19', 'speakers.csv')
    if p19_card(row):
        r = rec(ctx, row)
        if not r.get('Name'):
            return None
        return sorted({x['Affiliation'] for x in rows if x.get('Name') == r['Name']} | {r.get('Affiliation', '')} - {''})
    return sorted({x['Affiliation'] for x in rows if x.get('Affiliation') and x['Affiliation'] != SUMMIT})


def p19_with_photos(make):
    def h(row, ctx):
        photos = p19_photos(row, ctx)
        if photos is None:
            return None
        a = make(row, ctx)
        if a is None:
            return None
        a.update(photos=photos, sitter_ground=True)
        return a
    return h


def p19_present(name):
    """The colour appears outside the photograph: found with the sitter's ground left out passes; found only when
    that ground counts goes to a person (whether the ground behind a cut-out is part of the photograph is not
    settled); not found either way fails."""
    def h(row, ctx):
        photos = p19_photos(row, ctx)
        if photos is None:
            return None
        hexes = pal(ctx, name)
        return {'op': 'v2_any_of', 'checks': [{'op': 'v2_colour_present_raster', 'hexes': hexes, 'photos': photos, 'sitter_ground': True},
                                              {'op': 'v2_colour_present_raster', 'hexes': hexes, 'photos': photos}]}
    return h


def p19_type_on_paper(row, ctx):
    affs = p19_affiliations(row, ctx)
    photos = p19_photos(row, ctx)
    if affs is None or photos is None:
        return None
    return {'op': 'v2_type_ink_pb', 'grounds': pal(ctx, 'Warm Paper'), 'colors': pal(ctx, 'Near Black'), 'photos': photos,
            'allow': [{'parts': affs, 'colors': pal(ctx, 'Near Black', 'Signal Copper')}]}


def p19_copper_only(row, ctx):
    affs = p19_affiliations(row, ctx)
    photos = p19_photos(row, ctx)
    if affs is None or photos is None:
        return None
    return {'op': 'v2_colour_only_as_pb', 'hexes': pal(ctx, 'Signal Copper'), 'rules': 'thin', 'allow': [{'parts': affs}],
            'photos': photos, 'sitter_ground': True}


def p19_card_photo(make):
    def h(row, ctx):
        ph = rec(ctx, row).get('photo')
        return make(ph) if ph else None
    return h


def p19_tone(row, ctx):
    photo = rec(ctx, row).get('photo')
    return {'op': 'v2_tone_sitter_pb', 'photo': photo, 'hexes': pal(ctx, 'Fog Grey', 'Warm Paper')} if photo else None


def p19_role_length(row, ctx):
    role = rec(ctx, row).get('Role Line')
    if not role:
        return None
    return {'op': 'v2_line_chars_pb', 'max_chars': 65, 'roles': ['body'], 'parts': [role], 'photos': [rec(ctx, row)['photo']]}


# ------------------------------------------------------------------ PHOTO-20 Astrid Vellacourt

NAME20 = 'Astrid Vellacourt'
P20_MONO = 'vellacourt_av_transparent.png'


def p20_titles(ctx):
    return sorted({v['Talk Title'] for v in ctx.records.values() if v.get('Talk Title')})


def p20_photo(row, ctx):
    p = rec(ctx, row).get('Portrait')
    return [p] if p else None


def p20_light(ctx):
    return pal(ctx, 'Warm Neutral', 'Bone')


def p20_name_titles_running(with_running):
    """Her name (a line reading it alone), the talk titles and (with_running) the body text, on Warm Neutral or Bone,
    are Vellacourt Ink. A line carrying her name among other words (a footer credit) may or may not be meant: a
    different colour there goes to a person."""
    def h(row, ctx):
        sel = [{'whole': [NAME20]}, {'texts': p20_titles(ctx)}] + ([{'roles': ['body']}] if with_running else [])
        a = {'op': 'v2_type_ink_pb', 'grounds': p20_light(ctx), 'colors': pal(ctx, 'Vellacourt Ink'), 'select': sel,
             'maybe': [{'texts': [NAME20]}]}
        if not row['file'].endswith('.pdf'):
            photos = p20_photo(row, ctx)
            if photos is None:
                return None
            a['photos'] = photos
        return a
    return h


def p20_event_date(separate):
    def h(row, ctx):
        r = rec(ctx, row)
        photos = p20_photo(row, ctx)
        if not r or photos is None:
            return None
        from round2 import p20_date
        date = p20_date(r['Date'])['regex']
        if separate:
            sel = [{'separate': {'texts': [r['Event Name']], 'patterns': [date], 'max_other_words': 2,
                                 'ignore': [w.lower() for w in (r.get('Format') or '').split()]}}]
        else:
            sel = [{'texts': [r['Event Name']]}, {'patterns': [date]}]
        return {'op': 'v2_type_ink_pb', 'grounds': p20_light(ctx), 'colors': pal(ctx, 'Vellacourt Ink', 'Studio Slate'), 'select': sel,
                'photos': photos}
    return h


def p20_overlay(row, ctx):
    if row['file'].endswith('.pdf'):
        return {'op': 'v2_pdf_overlay_pb', 'require_photo': True}
    photos = p20_photo(row, ctx)
    return no_overlay(photos[0]) if photos else None


def p20_line_length(row, ctx):
    a = {'op': 'v2_line_chars_pb', 'max_chars': 65, 'roles': ['body']}
    if not row['file'].endswith('.pdf'):
        photos = p20_photo(row, ctx)
        if photos is None:
            return None
        a['photos'] = photos
    return a


# ------------------------------------------------------------------ PHOTO-24 Lunara

P24_PHOTOS = ([f'lunara_campaign_{i:02d}.jpg' for i in range(1, 10)] + ['lunara_detail_caseback.jpg', 'lunara_detail_clasp.jpg',
              'lunara_detail_crown.jpg', 'lunara_detail_handstack.jpg', 'lunara_detail_lug.jpg', 'lunara_detail_movement.jpg'] +
              ['lunara_pdp_ardent.jpg', 'lunara_pdp_halcyon.jpg', 'lunara_pdp_meridian.jpg', 'lunara_pdp_selene.jpg', 'lunara_pdp_vesper.jpg'])
P24_REFS = ['Meridian', 'Selene', 'Ardent', 'Halcyon', 'Vesper']
P24_MARK = ['LUNARA', 'CHRONOMETRY', 'LUNARA CHRONOMETRY']


def p24_photos(row, ctx):
    """A product feature shows its record's photo; the key visual may show any supplied photo."""
    img = rec(ctx, row).get('image')
    return [img] if img else list(P24_PHOTOS)


def p24_palette(ctx):
    return pal(ctx, 'Warm near-black', 'Bone cream', 'Tempered steel', 'Aged brass', 'Oxblood')


def p24_img(make):
    def h(row, ctx):
        a = make(row, ctx)
        if a is not None and not row['file'].endswith('.pdf'):
            a['photos'] = p24_photos(row, ctx)
        return a
    return h


def p24_type_on_bone(row, ctx):
    """On Bone cream, type is Warm near-black; small captions, labels (the fine role) and footer lines may be Tempered
    steel or Oxblood. A line between fine and body size in those colours goes to a person."""
    extra = pal(ctx, 'Warm near-black', 'Tempered steel', 'Oxblood')
    return {'op': 'v2_type_ink_pb', 'grounds': pal(ctx, 'Bone cream'), 'colors': pal(ctx, 'Warm near-black'),
            'allow': [{'roles': ['fine'], 'colors': extra}, {'footer': True, 'colors': extra},
                      {'roles': ['other'], 'colors': extra, 'maybe': True}]}


# ------------------------------------------------------------------ PHOTO-26 Thornmere

def p26_rows():
    return [{'name': r['product_name'], 'care': r['care_line'], 'price': r['price'], 'dims': r['dimensions'], 'materials': r['materials']}
            for r in read_csv('PHOTO-26', 'thornmere_autumn_skus.csv')]


def p26_names():
    return [r['name'] for r in p26_rows()]


def p26_text(mode, require):
    return lambda row, ctx: {'op': 'v2_product_text_pb', 'mode': mode, 'rows': p26_rows(), 'require': require}


def p26_style(*select, **want):
    """PDF style of product names (lines reading a product_name exactly), main headings, the brand name or a role.
    The type scale names its display heading by the sample THORNMERE HOME: where the largest heading is another line,
    either may be meant, so a difference there goes to a person."""
    def h(row, ctx):
        sel = []
        for s in select:
            sel.append({'products': p26_names()} if s == 'products' else {'brand': 'Thornmere'} if s == 'brand' else s)
        if 'main' in select:
            sel.append({'h1': ['THORNMERE HOME']})
        return dict({'op': 'v2_role_style_pb', 'select': sel}, **want)
    return h


# ------------------------------------------------------------------ PHOTO-28 Verda

P28_FRAMES = ['verda_studio_frame_01.jpg', 'verda_studio_frame_02.jpg']
P28_INSTRUCTORS = [f'verda_instructor_0{i}.jpg' for i in range(1, 7)]
P28_ALL = P28_FRAMES + P28_INSTRUCTORS
P28_MARK = 'verda_wordmark_transparent.png'
P28_INK = '#222724'


def p28(make):
    def h(row, ctx):
        a = make(row, ctx)
        if a is not None:
            a.setdefault('photos', list(P28_ALL))
        return a
    return h


def p28_wordmark_ink(ground):
    """The wordmark (a line reading "Verda" alone) on the named ground is inked #222724, Soft Ink or, on Sage, Warm
    Off White. None on that ground passes; none read at all goes to a person (the mark may be drawn, not typeset)."""
    def h(row, ctx):
        inks = [P28_INK] + pal(ctx, 'Soft Ink') + (pal(ctx, 'Warm Off White') if ground == 'Sage' else [])
        return {'op': 'v2_all_of', 'checks': [
            {'op': 'v2_type_ink_pb', 'select': [{'whole': ['Verda']}], 'colors': inks, 'grounds': [], 'optional': False, 'photos': list(P28_ALL)},
            {'op': 'v2_type_ink_pb', 'select': [{'whole': ['Verda']}], 'colors': inks, 'grounds': pal(ctx, ground), 'photos': list(P28_ALL)}]}
    return h


# ------------------------------------------------------------------ the rule table

R3 = {
    # PHOTO-19 cards (and the announcement where the rule covers it)
    ('PHOTO-19', 'R028'): p19_tone,
    ('PHOTO-19', 'R029'): p19_card_photo(lambda ph: {'op': 'v2_palette_sitter_pb', 'photos': [ph], 'sitter_ground_b': True,
                                                     'hexes': ['#23303A', '#2C4A3B', '#D9DDDE', '#F2EEE7', '#B06B3E', '#1A1F24']}),
    ('PHOTO-19', 'R030'): lambda row, ctx: no_overlay(rec(ctx, row)['photo']) if rec(ctx, row).get('photo') else None,
    ('PHOTO-19', 'R031'): p19_present('Cascadia Slate'),
    ('PHOTO-19', 'R032'): p19_card_photo(lambda ph: {'op': 'v2_grounds_sitter_pb', 'photos': [ph], 'sitter_ground_b': True,
                                                     'hexes': ['#23303A', '#F2EEE7']}),
    ('PHOTO-19', 'R033'): p19_type_on_paper,
    ('PHOTO-19', 'R034'): p19_copper_only,
    ('PHOTO-19', 'R042'): p19_with_photos(lambda row, ctx: {'op': 'v2_type_ink_pb', 'select': [{'texts': ['CFS']}], 'grounds': [],
                                                            'colors': pal(ctx, 'Fog Grey'), 'optional': False}),
    ('PHOTO-19', 'R043'): p19_with_photos(lambda row, ctx: {'op': 'v2_type_ink_pb', 'grounds': pal(ctx, 'Cascadia Slate'),
                                                            'colors': pal(ctx, 'Warm Paper', 'Fog Grey')}),
    ('PHOTO-19', 'R044'): p19_with_photos(lambda row, ctx: {'op': 'v2_colour_only_as_pb', 'hexes': pal(ctx, 'Evergreen'), 'rules': 'thin'}),
    ('PHOTO-19', 'R045'): lambda row, ctx: {'op': 'v2_area_share_raster', 'hexes': pal(ctx, 'Signal Copper', 'Evergreen'), 'max_pct': 5,
                                            'photos': p19_photos(row, ctx)} if p19_photos(row, ctx) else None,
    ('PHOTO-19', 'R049'): lambda row, ctx: {'op': 'v2_mark_ground_pb', 'texts': ['CFS'], 'grounds': pal(ctx, 'Cascadia Slate')},
    ('PHOTO-19', 'R050'): p19_present('Warm Paper'),
    ('PHOTO-19', 'R055'): p19_role_length,
    # PHOTO-19 announcement
    ('PHOTO-19', 'R035'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P19_PORTRAITS, 'known': ['venue_render.jpg'],
                                            'then': {'op': 'v2_tone_between', 'photo': '{photo}', 'hexes': pal(ctx, 'Fog Grey', 'Warm Paper')}},
    ('PHOTO-19', 'R036'): p19_with_photos(lambda row, ctx: {'op': 'v2_palette_raster', 'hexes': p19_palette(ctx)}),
    ('PHOTO-19', 'R037'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P19_ALL, 'then': no_overlay('{photo}')},
    ('PHOTO-19', 'R038'): p19_with_photos(lambda row, ctx: {'op': 'v2_colour_present_raster', 'hexes': pal(ctx, 'Cascadia Slate')}),
    ('PHOTO-19', 'R039'): p19_with_photos(lambda row, ctx: {'op': 'v2_ground_raster', 'hexes': pal(ctx, 'Cascadia Slate', 'Warm Paper')}),
    ('PHOTO-19', 'R040'): p19_type_on_paper,
    ('PHOTO-19', 'R041'): p19_copper_only,
    ('PHOTO-19', 'R046'): lambda row, ctx: {'op': 'v2_type_ink_pb', 'select': [{'texts': ['CFS']}], 'grounds': [], 'colors': pal(ctx, 'Fog Grey'),
                                            'optional': False, 'photos': P19_ALL},
    ('PHOTO-19', 'R047'): lambda row, ctx: {'op': 'v2_area_share_raster', 'hexes': pal(ctx, 'Signal Copper', 'Evergreen'), 'max_pct': 5,
                                            'photos': P19_ALL},
    ('PHOTO-19', 'R052'): lambda row, ctx: {'op': 'v2_mark_ground_pb', 'texts': ['CFS'], 'grounds': pal(ctx, 'Cascadia Slate')},
    ('PHOTO-19', 'R053'): p19_with_photos(lambda row, ctx: {'op': 'v2_colour_present_raster', 'hexes': pal(ctx, 'Warm Paper')}),
    ('PHOTO-19', 'R060'): const({'op': 'v2_line_chars_pb', 'max_chars': 65, 'roles': ['body'], 'photos': P19_ALL}),

    # PHOTO-20
    ('PHOTO-20', 'R051'): lambda row, ctx: {'op': 'v2_mark_solid_pb', 'asset': P20_MONO, 'colour': ctx.palette['Ochre']},
    ('PHOTO-20', 'R052'): lambda row, ctx: {'op': 'v2_palette_raster', 'hexes': [p['hex'] for p in ctx.spec['brand_identity']['palette']],
                                            'photos': p20_photo(row, ctx)} if p20_photo(row, ctx) else None,
    ('PHOTO-20', 'R053'): lambda row, ctx: {'op': 'v2_ground_raster', 'hexes': pal(ctx, 'Warm Neutral', 'Bone', 'Deep Ground', 'Vellacourt Ink'),
                                            'photos': p20_photo(row, ctx)} if p20_photo(row, ctx) else None,
    ('PHOTO-20', 'R054'): p20_name_titles_running(True),
    ('PHOTO-20', 'R055'): lambda row, ctx: {'op': 'v2_type_ink_pb', 'grounds': pal(ctx, 'Deep Ground', 'Vellacourt Ink'),
                                            'colors': pal(ctx, 'Warm Neutral', 'Bone'), 'other_marks_ok': pal(ctx, 'Ochre'),
                                            'photos': p20_photo(row, ctx)} if p20_photo(row, ctx) else None,
    ('PHOTO-20', 'R056'): by_file(pdf=lambda row, ctx: {'op': 'v2_colour_only_in_mark', 'hexes': pal(ctx, 'Ochre')},
                                  image=lambda row, ctx: {'op': 'v2_colour_only_in_mark', 'hexes': pal(ctx, 'Ochre'), 'photos': p20_photo(row, ctx)}
                                  if p20_photo(row, ctx) else None),
    ('PHOTO-20', 'R057'): by_file(pdf=const({'op': 'v2_solid_pdf'}),
                                  image=lambda row, ctx: {'op': 'v2_all_of', 'checks': [
                                      {'op': 'v2_solid_raster_pb', 'hexes': [p['hex'] for p in ctx.spec['brand_identity']['palette']],
                                       'photos': p20_photo(row, ctx)},
                                      no_overlay(p20_photo(row, ctx)[0])]} if p20_photo(row, ctx) else None),
    ('PHOTO-20', 'R058'): p20_name_titles_running(False),
    ('PHOTO-20', 'R064'): lambda row, ctx: {'op': 'v2_pdf_grounds_pb', 'only': pal(ctx, 'Warm Neutral', 'Bone', 'Deep Ground', 'Vellacourt Ink')},
    ('PHOTO-20', 'R065'): p20_name_titles_running(True),
    ('PHOTO-20', 'R066'): lambda row, ctx: {'op': 'v2_pdf_grounds_pb', 'only': pal(ctx, 'Warm Neutral', 'Bone', 'Deep Ground', 'Vellacourt Ink'),
                                            'panels_only': True},
    ('PHOTO-20', 'R067'): p20_event_date(True),
    ('PHOTO-20', 'R068'): p20_event_date(False),
    ('PHOTO-20', 'R074'): p20_line_length,
    ('PHOTO-20', 'R076'): p20_line_length,
    ('PHOTO-20', 'R078'): p20_line_length,
    ('PHOTO-20', 'R079'): lambda row, ctx: {'op': 'v2_role_style_pb', 'select': ['body', {'below': p20_titles(ctx)},
                                                                              {'pattern': r'@|\bwww\.|https?://|\+?\d[\d ()-]{7,}\d|\bbook(?:ing|ings)?\b|\benquir'}],
                                            'family': 'Inter', 'weight': 'Regular'},
    ('PHOTO-20', 'R080'): p20_line_length,
    ('PHOTO-20', 'R096'): const({'op': 'v2_pdf_overlay_pb'}),
    ('PHOTO-20', 'R097'): p20_overlay,

    # PHOTO-24
    ('PHOTO-24', 'R046'): p24_img(lambda row, ctx: {'op': 'v2_palette_raster', 'hexes': p24_palette(ctx)}),
    ('PHOTO-24', 'R047'): by_file(pdf=lambda row, ctx: {'op': 'v2_pdf_grounds_pb', 'only': pal(ctx, 'Bone cream', 'Warm near-black', 'Oxblood')},
                                  image=p24_img(lambda row, ctx: {'op': 'v2_ground_raster', 'hexes': pal(ctx, 'Bone cream', 'Warm near-black', 'Oxblood')})),
    ('PHOTO-24', 'R048'): p24_img(p24_type_on_bone),
    ('PHOTO-24', 'R049'): p24_img(lambda row, ctx: {'op': 'v2_colour_only_as_pb', 'hexes': pal(ctx, 'Aged brass'), 'rules': 'hairline'}),
    ('PHOTO-24', 'R050'): by_file(pdf=const({'op': 'v2_solid_pdf'}),
                                  image=p24_img(lambda row, ctx: {'op': 'v2_solid_raster_pb', 'hexes': p24_palette(ctx)})),
    ('PHOTO-24', 'R052'): p24_img(lambda row, ctx: {'op': 'v2_ground_raster', 'hexes': pal(ctx, 'Bone cream', 'Warm near-black', 'Oxblood'),
                                                    'panels_only': True}),
    ('PHOTO-24', 'R053'): p24_img(lambda row, ctx: {'op': 'v2_type_ink_pb', 'grounds': pal(ctx, 'Warm near-black', 'Oxblood'),
                                                    'colors': pal(ctx, 'Bone cream')}),
    ('PHOTO-24', 'R054'): p24_img(lambda row, ctx: {'op': 'v2_type_ink_pb', 'grounds': ['photo'], 'colors': pal(ctx, 'Bone cream', 'Warm near-black')}),
    ('PHOTO-24', 'R055'): p24_img(lambda row, ctx: {'op': 'v2_colour_only_as_pb', 'hexes': pal(ctx, 'Tempered steel'), 'rules': 'thin',
                                                    'allow': [{'roles': ['fine']}, {'footer': True}], 'ambiguous': [{'roles': ['other']}]}),
    ('PHOTO-24', 'R056'): lambda row, ctx: no_overlay(rec(ctx, row)['image']) if rec(ctx, row).get('image') else None,
    ('PHOTO-24', 'R059'): const({'op': 'v2_pdf_overlay_pb'}),
    ('PHOTO-24', 'R070'): p24_img(lambda row, ctx: {'op': 'v2_line_chars_pb', 'max_chars': 65, 'roles': ['body']}),
    ('PHOTO-24', 'R071'): const({'op': 'v2_role_style_pb', 'select': [{'family': 'Cormorant Garamond'}], 'optional': True, 'weight': 'Medium',
                                 'except': ['main', {'whole': P24_REFS + P24_MARK}]}),
    ('PHOTO-24', 'R081'): const({'op': 'v2_role_style_pb', 'select': ['main'], 'family': 'Cormorant Garamond', 'weight': 'Medium', 'optional': True}),
    ('PHOTO-24', 'R086'): const({'op': 'v2_role_style_pb', 'select': ['heading'], 'figures_same_size': True, 'optional': True}),
    ('PHOTO-24', 'R090'): const({'op': 'v2_role_style_pb', 'select': ['main'], 'size': 28, 'optional': True}),
    ('PHOTO-24', 'R091'): const({'op': 'v2_role_style_pb', 'select': ['main'], 'leading': 31, 'only_multi': True}),
    ('PHOTO-24', 'R092'): const({'op': 'v2_role_style_pb', 'select': ['prose', 'fine', '?other'], 'size': 10, 'except': [{'whole': P24_MARK}]}),
    ('PHOTO-24', 'R093'): const({'op': 'v2_role_style_pb', 'select': ['prose', 'fine', '?other'], 'leading': 14, 'optional': True,
                                 'except': [{'whole': P24_MARK}]}),
    ('PHOTO-24', 'R114'): lambda row, ctx: None,          # main heading = largest text: checking it is larger is circular

    # PHOTO-26
    ('PHOTO-26', 'R001'): p26_text('names', True),
    ('PHOTO-26', 'R006'): p26_text('names', False),
    ('PHOTO-26', 'R016'): p26_text('care', True),
    ('PHOTO-26', 'R017'): p26_text('care', False),
    ('PHOTO-26', 'R019'): p26_text('price', False),
    ('PHOTO-26', 'R025'): lambda row, ctx: {'op': 'v2_pdf_grounds_pb', 'band': pal(ctx, 'Soft Clay', 'Indigo Dye')},
    ('PHOTO-26', 'R036'): const({'op': 'v2_pdf_grounds_pb', 'band_same': True}),
    ('PHOTO-26', 'R029'): lambda row, ctx: {'op': 'v2_pdf_grounds_pb', 'not': pal(ctx, 'Stoneware Charcoal')},
    ('PHOTO-26', 'R030'): lambda row, ctx: {'op': 'v2_colour_only_as_pb', 'hexes': pal(ctx, 'Soft Clay'), 'type_only': True,
                                            'allow': [{'footer': True}], 'foot_grounds': pal(ctx, 'Warm Paper Ground')},
    ('PHOTO-26', 'R035'): const({'op': 'v2_pdf_overlay_pb'}),
    ('PHOTO-26', 'R037'): lambda row, ctx: {'op': 'v2_role_style_pb', 'select': [{'colour': ctx.palette['Soft Clay'], 'foot': True}], 'caps': True,
                                            'optional': True},
    ('PHOTO-26', 'R039'): p26_style('products', 'main', 'page_main', family='Barlow Condensed', weight='Medium'),
    ('PHOTO-26', 'R040'): p26_style('body', family='Source Serif 4', weight='Regular', optional=True),
    ('PHOTO-26', 'R041'): const({'op': 'v2_line_chars_pb', 'max_chars': 65, 'roles': ['body']}),
    ('PHOTO-26', 'R044'): p26_style('products', 'main', 'page_main', 'brand', family='Barlow Condensed', weight='Medium'),
    ('PHOTO-26', 'R045'): p26_style('products', 'main', 'page_main', size=13, optional=True),
    ('PHOTO-26', 'R046'): p26_style('secondary', family='Barlow Condensed', weight='Medium', optional=True),
    ('PHOTO-26', 'R047'): p26_style('secondary', size=11, optional=True),
    ('PHOTO-26', 'R048'): p26_style('body', size=10, optional=True),
    ('PHOTO-26', 'R050'): p26_style('products', 'main', 'page_main', size=13),
    ('PHOTO-26', 'R053'): p26_style('products', 'main', 'page_main', caps=True),
    ('PHOTO-26', 'R054'): p26_style('secondary', caps=True, optional=True),

    # PHOTO-28
    ('PHOTO-28', 'R045'): lambda row, ctx: {'op': 'v2_sitter_ground_pb', 'photos': P28_INSTRUCTORS, 'hexes': pal(ctx, 'Warm Off White', 'Sage')},
    ('PHOTO-28', 'R064'): p28(lambda row, ctx: {'op': 'v2_ground_raster', 'hexes': pal(ctx, 'Warm Off White', 'Sage')}),
    ('PHOTO-28', 'R065'): p28(lambda row, ctx: {'op': 'v2_palette_marks_pb', 'hexes': pal(ctx, 'Sage', 'Oak', 'Warm Off White', 'Soft Ink'),
                                                'marks': [{'asset': P28_MARK}, {'whole': ['Verda']}], 'mark_hexes': [P28_INK]}),
    ('PHOTO-28', 'R066'): p28(lambda row, ctx: {'op': 'v2_colour_present_raster', 'hexes': pal(ctx, 'Warm Off White')}),
    ('PHOTO-28', 'R068'): p28(lambda row, ctx: {'op': 'v2_type_ink_pb', 'grounds': pal(ctx, 'Warm Off White'), 'colors': pal(ctx, 'Soft Ink'),
                                                'allow': [{'roles': ['label'], 'max_words': 3, 'colors': pal(ctx, 'Soft Ink', 'Sage')},
                                                          {'whole': ['Verda'], 'colors': pal(ctx, 'Soft Ink') + [P28_INK]},
                                                          {'roles': ['other', 'fine'], 'max_words': 3, 'colors': pal(ctx, 'Sage'), 'maybe': True}]}),
    ('PHOTO-28', 'R069'): p28(lambda row, ctx: {'op': 'v2_colour_only_as_pb', 'hexes': pal(ctx, 'Oak'), 'rules': 'hairline'}),
    ('PHOTO-28', 'R070'): p28(lambda row, ctx: {'op': 'v2_type_ink_pb', 'ground_must': pal(ctx, 'Warm Off White', 'Sage')}),
    ('PHOTO-28', 'R071'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P28_ALL, 'then': no_overlay('{photo}')},
    ('PHOTO-28', 'R072'): p28(lambda row, ctx: {'op': 'v2_type_ink_pb', 'grounds': pal(ctx, 'Sage'), 'colors': pal(ctx, 'Soft Ink', 'Warm Off White'),
                                                'allow': [{'whole': ['Verda'], 'colors': [P28_INK]}]}),
    ('PHOTO-28', 'R074'): p28(lambda row, ctx: {'op': 'v2_area_share_raster', 'hexes': pal(ctx, 'Oak'), 'max_pct': 5}),
    ('PHOTO-28', 'R075'): p28_wordmark_ink('Warm Off White'),
    ('PHOTO-28', 'R076'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P28_INSTRUCTORS, 'known': P28_FRAMES,
                                            'then': {'op': 'v2_sitter_ground_pb', 'photo': '{photo}', 'hexes': pal(ctx, 'Warm Off White', 'Sage')}},
    ('PHOTO-28', 'R077'): p28(lambda row, ctx: {'op': 'v2_type_has_colour_pb', 'hexes': pal(ctx, 'Soft Ink')}),
    ('PHOTO-28', 'R078'): p28_wordmark_ink('Sage'),
    ('PHOTO-28', 'R084'): p28(lambda row, ctx: {'op': 'v2_line_chars_pb', 'max_chars': 65, 'roles': ['body']}),
    ('PHOTO-28', 'R095'): p28(lambda row, ctx: {'op': 'v2_above_role_pb', 'asset': P28_MARK, 'whole': ['Verda'], 'role': 'main'}),
    ('PHOTO-28', 'R104'): lambda row, ctx: None,          # headline = largest text: checking it is larger is circular
    ('PHOTO-28', 'R105'): lambda row, ctx: None,          # same
    ('PHOTO-28', 'R106'): lambda row, ctx: None,          # the launch headline's wording is not given
}


# ------------------------------------------------------------------ measurable rules first sorted as judgement

def photo_cmp(photo_or_photos, pass_if=None, fail_if=None, **kw):
    a = {'op': 'v2_photo_compare_pb', 'pass_if': pass_if or [], 'fail_if': fail_if or []}
    a.update({'photo': photo_or_photos} if isinstance(photo_or_photos, str) else {'photos': list(photo_or_photos)})
    a.update(kw)
    return a


# colours of a placed photo kept: every tile within 5 per channel passes; most tiles moved more than 10 (a treatment
# or recolouring) fails; a few tiles moved goes to a person
TRUE_COLOUR = dict(region='shown', pass_if=[['rgb_max', '<=', 5]], fail_if=[['rgb_median', '>', 10]])


def p19_portraits_by_name():
    return {r['photo']: r['Name'] for r in read_csv('PHOTO-19', 'speakers.csv') if r.get('photo')}


P28_ROSTER = {'Priya Anand': ('Foundations', 34), 'Dana Osei': ('Flow', 36), 'Lena Brandt': ('Core & Restore', 34),
              'Tomas Reyes': ('Strength', 38), 'Yuki Sato': ('Prenatal', 36), 'Nadia Haddad': ('Slow & Deep', 34)}
P28_BY_PHOTO = {f'verda_instructor_0{i}.jpg': n for i, n in enumerate(P28_ROSTER, 1)}
P28_CLASSES = [c for c, _ in P28_ROSTER.values()]
P28_CODE = r'\bRF-?\s?[A-Z]{3}\b'
WEEKDAY = r'\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b|(?-i:\b(?:MON|TUE|TUES|WED|THU|THUR|THURS|FRI|SAT|SUN)\b)'
MONTH = (r'\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|'
         r'nov(?:ember)?|dec(?:ember)?)\b')
CLOCK = r'(?<![$€£\d.,])\b\d{1,2}[:.]\d{2}\s*(?:am|pm)?\b|\b\d{1,2}\s?(?:am|pm|a\.m\.|p\.m\.)(?![a-z])'


def p28_price_when(names, price):
    """If the pictured instructor (by supplied portrait) is one of names, the class price reads price and no other
    class price ($34, $36 or $38) appears; another instructor pictured passes."""
    others = [x for x in (34, 36, 38) if x != price]
    then = {'op': 'v2_text_pb', 'expected': [{'regex': rf'\$\s?{price}(?!\d)'}],
            'forbidden': [{'regex': rf'\$\s?(?:{"|".join(map(str, others))})(?!\d)'}], 'photos': list(P28_BY_PHOTO)}
    return lambda row, ctx: {'op': 'v2_all_of', 'checks': [{'op': 'v2_pictured', 'photos': P28_BY_PHOTO, 'when': n, 'then': then} for n in names]}


def p28_price_beside(cls, price):
    """The price set on the class's own row of the list (the price line to its right on the same row)."""
    return lambda row, ctx: {'op': 'v2_price_list_pb', 'prices': {cls: rf'\$\s?{price}(?!\d)'}}


def p28_wordmark(measure, **kw):
    return lambda row, ctx: dict({'op': 'v2_wordmark_pb', 'whole': ['Verda'], 'asset': P28_MARK, 'measure': measure, 'photos': list(P28_ALL)}, **kw)


P24_FINISH = r'^\s*(?:silver sunburst|grained cream|lacquered oxblood|silver|deep blue sunray)\s*$'


def p24_pdp(row, ctx):
    return rec(ctx, row).get('image') or (row.get('values') or {}).get('1')


def p24_finish(row, ctx):
    v = row['values']
    return {'op': 'v2_paired', 'anchor': [v['1']], 'rivals': [r for r in P24_REFS if r != v['1']], 'kind': P24_FINISH,
            'value': {'regex': rf'^\s*{re.escape(v["2"])}\s*$'}, 'where': 'section'}


def p24_one_caliber(row, ctx):
    v = row['values']
    base = {'op': 'v2_paired', 'anchor': [v['1']], 'rivals': [r for r in P24_REFS if r != v['1']], 'kind': r'\bLM-\d{2}\b',
            'value': {'regex': rf'\b{v["2"]}\b'}, 'where': 'section'}
    return {'op': 'v2_all_of', 'checks': [dict(base), dict(base, empty_ok=True)]}


def p24_pdf_true(only):
    """Colour of the dealer sheet's photos kept against their supplied files (read from the embedded pixels)."""
    return lambda row, ctx: dict({'op': 'v2_pdf_photos_pb', 'photos': list(P24_PHOTOS), 'only': only}, **TRUE_COLOUR)


P26_PHOTOS = [f'autumn_shoot_{i:02d}.jpg' for i in range(1, 15)] + [f'textile_flatlay_{i:02d}.jpg' for i in range(1, 7)]


def p20_talk_parts(row, ctx):
    """The three talk titles and their one-line subjects from vellacourt_bio_copy.txt."""
    f = source_file('PHOTO-20', 'vellacourt_bio_copy.txt')
    if not f:
        return None
    pairs = re.findall(r'"([^"]+)"\s*-\s*(on [^\n]+?\.)\s*$', f.read_text(encoding='utf-8'), re.M)
    return [x for t, sub in pairs for x in (t, sub)] if len(pairs) == 3 else None


def p20_card_block(row, ctx):
    r = rec(ctx, row)
    if not r:
        return None
    from round2 import p20_date
    return {'op': 'v2_pdf_block_pb', 'texts': [r['Talk Title'], r['Event Name']], 'patterns': [p20_date(r['Date'])['regex']], 'consecutive': True}


R3_MEASURABLE = {
    # PHOTO-19
    ('PHOTO-19', 'R010'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P19_PORTRAITS, 'known': ['venue_render.jpg'], 'then': {},
                                            'then_by': {ph: {'op': 'v2_names_by_photo', 'photo': ph,
                                                             'names': sorted(set(p19_portraits_by_name().values())), 'expected': n}
                                                        for ph, n in p19_portraits_by_name().items()}},
    ('PHOTO-19', 'R073'): lambda row, ctx: {'op': 'v2_sitter_ground_even_pb', 'photo': rec(ctx, row)['photo']} if rec(ctx, row).get('photo') else None,
    ('PHOTO-19', 'R078'): lambda row, ctx: {'op': 'v2_sitter_ground_same_pb', 'photo': rec(ctx, row)['photo'],
                                            'deliverable': 'deliverables/speaker-card-r005.png', 'other_photo': 'speaker_portrait_03.jpg'}
                                           if rec(ctx, row).get('photo') else None,
    ('PHOTO-19', 'R080'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P19_PORTRAITS, 'known': ['venue_render.jpg'],
                                            'then': {'op': 'v2_sitter_ground_even_pb', 'photo': '{photo}'}},
    ('PHOTO-19', 'R081'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P19_PORTRAITS, 'known': ['venue_render.jpg'],
                                            'then': {'op': 'v2_sitter_ground_same_pb', 'photo': '{photo}', 'other_photo': 'speaker_portrait_03.jpg',
                                                     'deliverable': 'deliverables/speaker-card-r005.png'}},
    # PHOTO-20
    ('PHOTO-20', 'R022'): lambda row, ctx: {'op': 'v2_pdf_block_pb', 'texts': p20_talk_parts(row, ctx), 'allow': [r'^\s*confirmed talk offer\s*$']}
                                           if p20_talk_parts(row, ctx) else None,
    ('PHOTO-20', 'R024'): lambda row, ctx: {'op': 'v2_pdf_portraits_pb', 'photos': [f'vellacourt_session_0{i}.jpg' for i in range(1, 10)],
                                            'others': ['vellacourt_workshop_snap.jpg', 'vellacourt_deboss_card.jpg']},
    ('PHOTO-20', 'R025'): lambda row, ctx: {'op': 'v2_pdf_covered_pb', 'texts': p20_talk_parts(row, ctx)} if p20_talk_parts(row, ctx) else None,
    ('PHOTO-20', 'R026'): p20_card_block,
    ('PHOTO-20', 'R031'): lambda row, ctx: {'op': 'v2_text_pb', 'expected': [rec(ctx, row)['Talk Title']], 'photos': p20_photo(row, ctx) or []}
                                           if rec(ctx, row).get('Talk Title') else None,
    ('PHOTO-20', 'R077'): lambda row, ctx: {'op': 'v2_style_lines', 'texts': [rec(ctx, row)['Event Name']],
                                            'patterns': [__import__('round2').p20_date(rec(ctx, row)['Date'])['regex']],
                                            'family': 'Inter', 'weight': 'Regular'} if rec(ctx, row) else None,
    # PHOTO-24
    ('PHOTO-24', 'R007'): lambda row, ctx: {'op': 'v2_text_pb', 'if_any': r'\b[A-Z]\.\s?[A-Z]\.', 'expected': ['J.M.'],
                                            'forbidden': [{'regex': r'\b(?!J\.\s?M\.)[A-Z]\.\s?[A-Z]\.'}], 'photos': p24_photos(row, ctx)},
    ('PHOTO-24', 'R013'): p24_finish,
    ('PHOTO-24', 'R021'): lambda row, ctx: photo_cmp(p24_pdp(row, ctx), **TRUE_COLOUR) if p24_pdp(row, ctx) else None,
    ('PHOTO-24', 'R022'): lambda row, ctx: photo_cmp('lunara_pdp_vesper.jpg', **TRUE_COLOUR),
    ('PHOTO-24', 'R023'): lambda row, ctx: {'op': 'v2_pdf_photos_pb', 'photos': list(P24_PHOTOS), 'region': 'shown',
                                            'pass_if': [['rgb_max', '<=', 5]], 'fail_if': [['warm_single', '>=', 1], ['src_warm_single', '<=', 0]]},
    ('PHOTO-24', 'R024'): p24_pdf_true(['lunara_pdp_vesper.jpg']),
    ('PHOTO-24', 'R027'): lambda row, ctx: {'op': 'v2_pdf_photos_pb', 'photos': list(P24_PHOTOS), 'region': 'shown',
                                            'pass_if': [['noise_ratio', '<=', 1.3]], 'fail_if': [['noise_ratio', '>=', 2]]},
    ('PHOTO-24', 'R037'): p24_one_caliber,
    ('PHOTO-24', 'R057'): lambda row, ctx: photo_cmp('lunara_pdp_ardent.jpg', **TRUE_COLOUR),
    ('PHOTO-24', 'R060'): p24_pdf_true(['lunara_pdp_ardent.jpg']),
    ('PHOTO-24', 'R061'): p24_pdf_true(None),
    ('PHOTO-24', 'R062'): lambda row, ctx: photo_cmp(p24_pdp(row, ctx), **TRUE_COLOUR) if p24_pdp(row, ctx) else None,
    ('PHOTO-24', 'R063'): lambda row, ctx: photo_cmp(p24_pdp(row, ctx), **TRUE_COLOUR) if p24_pdp(row, ctx) else None,
    ('PHOTO-24', 'R064'): p24_pdf_true(['lunara_pdp_ardent.jpg']),
    ('PHOTO-24', 'R096'): lambda row, ctx: photo_cmp([f'lunara_campaign_{i:02d}.jpg' for i in range(1, 10)], region='shown',
                                                     pass_if=[['warm_single', '>=', 1]], fail_if=[['de_max', '<=', 3]]),
    ('PHOTO-24', 'R097'): const({'op': 'v2_stacked', 'top': 'Lunara', 'bottom': 'Chronometry', 'stack': True}),
    ('PHOTO-24', 'R098'): lambda row, ctx: photo_cmp([f'lunara_campaign_{i:02d}.jpg' for i in range(1, 10)], region='shown', min_tiles=0,
                                                     pass_if=[['drift', '<=', 4]], fail_if=[['drift', '>=', 12]]),
    ('PHOTO-24', 'R102'): lambda row, ctx: {'op': 'v2_photo_aspect_pb', 'photo': p24_pdp(row, ctx)} if p24_pdp(row, ctx) else None,
    ('PHOTO-24', 'R108'): lambda row, ctx: {'op': 'v2_any_of', 'checks': [{'op': 'v2_photo_aspect_pb', 'photo': f'lunara_campaign_{i:02d}.jpg'}
                                                                          for i in range(1, 10)]},
    ('PHOTO-24', 'R109'): lambda row, ctx: {'op': 'v2_photo_aspect_pb', 'photo': row['values']['2']},
    # PHOTO-26
    ('PHOTO-26', 'R002'): lambda row, ctx: {'op': 'v2_product_text_pb', 'mode': 'dims', 'rows': p26_rows(), 'require': True},
    ('PHOTO-26', 'R004'): lambda row, ctx: {'op': 'v2_product_text_pb', 'mode': 'materials', 'rows': p26_rows(), 'require': True},
    ('PHOTO-26', 'R005'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_contains_asset', 'assets': [ph], 'shape': False} for ph in P26_PHOTOS]}),
    ('PHOTO-26', 'R007'): lambda row, ctx: {'op': 'v2_product_text_pb', 'mode': 'dims', 'rows': p26_rows()},
    ('PHOTO-26', 'R014'): const({'op': 'v2_pdf_printer_marks_pb'}),
    ('PHOTO-26', 'R023'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'forbid': ['thornmere_colour_note_phone.jpg'], 'region': 'shown',
                                 'pass_if': [['rgb_max', '<=', 5]]}),
    ('PHOTO-26', 'R028'): const({'op': 'v2_pdf_flat_paint_pb'}),
    ('PHOTO-26', 'R038'): lambda row, ctx: {'op': 'v2_pdf_tracking_pb', 'foot_colour': ctx.palette['Soft Clay']},
    ('PHOTO-26', 'R043'): const({'op': 'v2_role_style_pb', 'select': ['largest', {'pattern': r'.'}],
                                 'allowed_fonts': [['Barlow Condensed', 'Medium'], ['Source Serif 4', 'Regular'], ['Inter', 'Regular']]}),
    ('PHOTO-26', 'R057'): lambda row, ctx: {'op': 'v2_pdf_tracking_pb', 'names': p26_names()},
    # PHOTO-28
    ('PHOTO-28', 'R005'): p28_price_when(['Priya Anand', 'Lena Brandt', 'Nadia Haddad'], 34),
    ('PHOTO-28', 'R025'): p28_price_when(['Dana Osei', 'Yuki Sato'], 36),
    ('PHOTO-28', 'R026'): p28_price_when(['Tomas Reyes'], 38),
    ('PHOTO-28', 'R007'): const({'op': 'v2_prices', 'mode': 'only', 'allowed': ['$34', '$36', '$38', '$180', '$220']}),
    ('PHOTO-28', 'R009'): lambda row, ctx: __import__('round2').p28_price(['Foundations', 'Core & Restore', 'Slow & Deep'], 34)(row, ctx),
    ('PHOTO-28', 'R010'): const({'op': 'v2_text_pb', 'if_any': r'\bvalid\b|\bthrough\b|\buntil\b|\bexpires?\b',
                                 'expected': [{'regex': r'through\s+Dec(?:ember)?\.?\s+2027'}],
                                 'forbidden': [{'regex': r'\b(?:through|until|thru|valid(?:\s+\w+){0,2})\s+(?:[A-Za-z]{3,9}\.?\s+)?(?:\d{1,2}\s+)?20(?:1\d|2[0-6])\b'}],
                                 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R013'): const({'op': 'v2_price_list_pb', 'names': P28_CLASSES}),
    ('PHOTO-28', 'R016'): const({'op': 'v2_price_list_pb', 'block': True, 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R017'): p28_price_beside('Foundations', 34),
    ('PHOTO-28', 'R018'): p28_price_beside('Flow', 36),
    ('PHOTO-28', 'R019'): p28_price_beside('Core & Restore', 34),
    ('PHOTO-28', 'R020'): p28_price_beside('Strength', 38),
    ('PHOTO-28', 'R021'): p28_price_beside('Prenatal', 36),
    ('PHOTO-28', 'R022'): p28_price_beside('Slow & Deep', 34),
    ('PHOTO-28', 'R028'): lambda row, ctx: __import__('round2').p28_class_beside('Lena Brandt')(row, ctx),
    ('PHOTO-28', 'R035'): const({'op': 'v2_text_pb', 'expected': [P28_CLASSES], 'forbidden': [{'regex': P28_CODE}], 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R037'): const({'op': 'v2_text_pb', 'photos': list(P28_ALL), 'forbidden': [
        {'regex': WEEKDAY}, {'regex': CLOCK}, {'regex': r'\btimetable\b|\bschedule\b'},
        {'regex': rf'(?<!\d)\d{{1,2}}(?:st|nd|rd|th)?\s*{MONTH}|{MONTH}\.?\s*\d{{1,2}}(?:st|nd|rd|th)?(?!\d)'}]}),
    ('PHOTO-28', 'R041'): const({'op': 'v2_text_pb', 'forbidden': [{'regex': P28_CODE}], 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R044'): const({'op': 'v2_text_pb', 'expected': P28_CLASSES, 'forbidden': [{'regex': P28_CODE}], 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R046'): const({'op': 'v2_text_pb', 'forbidden': ['Erin', 'Coyle', 'erin@verdastudio.example'], 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R048'): lambda row, ctx: {'op': 'v2_names_by_photo', 'photo': row['values']['1'], 'names': list(P28_ROSTER),
                                            'expected': row['values']['2']},
    ('PHOTO-28', 'R049'): const({'op': 'v2_contains_asset', 'assets': P28_INSTRUCTORS, 'shape': False}),
    ('PHOTO-28', 'R051'): const({'op': 'v2_contains_asset', 'assets': P28_FRAMES, 'shape': False}),
    ('PHOTO-28', 'R058'): p28_wordmark('halo'),
    ('PHOTO-28', 'R059'): p28_wordmark('edges'),
    ('PHOTO-28', 'R063'): p28_wordmark('aspect', range=[3.1, 3.45]),
    ('PHOTO-28', 'R079'): p28_wordmark('height', max_px=34),
    ('PHOTO-28', 'R096'): const({'op': 'v2_text_pb', 'forbidden': ['!'], 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R097'): p28_wordmark('spacing'),
    ('PHOTO-28', 'R099'): p28_wordmark('counters'),
    ('PHOTO-28', 'R101'): const({'op': 'v2_window_flat_pb', 'photo': 'verda_studio_frame_01.jpg', 'known': ['verda_studio_frame_02.jpg'] + P28_INSTRUCTORS}),
    ('PHOTO-28', 'R103'): const(photo_cmp(P28_FRAMES, region='own', pass_if=[['dL', '>=', 5]], fail_if=[['dL', '<', 2]], absent='pass',
                                          known=P28_INSTRUCTORS)),
}
R3.update(R3_MEASURABLE)


# ------------------------------------------------------------------ partly measurable rules (code settles most rows of the run)

ASK = {'op': 'v2_ask_pb'}
UNTOUCHED = [['de_max', '<=', 3]]                       # every tile within 3 Delta E of the supplied photo: left as shot
SAME_FACE = [['ncc_min', '>=', 0.95]]


def if_portraits(photos, known, then, absent_ok=True):
    """For each supplied portrait found, the check `then`; none found and no other photograph: a pass."""
    return {'op': 'v2_each_photo_pb', 'photos': list(photos), 'known': list(known), 'then': then}


def p19_cast_left(photo):
    """The supplied portrait's cast is only proven left when every tile is within 3 Delta E of it (a fail); any
    correction goes to a person, who judges whether the skin now looks natural."""
    return lambda row, ctx: photo_cmp(photo, region='subject', fail_if=UNTOUCHED)


def p19_untouched_trap(photo):
    """The supplied retouching (whitened eyes, sheen) is proven left when the portrait is the file itself: every tile
    within 3 Delta E and correlating 0.98 or more (a fail); otherwise a person."""
    return lambda row, ctx: photo_cmp(photo, region='subject', fail_if=UNTOUCHED + [['ncc_min', '>=', 0.98]])


P19_SUPPLIED = [r'founders and the people who fund them', r'register for the summit']
OFFER_WORDS = [r'discount', r'early[- ]?bird', r'group (?:pass|rate|ticket)', r'bundle', r'%\s*off', r'promo(?:tion)? code', r'\bsave\b']


def p20_session(row, ctx):
    p_ = rec(ctx, row).get('Portrait')
    return p_ or None


P20_SESSIONS = [f'vellacourt_session_0{i}.jpg' for i in range(1, 10)]


def p20_photo_rule(pass_if=None, fail_if=None, region='subject'):
    """A portrait check on PNGs (the row's supplied session photo) and PDFs (the embedded picture, matched among the
    nine session photos)."""
    def h(row, ctx):
        if row['file'].endswith('.pdf'):
            a = {'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'region': region, 'pass_if': pass_if or [], 'fail_if': fail_if or []}
            if 'talk-card-r007' in row['file']:
                a['optional'] = True
            return a
        ph = p20_session(row, ctx)
        return photo_cmp(ph, region=region, pass_if=pass_if, fail_if=fail_if) if ph else None
    return h


R3_PARTLY = {
    # PHOTO-19
    ('PHOTO-19', 'R009'): const({'op': 'v2_inside_all', 'patterns': [r'\bregist']}),
    ('PHOTO-19', 'R015'): const({'op': 'v2_text_pb', 'expected': [{'line': r'^\W*register\b(?!ation)', 'max_words': 8}], 'missing': PERSON,
                                 'photos': P19_ALL}),
    ('PHOTO-19', 'R016'): lambda row, ctx: {'op': 'v2_all_of', 'checks': [
        {'op': 'v2_text_pb', 'forbidden': [{'regex': w} for w in OFFER_WORDS], 'photos': P19_ALL},
        {'op': 'v2_copy_only_pb', 'files': ['programme_copy.txt', 'speakers.csv'], 'extra': ['cfs', 'register', 'for', 'the', 'summit'],
         'photos': P19_ALL}]},
    ('PHOTO-19', 'R017'): const({'op': 'v2_text_pb', 'photos': P19_ALL, 'forbidden': [
        {'line': r'(?:regist|ticket|pass|closes?|deadline|\bby\b).*(?:\d{1,2}[:.]\d{2}|\b\d{1,2}\s*(?:am|pm)\b|' + MONTH + r'|\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b)'
                 r'|(?:\d{1,2}[:.]\d{2}|' + MONTH + r').*(?:regist|ticket|closes?|deadline)'}]}),
    ('PHOTO-19', 'R020'): lambda row, ctx: {'op': 'v2_each_photo_pb', 'photos': P19_PORTRAITS, 'known': ['venue_render.jpg'], 'then': {},
                                            'then_by': {ph: {'op': 'v2_names_by_photo', 'photo': ph, 'names': sorted(set(p19_portraits_by_name().values())),
                                                             'expected': n} for ph, n in p19_portraits_by_name().items()}},
    ('PHOTO-19', 'R022'): p19_card_photo(lambda ph: photo_cmp(ph, region='subject', pass_if=SAME_FACE)),
    ('PHOTO-19', 'R023'): const(if_portraits(P19_PORTRAITS, ['venue_render.jpg'], photo_cmp('{photo}', region='subject', pass_if=SAME_FACE))),
    ('PHOTO-19', 'R027'): const(photo_cmp('venue_render.jpg', region='subject', pass_if=[['scale', '<=', 1.1], ['hf_median', '>=', 0.9]],
                                          absent='pass', known=P19_PORTRAITS)),
    ('PHOTO-19', 'R048'): p19_card_photo(lambda ph: photo_cmp(ph, region='subject', pass_if=[['dc_max', '<=', 2]])),
    ('PHOTO-19', 'R051'): const(if_portraits(P19_PORTRAITS, ['venue_render.jpg'], photo_cmp('{photo}', region='subject', pass_if=[['dc_max', '<=', 2]]))),
    ('PHOTO-19', 'R058'): lambda row, ctx: {'op': 'v2_text_pb', 'forbidden': sorted(set(p19_portraits_by_name().values())), 'found': PERSON,
                                            'photos': P19_ALL},
    ('PHOTO-19', 'R067'): lambda row, ctx: {'op': 'v2_text_pb', 'found': PERSON, 'photos': P19_ALL,
                                            'forbidden': sorted({r['Affiliation'] for r in read_csv('PHOTO-19', 'speakers.csv') if r.get('Affiliation') and r['Affiliation'] != SUMMIT})},
    ('PHOTO-19', 'R068'): const({'op': 'v2_text_pb', 'found': PERSON, 'photos': P19_ALL,
                                 'forbidden': ['Opening Keynote', 'Building Track', 'Scaling Track', 'Funding Track']}),
    ('PHOTO-19', 'R076'): lambda row, ctx: {'op': 'v2_solid_raster_pb', 'hexes': p19_palette(ctx), 'photos': p19_photos(row, ctx) or [],
                                            'sitter_ground': True} if p19_photos(row, ctx) else None,
    ('PHOTO-19', 'R077'): p19_card_photo(lambda ph: {'op': 'v2_bg_remnant_pb', 'photo': ph}),
    ('PHOTO-19', 'R079'): const(if_portraits(P19_PORTRAITS, ['venue_render.jpg'], {'op': 'v2_bg_remnant_pb', 'photo': '{photo}'})),
    ('PHOTO-19', 'R083'): p19_card_photo(lambda ph: photo_cmp(ph, region='subject', pass_if=[['da', '<=', 2], ['db', '<=', 2]])),
    ('PHOTO-19', 'R084'): const(if_portraits(P19_PORTRAITS, ['venue_render.jpg'], ASK)),
    ('PHOTO-19', 'R085'): const(if_portraits(P19_PORTRAITS, ['venue_render.jpg'], photo_cmp('{photo}', region='subject',
                                                                                          pass_if=[['da', '<=', 2], ['db', '<=', 2]]))),
    ('PHOTO-19', 'R087'): p19_card_photo(lambda ph: photo_cmp(ph, region='subject', pass_if=SAME_FACE)),
    ('PHOTO-19', 'R088'): p19_card_photo(lambda ph: photo_cmp(ph, region='subject', pass_if=SAME_FACE + [['hf_min', '>=', 0.9]])),
    ('PHOTO-19', 'R090'): p19_cast_left('speaker_portrait_07.jpg'),
    ('PHOTO-19', 'R091'): p19_card_photo(lambda ph: photo_cmp(ph, region='subject', pass_if=[['hf_min', '>=', 1.0]])),
    ('PHOTO-19', 'R092'): p19_untouched_trap('speaker_portrait_08.jpg'),
    ('PHOTO-19', 'R093'): p19_cast_left('speaker_portrait_08.jpg'),
    ('PHOTO-19', 'R094'): p19_cast_left('speaker_portrait_09.jpg'),
    ('PHOTO-19', 'R095'): p19_cast_left('speaker_portrait_11.jpg'),
    ('PHOTO-19', 'R096'): p19_cast_left('speaker_portrait_12.jpg'),
    ('PHOTO-19', 'R097'): p19_cast_left('speaker_portrait_13.jpg'),
    ('PHOTO-19', 'R098'): p19_cast_left('staff_portrait_03.jpg'),
    ('PHOTO-19', 'R099'): const(if_portraits(P19_PORTRAITS, ['venue_render.jpg'], photo_cmp('{photo}', region='subject',
                                                                                          pass_if=SAME_FACE + [['hf_min', '>=', 0.9]]))),
    ('PHOTO-19', 'R100'): const(if_portraits(P19_PORTRAITS, ['venue_render.jpg'], ASK)),
    ('PHOTO-19', 'R101'): const(if_portraits(['speaker_portrait_02.jpg'], [x for x in P19_ALL if x != 'speaker_portrait_02.jpg'], ASK)),
    ('PHOTO-19', 'R102'): const(if_portraits(['speaker_portrait_08.jpg'], [x for x in P19_ALL if x != 'speaker_portrait_08.jpg'], ASK)),
    ('PHOTO-19', 'R103'): p19_cast_left('speaker_portrait_04.jpg'),
    ('PHOTO-19', 'R104'): p19_untouched_trap('speaker_portrait_02.jpg'),
    ('PHOTO-19', 'R105'): p19_cast_left('speaker_portrait_02.jpg'),
    ('PHOTO-19', 'R106'): p19_untouched_trap('speaker_portrait_02.jpg'),
    ('PHOTO-19', 'R107'): p19_untouched_trap('speaker_portrait_08.jpg'),
    ('PHOTO-19', 'R108'): const(if_portraits(['speaker_portrait_02.jpg'], [x for x in P19_ALL if x != 'speaker_portrait_02.jpg'], ASK)),
    ('PHOTO-19', 'R109'): const(if_portraits(['speaker_portrait_08.jpg'], [x for x in P19_ALL if x != 'speaker_portrait_08.jpg'], ASK)),
    # PHOTO-20
    ('PHOTO-20', 'R001'): const({'op': 'v2_text_pb', 'expected': ['co-founded and runs Vellacourt & Sund, a six-person industrial design studio'],
                                 'missing': PERSON}),
    ('PHOTO-20', 'R020'): const({'op': 'v2_text_pb', 'expected': ['works on physical products from first sketch to production'], 'missing': PERSON}),
    ('PHOTO-20', 'R023'): const({'op': 'v2_text_pb', 'expected': [{'regex': r"raising a seed round to grow the studio.s own product line"}],
                                 'missing': PERSON}),
    ('PHOTO-20', 'R029'): lambda row, ctx: ({'op': 'v2_bg_remnant_pb', 'photos': P20_SESSIONS} if row['file'].endswith('.pdf') else
                                            {'op': 'v2_bg_remnant_pb', 'photo': p20_session(row, ctx)} if p20_session(row, ctx) else None),
    ('PHOTO-20', 'R030'): const({'op': 'v2_bg_remnant_pb', 'photos': P20_SESSIONS, 'absent': 'pass'}),
    ('PHOTO-20', 'R038'): const({'op': 'v2_copy_only_pb', 'files': ['vellacourt_bio_copy.txt', 'vellacourt_talks.csv']}),
    ('PHOTO-20', 'R041'): const({'op': 'v2_copy_only_pb', 'files': ['vellacourt_bio_copy.txt', 'vellacourt_talks.csv'], 'photos': P20_SESSIONS}),
    ('PHOTO-20', 'R045'): p20_photo_rule(pass_if=SAME_FACE),
    ('PHOTO-20', 'R047'): lambda row, ctx: photo_cmp('vellacourt_workshop_snap.jpg', region='subject', pass_if=[['scale', '<=', 1.1], ['hf_median', '>=', 0.9]],
                                                     absent='pass', known=P20_SESSIONS),
    ('PHOTO-20', 'R048'): by_file(pdf=lambda row, ctx: {'op': 'v2_pdf_flat_paint_pb'},
                                  image=lambda row, ctx: {'op': 'v2_mark_solid_pb', 'asset': P20_MONO, 'colour': ctx.palette['Ochre']}),
    ('PHOTO-20', 'R049'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS + ['vellacourt_workshop_snap.jpg'],
                                 'by_photo': {'vellacourt_workshop_snap.jpg': {'pass_if': [['fills_image', '>=', 0.0]], 'region': 'subject'}}}),
    ('PHOTO-20', 'R071'): lambda row, ctx: {'op': 'v2_style_lines', 'whole_lines': [NAME20], 'family': 'Instrument Serif', 'weight': 'Regular'},
    ('PHOTO-20', 'R072'): lambda row, ctx: {'op': 'v2_serif_spans_pb', 'allow': [NAME20]},
    ('PHOTO-20', 'R084'): lambda row, ctx: {'op': 'v2_type_ink_pb', 'select': p20_event_date(True)(row, ctx)['select'], 'grounds': [], 'colors': [],
                                            'optional': True, 'photos': p20_photo(row, ctx) or []} if rec(ctx, row) else None,
    ('PHOTO-20', 'R085'): lambda row, ctx: {'op': 'v2_style_lines', 'texts': [rec(ctx, row)['Talk Title']], 'family': 'Inter', 'weight': 'Medium'}
                                           if rec(ctx, row).get('Talk Title') else None,
    ('PHOTO-20', 'R087'): lambda row, ctx: {'op': 'v2_monogram_pb', 'colour': ctx.palette['Ochre'], 'min_px': 69},
    ('PHOTO-20', 'R088'): lambda row, ctx: {'op': 'v2_monogram_pb', 'colour': ctx.palette['Ochre'], 'text': NAME20, 'narrower': True},
    ('PHOTO-20', 'R089'): lambda row, ctx: {'op': 'v2_monogram_pb', 'colour': ctx.palette['Ochre'], 'text': NAME20, 'beneath': True},
    ('PHOTO-20', 'R090'): lambda row, ctx: {'op': 'v2_monogram_pb', 'colour': ctx.palette['Ochre'], 'once': True},
    ('PHOTO-20', 'R093'): by_file(pdf=lambda row, ctx: {'op': 'v2_pdf_flat_paint_pb'},
                                  image=lambda row, ctx: {'op': 'v2_solid_raster_pb', 'hexes': [p['hex'] for p in ctx.spec['brand_identity']['palette']],
                                                          'photos': p20_photo(row, ctx) or []}),
    ('PHOTO-20', 'R098'): p20_photo_rule(pass_if=SAME_FACE),
    ('PHOTO-20', 'R100'): p20_photo_rule(pass_if=UNTOUCHED),
    ('PHOTO-20', 'R103'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': UNTOUCHED}),
    ('PHOTO-20', 'R104'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': SAME_FACE + [['fills_image', '>=', 0.98]]}),
    ('PHOTO-20', 'R106'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': SAME_FACE + [['fills_image', '>=', 0.98]]}),
    ('PHOTO-20', 'R107'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': UNTOUCHED}),
    ('PHOTO-20', 'R108'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'fail_if': UNTOUCHED,
                                 'by_photo': {'vellacourt_session_08.jpg': {'fail_if': UNTOUCHED}, 'vellacourt_session_09.jpg': {'fail_if': UNTOUCHED}}}),
    ('PHOTO-20', 'R109'): p20_photo_rule(pass_if=UNTOUCHED),
    ('PHOTO-20', 'R110'): p20_photo_rule(pass_if=UNTOUCHED, fail_if=[['chroma_ratio', '<=', 0.25]]),
    ('PHOTO-20', 'R111'): p20_photo_rule(pass_if=[['hf_min', '>=', 0.9]]),
    ('PHOTO-20', 'R112'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': UNTOUCHED}),
    ('PHOTO-20', 'R113'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': UNTOUCHED}),
    ('PHOTO-20', 'R114'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': UNTOUCHED, 'fail_if': [['chroma_ratio', '<=', 0.25]]}),
    ('PHOTO-20', 'R115'): const({'op': 'v2_pdf_photos_pb', 'photos': P20_SESSIONS, 'pass_if': [['hf_min', '>=', 0.9]]}),
    # PHOTO-24
    ('PHOTO-24', 'R020'): lambda row, ctx: {'op': 'v2_inside_all', 'texts': [rec(ctx, row)[k] for k in ('reference', 'caliber', 'case_metal', 'dial_finish')]}
                                           if rec(ctx, row) else None,
    ('PHOTO-24', 'R025'): const({'op': 'v2_inside_all', 'texts': [__import__('round2').TIMING], 'patterns': [r'.']}),
    ('PHOTO-24', 'R026'): const({'op': 'v2_inside_all', 'texts': ['LUNARA', 'CHRONOMETRY', 'MERIDIAN']}),
    ('PHOTO-24', 'R041'): lambda row, ctx: photo_cmp(p24_pdp(row, ctx), region='shown', pass_if=[['rgb_max', '<=', 8]]) if p24_pdp(row, ctx) else None,
    ('PHOTO-24', 'R042'): const(photo_cmp('lunara_pdp_meridian.jpg', region='shown', pass_if=[['rgb_max', '<=', 8]])),
    ('PHOTO-24', 'R043'): lambda row, ctx: {'op': 'v2_pdf_photos_pb', 'photos': list(P24_PHOTOS), 'region': 'shown',
                                            'only': [f'lunara_pdp_{r.lower()}.jpg' for r in (row.get('values') or {}).values() if r in P24_REFS] or None,
                                            'pass_if': [['rgb_max', '<=', 8], ['fills_image', '>=', 0.98]]},
    ('PHOTO-24', 'R044'): const({'op': 'v2_pdf_photos_pb', 'photos': list(P24_PHOTOS), 'region': 'shown', 'only': ['lunara_pdp_meridian.jpg'],
                                 'pass_if': [['rgb_max', '<=', 8], ['fills_image', '>=', 0.98]]}),
    ('PHOTO-24', 'R066'): lambda row, ctx: {'op': 'v2_text_pb', 'forbidden': ['Timed by hand and signed'], 'found': PERSON, 'photos': p24_photos(row, ctx)},
    ('PHOTO-24', 'R095'): lambda row, ctx: {'op': 'v2_text_pb', 'photos': p24_photos(row, ctx) if not row['file'].endswith('.pdf') else [],
                                            'forbidden': [{'regex': r'\b(?:luxury|luxurious|iconic|ultimate|finest|best|perfect|perfection|exceptional|unrivall?ed|'
                                                                    r'legendary|world-?class|unparalleled|exquisite|breathtaking|stunning|timeless masterpiece)\b'}]},
    ('PHOTO-24', 'R099'): const(photo_cmp([f'lunara_campaign_{i:02d}.jpg' for i in range(1, 10)], region='shown',
                                          pass_if=[['noise_ratio', '>=', 1.5]], fail_if=[['noise_ratio', '<=', 1.2]])),
    ('PHOTO-24', 'R100'): by_file(pdf=const({'op': 'v2_pdf_flat_paint_pb'}),
                                  image=p24_img(lambda row, ctx: {'op': 'v2_solid_raster_pb', 'hexes': p24_palette(ctx)})),
    ('PHOTO-24', 'R103'): lambda row, ctx: photo_cmp(p24_pdp(row, ctx), region='subject', pass_if=SAME_FACE) if p24_pdp(row, ctx) else None,
    ('PHOTO-24', 'R104'): lambda row, ctx: photo_cmp(p24_pdp(row, ctx), region='subject', pass_if=SAME_FACE) if p24_pdp(row, ctx) else None,
    ('PHOTO-24', 'R107'): const(photo_cmp([f'lunara_campaign_{i:02d}.jpg' for i in range(1, 10)], region='subject', pass_if=[['ncc_min', '>=', 0.9]])),
    # PHOTO-26
    ('PHOTO-26', 'R008'): lambda row, ctx: {'op': 'v2_product_text_pb', 'mode': 'materials', 'rows': p26_rows()},
    ('PHOTO-26', 'R020'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        ph: {'pass_if': [['frame_share', '>=', 0.98], ['ncc_min', '>=', 0.95]], 'region': 'subject'}
        for ph in ('autumn_shoot_04.jpg', 'autumn_shoot_07.jpg', 'autumn_shoot_10.jpg', 'autumn_shoot_13.jpg')}}),
    ('PHOTO-26', 'R024'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        ph: {'pass_if': [['ncc_min', '>=', 0.95]], 'region': 'subject'}
        for ph in ['autumn_shoot_12.jpg'] + [f'textile_flatlay_{i:02d}.jpg' for i in range(1, 7)]}}),
    ('PHOTO-26', 'R056'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'region': 'shown', 'pass_if': [['rgb_max', '<=', 5]]}),
    ('PHOTO-26', 'R059'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'region': 'shown', 'pass_if': [['ncc_min', '>=', 0.9],
                                                                                                                ['fills_image', '>=', 0.98]]}),
    ('PHOTO-26', 'R060'): lambda row, ctx: {'op': 'v2_text_pb', 'forbidden': p26_names(), 'found': PERSON},
    ('PHOTO-26', 'R062'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'region': 'subject', 'by_photo': {
        ph: {'pass_if': [['frame_share', '>=', 0.98], ['ncc_min', '>=', 0.95]], 'region': 'subject'}
        for ph in [f'autumn_shoot_{i:02d}.jpg' for i in range(1, 15) if i != 12]}}),
    ('PHOTO-26', 'R063'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        ph: {'pass_if': [['ncc_min', '>=', 0.9], ['fills_image', '>=', 0.98]], 'region': 'shown'}
        for ph in ('autumn_shoot_03.jpg', 'autumn_shoot_06.jpg', 'autumn_shoot_08.jpg')}}),
    ('PHOTO-26', 'R064'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        'autumn_shoot_01.jpg': {'pass_if': [['ncc_min', '>=', 0.9], ['fills_image', '>=', 0.98]], 'region': 'shown'}}}),
    ('PHOTO-26', 'R066'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        ph: {'pass_if': [['rgb_max', '<=', 5]], 'region': 'shown'}
        for ph in ('autumn_shoot_02.jpg', 'autumn_shoot_08.jpg', 'autumn_shoot_14.jpg', 'textile_flatlay_02.jpg', 'textile_flatlay_05.jpg',
                   'textile_flatlay_06.jpg')}}),
    ('PHOTO-26', 'R067'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        ph: {'pass_if': [['rgb_max', '<=', 5]], 'region': 'shown'}
        for ph in ('autumn_shoot_01.jpg', 'autumn_shoot_03.jpg', 'autumn_shoot_07.jpg', 'autumn_shoot_09.jpg', 'autumn_shoot_12.jpg',
                   'autumn_shoot_13.jpg', 'textile_flatlay_01.jpg', 'textile_flatlay_05.jpg')}}),
    ('PHOTO-26', 'R068'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        ph: {'pass_if': [['rgb_max', '<=', 5]], 'region': 'shown'} for ph in ('autumn_shoot_05.jpg', 'autumn_shoot_11.jpg', 'textile_flatlay_03.jpg')}}),
    ('PHOTO-26', 'R069'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        ph: {'pass_if': [['rgb_max', '<=', 5]], 'region': 'shown'}
        for ph in ('autumn_shoot_04.jpg', 'autumn_shoot_06.jpg', 'autumn_shoot_10.jpg', 'textile_flatlay_04.jpg')}}),
    ('PHOTO-26', 'R070'): const({'op': 'v2_pdf_photos_pb', 'photos': P26_PHOTOS, 'by_photo': {
        'autumn_shoot_13.jpg': {'pass_if': [['ncc_min', '>=', 0.9], ['fills_image', '>=', 0.98]], 'region': 'shown'}}}),
    # PHOTO-28
    ('PHOTO-28', 'R002'): const({'op': 'v2_all_of', 'checks': [{'op': 'v2_price_list_pb', 'names': P28_CLASSES},
                                                               {'op': 'v2_price_list_pb', 'block': True, 'photos': list(P28_ALL)}]}),
    ('PHOTO-28', 'R014'): const({'op': 'v2_text_pb', 'expected': [{'line': r'^\W*book\b'}], 'missing': PERSON, 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R015'): const({'op': 'v2_bg_remnant_pb', 'photos': P28_INSTRUCTORS}),
    ('PHOTO-28', 'R032'): const({'op': 'v2_action_box_pb', 'line': r'^\W*book\b', 'box': [60, 250, 1020, 1600]}),
    ('PHOTO-28', 'R033'): const({'op': 'v2_action_box_pb', 'line': r'^\W*book\b'}),
    ('PHOTO-28', 'R039'): const({'op': 'v2_each_photo_pb', 'photos': list(P28_ALL), 'then': None}),
    ('PHOTO-28', 'R040'): const({'op': 'v2_each_photo_pb', 'photos': list(P28_ALL), 'then': None}),
    ('PHOTO-28', 'R043'): const({'op': 'v2_each_photo_pb', 'photos': P28_FRAMES, 'then': None}),
    ('PHOTO-28', 'R047'): const({'op': 'v2_all_of', 'checks': [
        {'op': 'v2_text_pb', 'photos': list(P28_ALL), 'forbidden': [{'line': r'\b(?:open|opening|opens|launch\w*)\b.*(?:' + MONTH + r'|\d{1,2}/\d{1,2})|(?:'
                                                                             + MONTH + r').*\b(?:open|opening|opens|launch\w*)\b'}]},
        {'op': 'v2_text_pb', 'photos': list(P28_ALL), 'found': PERSON,
         'forbidden': [{'line': r'(?!.*\bthrough\s+dec(?:ember)?\.?\s+2027\b)(?:' + MONTH + r'|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b)'}]}]}),
    ('PHOTO-28', 'R052'): const({'op': 'v2_each_photo_pb', 'photos': list(P28_ALL), 'then': None}),
    ('PHOTO-28', 'R054'): const({'op': 'v2_pictured', 'photos': P28_BY_PHOTO, 'when': 'Dana Osei', 'then': ASK}),
    ('PHOTO-28', 'R055'): const({'op': 'v2_pictured', 'photos': P28_BY_PHOTO, 'when': 'Yuki Sato', 'then': ASK}),
    ('PHOTO-28', 'R056'): const(photo_cmp('verda_instructor_04.jpg', region='subject', pass_if=[['scale', '<=', 1.1]], absent='pass',
                                          known=[x for x in P28_ALL if x != 'verda_instructor_04.jpg'])),
    ('PHOTO-28', 'R060'): const({'op': 'v2_each_photo_pb', 'photos': P28_FRAMES, 'then': None}),
    ('PHOTO-28', 'R061'): const({'op': 'v2_each_photo_pb', 'photos': P28_FRAMES, 'then': None}),
    ('PHOTO-28', 'R067'): lambda row, ctx: {'op': 'v2_solid_raster_pb', 'hexes': pal(ctx, 'Sage', 'Oak', 'Warm Off White', 'Soft Ink') + [P28_INK],
                                            'photos': list(P28_ALL)},
    ('PHOTO-28', 'R089'): const(photo_cmp(P28_FRAMES, region='subject', fail_if=[['dc_max', '<=', 3]], absent='pass', known=P28_INSTRUCTORS)),
    ('PHOTO-28', 'R093'): const(photo_cmp(P28_FRAMES, region='subject', fail_if=[['dc_max', '<=', 3]], absent='pass', known=P28_INSTRUCTORS)),
    ('PHOTO-28', 'R094'): const(photo_cmp(P28_FRAMES, region='subject', fail_if=[['dc_max', '<=', 3]], absent='pass', known=P28_INSTRUCTORS)),
    ('PHOTO-28', 'R091'): const({'op': 'v2_all_of', 'checks': [
        {'op': 'v2_text_pb', 'photos': list(P28_ALL), 'forbidden': [{'regex': r'\bsale\b|%\s*off|\bdiscount|\bdeal\b|limited time|\bhurry\b|last chance|today only|ends soon'}]},
        {'op': 'v2_copy_only_pb', 'files': ['owner_note.txt', 'roster_2027.csv'], 'photos': list(P28_ALL)}]}),
    ('PHOTO-28', 'R092'): const({'op': 'v2_above_role_pb', 'asset': P28_MARK, 'whole': ['Verda'], 'role': 'main', 'min_gap': 0.5, 'photos': list(P28_ALL)}),
    ('PHOTO-28', 'R098'): const(photo_cmp(P28_INSTRUCTORS, region='subject', pass_if=SAME_FACE)),
    ('PHOTO-28', 'R100'): const(photo_cmp(P28_FRAMES, region='subject', pass_if=[['ncc_min', '>=', 0.9]], absent='pass', known=P28_INSTRUCTORS)),
    ('PHOTO-28', 'R102'): const({'op': 'v2_each_photo_pb', 'photos': P28_FRAMES, 'then': None}),
}
# partly measurable rules whose checks settled fewer than half of their rows on the 2026-09-28 run stay with people
# (a rule moves to code only when code answers most of its rows)
PARTLY_LOW = {('PHOTO-19', r) for r in ('R077', 'R092', 'R098', 'R104', 'R106', 'R107')} | \
             {('PHOTO-20', r) for r in ('R038', 'R106', 'R107', 'R112')} | \
             {('PHOTO-24', r) for r in ('R099',)} | \
             {('PHOTO-28', r) for r in ('R014', 'R032', 'R033', 'R047', 'R089', 'R091', 'R093', 'R094', 'R098')}
R3.update({k: v for k, v in R3_PARTLY.items() if k not in PARTLY_LOW})

HOW = {
    'v2_type_ink_pb': 'Reads each text line (OCR on images, live text on PDFs), the colour of its letters and of the ground behind it, and checks the pairing.',
    'v2_type_has_colour_pb': 'Reads the colour of each text line\'s letters and looks for one in the colour.',
    'v2_colour_only_as_pb': 'Finds every piece in the colour outside the photographs and checks each is a thin rule or sits in an allowed text line.',
    'v2_mark_ground_pb': 'Finds the mark and reads the colour of the ground round it.',
    'v2_sitter_ground_pb': 'Finds the supplied photo\'s cut-out subject and reads the flat ground wrapped round it.',
    'v2_each_photo_pb': 'Finds each supplied photo on the file, runs the check on each, and checks no other photograph is present.',
    'v2_palette_marks_pb': 'Reads every flat colour outside the photographs and checks each is a palette colour, the wordmark\'s own ink allowed in its box.',
    'v2_solid_raster_pb': 'Checks every flat designed colour is a palette colour, with no shaded area and no type over a photograph.',
    'v2_line_chars_pb': 'Reads each line of text and counts its characters.',
    'v2_above_role_pb': 'Finds the wordmark and the largest heading and compares their positions.',
    'v2_role_style_pb': 'Sorts the PDF text into roles by size and reads the font, size, letter case and line spacing of the named role.',
    'v2_pdf_grounds_pb': 'Reads the page ground and the filled shapes drawn in the PDF: their colours, sizes and opacity.',
    'v2_pdf_overlay_pb': 'Reads the PDF\'s drawing order and checks nothing is drawn over a placed photo.',
    'v2_product_text_pb': 'Reads the PDF text, ties each product name, care line and price to its product, and compares it with the product table.',
    'v2_photo_compare_pb': 'Lays the supplied photo over the placed one and compares them tile by tile: colour, detail and correlation.',
    'v2_mark_solid_pb': 'Finds the mark by its colour, confirms its shape against the supplied artwork, and checks every pixel is that colour or its edge blend.',
    'v2_wordmark_pb': 'Finds the wordmark, splits its letters from the ground and measures their height, proportions, spacing, counters and edges.',
    'v2_price_list_pb': 'Reads the names set with a price on their own row and checks the list, or that nothing else sits inside the block.',
    'v2_window_flat_pb': 'Lays the supplied photo over the placed one and checks its blown-out area is cropped away or still plain.',
    'v2_pdf_photos_pb': 'Reads every picture placed in the PDF, identifies its supplied photo and compares the colours tile by tile.',
    'v2_text_pb': 'Reads the type by OCR or from the PDF, leaving out lettering inside the supplied photos, and looks for the wording.',
    'v2_photo_aspect_pb': 'Finds the supplied photo and compares its horizontal and vertical scale and corner angles.',
    'v2_pdf_block_pb': 'Finds the texts in the PDF and checks they form one block with nothing else inside it.',
    'v2_pdf_covered_pb': 'Reads the PDF drawing order and checks nothing is drawn over the texts.',
    'v2_pdf_portraits_pb': 'Reads the pictures placed in the PDF and identifies which supplied portraits they show.',
    'v2_sitter_ground_even_pb': 'Finds the cut-out sitter and checks the ground round it is one even colour.',
    'v2_sitter_ground_same_pb': 'Reads the ground round the cut-out sitter on this file and on the reference card and compares them.',
    'v2_pdf_printer_marks_pb': 'Reads the PDF page boxes and drawn paths for crop and registration marks.',
    'v2_pdf_flat_paint_pb': 'Reads the PDF paint: opacity, shading, patterns, soft masks and blend modes.',
    'v2_pdf_tracking_pb': 'Measures letter spacing from the PDF glyph positions and compares it with the commonest text.',
    'v2_ask_pb': 'Hands the row to a person (used where code settles only the files without the element).',
    'v2_bg_remnant_pb': 'Lays the supplied photo over the placed one and looks for its original backdrop left unchanged round the subject.',
    'v2_monogram_pb': 'Finds the monogram by its colour and measures its width, its place over the name and how often it appears.',
    'v2_serif_spans_pb': 'Reads the PDF fonts and flags any serif type other than the allowed lines.',
    'v2_copy_only_pb': 'Reads every line of type and checks its words come from the supplied copy.',
    'v2_action_box_pb': 'Finds the action line and its button and checks they sit inside the allowed area.',
}


def convert(tid, rid, row, ctx):
    h = R3.get((tid, rid))
    return h(row, ctx) if h else None
