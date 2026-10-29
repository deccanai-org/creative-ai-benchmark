"""Round 4 type measurements (2026-10-28): figures, the dollar sign, capital heights, caption layout under a picture
and letter spacing, read from glyph data. Images: OCR word boxes locate the text, ink pieces (connected components on a
flat ground) give each glyph's box. PDFs: glyphs are read exactly. Op names end _r4t; every limit is a setting named in
its op's docstring. Ops: v2_price_figures_r4t (price figures lining, dollar sign height and top), v2_cap_ratio_r4t
(opening capital against a later capital), v2_caption_r4t (numeral, name, rule and caption block under a picture),
v2_lining_r4t (every figure a lining figure), v2_track_vs_r4t (one line letterspaced more open than another).
"""
from __future__ import annotations

# ---------------------------------------------------------------- part A
import functools
import re
from pathlib import Path

import numpy as np
from PIL import Image

import objective_ops as base
from objective_ops import PERSON

PA_IMAGES = ('.png', '.jpg', '.jpeg')


@functools.lru_cache(maxsize=16)
def pa_gray(key: str) -> np.ndarray:
    im = Image.open(key)
    if im.mode in ('RGBA', 'LA', 'P'):
        rgba = im.convert('RGBA')
        im = Image.alpha_composite(Image.new('RGBA', rgba.size, (255, 255, 255, 255)), rgba)
    return np.asarray(im.convert('L'), dtype=np.int16)


def pa_comps(gray: np.ndarray, box, ink_tol: int, min_area: int = 6):
    """Ink pieces inside a box: the ground is the median of the box border, ink differs from it by ink_tol or more.
    Returns [(x0, y0, x1, y1, area)] in image pixels, sorted left to right, and the ground level."""
    import cv2
    h, w = gray.shape
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    crop = gray[y0:y1, x0:x1]
    if crop.shape[0] < 4 or crop.shape[1] < 4:
        return [], None
    ring = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    ground = float(np.median(ring))
    ink = (np.abs(crop - ground) >= ink_tol).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = []
    for i in range(1, n):
        cx, cy, cw, ch, area = st[i]
        if area >= min_area:
            out.append((x0 + cx, y0 + cy, x0 + cx + cw, y0 + cy + ch, int(area)))
    out.sort(key=lambda c: c[0])
    return out, ground


def pa_ring_flat(gray, box, tol=12):
    """The ground around a box is one flat tone (so ink pieces are type, not photograph detail)."""
    h, w = gray.shape
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w - 1, x1), min(h - 1, y1)
    ring = np.concatenate([gray[y0, x0:x1], gray[y1, x0:x1], gray[y0:y1, x0], gray[y0:y1, x1]])
    if not len(ring):
        return False
    return float(np.mean(np.abs(ring - np.median(ring)) <= tol)) >= 0.9


def pa_find_line(layer, rx, min_conf=0):
    """OCR lines whose text matches rx (a regex on the text with spaces kept), largest first."""
    hits = [l for l in layer.lines if re.search(rx, l.text) and l.conf >= min_conf]
    return sorted(hits, key=lambda l: -(l.bbox[3] - l.bbox[1]))


# ------------------------------------------------------------------ price figures and the dollar sign (PHOTO-08)

def pa_price_glyphs(path, a):
    """The price's figure pieces and its dollar sign, from the OCR line whose figures read the price exactly.
    Returns (digits, dollar, line) or (None, reason, None)."""
    gray = pa_gray(str(path))
    layer = base.ocr_layer_cached(str(path))
    digits = re.sub(r'\D', '', str(a['price']))
    lines = [l for l in layer.lines if digits in re.sub(r'\D', '', l.text)]
    if not lines:
        return None, f'price {a["price"]} not read', None
    line = max(lines, key=lambda l: l.bbox[3] - l.bbox[1])
    x0, y0, x1, y1 = line.bbox
    h = y1 - y0
    box = (x0 - 1.4 * h, y0 - 0.35 * h, x1 + 0.25 * h, y1 + 0.35 * h)
    if not pa_ring_flat(gray, box, a.get('ground_tol', 12)):
        return None, 'the price does not sit on a flat ground', None
    comps, _ = pa_comps(gray, box, a.get('ink_tol', 60))
    if not comps:
        return None, 'no ink read at the price', None
    big = max(c[3] - c[1] for c in comps if c[0] >= x0 - 2)
    # the price as set ("26,900"): its last characters map one to one onto the pieces ending at the OCR box's right
    # end; a comma piece must be the smallest there, else the mapping is not trusted
    shown = f'{int(digits):,}'
    pieces = [c for c in comps if (c[3] - c[1]) >= 0.15 * big and c[2] <= x1 + 0.25 * h]
    if len(pieces) < len(shown):
        return None, f'{len(pieces)} shapes found for the {len(shown)} characters of {shown}', line
    run = pieces[-len(shown):]
    figs = [c for c, ch in zip(run, shown) if ch.isdigit()]
    commas = [c for c, ch in zip(run, shown) if not ch.isdigit()]
    if commas and max(c[4] for c in commas) >= 0.5 * min(c[4] for c in figs):
        return None, 'the comma shape is not clearly smaller than the figures', line
    widths = [c[2] - c[0] for c in figs]
    if max(widths) > 1.6 * float(np.median(widths)):
        return None, 'two figures touch, so their shapes cannot be measured apart', line
    first = figs[0][0]
    left = [c for c in comps if c[2] <= first + 1 and c not in figs and (c[3] - c[1]) >= 0.15 * big]
    dollar = None
    if left:
        near = [c for c in left if first - c[2] <= 1.0 * big]
        if near:
            # the dollar sign: every piece of the nearest glyph (a bar may be drawn apart from the S)
            ref = max(near, key=lambda c: c[2])
            parts = [c for c in near if min(c[2], ref[2]) - max(c[0], ref[0]) > 0.3 * min(c[2] - c[0], ref[2] - ref[0])]
            dollar = (min(c[0] for c in parts), min(c[1] for c in parts), max(c[2] for c in parts), max(c[3] for c in parts))
            if len([c for c in near if c not in parts]) > 0:
                dollar = ('extra', dollar)
    return figs, dollar, line


def op_price_figures_r4t(path, a):
    """Price figures on an image: lining figures of one height, the dollar sign's height and the alignment of its top.

    Settings: price (the asking price; the OCR line whose figures read it exactly is measured), test ('lining',
    'dollar_ratio' or 'dollar_top'), ink_tol (60: grey-level difference from the ground that counts as ink),
    ground_tol (12: the ground around the price must be one flat tone within this).
    lining: every figure within pass_tol (0.06) of the tallest figure's height and of the common baseline passes; a
    figure shorter than fail_short (0.85) of the tallest or dropping more than fail_drop (0.12) of that height below
    the baseline fails; in between a person decides.
    dollar_ratio: the sign's ink height divided by the figures' height; within pass_tol (0.08) of target (0.6)
    passes, fail_tol (0.2) or further from it fails, in between a person decides.
    dollar_top: the gap between the sign's top and the figures' top, as a share of the figures' height; pass_tol
    (0.05) or less passes, fail_tol (0.15) or more fails. Figures of unequal height (more than even_tol 0.06 apart):
    the sign fails dollar_top when its top is fail_tol or more from every figure's top, else a person decides, and
    dollar_ratio goes to a person. The price's pieces are mapped one to one onto the price as set (26,900); a comma
    piece not clearly smaller than the figures (half their ink area) sends the check to a person.
    A price not read, figures that touch, or a dollar sign not found apart from the figures go to a person."""
    path = Path(path)
    if path.suffix.lower() not in PA_IMAGES:
        return PERSON, {'reason': 'read on images only'}
    figs, dollar, line = pa_price_glyphs(path, a)
    if figs is None:
        return PERSON, {'reason': dollar}
    hs = [c[3] - c[1] for c in figs]
    bottoms = [c[3] for c in figs]
    tops = [c[1] for c in figs]
    H = float(max(hs))
    base_y = float(np.median(bottoms))
    ev = {'line': line.text, 'figure_heights': hs, 'drops': [round((b - base_y) / H, 3) for b in bottoms]}
    test = a['test']
    if test == 'lining':
        pt, fs, fd = a.get('pass_tol', 0.06), a.get('fail_short', 0.85), a.get('fail_drop', 0.12)
        short = min(hs) / H
        drop = max(b - base_y for b in bottoms) / H
        ev.update(shortest=round(short, 3), largest_drop=round(drop, 3))
        if short >= 1 - pt and max(abs(b - base_y) for b in bottoms) / H <= pt:
            return 'pass', ev
        if short <= fs or drop >= fd:
            return 'fail', dict(ev, reason='figures of unequal height or dropping below the baseline (old-style)')
        return PERSON, dict(ev, reason='figure heights differ by too little to call')
    if dollar is None:
        return PERSON, dict(ev, reason='dollar sign not found beside the figures')
    if isinstance(dollar, tuple) and dollar and dollar[0] == 'extra':
        return PERSON, dict(ev, reason='more than one shape left of the figures')
    dh = dollar[3] - dollar[1]
    uneven = min(hs) / H < 1 - a.get('even_tol', 0.06)
    if uneven and test == 'dollar_top':
        gaps = [abs(dollar[1] - t) / H for t in tops]
        ev.update(top_gaps=[round(g, 3) for g in gaps])
        if min(gaps) >= a.get('fail_tol', 0.15):
            return 'fail', dict(ev, reason='the dollar sign\'s top lines up with the top of none of the figures')
        return PERSON, dict(ev, reason='the figures are not of one height, so the figures\' top is unclear')
    if uneven:
        return PERSON, dict(ev, reason='the figures are not of one height, so the figures\' height is unclear')
    if test == 'dollar_ratio':
        r = dh / H
        target = a.get('target', 0.6)
        ev.update(ratio=round(r, 3), dollar_height=dh)
        if abs(r - target) <= a.get('pass_tol', 0.08):
            return 'pass', ev
        if abs(r - target) >= a.get('fail_tol', 0.2):
            return 'fail', dict(ev, reason=f'dollar sign is {r:.2f} of the figures\' height')
        return PERSON, dict(ev, reason='ratio too close to the limit to call')
    if test == 'dollar_top':
        gap = abs(dollar[1] - float(np.median(tops))) / H
        ev.update(top_gap=round(gap, 3), dollar_top=dollar[1], figures_top=float(np.median(tops)))
        if gap <= a.get('pass_tol', 0.05):
            return 'pass', ev
        if gap >= a.get('fail_tol', 0.15):
            return 'fail', dict(ev, reason=f'dollar sign top sits {gap:.2f} of the figure height away from the figures\' top')
        return PERSON, dict(ev, reason='too close to the limit to call')
    raise ValueError(f'unknown test {test}')


# ------------------------------------------------------------------ opening capital against another capital (PHOTO-04)

def op_cap_ratio_r4t(path, a):
    """The first letter of a line stands `ratio` times as tall as the first letter of a later word.

    Settings: line (the line's exact text, read by OCR at min_conf 80 or more), word (index of the later word, 1 =
    second word), ratio (2.0), pass_tol (0.15) and fail_tol (0.4): a measured height ratio within pass_tol of ratio
    passes, fail_tol or more away from it fails, in between a person decides. Letters are ink pieces inside the OCR box on a flat ground (ground_tol 12, ink_tol 60); each word
    must split into exactly as many pieces as it has letters, else a person decides."""
    path = Path(path)
    if path.suffix.lower() not in PA_IMAGES:
        return PERSON, {'reason': 'read on images only'}
    gray = pa_gray(str(path))
    layer = base.ocr_layer_cached(str(path))
    want = a['line']
    lines = [l for l in layer.lines if base.canon(l.text, False) == base.canon(want, False) and l.conf >= a.get('min_conf', 80)]
    if len(lines) != 1:
        return PERSON, {'reason': f'line {want} not read once confidently ({len(lines)} found)'}
    line = lines[0]
    x0, y0, x1, y1 = line.bbox
    h = y1 - y0
    box = (x0 - 0.6 * h, y0 - 0.6 * h, x1 + 0.3 * h, y1 + 0.4 * h)
    if not pa_ring_flat(gray, box, a.get('ground_tol', 12)):
        return PERSON, {'reason': 'the line does not sit on a flat ground'}
    comps, _ = pa_comps(gray, box, a.get('ink_tol', 60))
    words = want.split()
    nletters = [len(re.sub(r'[^A-Za-z]', '', w)) for w in words]
    if len(comps) != sum(nletters):
        return PERSON, {'reason': f'{len(comps)} letter shapes for {sum(nletters)} letters (touching or broken letters)'}
    first = comps[0]
    k = a.get('word', 1)
    other = comps[sum(nletters[:k])]
    r = (first[3] - first[1]) / max(1, other[3] - other[1])
    ev = {'first_height': first[3] - first[1], 'other_height': other[3] - other[1], 'ratio': round(r, 3)}
    target = a.get('ratio', 2.0)
    if abs(r - target) <= a.get('pass_tol', 0.15):
        return 'pass', ev
    if abs(r - target) >= a.get('fail_tol', 0.4):
        return 'fail', dict(ev, reason=f'the opening letter is {r:.2f} times as tall, not {target:g} times')
    return PERSON, dict(ev, reason='ratio too close to the limit to call')


# ------------------------------------------------------------------ caption block under a picture (PHOTO-06)

@functools.lru_cache(maxsize=16)
def pa_caption(key: str, ink_tol: int, rule_tol: int, min_run: float, pic_tol: int = 15):
    """Layout of a caption set under a picture on a flat ground: the picture box, rules (long thin runs of ink),
    the first text band (numeral in the left margin, name to the right) and all ink below the picture."""
    import cv2
    gray = pa_gray(key)
    h, w = gray.shape
    border = np.concatenate([gray[:4].ravel(), gray[-4:].ravel(), gray[:, :4].ravel(), gray[:, -4:].ravel()])
    ground = float(np.median(border))
    if np.mean(np.abs(border - ground) <= 12) < 0.9:
        return None, 'the ground around the edges is not one flat tone'
    ink = (np.abs(gray - ground) >= ink_tol).astype(np.uint8)
    # the picture block: the largest piece differing from the ground by pic_tol or more (a pale mount counts)
    n, lab, st, _ = cv2.connectedComponentsWithStats((np.abs(gray - ground) >= pic_tol).astype(np.uint8), connectivity=8)
    if n < 2:
        return None, 'no ink'
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    px, py, pw, ph, parea = st[i]
    if pw * ph < 0.2 * w * h or parea < 0.6 * pw * ph:
        return None, 'no solid picture block found'
    pic = (int(px), int(py), int(px + pw), int(py + ph))
    # anything outside the picture other than below it means a caption may sit elsewhere
    elsewhere = ink.copy()
    elsewhere[pic[3]:, :] = 0
    elsewhere[pic[1]:pic[3], pic[0]:pic[2]] = 0
    above_side = int(elsewhere.sum())
    faint = (np.abs(gray - ground) >= rule_tol)
    below = slice(pic[3] + 2, h)
    # rules: rows below the picture whose longest run of faint ink is min_run of the picture width or more
    rules = []
    for y in range(pic[3] + 2, h):
        row = faint[y]
        if not row.any():
            continue
        xs = np.flatnonzero(row)
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts = np.concatenate([[xs[0]], xs[breaks + 1]])
        ends = np.concatenate([xs[breaks], [xs[-1]]])
        k = int(np.argmax(ends - starts))
        if ends[k] - starts[k] + 1 >= min_run * pw:
            if rules and rules[-1]['y1'] == y - 1:
                r = rules[-1]
                r['y1'] = y
                r['x0'], r['x1'] = min(r['x0'], int(starts[k])), max(r['x1'], int(ends[k]) + 1)
            else:
                rules.append({'y0': y, 'y1': y, 'x0': int(starts[k]), 'x1': int(ends[k]) + 1})
    rule_rows = np.zeros(h, bool)
    for r in rules:
        rule_rows[r['y0']:r['y1'] + 1] = True
    text_ink = ink.copy()
    text_ink[rule_rows] = 0
    rows = text_ink[below].any(axis=1)
    ys = np.flatnonzero(rows) + pic[3] + 2
    if not len(ys):
        return None, 'no text below the picture'
    # first text band: from the first inked row to the first blank row after it
    b0 = int(ys[0])
    b1 = b0
    while b1 + 1 < h and text_ink[b1 + 1].any():
        b1 += 1
    band = text_ink[b0:b1 + 1]
    n2, _, st2, _ = cv2.connectedComponentsWithStats(band.astype(np.uint8), connectivity=8)
    comps = [(int(s[0]), b0 + int(s[1]), int(s[0] + s[2]), b0 + int(s[1] + s[3]), int(s[4])) for s in st2[1:] if s[4] >= 6]
    allys = np.flatnonzero(ink[below].any(axis=1)) + pic[3] + 2
    xs_all = np.flatnonzero(ink[below].any(axis=0))
    block = (int(xs_all[0]), int(allys[0]), int(xs_all[-1]) + 1, int(allys[-1]) + 1) if len(xs_all) else None
    return {'pic': pic, 'rules': rules, 'band': (b0, b1 + 1), 'band_comps': comps, 'block': block,
            'above_side': above_side, 'size': (w, h)}, None


def op_caption_r4t(path, a):
    """Caption block under a picture on a flat ground (share images of PHOTO-06), measured from ink.

    The picture is the largest solid block of ink (at least 20% of the image); the first text band below it holds
    the plate numeral (pieces wholly left of the picture's left edge, in the margin) and the name (pieces from the
    picture's left edge on, which OCR must read as capitals); a rule is a run of ink at least min_run (0.5) of the
    picture width long (faint ink counts for rules: rule_tol 25 grey levels; other ink ink_tol 60). The picture block
    is the largest piece differing from the ground by pic_tol (15) grey levels, so a pale mount counts; with asset
    set, its shape must match the supplied picture's within aspect_tol (0.02), else a person decides. Tests:
    numeral_margin (pass when a numeral sits wholly in the left margin; else a person), numeral_larger (numeral
    height over the name's capital height: pass_ratio 1.10 or more passes, fail_ratio 0.95 or less fails),
    numeral_top (top gap as a share of the capital height: pass_tol 0.05 or less passes, fail_tol 0.15 or more
    fails), rule_single (the first rule below the name band: one rule of max_px 2 rows or fewer passes; a second rule
    before the next text line or a bar of fail_px 5 rows or more fails), rule_edges (both rule ends within tol 3 px of
    the picture's edges pass, fail_px 12 px or more off fails), caption_area (the bounding box of everything below the
    picture covers at most pass_ratio 0.8 of the picture's area: pass; ink beside or above the picture: a person),
    place_below (the OCR line matching place, read at min_conf 80, starts below the rule: pass; ends above it: fail).
    In between the bands, and whenever a part is not found, a person decides."""
    path = Path(path)
    if path.suffix.lower() not in PA_IMAGES:
        return PERSON, {'reason': 'read on images only'}
    cap, why = pa_caption(str(path), a.get('ink_tol', 60), a.get('rule_tol', 25), a.get('min_run', 0.5), a.get('pic_tol', 15))
    if cap is None:
        return PERSON, {'reason': why}
    pic, rules, comps = cap['pic'], cap['rules'], cap['band_comps']
    test = a['test']
    ev = {'picture': pic}
    if a.get('asset'):
        try:
            src = base.asset_path(a, a['asset'])
            sw, sh = Image.open(src).size
        except Exception:
            return PERSON, dict(ev, reason=f'supplied picture {a["asset"]} not found')
        got = (pic[2] - pic[0]) / (pic[3] - pic[1])
        if abs(got / (sw / sh) - 1) > a.get('aspect_tol', 0.02):
            return PERSON, dict(ev, reason='the picture block is not the shape of the supplied picture (cropped, or a frame drawn round it)')
    if test == 'caption_area':
        if cap['above_side']:
            return PERSON, dict(ev, reason='ink beside or above the picture: the caption block may sit there')
        bx = cap['block']
        area = (bx[2] - bx[0]) * (bx[3] - bx[1])
        parea = (pic[2] - pic[0]) * (pic[3] - pic[1])
        ev.update(block=bx, share=round(area / parea, 3))
        if area <= a.get('pass_ratio', 0.8) * parea:
            return 'pass', ev
        return PERSON, dict(ev, reason='caption block not clearly smaller than the picture')
    # name band: OCR must read a line in capitals there
    layer = base.ocr_layer_cached(str(path))
    b0, b1 = cap['band']
    tol_edge = a.get('edge_tol', 2)
    num = [c for c in comps if c[2] <= pic[0] - tol_edge]
    name = [c for c in comps if c[0] >= pic[0] - tol_edge]
    straddle = [c for c in comps if c not in num and c not in name]
    in_band = [l for l in layer.lines if l.bbox[1] < b1 and l.bbox[3] > b0 and l.conf >= a.get('name_conf', 75)]
    caps = [l for l in in_band if len(re.findall(r'[A-Z]', l.text)) >= 4 and not re.search(r'[a-z]{2}', l.text)]
    if straddle or not name or not caps:
        return PERSON, dict(ev, reason='the name line (in capitals) was not found clearly beside the picture edge')
    nh = [c[3] - c[1] for c in name]
    tallest = max(nh)
    letters = [c for c in name if c[3] - c[1] >= 0.6 * tallest]
    cap_h = float(np.median([c[3] - c[1] for c in letters]))
    cap_top = float(np.median([c[1] for c in letters]))
    ev.update(name_cap_height=cap_h, name_top=cap_top)
    after = [r for r in rules if r['y0'] >= b1]
    if test in ('numeral_margin', 'numeral_larger', 'numeral_top'):
        if not num:
            return PERSON, dict(ev, reason='no numeral found in the left margin; a person confirms where it is')
        nx = (min(c[0] for c in num), min(c[1] for c in num), max(c[2] for c in num), max(c[3] for c in num))
        num_h = max(c[3] - c[1] for c in num)
        ev.update(numeral=nx, numeral_height=num_h)
        ocr_num = [l for l in layer.lines if base._overlap(l.bbox, nx) > 0.5 and re.search(r'[0-9OoQIl|]', l.text)]
        if not ocr_num:
            return PERSON, dict(ev, reason='the shape in the margin was not read as a numeral')
        if test == 'numeral_margin':
            return 'pass', ev
        if test == 'numeral_larger':
            r = num_h / cap_h
            ev['ratio'] = round(r, 3)
            if r >= a.get('pass_ratio', 1.10):
                return 'pass', ev
            if r <= a.get('fail_ratio', 0.95):
                return 'fail', dict(ev, reason='the numeral is not larger than the name')
            return PERSON, dict(ev, reason='sizes too close to call')
        gap = abs(nx[1] - cap_top) / cap_h
        ev['top_gap'] = round(gap, 3)
        if gap <= a.get('pass_tol', 0.05):
            return 'pass', ev
        if gap >= a.get('fail_tol', 0.15):
            return 'fail', dict(ev, reason=f'the numeral top sits {abs(nx[1] - cap_top):.0f} px from the top of the capitals')
        return PERSON, dict(ev, reason='too close to the limit to call')
    if not after:
        return PERSON, dict(ev, reason='no rule found beneath the name')
    rule = after[0]
    ev['rule'] = rule
    if test == 'rule_single':
        thick = rule['y1'] - rule['y0'] + 1
        nxt = [l for l in layer.lines if l.bbox[1] > rule['y1'] and l.conf >= 80 and len(l.text) >= 3]
        stop = min([l.bbox[1] for l in nxt], default=cap['size'][1])
        second = [r for r in after[1:] if r['y0'] < stop]
        ev.update(thickness=thick, rules_before_next_line=1 + len(second))
        if second:
            return 'fail', dict(ev, reason='a second rule sits beneath the name (a double line)')
        if thick >= a.get('fail_px', 5):
            return 'fail', dict(ev, reason=f'the rule is {thick} px thick, a bar rather than a hairline')
        if thick <= a.get('max_px', 2):
            return 'pass', ev
        return PERSON, dict(ev, reason='rule thickness between a hairline and a bar')
    if test == 'rule_edges':
        d0, d1 = abs(rule['x0'] - pic[0]), abs(rule['x1'] - pic[2])
        ev.update(left_off=d0, right_off=d1)
        if max(d0, d1) <= a.get('tol', 3):
            return 'pass', ev
        if max(d0, d1) >= a.get('fail_px', 12):
            return 'fail', dict(ev, reason='the rule does not start and end in line with the picture edges')
        return PERSON, dict(ev, reason='too close to the limit to call')
    if test == 'place_below':
        hits = [l for l in layer.lines if re.search(a['place'], l.text) and l.conf >= a.get('min_conf', 80) and l.bbox[1] > pic[3]]
        if len(hits) != 1:
            return PERSON, dict(ev, reason=f'place and date line read {len(hits)} times')
        l = hits[0]
        ev['place_line'] = (l.text, l.bbox)
        if l.bbox[1] >= rule['y1']:
            return 'pass', ev
        if l.bbox[3] <= rule['y0']:
            return 'fail', dict(ev, reason='the place and date line sits above the rule')
        return PERSON, dict(ev, reason='the line and the rule overlap')
    raise ValueError(f'unknown test {test}')


def op_rule_under_r4t(path, a):
    """The rule directly under the price on an image is no more than max_px thick.

    Settings: price (the OCR line whose figures read it exactly), min_run (0.5: a rule is a run of ink at least this
    share of the image width), rule_tol (25: grey-level difference from the ground that counts as rule ink), start
    (0.3) and max_gap (2.5): the rule is looked for from start to max_gap line heights below the price line; thickness
    counts the rows whose run is at least half as dark as the rule's darkest row (antialiased edges left out).
    Thickness max_px (2) or less passes, fail_px (4) or more fails, in between a person decides. A price not read, or
    no rule in that range, goes to a person."""
    path = Path(path)
    if path.suffix.lower() not in PA_IMAGES:
        return PERSON, {'reason': 'read on images only'}
    gray = pa_gray(str(path))
    layer = base.ocr_layer_cached(str(path))
    digits = re.sub(r'\D', '', str(a['price']))
    lines = [l for l in layer.lines if digits in re.sub(r'\D', '', l.text)]
    if not lines:
        return PERSON, {'reason': f'price {a["price"]} not read'}
    line = max(lines, key=lambda l: l.bbox[3] - l.bbox[1])
    h_img, w_img = gray.shape
    lh = line.bbox[3] - line.bbox[1]
    y_from = int(line.bbox[3] + a.get('start', 0.3) * lh)
    y_to = min(h_img, int(line.bbox[3] + a.get('max_gap', 2.5) * lh))
    ground = float(np.median(gray[y_from:y_to]))
    band, best = [], []
    for y in range(y_from, y_to):
        diff = np.abs(gray[y] - ground)
        row = diff >= a.get('rule_tol', 25)
        if not row.any():
            if band:
                break
            continue
        xs = np.flatnonzero(row)
        breaks = np.flatnonzero(np.diff(xs) > 1)
        starts = np.concatenate([[xs[0]], xs[breaks + 1]])
        ends = np.concatenate([xs[breaks], [xs[-1]]])
        k = int(np.argmax(ends - starts))
        if ends[k] - starts[k] + 1 >= a.get('min_run', 0.5) * w_img:
            band.append(y)
            best.append(float(diff[starts[k]:ends[k] + 1].mean()))
        elif band:
            break
    if not band:
        return PERSON, {'reason': 'no rule found under the price', 'line': line.text}
    peak = max(best)
    thick = sum(1 for v in best if v >= 0.5 * peak)
    ev = {'line': line.text, 'rule_rows': [band[0], band[-1]], 'thickness': thick, 'row_contrast': [round(v) for v in best]}
    if thick <= a.get('max_px', 2):
        return 'pass', ev
    if thick >= a.get('fail_px', 4):
        return 'fail', dict(ev, reason=f'the rule is {thick} px thick')
    return PERSON, dict(ev, reason='thickness too close to the limit to call')


def op_pass_only_r4t(path, a):
    """A wider check whose pass settles this rule: check (an assertion, e.g. every figure on the file is a lining
    figure, which covers the figures of one price) passing is a pass; its fail or person goes to a person, because the
    wider check can fail on text this rule is not about."""
    sub = dict(a['check'])
    sub.update({k: v for k, v in a.items() if k.startswith('_')})
    st, ev = base.run(path, sub)
    if st == 'pass':
        return 'pass', {'wider_check': sub['op'], 'evidence': ev}
    return PERSON, {'reason': f'the wider check answered {st}; a person checks the part this rule is about', 'evidence': ev}


_OPS_A = {'v2_price_figures_r4t': op_price_figures_r4t, 'v2_rule_under_r4t': op_rule_under_r4t, 'v2_pass_only_r4t': op_pass_only_r4t, 'v2_cap_ratio_r4t': op_cap_ratio_r4t, 'v2_caption_r4t': op_caption_r4t}


# ---------------------------------------------------------------- part B
import functools
import re
from pathlib import Path

import numpy as np
from PIL import Image

import objective_ops as base
import objective_ops_r2 as r2
from objective_ops import PERSON

PB_IMAGES = ('.png', '.jpg', '.jpeg')


# ------------------------------------------------------------------ lining figures

def pb_ring_flat(rgb: np.ndarray, box, pad: int, tol: int):
    """Share of the pixels in a ring around a box that match the ring's median colour, and that colour."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    outer = rgb[Y0:Y1, X0:X1].astype(int)
    mask = np.ones(outer.shape[:2], bool)
    mask[max(0, y0 - Y0):max(0, y1 - Y0), max(0, x0 - X0):max(0, x1 - X0)] = False
    ring = outer[mask]
    if len(ring) < 20:
        return 0.0, None
    med = np.median(ring, axis=0)
    share = float((np.abs(ring - med).max(axis=1) <= tol).mean())
    return share, med


def pb_glyphs(rgb: np.ndarray, box, ground, ink_min: int):
    """Ink components inside a word box: [(x0, y0, x1, y1, area)] in image pixels, left to right. Ink = pixels at
    least half as far from the ground as the strongest ink in the box (and at least ink_min levels)."""
    import cv2
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    pad_y = max(2, (y1 - y0) // 3)
    X0, Y0, X1, Y1 = max(0, x0 - 2), max(0, y0 - pad_y), min(w, x1 + 2), min(h, y1 + pad_y)
    crop = rgb[Y0:Y1, X0:X1].astype(int)
    diff = np.abs(crop - ground).max(axis=2)
    if diff.max() < ink_min:
        return []
    ink = (diff >= max(ink_min, 0.5 * diff.max())).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, ww, hh, area = st[i]
        out.append((X0 + x, Y0 + y, X0 + x + ww, Y0 + y + hh, int(area)))
    return sorted(out)


@functools.lru_cache(maxsize=16)
def pb_words(key: str, photo_bytes: bytes, shape: tuple):
    """Every word Tesseract reads (conf 60 or more) on the image and on a contrast-stretched copy (light grey type
    becomes dark; photographs blanked), at 2x with sparse and automatic layout and at 1x sparse."""
    import cv2
    from PIL import ImageOps
    rgb = np.asarray(Image.open(key).convert('RGB'))
    photo = np.unpackbits(np.frombuffer(photo_bytes, np.uint8))[:shape[0] * shape[1]].reshape(shape).astype(bool)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    bg = cv2.medianBlur(gray, 31)
    stretched = 255 - np.clip(np.abs(gray.astype(int) - bg.astype(int)) * 4, 0, 255).astype(np.uint8)
    stretched[photo] = 255
    words = []
    for k, src in enumerate((Image.fromarray(rgb), Image.fromarray(stretched).convert('RGB'))):
        for scale, psm in ((2, 11), (2, 3), (1, 11)):
            im = src if scale == 1 else src.resize((src.width * scale, src.height * scale), Image.LANCZOS)
            g = ImageOps.grayscale(im)
            for cand in (g, ImageOps.invert(g)):
                for w in base._tesseract(cand, psm, scale):
                    if k and w['conf'] < base.OCR_GOOD_CONF:
                        continue                       # the stretched copy turns texture into low-confidence noise
                    if not any(base._overlap(w['bbox'], o['bbox']) > 0.5 and w['text'] == o['text'] for o in words):
                        words.append(w)
    return words


@functools.lru_cache(maxsize=16)
def pb_photo_mask_cached(key: str, ground_share: float, min_area: float):
    import cv2
    rgb = np.asarray(Image.open(key).convert('RGB')).astype(np.int16)
    h, w = rgb.shape[:2]
    q = (rgb // 4).reshape(-1, 3)
    values, counts = np.unique(q, axis=0, return_counts=True)
    grounds = values[counts >= ground_share * h * w]
    designed = np.zeros((h, w), bool)
    for v in grounds:
        designed |= (np.abs(rgb // 4 - v).max(axis=2) <= 1)
    other = cv2.morphologyEx((~designed).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(other, connectivity=8)
    photo = np.zeros((h, w), bool)
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if area >= min_area * h * w:
            photo[y:y + bh, x:x + bw] = True       # the photograph's whole frame
    return photo


def pb_photo_mask(path: Path, a):
    """Photographs: every large area whose pixels are not one of the image's ground colours (a colour, to 4 levels,
    covering `ground_share` of the image or more, default 0.03), closed over small gaps; an area of `photo_area`
    (default 0.02 of the image) or more is a photograph and its whole bounding box is masked. Type never covers
    that much; a photograph's smooth parts (a watch dial, a studio backdrop) fall inside its box."""
    return pb_photo_mask_cached(str(path), a.get('ground_share', 0.03), a.get('photo_area', 0.02))


def pb_unread(rgb, photo, words, a):
    """Text-like ink outside photographs that no confidently read word covers: [(x0, y0, x1, y1)]. Ink = pixels that
    are not flat (letter edges), merged into words; straight edges of panels and rules are left out."""
    import cv2
    import objective_ops_r3 as r3
    ink = ~r3._flat(rgb.astype(np.int16), a.get('flat_tol', 3)) & ~photo
    ink[:2, :] = ink[-2:, :] = False
    ink[:, :2] = ink[:, -2:] = False                 # the image's own edge is not ink
    merged = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 15), np.uint8))
    n, labels, st, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    covered = np.zeros(photo.shape, bool)
    for w in words:
        if w['conf'] >= a.get('min_conf', base.OCR_GOOD_CONF):
            x0, y0, x1, y1 = (int(round(v)) for v in w['bbox'])
            covered[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = True
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        if bh < a.get('min_px', 8) or bw < 4 or bh <= 4 or (bw > 40 * bh and bh < 6) or (bh > 40 * bw and bw < 6):
            continue                                   # specks, hairline rules and panel edges carry no figure
        if bh > a.get('max_text', 0.15) * photo.shape[0] or area < 0.05 * bw * bh:
            continue                                   # frame outlines and panel borders, taller than any type here
        part = labels[y:y + bh, x:x + bw] == i
        if covered[y:y + bh, x:x + bw][part].mean() < 0.8:
            out.append((int(x), int(y), int(x + bw), int(y + bh)))
    return out


def pb_word_figures(rgb, word, a):
    """Measure one OCR word holding figures: list of (char, height, bottom) for its capitals and figures, or a reason."""
    text = word['text']
    flat, ground = pb_ring_flat(rgb, word['bbox'], a.get('ring_px', 4), a.get('ground_tol', 14))
    if ground is None or flat < a.get('flat_ring', 0.85):
        return None, 'ground'
    comps = pb_glyphs(rgb, word['bbox'], ground, a.get('ink_min', 20))
    if not comps:
        return None, f'{text}: no ink found'
    # pieces one above the other (a figure's flag, a letter's dot) are one glyph: merge pieces whose horizontal
    # ranges overlap by more than half the narrower one
    merged = []
    for c in comps:
        for i, m in enumerate(merged):
            ov = min(c[2], m[2]) - max(c[0], m[0])
            if ov > 0.5 * min(c[2] - c[0], m[2] - m[0]):
                merged[i] = (min(c[0], m[0]), min(c[1], m[1]), max(c[2], m[2]), max(c[3], m[3]), c[4] + m[4])
                break
        else:
            merged.append(c)
    comps = sorted(merged)
    top_h = max(c[3] - c[1] for c in comps)
    # letters and figures are the glyphs at least 35% of the tallest; hyphens, commas and specks are not
    keep = [c for c in comps if (c[3] - c[1]) >= 0.35 * top_h]
    chars = [ch for ch in text if ch.isalnum() or ch in '/&%$#@?!()[]{}|\\']
    if len(keep) != len(chars):
        return None, f'{text}: {len(keep)} glyphs found for {len(chars)} characters'
    out = []
    for ch, c in zip(chars, keep):
        if ch.isdigit() or (ch.isupper() and ch not in 'QJ'):
            out.append((ch, c[3] - c[1], c[3]))
    return out, None


def pb_pdf_figures(path: Path, a):
    """Every figure in a PDF: [(glyph, height_em, drop_em)] from the rendered glyph ink, or (None, reason)."""
    out = []
    chars = r2._pdf_chars(str(path))
    for c in chars:
        if not c['c'].isdigit():
            continue
        ink = r2._ink_rows(str(path), c['page'], c['bbox'])
        if ink is None:
            return None, f'figure {c["c"]} could not be measured'
        top, bottom = ink
        base_y = c['origin'][1]
        out.append((c, (base_y - top) / c['size'], (bottom - base_y) / c['size']))
    return out, None


def op_lining_r4t(path, a):
    """Every figure is a lining figure at full capital height, none dropping below the baseline.
    PDF: every digit glyph's ink is measured (rendered at 600 dpi) against its own baseline; the tallest figure of
    each font and size sets the figure height. Images: every OCR word holding a figure on a flat ground (the ring of
    `ring_px` pixels around it matches one colour within `ground_tol` on at least `flat_ring` of its pixels) is split
    into ink components (pixels at least half as far from the ground as its strongest ink, and at least `ink_min`
    levels; pieces one above the other are merged into one glyph); each figure is compared with the tallest capital
    or figure of its word and with their median bottom. A figure within `pass_tol` (default 0.06 of that height, at
    least 1 px) of the height and the baseline passes; one shorter than `fail_short` (default 0.85) of the height or
    dropping more than `fail_drop` (default 0.12) below the baseline is an old-style figure and fails; between them a
    person decides. Images: words are read on the image and on a contrast-stretched copy (light grey type made dark);
    figures inside a photograph (see pb_photo_mask: `ground_share`, `photo_area`) belong to the pictured product,
    such as a watch dial, and are left out, but one taller than `photo_digit_max` (default 0.03 of the image height) read
    confidently there may be type set over the photograph and goes to a person. A pass also needs every figure word
    read at `min_conf` (default 80) or more, figures at least `min_px` (default 8) pixels tall, and every piece of
    text-like ink outside the photographs (non-flat pixels at `flat_tol`, default 3, merged into words; pieces
    shorter than `min_px` or taller than `max_text`, default 0.15 of the image height, and outlines are left out)
    covered by a confidently read word: unread type could hold a figure."""
    path = Path(path)
    pass_tol, fail_short, fail_drop = a.get('pass_tol', 0.06), a.get('fail_short', 0.85), a.get('fail_drop', 0.12)
    if path.suffix.lower() == '.pdf':
        figs, why = pb_pdf_figures(path, a)
        if figs is None:
            return PERSON, {'reason': why}
        if not figs:
            return 'pass', {'reason': 'no figures in the PDF text'}
        groups = {}
        for c, h, d in figs:
            groups.setdefault((c['font'], round(c['size'], 2)), []).append((c, h, d))
        bad, unsure = [], []
        for (font, size), fs in groups.items():
            top = max(h for _, h, _ in fs)
            for c, h, d in fs:
                if h < fail_short * top or d > fail_drop:
                    bad.append((c['c'], font, size, round(h / top, 2), round(d, 3)))
                elif h < (1 - pass_tol) * top or d > pass_tol:
                    unsure.append((c['c'], font, size, round(h / top, 2), round(d, 3)))
        ev = {'figures': len(figs), 'fonts': sorted({f for f, _ in groups})}
        if bad:
            return 'fail', dict(ev, old_style=bad[:6])
        if unsure:
            return PERSON, dict(ev, reason='a figure is slightly short or low', figures_unsure=unsure[:6])
        return 'pass', ev
    if path.suffix.lower() not in PB_IMAGES:
        return PERSON, {'reason': 'figures are read on PDFs and images'}
    rgb = np.asarray(Image.open(path).convert('RGB'))
    H = rgb.shape[0]
    photo = pb_photo_mask(path, a)
    words = pb_words(str(path), np.packbits(photo).tobytes(), photo.shape)
    measured, bad, unsure, in_photo = [], [], [], []
    for w in words:
        if not re.search(r'\d', w['text']):
            continue
        x0, y0, x1, y1 = w['bbox']
        hgt = y1 - y0
        cy, cx = int((y0 + y1) / 2), int((x0 + x1) / 2)
        if photo[min(H - 1, max(0, cy)), min(rgb.shape[1] - 1, max(0, cx))]:
            if hgt >= a.get('photo_digit_max', 0.03) * H and w['conf'] >= base.OCR_GOOD_CONF:
                return PERSON, {'reason': f'figures set over a photograph: {w["text"]}'}
            in_photo.append(w['text'])
            continue
        if w['conf'] < a.get('min_conf', base.OCR_GOOD_CONF):
            if any(o['conf'] >= a.get('min_conf', base.OCR_GOOD_CONF) and base._overlap(o['bbox'], w['bbox']) > 0.5
                   and re.sub(r'\D', '', o['text']) == re.sub(r'\D', '', w['text']) for o in words):
                continue                               # another pass read the same figures confidently
            return PERSON, {'reason': f'figures read without confidence: {w["text"]}'}
        figs, why = pb_word_figures(rgb, w, a)
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
    ev = {'measured': sorted(set(measured))[:12], 'left_as_photo_detail': in_photo[:8]}
    if bad:
        return 'fail', dict(ev, old_style=bad[:6])
    if unsure:
        return PERSON, dict(ev, reason='a figure is slightly short or low', figures_unsure=unsure[:6])
    unread = pb_unread(rgb, photo, words, a)
    if unread:
        return PERSON, dict(ev, reason='text outside the photographs that was not read confidently may hold a figure',
                            unread_boxes=unread[:6])
    if not measured:
        return PERSON, dict(ev, reason='no typeset figure found')
    return 'pass', ev


_OPS_B = {
    'v2_lining_r4t': op_lining_r4t,
}


# ---------------------------------------------------------------- part L12
import functools
from itertools import combinations
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import objective_ops as base
import ops_r3_fonts as rf
from objective_ops import PERSON, canon

L12_REF = 400.0                 # px per em of the glyph renders the letter centres are taken from
L12_DEFAULTS = dict(max_rms=0.6, min_letters=8, touch_spread=5.0,
                    pass_if=[['difference', '>=', 15]], fail_if=[['difference', '<=', 0]])
L12_CMP = {'>=': lambda x, v: x >= v, '>': lambda x, v: x > v, '<=': lambda x, v: x <= v, '<': lambda x, v: x < v}


def l12_holds(stats, conds):
    """Every [stat, comparison, value] in conds holds for the stats."""
    return all(L12_CMP[c](stats[k], v) for k, c, v in conds)


def l12_key(text: str) -> str:
    return re.sub(r'\s+', ' ', canon(text, False)).strip()


@functools.lru_cache(maxsize=4096)
def l12_glyph(face, ch: str):
    """(advance, (ink centre, left edge, right edge)) of one character in em, measured from the pen position on a
    large render: the centre weighted by ink coverage, the edges where the column's ink first and last reaches half
    coverage (the same measures as on the image)."""
    f = rf.pil_font(face, L12_REF)
    adv = f.getlength(ch) / L12_REF
    if not ch.strip():
        return adv, None
    pad = int(L12_REF)
    im = Image.new('L', (int(L12_REF * 3), int(L12_REF * 2)), 0)
    ImageDraw.Draw(im).text((pad, int(L12_REF * 1.4)), ch, font=f, fill=255, anchor='ls')
    a = np.asarray(im, float) / 255.0
    col = a.sum(axis=0)
    if col.sum() <= 0:
        return adv, None
    cx = float((np.arange(a.shape[1]) * col).sum() / col.sum())
    lo, hi = l12_edges(a.max(axis=0))
    return adv, tuple((v - pad) / L12_REF for v in (cx, lo, hi))


def l12_edges(prof):
    """Left and right x where a column-coverage profile first and last reaches one half (linear interpolation)."""
    idx = np.nonzero(prof >= 0.5)[0]
    i, j = int(idx[0]), int(idx[-1])
    lo = i - 0.5 if i == 0 else i - 1 + (0.5 - prof[i - 1]) / max(prof[i] - prof[i - 1], 1e-6)
    hi = j + 0.5 if j == len(prof) - 1 else j + (prof[j] - 0.5) / max(prof[j] - prof[j + 1], 1e-6)
    return float(lo) + 0.5, float(hi) + 0.5


def l12_faces(fonts):
    """Candidate faces from [[family, [weight names or numbers]], ...]."""
    out = []
    for fam, weights in fonts:
        ws = None if not weights else [w if isinstance(w, int) else rf.WEIGHT_NAMES[str(w).lower().replace(' ', '')]
                                       for w in weights]
        out += rf.brand_faces(fam, ws)
    return out


def l12_line(layer, text):
    """The OCR line that reads exactly `text` (letter case and spacing aside), or None."""
    want = l12_key(text)
    hits = [l for l in layer.lines if l12_key(l.text) == want]
    return hits[0] if len(hits) == 1 else None


def l12_letters(rgb, bbox):
    """Ink centres (x, in image px) of the letters inside a line box, left to right: ink measured against the
    line's ground (commonest grey round the box), blobs overlapping across x merged (a colon, an i or a j counts
    once), each centre weighted by ink coverage. Returns (centres, reason)."""
    import cv2
    gray = np.asarray(Image.fromarray(rgb).convert('L'), float)
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    h = y1 - y0
    X0, X1 = max(0, x0 - 4), min(gray.shape[1], x1 + 4)
    Y0, Y1 = max(0, y0 - 2), min(gray.shape[0], y1 + 2)
    crop = gray[Y0:Y1, X0:X1]
    if crop.size == 0 or h < 6:
        return None, 'line too small to measure'
    ring = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    ground = float(np.median(ring))
    ink = np.abs(crop - ground)
    top = float(np.percentile(ink, 99.5))
    if top < 60:
        return None, 'too little contrast between the letters and their ground'
    cov = np.clip(ink / top, 0, 1)
    mask = (cov >= 0.5).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = [i for i in range(1, n) if stats[i][cv2.CC_STAT_AREA] >= 3]
    if any(stats[i][cv2.CC_STAT_TOP] == 0 and stats[i][cv2.CC_STAT_TOP] + stats[i][cv2.CC_STAT_HEIGHT] >= mask.shape[0]
           for i in comps):
        return None, 'a shape runs through the whole line height (not letters on a plain ground)'
    comps.sort(key=lambda i: stats[i][cv2.CC_STAT_LEFT])
    groups = []
    for i in comps:
        l, w = stats[i][cv2.CC_STAT_LEFT], stats[i][cv2.CC_STAT_WIDTH]
        if groups and l < groups[-1][1]:            # overlaps the previous blob across x: the same letter
            groups[-1][1] = max(groups[-1][1], l + w)
            groups[-1][2].append(i)
        else:
            groups.append([l, l + w, [i]])
    centres = []
    for l, r, ids in groups:
        m = np.isin(lab, ids).astype(np.uint8)
        m = cv2.dilate(m, np.ones((3, 3), np.uint8))
        wgt = cov * m
        col = wgt.sum(axis=0)
        lo, hi = l12_edges(wgt.max(axis=0))
        centres.append(tuple(X0 + v for v in (float((np.arange(len(col)) * col).sum() / col.sum()), lo, hi)))
    return centres, None


def l12_glyphs(text, face):
    """[(pen position, (centre, left, right), index in the text)] of the text's visible characters, in em."""
    out, pen = [], 0.0
    for i, ch in enumerate(text):
        adv, g = l12_glyph(face, ch)
        if g is not None:
            out.append((pen, g, i))
        pen += adv
    return out


def l12_assignments(text, glyphs, n_shapes, most=2):
    """Ways the text's letters map onto n_shapes ink shapes, left to right: one to one, or (where letters touch) up to
    `most` pairs of neighbouring letters of one word sharing a shape. [[(first, last) glyph index per shape]]."""
    d = len(glyphs) - n_shapes
    if d == 0:
        return [[(k, k) for k in range(n_shapes)]]
    if d < 0 or d > most:
        return []
    pairs = [k for k in range(len(glyphs) - 1) if glyphs[k + 1][2] == glyphs[k][2] + 1]
    out = []
    for starts in combinations(pairs, d):
        if any(b - a < 2 for a, b in zip(starts, starts[1:])):
            continue
        ranges, k = [], 0
        while k < len(glyphs):
            if k in starts:
                ranges.append((k, k + 1))
                k += 2
            else:
                ranges.append((k, k))
                k += 1
        out.append(ranges)
    return out


def l12_fit(shapes, glyphs, assign):
    """Least-squares fit of each shape's ink centre and left and right edges to the font: x = start + size x (advance
    sum + the letter's own centre or edge) + spacing x letter index (the edges pin the size, which the spacing could
    otherwise trade against); a shape two touching letters share gives its left and right edges only. Returns
    (tracking in thousandths of an em, rms miss in px, size in px per em) or None."""
    rows, y = [], []
    for (j0, j1), meas in zip(assign, shapes):
        p0, g0, i0 = glyphs[j0]
        p1, g1, i1 = glyphs[j1]
        if j0 == j1:
            for v, m in zip(g0, meas):
                rows.append((1.0, p0 + v, i0))
                y.append(m)
        else:
            rows += [(1.0, p0 + g0[1], i0), (1.0, p1 + g1[2], i1)]
            y += [meas[1], meas[2]]
    A, y = np.array(rows), np.array(y)
    sol, *_ = np.linalg.lstsq(A, y, rcond=None)
    _, size, b = sol
    if size <= 0:
        return None
    rms = float(np.sqrt(np.mean((A @ sol - y) ** 2)))
    return 1000.0 * b / size, rms, float(size)


def l12_tracking(rgb, layer, text, fonts, a):
    """(tracking, evidence) of the line reading `text`, in its best-fitting candidate face; (None, reason)."""
    line = l12_line(layer, text)
    if line is None:
        return None, f'line not read exactly: {text}'
    if line.conf < base.OCR_GOOD_CONF:
        return None, f'line read below {base.OCR_GOOD_CONF}% confidence: {text}'
    centres, why = l12_letters(rgb, line.bbox)
    if centres is None:
        return None, f'{text}: {why}'
    letters = len(re.sub(r'\s', '', text))
    if letters < a['min_letters']:
        return None, f'{text}: too few letters to fit the spacing'
    if not (0 <= letters - len(centres) <= 2):
        return None, f'{text}: {len(centres)} letter shapes for {letters} letters (letters broken apart or run together)'
    fits = []
    for face in l12_faces(fonts):
        glyphs = l12_glyphs(text, face)
        if len(glyphs) != letters:
            continue
        for assign in l12_assignments(text, glyphs, len(centres)):
            r = l12_fit(centres, glyphs, assign)
            if r:
                fits.append((r[1], r[0], r[2], f'{face.family} {face.weight}', len(assign)))
    if not fits:
        return None, f'{text}: no candidate font to fit'
    fits.sort()
    rms, t, size, label, _ = fits[0]
    if rms > a['max_rms']:
        return None, f'{text}: letter positions do not fit the expected font closely (miss {rms:.2f} px)'
    if len(centres) < letters:
        # touching letters: every pairing (in the best face) that fits nearly as well must agree on the spacing
        near = [f[1] for f in fits if f[3] == label and f[0] <= max(1.5 * rms, rms + 0.1)]
        if max(near) - min(near) > a['touch_spread']:
            return None, f'{text}: letters touch and the ways of pairing them disagree on the spacing'
    return t, {'text': text, 'tracking': round(t, 1), 'font': label, 'miss_px': round(rms, 2), 'px_per_em': round(size, 1),
               'touching_pairs': letters - len(centres)}


def l12_op_track_vs_r4t(path, a):
    """Line a is letterspaced more open than line b, on an image. Each line is found by OCR reading its expected
    text exactly (letter case and spacing aside, at 80% confidence or more); its letters are separated as ink blobs
    (blobs overlapping across x count as one letter, so a colon or an i counts once) and each letter's ink centre is
    taken, weighted by ink coverage. The centres are fitted by least squares to the expected font's own advance
    widths and letter centres (centre = start + size x (advance sum + letter centre) + spacing x letter index, the
    way a PDF's character spacing adds to every advance), in each candidate face (fonts_a, fonts_b: [family,
    [weights]]); the face that fits best is used and its spacing read in thousandths of an em.
    Settings: a, b {'text': the line's exact text}; fonts_a, fonts_b; max_rms (px, default 0.6): a best fit whose
    letter centres miss by more than this on average is not trusted (person); min_letters (default 8): fewer letters
    in a line go to a person; pass_if (default [['difference', '>=', 15]]) and fail_if (default [['difference', '<=',
    0]]): difference = a's spacing minus b's, in thousandths of an em; a passes reading at least 15 more open, fails
    reading no more open, and anything between goes to a person (the measuring error on made files was at most 4). Where up to two pairs of neighbouring letters touch
    (fewer ink shapes than letters), every pairing is fitted; the pairings that fit within 1.5 times the best miss must
    agree on the spacing within touch_spread (thousandths of an em, default 5), else a person decides. More shapes
    than letters (letters broken apart) goes to a person."""
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        return PERSON, {'reason': 'spacing is read on images only'}
    s = dict(L12_DEFAULTS, **{k: a[k] for k in L12_DEFAULTS if k in a})
    rgb, layer = rf._page(str(path), -1)
    ta, ea = l12_tracking(rgb, layer, a['a']['text'], a['fonts_a'], s)
    tb, eb = l12_tracking(rgb, layer, a['b']['text'], a['fonts_b'], s)
    if ta is None or tb is None:
        return PERSON, {'reason': ea if ta is None else eb}
    diff = ta - tb
    ev = {'a': ea, 'b': eb, 'difference': round(diff, 1)}
    if l12_holds({'difference': diff}, s['pass_if']):
        return 'pass', ev
    if l12_holds({'difference': diff}, s['fail_if']):
        return 'fail', dict(ev, reason='not letterspaced more open')
    return PERSON, dict(ev, reason='spacing difference too small to call')


_OPS_L12 = {'v2_track_vs_r4t': l12_op_track_vs_r4t}


OPS = {**_OPS_A, **_OPS_B, **_OPS_L12}
