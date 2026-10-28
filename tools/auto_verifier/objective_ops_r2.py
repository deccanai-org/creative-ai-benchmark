"""Round 2 of the deterministic checks moved from human review (pilot-13 v2, 2026-10-28).

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person", and
nothing passes on a failed read. These operations read layout: which value belongs to which name (a rate to its
house and season, a date to its act), the colour behind text, where a mark sits against a photo, letter spacing,
page and artwork sizes, and which supplied picture a deliverable is built from.
"""
from __future__ import annotations

import functools
import io
import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

import objective_ops as base
from objective_ops import PERSON, OCR_GOOD_CONF, canon, contains, merged, text_layers

PT_MM = 25.4 / 72
GROUND_DPI = 100

# ---------------------------------------------------------------- shared helpers


def _rx(item) -> str:
    """A plain text becomes an exact, word-bounded, case-insensitive pattern; a pattern stays as it is."""
    if isinstance(item, dict):
        return item['regex']
    return r'(?<![\w])' + re.escape(canon(item, False)).replace(r'\ ', r'\s+') + r'(?![\w])'


def _has(text: str, item) -> bool:
    """The text carries the item. Letter-spaced type ("O A T M E A L  M U G", as PDFs extract tracked type)
    also counts for a name of six letters or more, compared with spaces removed."""
    if isinstance(item, dict):
        return re.search(item['regex'], canon(text), re.I) is not None
    if re.search(_rx(item), canon(text, False), re.I):
        return True
    flat = base.squash(canon(item, False))
    return len(flat) >= 6 and flat in base.squash(canon(text, False))


def _rxs(pattern: str, text: str) -> bool:
    """A pattern found in the line, or in the line with spaces removed (tracked type extracts as "F R I 2 5 S E P")."""
    return bool(re.search(pattern, canon(text), re.I) or re.search(pattern, base.squash(canon(text)), re.I))


def _whole(line_text: str, names) -> bool:
    """The line reads one of the names and nothing else (punctuation, letter case and letter spacing aside)."""
    bare = re.sub(r'[^0-9a-z]+', ' ', canon(line_text, False)).strip()
    for n in names:
        target = re.sub(r'[^0-9a-z]+', ' ', canon(n, False)).strip()
        if bare == target or bare.replace(' ', '') == target.replace(' ', ''):
            return True
    return False


def _xoverlap(a, b, slack=0.0) -> bool:
    return min(a[2], b[2]) - max(a[0], b[0]) > -slack


def _cy(b):
    return (b[1] + b[3]) / 2


def _reliable(layer) -> bool:
    """Live PDF text, or an OCR read clear enough to support an absence."""
    return layer.source == 'pdf' or getattr(layer, 'confident_all', layer.confident)


def _line_ok(line) -> bool:
    return line.source == 'pdf' or line.conf >= OCR_GOOD_CONF


def _layer(path: Path, frame: str | None = None):
    if frame == 'last' and path.suffix.lower() == '.mp4':
        return merged(text_layers(path)[-1:])
    return merged(text_layers(path))


# ---------------------------------------------------------------- which value belongs to which name


def _governing(cand, anchors, max_dy=None):
    """The anchor a value line belongs to: on its page, starting no lower than the value; one standing over it
    (sharing some width) wins over one beside it (a table's row name); the nearest wins among either kind."""
    pool = [a for a in anchors if a.page == cand.page and a.bbox[1] <= cand.bbox[1] + 2 and a is not cand]
    if max_dy is not None:
        pool = [a for a in pool if cand.bbox[1] - a.bbox[3] <= max_dy]
    over = [a for a in pool if _xoverlap(a.bbox, cand.bbox)]
    pick = over or pool
    return max(pick, key=lambda a: (a.bbox[1], -abs(a.bbox[0] - cand.bbox[0])), default=None)


def _nearest(anchor, lines, direction, max_gap=None):
    """The nearest line above or below the anchor that shares some of its width, on the same page."""
    pool = []
    for l in lines:
        if l is anchor or l.page != anchor.page or not _xoverlap(l.bbox, anchor.bbox):
            continue
        if direction == 'below' and l.bbox[1] >= anchor.bbox[1] + 0.5 * (anchor.bbox[3] - anchor.bbox[1]):
            gap = l.bbox[1] - anchor.bbox[3]
        elif direction == 'above' and l.bbox[3] <= anchor.bbox[3] - 0.5 * (anchor.bbox[3] - anchor.bbox[1]):
            gap = anchor.bbox[1] - l.bbox[3]
        else:
            continue
        if max_gap is None or gap <= max_gap:
            pool.append((gap, l))
    return min(pool, key=lambda p: p[0])[1] if pool else None


def op_paired(path, a):
    """A value stands with its name: a rate with its house and season, a date with its act, a caliber with its
    reference, a figure with its chart label.

    anchor/rivals: the name and the other names of its kind (house names, act names), as whole lines.
    kind: a pattern for every value of this field; value: the expected value (one of several patterns).
    where: "section" (the value's governing name is the anchor; with label, the value also stands under the label
    in the same column), "above" / "below" (the nearest value line directly above / below the anchor), "beside" (on
    the anchor's line, or the line directly above or below it).
    optional: the anchor not being shown is a pass; empty_ok: no value of the kind with the anchor is a pass.
    """
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    lines = [l for l in layer.lines if base._real(l)] if layer.source == 'ocr' else layer.lines
    names = a['anchor'] if isinstance(a['anchor'], list) else [a['anchor']]
    whole = a.get('whole_line', True)
    hit = (lambda l: _whole(l.text, names)) if whole else (lambda l: any(_has(l.text, n) for n in names))
    anchors = [l for l in lines if hit(l)]
    if not anchors:
        if a.get('optional') and _reliable(layer):
            return 'pass', {'reason': 'name not shown (the check applies only where it appears)'}
        return PERSON, {'reason': f'name not found: {names[0]}'}
    kind = [l for l in lines if _rxs(a['kind'], l.text)]
    expected = a['value'] if isinstance(a['value'], list) else [a['value']]
    good = lambda l: any(_rxs(_rx(v), l.text) for v in expected)
    found = []
    if a['where'] == 'section':
        rivals = [l for l in lines if _whole(l.text, names + a.get('rivals', []))]
        labels = [l for l in lines if _whole(l.text, a['label'] + a.get('label_rivals', []))] if a.get('label') else []
        for c in kind:
            owner = _governing(c, rivals)
            if owner is None or owner not in anchors:
                continue
            if a.get('label'):
                col = _nearest(c, labels, 'above')
                if col is None or not _whole(col.text, a['label']):
                    continue
            found.append(c)
    elif a['where'] in ('above', 'below'):
        for an in anchors:
            l = _nearest(an, kind, a['where'], a.get('max_gap'))
            if l is not None:
                found.append(l)
    elif a['where'] == 'column':
        for an in anchors:
            ups = _nearest(an, kind, 'above', a.get('max_gap'))
            downs = _nearest(an, kind, 'below', a.get('max_gap'))
            pick = [l for l in (ups, downs) if l is not None]
            if pick:
                found.append(min(pick, key=lambda l: abs(_cy(l.bbox) - _cy(an.bbox))))
    elif a['where'] == 'above_or_same':
        for an in anchors:
            l = an if an in kind else _nearest(an, kind, 'above', a.get('max_gap'))
            if l is not None:
                found.append(l)
    else:                                                   # beside
        for an in anchors:
            h = an.bbox[3] - an.bbox[1]
            if an in kind:
                found.append(an)
                continue
            row = [l for l in kind if l.page == an.page and abs(_cy(l.bbox) - _cy(an.bbox)) <= 0.6 * h]
            # on the anchor's row, the nearest value to its right (a table's own column), else to its left
            right = [l for l in row if l.bbox[0] >= an.bbox[2] - 2]
            left = [l for l in row if l.bbox[2] <= an.bbox[0] + 2]
            if right:
                found.append(min(right, key=lambda l: l.bbox[0]))
            elif left:
                found.append(max(left, key=lambda l: l.bbox[2]))
            for direction in ('above', 'below'):
                l = _nearest(an, kind, direction, 1.2 * h)
                if l is not None:
                    found.append(l)
    found = list(dict.fromkeys(found))
    if not found:
        if a.get('empty_ok') and _reliable(layer):
            return 'pass', {'reason': 'no value of this kind stands with the name'}
        return PERSON, {'reason': 'no value found with the name', 'name': names[0]}
    right = [l.text for l in found if good(l)]
    wrong = [l for l in found if not good(l)]
    if a.get('empty_ok'):
        # "any value beside the name is X": every value with the name must be the expected one
        if not wrong:
            return 'pass', {'found': right}
        if any(not _line_ok(l) for l in wrong):
            return PERSON, {'reason': 'a different value read with low confidence', 'read': [l.text for l in wrong]}
        return 'fail', {'wrong': [l.text for l in wrong], 'name': names[0]}
    if right:
        return 'pass', {'found': right}
    if layer.source == 'ocr' and (not all(_line_ok(l) for l in found) or
                                   any(base.near_miss(l.text, v) >= base.NEAR_MISS for l in found for v in expected if not isinstance(v, dict))):
        return PERSON, {'reason': 'value with the name not read clearly', 'read': [l.text for l in found]}
    return 'fail', {'wrong': [l.text for l in found], 'name': names[0]}


def op_followed_by(path, a):
    """Text A is followed directly by text B: later on the same line, or on the next line below it."""
    layer = _layer(path)
    lines = layer.lines
    for i, l in enumerate(lines):
        if not contains(l.text, a['a'], False):
            continue
        rest = canon(l.text, False).split(canon(a['a'], False), 1)[1]
        if contains(rest, a['b'], False):
            return 'pass', {'line': l.text}
        nxt = _next_line(lines, l)
        if nxt is not None and contains(nxt.text, a['b'], False):
            return 'pass', {'next_line': nxt.text}
        if nxt is not None and layer.source == 'pdf':
            return 'fail', {'a': l.text, 'next_line': nxt.text}
    span = base._span(layer, a['a'])
    if span:
        nxt = _next_line(lines, span[-1])
        if nxt is not None and contains(nxt.text, a['b'], False):
            return 'pass', {'next_line': nxt.text}
    return PERSON, {'reason': f'not found: {a["a"]}'}


def _next_line(lines, line):
    """The line read next after this one: the nearest line below it on the same page that shares some width."""
    return _nearest(line, [l for l in lines if l.text.strip()], 'below')


# ---------------------------------------------------------------- the colour behind text (PDF)


@functools.lru_cache(maxsize=16)
def _page_pixels(key: str, page: int):
    import pymupdf
    doc = pymupdf.open(key)
    pix = doc[page].get_pixmap(dpi=GROUND_DPI)
    arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].astype(int)
    return arr


@functools.lru_cache(maxsize=16)
def _pdf_spans(key: str):
    """Every text span: text, bbox (pt), font, size, colour, page."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip():
                        out.append(dict(text=s['text'], bbox=tuple(s['bbox']), font=s['font'], size=s['size'],
                                        color=base._hex(s['color']), page=page.number, line=tuple(l['bbox'])))
    return out


@functools.lru_cache(maxsize=16)
def _pdf_images(key: str):
    import pymupdf
    return {p.number: [tuple(i['bbox']) for i in p.get_image_info()] for p in pymupdf.open(key)}


def _rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)])


def _ground(key: str, page: int, bbox, text_hex: str):
    """The colour behind a span: the commonest colour of its box once its own letters are left out.
    Returns a hex, "photo" (over a placed image), or "mixed" (no single colour)."""
    arr = _page_pixels(key, page)
    s = GROUND_DPI / 72
    x0, y0, x1, y1 = (int(round(v * s)) for v in bbox)
    pad = 2
    crop = arr[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad].reshape(-1, 3)
    if not len(crop):
        return 'mixed'
    rest = crop[np.abs(crop - _rgb(text_hex)).sum(axis=1) > 45]          # the letters' own pixels left out; low contrast kept
    over = [i for i in _pdf_images(key).get(page, []) if base._overlap(i, bbox) > 0.3]
    if len(rest) < 12:
        return 'photo' if over else text_hex
    values, counts = np.unique(rest // 4, axis=0, return_counts=True)
    mode = values[counts.argmax()] * 4
    share = (np.abs(rest - mode).max(axis=1) <= 8).mean()
    if over and share < 0.9:
        return 'photo'
    if share < 0.5:
        return 'mixed'
    near = rest[np.abs(rest - mode).max(axis=1) <= 8].mean(axis=0)
    return '#%02X%02X%02X' % tuple(int(round(v)) for v in near)


def _spans_for(key, a):
    """Spans a colour or ground check is about: named texts, pattern lines, or all text except named ones."""
    spans = _pdf_spans(key)
    picks = []
    for s in spans:
        line_text = s['text']
        if a.get('texts') and any(_has(line_text, t) or (len(canon(line_text).strip()) >= 3 and canon(line_text, False).strip() in canon(t, False))
                                  for t in a['texts']):
            picks.append(s)
        elif a.get('patterns') and any(re.search(p, canon(line_text), re.I) or re.search(p, base.squash(canon(line_text)), re.I) for p in a['patterns']):
            picks.append(s)
        elif a.get('all_text'):
            if any(_has(line_text, e) for e in a.get('except', [])):
                continue
            if any(re.search(p, canon(line_text), re.I) for p in a.get('except_patterns', [])):
                continue
            picks.append(s)
    return picks


def op_text_on_ground(path, a):
    """Type on the named grounds is in the allowed colours (grounds: hexes, or "photo" for type over a placed
    photograph); or, with ground_must, the selected type sits on one of those grounds."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'the colour behind type is read from a PDF'}
    key = str(path)
    picks = _spans_for(key, a)
    if not picks:
        if a.get('optional', True):
            return 'pass', {'reason': 'no such type (the check applies only where it appears)'}
        return PERSON, {'reason': 'type not found'}
    bad, unsure, checked = [], [], 0
    import pymupdf
    heights = {p.number: p.rect.height for p in pymupdf.open(key)}
    for s in picks:
        if a.get('foot_ok') and base._near_hex(s['color'], a['foot_ok'], 2) and s['bbox'][1] > 0.9 * heights[s['page']]:
            continue                                       # a running foot allowed in its own colour
        g = _ground(key, s['page'], s['bbox'], s['color'])
        if a.get('ground_must'):
            checked += 1
            if g in ('photo', 'mixed') or not base._near_hex(g, a['ground_must'], 6):
                (unsure if g == 'mixed' else bad).append((s['text'], g))
            continue
        on = (g == 'photo' and 'photo' in a['grounds']) or (g not in ('photo', 'mixed') and base._near_hex(g, [h for h in a['grounds'] if h != 'photo'], 6))
        if g == 'mixed' and 'photo' in a['grounds'] and any(base._overlap(i, s['bbox']) > 0.3 for i in _pdf_images(key).get(s['page'], [])):
            on = True
        if not on:
            continue
        checked += 1
        if not base._near_hex(s['color'], a['colors'], 2):
            bad.append((s['text'], s['color'], g))
    if bad:
        return 'fail', {'not_matching': bad[:8]}
    if unsure:
        return PERSON, {'reason': 'the ground behind some type is not one colour', 'spans': unsure[:4]}
    return 'pass', {'checked': checked}


# ---------------------------------------------------------------- marks, photos and their positions


def _vector_marks(key: str, hex_: str, tol=3):
    """Drawn shapes in one colour, per page: union box (pt, stroke included) and whether all are solid."""
    import pymupdf
    out = {}
    for page in pymupdf.open(key):
        boxes, solid = [], True
        for d in page.get_drawings():
            for k in ('fill', 'color'):
                if d.get(k) is not None and base._near_hex(base._hex(d[k]), [hex_], tol):
                    w = (d.get('width') or 0) / 2 if k == 'color' else 0
                    r = d['rect']
                    boxes.append((r.x0 - w, r.y0 - w, r.x1 + w, r.y1 + w))
                    op = d.get('fill_opacity' if k == 'fill' else 'stroke_opacity')
                    if op is not None and op < 0.999:
                        solid = False
        if boxes:
            out[page.number] = ((min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)), solid, len(boxes))
    return out


def _pixel_mark(img: np.ndarray, hex_: str, exclude=None, tol=14, min_px=30):
    """The box of the largest cluster of pixels in one colour (a printed mark on an image), outside excluded boxes."""
    import cv2
    m = (np.abs(img - _rgb(hex_)) <= tol).all(axis=2).astype(np.uint8)
    for x0, y0, x1, y1 in exclude or []:
        m[max(0, int(y0)):int(y1) + 1, max(0, int(x0)):int(x1) + 1] = 0
    if m.sum() < min_px:
        return None
    k = max(3, int(min(img.shape[:2]) * 0.015))
    grown = cv2.dilate(m, np.ones((k, k), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
    best = max(range(1, n), key=lambda i: int(m[labels == i].sum()), default=None)
    if best is None or m[labels == best].sum() < min_px:
        return None
    ys, xs = np.where((labels == best) & (m > 0))
    return (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))


def _image_rgb(path: Path):
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        rgba = im.convert('RGBA')
        im = Image.alpha_composite(Image.new('RGBA', rgba.size, (255, 255, 255, 255)), rgba)
    return np.asarray(im.convert('RGB')).astype(int)


def _visible_box(scene, asset, corners):
    """The part of the deliverable where the supplied file actually shows: the file is warped onto the scene and
    compared pixel by pixel, so a cropped placement gives its visible crop, not the whole file's projected corners."""
    import cv2
    h, w = asset.shape
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
    size = (scene.shape[1], scene.shape[0])
    warped = cv2.warpPerspective(asset, H, size, flags=cv2.INTER_AREA)
    valid = cv2.warpPerspective(np.full(asset.shape, 255, np.uint8), H, size, flags=cv2.INTER_NEAREST) > 0
    diff = cv2.blur(np.abs(scene.astype(int) - warped.astype(int)).astype(np.float32), (9, 9))
    m = (valid & (diff < 28)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n < 2:
        xs, ys = corners[:, 0].clip(0, size[0]), corners[:, 1].clip(0, size[1])
        return xs.min(), ys.min(), xs.max(), ys.max()
    k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh = (stats[k, j] for j in (cv2.CC_STAT_LEFT, cv2.CC_STAT_TOP, cv2.CC_STAT_WIDTH, cv2.CC_STAT_HEIGHT))
    return x, y, x + bw, y + bh


def _confirm_here(scene, flat, corners):
    """Feature matching was unsure: template-match the flat artwork at the place and scale it pointed to.
    Returns corners when the artwork correlates at FLAT_MIN_SCORE or more there, else None."""
    import cv2
    x0, y0 = corners[:, 0].min(), corners[:, 1].min()
    x1, y1 = corners[:, 0].max(), corners[:, 1].max()
    w, h = x1 - x0, y1 - y0
    if w < 16 or h < 8:
        return None
    mx, my = 0.15 * w, 0.15 * h
    X0, Y0 = int(max(0, x0 - mx)), int(max(0, y0 - my))
    crop = scene[Y0:int(min(scene.shape[0], y1 + my)), X0:int(min(scene.shape[1], x1 + mx))]
    t0 = base._ink_crop(flat)
    best = (-1.0, None)
    for f in (0.94, 0.97, 1.0, 1.03, 1.06):
        tw = int(round(w * f))
        th = int(round(tw * t0.shape[0] / t0.shape[1]))
        if tw < 8 or th < 8 or tw > crop.shape[1] or th > crop.shape[0]:
            continue
        t = cv2.resize(t0, (tw, th), interpolation=cv2.INTER_AREA)
        if t.std() < 1:
            continue
        r = cv2.matchTemplate(crop, t, cv2.TM_CCOEFF_NORMED)
        lo, hi, lo_at, hi_at = cv2.minMaxLoc(r)
        for score, (x, y) in ((hi, hi_at), (-lo, lo_at)):
            if score > best[0]:
                best = (float(score), np.float32([[X0 + x, Y0 + y], [X0 + x + tw, Y0 + y], [X0 + x + tw, Y0 + y + th], [X0 + x, Y0 + y + th]]))
    return best[1] if best[0] >= base.FLAT_MIN_SCORE else None


def _asset_box(path: Path, a, name, page=0):
    """Where a supplied file sits in the deliverable (pixels of the image, or points of a PDF page)."""
    scenes = base._scenes(path)
    asset = base._load_gray(base.asset_path(a, name))
    pages = range(len(scenes)) if page is None else [page]
    unsure = None
    for i in pages:
        n, corners, state = base.find_asset(scenes[i], asset)
        if state == 'found':
            s = 72 / base.RENDER_DPI if path.suffix.lower() == '.pdf' else 1
            box = _visible_box(scenes[i], asset, corners)
            return i, tuple(float(v) * s for v in box), state
        if state == 'unsure':
            here = _confirm_here(scenes[i], base._load_gray(base.asset_path(a, name), width=1600), corners)
            if here is not None:
                s = 72 / base.RENDER_DPI if path.suffix.lower() == '.pdf' else 1
                return i, (float(here[:, 0].min() * s), float(here[:, 1].min() * s), float(here[:, 0].max() * s), float(here[:, 1].max() * s)), 'found'
            if unsure is None:
                unsure = i
    if base._flat_asset(name) or 'monogram' in name or 'wordmark' in name:
        # flat artwork (a mark, a monogram) has few features: match it as a template at its own proportions
        flat = base._load_gray(base.asset_path(a, name), width=1600)
        for i in pages:
            score, corners = base.find_flat(scenes[i], flat)
            if score >= base.FLAT_MIN_SCORE:
                s = 72 / base.RENDER_DPI if path.suffix.lower() == '.pdf' else 1
                return i, (float(corners[:, 0].min() * s), float(corners[:, 1].min() * s), float(corners[:, 0].max() * s), float(corners[:, 1].max() * s)), 'found'
    # a one-colour mark gives correlation little to work with inside its own shape: unsure only when the template
    # match does not confirm it either
    return (unsure, None, 'unsure') if unsure is not None else (None, None, 'none')


def _locate(path: Path, a, spec, page=None):
    """A thing's page and box: {"colour": hex} a mark printed in that colour, {"asset": file} a supplied file,
    {"image": "largest"} the largest placed image of a PDF page, {"text": t} a line of text."""
    pdf = path.suffix.lower() == '.pdf'
    if 'colour' in spec:
        if pdf:
            marks = _vector_marks(str(path), spec['colour'])
            pages = sorted(marks) if page is None else [p for p in marks if p == page]
            return (pages[0], marks[pages[0]][0]) if pages else (None, None)
        img = _image_rgb(path)
        box = _pixel_mark(img, spec['colour'], spec.get('_exclude'))
        return (0, box) if box else (None, None)
    if 'asset' in spec:
        i, box, state = _asset_box(path, a, spec['asset'], page if page is not None else (None if pdf else 0))
        return (i, box) if box else (None, None)
    if 'image' in spec and pdf:
        imgs = _pdf_images(str(path))
        pages = sorted(imgs) if page is None else [page]
        for p in pages:
            boxes = imgs.get(p, [])
            if boxes:
                return p, max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        return None, None
    if 'pattern' in spec:
        layer = _layer(path)
        hits = [l for l in layer.lines if _rxs(spec['pattern'], l.text) and base._real(l)]
        if page is not None:
            hits = [l for l in hits if l.page == page]
        return (hits[0].page, hits[0].bbox) if hits else (None, None)
    if 'text' in spec:
        layer = _layer(path)
        hits = [l for l in layer.lines if contains(l.text, spec['text'], False)] or base._span(layer, spec['text'])
        if page is not None:
            hits = [l for l in hits if l.page == page]
        if not hits:
            return None, None
        return hits[0].page, (min(l.bbox[0] for l in hits), min(l.bbox[1] for l in hits), max(l.bbox[2] for l in hits), max(l.bbox[3] for l in hits))
    return None, None


def op_position(path, a):
    """A thing sits above or left of another (rel "above_or_left"), or below it ("below"), on the same page.
    Things are located by colour, supplied file, placed image or text (see _locate)."""
    pb, bb = _locate(path, a, a['b'])
    if bb is None:
        if a.get('optional_b'):
            return 'pass', {'reason': 'not present (the check applies only where it appears)'}
        return PERSON, {'reason': 'reference element not found', 'b': a['b']}
    spec_a = dict(a['a'])
    if 'colour' in spec_a and path.suffix.lower() != '.pdf':
        spec_a['_exclude'] = [bb]                            # a photo's own colours are not the mark
    pa, ba = _locate(path, a, spec_a, pb)
    if ba is None:
        return PERSON, {'reason': 'element not found', 'a': a['a']}
    tol = 0.02 * max(bb[2] - bb[0], bb[3] - bb[1])
    above, left, below = ba[3] <= bb[1] + tol, ba[2] <= bb[0] + tol, ba[1] >= bb[3] - tol
    ev = {'a_box': [round(v, 1) for v in ba], 'b_box': [round(v, 1) for v in bb]}
    if a['rel'] == 'above_or_left':
        ok, overlap = above or left, base._overlap(ba, bb) > 0.05
    elif a['rel'] == 'below':
        ok, overlap = below, False
    else:
        ok, overlap = above, False
    if ok:
        return 'pass', ev
    return (PERSON if overlap else 'fail'), ev


def op_mark(path, a):
    """A mark printed in one colour (the only element in that colour by the brand rules): at least min_mm wide,
    and drawn solid (vector shapes at full opacity, no other colour drawn over it)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'mark size and finish are read from a PDF'}
    marks = _vector_marks(str(path), a['colour'])
    if not marks:
        return PERSON, {'reason': f'no shape drawn in {a["colour"]} (the mark may be a picture or another colour)'}
    page, (box, solid, n) = next(iter(sorted(marks.items())))
    width_mm = (box[2] - box[0]) * PT_MM
    ev = {'page': page + 1, 'width_mm': round(width_mm, 2), 'shapes': n}
    if 'min_mm' in a:
        if abs(width_mm - a['min_mm']) < 0.3:
            return PERSON, dict(ev, reason='within 0.3 mm of the limit')
        return ('pass' if width_mm >= a['min_mm'] else 'fail'), ev
    if a.get('solid'):
        if not solid:
            return 'fail', dict(ev, reason='drawn with transparency')
        import pymupdf
        pg = pymupdf.open(path)[page]
        inside = [d for d in pg.get_drawings() if base._overlap(tuple(d['rect']), box) > 0.6 and d['rect'].width * d['rect'].height < 0.5 * pg.rect.width * pg.rect.height]
        others = [base._hex(d.get('fill') or d.get('color')) for d in inside
                  if (d.get('fill') or d.get('color')) is not None and not base._near_hex(base._hex(d.get('fill') or d.get('color')), [a['colour']], 3)]
        imgs = [i for i in _pdf_images(str(path)).get(page, []) if base._overlap(i, box) > 0.3]
        if others:
            return 'fail', dict(ev, reason='other colours drawn on the mark', colours=sorted(set(others))[:4])
        if imgs:
            return PERSON, dict(ev, reason='a picture overlaps the mark')
        return 'pass', ev
    return PERSON, ev


# ---------------------------------------------------------------- page geometry (PDF)


def op_page_size(path, a):
    """Every page measures width x height mm (within tol), with no bleed box larger than the page."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'page size is read from a PDF'}
    tol = a.get('tol', 0.2)
    bad = []
    for page in pymupdf.open(path):
        crop = page.cropbox
        w, h = crop.width * PT_MM, crop.height * PT_MM
        if abs(w - a['width_mm']) > tol or abs(h - a['height_mm']) > tol:
            bad.append({'page': page.number + 1, 'mm': [round(w, 2), round(h, 2)]})
        elif a.get('no_bleed'):
            media = page.mediabox
            if media.width * PT_MM > w + tol or media.height * PT_MM > h + tol:
                bad.append({'page': page.number + 1, 'media_mm': [round(media.width * PT_MM, 2), round(media.height * PT_MM, 2)]})
    return ('fail', {'pages': bad[:6]}) if bad else ('pass', {'mm': [a['width_mm'], a['height_mm']]})


def op_no_blank_page(path, a):
    """No page is blank: every page carries text, a placed image or a drawn shape other than its ground."""
    import pymupdf
    doc = pymupdf.open(path)
    blank = []
    for page in doc:
        if page.get_text('text').strip() or page.get_image_info():
            continue
        area = page.rect.width * page.rect.height
        shapes = [d for d in page.get_drawings() if d['rect'].width * d['rect'].height < 0.95 * area]
        if not shapes:
            arr = _page_pixels(str(path), page.number)
            if arr.std(axis=(0, 1)).max() < 2:
                blank.append(page.number + 1)
    return ('fail', {'blank_pages': blank}) if blank else ('pass', {'pages': len(doc)})


def op_bare_below(path, a):
    """On every page that carries exactly one of the named headings, at least min_mm of bare paper lies directly
    below it: no text, placed image or drawn shape inside the heading's width for that depth. Within 1 mm of the
    limit goes to a person (a ruler reading)."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(path)
    layer = base.pdf_layer(str(path))
    checked, bad, close = 0, [], []
    for page in doc:
        heads = [l for l in layer.lines if l.page == page.number and _whole(l.text, a['names'])]
        if len(heads) != 1:
            continue
        h = heads[0]
        x0, x1, top = h.bbox[0], h.bbox[2], h.bbox[3]
        ink = _ink_rows(str(path), page.number, h.bbox)
        if ink:
            top = ink[1]                                  # the letters' own bottom, not the line box's descender room
        tops = [l.bbox[1] for l in layer.lines if l.page == page.number and l is not h and l.bbox[1] >= top - 0.5 and min(l.bbox[2], x1) > max(l.bbox[0], x0)]
        tops += [i[1] for i in _pdf_images(str(path)).get(page.number, []) if i[1] >= top - 0.5 and min(i[2], x1) > max(i[0], x0)]
        area = page.rect.width * page.rect.height
        tops += [d['rect'].y0 for d in page.get_drawings() if d['rect'].width * d['rect'].height < 0.5 * area and d['rect'].y0 >= top - 0.5
                 and min(d['rect'].x1, x1) > max(d['rect'].x0, x0)]
        depth = ((min(tops) if tops else page.rect.height) - top) * PT_MM
        checked += 1
        entry = {'page': page.number + 1, 'heading': h.text, 'bare_mm': round(depth, 1)}
        if depth < a['min_mm'] - 1:
            bad.append(entry)
        elif depth < a['min_mm']:
            close.append(entry)
    if bad:
        return 'fail', {'pages': bad}
    if close:
        return PERSON, {'reason': 'within 1 mm of the limit', 'pages': close}
    return 'pass', {'single_product_pages': checked}


# ---------------------------------------------------------------- letter spacing (PDF)


@functools.lru_cache(maxsize=16)
def _pdf_lines_chars(key: str):
    """Each line's text with its letter spacing in em: the median gap between consecutive glyph boxes over size."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        for b in page.get_text('rawdict')['blocks']:
            for l in b.get('lines', []):
                chars = [c for s in l['spans'] for c in s['chars']]
                text = ''.join(c['c'] for c in chars).strip()
                size = max((s['size'] for s in l['spans']), default=0)
                # glyph to next glyph, spaces skipped: PDF readers insert spaces into widely tracked type, and the
                # median keeps a real word space from counting as letter spacing
                ink = [c for c in chars if c['c'].strip()]
                gaps = [n['bbox'][0] - c['bbox'][2] for c, n in zip(ink, ink[1:])]
                if text and size and gaps:
                    out.append(dict(text=text, bbox=tuple(l['bbox']), page=page.number, size=size,
                                    tracking=float(np.median(gaps)) / size))
    return out


def op_tracking(path, a):
    """Lines matching a are letterspaced more openly than lines matching b. With pair "below", each a line is
    compared with the nearest b line below it (a date line with its act name)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'letter spacing is read from a PDF'}
    rows = _pdf_lines_chars(str(path))
    sel = lambda spec: [r for r in rows if any(_has(r['text'], t) for t in spec.get('texts', [])) or
                        any(re.search(p, canon(r['text']), re.I) or re.search(p, base.squash(canon(r['text'])), re.I) for p in spec.get('patterns', []))]
    la, lb = sel(a['a']), sel(a['b'])
    if not la:
        return ('pass', {'reason': 'none present'}) if a.get('optional') else (PERSON, {'reason': 'lines not found'})
    if not lb:
        return PERSON, {'reason': 'lines to compare with not found'}
    bad = []
    for r in la:
        if a.get('pair') == 'below':
            cands = [b for b in lb if b['page'] == r['page'] and b['bbox'][1] >= r['bbox'][1] and _xoverlap(b['bbox'], r['bbox'])]
            others = [min(cands, key=lambda b: b['bbox'][1] - r['bbox'][1])] if cands else []
        else:
            others = lb
        for b in others:
            if not r['tracking'] > b['tracking'] + 0.005:
                bad.append({'line': r['text'], 'em': round(r['tracking'], 3), 'other': b['text'], 'other_em': round(b['tracking'], 3)})
    if bad:
        return 'fail', {'not_more_open': bad[:6]}
    return 'pass', {'lines': len(la)}


# ---------------------------------------------------------------- wording that must stay exact


def op_description(path, a):
    """Where a description of this kind appears (trigger), it carries the required terms and none of the
    contradicting ones. scope_names/scope_map: on an image naming one reference, its own description applies."""
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    hay = ' '.join(l.text for l in layer.lines if base._real(l)) if layer.source == 'ocr' else layer.text
    if a.get('scope_line'):
        # several entries on one sheet: only the lines naming this entry, and the line read after each, count
        own = [l for l in layer.lines if re.search(a['scope_line'], canon(l.text), re.I)]
        scoped = ' '.join(l.text + ' ' + (_next_line(layer.lines, l).text if _next_line(layer.lines, l) else '') for l in own)
        if not re.search(a['trigger'], canon(hay), re.I):
            return ('pass', {'reason': 'no description of this kind'}) if _reliable(layer) else (PERSON, {'reason': 'could not rule out a description'})
        if not re.search(a['trigger'], canon(scoped), re.I):
            return PERSON, {'reason': 'a description appears, but not on this entry\'s lines'}
        hay = scoped
    if a.get('scope_map'):
        shown = [n for n in a['scope_map'] if contains(hay, n, False)]
        if len(shown) != 1:
            if not re.search(a['trigger'], canon(hay), re.I) and _reliable(layer):
                return 'pass', {'reason': 'no description shown'}
            return PERSON, {'reason': 'none or several references shown', 'shown': shown}
        a = dict(a, **a['scope_map'][shown[0]])
    if not re.search(a['trigger'], canon(hay), re.I):
        if _reliable(layer):
            return 'pass', {'reason': 'no description of this kind (the check applies only where it appears)'}
        return PERSON, {'reason': 'could not rule out a description'}
    bad = [f for f in a.get('forbidden', []) if re.search(f, canon(hay), re.I)]
    if bad:
        if layer.source == 'ocr' and not any(l.conf >= OCR_GOOD_CONF and any(re.search(f, canon(l.text), re.I) for f in bad) for l in layer.lines):
            return PERSON, {'reason': 'contradicting term read with low confidence', 'found': bad}
        return 'fail', {'contradicting': bad}
    missing = [r for r in a.get('required', []) if not re.search(r, canon(hay), re.I)]
    if missing:
        return PERSON, {'reason': 'description present without the expected terms', 'missing': missing}
    return 'pass', {'terms': a.get('required', [])}


def op_names_full(path, a):
    """Wherever a person's first or last name appears, the full name appears, spelled exactly."""
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    hay = ' '.join(l.text for l in layer.lines)
    bad = []
    for full in a['names']:
        parts = full.split()
        if not any(contains(hay, p, False) for p in parts):
            continue
        if contains(hay, full, False):
            rest = canon(hay, False).replace(canon(full, False), ' ')
            if not any(contains(rest, p, False) for p in parts):
                continue
        bad.append(full)
    if bad:
        if layer.source == 'ocr' and not _reliable(layer):
            return PERSON, {'reason': 'a partial name read with low confidence', 'names': bad}
        if layer.source == 'ocr' and any(base.near_miss(hay, n) >= base.NEAR_MISS for n in bad):
            return PERSON, {'reason': 'a name read close to the full spelling; could be a misreading', 'names': bad}
        return 'fail', {'not_in_full': bad}
    if not _reliable(layer):
        return PERSON, {'reason': 'text not read clearly enough to rule out a partial name'}
    return 'pass', {'checked': a['names']}


def op_spelled(path, a):
    """Any text close to one of the names (a style or product name) is spelled exactly as listed."""
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    hay = ' '.join(l.text for l in layer.lines if base._real(l)) if layer.source == 'ocr' else layer.text
    off = []
    for n in a['names']:
        if contains(hay, n, False):
            continue
        score = base.near_miss(hay, n)
        if score >= 0.85:
            off.append((n, round(score, 2)))
    if off:
        return PERSON, {'reason': 'a name close to, but not exactly, the listed spelling (a typo or a misreading)', 'names': off}
    if not _reliable(layer):
        return PERSON, {'reason': 'text not read clearly enough'}
    return 'pass', {'checked': a['names']}


def op_directly_above(path, a):
    """Each named text that is shown has a line matching the pattern directly above it (a date line over its act):
    the nearest line above it that shares some of its width."""
    layer = _layer(path)
    lines = [l for l in layer.lines if base._real(l)] if layer.source == 'ocr' else layer.lines
    checked, bad = 0, []
    for name in a['texts']:
        for an in [l for l in lines if contains(l.text, name, False)]:
            up = _nearest(an, lines, 'above')
            checked += 1
            if up is None or not _rxs(a['pattern'], up.text):
                bad.append({'text': an.text, 'above': up.text if up else None, 'ok_read': up is None or _line_ok(up)})
    if not checked:
        return ('pass', {'reason': 'none shown'}) if a.get('optional') and _reliable(layer) else (PERSON, {'reason': 'names not found'})
    if bad:
        if layer.source == 'ocr' and not all(b['ok_read'] for b in bad):
            return PERSON, {'reason': 'the line above was read with low confidence', 'lines': bad[:3]}
        return 'fail', {'not_directly_above': bad[:4]}
    return 'pass', {'checked': checked}


def op_stacked(path, a):
    """A two-part wordmark is stacked, top part over bottom part (stack True), or set on one line (stack False)."""
    layer = _layer(path)
    lines = layer.lines
    tops = [l for l in lines if contains(l.text, a['top'], False)]
    bottoms = [l for l in lines if contains(l.text, a['bottom'], False)]
    one = [l for l in tops if contains(l.text, a['bottom'], False)]
    if not tops and not bottoms:
        return ('pass', {'reason': 'no wordmark shown'}) if a.get('optional') and _reliable(layer) else (PERSON, {'reason': 'wordmark not found'})
    pairs = [(t, b) for t in tops for b in bottoms if t.page == b.page and b.bbox[1] > t.bbox[1] and _xoverlap(t.bbox, b.bbox)
             and b.bbox[1] - t.bbox[3] <= 1.5 * (t.bbox[3] - t.bbox[1]) and t not in one]
    # the wordmark is the prominent setting; the two words run together in small running text (a footer) are not it
    sizes = sorted(l.size for l in lines if base._real(l)) or [0]
    median = sizes[len(sizes) // 2]
    big_one = [l for l in one if l.size >= max(1.5 * median, max((t.size for t, _ in pairs), default=0) * 0.8)]
    if pairs and not big_one:
        return ('pass' if a['stack'] else 'fail'), {'stacked': [pairs[0][0].text, pairs[0][1].text]}
    if big_one and not pairs:
        return ('fail' if a['stack'] else 'pass'), {'one_line': big_one[0].text}
    if one and not pairs:
        return PERSON, {'reason': 'the two words run together only in small text', 'line': one[0].text}
    return PERSON, {'reason': 'wordmark set both ways, or its parts found apart'}


def op_inside_all(path, a):
    """Every occurrence of the named texts (a text set over several lines counts by its lines) and of lines matching
    the patterns lies inside its page or image: nothing cut off at an edge."""
    layers = text_layers(path)
    layer = merged(layers)
    pages = {}
    if path.suffix.lower() == '.pdf':
        import pymupdf
        pages = {p.number: (p.rect.width, p.rect.height) for p in pymupdf.open(path)}
    def outside(l):
        w, h = pages.get(l.page, (layer.width, layer.height))
        x0, y0, x1, y1 = l.bbox
        return x0 < 0.5 or y0 < 0.5 or x1 > w - 0.5 or y1 > h - 0.5
    bad, checked = [], 0
    for t in a.get('texts', []):
        hits = [l for l in layer.lines if contains(l.text, t, False)] or base._span(layer, t, max_lines=8)
        if not hits:
            if a.get('optional'):
                continue
            return PERSON, {'reason': f'not read in full: {t}'}
        checked += 1
        bad += [l.text for l in hits if outside(l)]
    for p in a.get('patterns', []):
        for l in layer.lines:
            if _rxs(p, l.text):
                checked += 1
                if outside(l):
                    bad.append(l.text)
    if bad:
        return 'fail', {'cut_off': bad[:4]}
    if not checked:
        return PERSON, {'reason': 'nothing found to check'}
    return 'pass', {'checked': checked}


def op_style_lines(path, a):
    """PDF type style for selected lines: texts (a text set over several lines counts by its lines), whole_lines
    (lines reading exactly one of these, letter spacing aside), patterns, or font_family (every line set in that
    family). Checks family and weight (italic never matches a roman weight), size, max_size, capitals."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'type style is read from a PDF'}
    layer = base.pdf_layer(str(path))
    if not layer.readable:
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    picks = []
    for t in a.get('texts', []):
        hits = [l for l in layer.lines if contains(l.text, t, False)] or base._span(layer, t, max_lines=8)
        if not hits and not a.get('optional'):
            return PERSON, {'reason': f'text not found: {t}'}
        picks += hits
    for t in a.get('whole_lines', []):
        picks += [l for l in layer.lines if base.squash(canon(l.text, False)).strip(' .,') == base.squash(canon(t, False))]
    for p in a.get('patterns', []):
        picks += [l for l in layer.lines if re.search(p, canon(l.text), re.I) or re.search(p, base.squash(canon(l.text)), re.I)]
    if a.get('font_family'):
        fam = re.sub(r'[^a-z0-9]', '', a['font_family'].lower())
        picks += [l for l in layer.lines if any(base._font_parts(f)[0] == fam for _, f, _, _ in l.fonts)]
    picks = list(dict.fromkeys(picks))
    if not picks:
        return ('pass', {'reason': 'none present (the check applies only where they appear)'}) if a.get('optional') else (PERSON, {'reason': 'nothing selected'})
    bad = []
    want_fam = re.sub(r'[^a-z0-9]', '', a['family'].lower()) if a.get('family') else None
    want_wt = re.sub(r'[^a-z0-9]', '', a['weight'].lower()) if a.get('weight') else None
    for l in picks:
        for s_text, font, size, color in l.fonts:
            if not s_text.strip() or (a.get('except_digits') and re.fullmatch(r'[\d\s.,/-]+', s_text)):
                continue
            if a.get('font_family') and base._font_parts(font)[0] != re.sub(r'[^a-z0-9]', '', a['font_family'].lower()):
                continue
            fam, style = base._font_parts(font)
            if want_fam and fam != want_fam:
                bad.append((s_text, font))
            elif want_wt and style != want_wt:
                bad.append((s_text, font))
            elif 'size' in a and abs(size - a['size']) > a.get('tolerance', 0.05):
                bad.append((s_text, size))
            elif 'max_size' in a and size > a['max_size'] + 0.05:
                bad.append((s_text, size))
            elif a.get('caps') and re.search(r'[a-z]', s_text):
                bad.append((s_text, 'lowercase'))
    return ('fail', {'not_matching': bad[:10]}) if bad else ('pass', {'lines': len(picks)})


def op_size_vs(path, a):
    """The size of text a (the first of its options shown) against every text of b that is shown: larger (rel
    "larger") or smaller. Neither shown: a pass when optional; b none shown: a pass ("if ... appears")."""
    layer = _layer(path)
    def size_of(t):
        if isinstance(t, dict):
            hits = [l for l in layer.lines if re.search(t['regex'], canon(l.text), re.I) and base._real(l)]
            return (max(l.size for l in hits), hits) if hits else (None, [])
        return base._cap_size(layer, t)
    sa, ha = None, []
    for t in a['a'] if isinstance(a['a'], list) else [a['a']]:
        sa, ha = size_of(t)
        if sa is not None:
            break
    if sa is None:
        return ('pass', {'reason': 'not shown'}) if a.get('optional') and _reliable(layer) else (PERSON, {'reason': 'text not found'})
    bs = [(t, *size_of(t)) for t in a['b']]
    bs = [(t, s, h) for t, s, h in bs if s is not None and not any(l in ha for l in h)]
    if not bs:
        return ('pass', {'reason': 'nothing to compare shown'}) if _reliable(layer) or a.get('optional') else (PERSON, {'reason': 'compared text not found'})
    if not all(l.size_ok for l in ha + [l for _, _, h in bs for l in h]):
        return PERSON, {'reason': 'letter height could not be measured on every line compared'}
    margin = base.SIZE_MARGIN if layer.source == 'ocr' else 0.01
    for t, sb, _ in bs:
        r = sa / sb if sb else 99
        ok = r > 1 + margin if a['rel'] == 'larger' else r < 1 - margin
        if not ok:
            return (PERSON if abs(r - 1) <= margin and layer.source == 'ocr' else 'fail'), {'a': round(sa, 1), 'b': round(sb, 1), 'b_text': t if isinstance(t, str) else t['regex']}
    return 'pass', {'a': round(sa, 1), 'b': [round(s, 1) for _, s, _ in bs]}


def op_size_pairs(path, a):
    """Each shown name is set larger than its own value (a product and its price). On a page showing one name,
    every value of the kind on that page is its own; otherwise the value is the nearest line of the kind below
    the name sharing some width, or on its row. A name shown with no value found goes to a person, never a pass."""
    layer = _layer(path)
    names = [l for l in layer.lines if any(_whole(l.text, [n]) or _has(l.text, n) for n in a['names'])]
    if not names:
        return ('pass', {'reason': 'none shown'}) if _reliable(layer) else (PERSON, {'reason': 'names not found'})
    kind = [l for l in layer.lines if (re.search(a['kind'], canon(l.text), re.I) or re.search(a['kind'], base.squash(canon(l.text)), re.I)) and l not in names]
    pairs, bad, unpaired = 0, [], []
    for n in names:
        same_page = [x for x in names if x.page == n.page]
        if len(same_page) == 1:
            values = [l for l in kind if l.page == n.page]
        else:
            v = _nearest(n, kind, 'below', 4 * (n.bbox[3] - n.bbox[1]))
            if v is None:
                row = [l for l in kind if l.page == n.page and abs(_cy(l.bbox) - _cy(n.bbox)) <= 0.6 * (n.bbox[3] - n.bbox[1])]
                v = min(row, key=lambda l: abs(l.bbox[0] - n.bbox[2]), default=None)
            values = [v] if v is not None else []
        if not values:
            unpaired.append(n.text)
            continue
        for v in values:
            pairs += 1
            if not n.size > v.size * (1 + (base.SIZE_MARGIN if layer.source == 'ocr' else 0.01)):
                bad.append({'name': n.text, 'value': v.text, 'sizes': [round(n.size, 1), round(v.size, 1)]})
    if bad:
        return ('fail' if layer.source == 'pdf' else PERSON), {'not_larger': bad[:4]}
    if unpaired:
        return PERSON, {'reason': 'a name shown without a value found for it', 'names': unpaired[:3]}
    return 'pass', {'pairs': pairs}


# ---------------------------------------------------------------- figures in PDF type


@functools.lru_cache(maxsize=8)
def _pdf_chars(key: str):
    """Every glyph: char, box, origin, size, font, page."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        for b in page.get_text('rawdict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    for c in s['chars']:
                        out.append(dict(c=c['c'], bbox=tuple(c['bbox']), origin=tuple(c['origin']), size=s['size'],
                                        font=s['font'], page=page.number, line=tuple(l['bbox'])))
    return out


def _ink_rows(key: str, page: int, bbox, dpi=600):
    """Top and bottom of the ink inside a box, in points (None when the box holds no ink)."""
    import pymupdf
    doc = pymupdf.open(key)
    clip = pymupdf.Rect(bbox)
    pix = doc[page].get_pixmap(dpi=dpi, clip=clip)
    g = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3].mean(axis=2)
    ground = np.median(np.concatenate([g[0], g[-1]]))
    rows = np.where((np.abs(g - ground) > 60).any(axis=1))[0]
    if not len(rows):
        return None
    s = 72 / dpi
    return clip.y0 + rows.min() * s, clip.y0 + (rows.max() + 1) * s


def op_figures(path, a):
    """Figures in PDF type. font_not: no digit is set in this family. same_size: a digit is the size of the letters
    on its line. tabular: every digit of the selected lines has the same advance width. lining: every digit of the
    selected lines stands on the baseline at one height (old-style figures drop below it or sit at x-height)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    chars = _pdf_chars(key)
    digits = [c for c in chars if c['c'].isdigit()]
    if a.get('lines_pattern'):
        layer = base.pdf_layer(key)
        boxes = [(l.page, l.bbox) for l in layer.lines if re.search(a['lines_pattern'], canon(l.text), re.I)]
        digits = [c for c in digits if any(p == c['page'] and base._overlap(b, c['bbox']) > 0.5 for p, b in boxes)]
    if not digits:
        return 'pass', {'reason': 'no figures of this kind'}
    if a.get('font_not'):
        fam = re.sub(r'[^a-z0-9]', '', a['font_not'].lower())
        bad = sorted({c['font'] for c in digits if base._font_parts(c['font'])[0] == fam})
        return ('fail', {'fonts': bad}) if bad else ('pass', {'digits': len(digits)})
    if a.get('same_size'):
        bad = []
        for c in digits:
            peers = [o for o in chars if o['page'] == c['page'] and o['line'] == c['line'] and o['c'].isalpha()]
            if peers and any(abs(o['size'] - c['size']) > 0.1 for o in peers):
                bad.append((c['c'], c['size'], peers[0]['size']))
        return ('fail', {'different': bad[:6]}) if bad else ('pass', {'digits': len(digits)})
    if a.get('tabular'):
        widths = {}
        for c in digits:
            w = (c['bbox'][2] - c['bbox'][0]) / c['size']
            widths.setdefault(c['font'], []).append(round(w, 3))
        uneven = {f: sorted(set(w)) for f, w in widths.items() if max(w) - min(w) > 0.01}
        return ('fail', {'advance_widths_em': uneven}) if uneven else ('pass', {'fonts': sorted(widths)})
    if a.get('lining'):
        heights, drops = [], []
        for c in digits[:60]:
            ink = _ink_rows(key, c['page'], c['bbox'])
            if ink is None:
                continue
            top, bottom = ink
            base_y = c['origin'][1]
            heights.append((base_y - top) / c['size'])
            drops.append((bottom - base_y) / c['size'])
        if not heights:
            return PERSON, {'reason': 'figures could not be measured'}
        spread = max(heights) - min(heights)
        if max(drops) > 0.08 or spread > 0.12:
            return 'fail', {'height_em': [round(min(heights), 3), round(max(heights), 3)], 'max_drop_em': round(max(drops), 3)}
        return 'pass', {'height_em': round(float(np.median(heights)), 3)}
    return PERSON, {'reason': 'nothing to check'}


def op_initial_ratio(path, a):
    """A heading opens with an initial set at ratio times the size of the capital that starts the next word
    (font sizes from the PDF, same family); within 0.1 of it passes, beyond 0.25 fails."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    chars = _pdf_chars(str(path))
    lines = {}
    for c in chars:
        lines.setdefault((c['page'], c['line']), []).append(c)
    for cs in lines.values():
        text = ''.join(c['c'] for c in cs)
        if not contains(text, a['heading'], False):
            continue
        i = canon(text, False).find(canon(a['heading'], False))
        first = cs[i]
        word2 = a['heading'].split()[1] if len(a['heading'].split()) > 1 else None
        j = canon(text, False).find(canon(word2, False), i + 1) if word2 else -1
        if j < 0:
            return PERSON, {'reason': 'second word not found on the heading line'}
        second = cs[j]
        if base._font_parts(first['font'])[0] != base._font_parts(second['font'])[0]:
            return PERSON, {'reason': 'initial and word are set in different families', 'fonts': [first['font'], second['font']]}
        r = first['size'] / second['size']
        ev = {'initial_pt': first['size'], 'capital_pt': second['size'], 'ratio': round(r, 2)}
        if abs(r - a['ratio']) <= 0.1:
            return 'pass', ev
        return ('fail' if abs(r - a['ratio']) > 0.25 else PERSON), ev
    return PERSON, {'reason': f'heading not found: {a["heading"]}'}


def op_sections(path, a):
    """House sections of a PDF (pages carrying exactly one of the names in full): the name sits above (above) and
    is set larger than (larger) the section's value lines; the entries come in the same order (same_order) and carry
    the same labels (same_labels) in every section."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = base.pdf_layer(str(path))
    sections = {}
    for l in layer.lines:
        if _whole(l.text, a['names']):
            sections.setdefault(l.page, []).append(l)
    sections = {p: hs[0] for p, hs in sections.items() if len(hs) == 1}
    if len(sections) < 2:
        return PERSON, {'reason': 'house sections not found', 'pages': sorted(sections)}
    kinds = a['kinds']                                      # {kind: pattern}
    sigs, labels, bad = {}, {}, []
    for p, head in sections.items():
        rows = [l for l in layer.lines if l.page == p and l.bbox[1] > head.bbox[1] - 1 and l is not head]
        entries = []
        for l in sorted(rows, key=lambda l: (round(l.bbox[1] / 3), l.bbox[0])):
            k = next((k for k, rx in kinds.items() if re.search(rx, canon(l.text), re.I)), None)
            if k:
                entries.append((k, l))
        values = [l for k, l in entries if k in a.get('value_kinds', kinds)]
        if a.get('above') and any(l.bbox[1] < head.bbox[3] - 1 for l in values):
            bad.append({'page': p + 1, 'reason': 'a value sits level with or above the name'})
        if a.get('larger') and any(l.size >= head.size for l in values):
            bad.append({'page': p + 1, 'reason': 'a value is set as large as the name'})
        sigs[p] = [k for k, _ in entries]
        labels[p] = sorted({re.sub(r'[\d,.$€£]+', '#', canon(l.text, False)).strip() for _, l in entries})
    if a.get('same_order') and len({tuple(s) for s in sigs.values()}) > 1:
        bad.append({'reason': 'entries in a different order', 'orders': {p + 1: s for p, s in sigs.items()}})
    if a.get('same_labels') and len({tuple(s) for s in labels.values()}) > 1:
        bad.append({'reason': 'different labels', 'labels': {p + 1: s for p, s in labels.items()}})
    if any(not s for s in sigs.values()):
        return PERSON, {'reason': 'a section without entries', 'orders': {p + 1: s for p, s in sigs.items()}}
    return ('fail', {'problems': bad[:4]}) if bad else ('pass', {'sections': len(sections)})


def op_placed_opacity(path, a):
    """The supplied picture is placed fully opaque: drawn with no transparency or blend mode (read from the page's
    graphics state), the picture's own alpha edge aside. The picture is found on the rendered page first, so a
    transparent PNG is matched as it shows."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(path)
    page_no, box, state = _asset_box(path, a, a['asset'], None)
    if box is None:
        return PERSON, {'reason': f'{a["asset"]} not found on the page' if state == 'none' else 'possible placement, unclear'}
    page = doc[page_no]
    names = {img[0]: img[7] for img in page.get_images(full=True)}
    infos = [i for i in page.get_image_info(xrefs=True) if i.get('xref') in names and base._overlap(tuple(i['bbox']), box) > 0.5]
    if not infos:
        return PERSON, {'reason': 'found as artwork, not as a placed picture'}
    name = names[max(infos, key=lambda i: base._overlap(tuple(i['bbox']), box))['xref']]
    content = b''.join(doc.xref_stream(x) or b'' for x in page.get_contents()).decode('latin-1')
    uses = [m.start() for m in re.finditer(r'/' + re.escape(name) + r'\s+Do\b', content)]
    if not uses:
        return PERSON, {'reason': 'placed inside a nested form; graphics state not read'}
    states = []
    for u in uses:
        block, depth, start = content[:u], 0, 0
        for m in reversed(list(re.finditer(r'(?<![^\s])([qQ])(?![^\s])', block))):
            depth += 1 if m.group(1) == 'Q' else -1
            if depth < 0:
                start = m.end()
                break
        states += re.findall(r'/(\S+)\s+gs\b', block[start:])
    bad = []
    for gs in states:
        kind, val = doc.xref_get_key(page.xref, f'Resources/ExtGState/{gs}')
        if kind == 'xref':
            val = doc.xref_object(int(val.split()[0]))
        for key, rx in (('ca', r'/ca\s+([\d.]+)'), ('CA', r'/CA\s+([\d.]+)')):
            m = re.search(rx, val or '')
            if m and float(m.group(1)) < 0.999:
                bad.append(f'{key} {m.group(1)}')
        m = re.search(r'/BM\s*/(\w+)', val or '')
        if m and m.group(1) not in ('Normal', 'Compatible'):
            bad.append(f'blend {m.group(1)}')
    return ('fail', {'graphics_state': bad}) if bad else ('pass', {'page': page_no + 1, 'image': name, 'states': states})


# ---------------------------------------------------------------- pictures: which one, and what stands beside it


def _which_photo(path, a, photos):
    """The one supplied photo (of several) found in the deliverable; 'unsure' when unclear or several."""
    found, unsure = [], []
    scenes = base._scenes(path)
    for name in photos:
        asset = base._load_gray(base.asset_path(a, name))
        for i, scene in enumerate(scenes):
            n, corners, state = base.find_asset(scene, asset)
            if state == 'found':
                found.append((n, name, i, corners))
            elif state == 'unsure':
                unsure.append(name)
    names = sorted({f[1] for f in found})
    if len(names) == 1 and not unsure:
        best = max(found)
        return best[1], best[2], best[3]
    return ('unsure' if names or unsure else None), None, None


def op_pictured(path, a):
    """The pictured person is identified by which supplied photo appears (photos: {file: name}). when: the check
    applies only if this person is pictured. then: an assertion run on the deliverable, with {name} replaced by the
    pictured person's name."""
    name, _, _ = _which_photo(path, a, list(a['photos']))
    if name is None:
        return PERSON, {'reason': 'no supplied instructor photo found (it may be another photo)'}
    if name == 'unsure':
        return PERSON, {'reason': 'the pictured person could not be told apart'}
    who = a['photos'][name]
    if a.get('when') and who != a['when']:
        return 'pass', {'pictured': who, 'reason': 'another person is pictured'}
    sub = _fill(a['then'], who)
    status, ev = base.run(path, dict(sub, **{k: v for k, v in a.items() if k.startswith('_')}))
    return status, dict(ev, pictured=who)


def _fill(obj, who):
    if isinstance(obj, str):
        return obj.replace('{name}', who)
    if isinstance(obj, list):
        return [_fill(x, who) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, who) for k, v in obj.items()}
    return obj


def op_names_by_photo(path, a):
    """If the supplied photo appears, any of the listed names standing beside it (below, above, or level with it,
    within half the photo's size) is the expected one."""
    asset = base._load_gray(base.asset_path(a, a['photo']))
    scenes = base._scenes(path)
    hit = None
    for i, scene in enumerate(scenes):
        n, corners, state = base.find_asset(scene, asset)
        if state == 'unsure':
            return PERSON, {'reason': 'a possible match that does not clearly look like the supplied photo'}
        if state == 'found':
            hit = (i, corners)
            break
    if hit is None:
        return 'pass', {'reason': 'photo not shown (the check applies only where it appears)'}
    i, corners = hit
    s = 72 / base.RENDER_DPI if path.suffix.lower() == '.pdf' else 1
    box = (corners[:, 0].min() * s, corners[:, 1].min() * s, corners[:, 0].max() * s, corners[:, 1].max() * s)
    w, h = box[2] - box[0], box[3] - box[1]
    zone = (box[0] - 0.5 * w, box[1] - 0.5 * h, box[2] + 0.5 * w, box[3] + 0.5 * h)
    layer = _layer(path)
    near = [l for l in layer.lines if l.page == i and base._overlap(l.bbox, zone) > 0.5]
    named = [(n, l) for l in near for n in a['names'] if contains(l.text, n, False)]
    wrong = [(n, l) for n, l in named if n != a['expected']]
    if not wrong:
        return 'pass', {'names_beside': [n for n, _ in named]}
    right = [n for n, _ in named if n == a['expected']]
    if right:
        return PERSON, {'reason': 'several names beside the photo', 'names': sorted({n for n, _ in named})}
    if not all(_line_ok(l) for _, l in wrong):
        return PERSON, {'reason': 'a name read with low confidence', 'names': [n for n, _ in wrong]}
    return 'fail', {'wrong_name': [n for n, _ in wrong]}


def op_same_photo(path, a):
    """The supplied photo is placed unaltered: found, and inside the placed picture's frame the pixels correlate with
    the file at min_ncc or more (a crop compares only what it shows; a retouched or regenerated face lowers the
    score). Never a fail: a lower score goes to a person, who judges whether it is still recognizably the person."""
    import cv2
    asset = base._load_gray(base.asset_path(a, a['asset']))
    pdf = path.suffix.lower() == '.pdf'
    for i, scene in enumerate(base._scenes(path)):
        n, corners, state = base.find_asset(scene, asset)
        if state != 'found':
            continue
        h, w = asset.shape
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
        frame = np.zeros(scene.shape, np.uint8)
        if pdf:
            k = base.RENDER_DPI / 72
            quad = (corners[:, 0].min() / k, corners[:, 1].min() / k, corners[:, 0].max() / k, corners[:, 1].max() / k)
            boxes = [b for b in _pdf_images(str(path)).get(i, []) if base._overlap(b, quad) > 0.2]
            if not boxes:
                return PERSON, {'reason': 'the placed picture frame was not found'}
            b = max(boxes, key=lambda b: base._overlap(b, quad))
            frame[int(b[1] * k):int(b[3] * k), int(b[0] * k):int(b[2] * k)] = 255
        else:
            frame[:] = 255
        inv = np.linalg.inv(H)
        shown = cv2.warpPerspective(frame, inv, (w, h), flags=cv2.INTER_NEAREST) > 0
        back = cv2.warpPerspective(scene, inv, (w, h), flags=cv2.INTER_AREA)
        share = float(shown.mean())
        if share < 0.15:
            return PERSON, {'reason': 'only a small part of the photo is shown', 'shown_share': round(share, 2)}
        x, y = asset[shown].astype(float), back[shown].astype(float)
        x, y = x - x.mean(), y - y.mean()
        ncc = float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9))
        ev = {'ncc': round(ncc, 3), 'shown_share': round(share, 2)}
        return ('pass', ev) if ncc >= a.get('min_ncc', 0.9) else (PERSON, dict(ev, reason='placed photo differs from the supplied file'))
    return PERSON, {'reason': 'supplied photo not found'}


def op_no_added_detail(path, a):
    """The placed headshot shows nothing the small supplied file lacks: it is not enlarged beyond the file's own
    pixels and does not extend past the file's edges. Never a fail: enlarged or extended pictures go to a person,
    who judges whether hair, skin or fabric detail was invented."""
    import pymupdf
    import cv2
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    asset = base._load_gray(base.asset_path(a, a['asset']))
    doc = pymupdf.open(path)
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            if not info.get('xref'):
                continue
            pix = pymupdf.Pixmap(doc, info['xref'])
            if pix.n - pix.alpha >= 3:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., 0]
            n, corners, state = base.find_asset(img, asset)
            if state != 'found':
                continue
            h, w = asset.shape
            scale = float(np.sqrt(cv2.contourArea(np.float32(corners)) / (w * h)))
            covered = cv2.contourArea(cv2.convexHull(np.clip(corners, 0, [img.shape[1], img.shape[0]]).astype(np.float32))) / (img.shape[0] * img.shape[1])
            ev = {'pixels_per_source_pixel': round(scale, 2), 'image_covered_by_source': round(float(covered), 3)}
            if scale <= 1.05 and covered >= 0.98:
                return 'pass', ev
            return PERSON, dict(ev, reason='enlarged or extended beyond the supplied file')
    return PERSON, {'reason': f'{a["asset"]} not found as a placed picture'}


def op_mark_with_text(path, a):
    """The supplied wordmark appears and the act name is also typeset outside it (not replaced by it)."""
    pdf = path.suffix.lower() == '.pdf'
    page, box, state = _asset_box(path, a, a['asset'], None if pdf else 0)
    if box is None:
        return PERSON, {'reason': 'wordmark not found' if state == 'none' else 'possible wordmark, unclear'}
    layer = _layer(path)
    lines = [l for l in layer.lines if contains(l.text, a['text'], False) and l.page == page]
    outside = [l for l in lines if base._overlap(l.bbox, box) < 0.3]
    if outside:
        return 'pass', {'typeset': outside[0].text}
    if layer.source == 'ocr' and not _reliable(layer):
        return PERSON, {'reason': 'typeset name not read clearly'}
    return 'fail', {'reason': 'the act name is not typeset beside the wordmark'}


def op_asset_finish(path, a):
    """Each placement of the supplied mark outside larger placed pictures (posters shown in a deck) is inked in
    the colour (ink) and/or sits on the ground colour (ground)."""
    import cv2
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    asset = base._load_gray(base.asset_path(a, a['asset']))
    s = 72 / base.RENDER_DPI
    seen, bad = 0, []
    flat = base._load_gray(base.asset_path(a, a['asset']), width=1600)
    unsure = False
    for i, scene in enumerate(base._scenes(path)):
        n, corners, state = base.find_asset(scene, asset)
        here = _confirm_here(scene, flat, corners) if state == 'unsure' else None
        if here is not None:
            corners = here
        elif state != 'found':
            score, corners = base.find_flat(scene, flat)
            if score < base.FLAT_MIN_SCORE:
                unsure = unsure or state == 'unsure'
                continue
        box = (corners[:, 0].min() * s, corners[:, 1].min() * s, corners[:, 0].max() * s, corners[:, 1].max() * s)
        area = (box[2] - box[0]) * (box[3] - box[1])
        posters = [b for b in _pdf_images(str(path)).get(i, []) if base._overlap(b, box) > 0.9 and (b[2] - b[0]) * (b[3] - b[1]) > 3 * area]
        if posters:
            continue
        seen += 1
        arr = np.asarray(base.render_pdf(path, i, 200)).astype(int)
        k = 200 / 72
        x0, y0, x1, y1 = (int(round(v * k)) for v in box)
        inner = arr[max(0, y0):y1, max(0, x0):x1].reshape(-1, 3)
        ring = np.concatenate([arr[max(0, y0 - 6):max(0, y0 - 2), max(0, x0):x1].reshape(-1, 3), arr[y1 + 2:y1 + 6, max(0, x0):x1].reshape(-1, 3)])
        if not len(inner) or not len(ring):
            return PERSON, {'reason': 'placement at the page edge'}
        values, counts = np.unique(ring // 4, axis=0, return_counts=True)
        ground = values[counts.argmax()] * 4
        ground_hex = '#%02X%02X%02X' % tuple(int(v) for v in ground)
        if a.get('ground') and not base._near_hex(ground_hex, [a['ground']], 8):
            bad.append({'page': i + 1, 'ground': ground_hex})
        if a.get('ink'):
            ink = inner[np.abs(inner - ground).sum(axis=1) > 120]
            if len(ink) < 20:
                return PERSON, {'reason': 'mark ink not measurable'}
            core = ink[np.abs(ink - np.median(ink, axis=0)).max(axis=1) <= 10]
            if len(core) < 0.6 * len(ink):
                bad.append({'page': i + 1, 'ink': 'not one solid colour'})
            else:
                ink_hex = '#%02X%02X%02X' % tuple(int(v) for v in core.mean(axis=0))
                if not base._near_hex(ink_hex, [a['ink']], 8):
                    bad.append({'page': i + 1, 'ink': ink_hex})
        break
    if bad:
        return 'fail', {'placements': bad}
    if not seen:
        if unsure:
            return PERSON, {'reason': 'a possible placement, unclear'}
        return ('pass', {'reason': 'not placed outside the poster pictures'}) if a.get('optional') else (PERSON, {'reason': 'mark not found'})
    return 'pass', {'placements': seen}


def op_shows_deliverable(path, a):
    """A design shown inside this deliverable (a poster in a deck) is the delivered file itself: its render is found
    in the deliverable, and every cell of a 4 x 4 grid over it matches (an earlier draft differs in places). Any
    cell that differs, or no placement found, goes to a person."""
    import cv2
    other = Path(a['_artifacts']) / a['deliverable']
    if not other.is_file():
        return PERSON, {'reason': 'the delivered file is not available', 'file': a['deliverable']}
    poster = np.asarray(ImageOps.grayscale(base.render_pdf(other, 0, 40)))
    for i, scene in enumerate(base._scenes(path)):
        n, corners, state = base.find_asset(scene, poster)
        if state != 'found':
            continue
        width = int(round(np.linalg.norm(corners[1] - corners[0])))
        if width < 40:
            return PERSON, {'reason': 'shown too small to compare'}
        height = int(round(width * poster.shape[0] / poster.shape[1]))
        small = cv2.resize(poster, (width, height), interpolation=cv2.INTER_AREA)
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [width, 0], [width, height], [0, height]]), np.float32(corners))
        back = cv2.warpPerspective(scene, np.linalg.inv(H), (width, height), flags=cv2.INTER_AREA)
        x, y = cv2.GaussianBlur(small, (0, 0), 1.5).astype(float), cv2.GaussianBlur(back, (0, 0), 1.5).astype(float)
        cells, low = [], []
        for gy in range(4):
            for gx in range(4):
                sl = (slice(gy * height // 4, (gy + 1) * height // 4), slice(gx * width // 4, (gx + 1) * width // 4))
                cx, cy = x[sl] - x[sl].mean(), y[sl] - y[sl].mean()
                if cx.std() < 5 and cy.std() < 5:
                    score = 1.0 if abs(x[sl].mean() - y[sl].mean()) < 20 else 0.0
                else:
                    score = float((cx * cy).sum() / (np.sqrt((cx * cx).sum() * (cy * cy).sum()) + 1e-9))
                cells.append(round(score, 2))
                if score < 0.6:
                    low.append((gy, gx))
        ev = {'page': i + 1, 'inliers': n, 'cells_below_0.6': len(low)}
        if low:
            return PERSON, dict(ev, reason='found, but parts of the design differ from the delivered file', cells=low[:6])
        return 'pass', ev
    return PERSON, {'reason': 'the delivered design was not found in the deck'}


def op_ground_mark(path, a):
    """If the supplied mark sits on the named ground colour, it is the light (reversed) version: on that ground
    its ink must be light. Located by matching the mark's shape in either polarity."""
    scenes = base._scenes(path)
    asset = base._load_gray(base.asset_path(a, a['asset']), width=600)
    img = _image_rgb(path) if path.suffix.lower() != '.pdf' else np.asarray(base.render_pdf(path, 0, base.RENDER_DPI)).astype(int)
    score, corners = base.find_flat(scenes[0], asset)
    n, c2, state = base.find_asset(scenes[0], asset)
    if state == 'found':
        corners, score = c2, 1.0
    if score < base.FLAT_MIN_SCORE:
        return PERSON, {'reason': 'mark not found (it may be absent or redrawn)'}
    x0, y0 = int(max(0, corners[:, 0].min())), int(max(0, corners[:, 1].min()))
    x1, y1 = int(min(img.shape[1], corners[:, 0].max())), int(min(img.shape[0], corners[:, 1].max()))
    ring = np.concatenate([img[max(0, y0 - 8):max(0, y0 - 2), x0:x1].reshape(-1, 3), img[y1 + 2:y1 + 8, x0:x1].reshape(-1, 3),
                           img[y0:y1, max(0, x0 - 8):max(0, x0 - 2)].reshape(-1, 3), img[y0:y1, x1 + 2:x1 + 8].reshape(-1, 3)])
    if not len(ring):
        return PERSON, {'reason': 'mark at the image edge'}
    values, counts = np.unique(ring // 4, axis=0, return_counts=True)
    ground = values[counts.argmax()] * 4
    ground_hex = '#%02X%02X%02X' % tuple(int(v) for v in ground)
    if not base._near_hex(ground_hex, [a['ground']], 10):
        return 'pass', {'ground': ground_hex, 'reason': 'not on that ground'}
    inner = img[y0:y1, x0:x1].reshape(-1, 3)
    ink = inner[np.abs(inner - ground).sum(axis=1) > 90]
    if len(ink) < 20:
        return PERSON, {'reason': 'mark ink not measurable'}
    lum = float((ink @ np.array([0.299, 0.587, 0.114])).mean())
    return ('pass' if lum >= 150 else 'fail'), {'ground': ground_hex, 'ink_luminance': round(lum)}


# ---------------------------------------------------------------- SVG artwork


def _svg_root(path: Path):
    from xml.etree import ElementTree as ET
    return ET.fromstring(path.read_text())


def _local(tag):
    return tag.split('}')[-1]


CUT_RX = r'cut\s*contour|cut[-_ ]?line|die[-_ ]?cut|kiss[-_ ]?cut|^cut$'


def _is_cut_layer(e, top_level=False) -> bool:
    """A separate cut layer: a group, or an element standing directly in the document, named as the cut contour.
    A path named "cut-line" inside the artwork group is part of the picture, not its own layer."""
    if _local(e.tag) != 'g' and not top_level:
        return False
    names = [v for k, v in e.attrib.items() if _local(k) in ('id', 'label', 'class', 'data-name')]
    return any(re.search(CUT_RX, v, re.I) for v in names)


def _svg_without_cut(path: Path) -> str:
    """The SVG text with any separate cut-contour layer removed (so it does not count as artwork)."""
    from xml.etree import ElementTree as ET
    root = _svg_root(path)
    for parent in list(root.iter()):
        for child in list(parent):
            if _is_cut_layer(child, top_level=parent is root):
                parent.remove(child)
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    return ET.tostring(root, encoding='unicode')


def _render_svg_text(svg: str, width: int):
    import cairosvg
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=width)
    return np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))


UNIT_MM = {'mm': 1.0, 'cm': 10.0, 'in': 25.4, 'pt': 25.4 / 72, 'pc': 25.4 / 6}


def _doc_mm(root):
    """The document's width and height in mm, when set in physical units (px is ambiguous: 72 or 96 per inch)."""
    out = []
    for k in ('width', 'height'):
        m = re.fullmatch(r'\s*([\d.]+)\s*(mm|cm|in|pt|pc)\s*', root.get(k) or '')
        if not m:
            return None
        out.append(float(m.group(1)) * UNIT_MM[m.group(2)])
    return out


def op_svg_size(path, a):
    """The artwork (any separate cut layer left out) measures long_mm on its long edge, within tol."""
    root = _svg_root(path)
    mm = _doc_mm(root)
    if mm is None:
        return PERSON, {'reason': 'document size not in physical units', 'width': root.get('width'), 'height': root.get('height')}
    arr = _render_svg_text(_svg_without_cut(path), 1600)
    ys, xs = np.where(arr[..., 3] > 16)
    if not len(xs):
        return PERSON, {'reason': 'nothing drawn'}
    per_px = mm[0] / arr.shape[1]
    w, h = (xs.max() - xs.min() + 1) * per_px, (ys.max() - ys.min() + 1) * per_px
    long_edge = max(w, h)
    ev = {'artwork_mm': [round(w, 2), round(h, 2)]}
    tol = a.get('tol', 0.5)
    if abs(long_edge - a['long_mm']) <= tol:
        return 'pass', ev
    return ('fail' if abs(long_edge - a['long_mm']) > 2 * tol else PERSON), ev


def op_svg_no_cutline(path, a):
    """No cut line is drawn into the artwork: outside a separate cut layer (id or label CutContour, cut line,
    die cut, kiss cut), no unfilled stroked outline runs round most of the artwork, and nothing is stroked in the
    cut-line magenta."""
    from xml.etree import ElementTree as ET
    root = _svg_root(path)
    full = _render_svg_text(_svg_without_cut(path), 800)
    ys, xs = np.where(full[..., 3] > 16)
    if not len(xs):
        return PERSON, {'reason': 'nothing drawn'}
    art = (xs.min(), ys.min(), xs.max(), ys.max())
    cut_ids = set()
    for parent in root.iter():
        for e in parent:
            if _is_cut_layer(e, top_level=parent is root):
                cut_ids |= {id(x) for x in e.iter()}
    shapes = ('path', 'circle', 'ellipse', 'rect', 'polygon', 'polyline')
    bad = []
    for e in root.iter():
        if id(e) in cut_ids or _local(e.tag) not in shapes:
            continue
        style = e.get('style') or ''
        get = lambda k: (re.search(rf'(?:^|;)\s*{k}\s*:\s*([^;]+)', style).group(1).strip() if re.search(rf'(?:^|;)\s*{k}\s*:', style) else e.get(k))
        fill, stroke = (get('fill') or '').lower(), (get('stroke') or '').lower()
        if not stroke or stroke == 'none':
            continue
        if stroke in ('#ff00ff', '#f0f', 'magenta'):
            bad.append({'element': _local(e.tag), 'reason': 'magenta cut stroke'})
            continue
        if fill not in ('none', 'transparent'):
            continue
        one = ET.Element(root.tag, root.attrib)
        one.append(e)
        arr = _render_svg_text(ET.tostring(one, encoding='unicode'), 800)
        ey, ex = np.where(arr[..., 3] > 16)
        if not len(ex):
            continue
        cover = ((ex.max() - ex.min()) * (ey.max() - ey.min())) / max(1, (art[2] - art[0]) * (art[3] - art[1]))
        if cover >= 0.85:
            bad.append({'element': _local(e.tag), 'reason': 'unfilled outline round the artwork', 'cover': round(float(cover), 2)})
    return ('fail', {'cut_lines': bad[:3]}) if bad else ('pass', {'cut_layer': bool(cut_ids)})


def _solid_colours(arr):
    """Colours of solid interior pixels (opaque, 3x3 neighbourhood one colour): anti-aliased edges left out."""
    a = arr.astype(int)
    solid = a[..., 3] == 255
    same = solid.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            same &= (np.abs(np.roll(np.roll(a, dy, 0), dx, 1) - a) <= 2).all(axis=2)
    return a[same][:, :3]


def op_main_ink(path, a):
    """The main ink (the colour covering most of the artwork, ground colours left out) is one of the hexes."""
    if path.suffix.lower() == '.svg':
        arr = _render_svg_text(_svg_without_cut(path), 900)
    else:
        arr = np.asarray(Image.open(path).convert('RGBA'))
    px = _solid_colours(arr)
    keep = np.ones(len(px), bool)
    for g in a.get('grounds', []) + ['#FFFFFF']:
        keep &= ~(np.abs(px - _rgb(g)) <= 3).all(axis=1)
    px = px[keep]
    if not len(px):
        return PERSON, {'reason': 'no ink found'}
    values, counts = np.unique(px, axis=0, return_counts=True)
    top = '#%02X%02X%02X' % tuple(values[counts.argmax()])
    share = counts.max() / counts.sum()
    ev = {'main_ink': top, 'share_of_ink': round(float(share), 2)}
    if base._near_hex(top, a['hexes'], 3):
        return 'pass', ev
    return 'fail', ev


def op_svg_glyph_ratio(path, a):
    """Live SVG text: the glyph (an ampersand) is set at ratio times the font size of the capitals beside it, in the
    same family. Within 0.1 passes; at cap height (within 0.15 of 1) fails; otherwise a person looks."""
    root = _svg_root(path)
    def family(e, inherited):
        style = e.get('style') or ''
        m = re.search(r'font-family\s*:\s*([^;]+)', style)
        return (m.group(1) if m else e.get('font-family') or inherited or '').strip('\'" ')
    def size(e, inherited):
        style = e.get('style') or ''
        m = re.search(r'font-size\s*:\s*([\d.]+)', style)
        v = m.group(1) if m else (re.match(r'[\d.]+', e.get('font-size') or '') or [None])[0]
        return float(v) if v else inherited
    runs = []
    def walk(e, fam, sz):
        fam, sz = family(e, fam), size(e, sz)
        if e.text and e.text.strip():
            runs.append((e.text, fam, sz))
        for c in e:
            walk(c, fam, sz)
            if c.tail and c.tail.strip():
                runs.append((c.tail, fam, sz))
    texts = [e for e in root.iter() if _local(e.tag) == 'text']
    for t in texts:
        walk(t, None, None)
    if not texts:
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    fam_rx = re.sub(r'\s+', r'\\s*', a['family'])
    amps = [r for r in runs if a['glyph'] in r[0] and re.search(fam_rx, r[1] or '', re.I)]
    if not amps:
        return 'pass', {'reason': 'no such glyph in that family'}
    caps = [r for r in runs if re.search(r'[A-Z]{2,}', r[0]) and re.search(fam_rx, r[1] or '', re.I) and a['glyph'] not in r[0]]
    results = []
    for text, fam, sz in amps:
        if re.search(r'[A-Z]', text.replace(a['glyph'], '')):
            results.append(1.0)                              # set in the same run as the capitals: same size
            continue
        if not caps or not sz:
            return PERSON, {'reason': 'capitals beside the glyph not found'}
        results.append(sz / caps[0][2])
    ev = {'ratios': [round(r, 2) for r in results]}
    if all(abs(r - a['ratio']) <= 0.1 for r in results):
        return 'pass', ev
    if any(abs(r - 1) <= 0.15 for r in results):
        return 'fail', ev
    return PERSON, ev


@functools.lru_cache(maxsize=8)
def _photo_gray(key: str, width: int = 1400):
    import cv2
    g = np.asarray(Image.open(key).convert('L'))
    return cv2.resize(g, (width, round(width * g.shape[0] / g.shape[1])), interpolation=cv2.INTER_AREA)


def op_built_from(path, a):
    """The drawing is traced from the named photo, not the others: the rendered drawing is feature-matched against
    each photo, and its own photo must give clearly more matched points (30 or more, three times any other's).
    Another photo clearly ahead fails; a drawing too freely redrawn to match any photo goes to a person."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'compared from the SVG artwork'}
    rgba = Image.fromarray(_render_svg_text(_svg_without_cut(path), 700))
    drawing = np.asarray(Image.alpha_composite(Image.new('RGBA', rgba.size, (255, 255, 255, 255)), rgba).convert('L'))
    points = {}
    for name in [a['photo']] + a['others']:
        n, _, state = base.find_asset(_photo_gray(str(base.asset_path(a, name))), drawing)
        points[name] = n if state != 'none' else 0
    own, other = points[a['photo']], max(points[o] for o in a['others'])
    ev = {'matched_points': points}
    if own >= 30 and own >= 3 * other:
        return 'pass', ev
    if other >= 30 and other >= 3 * own:
        return 'fail', ev
    return PERSON, ev


def op_no_halftone(path, a):
    """The drawing is built from solid shapes, not a field of halftone dots: no more than max_dots tiny dots."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG artwork'}
    root = _svg_root(path)
    vb = [float(v) for v in re.split(r'[\s,]+', (root.get('viewBox') or '0 0 0 0').strip())]
    extent = max(vb[2], vb[3]) if len(vb) == 4 and max(vb[2], vb[3]) > 0 else None
    if extent is None:
        return PERSON, {'reason': 'no viewBox'}
    dots = 0
    for e in root.iter():
        t = _local(e.tag)
        if t == 'circle' and float(e.get('r') or 0) < 0.01 * extent:
            dots += 1
        elif t == 'ellipse' and max(float(e.get('rx') or 0), float(e.get('ry') or 0)) < 0.01 * extent:
            dots += 1
        elif t == 'path':
            dots += len(re.findall(r'[Mm]', e.get('d') or '')) if len(e.get('d') or '') / max(1, len(re.findall(r'[Mm]', e.get('d') or ''))) < 40 else 0
    ev = {'tiny_dots': dots}
    return ('fail', ev) if dots > a.get('max_dots', 40) else ('pass', ev)


# ---------------------------------------------------------------- video


@functools.lru_cache(maxsize=12)
def _capture_frames(key: str, fps: float = 2.0):
    return tuple(np.asarray(ImageOps.grayscale(f)) for f in base.video_frames(key, fps))


def _frame_ncc(thumb, frame, width=320):
    """Correlation of the thumbnail with a whole frame, both reduced to one size (a title band costs a little)."""
    import cv2
    h = round(width * thumb.shape[0] / thumb.shape[1])
    x = cv2.resize(thumb, (width, h), interpolation=cv2.INTER_AREA).astype(float)
    y = cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA).astype(float)
    x, y = x - x.mean(), y - y.mean()
    return float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9))


def op_from_capture(path, a):
    """The thumbnail is built on a frame of its own capture: that video's frames match it clearly better than any
    other capture's, by matched feature points (15 or more, twice any other's) or, for frames with little texture,
    by whole-frame correlation (0.6 or more, 0.25 ahead of any other capture)."""
    import cv2
    scene = base._load_gray(path)
    points, ncc = {}, {}
    for name in [a['capture']] + a['others']:
        frames = _capture_frames(str(base.asset_path(a, name)))
        top, best = 0, -1.0
        for f in frames[:: max(1, len(frames) // 24)]:
            small = cv2.resize(f, (min(640, f.shape[1]), round(f.shape[0] * min(640, f.shape[1]) / f.shape[1])), interpolation=cv2.INTER_AREA)
            n, _, state = base.find_asset(scene, small)
            if state == 'found':
                top = max(top, n)
            best = max(best, _frame_ncc(scene, f))
        points[name], ncc[name] = top, round(best, 3)
    own_p, other_p = points[a['capture']], max((points[o] for o in a['others']), default=0)
    own_c, other_c = ncc[a['capture']], max((ncc[o] for o in a['others']), default=-1)
    ev = {'inliers': points, 'frame_correlation': ncc}
    if (own_p >= base.MIN_INLIERS and own_p > 2 * other_p) or (own_c >= 0.6 and own_c - other_c >= 0.25 and other_p < base.MIN_INLIERS):
        return 'pass', ev
    if (other_p >= base.MIN_INLIERS and other_p > 2 * own_p) or (other_c >= 0.6 and other_c - own_c >= 0.25 and own_p < base.MIN_INLIERS):
        return 'fail', ev
    return PERSON, ev


def op_largest_last_frame(path, a):
    """On the held last frame of a video, the named text is the largest text."""
    import tempfile
    frame = base.video_frames(str(path))[-1]
    with tempfile.TemporaryDirectory() as tmp:
        still = Path(tmp) / (Path(path).stem + '_last.png')
        frame.save(still)
        return base.op_largest_text(still, a)


# ---------------------------------------------------------------- registry

OPS_R2 = {
    'v2_style_lines': op_style_lines,
    'v2_size_vs': op_size_vs,
    'v2_size_pairs': op_size_pairs,
    'v2_directly_above': op_directly_above,
    'v2_stacked': op_stacked,
    'v2_inside_all': op_inside_all,
    'v2_figures': op_figures,
    'v2_initial_ratio': op_initial_ratio,
    'v2_sections': op_sections,
    'v2_placed_opacity': op_placed_opacity,
    'v2_pictured': op_pictured,
    'v2_names_by_photo': op_names_by_photo,
    'v2_same_photo': op_same_photo,
    'v2_no_added_detail': op_no_added_detail,
    'v2_mark_with_text': op_mark_with_text,
    'v2_asset_finish': op_asset_finish,
    'v2_shows_deliverable': op_shows_deliverable,
    'v2_ground_mark': op_ground_mark,
    'v2_svg_size': op_svg_size,
    'v2_svg_no_cutline': op_svg_no_cutline,
    'v2_main_ink': op_main_ink,
    'v2_svg_glyph_ratio': op_svg_glyph_ratio,
    'v2_built_from': op_built_from,
    'v2_no_halftone': op_no_halftone,
    'v2_from_capture': op_from_capture,
    'v2_largest_last_frame': op_largest_last_frame,
    'v2_paired': op_paired,
    'v2_followed_by': op_followed_by,
    'v2_text_on_ground': op_text_on_ground,
    'v2_position': op_position,
    'v2_mark': op_mark,
    'v2_page_size': op_page_size,
    'v2_no_blank_page': op_no_blank_page,
    'v2_bare_below': op_bare_below,
    'v2_tracking': op_tracking,
    'v2_description': op_description,
    'v2_names_full': op_names_full,
    'v2_spelled': op_spelled,
}
