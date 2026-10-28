"""Step 1: for every v2 rule, decide whether deterministic code can answer it and how. Read-only on the repo.

Statuses: auto (code answers it; if the code cannot find or read what it needs, a person answers that row),
needs_definition (code could answer it once a term the check leaves open is defined), human.
Methods: file (read the PDF/SVG data), ocr (read text from pixels), match (find a supplied image or logo).
"""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2])
IDS = ['PHOTO-04','PHOTO-06','PHOTO-08','PHOTO-10','PHOTO-19','PHOTO-20','PHOTO-24','PHOTO-26','PHOTO-28','LAYOUT-15','LAYOUT-12','VECTOR-04','MOTION-11']
I = re.I

# 1. Never automated: the answer needs judgement, the meaning of words, or a look at what a picture shows.
JUDGEMENT = [
    (r'claim|superlative|hype|luxury|premium|bargain|invents?\b|adds no|states no|honestly|gives a reason|states which|says she|'
     r'is raising|works on|grouped|coordinated|arranged|styled together|follows the poster direction|identif(?:y|ies) a pictured|'
     r'stands for|in place of|in type only|sponsor|partner mark|plain note|not quoted on the same basis|names no one other|'
     r'and no one else|labels a different|beside its own|printed with it|copied word for word from that colourway|'
     r'every line of copy|names a style, colourway|beyond (?:the values|what)', 'meaning of the copy'),
    (r'starburst|struck-through|slashed|speech bubble|quoted caption|speech|voiceover|music|end card|heading line|newly drawn|'
     r'burst|callout|exclamation|guarantee|competitor', 'what the design shows'),
    (r'\bskin\b|\bfaces?\b|\bhair\b|\beyes\b|\bhead\b|sitter(?!\'s name)|retouch|smooth|airbrush|glamou?r|\bcast\b|filter|\bgrade\b|'
     r'glow|halo|fringe|cut[- ]?out|flash|regenerat|repaint|generated|recogni|natural|crushed|texture|scratch|crease|stain|\btear\b|'
     r'dust|restor|damage|blur|sharp|noise|upscal|pixelat|softness|stretched|squashed|distort|\blit\b|lighting|daylight|shadow|'
     r'evenly|water|\bpool\b|\bsky\b|silhouette|grain|\bpaint\b|\bdial\b(?! finish)|strap|grass|corridor tiles|garment|weave|crest|jacket|collar|'
     r'shoulder|curls|roofline|bumper|body panels|webcam|reframe|\bshots?\b|footage|\blooped\b|hides|overlap|opaque|showing through|'
     r'monster|flames|car and|portrait area|left empty|stand-in|grey studio paper|recolou?r|keeps the colour|matches its colour|'
     r'colours? (?:of|from) (?:its|the) (?:supplied|source)|toward|tinted|two palette colours|full colour|handle loop|'
     r'colour behind|small-text shapes|thin rule|rule under|dollar sign|reads (?:deep|pale|sage)|upholstery|lockup|'
     r'halftone|solid filled shapes|shows no hair|same person|indigo wool', 'how a photograph or picture looks'),
    (r'legible|readable|visibly|clearly|noticeably|wide, open|looser|at a glance|without zooming', 'a judgement word ("legible", "visibly")'),
    (r'motif|lettering or motif|glass pane|window frame|arches|curve that spans|\bgaps?\b|stays open|fill in|traced from|'
     r'letters of ASH|hairline ring|enclosed counter|closed up|knocked-out|white square|all ten letters|keeps every part|'
     r'keeps the leaf|keeps its source-photo outline|shows both|shows ada|shows the|photograph shows|person|people|'
     r'appears in exactly one|no vehicle|whole\b|cropped off|clipped|intact|complete,|are complete|is complete|'
     r'narrower than|exactly once|share(?:d)? hairline|stacked as|stack\b(?!.*largest)', 'shapes inside artwork or photos'),
]
JUDGEMENT = [(re.compile(p, I), why) for p, why in JUDGEMENT]

ROLE_WORDS = re.compile(r'\b(?:body(?: text| copy)?|running text|caption(?:s| line)?|fine[- ]print|fine print|secondary heading|'
                        r'standfirst|subhead(?:ing)?s?|main heading|headline|heading|display (?:lines?|lettering)|title line|'
                        r'specification (?:text|lines?)|billing (?:line|text)|table text|chart-label|label|booking (?:action|contact)|'
                        r'enquiry action|registration action|action text|copy|cloth notes|validity line|price, dimension|'
                        r'materials line|care line|dimension line)\b', I)
KNOWN_TEXT = re.compile(r'“[^”]+”|\b(?:act names?|date lines?|door (?:times?|lines?)|support acts?|series title|licence line|'
                        r'accessibility line|house names?|reference names?|product names?|talk titles?|event name|her name|'
                        r'producer name|speaker name|host name|role line|affiliation|session|stock number|year|make and model|'
                        r'trim|mileage|asking price|offer price|style name|colourway names?|timing line|wordmark|numerals?|figures?|'
                        r'rates?|minimum stays?|sleeps figure)\b', I)


def judgement(text):
    text = re.sub(r'“[^”]*”', '“”', text)          # quoted values are data, not the check's own words
    for rx, why in JUDGEMENT:
        if rx.search(text):
            return why
    return None


def decide(r, fmt_of, outlined, assets, palette):
    row0 = r['rows'][0]
    text = row0['check'].replace(row0['deliverable_ref'], '[the deliverable]') if row0.get('deliverable_ref') else row0['check']
    formats = {fmt_of[x['output_id']] for x in r['rows']}
    vector = formats <= {'pdf', 'svg'} and not outlined
    raster = formats & {'png', 'jpg'} or outlined
    video = formats == {'mp4'}
    read = 'file' if vector else 'ocr'
    D = lambda status, method, op, rule, note='': dict(status=status, method=method, op=op, pass_rule=rule, note=note)

    # Image matching: is a supplied logo or photo the one used?
    m = re.search(r'is (?:the supplied [\w ]*?(?:artwork|mark|logo|monogram|wordmark|roundel|frame|photo|drawing)|'
                  r'the [\w_.-]+\.(?:png|svg|jpe?g) (?:artwork|drawing)|(?:meridian|verranza|cfs|northgrove|verda|producer)_[\w.]+\.(?:png|svg|jpe?g)|'
                  r'built (?:on a frame )?from|taken from one of|the supplied mark)|uses? the supplied photo|using the supplied photo|'
                  r'carries the supplied|the headshot on .* is |is built from', text, I)
    if m and not re.search(r'keeps every part|traced from|not from the redrawn', text, I):
        cond = ' If no supplied version is found, a person answers.' if re.match(r'(?:If|Any|Where|Wherever)\b', text) else ''
        how = 'in the video frames of' if 'mp4' in text else 'in'
        return D('auto', 'match', 'image_contains_asset',
                 f'Search {how} the deliverable for the supplied file(s) named in the check. Pass if one is found with the '
                 f'same shape and proportions (not redrawn, retyped or distorted).{cond}')
    if re.search(r'no photograph .* is any of the supplied|appears on no page|no merchandise photo|is placed as an image', text, I):
        return D('auto', 'match', 'image_lacks_asset', 'Search the deliverable for the named supplied file(s). Pass if none is found.')
    if re.search(r'placed at 300 ppi', text, I) and vector:
        return D('auto', 'file+match', 'placed_image_ppi', 'Find the placed headshot in the PDF; pass if its pixel size divided by its printed size is at least 300 ppi.')
    if re.search(r'is the one delivered as', text, I):
        return D('auto', 'match', 'contains_rendered_deliverable', 'Render the named delivered poster and search the deck for it. Pass if found.')

    # Flat colour of type, grounds or marks on an image: code must find the element first, so it comes later.
    colour_words = re.search(r'#[0-9A-Fa-f]{6}', text) or any(re.search(rf'(?<![\w-]){re.escape(n)}(?![\w-])', text) for n in palette)
    photo_look = re.search(r'\bcast\b|tint|recolou?r|toward|\bskin\b|\bfaces?\b|\bhair\b|keeps the colour|matches its colour|'
                           r'reads (?:deep|pale|sage)|natural|glaze|cloth|paint|upholstery|wool', text, I)
    if colour_words and not vector and not photo_look:
        return D('later', '', '', '', 'colour sampled on an image: code must first find the element')
    why = judgement(text)
    if why:
        return D('human', '', '', '', why)

    # Machine facts read from the file
    if vector:
        if re.search(r'declares an explicit viewBox', text, I):
            return D('auto', 'file', 'svg_viewbox', 'Pass if the SVG root element declares a viewBox.')
        if re.search(r'named exactly “CutContour”|layer or group named exactly', text, I):
            return D('auto', 'file', 'cut_layer_named', 'Pass if the cut path sits in a layer or group whose name is exactly CutContour.')
        if re.search(r'exactly one cutting contour|exactly one closed cut path|holds no paths other than|holds the cut path only|'
                     r'cut path only|can be selected on its own|no cut line is drawn into|has no cut line drawn into', text, I):
            return D('auto', 'file', 'cut_layer_structure', 'Read the cut layer and the artwork: pass if the stated count and separation of cut paths hold exactly.')
        if re.search(r'at least \d+ mm in from|at least \d+ mm apart|inside the \d+ mm safe margin|measures \d+ mm on its long edge|'
                     r'at least \d+ mm wide|has a \d+ x \d+ mm trim|reads \d+ x \d+ mm|at least \d+ mm of bare paper', text, I):
            return D('auto', 'file', 'geometry_mm', 'Measure the named element from the file in millimetres; pass if the stated limit holds (0.2 mm tolerance).')
        if re.search(r'sits \d+(?:\.\d+)? mm outside the edge|radius of at least', text, I):
            return D('needs_definition', 'file', 'cut_offset', 'Measure the cut path against the artwork edge.', 'tolerance for "2.5 mm outside" and how to measure a corner radius on a traced path')
        if re.search(r'no blank page', text, I):
            return D('auto', 'file', 'no_blank_page', 'Render every page; pass if no page is a single flat colour with no text, image or shape.')

    # Colour (vector only; colour sampled on pixels comes later)
    if re.search(r'#[0-9A-Fa-f]{6}|\bcolou?rs?\b|opacity|blend mode|scrim|overlay|gradient|metallic|\bgold\b', text, I) or any(
            re.search(rf'(?<![\w-]){re.escape(n)}(?![\w-])', text) for n in palette):
        if not vector:
            return D('later', '', '', '', 'colour sampled on an image: code must first find the element')
        if re.search(r'scrim|overlay|gradient', text, I):
            return D('needs_definition', 'file', 'no_overlay_on_image', 'Pass if no semi-transparent or gradient fill is drawn over a placed photograph.',
                     'whether an opaque shape partly covering a photo counts as an overlay')
        if re.search(r'only as hairline|only for hairline|hairlines, dividers|small labels|metallic|\bgold\b', text, I):
            return D('needs_definition', 'file', 'colour_use_limits', 'Check where the named colours are used.', 'what counts as a hairline, divider or small label, and which colours count as gold or metallic')
        if re.search(r'(?:every|any|all) (?:page )?ground(?:s)? and panel|ground and panel|non-photographic ground|grounds? or panels? is', text, I):
            return D('needs_definition', 'file', 'panel_colours', 'Read the fill colour of every ground and panel.', 'which shapes count as a ground or panel (for example any filled shape over 10% of the page)')
        if re.search(r'opacity|blend mode', text, I):
            return D('auto', 'file+match', 'placed_image_opacity', 'Find the supplied mark in the PDF; pass if it is drawn at 100% opacity with the normal blend mode.')
        if re.search(r'come only from|use only|is one of|one of the six palette|only from', text, I):
            return D('auto', 'file', 'palette_only', 'Read every type, shape and line colour in the file (placed photos excluded). Pass if each is one of the listed hexes.')
        if re.search(r'both appear|appear in the type', text, I):
            return D('auto', 'file', 'colours_present', 'Pass if each listed colour is used by type or a shape (not only inside photos).')
        if re.search(r'cover no more than|covers no more than', text, I):
            return D('auto', 'file', 'colour_area_share', 'Render the file without placed photos; pass if the listed colours together cover no more than the stated share.')
        if re.search(r'main ground of every page', text, I):
            return D('auto', 'file', 'main_ground', 'Render each page without photos; pass if the colour covering the most area is the stated hex.')
        if re.search(r'main ink of', text, I):
            return D('auto', 'file', 'main_ink', 'Render the artwork; pass if the colour covering the most inked area is the stated hex.')
        if re.search(r'sits? on (?:a )?(?:solid )?Pitch|sit on Showroom|on a Pitch', text, I):
            return D('auto', 'file', 'text_ground', 'Find the named text; pass if the shape directly behind it is the stated colour (not a photo).')
        if re.search(r'on Verranza Blue|on Lime Wash|sitting on', text, I):
            return D('auto', 'file', 'text_on_ground_colour', 'For type sitting on the named ground colour, pass if its fill is the stated hex.')
        if re.search(r'wordmark .* inked|monogram .* solid|is solid', text, I) and 'svg' not in formats:
            return D('auto', 'file+match', 'placed_mark_colour', 'Find the placed mark; pass if its inked pixels are the stated hex (R, G, B within 5).')
        if re.search(r'act name|date line|title, support|heading, support|line .* is Bone White|is Sodium|is Bone White', text, I):
            return D('auto', 'file', 'text_colour', 'Find each named line by its text; pass if every letter is filled with the stated hex.')
        if 'svg' in formats and re.search(r'is solid|filled', text, I):
            return D('human', '', '', '', 'which paths make up the named element cannot be told from the file')
        return D('needs_definition', 'file', 'colour', 'Read colours from the file.', 'which elements the check means')

    # Typography read from the PDF / SVG
    if re.search(r'\bset in\b|\bpt\b|capitals|letterspaced|baselines|tabular|lining figures|numeral|cap height|small caps', text, I):
        if not vector:
            if re.search(r'capital', text, I) and re.search(r'every letter of the title', text, I):
                return D('auto', 'ocr', 'ocr_text_case', 'Read the title with OCR; pass if every letter is a capital.')
            return D('human', '', '', '', 'typeface or size on an image: OCR reads words, not fonts')
        role = ROLE_WORDS.search(re.sub(r'“[^”]+”', '', text))
        known = re.search(r'act names?|date lines?|door (?:time|line)|support acts?|series title|licence line|accessibility line|'
                          r'house names?|reference names?|product names?|talk titles?|her name|timing line|numerals?|figures|'
                          r'rate figures|wordmark|“[^”]+”|biography, talk subjects and booking contact|Cormorant Garamond line', text, I)
        if role and not known:
            return D('needs_definition', 'file', 'role_type', 'Find the text of that role and read its font, size or spacing.',
                     f'which text counts as "{role.group(0)}" (for example: paragraphs of two or more lines)')
        if re.search(r'letterspaced more open', text, I):
            return D('auto', 'file', 'tracking_compare', 'Measure the letter spacing of both named lines from the file; pass if the first is wider.')
        if re.search(r'capitals|small caps', text, I):
            return D('auto', 'file', 'text_caps', 'Find each named line by its text; pass if it contains no lowercase letters.')
        if re.search(r'baselines|\d+(?:\.\d+)? ?pt apart', text, I):
            return D('auto', 'file', 'text_leading', 'Measure baseline-to-baseline distance of the named text from the file; pass if within the stated tolerance (0.5 pt if none is stated).')
        if re.search(r'tabular|line up vertically', text, I):
            return D('auto', 'file', 'tabular_figures', 'For figures stacked in a column, pass if each digit position starts at the same x position (0.1 pt).')
        if re.search(r'lining figures|dropping below the baseline', text, I):
            return D('auto', 'file', 'lining_figures', 'Pass if no digit glyph descends below the baseline of its line.')
        if re.search(r'cap height|twice|1\.6 times', text, I):
            return D('auto', 'file', 'glyph_height_ratio', 'Measure the glyph heights from the file; pass if the ratio is within the range in the method note.')
        if re.search(r'numeral', text, I) and re.search(r'no numeral|same size', text, I):
            return D('auto', 'file', 'numeral_font', 'Read the font and size of every digit; pass if the stated rule holds for all of them.')
        if re.search(r'\d+(?:\.\d+)? pt', text, I) and not re.search(r'set in [A-Z]', text):
            return D('auto', 'file', 'text_size', 'Find the named text; pass if its font size is the stated pt (0.1 pt).')
        return D('auto', 'file', 'text_font', 'Find each named line by its text; pass if every letter is set in the stated family and weight.')

    if re.search(r'characters', text, I) and re.search(r'longer than 65|65 characters or fewer|more than 65', text, I):
        role = ROLE_WORDS.search(text)
        return D('needs_definition', read, 'line_length', 'Count characters on each line of the named text.',
                 f'which lines count as "{role.group(0) if role else "the named text"}" (or: count every line except titles)')

    # Layout read from positions and sizes
    if re.search(r'largest text|set (?:larger|smaller) than|is (?:larger|smaller) than|sits? (?:directly |immediately )?(?:above|below)|'
                 r'billed with|sits alone on|on the last row|one or two lines|on one line|follow .* order|same order|same labels|'
                 r'prefixed|is followed by', text, I):
        role = ROLE_WORDS.search(re.sub(r'“[^”]+”', '', text))
        if role and not re.search(r'act name|date line|support act|house name|reference name|product name|her name|series title|'
                                  r'speaker name|host name|role line|producer name|asking price|style name|“', text, I):
            return D('needs_definition', read, 'layout_role', 'Compare sizes or positions of the named text.', f'which text counts as "{role.group(0)}"')
        if video:
            return D('needs_definition', 'ocr', 'video_layout', 'Read frames with OCR.', 'which frame of the video to check')
        how = 'from the file (font size and position)' if vector else 'with OCR (line height and position)'
        return D('auto', read, 'text_layout', f'Find the named texts {how}; pass if the stated order, size relation or line count holds.')

    if re.search(r'fully (?:visible|inside)|sits? fully inside|inside the trim|none of it cut off|no letters? (?:is |are )?cut off|'
                 r'is inside the frame|none clipped|not cropped|no letter of', text, I):
        if re.search(r'every line of type|all on-screen text|all on screen text|booking action|enquiry action|registration action|action text', text, I):
            return D('human', '', '', '', 'which text is meant is not stated exactly, so code cannot find it')
        target = 'the named text' + (' (read with OCR)' if not vector else '')
        return D('auto', read, 'text_inside', f'Find {target}; pass if it is read in full and its box lies inside the page or image.')

    # Text content
    if re.search(r'no (?:registration )?web address|no phone|phone number|email|social handle|follower count|accession code', text, I):
        return D('auto', read, 'text_absent_pattern', 'Read all text; pass if no web address, email, phone number or handle (as named) appears.'
                 + ('' if vector else ' Passes only if OCR reads every text region clearly; otherwise a person answers.'))
    if re.search(r'no price|any price|gives no price|shows no price', text, I):
        return D('auto', read, 'price_rule', 'Find every price (currency sign or amount); pass if each one meets the stated rule.'
                 + ('' if vector else ' Passes only if OCR reads every text region clearly.'))
    if re.search(r'contains no entry|names or offers|does not carry|not the codes?|no other talk|no last-season|“&nbsp;”|no colourway name|'
                 r'no fabric line|not appear', text, I):
        return D('auto', read, 'text_absent', 'Read all text; pass if none of the named words or values appears.'
                 + ('' if vector else ' Passes only if OCR reads every text region clearly.'))
    if re.search(r'reads exactly|reads “|\breads \d|\breads\b.*“|is named in full|spelled|word for word|exactly as written|exactly as in|'
                 r'gives the year|names the place|names [A-Z]|names stock|names Meridian|names Portland|contains “|shows the handle|appears on|'
                 r'appears on screen|appears on “|\bis \$?\d|is [A-Z][\w .&-]+, as|gives [\w ]+? (?:nightly rate|minimum stay)|'
                 r'gives (?:Meridian|Selene)|labels Sep|is through|any year|any weekday|weekday shown|reads \d|is 2026|the date on|'
                 r'door time|set time|matches lunara_notes|is (?:Friday|Oat|Moss)|is Foundations|is the one its reference takes|'
                 r'states? .* \d+ mm', text, I):
        cond = ' If the field is absent, the check passes, as the check says.' if re.match(r'(?:Any|If)\b', text) else ''
        how = 'in the PDF\'s live text' if vector else ('in the video frames with OCR' if video else 'with OCR')
        return D('auto', read, 'text_value', f'Read the text {how}. Pass if it contains the expected value exactly (spacing and line '
                 f'breaks ignored; letter case ignored only where the check says so; any alternative forms the check allows are accepted).{cond}')
    return D('human', '', '', '', 'no exact rule a program could apply')



# Rules read one by one where the general patterns get it wrong.
MATCH_OCR = 'ocr+match'
ND = 'needs_definition'
OVERRIDES = {
    # image matching
    'PHOTO-19/R002': ('auto', 'match', 'asset_inside', 'Find the supplied CFS mark; pass if its whole outline lies inside the image.'),
    'PHOTO-19/R011': ('auto', 'match', 'asset_inside', 'Find the supplied CFS mark; pass if its whole outline lies inside the image. If no mark is found, a person answers.'),
    'PHOTO-19/R024': ('auto', 'match', 'asset_scale', 'Find venue_render.jpg in the image; pass if it is shown at no more than its native 1400 x 933 pixels.'),
    'PHOTO-28/R090': ('auto', 'match', 'asset_shape', 'Find the supplied wordmark; pass if it keeps its one-line proportions (not restacked).'),
    'PHOTO-28/R003': ('auto', MATCH_OCR, 'pictured_then_text', 'Find which instructor photo is used; if it is Priya Anand, pass if the class named is Foundations.'),
    'PHOTO-28/R004': ('auto', MATCH_OCR, 'pictured_then_text', 'Find which instructor photo is used; pass if that instructor is named in full, spelled as in owner_note.txt.'),
    'PHOTO-28/R050': ('auto', MATCH_OCR, 'pictured_then_text', 'If verda_instructor_01.jpg is found, pass if the name beside it is Priya Anand.'),
    'PHOTO-20/R092': ('auto', 'match', 'asset_position', 'Find the supplied AV monogram and the portrait; pass if the monogram sits above or left of the portrait.'),
    'PHOTO-20/R094': ('auto', 'match', 'asset_position', 'If a portrait is placed, find the supplied AV monogram; pass if it sits above or left of the portrait.'),
    'PHOTO-20/R027': ('auto', 'file+match', 'text_below_image', 'Find the portrait and the talk title, event and date; pass if the text sits below the portrait.'),
    'LAYOUT-15/R024': ('auto', 'file+match', 'placed_image_ppi', 'Find the placed headshot in the PDF; pass if its pixel size divided by its printed size is at least 300 ppi.'),
    # needs a definition: the check names a role or links two items without saying how to find them
    'PHOTO-04/R060': (ND, 'file', 'role_type', 'Read the font of body text.', 'which text counts as body text (for example: paragraphs of two or more lines)'),
    'PHOTO-04/R068': (ND, 'file', 'role_type', 'Read the size of body text.', 'which text counts as body text'),
    'PHOTO-04/R069': (ND, 'file', 'role_type', 'Measure the leading of wrapped body text.', 'which text counts as body text'),
    'PHOTO-04/R073': (ND, 'file', 'role_type', 'Read the font of secondary headings and standfirsts.', 'which text counts as a secondary heading or standfirst'),
    'PHOTO-04/R074': (ND, 'file', 'role_type', 'Read the font of rates, captions, sleeps and minimum-stay lines.', 'which text counts as a caption'),
    'PHOTO-04/R054': (ND, 'file', 'role_colour', 'Read the colour of house names and display lines on Lime Wash.', 'which text counts as a display line'),
    'PHOTO-04/R055': (ND, 'file', 'role_colour', 'Read the colour of body text, rates and captions on Lime Wash.', 'which text counts as body text or a caption'),
    'PHOTO-04/R118': ('human', '', '', '', 'the booking-action text is not stated, so code cannot find it'),
    'PHOTO-04/R120': (ND, 'file', 'layout_role', 'Compare secondary headings with house names.', 'which text counts as a secondary heading'),
    'PHOTO-04/R051': ('later', '', '', '', 'colour sampled on an image: code must first find the element'),
    'PHOTO-06/R084': ('human', '', '', '', 'needs the rule (a drawn line) found on the image'),
    'PHOTO-08/R023': (ND, 'ocr', 'disclosure_text', 'Look for a price; if found, look for the disclosure.', 'the exact disclosure wording, or the words it must contain'),
    'PHOTO-08/R157': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as the fine-print disclosure'),
    'PHOTO-08/R160': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as the fine-print disclosure'),
    'PHOTO-08/R161': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as the fine-print disclosure'),
    'PHOTO-08/R095': ('human', '', '', '', 'glyph proportions on an image'),
    'PHOTO-08/R096': ('human', '', '', '', 'glyph proportions on an image'),
    'PHOTO-08/R109': ('human', '', '', '', 'needs the drawn rule found on the image'),
    'PHOTO-08/R116': ('human', '', '', '', 'needs the drawn rule found on the image'),
    'PHOTO-08/R118': ('human', '', '', '', 'needs the drawn rule found on the image'),
    'PHOTO-10/R019': (ND, 'ocr', 'linked_text', 'Find fabric lines and the style they belong to.', 'how a fabric line is tied to its style (for example: the nearest style name)'),
    'PHOTO-10/R023': (ND, 'ocr', 'linked_text', 'Find fabric lines and the style they belong to.', 'how a fabric line is tied to its style'),
    'PHOTO-10/R035': (ND, 'ocr', 'linked_text', 'Find fabric lines and the style they belong to.', 'how a fabric line is tied to its style'),
    'PHOTO-10/R105': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as the headline'),
    'PHOTO-10/R106': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as the headline'),
    'PHOTO-10/R107': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as body text or a cloth note'),
    'PHOTO-19/R071': ('human', '', '', '', 'typeface shapes on an image'),
    'PHOTO-19/R072': ('human', '', '', '', 'typeface shapes on an image'),
    'PHOTO-20/R028': ('human', '', '', '', 'a platform icon is a picture, not text'),
    'PHOTO-20/R079': (ND, 'file', 'role_type', 'Read the font of the biography, talk subjects and booking contact.', 'which text counts as the biography (it is rewritten from vellacourt_bio_copy.txt)'),
    'PHOTO-24/R071': (ND, 'file', 'role_type', 'Read the weight of other Cormorant Garamond lines.', 'which text counts as the main heading'),
    'PHOTO-24/R081': (ND, 'file', 'role_type', 'Read the font of the main heading.', 'which text counts as the main heading'),
    'PHOTO-24/R090': (ND, 'file', 'role_type', 'Read the size of the main heading.', 'which text counts as the main heading'),
    'PHOTO-24/R091': (ND, 'file', 'role_type', 'Measure the leading of the main heading.', 'which text counts as the main heading'),
    'PHOTO-24/R092': (ND, 'file', 'role_type', 'Read the size of body, specification and fine-print text.', 'which text counts as body or fine print'),
    'PHOTO-24/R093': (ND, 'file', 'role_type', 'Measure leading inside text blocks.', 'which text counts as body or fine print'),
    'PHOTO-24/R114': (ND, 'file', 'layout_role', 'Compare sizes.', 'which text counts as the main heading and body text'),
    'PHOTO-26/R001': (ND, 'file', 'role_text', 'Check product-name spelling.', 'which text counts as a product name (for example: text in the product-name style)'),
    'PHOTO-26/R006': (ND, 'file', 'role_text', 'Check product-name spelling.', 'which text counts as a product name'),
    'PHOTO-26/R016': (ND, 'file', 'linked_text', 'Check care lines.', 'how a care line is tied to its product'),
    'PHOTO-26/R017': (ND, 'file', 'linked_text', 'Check care lines.', 'how a care line is tied to its product'),
    'PHOTO-26/R019': (ND, 'file', 'linked_text', 'Check prices.', 'how a price is tied to its product'),
    'PHOTO-26/R037': (ND, 'file', 'role_type', 'Check the running foot.', 'which text counts as the running foot'),
    'PHOTO-26/R039': (ND, 'file', 'role_type', 'Read the font of product names and main headings.', 'which text counts as a main heading'),
    'PHOTO-26/R040': (ND, 'file', 'role_type', 'Read the font of body text.', 'which text counts as body text'),
    'PHOTO-26/R044': (ND, 'file', 'role_type', 'Read the font of product names, headings and brand name.', 'which text counts as a main heading'),
    'PHOTO-26/R045': (ND, 'file', 'role_type', 'Read sizes.', 'which text counts as a main heading'),
    'PHOTO-26/R046': (ND, 'file', 'role_type', 'Read the font of subheadings.', 'which text counts as a subheading'),
    'PHOTO-26/R047': (ND, 'file', 'role_type', 'Read the size of subheadings.', 'which text counts as a subheading'),
    'PHOTO-26/R048': (ND, 'file', 'role_type', 'Read the size of body text.', 'which text counts as body text'),
    'PHOTO-26/R050': (ND, 'file', 'role_type', 'Read sizes.', 'which text counts as a main heading'),
    'PHOTO-26/R053': (ND, 'file', 'role_type', 'Check capitals.', 'which text counts as a main heading'),
    'PHOTO-26/R054': (ND, 'file', 'role_type', 'Check capitals.', 'which text counts as a subheading'),
    'PHOTO-26/R065': ('human', '', '', '', 'how a photograph looks'),
    'PHOTO-28/R092': ('human', '', '', '', 'whether the wordmark forms its own lockup'),
    'PHOTO-28/R095': (ND, MATCH_OCR, 'layout_role', 'Compare positions.', 'which text counts as the headline'),
    'PHOTO-28/R104': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as the headline'),
    'PHOTO-28/R105': (ND, 'ocr', 'layout_role', 'Compare text heights.', 'which text counts as the headline'),
    'PHOTO-28/R106': (ND, 'ocr', 'layout_role', 'Find the largest text.', 'the launch headline wording'),
    'PHOTO-28/R089': ('human', '', '', '', 'how a photograph looks'),
    'LAYOUT-12/R116': (ND, 'file', 'role_type', 'Read the font of support acts and billing lines.', 'which text counts as a billing line'),
    'LAYOUT-12/R119': (ND, 'file', 'role_type', 'Read the font of body, billing and table text.', 'which text counts as body, billing or table text'),
    'LAYOUT-12/R159': (ND, 'file', 'tracking_compare', 'Compare letter spacing.', 'which text counts as body text'),
    'VECTOR-04/R093': (ND, 'file', 'role_type', 'Measure leading of body copy.', 'which text counts as body copy'),
    'VECTOR-04/R094': (ND, 'file', 'role_type', 'Measure leading of a title line.', 'which text counts as a flat title line'),
    'VECTOR-04/R096': (ND, 'file', 'role_type', 'Measure leading of display lettering.', 'which text counts as display lettering'),
}

OVERRIDES.update({
    'PHOTO-20/R061': ('auto', 'file', 'main_ground', 'Render each page without photos; pass if the colour covering the most area is Warm Neutral #E8E1D6.'),
    'PHOTO-20/R062': ('auto', 'file', 'text_on_ground_colour', 'Find her name and the talk title; where they sit on Warm Neutral or Bone, pass if they are Vellacourt Ink #262524.'),
    'PHOTO-20/R063': ('auto', 'file', 'text_on_ground_colour', 'For all type on Deep Ground or Vellacourt Ink (the monogram aside), pass if it is Warm Neutral #E8E1D6 or Bone #F4EFE7.'),
    'PHOTO-20/R065': (ND, 'file', 'role_colour', 'Read the colour of her name, talk titles and running text on light grounds.', 'which text counts as running text'),
    'PHOTO-20/R066': (ND, 'file', 'panel_colours', 'Read the fill colour of every panel.', 'which shapes count as a panel'),
    'PHOTO-20/R069': ('auto', 'file', 'text_on_ground_colour', 'Find the event name and date; where they sit on Warm Neutral or Bone, pass if they are #262524 or #4C5560.'),
    'PHOTO-24/R058': ('auto', 'file', 'text_on_image_colour', 'For any type drawn over a placed photograph, pass if it is #EDE6D6 or #191512.'),
    'PHOTO-26/R025': (ND, 'file', 'band', 'Find the coloured band.', 'which shape counts as the band'),
    'PHOTO-26/R027': ('auto', 'file', 'main_ground', 'Render each page without photos; pass if the colour covering the most area is Warm Paper Ground #F6F1E8.'),
    'PHOTO-26/R029': (ND, 'file', 'panel_colours', 'Read the fill colour of grounds, tiles, panels and bands.', 'which shapes count as a ground, tile, panel or band'),
    'PHOTO-26/R030': (ND, 'file', 'role_colour', 'Find Soft Clay type.', 'which text counts as the running foot'),
    'PHOTO-26/R032': ('auto', 'file', 'text_on_ground_colour', 'For type on Warm Paper Ground, Oatmeal Glaze or Soft Clay that is not itself Soft Clay, pass if it is Stoneware Charcoal #3B3733.'),
    'PHOTO-26/R033': ('auto', 'file', 'text_on_ground_colour', 'For type on Indigo Dye #33455E, pass if it is Warm Paper Ground #F6F1E8.'),
    'PHOTO-26/R034': ('auto', 'file', 'colour_area_share', 'Render each page without photos; pass if Warm Paper Ground covers more area than Oatmeal Glaze, Soft Clay and Indigo Dye combined.'),
    'PHOTO-26/R036': (ND, 'file', 'band', 'Compare the band colour across pages.', 'which shape counts as the band'),
    'PHOTO-26/R068': ('human', '', '', '', 'how a photograph looks'),
    'PHOTO-26/R042': ('auto', 'file', 'text_font', 'Find each price, dimension and care line by its wording in thornmere_autumn_skus.csv; pass if it is set in Inter Regular.'),
    'PHOTO-26/R049': ('auto', 'file', 'text_size', 'Find each price, dimension and care line by its wording in thornmere_autumn_skus.csv; pass if it is 8.5 pt (0.1 pt).'),
    'PHOTO-26/R051': ('auto', 'file', 'text_size', 'Find each price, dimension and care line by its wording in thornmere_autumn_skus.csv; pass if it is 8.5 pt (0.1 pt).'),
    'VECTOR-04/R070': (ND, 'file', 'text_on_ground_colour', 'Read the colour of type on light grounds.', 'which grounds count as light, and whether the SVG keeps its type as text'),
    'VECTOR-04/R071': ('human', '', '', '', 'what counts as fine detail versus a main shape'),
    'VECTOR-04/R081': ('human', '', '', '', 'which paths are type cannot be told once lettering is outlined'),
    'LAYOUT-15/R047': ('auto', 'ocr', 'line_length', 'Find the license and office lines by their wording in producer_roster_northern.csv; pass if every printed line of them has 65 characters or fewer.'),
    'MOTION-11/R084': ('human', '', '', '', 'OCR cannot tell which text is set in Inter'),
    'MOTION-11/R097': ('human', '', '', '', 'OCR cannot tell which text is set in Inter'),
})

OVERRIDES.update({
    'PHOTO-20/R039': ('auto', 'file', 'text_absent_pattern', 'Read the booking contact in the PDF; pass if it contains no email address, phone number or web address.'),
    'PHOTO-28/R038': ('auto', 'ocr', 'text_absent_pattern', 'Read all text with OCR; pass if any web address, phone number or handle is a supplied verdastudio.example address. Passes only if OCR reads every text region clearly.'),
    'PHOTO-28/R042': ('auto', 'ocr', 'text_absent_pattern', 'Read the booking action with OCR; pass if any contact in it is a supplied verdastudio.example address. Passes only if OCR reads every text region clearly.'),
    'LAYOUT-15/R052': ('auto', 'ocr', 'ocr_text_case', 'Read the producer name with OCR; pass if it reads Raymond Hollis in sentence case, not all capitals.'),
    'LAYOUT-12/R024': ('auto', 'file+match', 'mark_with_text', 'Find the supplied Sable Quartet wordmark and the typeset act name SABLE QUARTET; pass if both are present.'),
    'LAYOUT-12/R025': ('auto', 'file+match', 'mark_with_text', 'Find the supplied Meridian Brass wordmark and the typeset act name MERIDIAN BRASS; pass if both are present.'),
    'LAYOUT-12/R032': ('auto', MATCH_OCR, 'mark_with_text', 'Find the supplied Sable Quartet wordmark and the typeset act name (OCR); pass if both are present.'),
    'LAYOUT-12/R033': ('auto', MATCH_OCR, 'mark_with_text', 'Find the supplied Meridian Brass wordmark and the typeset act name (OCR); pass if both are present.'),
    'MOTION-11/R004': ('auto', 'ocr', 'text_value', 'Read the end-card frames with OCR; pass if the members line appears word for word.'),
    'MOTION-11/R035': ('auto', 'match', 'image_contains_asset', 'Search the video frames for the supplied staticfox_scrap_transparent.png; pass if every appearance of Scrap matches it.'),
    'MOTION-11/R119': ('auto', 'ocr', 'text_layout', 'Read the last held frame with OCR; pass if STATIC FOX is the tallest text.'),
    'PHOTO-24/R094': ('auto', 'ocr', 'text_layout', 'Read the wordmark with OCR; pass if LUNARA sits on a line above CHRONOMETRY.'),
    'PHOTO-08/R043': ('auto', 'match', 'asset_shape', 'Find the supplied roundel; pass if it keeps its own proportions (width to height within 2%). If none is found, the check passes, as the check says.'),
    'PHOTO-19/R026': ('auto', 'match', 'asset_shape', 'Find venue_render.jpg; pass if it keeps its own proportions (within 2%). If it is not used, the check passes.'),
    'PHOTO-10/R008': (ND, 'ocr', 'linked_text', 'Check colourway stories.', 'how a story is tied to its colourway'),
    'PHOTO-10/R011': (ND, 'ocr', 'linked_text', 'Check colourway stories.', 'how a story is tied to its colourway'),
})

OVERRIDES.update({
    'PHOTO-20/R040': ('auto', 'file', 'text_absent', 'Read the PDF text; pass if no other talk title from vellacourt_talks.csv, and no template sample text, appears.'),
    'PHOTO-20/R033': ('auto', 'file', 'text_absent', 'Read the PDF text; pass if no other talk title from vellacourt_talks.csv, and no template sample text, appears.'),
    'PHOTO-10/R031': (ND, 'ocr', 'linked_text', 'Find colourway names and the style they label.', 'how a colourway name is tied to the style it labels'),
    'PHOTO-10/R032': (ND, 'ocr', 'linked_text', 'Find fabric lines and the style they belong to.', 'how a fabric line is tied to its style'),
})

rows_out = []
for tid in IDS:
    spec = json.loads((ROOT/'docs/gatsby-v7/tasks'/tid/'TASK_SPEC.json').read_text())
    fmt_of = {o['output_id']: o['spec']['format'] for o in spec['deliverables']}
    outl = {o['output_id'] for o in spec['deliverables'] if re.search(r'(?i)outlin', json.dumps(o.get('commission', {})))}
    assets = {a['filename'] for a in json.loads((ROOT/'docs/gatsby-v7/tasks'/tid/'ASSET_MANIFEST.json').read_text())}
    palette = [c['name'] for c in spec['brand_identity']['palette']]
    for r in json.loads((ROOT/'docs/gatsby-v7/annotation-pilot-v2/groups'/f'{tid}.json').read_text())['rules']:
        outlined = any(x['output_id'] in outl for x in r['rows'])
        d = OVERRIDES.get(f"{tid}/{r['rule_id']}") or decide(r, fmt_of, outlined, assets, palette)
        if isinstance(d, tuple):
            d = dict(zip(('status', 'method', 'op', 'pass_rule', 'note'), d + ('',) * (5 - len(d))))
        rows_out.append(dict(task=tid, rule=r['rule_id'], k=r['k_id'], critical=r['critical'], checks=len(r['rows']),
                             formats=sorted({fmt_of[x['output_id']] for x in r['rows']}), outlined=outlined,
                             text=r['rows'][0]['check'], **d))
json.dump(rows_out, open(OUT, 'w'), ensure_ascii=False, indent=1)
tot = defaultdict(Counter)
for r in rows_out:
    key = r['status'] + (f":{r['method']}" if r['status'] == 'auto' else '')
    tot[key]['rules'] += 1; tot[key]['checks'] += r['checks']
for k in sorted(tot):
    print(f"{k:22s} rules {tot[k]['rules']:5d}  checks {tot[k]['checks']:5d}")
