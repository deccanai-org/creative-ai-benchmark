"""Round 5, vision-model helper b (2026-10-29): objective look, count and read checks on PHOTO-04, PHOTO-06, PHOTO-20,
PHOTO-24 and PHOTO-28, answered by the vision model through ops_r5_vlm.py (every question asked twice; a check is
decided only when both answers agree) and the two thin ops in ops_r5_vlm_b.py (vlm_text_rx_r5vb: every text copied
once, then regular expressions in code; vlm_items_r5vb: one list question, every item sorted by code).

One handler per (task, rule), taking (row, ctx) and returning an assertion, or None when the row cannot be checked.
Each assertion carries its own plain `how` sentence. Absence passes (`none_found: 'pass'`) only for rules whose
planted copies (W/round5/vlm/planted_b, two sets) proved the model finds such a thing when it is there.

Converted (28 rules): PHOTO-04 R009, R014, R018, R032; PHOTO-06 R002, R005, R007, R009, R025, R026, R036, R069, R070,
R080; PHOTO-20 R017, R028, R038; PHOTO-24 R006, R009, R011, R016, R029, R031, R035; PHOTO-28 R014, R033, R047, R091.

Left with people: reads of text set in capitals (PHOTO-04 R015, R017; PHOTO-19 R006; PHOTO-24 R001, R010, R017), since a
difference only in letter case goes to a person; judgement or fine detail (damage repair PHOTO-06 R010 to R017,
lighting PHOTO-19 R075, legibility PHOTO-19 R001, dial finish PHOTO-24 R101, dominance PHOTO-24 R110, shadows PHOTO-26
R059, whole pairs PHOTO-26 R022, the gate-plate photo PHOTO-04 R025); meaning of the copy (luxury, light, stone, claims:
PHOTO-04 R082, R083, R087, R090, R092, R094, R096; PHOTO-24 R028, R032, R034; PHOTO-26 R018); readings open to more
than one answer (PHOTO-06 R027 plate line, PHOTO-20 R035 typographic panel, PHOTO-24 R030 timing wording, PHOTO-26 R003,
R010 to R013, R021, R053, R061, PHOTO-04 R011 cover photographs).

Project rules kept: a difference only in letter case goes to a person, and an item close to an allowed one
(similarity 0.8 or more) is a possible misreading, never a fail.
"""
from __future__ import annotations

import re

# ------------------------------------------------------------------ shared pieces
TWO = ('Image 1 is the original scan of an old photograph. Image 2 is the {what} made from it. ')


def _src(row):
    """hollis_scan_NN.jpg for a PHOTO-06 row (slot 1, or the deliverable's own number)."""
    v = (row.get('values') or {}).get('1', '')
    if re.fullmatch(r'hollis_scan_\d\d\.jpg', v):
        return v
    m = re.search(r'hollis-scan-(\d\d)', row['output_id'])
    return f'hollis_scan_{m.group(1)}.jpg' if m else None


def _pair(row, what):
    s = _src(row)
    if not s:
        return None
    return [{'src': f'asset:{s}', 'label': 'Image 1: the original scan.'},
            {'src': 'deliverable', 'label': f'Image 2: the {what}.'}]


def _strip(v):
    return (v or '').strip().strip('“”"')


# ------------------------------------------------------------------ PHOTO-06: the Hollis restorations and share cards
def p06_people(row, ctx):
    return {'op': 'vlm_count_r5v', 'expected': 1,
            'question': ('How many people are shown in the photograph on this image? Count every person whose face or '
                         'body is visible, including babies, children and anyone partly visible or in the background. '
                         'Do not count people in pictures hanging on a wall, statues or reflections. Give the number in '
                         'count.'),
            'how': 'Asks the vision model how many people the photograph shows; code checks it is one, as in the source scan.'}


def p06_caption_margin(row, ctx):
    return {'op': 'vlm_yesno_r5v', 'pass_on': 'no',
            'question': ('This image is a share card: a scanned photograph (with any album page, mount or scanner '
                         'background around the print) placed on a plain margin, with caption text. Does any caption '
                         'text or other added text lie on top of the photograph or the area around the print that came '
                         'with the scan, instead of on the plain margin? answer yes if any text overlaps that picture '
                         'area, no if all text sits on the plain margin outside it.'),
            'how': 'Asks the vision model whether any caption text lies on the picture rather than on the plain margin; it passes when the model finds none.'}


def p06_no_added_text(row, ctx):
    imgs = _pair(row, 'restored file')
    if not imgs:
        return None
    return {'op': 'vlm_items_r5vb', 'images': imgs, 'none_found': 'pass',
            'question': (TWO.format(what='restored file') +
                         'List every caption, word, letter, number or drawn straight line (a rule) that appears on '
                         'Image 2 but not on Image 1. The edges of the print, the album page or mount, photo corners and '
                         'the scanner background are not drawn lines. answer yes if there is at least one, no if there '
                         'is none.'),
            'how': 'Shows the vision model the source scan and the restored file and asks it to list any text, numeral or ruled line the restored file adds; any item fails.'}


def p06_no_frame_master(row, ctx):
    imgs = _pair(row, 'restored file')
    if not imgs:
        return None
    return {'op': 'vlm_items_r5vb', 'images': imgs, 'none_found': 'pass',
            'question': (TWO.format(what='restored file') +
                         'List every frame or border, ornament, logo or brand mark, and drop shadow that Image 2 has but '
                         'Image 1 does not. The print\'s own edges, its album page or mount, photo corners and the scanner '
                         'background, as seen in Image 1, are not added. Text and single plain straight lines are checked '
                         'separately: do not list them. answer yes if there is at least one, no if there is none.'),
            'how': 'Shows the vision model the source scan and the restored file and asks it to list any frame, ornament, brand mark or drop shadow the restored file adds; any item fails.'}


def p06_no_ornament_share(row, ctx):
    imgs = _pair(row, 'share card')
    if not imgs:
        return None
    return {'op': 'vlm_items_r5vb', 'images': imgs, 'none_found': 'pass',
            'question': (TWO.format(what='share card') +
                         'Image 2 shows the photograph on a plain margin with plain caption text. List every ornament, '
                         'decorative frame or border, script (handwriting-style) lettering, drop shadow, logo or monogram '
                         'on Image 2 that is not part of the photograph as seen in Image 1. Plain printed caption text, '
                         'plain thin straight lines and the plain margin do not count. answer yes if there is at least '
                         'one, no if there is none.'),
            'how': 'Shows the vision model the source scan and the share image and asks it to list any ornament, decorative frame, script lettering, drop shadow, logo or monogram added; any item fails.'}


def p06_no_person_cut(row, ctx):
    imgs = _pair(row, 'restored file')
    if not imgs:
        return None
    return {'op': 'vlm_yesno_r5v', 'images': imgs, 'pass_on': 'no',
            'question': (TWO.format(what='restored file') +
                         'Compare the people in the two images. Is any part of any person visible in Image 1 (head, '
                         'hair, face, hands, arms, legs, feet or clothing) missing from Image 2, cut off by its edge or '
                         'covered by something? answer yes if any part is missing, cut off or covered, no if every '
                         'person is shown as fully as in Image 1.'),
            'how': 'Shows the vision model the source scan and the restored file and asks whether any part of a person is missing, cut off or covered; it passes when the model finds none.'}


def p06_deckle(row, ctx):
    what = 'share card' if row['output_id'].startswith('share') else 'restored file'
    imgs = _pair(row, what)
    if not imgs:
        return None
    return {'op': 'vlm_yesno_r5v', 'images': imgs, 'pass_on': 'yes',
            'question': (TWO.format(what=what) +
                         'The print in Image 1 has a deckled edge: a wavy, scalloped border along its sides. Look at the '
                         'print in Image 2. Is its deckled edge kept along all four sides, with no side trimmed off or '
                         'cut straight (turning or levelling the print is fine)? answer yes if the deckled edge is kept '
                         'on all four sides, no if any side is trimmed or cut straight.'),
            'how': 'Shows the vision model the source scan and the file and asks whether the print keeps its deckled edge on all four sides; it passes when the model says yes.'}


NAMES_Q = ('List every person named in the caption text on this image (the text set beside or below the photograph). '
           'Copy each name exactly as printed, one entry per person, and list a person printed twice only once. When '
           'several first names share one surname (for example "Ann, Bob and Cy Lee"), give each person with the surname, '
           'as "Ann Lee", "Bob Lee" and "Cy Lee". Do not list place names or the archive or collection name. answer yes '
           'if any person is named, no if none.')


def _names(*people):
    ok = {'Nan', 'Hollis'}   # the catalogue calls Ada "Nan"; the surname alone names no one new
    for p in people:
        ok.add(p)
        ok.add(p.split()[0])
    return sorted(ok)


def p06_caption_names(fixed=None):
    def h(row, ctx):
        others = fixed or [_strip((row.get('values') or {}).get('1'))]
        people = ['Ada Hollis'] + [o for o in others if o]
        return {'op': 'vlm_items_r5vb', 'question': NAMES_Q, 'ok': _names(*people), 'near': 0.8,
                'how': ('Asks the vision model to list every person the caption names; code checks each is '
                        + ', '.join(people[:-1]) + (' or ' if len(people) > 1 else '') + people[-1] + '.')}
    return h


# ------------------------------------------------------------------ PHOTO-20: Astrid Vellacourt speaker set
def p20_cut_letters(row, ctx):
    return {'op': 'vlm_yesno_r5v', 'pass_on': 'no',
            'question': ('Look at the talk title, the event name and the date printed on this banner. Is any letter of '
                         'them cut off by an edge of the image, so that part of the letter lies outside the image? '
                         'answer yes if any letter is cut off, no if every letter is complete.'),
            'how': 'Asks the vision model whether any letter of the talk title, event name or date is cut off at an edge; it passes when the model finds none.'}


def p20_social(row, ctx):
    a = {'op': 'vlm_items_r5vb', 'none_found': 'pass',
         'question': ('List every social media handle (such as @name), follower, subscriber or like count, and social '
                      'platform icon or logo (for example Instagram, LinkedIn, X or Twitter, TikTok, Facebook or '
                      'YouTube) visible anywhere on this image, each copied or named exactly. answer yes if there is at '
                      'least one, no if there is none.'),
         'how': 'Asks the vision model to list any social handle, follower count or platform icon on the file; any item fails.'}
    if ctx.outputs[row['output_id']]['path'].endswith('.pdf'):
        small = row['output_id'].startswith('talk-card')
        a['images'] = [{'src': 'deliverable', 'page': 1, 'dpi': 288 if small else 144}]
    return a


BIO = ['Vellacourt & Sund is a six-person industrial design studio working on products people keep.',
       'Astrid Vellacourt co-founded and runs Vellacourt & Sund, a six-person industrial design studio.',
       "She works on physical products from first sketch to production and is raising a seed round to grow the studio's own product line."]


def p20_bio(row, ctx):
    """Every biography sentence must be one of vellacourt_bio_copy.txt's own (the studio one-liner and the short bio);
    a sentence with a figure the file does not give fails; any other sentence goes to a person."""
    return {'op': 'vlm_items_r5vb', 'ok': BIO + [b.rstrip('.') for b in BIO], 'bad_rx': [r'\d'], 'near': 0.9, 'near_item': True,
            'question': ('Copy the biography text on this page sentence by sentence: the paragraph or paragraphs that '
                         'describe the person and her studio, not the name heading, the role line, the talk titles and '
                         'their descriptions or the footer. Give one sentence per entry, joining a sentence broken across '
                         'lines, copied exactly as printed. answer yes if there is a biography, no if there is none.'),
            'how': ('Asks the vision model to copy the biography sentence by sentence; code checks each is a sentence of '
                    'vellacourt_bio_copy.txt word for word (a sentence with a figure the file does not give fails).')}


# ------------------------------------------------------------------ PHOTO-24: Lunara watches
_RES = r'(?:h|hrs?|hours?)\b(?:\s|-)*(?:of\s)?(?:power\s)?reserve'


def _reserve_not(n):
    return (rf'\b(?!{n}(?!\d))\d{{2,3}}\s?-?\s?{_RES}|reserve\W{{0,3}}(?:of\s)?(?!{n}(?!\d))\d{{2,3}}' if n else
            rf'\b\d{{2,3}}\s?-?\s?{_RES}|reserve\W{{0,3}}(?:of\s)?\d{{2,3}}')


def _hours_not(n):
    """An hour figure with no 'reserve' beside it, other than the caliber's own: a person reads it."""
    return rf'\b(?!{n}(?!\d))\d{{2,3}}\s?-?\s?(?:h|hrs?|hours?)\b' if n else r'\b\d{2,3}\s?-?\s?(?:h|hrs?|hours?)\b'


AUTO = r'\bautomatic\b|self[- ]?winding|auto[- ]?wind'
HAND = r'hand[- ]?wound|hand[- ]?winding|manual(?:ly)?[- ]?(?:wound|winding)'
SMALL = r'small[- ]?seconds'
CALIBER = {'LM-01': [AUTO, SMALL, _reserve_not(42)], 'LM-02': [HAND, SMALL, _reserve_not(48)],
           'LM-03': [AUTO, _reserve_not(None)]}
HOURS = {'LM-01': [_hours_not(42)], 'LM-02': [_hours_not(48)], 'LM-03': [_hours_not(None)]}
REF_CAL = {'Meridian': 'LM-01', 'Ardent': 'LM-01', 'Selene': 'LM-02', 'Vesper': 'LM-02', 'Halcyon': 'LM-03'}


def p24_movement(cal):
    def h(row, ctx):
        return {'op': 'vlm_text_rx_r5vb', 'forbid_rx': CALIBER[cal], 'person_rx': HOURS[cal], 'none_found': 'pass',
                'how': (f'Copies every text on the file with the vision model; code checks no movement wording contradicts '
                        f'lunara_notes.txt for {cal} (winding, reserve hours, small seconds).')}
    return h


def p24_movement_shown(row, ctx):
    return {'op': 'vlm_text_rx_r5vb', 'none_found': 'pass',
            'by_name': {r: CALIBER[c] for r, c in REF_CAL.items()},
            'person_rx': [r'\b\d{2,3}\s?-?\s?(?:h|hrs?|hours?)\b(?!\W{0,3}(?:of\s)?(?:power\s)?reserve)'],
            'how': ('Copies every text on the file with the vision model; code finds the one reference named and checks no '
                    'movement wording contradicts lunara_notes.txt for its caliber.')}


def p24_timing(row, ctx):
    exp = _strip((row.get('values') or {}).get('1'))
    if not exp:
        return None
    return {'op': 'vlm_text_rx_r5vb', 'none_found': 'pass',
            'values_rx': {'rx': r'([+\-±]?\s?\d+(?:[.,]\d+)?\s?(?:s|sec|secs|seconds?)\s?(?:/|per|a)\s?(?:day|d)\b)',
                          'allowed': [exp]},
            'person_rx': [r'[+\-±]\s?\d+(?:[.,]\d+)?\s?(?:s|sec|secs|seconds?)\b'],
            'how': f'Copies every text on the file with the vision model; code checks any timing result reads {exp}.'}


BAND = ['$4,000-$12,000', '$4,000 - $12,000', '$4,000 to $12,000', '$4,000-12,000']
PRICE_RX = r'((?:[$€£]|\busd\s?|\beur\s?|\bgbp\s?)\d[\d,.]*(?:\s?(?:-|to)\s?(?:[$€£]|usd\s?|eur\s?|gbp\s?)?\d[\d,.]*)?)'


def p24_price(row, ctx):
    return {'op': 'vlm_text_rx_r5vb', 'none_found': 'pass', 'values_rx': {'rx': PRICE_RX, 'allowed': BAND},
            'person_rx': [r'\b\d[\d,.]*\s?(?:usd|eur|gbp|dollars?|euros?|pounds?)\b', r'\bprice\b'],
            'how': 'Copies every text on the file with the vision model; code checks any price shown is the band $4,000-$12,000.'}


def p24_other_refs(row, ctx):
    return {'op': 'vlm_items_r5vb', 'images': [{'src': 'deliverable', 'page': 1}, {'src': 'deliverable', 'page': 2}],
            'ok': list(REF_CAL), 'ok_rx': [r'^(?:lunara|chronometry|lunara chronometry)$'], 'near': 0.8,
            'question': ('These two images are the pages of a watch dealer launch sheet. List every watch reference '
                         '(model) name printed on the pages, each once, copied exactly as printed. Do not list the brand '
                         'name, caliber codes (such as LM-01), serial numbers, case metals or dial finishes. answer yes if '
                         'there is at least one, no if there is none.'),
            'how': 'Asks the vision model to list every watch reference named on both pages; code checks each is Meridian, Selene, Ardent, Halcyon or Vesper.'}


# ------------------------------------------------------------------ PHOTO-28: Verda studio
MONTHS = (r'\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\b|\b(?:january|february|march|april|june|july|august|'
          r'september|october|november|december)\b|\b\d{1,2}[/.]\d{1,2}\b|\b20\d\d\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s)?[a-z]{3,9}\b')


def p28_booking(row, ctx):
    return {'op': 'vlm_yesno_r5v', 'pass_on': 'yes',
            'question': ('Does this image show a booking action: a button, or a line of text, that tells the viewer how '
                         'to book (for example a "Book a class" button or a booking web address)? answer yes or no.'),
            'how': 'Asks the vision model whether the image shows a booking button or a line telling the viewer how to book.'}


def p28_booking_inside(row, ctx):
    return {'op': 'vlm_yesno_r5v', 'pass_on': 'no',
            'question': ('Find the booking action on this image (the button or line of text that tells the viewer how to '
                         'book). Does any part of it, its button shape or its text, run off an edge of the image, so that '
                         'part of it is cut off? answer yes if part of it is cut off at an edge, no if it lies fully '
                         'inside the image.'),
            'how': 'Asks the vision model whether any part of the booking button or line is cut off at an image edge; it passes when the model finds none.'}


def p28_opening(row, ctx):
    return {'op': 'vlm_items_r5vb', 'none_found': 'pass',
            'bad_rx': [rf'(?:open|launch|doors).*(?:{MONTHS})|(?:{MONTHS}).*(?:open|launch)'],
            'question': ('Copy every piece of text on this image that states when the studio opens or launches: an '
                         'opening or launch date, day, month, season or year. answer yes if there is any, no if there is '
                         'none.'),
            'how': 'Asks the vision model to copy any text stating when the studio opens; a copied opening date or month fails, anything else goes to a person.'}


URGENT = (r'\bsale\b|\d\s?%|percent|\boff\b|discount|limited[- ]time|limited offer|hurry|last chance|ends? (?:soon|today|tonight)'
          r'|today only|only \d+ (?:left|places|spots)|few (?:places|spots) left|don.?t miss|act now|while (?:stocks|spaces|places) last'
          r'|save \$|save \d|save up to|\bdeal\b|promo|clearance')


def p28_urgency(row, ctx):
    return {'op': 'vlm_items_r5vb', 'none_found': 'pass', 'bad_rx': [URGENT],
            'question': ('Copy every piece of discount or urgency wording on this image, such as sale, a percentage or an '
                         'amount off, a discount, limited time, hurry, last chance, ends soon, today only or only a few '
                         'places left. answer yes if there is any, no if there is none.'),
            'how': 'Asks the vision model to copy any discount or urgency wording; plain discount or urgency words fail, other copied wording goes to a person.'}


# ------------------------------------------------------------------ PHOTO-04: Verranza villas
def p04_min_stay(row, ctx):
    n = _strip((row.get('values') or {}).get('1'))
    if not n.isdigit():
        return None
    return {'op': 'vlm_text_rx_r5vb', 'none_found': 'pass',
            'values_rx': {'rx': r'\bmin(?:imum|\.)?\s*(?:stay)?\s*(?:of|is|:)?\s*(\d+)\s*-?\s*nights?\b|\b(\d+)\s*-?\s*nights?\s*min(?:imum|\.)?\b',
                          'allowed': [n]},
            'person_rx': [r'\b\d+\s*-?\s*nights?\b', r'\bminimum\b|\bmin\.'],
            'how': f'Copies every text on the file with the vision model; code checks any minimum stay given is {n} nights.'}


def p04_no_fienile(row, ctx):
    return {'op': 'vlm_text_rx_r5vb', 'none_found': 'pass', 'forbid_rx': [r'fienile'],
            'how': 'Copies every text on the file with the vision model; code checks Casa Fienile is not named.'}


def p04_fienile_entry(row, ctx):
    return {'op': 'vlm_items_r5vb', 'images': [{'src': 'deliverable', 'page': p, 'dpi': 100} for p in range(1, 7)],
            'ok_rx': [r'verranza|oliveto|scogliera'], 'bad_rx': [r'fienile'],
            'question': ('These images are the pages of a villa brochure, in order. List every house name that appears '
                         'as the heading of a section or page, as the label of a photograph, or as the label of a row or '
                         'column in a table of rates, prices, sleeps figures or minimum stays. Copy each house name as '
                         'printed, once each. Do not list a name that appears only inside a sentence of running text. '
                         'answer yes if there is at least one, no if there is none.'),
            'how': 'Shows the vision model every page and asks it to list each house name used as a section heading, photo label or rates table label; Casa Fienile among them fails.'}


def p04_monogram(row, ctx):
    return {'op': 'vlm_items_r5vb', 'none_found': 'pass',
            'need_rx': [r'\bv\b', r'\bc\b', r'oval|ellips|ring|border', r'anchor'],
            'question': ('Is there a monogram anywhere on this image: a mark made of interlocked letters, often set '
                         'inside an outline? If there is none, answer no and list nothing. If there is one, answer yes '
                         'and list every part of it you can clearly see, as separate short items: each letter, each line '
                         'or shape round the letters, and each small symbol or picture inside it.'),
            'how': ('Asks the vision model whether the image carries a monogram and, if so, to list its parts; code '
                    'checks the V, the C, the oval and the anchor are all there (no monogram passes).')}


R5 = {
    # PHOTO-06
    ('PHOTO-06', 'R002'): p06_people,
    ('PHOTO-06', 'R025'): p06_caption_margin,
    ('PHOTO-06', 'R026'): p06_no_added_text,
    ('PHOTO-06', 'R069'): p06_no_frame_master,
    ('PHOTO-06', 'R070'): p06_no_ornament_share,
    ('PHOTO-06', 'R080'): p06_no_person_cut,
    ('PHOTO-06', 'R036'): p06_deckle,
    ('PHOTO-06', 'R005'): p06_caption_names(),
    ('PHOTO-06', 'R007'): p06_caption_names([]),
    ('PHOTO-06', 'R009'): p06_caption_names(['Ruth Hollis', 'Frank Hollis', 'Carol Hollis']),
    # PHOTO-20
    ('PHOTO-20', 'R017'): p20_cut_letters,
    ('PHOTO-20', 'R028'): p20_social,
    ('PHOTO-20', 'R038'): p20_bio,
    # PHOTO-24
    ('PHOTO-24', 'R006'): p24_timing,
    ('PHOTO-24', 'R009'): p24_movement('LM-03'),
    ('PHOTO-24', 'R011'): p24_movement('LM-01'),
    ('PHOTO-24', 'R016'): p24_movement_shown,
    ('PHOTO-24', 'R029'): p24_price,
    ('PHOTO-24', 'R035'): p24_price,
    ('PHOTO-24', 'R031'): p24_other_refs,
    # PHOTO-28
    ('PHOTO-28', 'R014'): p28_booking,
    ('PHOTO-28', 'R033'): p28_booking_inside,
    ('PHOTO-28', 'R047'): p28_opening,
    ('PHOTO-28', 'R091'): p28_urgency,
    # PHOTO-04
    ('PHOTO-04', 'R009'): p04_min_stay,
    ('PHOTO-04', 'R014'): p04_no_fienile,
    ('PHOTO-04', 'R018'): p04_fienile_entry,
    ('PHOTO-04', 'R032'): p04_monogram,
}

HOW = {
    'vlm_text_rx_r5vb': 'Copies every text on the file with the vision model (asked twice); code checks the copied text with fixed patterns.',
    'vlm_items_r5vb': 'Asks the vision model (twice) to list the items of one kind on the file; code checks every listed item.',
}
