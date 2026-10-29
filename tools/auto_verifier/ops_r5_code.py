"""Round 5 (2026-10-29): close calls settled by code. Each op here takes a rule whose earlier code already decided
some rows with no wrong answer and removes one exact reason rows came back to a person; everything else is left as it
was (several ops run the earlier check unchanged and only add one decision it could not make). Op names end _r5c;
every limit is a setting named in the op's docstring, with its pass, fail and person bands. Same contract as
objective_ops: (status, evidence), status pass, fail or person; nothing passes on a failed or partial read.

Ops: v2_keyline_only_r5c (a colour used outside the photograph only as a hairline keyline round it),
v2_ground_absent_r5c (type on a ground that the image does not contain at all), v2_cap_ratio_r5c (opening capital
against a later capital, with the dot of an i or j joined to its letter), v2_named_colour_r5c (a text line inked in
another named palette colour exactly), and the ops added further down (see OPS at the end).
"""
from __future__ import annotations

OPS: dict = {}

import re
from pathlib import Path

import numpy as np

import objective_ops as base
import objective_ops_r3 as r3
import ops_r4_type as t4
from objective_ops import PERSON, OCR_GOOD_CONF

IMAGES = ('.png', '.jpg', '.jpeg')


def _sub(a, spec):
    """A wrapped assertion, carrying the run's private settings (_asset_dirs, _artifacts)."""
    return dict(spec, **{k: v for k, v in a.items() if k.startswith('_')})


# ---------------------------------------------------------------- a colour used only as a keyline round the photo


def _photo_rect(path: Path, a, name):
    """The supplied photo's rectangle in the image, from the SIFT homography's corners (axis-aligned placements only).
    Returns ((x0, y0, x1, y1), None) or (None, reason)."""
    try:
        asset = base._load_gray(base.asset_path(a, name))
    except FileNotFoundError:
        return None, f'supplied photo {name} not available'
    scene = base._scenes(path)[0]
    n, corners, state = base.find_asset(scene, asset)
    if state != 'found':
        return None, f'supplied photo {name} not found'
    c = np.asarray(corners, float)
    # corners: top-left, top-right, bottom-right, bottom-left; a placement with rotation or perspective is not read here
    if max(abs(c[0, 1] - c[1, 1]), abs(c[3, 1] - c[2, 1]), abs(c[0, 0] - c[3, 0]), abs(c[1, 0] - c[2, 0])) > 2.0:
        return None, 'the photo is not placed square to the page'
    rect = (float(c[:, 0].min()), float(c[:, 1].min()), float(c[:, 0].max()), float(c[:, 1].max()))
    # the whole file must show up to each edge (a cropped placement projects past what is shown): along each side, a
    # band 3 to 10 px inside the edge correlates with the supplied file laid over the image (a tone change keeps it)
    import ops_r3_photo_b as pb
    got = pb._warped(str(path), name, tuple(a.get('_asset_dirs') or []))
    if got is None:
        return None, f'supplied photo {name} not found'
    warped, valid = got
    rgb = r3._pixels(str(path))
    gray = rgb @ np.array([0.299, 0.587, 0.114])
    wgray = warped.astype(float) @ np.array([0.299, 0.587, 0.114])
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    lo, hi = a.get('band_in', (3, 10))
    bands = {'top': (slice(y0 + lo, y0 + hi), slice(x0 + hi, x1 - hi)), 'bottom': (slice(y1 - hi, y1 - lo), slice(x0 + hi, x1 - hi)),
             'left': (slice(y0 + hi, y1 - hi), slice(x0 + lo, x0 + hi)), 'right': (slice(y0 + hi, y1 - hi), slice(x1 - hi, x1 - lo))}
    for side, sl in bands.items():
        g, s, v = gray[sl], wgray[sl], valid[sl]
        if g.size < 50 or v.mean() < 0.99:
            return None, f'the photo is not shown whole ({side} edge)'
        g, s = g - g.mean(), s - s.mean()
        den = float(np.sqrt((g * g).sum() * (s * s).sum()))
        if den < 1e-6 or float((g * s).sum()) / den < a.get('edge_ncc', 0.5):
            return None, f'the photo does not clearly reach its {side} edge'
    return rect, None


def op_keyline_only_r5c(path, a):
    """Outside the supplied photograph, the colour appears only as a hairline keyline round it.

    Settings: hexes (the colour); photo (the supplied photograph; it is found with SIFT and its rectangle taken from
    the homography's corners; not found, not placed square, or not shown whole goes to a person: along every side a
    band 3 to 10 px inside the edge (band_in) must correlate edge_ncc, 0.5, or more with the supplied file laid over
    the image, so a cropped placement is never taken for the whole file); tol (a pixel within 5 per channel of
    the colour counts, 8 on JPEG); thin_px (0.4% of the image's short side, at least 3 px: the round-3 hairline);
    inset (2 px: pixels further inside the photo rectangle are the photograph's own and are not a use of the colour);
    edge_px (thin_px: a pixel of the colour within this distance outside the rectangle's edge is keyline);
    near_px (3 x edge_px); min_piece (12) and fail_piece (30 px). Pixels inside other photograph-like (textured)
    areas are left out, as in every round-3 colour read.
    Pass: every piece of the colour outside the photograph lies along its edge (within edge_px), and on each side
    the keyline is no thicker than thin_px; or the colour does not appear outside the photograph at all.
    Fail: a piece of fail_piece pixels or more lies away from the photograph (further than near_px from its edge),
    or a side's keyline is thicker than 2 x thin_px. Person: a smaller piece (min_piece or more), a piece just beside
    the edge (between edge_px and near_px, which a misplaced rectangle could explain), or a keyline between thin_px and
    2 x thin_px thick. Specks under min_piece pixels (JPEG blends at letter edges) decide nothing."""
    import cv2
    path = Path(path)
    if path.suffix.lower() not in IMAGES:
        return PERSON, {'reason': 'read on images only'}
    rect, why = _photo_rect(path, a, a['photo'])
    if rect is None:
        return PERSON, {'reason': why}
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    tol = r3._tol(path, a)
    thin = a.get('thin_px', max(3, round(0.004 * min(h, w))))
    inset, edge = a.get('inset', 2), a.get('edge_px', thin)
    near_px = a.get('near_px', 3 * edge)
    hit = r3._near_mask(rgb, a['hexes'], tol)
    x0, y0, x1, y1 = rect
    yy, xx = np.mgrid[0:h, 0:w]
    # signed distance outside the rectangle (0 inside it): how far a pixel lies beyond the photo's edge
    dx = np.maximum(np.maximum(x0 - xx, xx - (x1 - 1)), 0)
    dy = np.maximum(np.maximum(y0 - yy, yy - (y1 - 1)), 0)
    beyond = np.maximum(dx, dy)
    inner = (xx >= x0 + inset) & (xx <= x1 - 1 - inset) & (yy >= y0 + inset) & (yy <= y1 - 1 - inset)
    use = hit & ~inner                                  # the colour outside the photograph's own pixels
    key = use & (beyond <= edge)
    # pixels inside any other photograph-like area (objective_ops_r3._photo_mask: textured blocks) are not a use either
    other = use & (beyond > edge) & ~r3._photo_mask(path, {'photos': [], '_asset_dirs': a.get('_asset_dirs')})
    ev = {'photo_rect': [round(v, 1) for v in rect], 'keyline_px': int(key.sum())}
    bad, unsure = [], []
    n, labels, stats, _ = cv2.connectedComponentsWithStats(other.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area < a.get('min_piece', 12):
            continue
        far = int(beyond[labels == i].min()) > near_px
        item = {'box': [x, y, bw, bh], 'px': area}
        if far and area >= a.get('fail_piece', 30):
            bad.append(item)
        else:
            unsure.append(dict(item, reason='beside the photo edge' if not far else 'a small piece'))
    # keyline thickness on each side, from the pixels outside the rectangle only (the photo's own edge is left out)
    out_key = key & (beyond > 0)
    sides = {'top': (out_key & (yy < y0)).sum() / max(1.0, x1 - x0),
             'bottom': (out_key & (yy > y1 - 1)).sum() / max(1.0, x1 - x0),
             'left': (out_key & (xx < x0)).sum() / max(1.0, y1 - y0),
             'right': (out_key & (xx > x1 - 1)).sum() / max(1.0, y1 - y0)}
    ev['keyline_thickness'] = {k: round(float(v), 2) for k, v in sides.items()}
    thick = max(sides.values())
    if bad:
        return 'fail', dict(ev, used_elsewhere=bad[:4])
    if thick > 2 * thin:
        return 'fail', dict(ev, reason=f'the line round the photo is {thick:.1f} px thick, not a hairline')
    if unsure:
        return PERSON, dict(ev, reason='pieces of the colour whose use is unclear', pieces=unsure[:4])
    if thick > thin:
        return PERSON, dict(ev, reason='the line round the photo is close to the hairline limit')
    return 'pass', ev


# ---------------------------------------------------------------- type on a ground the image does not contain


def op_ground_absent_r5c(path, a):
    """Type on a named ground (a rule that applies only where that ground appears). Images: where no pixel of the
    image comes within absent_tol (12 per channel) of any of grounds, the image has no such ground, so no type sits
    on one: a pass (every pixel is read; nothing depends on OCR). Otherwise, and for PDFs, the earlier check in
    `then` answers unchanged."""
    path = Path(path)
    if path.suffix.lower() in IMAGES:
        rgb = r3._pixels(str(path))
        near = r3._near_mask(rgb, a['grounds'], a.get('absent_tol', 12))
        if not near.any():
            return 'pass', {'reason': 'no pixel of the image is in or near the ground colour, so no type sits on it',
                            'grounds': a['grounds']}
    st, ev = base.run(path, _sub(a, a['then']))
    return st, ev


# ---------------------------------------------------------------- opening capital against a later capital


def _stack_merge(comps, overlap=0.5):
    """Ink pieces one above the other (the dot of an i or j over its stem) joined into one letter: pieces whose
    horizontal ranges overlap by more than `overlap` of the narrower one and whose vertical ranges do not overlap."""
    merged = []
    for c in sorted(comps, key=lambda c: (c[0], c[1])):
        for i, m in enumerate(merged):
            ov = min(c[2], m[2]) - max(c[0], m[0])
            vov = min(c[3], m[3]) - max(c[1], m[1])
            if ov > overlap * min(c[2] - c[0], m[2] - m[0]) and vov <= 0:
                merged[i] = (min(c[0], m[0]), min(c[1], m[1]), max(c[2], m[2]), max(c[3], m[3]), c[4] + m[4])
                break
        else:
            merged.append(c)
    return sorted(merged, key=lambda c: c[0])


def op_cap_ratio_r5c(path, a):
    """The first letter of a line stands `ratio` times as tall as the first letter of a later word (as
    v2_cap_ratio_r4t, which sent a line with an i or j to a person because the letter's dot is a separate ink piece).

    Settings: line (the line's exact text, read by OCR at min_conf 80 or more, once), word (index of the later word,
    1 = the second word), ratio (2.0), pass_tol (0.15), fail_tol (0.4): a measured height ratio within pass_tol of
    ratio passes, fail_tol or more away fails, in between a person decides. Letters are the ink pieces inside the OCR
    box on a flat ground (ground_tol 12, ink_tol 60, as round 4), with pieces stacked one above the other joined into
    one letter (stack_overlap 0.5: horizontal overlap over the narrower piece, and no vertical overlap). Each word
    must then split into exactly as many pieces as it has letters, else a person decides."""
    path = Path(path)
    if path.suffix.lower() not in t4.PA_IMAGES:
        return PERSON, {'reason': 'read on images only'}
    gray = t4.pa_gray(str(path))
    layer = base.ocr_layer_cached(str(path))
    want = a['line']
    lines = [l for l in layer.lines if base.canon(l.text, False) == base.canon(want, False) and l.conf >= a.get('min_conf', 80)]
    if len(lines) != 1:
        return PERSON, {'reason': f'line {want} not read once confidently ({len(lines)} found)'}
    x0, y0, x1, y1 = lines[0].bbox
    hh = y1 - y0
    box = (x0 - 0.6 * hh, y0 - 0.6 * hh, x1 + 0.3 * hh, y1 + 0.4 * hh)
    if not t4.pa_ring_flat(gray, box, a.get('ground_tol', 12)):
        return PERSON, {'reason': 'the line does not sit on a flat ground'}
    comps, _ = t4.pa_comps(gray, box, a.get('ink_tol', 60))
    comps = _stack_merge(comps, a.get('stack_overlap', 0.5))
    words = want.split()
    nletters = [len(re.sub(r'[^A-Za-z]', '', w)) for w in words]
    if len(comps) != sum(nletters):
        return PERSON, {'reason': f'{len(comps)} letter shapes for {sum(nletters)} letters (touching or broken letters)'}
    first = comps[0]
    other = comps[sum(nletters[:a.get('word', 1)])]
    r = (first[3] - first[1]) / max(1, other[3] - other[1])
    ev = {'first_height': int(first[3] - first[1]), 'other_height': int(other[3] - other[1]), 'ratio': round(r, 3)}
    target = a.get('ratio', 2.0)
    if abs(r - target) <= a.get('pass_tol', 0.15):
        return 'pass', ev
    if abs(r - target) >= a.get('fail_tol', 0.4):
        return 'fail', dict(ev, reason=f'the opening letter is {r:.2f} times as tall, not {target:g} times')
    return PERSON, dict(ev, reason='ratio too close to the limit to call')


OPS.update({
    'v2_keyline_only_r5c': op_keyline_only_r5c,
    'v2_ground_absent_r5c': op_ground_absent_r5c,
    'v2_cap_ratio_r5c': op_cap_ratio_r5c,
})


# ---------------------------------------------------------------- small labels the earlier check could not place


def _small_label(text: str, height: float, img_h: int, a) -> bool:
    """A small label (the round-3 definition): a line with no lowercase letters and two capital letters at least (a
    price or figure alone is not a label), letters no taller than `small` (2.5%) of the image height, at most
    max_words words where that is set, and not one of not_labels (the brand's wordmark, a name set as a heading)."""
    if re.search(r'[a-z]', text) or len(re.findall(r'[A-Z]', text)) < 2:
        return False
    if a.get('max_words') and len(text.split()) > a['max_words']:
        return False
    bare = re.sub(r'[^0-9a-z]+', ' ', text.lower()).strip()
    if any(bare == re.sub(r'[^0-9a-z]+', ' ', n.lower()).strip() for n in a.get('not_labels', [])):
        return False
    return height <= a.get('small', 0.025) * img_h


def _missed_lines(path: Path, lines, a):
    """Lines the main OCR missed, read by the multi-pass word reading of round 4 (t4.pb_words: the image and a
    contrast-stretched copy, light grey type made dark, at 2x and 1x): words read at min_conf (80) or more that no
    existing line covers, the most confident reading kept where two overlap, grouped into rows (a word joins a row
    when the two overlap by half their height or more and the gap is under twice the word height)."""
    photo = t4.pb_photo_mask(path, {})
    words = t4.pb_words(str(path), np.packbits(photo).tobytes(), photo.shape)
    words = sorted((w for w in words if w['conf'] >= a.get('min_conf', OCR_GOOD_CONF) and re.search(r'[A-Za-z0-9]', w['text'])),
                   key=lambda w: (-w['conf'], w['bbox']))
    taken = []
    for w in words:
        if any(base._overlap(w['bbox'], l.bbox) > 0.3 for l in lines):
            continue
        if any(base._overlap(w['bbox'], t['bbox']) > 0.5 for t in taken):
            continue
        taken.append(w)
    rows = []
    for w in sorted(taken, key=lambda w: (w['bbox'][1], w['bbox'][0])):
        x0, y0, x1, y1 = w['bbox']
        for r in rows:
            rx0, ry0, rx1, ry1 = r['bbox']
            vov = min(y1, ry1) - max(y0, ry0)
            gap = max(x0 - rx1, rx0 - x1)
            if vov >= 0.5 * min(y1 - y0, ry1 - ry0) and gap < 2 * max(y1 - y0, ry1 - ry0):
                r['words'].append(w)
                r['bbox'] = (min(x0, rx0), min(y0, ry0), max(x1, rx1), max(y1, ry1))
                break
        else:
            rows.append({'words': [w], 'bbox': (x0, y0, x1, y1)})
    out = []
    for r in rows:
        ws = sorted(r['words'], key=lambda w: w['bbox'][0])
        out.append((' '.join(w['text'] for w in ws), r['bbox'], min(w['conf'] for w in ws)))
    return out


def op_small_labels_r5c(path, a):
    """An earlier type-colour or colour-use check (check: v2_type_ink_pb or v2_colour_only_as_pb) that sent a file to
    a person because a small label in a label colour could not be placed: either the label's role was unknown (no
    body size on the file) or OCR did not read it. The check runs first unchanged; any answer but person stands. On
    person, every small label (_small_label: no lowercase letters, two capitals at least, letters no taller than
    `small`, 0.025 of the image height; at most max_words words where set; not one of not_labels) outside photographs
    is named as an allowed line, taken from the main
    OCR and, with extra_ocr, from the multi-pass word reading for lines the main OCR missed (_missed_lines, words at
    min_conf 80 or more), and the check runs again with those lines added; its answer stands. For
    v2_type_ink_pb such a line may use label_colors; for v2_colour_only_as_pb it is an allowed line. Lines the main
    OCR missed are added to its reading only for that second run."""
    path = Path(path)
    check = _sub(a, a['check'])
    st, ev = base.run(path, check)
    if st != PERSON or path.suffix.lower() not in IMAGES:
        return st, ev
    rgb = r3._pixels(str(path))
    img_h = rgb.shape[0]
    photo = r3._photo_mask(path, check)
    cached = base.ocr_layer_cached(str(path))

    def outside(box):
        cx, cy = int((box[0] + box[2]) / 2), int((box[1] + box[3]) / 2)
        return 0 <= cy < photo.shape[0] and 0 <= cx < photo.shape[1] and not photo[cy, cx]
    labels = [l.text for l in cached.lines if l.conf >= OCR_GOOD_CONF and outside(l.bbox)
              and _small_label(l.text, l.bbox[3] - l.bbox[1], img_h, a)]
    added = []
    if a.get('extra_ocr'):
        for text, box, conf in _missed_lines(path, cached.lines, a):
            if outside(box) and _small_label(text, box[3] - box[1], img_h, a):
                gray = np.asarray(t4.pa_gray(str(path)), dtype=np.uint8)
                size = base.cap_height(gray, box, text) or (box[3] - box[1])
                added.append(base.Line(text, tuple(float(v) for v in box), float(size), float(conf), source='ocr'))
    if not labels and not added:
        return st, ev
    names = labels + [l.text for l in added]
    second = dict(check)
    if check['op'] == 'v2_colour_only_as_pb':
        second['allow'] = list(check.get('allow') or []) + [{'whole': names}]
    else:
        second['allow'] = list(check.get('allow') or []) + [{'whole': names, 'colors': a['label_colors']}]
    cached.lines.extend(added)
    try:
        st2, ev2 = base.run(path, second)
    finally:
        for l in added:
            cached.lines.remove(l)
    return st2, dict(ev2 if isinstance(ev2, dict) else {'evidence': ev2}, small_labels=names[:8],
                     read_again=[l.text for l in added][:4], first_answer=ev.get('reason') if isinstance(ev, dict) else None)


# ---------------------------------------------------------------- a line set exactly in another palette colour


def _blend_dist(ink, colour, ground) -> float:
    """Per-channel distance from an ink reading to the nearest blend of colour with the ground (colour mixed with
    0 to 100% of the ground, in 0.1% steps): how far the reading is from thin type in that colour."""
    c = r3._hex_rgb(colour).astype(float)
    s = np.linspace(0.0, 1.0, 1001)[:, None]
    return float(np.abs(c + s * (np.asarray(ground, float) - c) - np.asarray(ink, float)).max(axis=1).min())


def op_named_colour_r5c(path, a):
    """A text-colour check on an image (check: v2_line_colour_raster) whose lines it could not call because their
    ink lies between its pass band and its fail band (5, or 8 on JPEG, plus 3 for letter cores; 30 or more off
    fails). The check runs first unchanged; any answer but person stands. On person, a line it listed is set in
    another colour of the palette, a fail, when its letter-core ink is within other_tol (3 per channel) of one of
    others (palette colours the rule does not allow) and more than the check's own pass tolerance from every allowed
    colour (colors) and from every blend of an allowed colour with the line's ground (_blend_dist: thin type in an
    allowed colour reads lighter along that blend, never as another hue). Lines are those the check picked (read at
    its min_conf, 80 by default). Anything else stays with a person."""
    path = Path(path)
    check = _sub(a, a['check'])
    st, ev = base.run(path, check)
    if st != PERSON or not isinstance(ev, dict):
        return st, ev
    tol = r3._tol(path, check) + 3
    other_tol = a.get('other_tol', 3)
    hits = []
    for item in ev.get('lines', []):
        if not isinstance(item, dict) or 'ink' not in item:
            continue
        ink = r3._hex_rgb(item['ink']).astype(float)
        ground = r3._hex_rgb(item['ground']).astype(float)
        d_allowed = min(_blend_dist(ink, c, ground) for c in a['colors'])
        near = [c for c in a['others'] if float(np.abs(ink - r3._hex_rgb(c)).max()) <= other_tol]
        if near and d_allowed > tol:
            hits.append(dict(item, colour=near[0], off_allowed=round(d_allowed, 1)))
    if hits:
        return 'fail', {'in_another_palette_colour': hits[:4]}
    return st, ev


OPS.update({
    'v2_small_labels_r5c': op_small_labels_r5c,
    'v2_named_colour_r5c': op_named_colour_r5c,
})


# ---------------------------------------------------------------- lining figures: record values and photo marks


def op_lining_r5c(path, a):
    """Every figure is a lining figure (as v2_lining_r4t, whose settings and limits it keeps: pass_tol 0.06,
    fail_short 0.85, fail_drop 0.12, photo_digit_max 0.03, min_conf 80, min_px 8, ring_px 4, ground_tol 14,
    flat_ring 0.85, ink_min 20, flat_tol 3, max_text 0.15). PDFs: v2_lining_r4t unchanged. Images, two additions:
    (1) a word read below min_conf whose text is exactly one of known (values from the deliverable's own record,
    such as its serial number, compared letter for letter) is taken as read, since the reading is confirmed by the
    record; its figures are then measured from the pixels as any other word's. (2) Text-like ink outside the
    photographs that no word covers is left out where it is the supplied photograph's own pixels: the photo named in
    photos, found and laid over the deliverable, matches the image there (photo_b._photo_content: 90% of the pixels
    within 40 levels after a light blur), so the marks are the photograph's backdrop or product, not type."""
    import ops_r3_photo_b as pb
    path = Path(path)
    if path.suffix.lower() not in t4.PB_IMAGES:
        return t4.op_lining_r4t(path, a)
    from PIL import Image
    pass_tol, fail_short, fail_drop = a.get('pass_tol', 0.06), a.get('fail_short', 0.85), a.get('fail_drop', 0.12)
    min_conf = a.get('min_conf', OCR_GOOD_CONF)
    known = [base.canon(k) for k in a.get('known', []) if k]
    rgb = np.asarray(Image.open(path).convert('RGB'))
    H = rgb.shape[0]
    photo = t4.pb_photo_mask(path, a)
    words = t4.pb_words(str(path), np.packbits(photo).tobytes(), photo.shape)
    measured, bad, unsure, in_photo, confirmed = [], [], [], [], []
    for w in words:
        if not re.search(r'\d', w['text']):
            continue
        x0, y0, x1, y1 = w['bbox']
        hgt = y1 - y0
        cy, cx = int((y0 + y1) / 2), int((x0 + x1) / 2)
        if photo[min(H - 1, max(0, cy)), min(rgb.shape[1] - 1, max(0, cx))]:
            if hgt >= a.get('photo_digit_max', 0.03) * H and w['conf'] >= OCR_GOOD_CONF:
                return PERSON, {'reason': f'figures set over a photograph: {w["text"]}'}
            in_photo.append(w['text'])
            continue
        if w['conf'] < min_conf:
            if any(o['conf'] >= min_conf and base._overlap(o['bbox'], w['bbox']) > 0.5
                   and re.sub(r'\D', '', o['text']) == re.sub(r'\D', '', w['text']) for o in words):
                continue                               # another pass read the same figures confidently
            if base.canon(w['text']) not in known:
                return PERSON, {'reason': f'figures read without confidence: {w["text"]}'}
            confirmed.append(w['text'])                # a low-confidence read that is the record's value exactly
        figs, why = t4.pb_word_figures(rgb, w, a)
        if figs is None:
            return PERSON, {'reason': f'{w["text"]}: figures not on a flat ground' if why == 'ground' else why}
        if not any(ch.isdigit() for ch, _, _ in figs):
            return PERSON, {'reason': f'{w["text"]}: figures not separated'}
        ref_h = max(h for _, h, _ in figs)
        if ref_h < a.get('min_px', 8):
            return PERSON, {'reason': f'{w["text"]}: figures too small to measure'}
        bottoms = sorted(b for _, _, b in figs)
        base_y = bottoms[len(bottoms) // 2]
        tol_px = max(1.0, pass_tol * ref_h)
        for ch, h, b in figs:
            if not ch.isdigit():
                continue
            drop = (b - base_y) / ref_h
            if h < fail_short * ref_h or drop > fail_drop:
                bad.append((w['text'], ch, round(h / ref_h, 2), round(drop, 2)))
            elif ref_h - h > tol_px or abs(b - base_y) > tol_px:
                unsure.append((w['text'], ch, round(h / ref_h, 2), round(drop, 2)))
        measured.append(w['text'])
    ev = {'measured': sorted(set(measured))[:12], 'left_as_photo_detail': in_photo[:8], 'confirmed_by_record': confirmed}
    if bad:
        return 'fail', dict(ev, old_style=bad[:6])
    if unsure:
        return PERSON, dict(ev, reason='a figure is slightly short or low', figures_unsure=unsure[:6])
    unread = t4.pb_unread(rgb, photo, words, a)
    check = {'photos': a.get('photos', []), '_asset_dirs': a.get('_asset_dirs')}
    own = [b for b in unread if a.get('photos') and pb._photo_content(path, check, b)]
    unread = [b for b in unread if b not in own]
    if own:
        ev['photo_own_marks'] = own[:6]
    if unread:
        return PERSON, dict(ev, reason='text outside the photographs that was not read confidently may hold a figure',
                            unread_boxes=unread[:6])
    if not measured:
        return PERSON, dict(ev, reason='no typeset figure found')
    return 'pass', ev


# ---------------------------------------------------------------- size relations with lines read at lower confidence


def op_sizes_vs_r5c(path, a):
    """As v2_sizes_vs (every line matching a is set smaller, rel 'smaller', or larger than every line matching b;
    letter heights on images, 8% too close to call; a fail needs every compared line read at 80 or more), with the
    lines picked at min_conf (60) instead of 80: a line is picked by its words matching the patterns, and its size is
    measured from its pixels, which does not depend on every letter being read. Not shown (a or b) is decided as in
    v2_sizes_vs: a pass only when optional and every wording line was read at 80 or more."""
    import ops_r3_photo_a as pa
    from objective_ops import merged, text_layers
    layer = merged(text_layers(Path(path)))
    mc = a.get('min_conf', 60)
    la = pa._pattern_lines(layer, a['a'], mc)
    lb = [l for l in pa._pattern_lines(layer, a['b'], mc) if l not in la]
    reliable = layer.source == 'pdf' or getattr(layer, 'confident_all', layer.confident)
    if not la:
        return ('pass', {'reason': 'not shown'}) if a.get('optional') and reliable else (PERSON, {'reason': 'text not found'})
    if not lb:
        return ('pass', {'reason': 'nothing to compare shown'}) if reliable else (PERSON, {'reason': 'compared text not found'})
    if not all(l.size_ok for l in la + lb):
        return PERSON, {'reason': 'letter height could not be measured on every line compared'}
    margin = base.SIZE_MARGIN if layer.source == 'ocr' else 0.01
    worst = None
    for x in la:
        for y in lb:
            r = x.size / y.size if y.size else 99
            ok = r < 1 - margin if a['rel'] == 'smaller' else r > 1 + margin
            if not ok:
                close = abs(r - 1) <= margin and layer.source == 'ocr'
                item = ('person' if close else 'fail', {'a': x.text[:30], 'a_size': round(x.size, 1), 'b': y.text[:30], 'b_size': round(y.size, 1)})
                if worst is None or item[0] == 'fail':
                    worst = item
    if worst:
        st, ev = worst
        if st == 'fail' and layer.source == 'ocr' and not all(l.conf >= OCR_GOOD_CONF for l in la + lb):
            st = PERSON
        return (PERSON if st == 'person' else 'fail'), ev
    return 'pass', {'a': [round(l.size, 1) for l in la][:4], 'b': [round(l.size, 1) for l in lb][:4],
                    'least_confidence': round(min(l.conf for l in la + lb), 1)}


OPS.update({
    'v2_lining_r5c': op_lining_r5c,
    'v2_sizes_vs_r5c': op_sizes_vs_r5c,
})
