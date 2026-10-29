"""Round 5 (2026-10-29), vision-model checks, helper a: PHOTO-08 (Meridian Motors vehicle cards and campaign) and
PHOTO-10 (Northgrove product pages and launch carousel).

One handler per (task, rule), taking (row, ctx) and returning an assertion for tools/auto_verifier: the harness ops in
ops_r5_vlm.py (names ending _r5v) and three line checks in ops_r5_vlm_a.py (names ending _r5va). Every assertion
carries its own plain sentence in 'how'. Questions never contain the expected text or number: the model reads blind
and code compares. Absence passes ('none_found': 'pass') only for rules whose planted copies showed the model finds
the thing when it is there. One seed of the shared transcription once left out a planted price, so every check that
passes on absence and reads the transcription is paired (v2_all_of) with a second, narrower question that asks only
for that kind of thing; both must find nothing.

Left with people (tried or judged in round 5): PHOTO-08 R097 and R107 (a car cut off on one side of its frame was
missed by one of the two answers on a planted card, and by both with a first wording), R017 (whether the Portland,
Maine line under the enquiry band belongs to the enquiry action is a reading of the layout), R022 (whether the
campaign's CERTIFIED PRE-OWNED INVENTORY line is a claim beyond the intake sheet needs a person), R027 (not tried: no
non-stock vehicle to plant), R033, R034, R036, R039 (a white or silver roofline against a near-white ground is fine
edge detail), R040 and R044 (a white square on the #F6F7F8 ground and the knocked-out rings need exact colour);
PHOTO-10 R035 (which fabric line describes which garment: the model gave the opening page's general subhead to the
Heavyweight Tee with one wording and called the Tee / Raglan page's line unattached with another), R032 (the same
reading, for the loopback styles), R009 (whether Zip Hoodie or Tee counts as the style name is judgement), R014, R088
and R097 (the placed mark's leaf carries a dark sliver; whether it matches the supplied SVG or is a photograph strip is
judgement), R022 (labels such as NORTHGROVE / CAPSULE are neither copy lines nor names), R044, R046, R048 (cut-out
seams and cuffs are fine edges), R085 and R092 (a model can see the RA crest but cannot show it was not redrawn or
recoloured; on carousel page 6 it is about 25 px).
"""
from __future__ import annotations

import re

try:
    from ops_r5_vlm import TRANSCRIBE
except ImportError:   # convert.py builds the public page without tools/auto_verifier on its path
    TRANSCRIBE = ('Copy every piece of text visible in the image, exactly as printed, one entry per line of text, in reading '
                  'order (top to bottom, then left to right). Include headings, small print, labels, numbers, prices, '
                  'lettering in logos and any text on photographs. answer yes if there is any text, no if there is none.')


def _unq(s):
    return str(s).strip().strip('“”"').strip()


# ------------------------------------------------------------------ PHOTO-08, Meridian Motors
P08_ROWS = {   # meridian_intake_week.csv: stock_no -> (year, make_model, trim, mileage, asking_price, cert_tier)
    'M3082': ('2019', 'Norsted Alta', 'SE AWD', 54210, 26900, 'Meridian Certified'),
    'M3091': ('2018', 'Ardmoor Ridge', 'Premium AWD', 61840, 24500, 'Meridian Certified'),
    'M2417': ('2017', 'Calder Vireo', 'SEL', 68400, 23900, 'Meridian Certified Plus'),
    'M3105': ('2020', 'Brookmere Sable', 'Touring', 42980, 31900, 'Meridian Certified Plus'),
    'M2471': ('2017', 'Calder Kestrel', 'SEL Technology Package AWD', 70120, 24900, 'Meridian Certified'),
    'M3119': ('2019', 'Norsted Fjord', 'Adventure AWD', 58760, 29900, 'Meridian Certified'),
}
P08_PHOTOS = [f'{s}_{m.lower().replace(" ", "_")}_{v}.jpg' for s, (_, m, *_r) in P08_ROWS.items()
              for v in ('front34', 'side', 'rear34')]
CARD_STOCK = {f'vehicle-card-r00{i}': s for i, s in zip(range(2, 8), P08_ROWS)}


def _card(row):
    s = CARD_STOCK.get(row['output_id'])
    return (s, P08_ROWS[s]) if s else (None, None)


def _price_forms(n):
    return [f'{n:,}', f'${n:,}', f'$ {n:,}']


Q_PRICE = ('This is a vehicle sales card. Copy the figure of the vehicle\'s asking price exactly as printed (its digits and '
           'commas), as one value, leaving out the currency sign. Copy only the asking price, not the mileage, stock number '
           'or any other figure.')
Q_LARGEST = ('Which text on this card is printed in the largest letters (the tallest characters)? Copy that text exactly as '
             'printed, as one value, leaving out any currency sign.')
Q_CONTACT = ('List every web address, email address and phone number printed anywhere on the image, each copied exactly. '
             'answer yes if there is at least one, no if there is none.')
Q_RULE = ('Look at the large asking price on this card. Directly below the price, before the next line of text, is there '
          'a thin horizontal line (a rule) running under it? answer yes or no.')
Q_STARBURST = ('Does this image contain a starburst graphic: a star or burst shape with many spiky points, of the kind used '
               'as a sale or offer badge? answer yes or no.')
Q_TYPE_ON_PHOTO = ('Is any text (letters or numbers) printed on top of the vehicle photograph, inside its photo frame? Text '
                   'outside the photo frame does not count, and neither do badges or plates that are part of the vehicle '
                   'itself. answer yes or no.')
Q_TYPE_ON_PHOTOS = ('This image shows several vehicle photos, each in a panel above its caption. Is any text (letters or '
                    'numbers) printed on top of any of the vehicle photographs, inside the picture area above a caption? '
                    'Captions, the header and the footer do not count, and neither do badges or plates that are part of a '
                    'vehicle itself. answer yes or no.')
Q_STRUCK = ('Is any price on this image shown slashed or struck through (a price with a line drawn through it or across '
            'it)? answer yes or no.')
Q_TWICE_VEHICLE = ('This image shows several vehicle photos, each in its own panel. Is the same vehicle (the same model in '
                   'the same colour) shown in more than one panel? answer yes or no.')


LONG = {'max_tokens': 6000}   # the listing questions below need room for the model's reasoning
Q_NUMBERS = ('Copy every stock number, model year with its model name, mileage and price printed anywhere on the image, '
             'exactly as printed, one entry each. answer yes if there is any, no if there is none.')
Q_VCLAIMS = ('List every statement printed on this card about the vehicle\'s condition, number of owners, accident or service '
             'history, inspection, warranty or added features, other than its certification tier, trim and mileage, each '
             'copied exactly. answer yes if there is at least one, no if there is none.')
Q_VALUES_CARD = ('Copy every listing value printed on this card: the stock number, the year and model, the trim, the price, '
                 'the mileage and the certification tier, exactly as printed, one entry for each place it is printed (a '
                 'value printed twice is copied twice). Do not copy anything from the enquiry band. answer yes if there is '
                 'any, no if there is none.')
Q_VALUES_CAMPAIGN = ('Copy every listing value printed on this image for every vehicle: its stock number, year and model, '
                     'trim, price, mileage and certification tier, exactly as printed, one entry for each place it is '
                     'printed (a value printed twice is copied twice). answer yes if there is any, no if there is none.')


def _panel_q(year, mm, what):
    return ('Image 1 shows several vehicles, each in its own panel with a caption under its photo. Find the panel whose '
            f'caption names the {year} {mm}. {what} Do not copy text from outside that panel, such as the page header '
            'or footer. If that panel shows none, answer no with no values.')


def p08_price(row, ctx):
    s, r = _card(row)
    if not s:
        return None
    return {'op': 'vlm_read_r5v', 'question': Q_PRICE, 'expected': _price_forms(r[4]),
            'how': 'Asks the vision model to copy the asking price as printed; code checks it is the asking_price in '
                   'meridian_intake_week.csv.'}


def p08_largest(row, ctx):
    s, r = _card(row)
    if not s:
        return None
    return {'op': 'vlm_read_r5v', 'question': Q_LARGEST, 'expected': _price_forms(r[4]),
            'how': 'Asks the vision model to copy the text set in the largest letters; code checks it is the asking price.'}


def p08_caption(row, ctx):
    photos = [row['values'][k] for k in ('1', '2', '3')]
    imgs = [{'src': 'deliverable', 'label': 'Image 1:'}] + [
        {'src': f'asset:{p}', 'label': f'Image {i}:', 'max_side': 768} for i, p in enumerate(photos, 2)]
    return {'op': 'vlm_read_r5v', 'images': imgs, 'expected': [_unq(row['values']['4'])],
            'question': ('Image 1 is a vehicle inventory campaign showing several vehicles, each in its own panel with a '
                         'caption under its photo. Images 2, 3 and 4 are reference photos of one vehicle from three angles. '
                         'Find the vehicle in Image 1 that is this same vehicle (same body shape, details and colour). Copy '
                         'the year and model name printed in the caption under that vehicle\'s photo, exactly as printed, '
                         'without any trim, stock number or other text. If no vehicle in Image 1 is this vehicle, answer no '
                         'with no values.'),
            'how': 'Gives the vision model the campaign and the supplied photos of one vehicle and asks it to copy the '
                   'caption under that vehicle; code checks it is the year and make_model in meridian_intake_week.csv.'}


def p08_panel_stock(row, ctx):
    v = row['values']
    s = _unq(v['3'])
    return {'op': 'vlm_read_r5v', 'case': 'fold', 'none_found': 'pass',
            'expected': [s, f'STOCK {s}', f'STOCK NO. {s}', f'STOCK NO {s}', f'STOCK #{s}'],
            'question': _panel_q(v['1'], v['2'], 'Copy every stock number printed inside that panel, exactly as printed: '
                                                 'only the number itself, without the word STOCK or any other label.'),
            'how': 'Asks the vision model to copy any stock number in the panel captioned with this vehicle; code checks '
                   'it is the stock_no in meridian_intake_week.csv (none shown also passes).'}


def p08_panel_cert(row, ctx):
    v = row['values']
    return {'op': 'vlm_read_r5v', 'case': 'fold', 'none_found': 'pass', 'expected': [_unq(v['3'])],
            'question': _panel_q(v['1'], v['2'], 'Copy every certification tier printed inside that panel (a line naming '
                                                 'the vehicle\'s certification level), exactly as printed.'),
            'how': 'Asks the vision model to copy any certification tier in the panel captioned with this vehicle; code '
                   'checks it is the cert_tier in meridian_intake_week.csv (none shown also passes).'}


def p08_panel_trim(row, ctx):
    v = row['values']
    return {'op': 'vlm_read_r5v', 'case': 'fold', 'none_found': 'pass', 'expected': [_unq(v['3'])],
            'question': _panel_q(v['1'], v['2'], 'Copy the trim printed inside that panel (the trim or version name of '
                                                 'the vehicle, such as a package, drivetrain or grade name printed with or '
                                                 'near the model name), exactly as printed. Do not copy the year and '
                                                 'model name themselves or the stock number.'),
            'how': 'Asks the vision model to copy any trim in the panel captioned with this vehicle; code checks it is the '
                   'trim in meridian_intake_week.csv (none shown also passes).'}


def p08_photo(row, ctx):
    want = row['values']['3']
    imgs = [{'src': 'deliverable', 'label': 'Image 1, the vehicle sales card:'}] + [
        {'src': f'asset:{p}', 'label': f'Reference photo {p}:', 'max_side': 640} for p in P08_PHOTOS]
    return {'op': 'vlm_read_r5v', 'images': imgs, 'expected': [want],
            'question': ('Image 1 is a vehicle sales card with one vehicle photo. The images after it are reference '
                         'photos, each preceded by its file name. Which reference photo was used for the vehicle photo on '
                         'the card: the same vehicle, seen from the same angle? Copy that reference photo\'s file name '
                         'exactly as given. If none of them matches, answer no with no values.'),
            'how': 'Gives the vision model the card and all eighteen supplied vehicle photos by file name and asks which '
                   'one the card\'s photo was taken from; code checks it is the photo in meridian_intake_week.csv.'}


P08_PLACEHOLDER = ['M2290', '2016 Calder Vireo', '71,300', '71300', '22,900', '22900']


def _card_lines(s, r):
    """Every line of a vehicle card already judged to carry no vehicle claim beyond its row of the intake sheet."""
    year, mm, trim, miles, price, cert = r
    e = re.escape
    return ['meridian motors', 'portland, maine', f'stock {e(s.casefold())}', e(f'{year} {mm}'.casefold()), e(trim.casefold()),
            r'\$', e(f'{price:,}'), e(f'${price:,}'), e(f'$ {price:,}'), 'mileage', e(f'{miles:,} miles'), 'certification',
            e(cert.casefold()), f'enquire about {e(s.casefold())}', f'enquire about {e(s.casefold())} meridian motors',
            r'(portland, maine( ·)? )?price excludes tax, title and registration\.?']


P08_CLAIM_DENY = [r'\bone owner\b', r'\bowners?\b', r'\b172\b', r'inspect', r'warrant', r'accident', r'service (history|record)',
                  r'\bclean\b', r'\bmint\b', r'\blike new\b', r'\bnew (tyres|tires|brakes)\b', r'\bfull history\b',
                  r'\bcarfax\b', r'\bnon[- ]smok', r'\bgarage[d]?\b', r'\blow (miles|mileage)\b', r'\bloaded\b']


def p08_claims(row, ctx):
    s, r = _card(row)
    if not s:
        return None
    return {'op': 'v2_all_of', 'checks': [
        {'op': 'vlm_lines_ok_r5va', 'question': TRANSCRIBE, 'allow': _card_lines(s, r), 'deny': P08_CLAIM_DENY},
        {'op': 'vlm_list_r5v', 'question': Q_VCLAIMS, 'none_found': 'pass'}],
        'how': 'Asks the vision model to copy every line of text and, separately, to list any statement about condition, '
               'owners, history, inspection, warranty or features; passes only when every line is one of the row\'s values, '
               'the field labels, the brand and Portland, Maine or the price-terms note and no such statement is listed.'}


def p08_once(row, ctx):
    s, r = _card(row)
    if not s:
        return None
    year, mm, trim, miles, price, cert = r
    e = re.escape
    vals = [rf'\b{e(s.casefold())}\b', e(mm.casefold()), rf'(?<![\w ]){e(trim.casefold())}(?![\w])' if trim == 'SEL'
            else rf'\b{e(trim.casefold())}\b', e(f'{price:,}'), e(f'{miles:,}'),
            rf'{e(cert.casefold())}(?! plus)' if not cert.endswith('Plus') else e(cert.casefold())]
    return {'op': 'v2_all_of', 'checks': [
        {'op': 'vlm_once_r5va', 'question': TRANSCRIBE, 'values': vals, 'exempt': r'^enquire'},
        {'op': 'vlm_once_r5va', 'question': Q_VALUES_CARD, 'values': vals, 'exempt': r'^enquire', 'params': LONG}],
        'how': 'Asks the vision model to copy every line of text and, separately, every listing value once for each place '
               'it is printed; code fails any value (stock number, make and model, trim, price, mileage, certification) '
               'stated twice, leaving out the enquiry line.'}


def p08_once_campaign(row, ctx):
    e = re.escape
    vals = []
    for s, (year, mm, trim, miles, price, cert) in P08_ROWS.items():
        vals += [rf'\b{e(s.casefold())}\b', e(mm.casefold()), e(f'{price:,}'), e(f'{miles:,}')]
    return {'op': 'v2_all_of', 'checks': [
        {'op': 'vlm_once_r5va', 'question': TRANSCRIBE, 'values': vals, 'exempt': r'^enquire'},
        {'op': 'vlm_once_r5va', 'question': Q_VALUES_CAMPAIGN, 'values': vals, 'exempt': r'^enquire', 'params': LONG}],
        'how': 'Asks the vision model to copy every line of text and, separately, every listing value once for each place '
               'it is printed; code fails any vehicle\'s stock number, make and model, price or mileage stated twice.'}


def const(a):
    return lambda row, ctx: dict(a)


# ------------------------------------------------------------------ PHOTO-10, Northgrove
COLOURWAYS = ['Moss', 'Bark', 'Slate', 'Oat', 'Ink', 'Clay', 'Fern']
STORIES = {'Moss': 'a soft grey-green, dyed in small lots.', 'Bark': 'a warm mid brown that wears in.',
           'Slate': 'a quiet blue-grey.', 'Oat': 'an undyed-looking pale neutral.', 'Ink': 'a deep near-black charcoal.',
           'Clay': 'a muted terracotta.', 'Fern': 'a deeper forest green.'}
STORY_COLOURS = ['soft grey-green', 'grey-green', 'warm mid brown', 'mid brown', 'quiet blue-grey', 'blue-grey',
                 'undyed-looking pale neutral', 'pale neutral', 'deep near-black charcoal', 'near-black charcoal',
                 'muted terracotta', 'terracotta', 'deeper forest green', 'forest green']
APPROVED = ['Better than it looks in the price.', 'Six styles. Seven colours. One season.',
            'Loopback cotton, dyed in small lots, made to soften with wear.', 'The capsule is live.',
            'New season. New colours. Northgrove.', 'Made with Rowanfield Athletic.']
STYLE_PHOTO = {'Loopback Crew': 'northgrove_style_01_loopback_crew.jpg', 'Heavyweight Tee': 'northgrove_style_02_heavy_tee.jpg',
               'Raglan': 'northgrove_style_03_raglan.jpg', 'Henley': 'northgrove_style_04_henley.jpg',
               'Hoodie': 'northgrove_style_05_zip_hoodie.jpg', "Supporters' Crew": 'northgrove_style_06_supporters_crew.jpg'}


def _story_forms():
    out = []
    for name, st in STORIES.items():
        bare = st.rstrip('.')
        for body in (st, bare):
            out += [body, f'{name} - {body}', f'{name}: {body}', f'{name}. {body}', f'{name}, {body}', f'{name} {body}']
    return out + APPROVED + [x.rstrip('.') for x in APPROVED]


Q_COLOURS = ('Copy every colour name printed on this page as text: any word or phrase naming the colour, colourway, shade '
             'or tone of a garment (for example a colour word, or a heather or marl label), exactly as printed and keeping '
             'any misspelling, one entry per name. Do not include style names, fabric descriptions, the brand name or other '
             'text, and do not describe the colours seen in the photographs. Answer no with no values if no colour name is '
             'printed.')
Q_CWNAMES = ('Copy every colourway name printed on this page: the name given to a garment\'s colour, usually a short '
             'label of one or two words such as a single colour word, exactly as printed and keeping any misspelling, one '
             'entry per name. Do not include longer lines describing a colour, style names, fabric descriptions or the '
             'brand name, and do not describe the colours seen in the photographs. Answer no with no values if no '
             'colourway name is printed.')
Q_STORY = ('Copy every colourway story printed on this page: a short line of text describing the colour of a garment or '
           'colourway (its shade, its tone or how it is dyed), exactly as printed, one entry per story. Do not include '
           'headlines, style names, fabric weights or care instructions. Answer no with no values if there is none.')
Q_LOGO = ('Copy the lettering of the brand logo on this page (the large wordmark set beside a leaf), exactly as printed, '
          'letter by letter: keep any missing, extra or changed letters and do not correct it. Answer no with no values '
          'if there is no such logo.')
Q_LEAF = ('Look at the brand logo near the top of this page (the large wordmark lettering). Is a leaf shape printed '
          'directly beside the wordmark? answer yes or no.')
Q_METAL = ('Is any type, panel, rule, button, icon or logo on this page given a gold, foil, metallic or glossy effect (for '
           'example a gold colour, a metallic gradient, a shine or a glossy highlight)? Look only at the page design, not '
           'at the clothes in the photographs. answer yes or no.')
Q_RECOLOUR = ('Does this page show the same garment more than once in different colours (for example a second, recoloured '
              'copy of a garment beside the original)? Different garments do not count. answer yes or no.')
Q_HEADLINE_LARGEST = ('Which text on this page is printed in the largest letters, not counting the brand logo (the wordmark '
                      'beside the leaf)? Copy it exactly as printed, as one value; if it runs over several lines, join the '
                      'lines with single spaces.')

SIZE_RUN = 'XS S M L XL XXL'
SIZE_FORMS = [SIZE_RUN, f'{SIZE_RUN}.'] + [f'{p}{SIZE_RUN}{e}' for p in ('Size run ', 'Size run: ', 'Sizes ', 'Sizes: ',
                                                                          'Size: ', 'Sizes available: ') for e in ('', '.')]
Q_PRICES = ('List every price or amount of money printed anywhere on the image (a figure with a currency sign, or with a '
            'currency name or code), each copied exactly. answer yes if there is at least one, no if there is none.')
Q_FIND_CW = ('Is any of these colour words printed anywhere on the image as a word, in any capitals: Moss, Bark, Slate, Oat, '
             'Ink, Clay, Fern? List every line that contains one, copied exactly. answer yes if at least one is printed, '
             'no if none is.')
Q_SIZES = ('Copy every size run printed on this page (a list of garment sizes, such as letter sizes), exactly as printed, '
           'one entry per run, with any label printed before it on the same line. Answer no with no values if there is '
           'none.')
Q_HYPE = ('List every word or phrase printed on this page that calls the product luxury, exclusive or premium, offers a '
          'bargain, sale, deal or discount, or uses a superlative (such as best, finest, softest or most), each copied '
          'exactly. answer yes if there is at least one, no if there is none.')
Q_FABRIC = ('List every fabric description printed on this page (a fibre content, cloth name or fabric weight), each copied '
            'exactly. answer yes if there is at least one, no if there is none.')
BRAND_LINE = ['Better than it looks in the price.', 'Better than it looks in the price', 'better', 'better than', 'price',
              'in the price', 'looks in the price']
PRICE_RX = r'[$£€¥]\s*\d|\d\s*(usd|eur|gbp|cad|dollars?)\b|\b(usd|eur|gbp|cad)\s*\d|\b\d+\.\d{2}\b'
FABRIC_RX = r'\b(cotton|jersey|loopback|fleece|polyester|nylon|wool|linen|elastane|spandex|viscose|modal|terry|gsm)\b|\d\s*%'


def _label_q(style_list):
    n = len(style_list)
    names = ' and '.join(style_list) if n < 3 else ', '.join(style_list[:-1]) + ' and ' + style_list[-1]
    refs = 'Image 2 is a reference photo of one garment' if n == 1 else f'Images 2 to {n + 1} are reference photos of {n} garments'
    return (f'Image 1 is a page of a clothing campaign. {refs}: the {names}. Wherever '
            + ('this garment' if n == 1 else 'any of these garments')
            + ' appears in Image 1 (as a photo, or named by its style name), copy every colour or colourway name printed as '
              'a label for it (beside or under its photo, or together with its style name), exactly as printed. Do not copy '
              'colour names that label other garments, and do not describe the colours seen in the photos. Answer no with '
              'no values if there is none.')


def _label_imgs(style_list):
    return [{'src': 'deliverable', 'label': 'Image 1:'}] + [
        {'src': f'asset:{STYLE_PHOTO[s]}', 'label': f'Image {i}, the {s}:', 'max_side': 768} for i, s in enumerate(style_list, 2)]


def p10_label(styles, allowed, how):
    a = {'question': _label_q(styles), 'images': _label_imgs(styles), 'how': how, 'none_found': 'pass'}
    if allowed is None:
        return const(dict(a, op='vlm_list_r5v'))
    return const(dict(a, op='vlm_read_r5v', case='fold', expected=allowed))


P10_LINES = [   # every line on the Northgrove pages already judged to meet R020 and R080
    'northgrove', 'northgrove / capsule', r'\d{2} / 06', '(northgrove · )?burlington, vermont', 'northgrove · rowanfield athletic',
    "loopback crew|heavyweight tee|raglan|henley|zip hoodie|hoodie|supporters' crew|tee / raglan|henley / hoodie",
    r'80 / 20 loopback cotton, 340 gsm\.?', r'100% combed cotton jersey, 180 gsm\.?', r'wash cold\. (dry flat|line dry)\.?',
    r'180 gsm combed jersey / 340 gsm loopback cotton\.?', r'loopback cotton\.?', r'340 gsm\. made to soften with wear\.?',
    r'six styles\.?', r'seven colours\.?', r'one season\.?', r'six styles\. seven colours\. one season\.?',
    r'loopback cotton, dyed in small lots, made to soften with wear\.?', 'the capsule', r'is live\.?', r'the capsule is live\.?',
    r'better than it looks in the price\.?', r'made with rowanfield athletic\.?', r'size run xs-xxl\.?', 'xs s m l xl xxl', 'ra']
P10_DENY_WORDS = (r'\b(luxury|luxurious|luxe|exclusive|exclusively|premium|prestige|prestigious|elite|opulent|lavish|cheap|'
                  r'cheapest|bargain|sale|discount|discounted|deal|deals|clearance|best|finest|greatest|ultimate|unbeatable|'
                  r'lowest|perfect|softest|warmest|most|world-class|iconic)\b')
P10_DENY_CLAIMS = [PRICE_RX, r'%\s*off\b', r'\bsale\b', r'\bdiscount', r'\bfree\b', r'\bwaterproof\b', r'\borganic\b',
                   r'\brecycled\b', r'\bsustainab', r'\bhand-?made\b', r'\bmade in\b', r'\blimited\b', r'\bexclusive\b',
                   r'\bbest\b', r'\bguarantee', r'\baward', r'\bcertified\b']


R5 = {
    # ---------------- PHOTO-08
    ('PHOTO-08', 'R006'): p08_price,
    ('PHOTO-08', 'R155'): p08_largest,
    ('PHOTO-08', 'R009'): const({'op': 'vlm_text_r5v', 'require': ['Meridian Motors'], 'case': 'fold',
                                 'how': 'Asks the vision model to copy every text on the file; code checks that Meridian '
                                        'Motors is among them.'}),
    ('PHOTO-08', 'R010'): p08_caption,
    ('PHOTO-08', 'R012'): p08_panel_stock,
    ('PHOTO-08', 'R014'): p08_panel_cert,
    ('PHOTO-08', 'R015'): p08_panel_trim,
    ('PHOTO-08', 'R020'): const({'op': 'vlm_list_r5v', 'question': Q_CONTACT, 'none_found': 'pass',
                                 'how': 'Asks the vision model to list every phone number, email address and web address '
                                        'on the file; any found fails.'}),
    ('PHOTO-08', 'R024'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_text_r5v', 'forbid': P08_PLACEHOLDER, 'none_found': 'pass'},
                                     {'op': 'vlm_text_r5v', 'question': Q_NUMBERS, 'forbid': P08_PLACEHOLDER, 'none_found': 'pass',
                                      'params': LONG}],
                                 'how': 'Asks the vision model to copy every text on the file and, separately, every stock '
                                        'number, model, mileage and price; code fails any of last season\'s placeholder '
                                        'values (M2290, 2016 Calder Vireo, 71,300 mi, $22,900).'}),
    ('PHOTO-08', 'R026'): p08_photo,
    ('PHOTO-08', 'R029'): const({'op': 'vlm_yesno_r5v', 'question': Q_TWICE_VEHICLE, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether the same vehicle is shown in more than one panel.'}),
    ('PHOTO-08', 'R099'): const({'op': 'vlm_yesno_r5v', 'question': Q_RULE, 'pass_on': 'yes',
                                 'how': 'Asks the vision model whether a thin horizontal rule sits directly under the '
                                        'asking price.'}),
    ('PHOTO-08', 'R100'): const({'op': 'vlm_yesno_r5v', 'question': Q_STARBURST, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether the file contains a starburst graphic.'}),
    ('PHOTO-08', 'R102'): const({'op': 'vlm_yesno_r5v', 'question': Q_TYPE_ON_PHOTO, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether any text is printed on top of the vehicle '
                                        'photograph.'}),
    ('PHOTO-08', 'R110'): const({'op': 'vlm_yesno_r5v', 'question': Q_TYPE_ON_PHOTOS, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether any text is printed on top of any vehicle '
                                        'photograph.'}),
    ('PHOTO-08', 'R119'): const({'op': 'vlm_yesno_r5v', 'question': Q_STRUCK, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether any price is slashed or struck through.'}),
    ('PHOTO-08', 'R019'): p08_claims,
    ('PHOTO-08', 'R113'): p08_once,
    ('PHOTO-08', 'R114'): p08_once_campaign,

    # ---------------- PHOTO-10
    ('PHOTO-10', 'R004'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_text_r5v', 'select': r'\bXS\b|\bXXL\b', 'expected': SIZE_FORMS,
                                      'case': 'fold', 'none_found': 'pass'},
                                     {'op': 'vlm_read_r5v', 'question': Q_SIZES, 'expected': SIZE_FORMS, 'case': 'fold',
                                      'none_found': 'pass'}],
                                 'how': 'Asks the vision model to copy every text on the file and, separately, every size '
                                        'run; code checks that any size run reads XS S M L XL XXL.'}),
    ('PHOTO-10', 'R027'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_text_r5v', 'select': r'\b(moss|bark|slate|oat|ink|clay|fern)\b',
                                      'expected': [], 'none_found': 'pass'},
                                     {'op': 'vlm_list_r5v', 'question': Q_FIND_CW, 'none_found': 'pass'}],
                                 'how': 'Asks the vision model to copy every text on the file and, separately, to list any '
                                        'line naming a northgrove_colourways.csv colourway (Moss, Bark, Slate, Oat, Ink, '
                                        'Clay or Fern); any found fails.'}),
    ('PHOTO-10', 'R028'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_text_r5v', 'select': PRICE_RX, 'expected': [], 'none_found': 'pass'},
                                     {'op': 'vlm_list_r5v', 'question': Q_PRICES, 'none_found': 'pass'}],
                                 'how': 'Asks the vision model to copy every text on the file and, separately, to list any '
                                        'price; any price found fails.'}),
    ('PHOTO-10', 'R030'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_text_r5v', 'select': PRICE_RX, 'expected': [], 'none_found': 'pass'},
                                     {'op': 'vlm_list_r5v', 'question': Q_PRICES, 'none_found': 'pass'}],
                                 'how': 'Asks the vision model to copy every text on the file and, separately, to list any '
                                        'price; any price found fails.'}),
    ('PHOTO-10', 'R019'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_text_r5v', 'select': FABRIC_RX, 'expected': [], 'none_found': 'pass'},
                                     {'op': 'vlm_list_r5v', 'question': Q_FABRIC, 'none_found': 'pass'}],
                                 'how': 'Asks the vision model to copy every text on the Supporters\' Crew page and, '
                                        'separately, to list any fabric description; any fabric line found fails.'}),
    ('PHOTO-10', 'R001'): const({'op': 'vlm_read_r5v', 'question': Q_CWNAMES, 'expected': ['Oat'], 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colourway name printed on the page; code checks '
                                        'any is Oat.'}),
    ('PHOTO-10', 'R002'): const({'op': 'vlm_read_r5v', 'question': Q_CWNAMES, 'expected': ['Moss', 'Fern'], 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colourway name printed on the page; code checks '
                                        'any is Moss or Fern.'}),
    ('PHOTO-10', 'R006'): const({'op': 'vlm_read_r5v', 'question': Q_CWNAMES, 'expected': COLOURWAYS, 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colourway name printed on the page, keeping any '
                                        'misspelling; code checks each is spelled as in northgrove_colourways.csv.'}),
    ('PHOTO-10', 'R018'): const({'op': 'vlm_read_r5v', 'question': Q_COLOURS, 'expected': [], 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colour name printed on the page; any found '
                                        'fails, since no colourway is approved for this style.'}),
    ('PHOTO-10', 'R025'): lambda row, ctx: {
        'op': 'vlm_read_r5v', 'question': Q_COLOURS, 'case': 'fold', 'none_found': 'pass',
        'expected': (['Oat'] if '01-loopback' in row['output_id'] else ['Moss', 'Fern']) + STORY_COLOURS,
        'how': 'Asks the vision model to copy every colour name printed on the page; code checks each is the style\'s '
               'approved colourway name or a colour word of its northgrove_copy.txt story.'},
    ('PHOTO-10', 'R026'): const({'op': 'vlm_read_r5v', 'question': Q_COLOURS, 'expected': COLOURWAYS + STORY_COLOURS,
                                 'case': 'fold', 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colour name printed on the page; code checks '
                                        'each is a northgrove_colourways.csv colourway or a colour word of its story.'}),
    ('PHOTO-10', 'R008'): const({'op': 'vlm_read_r5v', 'question': Q_STORY, 'expected': _story_forms(), 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colourway story printed on the page; code '
                                        'checks each is word for word a northgrove_copy.txt story line.'}),
    ('PHOTO-10', 'R011'): const({'op': 'vlm_read_r5v', 'question': Q_STORY, 'expected': _story_forms(), 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colourway story printed on the page; code '
                                        'checks each is word for word a northgrove_copy.txt story line.'}),
    ('PHOTO-10', 'R013'): const({'op': 'vlm_read_r5v', 'question': Q_STORY, 'expected': _story_forms(), 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy every colourway story printed on the page; code '
                                        'checks each is word for word a northgrove_copy.txt story line.'}),
    ('PHOTO-10', 'R007'): p10_label(['Loopback Crew'], ['Oat'],
                                    'Gives the vision model the page and the supplied Loopback Crew photo and asks it to copy '
                                    'any colour name labelling that garment; code checks it is Oat.'),
    ('PHOTO-10', 'R015'): p10_label(['Heavyweight Tee'], ['Moss', 'Fern'],
                                    'Gives the vision model the page and the supplied Heavyweight Tee photo and asks it to copy '
                                    'any colour name labelling that garment; code checks it is Moss or Fern.'),
    ('PHOTO-10', 'R031'): p10_label(['Raglan', 'Henley', 'Hoodie', "Supporters' Crew"], None,
                                    'Gives the vision model the page and the supplied photos of the Raglan, Henley, Hoodie and '
                                    'Supporters\' Crew and asks it to list any colour name labelling them; any found fails.'),
    ('PHOTO-10', 'R010'): const({'op': 'vlm_joined_r5va', 'question': TRANSCRIBE, 'require': ['The capsule is live.'],
                                 'how': 'Asks the vision model to copy every text on the page; code joins the lines and '
                                        'checks they contain The capsule is live. word for word.'}),
    ('PHOTO-10', 'R104'): const({'op': 'vlm_read_r5v', 'question': Q_HEADLINE_LARGEST, 'expected': ['The capsule is live.'],
                                 'how': 'Asks the vision model to copy the text set in the largest letters, leaving out the '
                                        'wordmark; code checks it is The capsule is live.'}),
    ('PHOTO-10', 'R089'): const({'op': 'vlm_read_r5v', 'question': Q_LOGO, 'expected': ['NORTHGROVE'], 'case': 'fold',
                                 'none_found': 'pass',
                                 'how': 'Asks the vision model to copy the logo\'s lettering letter by letter; code checks it '
                                        'reads NORTHGROVE with all ten letters.'}),
    ('PHOTO-10', 'R098'): const({'op': 'vlm_read_r5v', 'question': Q_LOGO, 'expected': ['NORTHGROVE'], 'case': 'fold',
                                 'how': 'Asks the vision model to copy the logo\'s lettering letter by letter; code checks it '
                                        'reads NORTHGROVE with all ten letters.'}),
    ('PHOTO-10', 'R095'): const({'op': 'vlm_yesno_r5v', 'question': Q_LEAF, 'pass_on': 'yes',
                                 'how': 'Asks the vision model whether a leaf is printed beside the wordmark.'}),
    ('PHOTO-10', 'R078'): const({'op': 'vlm_yesno_r5v', 'question': Q_METAL, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether any type, panel, rule, icon or logo has a gold, foil, '
                                        'metallic or gloss effect.'}),
    ('PHOTO-10', 'R021'): const({'op': 'vlm_yesno_r5v', 'question': Q_RECOLOUR, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether the same garment is shown more than once in '
                                        'different colours.'}),
    ('PHOTO-10', 'R024'): const({'op': 'vlm_yesno_r5v', 'question': Q_RECOLOUR, 'pass_on': 'no',
                                 'how': 'Asks the vision model whether the same garment is shown more than once in '
                                        'different colours.'}),
    ('PHOTO-10', 'R023'): const({'op': 'vlm_list_r5v', 'none_found': 'pass', 'images': _label_imgs(["Supporters' Crew"]),
                                 'question': ('Image 1 is a page of a clothing campaign. Image 2 is a reference photo of one '
                                              'garment, the Supporters\' Crew. Wherever this garment appears in Image 1 (as '
                                              'a photo, or named by its style name), copy every fabric or cloth description '
                                              'printed for it (a fibre content, a fabric name or a fabric weight), exactly '
                                              'as printed. Do not copy text that describes only other garments. Answer no '
                                              'with no values if there is none.'),
                                 'how': 'Gives the vision model the page and the supplied Supporters\' Crew photo and asks it '
                                        'to list any fabric line given for that garment; any found fails.'}),
    ('PHOTO-10', 'R080'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_lines_ok_r5va', 'question': TRANSCRIBE, 'allow': P10_LINES,
                                      'deny': [P10_DENY_WORDS]},
                                     {'op': 'vlm_read_r5v', 'question': Q_HYPE, 'expected': BRAND_LINE, 'case': 'fold',
                                      'none_found': 'pass'}],
                                 'how': 'Asks the vision model to copy every line of text and, separately, to list any '
                                        'luxury, bargain or superlative wording; passes only when every line is one already '
                                        'judged free of them and nothing but the approved brand line is listed.'}),
    ('PHOTO-10', 'R020'): const({'op': 'v2_all_of', 'checks': [
                                     {'op': 'vlm_lines_ok_r5va', 'question': TRANSCRIBE, 'allow': P10_LINES,
                                      'deny': P10_DENY_CLAIMS},
                                     {'op': 'vlm_list_r5v', 'question': Q_PRICES, 'none_found': 'pass'}],
                                 'how': 'Asks the vision model to copy every line of text and, separately, to list any '
                                        'price; passes only when every line is one already traced to northgrove_copy.txt, '
                                        'northgrove_colourways.csv or Burlington, Vermont and no price is listed.'}),
}

HOW = {
    'vlm_joined_r5va': 'Asks the vision model to copy every text on the file; code joins the lines and checks the required wording is there.',
    'vlm_lines_ok_r5va': 'Asks the vision model to copy every line of text; code passes only lines already judged to meet the rule and fails a forbidden word.',
    'vlm_once_r5va': 'Asks the vision model to copy every line of text; code counts the lines carrying each listing value.',
}
