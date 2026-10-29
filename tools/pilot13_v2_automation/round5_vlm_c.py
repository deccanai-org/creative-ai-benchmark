"""Round 5 vision-model conversions, helper c (2026-10-29): LAYOUT-12, MOTION-11 and VECTOR-04, objective look,
count and read checks answered by the vision model through tools/auto_verifier/ops_r5_vlm.py (shared ops, names end
_r5v) and ops_r5_vlm_c.py (helper c's thin ops, names end _r5vc). Every question is asked twice; a check passes or
fails only when both answers agree, anything else goes to a person.

These three tasks have no real model run: every rule here was tested on the made files (W/made3/good, bad, bad2,
bad3, bad4 and bad5; bad5 carries helper c's planted defects, listed in W/made3/defects5_c.json).

One handler per (task, rule), taking (row, ctx) and returning an assertion; each assertion carries its own plain
sentence in 'how'.

Tried and left with people (round-5 report): MOTION-11 R111 (with an ear tip or the tail tip cut away from Scrap,
both answers still called him whole), R024 (the frames asked about cover only the closing card, so a title stack
held earlier in a teaser would be missed); VECTOR-04 R051 (with the hairline ring removed, one answer still saw a
ring and open space), R110 (the planted traced bag outline never drew two agreeing answers).
"""
from __future__ import annotations

L12, M11, V04 = 'LAYOUT-12', 'MOTION-11', 'VECTOR-04'


def unq(v):
    return str(v or '').strip().strip('“”"').strip()


# ------------------------------------------------------------------ LAYOUT-12 (After Dark posters, deck, posts)
REMAINING = 'The Blue Hour, Vespertine, The Eastons, Koa, and Laurel and the Dive'
POSTER = {'src': 'deliverable', 'page': 1, 'dpi': 144, 'max_side': 3072}
DECK = {'dpi': 144, 'max_side': 2048}

Q_SPONSOR = (
    'List every sponsor or partner credit on this design: any logo of a company, bank, brewery, drinks maker, shop, '
    'media outlet or other business, and any line such as presented by, sponsored by, supported by, in partnership '
    'with, in association with or powered by. Do not list the series or venue name (such as UMBRA / LOFT or Umbra '
    'Loft), act names, the logo lettering (wordmarks) of the acts, dates, times, prices, or the venue\'s address, '
    'licence and access lines. Copy each item\'s text, or describe it in a few words if it has no text. answer yes if '
    'there is at least one, no if there is none.')
Q_CAPTION = (
    'Look at every photograph on this design, including photographs inside any small pictures of posters shown on it. '
    'List every caption or credit that names who is shown in a photograph: for example Pictured: NAME, Photo: NAME, '
    'NAME on stage, NAME live, or a name set on or right against a photograph as its label. Do not list billing that '
    'is set apart from the photographs (act names listed with their dates, door times and prices), titles, or the '
    'venue name. Copy each caption exactly. answer yes if there is at least one, no if there is none.')
Q_TYPE_ONLY = (
    f'This design bills these acts: {REMAINING}. Is any of these five act names also, or instead, shown as a logo: '
    'lettering designed as a wordmark or badge (for example inside a ring or emblem, in a decorative, stencil, script '
    'or distressed style, or with a picture mark), rather than plain typeset text like the other names in the billing '
    'list? List each of the five acts that has such a logo. answer yes if at least one does, no if none does.')
Q_NIGHT_FERRY = (
    'Is the name NIGHT FERRY shown anywhere on this design as logo lettering: a wordmark or badge, stencil letters, '
    'distressed, worn, cracked or textured letters, hand-drawn, brush or decorative lettering, or a picture mark? '
    'Plain clean typeset text, like the act names in the billing list, does not count. List each such rendering of '
    'NIGHT FERRY. answer yes if there is at least one, no if there is none.')
Q_DIRECTION = (
    'These images are the pages of a pitch deck for a poster series. Does any page say which one of the poster '
    'directions (for example type-led, image-led or graphic-led) the nine release posts adapt, follow or are based '
    'on? If so, copy that sentence into values. answer yes if a page says it, no if no page says which direction '
    'the release posts use.')
Q_STACK = (
    'Find the series title: the venue or series name set in large letters near the top of this design, above the '
    'dates and act names (a name like UMBRA / LOFT). Count the rows of letters it is set on: count 1 if it runs on a '
    'single line, 2 if it is stacked on two rows, and so on; count 0 if there is no such title. answer yes if you '
    'found the series title, no if there is none.')
Q_SABLE = (
    'Image 1 is the supplied logo lettering (wordmark) of the band Sable Quartet. Image 2 is a poster. Does image 2 '
    'show both of these: (a) that same wordmark (the same letter shapes as image 1, in any colour), and (b) separately '
    'from it, the name SABLE QUARTET set as plain typeset text in the poster\'s own type? answer yes only if both are '
    'on image 2; answer no if either is missing.')

H_SPONSOR = ('Asks the vision model to list every sponsor logo or presented by, sponsored by or similar credit; it '
             'fails when both answers list one and passes when both find none.')
H_CAPTION = ('Asks the vision model to copy every caption or credit naming who is shown in a photograph; it fails '
             'when both answers copy one that names a billed act, and passes when both find none.')
H_TYPE_ONLY = ('Asks the vision model whether The Blue Hour, Vespertine, The Eastons, Koa or Laurel and the Dive is '
               'shown as a logo or wordmark rather than plain type; it fails when both answers name one and passes '
               'when both find none.')
H_NIGHT_FERRY = ('Asks the vision model whether NIGHT FERRY is shown as logo, stencil, distressed or other designed '
                 'lettering rather than plain type; it fails when both answers find one and passes when both find none.')


def billed_names(ctx):
    names = set()
    for v in ctx.records.values():
        for k in ('headline', 'support'):
            if v.get(k):
                names.add(v[k])
    return sorted(names)


def l12_sponsor(row, ctx):
    if row['output_id'] == 'promoter-deck':
        return {'op': 'vlm_pages_r5vc', 'then': 'vlm_list_r5v', 'page_spec': DECK, 'question': Q_SPONSOR,
                'none_found': 'pass', 'how': H_SPONSOR + ' Every page is shown.'}
    img = POSTER if row['output_id'].startswith('poster') else {'src': 'deliverable'}
    return {'op': 'vlm_list_r5v', 'images': [img], 'question': Q_SPONSOR, 'none_found': 'pass', 'how': H_SPONSOR}


def l12_caption(row, ctx):
    a = {'question': Q_CAPTION, 'names': billed_names(ctx), 'none_found': 'pass', 'how': H_CAPTION}
    if row['output_id'] == 'promoter-deck':
        return dict(a, op='vlm_pages_r5vc', then='vlm_names_r5vc', page_spec=DECK, how=H_CAPTION + ' Every page is shown.')
    img = POSTER if row['output_id'].startswith('poster') else {'src': 'deliverable'}
    return dict(a, op='vlm_names_r5vc', images=[img])


def l12_type_only(row, ctx):
    if row['output_id'] == 'promoter-deck':
        return {'op': 'vlm_pages_r5vc', 'then': 'vlm_list_r5v', 'page_spec': DECK, 'question': Q_TYPE_ONLY,
                'none_found': 'pass', 'how': H_TYPE_ONLY + ' Every page is shown.'}
    return {'op': 'vlm_list_r5v', 'images': [POSTER], 'question': Q_TYPE_ONLY, 'none_found': 'pass', 'how': H_TYPE_ONLY}


def l12_post_type_only(row, ctx):
    act = unq((row.get('values') or {}).get('1'))
    if not act:
        return None
    q = (f'This post bills the act {act}. Is the name {act} shown anywhere on it as a logo: lettering designed as a '
         'wordmark or badge (for example inside a ring or emblem, in a decorative, stencil, script or distressed style, '
         f'or with a picture mark), rather than plain typeset text? List each such logo of {act}. answer yes if there '
         'is one, no if there is none.')
    return {'op': 'vlm_list_r5v', 'question': q, 'none_found': 'pass',
            'how': f'Asks the vision model whether {act} is shown as a logo or wordmark rather than plain type; it fails '
                   'when both answers find one and passes when both find none.'}


def l12_night_ferry(row, ctx):
    if row['output_id'] == 'promoter-deck':
        return {'op': 'vlm_pages_r5vc', 'then': 'vlm_list_r5v', 'page_spec': DECK, 'question': Q_NIGHT_FERRY,
                'none_found': 'pass', 'how': H_NIGHT_FERRY + ' Every page is shown.'}
    img = POSTER if row['output_id'].startswith('poster') else {'src': 'deliverable'}
    return {'op': 'vlm_list_r5v', 'images': [img], 'question': Q_NIGHT_FERRY, 'none_found': 'pass', 'how': H_NIGHT_FERRY}


def l12_direction(row, ctx):
    return {'op': 'vlm_pages_r5vc', 'then': 'vlm_yesno_r5v', 'page_spec': DECK, 'question': Q_DIRECTION, 'pass_on': 'yes',
            'how': 'Shows the vision model every page and asks whether a page says which poster direction the nine '
                   'release posts adapt; both answers must agree.'}


def l12_stack(row, ctx):
    img = POSTER if row['output_id'].startswith('poster') else {'src': 'deliverable'}
    return {'op': 'vlm_count_r5v', 'images': [img], 'question': Q_STACK, 'expected': [2, 4],
            'how': 'Asks the vision model how many rows the series title is set on; two to four rows (a stack) '
                   'pass, one row or none fails.'}


def l12_sable(row, ctx):
    return {'op': 'vlm_yesno_r5v', 'question': Q_SABLE, 'pass_on': 'yes',
            'images': [{'src': 'asset:umbra_sable_wordmark_transparent.png', 'label': 'Image 1: the supplied wordmark'},
                       {'src': 'deliverable', 'label': 'Image 2: the poster'}],
            'how': 'Shows the vision model the supplied Sable Quartet wordmark and the post and asks whether the post '
                   'shows both that wordmark and the name in plain type; both answers must agree.'}


# ------------------------------------------------------------------ MOTION-11 (STATIC FOX)
Q_TITLE = (
    'Copy the title of this thumbnail: all the large lettering on the coloured band at the top, every row, in order '
    'from top to bottom. Copy it exactly as printed, letter for letter, keeping its spelling and punctuation; put '
    'each row in values as its own string, in order.')
Q_LARGEST = (
    'Which text on this image is set in the largest letters (the tallest capital letters)? Copy that row of text '
    'exactly as printed into values. If several rows share the largest size, copy each of them.')
Q_SPEECH = (
    'List every speech bubble or thought bubble on this image, and every caption that writes out words someone says: '
    'text in quotation marks, or a line given to a speaker (NAME: words). Copy the words of each. Do not list the '
    'title, the channel name, labels, numbers or other game or interface text. answer yes if there is at least one, '
    'no if there is none.')
Q_WEBCAM = (
    'Look for a webcam window: a small inset picture of a real person (the player\'s camera), round or rectangular, '
    'usually near a corner. Is part of that webcam window missing, either covered by something drawn over it (a '
    'cartoon character, a text band, a shape) or running past an edge of the image so that part of its outline and '
    'picture is cut away? answer yes only if part of it is clearly missing. answer no if its whole outline is visible '
    'inside the image with nothing over it, or if there is no webcam window at all.')
Q_END_CARD = (
    'This is the final frame of a video. Is it an end card: a designed closing card made of graphics and text (for '
    'example a channel name or handle, a subscribe line, an upload schedule line or a mascot on a plain ground), '
    'rather than gameplay or camera footage, a black or blank frame, or a frame caught in the middle of a transition? '
    'answer yes if it is an end card, no if it is not.')
Q_HELD_NAME = (
    'These are frames from the last two seconds of a video, where the channel name is held on screen. Look at the '
    'channel name lettering (the large title stack, such as STATIC FOX) in each frame. In any frame, is any letter of '
    'it covered by something placed over it (a character, a shape, a band or other text) or cut off by an edge of the '
    'frame? answer yes if so; answer no if every letter of it is fully visible in every frame.')
Q_SUBTITLE = (
    'These are frames taken every half second through a video, in order. List every subtitle or caption of speech in '
    'any frame: a line that writes out words someone says aloud (dialogue, narration or quoted speech, usually across '
    'the bottom of the frame). Do not list titles, the channel name or handle, slogans, calls to subscribe, upload '
    'schedule lines, member or link lines, or game interface text. Copy each one once. answer yes if there is at least '
    'one, no if there is none.')


def m11_title(row, ctx):
    t = unq((row.get('values') or {}).get('1'))
    if not t:
        return None
    return {'op': 'vlm_join_r5vc', 'question': Q_TITLE, 'expected': t, 'case': 'exact',
            'how': 'Asks the vision model to copy the title row by row exactly as printed; code joins the rows and '
                   'compares them with the upload title letter for letter.'}


def m11_largest(row, ctx):
    name = ctx.outputs[row['output_id']]['name']
    t = name.split(' - ', 1)[1] if ' - ' in name else None
    if not t:
        return None
    return {'op': 'vlm_part_r5vc', 'question': Q_LARGEST, 'expected': t,
            'how': 'Asks the vision model to copy the text set in the largest letters; code checks it is part of the '
                   'upload title (a misspelt word still counts as the title\'s word: spelling is another check).'}


def m11_speech(row, ctx):
    return {'op': 'vlm_list_r5v', 'question': Q_SPEECH, 'none_found': 'pass',
            'how': 'Asks the vision model to list every speech bubble and every caption of spoken words; it fails when '
                   'both answers list one and passes when both find none.'}


def m11_webcam(row, ctx):
    return {'op': 'vlm_yesno_r5v', 'question': Q_WEBCAM, 'pass_on': 'no',
            'how': 'Asks the vision model whether the webcam window is only partly visible, partly covered or partly '
                   'cut off by an edge; both answers must agree.'}


def m11_end_card(row, ctx):
    return {'op': 'vlm_frames_r5vc', 'then': 'vlm_yesno_r5v', 'images': [{'src': 'deliverable', 'from_end': [0]}],
            'question': Q_END_CARD, 'pass_on': 'yes',
            'how': 'Shows the vision model the film\'s last frame and asks whether it is a designed end card rather '
                   'than footage or a blank frame; both answers must agree.'}


def m11_held_name(row, ctx):
    return {'op': 'vlm_frames_r5vc', 'then': 'vlm_yesno_r5v',
            'images': [{'src': 'deliverable', 'from_end': [2.0, 1.0, 0], 'max_side': 1600}],
            'question': Q_HELD_NAME, 'pass_on': 'no',
            'how': 'Shows the vision model frames from the held end card (the last two seconds) and asks whether any '
                   'letter of the channel name is covered or cut off; both answers must agree.'}


def m11_subtitle(row, ctx):
    return {'op': 'vlm_frames_r5vc', 'then': 'vlm_list_r5v',
            'images': [{'src': 'deliverable', 'every': 0.5, 'max_side': 1024}],
            'question': Q_SUBTITLE, 'none_found': 'pass',
            'how': 'Shows the vision model a frame every half second through the film and asks it to list any '
                   'subtitle or caption of speech; it fails when both answers list one and passes when both find none.'}


# ------------------------------------------------------------------ VECTOR-04 (Meridian & Ash stickers)
BAG_OF = {'1': 'meridian_bag_moth.jpg', '2': 'meridian_bag_pourover.jpg', '3': 'meridian_bag_ridgeline.jpg'}
# where each bag photo prints its drawing, as fractions of the photo (the made-file generator's crop boxes, widened)
DRAWING = {'meridian_bag_moth.jpg': [0.25, 0.26, 0.74, 0.71], 'meridian_bag_pourover.jpg': [0.36, 0.11, 0.63, 0.92],
           'meridian_bag_ridgeline.jpg': [0.27, 0.26, 0.71, 0.88], 'meridian_window_mark.jpg': [0.12, 0.10, 0.82, 0.80]}
DARK = '#3A3A3A'


def photo_of(row):
    oid = row['output_id']
    if oid.endswith('window-mark'):
        return 'meridian_window_mark.jpg'
    return BAG_OF.get(oid[-1]) if '-bag-design-' in oid else None


def sticker(row, dark=False):
    """The deliverable as an image: an SVG rendered 1600 px wide, a proof as it is, on a plain ground."""
    k = 'svg_ground' if row['output_id'].startswith(('recovered', 'new')) else 'ground'
    return {'src': 'deliverable', 'label': 'Image 2: the sticker', k: DARK if dark else '#FFFFFF'}


Q_WHICH = (
    'Photos A, B and C each show a coffee bag with a different drawing printed on it. The last image is a sticker. '
    'Which photo\'s printed drawing does the sticker reproduce? Put only that photo\'s letter (A, B or C) in values. '
    'answer cannot_tell if the sticker reproduces none of them.')
PARTS = {'meridian_bag_pourover.jpg': ('a pour-over cone, the carafe beneath it and a rising steam curl',
                                      'the cone, the carafe, the steam curl'),
         'meridian_bag_moth.jpg': ('a moth with four wings, four eye spots (one on each wing), a body and two antennae',
                                  'a wing, an eye spot, the body, an antenna')}
Q_WINDOW_PARTS = (
    'Image 1 is a photo of a sign painted on a cafe window. Image 2 is a sticker made from that sign. The painted sign '
    'has four parts: the arched lettering MERIDIAN & ASH, a filled round disc, a fine thin ring around the disc, and a '
    'leaf inside the disc. List each of these four parts that does not appear in image 2. answer yes if any of them is '
    'missing, no if all four appear.')


THINGS = {   # what each rule names, by the photo the sticker is made from
    'meridian_bag_pourover.jpg': "the bag's kraft paper texture, the outline or edges of the bag, the shadow of the bag's "
                                 'side fold (gusset), or the wooden table',
    'meridian_bag_ridgeline.jpg': "the bag's kraft paper texture, the outline or edges of the bag, the wooden table, the "
                                  'plant, or the bowl',
    'meridian_bag_moth.jpg': "the bag's kraft paper texture, the outline or edges of the bag, the wooden table, the coffee "
                             'scoop, or coffee beans',
    'meridian_window_mark.jpg': 'the glass pane or reflections in it, the window frame, the cafe interior, or the street scene'}


def q_surround(photo):
    what = ('a street photograph of a sign painted on a cafe window' if photo == 'meridian_window_mark.jpg'
            else 'a photograph of a coffee bag on a table, with a drawing printed on the bag')
    made = 'the painted sign' if photo == 'meridian_window_mark.jpg' else 'that printed drawing'
    return (f'Image 1 is {what}. Image 2 is the delivered sticker file made from {made}; everything visible in image 2 '
            'counts, including anything around or behind the sticker shape. Does image 2 show any of these things from '
            f'the photograph: {THINGS[photo]}? A plain flat-coloured backing shape behind the art (the sticker\'s own '
            'die-cut base) does not count. List each of these things you find in image 2. answer yes if you find any, '
            'no if image 2 shows none of them.')


def v04_which(row, ctx):
    return {'op': 'vlm_read_r5v', 'question': Q_WHICH, 'expected': ['B', 'Photo B'], 'case': 'exact',
            'images': [{'src': 'asset:meridian_bag_moth.jpg', 'label': 'Photo A', 'max_side': 1024},
                       {'src': 'asset:meridian_bag_ridgeline.jpg', 'label': 'Photo B', 'max_side': 1024},
                       {'src': 'asset:meridian_bag_pourover.jpg', 'label': 'Photo C', 'max_side': 1024},
                       dict(sticker(row), label='The sticker')],
            'how': 'Shows the vision model the three bag photographs, labelled A to C, and the sticker, and asks which '
                   'photograph\'s drawing the sticker reproduces; code checks the answer names meridian_bag_ridgeline.jpg.'}


def v04_parts(row, ctx):
    photo = photo_of(row)
    if photo not in PARTS:
        return None
    whole, names = PARTS[photo]
    q = (f'Image 1 shows a drawing printed on a coffee bag: {whole}. Image 2 is a sticker made from that drawing. '
         f'Is any of these parts missing from image 2 or cut away in it: {names}? List only missing parts from that '
         'list, by those names (one entry for each missing eye spot, wing or antenna). Small differences in the shape '
         'or detail of a part that is there, and differences of colour, line weight or drawing style, do not count. '
         'answer yes if any listed part is missing, no if all of them are there.')
    return {'op': 'vlm_list_r5v', 'question': q, 'none_found': 'pass',
            'images': [{'src': f'asset:{photo}', 'crop': DRAWING[photo], 'max_side': 1536,
                        'label': 'Image 1: the drawing printed on the bag'}, sticker(row)],
            'how': f'Shows the vision model the drawing printed on {photo} and the sticker and asks it to list any part '
                   'of the drawing missing from the sticker; it fails when both answers list one and passes when both '
                   'find none.'}


def v04_window_parts(row, ctx):
    return {'op': 'vlm_list_r5v', 'question': Q_WINDOW_PARTS, 'none_found': 'pass',
            'images': [{'src': 'asset:meridian_window_mark.jpg', 'crop': DRAWING['meridian_window_mark.jpg'],
                        'max_side': 1536, 'label': 'Image 1: the sign painted on the window'}, sticker(row, dark=True)],
            'how': 'Shows the vision model the painted window sign and the sticker and asks which of its four parts '
                   '(arched lettering, filled roundel, hairline ring, leaf) the sticker lacks; it fails when both '
                   'answers list one and passes when both find none.'}


def v04_surround(row, ctx):
    photo = photo_of(row)
    if not photo:
        return None
    return {'op': 'vlm_list_r5v', 'question': q_surround(photo), 'none_found': 'pass',
            'images': [{'src': f'asset:{photo}', 'max_side': 1024, 'label': 'Image 1: the photograph'}, sticker(row)],
            'how': f'Shows the vision model {photo} and the whole sticker file and asks whether it shows any of the '
                   f'things the rule names from the photo ({THINGS[photo]}); it fails when both answers list one and '
                   'passes when both find none.'}


R5 = {
    # LAYOUT-12
    (L12, 'R029'): l12_direction,
    (L12, 'R032'): l12_sable,
    (L12, 'R045'): l12_type_only,
    (L12, 'R049'): l12_type_only,
    (L12, 'R055'): l12_post_type_only,
    (L12, 'R046'): l12_sponsor,
    (L12, 'R047'): l12_sponsor,
    (L12, 'R050'): l12_sponsor,
    (L12, 'R051'): l12_caption,
    (L12, 'R053'): l12_caption,
    (L12, 'R054'): l12_caption,
    (L12, 'R058'): l12_night_ferry,
    (L12, 'R062'): l12_night_ferry,
    (L12, 'R156'): l12_stack,
    # MOTION-11
    (M11, 'R001'): m11_title,
    (M11, 'R117'): m11_largest,
    (M11, 'R031'): m11_speech,
    (M11, 'R048'): m11_webcam,
    (M11, 'R010'): m11_end_card,
    (M11, 'R023'): m11_held_name,
    (M11, 'R026'): m11_subtitle,
    # VECTOR-04
    (V04, 'R034'): v04_which,
    (V04, 'R037'): v04_which,
    (V04, 'R042'): v04_parts,
    (V04, 'R046'): v04_parts,
    (V04, 'R050'): v04_window_parts,
    (V04, 'R053'): v04_window_parts,
    (V04, 'R113'): v04_surround,
    (V04, 'R114'): v04_surround,
    (V04, 'R116'): v04_surround,
    (V04, 'R117'): v04_surround,
    (V04, 'R118'): v04_surround,
    (V04, 'R120'): v04_surround,
    (V04, 'R121'): v04_surround,
}

HOW = {
    'vlm_frames_r5vc': 'Picks frames by the film\'s own length, then asks the vision model one narrow question about them; both answers must agree.',
    'vlm_pages_r5vc': 'Shows the vision model every page of the PDF and asks one narrow question about them; both answers must agree.',
    'vlm_join_r5vc': 'Asks the vision model to copy the text row by row; code joins the rows and compares them with the expected text.',
    'vlm_part_r5vc': 'Asks the vision model to copy a text; code checks it is part of the expected text.',
    'vlm_names_r5vc': 'Asks the vision model to list captions; it fails only when both answers list one naming a billed act.',
}
