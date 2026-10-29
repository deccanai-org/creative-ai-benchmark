"""Round 4 conversions for photographs (2026-10-28): palette reads with the whole placed photo frame left out
(PHOTO-08 R046, PHOTO-10 R052), shadow detail and clipped whites against the supplied photos (PHOTO-08, PHOTO-04,
PHOTO-24), the white border of a restored print (PHOTO-06), the Northgrove wordmark's counters and lettering
(PHOTO-10), visible grain and the placed wordmarks' texture (LAYOUT-12).

One handler per (task, rule), taking (row, ctx) and returning an assertion for tools/auto_verifier (round 4 ops in
ops_r4_photo.py, op names ending _r4p), or None when the row cannot be checked exactly.

Left with people (tried in round 4, see the round-4 report): PHOTO-08 R030, R037, R042 (the cut-out cars on the
cards are not found against their supplied photos, so every row came back to a person); PHOTO-06 R041 (the border's
yellow lies between the bands and skin is not read) and R042 (how washed out a picture looks is judgement); PHOTO-19
R077 (v2_bg_remnant_pb decides 4 of 18 cards); PHOTO-10 R102 and R099 (the mark on capsule-carousel-p01 is not read
by OCR), R087 and R096 (northgrove_mark_transparent.svg holds a dark strip where the leaf should be, so the leaf's
size and spacing cannot be measured against it).
"""
from __future__ import annotations

from round3_photo_a import (CHAR, CNAVY, GRAPHITE, NAVY, OAT, OFFW, OLIVE, P08_ROUNDELS, P10_PHOTOS, SGREY, SWHITE, TEAL, WGP,
                            p08_photos)
from round3_photo_b import P24_PHOTOS


def const(a):
    return lambda row, ctx: dict(a)


BROOKMERE = [f'M3105_brookmere_sable_{v}.jpg' for v in ('front34', 'side', 'rear34')]
P04_HOUSE = {'booking-hero-oliveto': 'oliveto', 'booking-hero-scogliera': 'scogliera', 'booking-hero-verranza': 'verranza'}
# the wordmark: a line reading NORTHGROVE alone (after at most one stray glyph, the leaf read as a letter); its
# lettering has four enclosed counters (two O, two R)
MARK = {'word': 'NORTHGROVE'}


def p04_house_photos(row, ctx):
    h = P04_HOUSE.get(row['output_id'])
    return [f'{h}_{k}.jpg' for k in ('pool', 'terrace', 'bedroom', 'living')] if h else None


R4 = {
    # palette reads: the whole placed photo frame is left out, not only its textured part (round 3 gave wrong fails
    # on the tyres of the cut-out car on vehicle-card-r006 and the flat photo backdrops of capsule-carousel p01, p06)
    ('PHOTO-08', 'R046'): lambda row, ctx: {'op': 'v2_palette_frames_r4p', 'hexes': [NAVY, SWHITE, GRAPHITE, TEAL, SGREY],
                                            'photos': p08_photos(ctx, row) + P08_ROUNDELS},
    ('PHOTO-10', 'R052'): const({'op': 'v2_palette_frames_r4p', 'hexes': [CHAR, WGP, OLIVE, OAT, CNAVY, OFFW], 'photos': P10_PHOTOS}),
    # against the supplied photos
    ('PHOTO-08', 'R038'): const({'op': 'v2_shadow_detail_r4p', 'photos': BROOKMERE}),
    ('PHOTO-04', 'R109'): lambda row, ctx: ({'op': 'v2_shadow_detail_r4p', 'photos': p04_house_photos(row, ctx)}
                                            if p04_house_photos(row, ctx) else None),
    ('PHOTO-24', 'R045'): const({'op': 'v2_clip_white_r4p', 'photos': list(P24_PHOTOS), 'every': True}),
    ('PHOTO-06', 'R037'): const({'op': 'v2_border_cast_r4p', 'photo': 'hollis_scan_06.jpg', 'cast': 'red'}),
    ('PHOTO-06', 'R039'): const({'op': 'v2_border_cast_r4p', 'photo': 'hollis_scan_07.jpg', 'cast': 'green'}),
    # the Northgrove wordmark
    ('PHOTO-10', 'R101'): const(dict(MARK, op='v2_counters_open_r4p', counters=4)),
    ('PHOTO-10', 'R090'): const(dict(MARK, op='v2_lettering_kept_r4p', mark='northgrove_mark_transparent.svg')),
    # grain
    ('LAYOUT-12', 'R157'): const({'op': 'v2_grain_r4p'}),
    ('LAYOUT-12', 'R155'): const({'op': 'v2_grain_r4p', 'none_ok': True}),
    # no knit texture round the Meridian Brass wordmark: every picture placed in the PDF is a one-ink transparent mark
    # or an allowed archive photograph (the release post, an image, goes to a person)
    ('LAYOUT-12', 'R072'): const({'op': 'v2_pdf_flat_marks_r4p', 'textured': ['umbra_wordmark_meridian.jpg'],
                                  'allowed': [f'umbra_archive_night_0{i}.jpg' for i in range(1, 7)]}),
}

HOW = {
    'v2_palette_frames_r4p': 'Leaves out every placed photograph as a whole frame, then reads every flat colour left and checks each is a palette colour.',
    'v2_shadow_detail_r4p': 'Finds the supplied photo in the deliverable and checks its shadows keep their detail and are not turned to solid black.',
    'v2_clip_white_r4p': 'Finds the supplied photo in the deliverable and looks for areas clipped to flat white.',
    'v2_border_cast_r4p': 'Finds the supplied scan in the deliverable and reads the colour of the print\'s white border.',
    'v2_counters_open_r4p': 'Reads the wordmark by OCR, finds the enclosed counters of its letters and checks each shows the ground round the mark.',
    'v2_lettering_kept_r4p': 'Reads the wordmark by OCR and compares the shape and proportions of its letters with the supplied mark.',
    'v2_pdf_flat_marks_r4p': 'Reads every picture placed in the PDF: each must be a one-ink transparent mark or an allowed photograph, never the textured photo.',
    'v2_grain_r4p': 'Measures the fine grain in the smooth parts of every photograph, against the photograph\'s tonal range.',
}
