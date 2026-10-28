"""Round 3, photo tasks B (PHOTO-19, 20, 24, 26, 28, 2026-10-28): operations the shared round-3 set could not express.

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person"; nothing
passes on a failed read, and a person answer carries a 'reason'. Loaded by objective_ops_r3 (OPS below).

Shared readings, the same on every file:
- Type on images is read line by line with OCR. A line's ink is read from its letter cores (pixels whose eight
  neighbours share their colour); where the letters are too thin to have a core, from the pixels furthest from the
  ground, and a reading that lies on the blend between the ground and an allowed colour (thin type in an allowed
  colour) goes to a person, never to a fail.
- Text roles are those of objective_ops_r3._roles, with two guards: tracked type ("O A T M E A L", as PDFs and OCR
  give letter-spaced capitals) is read with its letter spaces closed up, and a body size is recognised only where
  its running lines include a sentence (a full stop, question or exclamation mark after a word), so a page whose
  only running lines are headings has no body text.
- Text over a supplied photograph that is part of the photograph itself (a watch dial's numerals) is not type: it
  is found by comparing the line's pixels with the supplied photo laid over the deliverable.
"""
from __future__ import annotations

OPS: dict = {}          # filled at the end; defined first so a circular import finds it

import difflib
import functools
import re
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

import objective_ops as base
import objective_ops_r2 as r2
import objective_ops_r3 as r3
from objective_ops import PERSON, OCR_GOOD_CONF, canon, contains

SENTENCE = r'[a-z\)][.!?](?:\s|$)'
FOOT_SHARE = 0.12             # a running foot or footer line starts in the bottom 12% of its page or image

# ---------------------------------------------------------------- text lines, read the same way on every file


class PLine:
    """A PDF text line: text (tracked type rebuilt with its word spaces), box, size, baseline and spans."""
    __slots__ = ('text', 'bbox', 'size', 'conf', 'fonts', 'colors', 'page', 'source', 'size_ok', 'baseline', 'spans',
                 'page_w', 'page_h')

    def __init__(self, **kw):
        self.conf, self.source, self.size_ok = 100.0, 'pdf', True
        for k, v in kw.items():
            setattr(self, k, v)


def _tracked(raw: str) -> bool:
    tokens = raw.split()
    return len(tokens) >= 4 and sum(len(t) == 1 for t in tokens) >= 0.7 * len(tokens)


def _untrack(text: str) -> str:
    """Letter-spaced type with its letter spaces closed up: runs of two or more spaces are word breaks."""
    if not _tracked(text):
        return canon(text)
    return canon(' '.join(re.sub(r'\s', '', w) for w in re.split(r'\s{2,}', text.strip())))


@functools.lru_cache(maxsize=16)
def _pdf_lines(key: str):
    """Every text line of a PDF. Tracked type is rebuilt from its glyphs: a gap clearly wider than the tracking
    (median gap plus 0.15 em) is a word space, so "D i s h w a s h e r s a f e ." reads "Dishwasher safe."."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        for b in page.get_text('rawdict')['blocks']:
            for l in b.get('lines', []):
                spans = [s for s in l['spans'] if ''.join(c['c'] for c in s['chars']).strip()]
                if not spans:
                    continue
                chars = [c for s in spans for c in s['chars']]
                raw = ''.join(c['c'] for c in chars)
                size = max(s['size'] for s in spans)
                text = raw
                ink = [c for c in chars if c['c'].strip()]
                if _tracked(raw) and len(ink) >= 2:
                    gaps = [n['bbox'][0] - c['bbox'][2] for c, n in zip(ink, ink[1:])]
                    step = float(np.median(gaps))
                    text = ink[0]['c'] + ''.join((' ' if g > step + 0.15 * size else '') + n['c'] for g, n in zip(gaps, ink[1:]))
                box = (min(s['bbox'][0] for s in spans), min(s['bbox'][1] for s in spans), max(s['bbox'][2] for s in spans),
                       max(s['bbox'][3] for s in spans))
                sp = [dict(text=''.join(c['c'] for c in s['chars']), font=s['font'], size=s['size'], color=base._hex(s['color']),
                           bbox=tuple(s['bbox']), alpha=s.get('alpha', 255), serif=bool(s.get('flags', 0) & 4)) for s in spans]
                out.append(PLine(text=canon(text), bbox=box, size=size, page=page.number, baseline=max(s['origin'][1] for s in spans),
                                 spans=sp, fonts=[(s['text'], s['font'], round(s['size'], 2), s['color']) for s in sp],
                                 colors=[s['color'] for s in sp], page_w=page.rect.width, page_h=page.rect.height))
    return tuple(out)


class _Layer:
    def __init__(self, lines, source, width=0, height=0):
        self.lines, self.source, self.width, self.height = list(lines), source, width, height
        self.readable = bool(self.lines)


def _layer(path: Path):
    """PDF: the rebuilt live text (OCR of the render when there is none); images: OCR."""
    if path.suffix.lower() == '.pdf':
        lines = _pdf_lines(str(path))
        if lines:
            return _Layer(lines, 'pdf')
    m = base.merged(base.text_layers(path))
    return _Layer([l for l in m.lines if l.text.strip()], m.source, m.width, m.height)


def _text(l) -> str:
    return _untrack(l.text) if l.source != 'pdf' else canon(l.text)


def _is_type(l) -> bool:
    """A line judged as type: live text, or OCR read at 80% or more with three letters or figures (or a figure with
    a currency sign: a price)."""
    if l.source == 'pdf':
        return bool(l.text.strip())
    n = len(re.findall(r'[A-Za-z0-9]', l.text))
    return l.conf >= OCR_GOOD_CONF and (n >= 3 or (n >= 1 and bool(re.search(r'\d', l.text)) and bool(re.search(r'[$€£]', l.text))))


def _wording(l) -> bool:
    """A line that could carry wording (three letters or figures, or any figure)."""
    return len(re.findall(r'[A-Za-z0-9]', l.text)) >= 3 or bool(re.search(r'\d', l.text))


def _roles_b(layer):
    """(body size or None, {role: [lines]}) for body, heading, main, secondary, fine, caption, label, text (every
    line under the heading size), other (lines in no role) and largest (lines at the largest size, body or not).
    As objective_ops_r3._roles, with the two guards in the module notes."""
    pdf = layer.source == 'pdf'
    lines = [l for l in layer.lines if (pdf or (base._real(l) and l.size_ok)) and l.text.strip()]
    roles = {k: [] for k in ('body', 'heading', 'main', 'secondary', 'fine', 'caption', 'label', 'text', 'other', 'prose', 'largest')}
    if not lines:
        return None, roles
    txt = {id(l): _text(l) for l in lines}
    skel = lambda l: re.sub(r'\d+', '#', canon(txt[id(l)], False)).strip()
    seen = Counter(skel(l) for l in lines)
    running = [l for l in lines if re.search(r'[a-z]', txt[id(l)]) and seen[skel(l)] < 3]
    long_lines = [l for l in running if len(txt[id(l)].split()) >= 4]
    top = max(l.size for l in lines)
    top_tol = 0.3 if pdf else 0.08 * top
    roles['largest'] = [l for l in lines if l.size >= top - top_tol]
    body = None
    if long_lines:
        weight = {}
        for l in long_lines:
            key = round(l.size * 2) / 2 if pdf else round(l.size)
            weight[key] = weight.get(key, 0) + len(txt[id(l)])
        body = max(sorted(weight), key=weight.get)
        tol = 0.3 if pdf else 0.08 * body
        if not any(abs(l.size - body) <= tol and re.search(SENTENCE, txt[id(l)]) for l in running):
            body = None
    if body is None:
        # no body size: the largest lines are still the main heading where they stand well clear of the rest
        sizes = sorted(l.size for l in lines if l not in roles['largest'])
        if sizes and top >= 1.3 * sizes[len(sizes) // 2]:
            roles['main'] = list(roles['largest'])
        return None, roles
    for l in lines:
        if abs(l.size - body) <= tol and l in running:
            roles['body'].append(l)
        elif l.size >= 1.3 * body:
            roles['heading'].append(l)
            if l.size >= top - top_tol:
                roles['main'].append(l)
            else:
                roles['secondary'].append(l)
        elif l.size < 0.85 * body:
            roles['fine'].append(l)
            roles['caption' if re.search(r'[a-z]', txt[id(l)]) else 'label'].append(l)
        else:
            roles['other'].append(l)
        if l.size < 1.3 * body:
            roles['text'].append(l)
            if l in running:
                roles['prose'].append(l)                      # running text under heading size, body or not
    return body, roles


def _page_size(path: Path, l):
    if getattr(l, 'page_h', None):
        return l.page_w, l.page_h
    rgb = r3._pixels(str(path))
    return rgb.shape[1], rgb.shape[0]


def _footer(path, l) -> bool:
    return l.bbox[1] >= (1 - FOOT_SHARE) * _page_size(path, l)[1]


def _words(t: str):
    return re.findall(r"[a-z0-9&'@.$€£]+", canon(t, False))


def _is_part(line_text: str, whole: str) -> bool:
    """The line reads the text, or a run of its words set on a line of its own (a wrapped name or title)."""
    if contains(line_text, whole, False):
        return True
    lw, ww = [w.strip('.,;:') for w in _words(line_text)], [w.strip('.,;:') for w in _words(whole)]
    lw, ww = [w for w in lw if w], [w for w in ww if w]
    if not lw or sum(len(w) for w in lw) < 4:
        return False
    return any(ww[i:i + len(lw)] == lw for i in range(len(ww) - len(lw) + 1))


def _selected(path, l, item, roles) -> bool:
    """One selector: all, texts (contains), whole (the whole line), parts (_is_part), roles (+ max_words), patterns,
    footer, separate (a line of its own carrying the texts or patterns, at most max_other_words besides)."""
    t = _text(l)
    if item.get('all'):
        return True
    if 'texts' in item and any(r2._has(t, x) for x in item['texts']):
        return True
    if 'whole' in item and r2._whole(t, item['whole']):
        return True
    if 'parts' in item and any(_is_part(t, x) for x in item['parts']):
        return True
    if 'roles' in item and any(l in roles.get(r, []) for r in item['roles']):
        if 'max_words' not in item or len(t.split()) <= item['max_words']:
            return True
    if 'patterns' in item and any(r2._rxs(p, t) for p in item['patterns']):
        return True
    if item.get('footer') and _footer(path, l):
        return True
    if 'separate' in item:
        s = item['separate']
        hit = any(r2._has(t, x) for x in s.get('texts', [])) or any(r2._rxs(p, t) for p in s.get('patterns', []))
        if hit:
            rest = canon(t, False)
            for x in s.get('texts', []):
                rest = re.sub(r2._rx(x), ' ', rest)
            for p in s.get('patterns', []):
                rest = re.sub(p, ' ', rest, flags=re.I)
            rest = [w for w in re.findall(r'[a-z0-9]+', rest) if w not in s.get('ignore', [])]
            return len(rest) <= s.get('max_other_words', 2)
    return False


def _any(path, l, items, roles) -> bool:
    return any(_selected(path, l, it, roles) for it in items or [])


# ---------------------------------------------------------------- pixels: ink, grounds, photographs


def _hex(c):
    return r3._to_hex(c)


def _dist(c, hexes) -> float:
    return min(float(np.abs(np.asarray(c, float) - r3._hex_rgb(h)).max()) for h in hexes) if hexes else 999.0


def _on_blend(ink, ground, hexes) -> bool:
    """The reading lies on the blend between the ground and one of the colours, at least a third of the way: thin
    type in that colour whose letters never reach their full ink."""
    ink, ground = np.asarray(ink, float), np.asarray(ground, float)
    for h in hexes:
        c = r3._hex_rgb(h).astype(float)
        d = c - ground
        if (d * d).sum() < 400:
            continue
        t = float(((ink - ground) * d).sum() / (d * d).sum())
        if 0.33 <= t <= 1.1 and np.linalg.norm(ink - (ground + t * d)) <= 14:
            return True
    return False


@functools.lru_cache(maxsize=4)
def _flat_cached(key: str, tol: int):
    return r3._flat(r3._pixels(key), tol)


def _measure(path: Path, box, a):
    """Ink and ground of one text line on an image: {'ground', 'share', 'ink' (furthest pixels), 'cores' [(hex, px)]}."""
    rgb = r3._pixels(str(path))
    got = r3._ink_and_ground(rgb, box)
    if got is None:
        return None
    ink, ground, share = got
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    flat = _flat_cached(str(path), 6 if r3._lossy(path) else 3)[y0:y1, x0:x1]
    px = rgb[y0:y1, x0:x1]
    far = np.abs(px - ground).sum(axis=2) >= 60
    core = px[flat & far]
    cores = []
    if len(core) >= 12:
        q = core // 8
        values, counts = np.unique(q, axis=0, return_counts=True)
        groups = []
        for v, c in sorted(zip(values.tolist(), counts.tolist()), key=lambda t: -t[1]):
            for g in groups:
                if max(abs(v[i] - g[0][i]) for i in range(3)) <= 1:
                    g[1].append(v)
                    break
            else:
                groups.append((v, [v]))
        for g in groups:
            sel = np.zeros(len(core), bool)
            for v in g[1]:
                sel |= (q == v).all(axis=1)
            if sel.sum() >= 12:
                cores.append((_hex(np.median(core[sel], axis=0)), int(sel.sum())))
    return {'ground': ground, 'share': float(share), 'ink': ink, 'cores': cores}


def _judge(info, allowed, tol, ground=None) -> str:
    """'ok', 'bad' or 'unsure' for a line's ink against the allowed colours."""
    if info['cores']:
        verdict = 'ok'
        for hx, n in info['cores']:
            d = _dist(r3._hex_rgb(hx), allowed)
            if d <= tol:
                continue
            if d >= 30:
                return 'bad'
            verdict = 'unsure'
        return verdict
    d = _dist(info['ink'], allowed)
    if d <= tol:
        return 'ok'
    if _on_blend(info['ink'], info['ground'] if ground is None else ground, allowed):
        return 'unsure'
    return 'bad' if d >= 30 else 'unsure'


@functools.lru_cache(maxsize=4)
def _warped(key: str, name: str, dirs: tuple):
    """The supplied photo laid over the deliverable where it was found: (pixels, valid mask), or None."""
    import cv2
    try:
        ap = base.asset_path({'_asset_dirs': list(dirs)}, name)
    except FileNotFoundError:
        return None
    scene = base._load_gray(Path(key))
    asset = base._load_gray(ap)
    n, corners, state = base.find_asset(scene, asset)
    if state != 'found':
        return None
    h, w = asset.shape
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
    src = np.asarray(Image.open(ap).convert('RGB'))
    size = (scene.shape[1], scene.shape[0])
    warped = cv2.warpPerspective(src, H, size, flags=cv2.INTER_AREA)            # kept as uint8: caches stay small
    valid = cv2.warpPerspective(np.full((h, w), 255, np.uint8), H, size, flags=cv2.INTER_NEAREST) > 0
    return warped, valid


def _photo_content(path: Path, a, box) -> bool:
    """The line's pixels are the supplied photo's own (lettering inside the photograph), compared after a light blur
    so a pixel of misregistration does not count."""
    import cv2
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    pad = 4
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return False
    for name in a.get('photos', []):
        got = _warped(str(path), name, tuple(a.get('_asset_dirs') or []))
        if got is None:
            continue
        warped, valid = got
        v = valid[y0:y1, x0:x1]
        if v.mean() < 0.9:
            continue
        x = cv2.GaussianBlur(rgb[y0:y1, x0:x1].astype(np.float32), (0, 0), 1.2)
        y = cv2.GaussianBlur(warped[y0:y1, x0:x1].astype(np.float32), (0, 0), 1.2)
        diff = np.abs(x - y).max(axis=2)[v]
        if np.percentile(diff, 90) < 40:
            return True
    return False


def _in_photo(path: Path, a, box) -> bool:
    mask = r3._photo_mask(path, a)
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    sub = mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
    return sub.size > 0 and sub.mean() >= 0.5


def _fill_holes(mask):
    """The mask with its enclosed holes filled (OpenCV only): background not reachable from the border is a hole."""
    import cv2
    pad = np.pad(mask.astype(np.uint8), 1)
    seen = np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8)
    outside = pad.copy()
    cv2.floodFill(outside, seen, (0, 0), 2)
    return (outside[1:-1, 1:-1] != 2)


def _unread_marks(path: Path, a, grounds, lines, allowed, other_ok, tol):
    """Marks on the checked grounds that no OCR line covers (type OCR missed): groups of two or more letter-sized
    pieces inside a ground region. Returns the boxes of groups whose colour is not plainly an allowed one."""
    import cv2
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    outside = ~r3._photo_mask(path, a)
    near = r3._near_mask(rgb, grounds, r3._tol(path, a)) & outside
    n, labels, stats, _ = cv2.connectedComponentsWithStats(near.astype(np.uint8), connectivity=8)
    holes = np.zeros((h, w), bool)
    for i in range(1, n):
        if stats[i][4] < 0.005 * h * w:
            continue
        x, y, bw, bh = stats[i][:4]
        comp = labels[y:y + bh, x:x + bw] == i
        holes[y:y + bh, x:x + bw] |= _fill_holes(comp) & ~comp
    holes &= outside
    if not holes.any():
        return []
    covered = np.zeros((h, w), bool)
    for l in lines:
        x0, y0, x1, y1 = l.bbox
        m = 0.35 * (y1 - y0)
        covered[max(0, int(y0 - m)):int(y1 + m) + 1, max(0, int(x0 - m)):int(x1 + m) + 1] = True
    n, labels, stats, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8), connectivity=8)
    pieces = np.zeros((h, w), bool)
    heights = []
    rule = max(3, round(0.01 * min(h, w)))
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 6 or bh < 4 or bh > 0.2 * h:
            continue
        if area >= 0.003 * h * w and area >= 0.5 * bw * bh:
            continue                                            # a panel or picture inside the ground
        if min(bw, bh) <= rule and max(bw, bh) >= 6 * min(bw, bh):
            continue                                            # a rule
        sub = labels[y:y + bh, x:x + bw] == i
        if covered[y:y + bh, x:x + bw][sub].mean() >= 0.5:
            continue
        pieces[y:y + bh, x:x + bw] |= sub
        heights.append(bh)
    if not heights:
        return []
    k = max(3, int(np.median(heights)))
    grown = cv2.dilate(pieces.astype(np.uint8), np.ones((max(3, k // 3), k), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
    out, fine = [], 0
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        member = pieces & (labels == i)
        if cv2.connectedComponents(member.astype(np.uint8), connectivity=8)[0] - 1 < 2:
            continue                                            # a single piece: an icon or a stray mark, not wording
        info = _measure(path, (x, y, x + bw, y + bh), a)
        if info is not None and (_judge(info, list(allowed) + list(other_ok), tol) == 'ok' or
                                 _on_blend(info['ink'], info['ground'], list(allowed) + list(other_ok))):
            fine += 1                                           # unread, but its letters are an allowed colour
            continue
        out.append([int(x), int(y), int(bw), int(bh)])
    _unread_marks.fine = fine
    return out


# ---------------------------------------------------------------- type colour by ground


def op_type_ink(path, a):
    """Type of the selected lines (select: list of selectors, all lines by default) is in an allowed colour.
    grounds: the check covers lines on these grounds ('photo': type set on a photograph, lettering of the photograph
    itself left out); ground_must: instead, every selected line must sit on one of these grounds.
    colors: allowed inks; allow: [{selector, colors}] lines that may also use those colours (maybe: true, such a line
    in those colours goes to a person); maybe: selectors for lines that may or may not be meant (a wrong colour there
    goes to a person). other_marks_ok: colours unread marks may have (a monogram). optional: no such line passes
    (only when no type on those grounds was left unread); otherwise a person answers."""
    if path.suffix.lower() == '.pdf':
        return _type_ink_pdf(path, a)
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    body, roles = _roles_b(layer)
    tol = r3._tol(path, a) + 3
    sel_items = a.get('select') or [{'all': True}]
    everything = any(it.get('all') for it in sel_items)
    checked, bad, unsure = 0, [], []
    for l in layer.lines:
        sel = _any(path, l, sel_items, roles)
        maybe = not sel and _any(path, l, a.get('maybe'), roles)
        if not sel and not maybe:
            continue
        if not _is_type(l):
            if everything and _wording(l) and l.conf < OCR_GOOD_CONF and not _in_photo(path, a, l.bbox):
                info = _measure(path, l.bbox, a)
                if info and info['share'] >= 0.5 and _ground_ok(info['ground'], a, tol):
                    unsure.append({'line': l.text, 'reason': 'read with low confidence'})
            continue
        info = _measure(path, l.bbox, a)
        on_photo = _in_photo(path, a, l.bbox)
        if on_photo and _photo_content(path, a, l.bbox):
            continue                                            # lettering inside the photograph itself
        if a.get('ground_must'):
            checked += 1
            if info is None:
                unsure.append({'line': l.text, 'reason': 'not measurable'})
            elif info['share'] >= 0.5 and base._near_hex(_hex(info['ground']), a['ground_must'], tol + 3):
                continue
            elif on_photo:
                bad.append({'line': l.text, 'ground': 'photograph'})
            elif info['share'] >= 0.5 and _dist(info['ground'], a['ground_must']) >= 30:
                bad.append({'line': l.text, 'ground': _hex(info['ground'])})
            else:
                unsure.append({'line': l.text, 'ground': _hex(info['ground']), 'reason': 'ground not one clear colour'})
            continue
        grounds = a.get('grounds') or []
        if info is None:
            if on_photo and 'photo' in grounds or not on_photo and not grounds:
                unsure.append({'line': l.text, 'reason': 'not measurable'})
            continue
        if on_photo:
            if 'photo' not in grounds:
                continue
            checked += 1
            allowed = _allowed(path, l, a, roles)[0]
            # on a photograph only letter cores are trusted, and a stray flat patch of the photo may be among them
            if not info['cores'] or any(_dist(r3._hex_rgb(hx), allowed) > tol for hx, _ in info['cores']):
                unsure.append({'line': l.text, 'reason': 'type on a photograph; ink not clear'})
            continue
        hexes = [g for g in grounds if g != 'photo']
        if grounds:
            if info['share'] < 0.5:
                if hexes and _dist(info['ground'], hexes) <= tol + 3 and _judge(info, _allowed(path, l, a, roles)[0], tol) != 'ok':
                    unsure.append({'line': l.text, 'reason': 'ground not one clear colour'})
                continue
            if not base._near_hex(_hex(info['ground']), hexes, tol + 3):
                continue
        checked += 1
        allowed, soft = _allowed(path, l, a, roles)
        verdict = _judge(info, allowed, tol)
        if verdict == 'ok':
            continue
        ev = {'line': l.text, 'ink': info['cores'][0][0] if info['cores'] else _hex(info['ink']), 'ground': _hex(info['ground'])}
        if soft and _judge(info, allowed + soft, tol) == 'ok':
            unsure.append(dict(ev, reason='colour allowed only if this line is a label or caption'))
        elif verdict == 'bad' and not maybe and l.conf >= OCR_GOOD_CONF:
            bad.append(ev)
        else:
            unsure.append(dict(ev, reason='ink not clear' if verdict == 'unsure' else 'this line may not be one the check means'))
    if bad:
        return 'fail', {'not_matching': bad[:5]}
    # type OCR missed on a checked ground: its colour still matters where the check is about type colour (a missed
    # line on a ground_must ground already sits on an allowed ground)
    hexes = [g for g in (a.get('grounds') or []) if g != 'photo']
    if everything and hexes:
        # unread letters are fine only in the colours allowed for every line: one allowed only for some lines (the
        # affiliation's copper) cannot be placed without knowing which line it is
        missed = _unread_marks(path, a, hexes, layer.lines, list(a.get('colors', [])), a.get('other_marks_ok', []), tol)
        if missed:
            unsure.append({'reason': 'marks OCR did not read on the checked ground', 'boxes': missed[:4]})
        elif getattr(_unread_marks, 'fine', 0):
            checked += _unread_marks.fine                       # type OCR missed, judged by its letters' colour
    if unsure:
        return PERSON, {'reason': 'some lines could not be decided', 'lines': unsure[:5]}
    if not checked:
        if a.get('optional', True):
            return 'pass', {'reason': 'no such type (the check applies only where it appears)'}
        return PERSON, {'reason': 'the text was not found'}
    return 'pass', {'lines_checked': checked}


def _ground_ok(ground, a, tol):
    hexes = [g for g in (a.get('grounds') or a.get('ground_must') or []) if g != 'photo']
    return not hexes or base._near_hex(_hex(ground), hexes, tol + 3)


def _near_text(l, item) -> bool:
    """An OCR line close to one of the item's texts (85% alike, or a run of its words) but not matching it: a letter
    may be misread (Fjordline AI read as "Fjordline Al")."""
    if l.source == 'pdf':
        return False
    t = canon(_text(l), False)
    for x in item.get('parts', []) + item.get('texts', []) + item.get('whole', []):
        x = canon(x, False)
        if difflib.SequenceMatcher(None, t, x).ratio() >= 0.85:
            return True
        words = x.split()
        n = len(t.split())
        for i in range(len(words) - n + 1):
            if n and difflib.SequenceMatcher(None, t, ' '.join(words[i:i + n])).ratio() >= 0.85 and len(t) >= 4:
                return True
    return False


def _allowed(path, l, a, roles):
    """(allowed colours, colours allowed only if a doubtful selector is meant) for one line."""
    allowed, soft = list(a.get('colors', [])), []
    no_roles = not any(roles.get(k) for k in ('body', 'fine', 'heading'))
    for it in a.get('allow', []):
        if _selected(path, l, it, roles):
            (soft if it.get('maybe') else allowed).extend(it['colors'])
        elif _near_text(l, it) or ('roles' in it and no_roles):
            soft.extend(it['colors'])                 # a misread allowed line, or roles unknown (no body size)
    return allowed, [c for c in soft if c not in allowed]


def _type_ink_pdf(path, a):
    """op_type_ink on a PDF: each span's colour from the file, the colour behind it from the rendered page."""
    key = str(path)
    layer = _layer(path)
    if layer.source != 'pdf':
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    body, roles = _roles_b(layer)
    sel_items = a.get('select') or [{'all': True}]
    checked, bad, unsure = 0, [], []
    for l in layer.lines:
        sel = _any(path, l, sel_items, roles)
        maybe = not sel and _any(path, l, a.get('maybe'), roles)
        if not sel and not maybe:
            continue
        allowed, soft = _allowed(path, l, a, roles)
        for sp in l.spans:
            if not sp['text'].strip():
                continue
            g = r2._ground(key, l.page, sp['bbox'], sp['color'])
            if a.get('ground_must'):
                checked += 1
                if g in ('photo', 'mixed') or not base._near_hex(g, a['ground_must'], 6):
                    (unsure if g == 'mixed' else bad).append({'span': sp['text'][:40], 'ground': g})
                continue
            grounds = a.get('grounds') or []
            if grounds:
                on = (g == 'photo' and 'photo' in grounds) or (g not in ('photo', 'mixed') and base._near_hex(g, [x for x in grounds if x != 'photo'], 6))
                if not on:
                    if g == 'mixed' and not base._near_hex(sp['color'], allowed, 2):
                        unsure.append({'span': sp['text'][:40], 'reason': 'ground not one colour'})
                    continue
            checked += 1
            if base._near_hex(sp['color'], allowed, 2):
                continue
            ev = {'span': sp['text'][:40], 'colour': sp['color'], 'ground': g}
            if soft and base._near_hex(sp['color'], soft, 2):
                unsure.append(dict(ev, reason='colour allowed only if this line is a label or caption'))
            elif maybe:
                unsure.append(dict(ev, reason='this line may not be one the check means'))
            else:
                bad.append(ev)
    if bad:
        return 'fail', {'not_matching': bad[:6]}
    if unsure:
        return PERSON, {'reason': 'some type could not be decided', 'spans': unsure[:5]}
    if not checked:
        return ('pass', {'reason': 'no such type (the check applies only where it appears)'}) if a.get('optional', True) else \
            (PERSON, {'reason': 'the text was not found'})
    return 'pass', {'spans_checked': checked}


def op_type_has_colour(path, a):
    """Some type is set in the colour: a line read at 80% or more whose letter cores are that colour. None found
    fails only where every line's ink was read from its cores (thin type may be the colour unseen)."""
    layer = _layer(path)
    if layer.source == 'pdf':
        hit = [sp['text'] for l in layer.lines for sp in l.spans if base._near_hex(sp['color'], a['hexes'], 2)]
        return ('pass', {'lines': hit[:3]}) if hit else ('fail', {'reason': 'no type in the colour'})
    tol = r3._tol(path, a) + 3
    lines = [l for l in layer.lines if _is_type(l) and not (_in_photo(path, a, l.bbox) and _photo_content(path, a, l.bbox))]
    if not lines:
        return PERSON, {'reason': 'no readable type'}
    sure = True
    for l in lines:
        info = _measure(path, l.bbox, a)
        if info is None:
            sure = False
            continue
        if info['cores']:
            if any(_dist(r3._hex_rgb(hx), a['hexes']) <= tol for hx, _ in info['cores']):
                return 'pass', {'line': l.text}
        else:
            sure = False
            if _dist(info['ink'], a['hexes']) <= tol:
                return 'pass', {'line': l.text}
    if sure and getattr(base.merged(base.text_layers(path)), 'confident_all', False):
        return 'fail', {'reason': 'no line set in the colour', 'lines': len(lines)}
    return PERSON, {'reason': 'no line clearly in the colour; thin type may be'}


# ---------------------------------------------------------------- where a colour may appear


def op_colour_only_as(path, a):
    """The colour appears only as rules (rules: 'thin', a rule up to 1% of the short side thick, or 'hairline', up to
    0.4%; a rule is at least six times as long as thick) and in the allowed text lines (allow: selectors such as
    parts of a named text, roles, footer lines); never as other type, a ground or a panel. ambiguous: selectors for
    lines that may or may not be allowed (colour there goes to a person). PDFs: spans and drawn shapes; type_only:
    only type counts, and allowed type must sit on foot_grounds where given."""
    if path.suffix.lower() == '.pdf':
        return _colour_only_pdf(path, a)
    import cv2
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    tol = r3._tol(path, a)
    outside = ~r3._photo_mask(path, a)
    hit = r3._near_mask(rgb, a['hexes'], tol) & outside
    if hit.sum() < 12:
        return 'pass', {'reason': 'colour not used'}
    layer = _layer(path)
    body, roles = _roles_b(layer)
    real = [l for l in layer.lines if _is_type(l)]
    ok_boxes = [l.bbox for l in real if _any(path, l, a.get('allow'), roles)]
    doubt_boxes = [l.bbox for l in real if not _any(path, l, a.get('allow'), roles) and
                   (_any(path, l, a.get('ambiguous'), roles) or any(_near_text(l, it) for it in a.get('allow', [])))]
    if body is None and any('roles' in it for it in (a.get('allow') or []) + (a.get('ambiguous') or [])):
        # no body size, so captions and labels cannot be told from other type: any line may be one
        doubt_boxes += [l.bbox for l in real if not _any(path, l, a.get('allow'), roles)]
    text_lines = [l.bbox for l in layer.lines]
    wanted_texts = [x for it in a.get('allow', []) for x in it.get('parts', []) + it.get('texts', []) + it.get('whole', [])]
    found_wanted = bool([b for b in ok_boxes]) if wanted_texts else True
    hair = max(3, round(0.004 * min(h, w)))
    thin = max(3, round(0.01 * min(h, w)))
    limit = hair if a.get('rules') == 'hairline' else thin

    def inside(b, boxes):
        cx, cy = b[0] + b[2] / 2, b[1] + b[3] / 2
        for x0, y0, x1, y1 in boxes:
            m = 0.3 * (y1 - y0)
            if x0 - m <= cx <= x1 + m and y0 - m <= cy <= y1 + m:
                return True
        return False
    roles_n = Counter()
    bad, unsure = [], []
    for comp, st in r3._components(hit, 12):
        x, y, bw, bh, area = (int(v) for v in st)
        box = (x, y, bw, bh)
        short, long_ = min(bw, bh), max(bw, bh)
        if a.get('rules') and long_ >= 6 * short:
            if short <= limit:
                roles_n['rule'] += 1
                continue
            if short <= thin:
                unsure.append({'box': list(box), 'reason': 'a rule thicker than a hairline'})
                continue
        if inside(box, ok_boxes):
            roles_n['allowed text'] += 1
            continue
        if inside(box, doubt_boxes):
            unsure.append({'box': list(box), 'reason': 'in a line that may be a caption or label'})
            continue
        if area < 40:
            unsure.append({'box': list(box), 'reason': 'a speck'})
            continue
        if not found_wanted and bh <= 0.1 * h and inside(box, text_lines) is False and area < 0.002 * h * w:
            unsure.append({'box': list(box), 'reason': 'letters in the colour, and the allowed line was not read'})
            continue
        bad.append({'box': list(box), 'area_px': area})
    ev = {'pieces': dict(roles_n)}
    if bad:
        return 'fail', dict(ev, not_allowed=bad[:4])
    if unsure:
        return PERSON, dict(ev, reason='some pieces in the colour could not be placed', pieces_unsure=unsure[:4])
    return 'pass', ev


def _colour_only_pdf(path, a):
    key = str(path)
    layer = _layer(path)
    body, roles = _roles_b(layer) if layer.source == 'pdf' else (None, {})
    bad, unsure, n = [], [], 0
    for l in (layer.lines if layer.source == 'pdf' else []):
        for sp in l.spans:
            if not sp['text'].strip() or not base._near_hex(sp['color'], a['hexes'], 3):
                continue
            n += 1
            if _any(path, l, a.get('allow'), roles):
                if a.get('foot_grounds'):
                    g = r2._ground(key, l.page, sp['bbox'], sp['color'])
                    if g in ('photo', 'mixed'):
                        unsure.append({'span': sp['text'][:40], 'ground': g})
                    elif not base._near_hex(g, a['foot_grounds'], 6):
                        bad.append({'span': sp['text'][:40], 'ground': g})
                continue
            if _any(path, l, a.get('ambiguous'), roles):
                unsure.append({'span': sp['text'][:40], 'reason': 'may be a caption or label'})
                continue
            bad.append({'span': sp['text'][:40], 'page': l.page + 1})
    if not a.get('type_only'):
        hair, thin = 1.5, 3.0
        limit = hair if a.get('rules') == 'hairline' else thin
        for s in r3._pdf_shapes(key):
            if s['on_image'] or not base._near_hex(s['colour'], a['hexes'], 3):
                continue
            n += 1
            x0, y0, x1, y1 = s['box']
            long_ = max(x1 - x0, y1 - y0)
            if a.get('rules') and long_ >= 6 * s['thick']:
                if s['thick'] <= limit:
                    continue
                if s['thick'] <= thin:
                    unsure.append({'page': s['page'] + 1, 'thick_pt': s['thick'], 'reason': 'a rule thicker than a hairline'})
                    continue
            bad.append({'page': s['page'] + 1, 'shape': s['kind'], 'box': [round(v) for v in s['box']]})
    if bad:
        return 'fail', {'not_allowed': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'some uses of the colour could not be placed', 'uses': unsure[:4]}
    return 'pass', {'uses': n} if n else {'reason': 'colour not used'}


# ---------------------------------------------------------------- marks, cut-outs and photographs


def _mark_box(path, a):
    if a.get('asset'):
        try:
            page, box, state = r2._asset_box(path, a, a['asset'], 0)
        except FileNotFoundError:
            box = None
        if box is not None:
            return box
    layer = _layer(path)
    hits = [l for l in layer.lines if _is_type(l) and any(contains(_text(l), t, False) for t in a.get('texts', []))]
    return hits[0].bbox if hits else None


def op_mark_ground(path, a):
    """The mark (texts: a line carrying it; asset: the supplied file) sits on one of the grounds: the commonest colour
    round it. Not found: a person (it may be drawn differently)."""
    box = _mark_box(path, a)
    if box is None:
        return PERSON, {'reason': 'mark not found (it may be absent or redrawn)'}
    rgb = r3._pixels(str(path))
    got = r3._ink_and_ground(rgb, box)
    if got is None:
        return PERSON, {'reason': 'ground not measurable'}
    ink, ground, share = got
    tol = r3._tol(path, a) + 3
    ev = {'ground': _hex(ground), 'share': round(share, 2)}
    if share >= 0.5 and base._near_hex(_hex(ground), a['grounds'], tol):
        return 'pass', ev
    if share >= 0.5 and _dist(ground, a['grounds']) >= 30:
        return 'fail', ev
    return PERSON, dict(ev, reason='ground not one clear colour')


def _found_photos(path, a, names):
    out = []
    for name in names:
        try:
            page, box, state = r2._asset_box(path, a, name, 0)
        except FileNotFoundError:
            continue
        if box is not None:
            out.append((name, box))
    return out


def op_sitter_ground(path, a):
    """The cut-out subject of the supplied photo (photo, or the first of photos found) sits on a solid ground of one
    of the colours: the flat one-colour area wrapping the subject (objective_ops_r3._ground_round). No such flat
    area (a full photo, or a shaded ground) goes to a person."""
    names = [a['photo']] if a.get('photo') else a.get('photos', [])
    found = _found_photos(path, a, names)
    if not found:
        return PERSON, {'reason': 'supplied photo not found'}
    name, box = found[0]
    rgb = r3._pixels(str(path))
    ground = _sitter_ground_b(rgb, box)
    if ground is None:
        return PERSON, {'reason': 'no solid ground round the subject', 'photo': name}
    tone = np.median(rgb[ground], axis=0)
    tol = r3._tol(path, a)
    ev = {'photo': name, 'ground': _hex(tone)}
    if _dist(tone, a['hexes']) <= tol:
        return 'pass', ev
    return ('fail' if _dist(tone, a['hexes']) >= 30 else PERSON), ev


def op_each_photo(path, a):
    """The check `then` holds for every supplied photo found among photos ({photo} in it is filled with each). known:
    other supplied photos expected on the file (left out of the search for strays but checked too when check_known).
    Every photographic region must belong to a found photo; otherwise a person answers (a photo not among the
    supplied files). None found and no other photograph: a pass (the check applies only where one appears)."""
    import cv2
    names = list(a.get('photos', []))
    known = [n for n in a.get('known', []) if n not in names]
    found = _found_photos(path, a, names)
    found_known = _found_photos(path, a, known)
    results = []
    for name, box in found + (found_known if a.get('check_known') else []):
        sub = _fill(a['then_by'][name], name) if a.get('then_by') and name in a['then_by'] else _fill(a.get('then'), name)
        if not sub:
            results.append((name, 'pass', {'found': name}))
            continue
        st, ev = base.run(path, dict(sub, **{k: v for k, v in a.items() if k.startswith('_')}))
        results.append((name, st, ev))
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    tex = r3._photo_mask_cached(str(path), (), tuple(a.get('_asset_dirs') or []), -1, False)
    rest = tex.copy()
    for name, box in found + found_known:
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        rest[max(0, y0 - 12):y1 + 12, max(0, x0 - 12):x1 + 12] = False
    n, labels, stats, _ = cv2.connectedComponentsWithStats(rest.astype(np.uint8), connectivity=8)
    strays = [list(map(int, stats[i][:4])) for i in range(1, n) if stats[i][4] >= 0.01 * h * w]
    if any(st == 'fail' for _, st, _ in results):
        return 'fail', {'photos': [(nm, st, ev) for nm, st, ev in results if st == 'fail'][:3]}
    if any(st == PERSON for _, st, _ in results):
        return PERSON, {'reason': 'a photo could not be decided', 'photos': [(nm, ev) for nm, st, ev in results if st == PERSON][:3]}
    if strays:
        return PERSON, {'reason': 'a photograph not matched to a supplied file', 'regions': strays[:3],
                        'checked': [nm for nm, _, _ in results]}
    if not results:
        return 'pass', {'reason': 'no such photo (the check applies only where one appears)'}
    return 'pass', {'checked': [nm for nm, _, _ in results]}


def _fill(obj, name):
    if isinstance(obj, str):
        return obj.replace('{photo}', name)
    if isinstance(obj, list):
        return [_fill(x, name) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, name) for k, v in obj.items()}
    return obj


def op_palette_marks(path, a):
    """objective_ops_r3 palette check (every flat designed colour is a palette colour), where the named marks
    (marks: [{asset} or {whole: [text]}]) may also use mark_hexes inside their own box (a wordmark's original ink)."""
    rgb, flat, outside = r3._designed(path, a)
    if flat.sum() < 200:
        return PERSON, {'reason': 'almost no flat designed area found'}
    tol = r3._tol(path, a)
    off = flat & ~r3._near_mask(rgb, a['hexes'], tol)
    layer = _layer(path)
    boxes = []
    for m in a.get('marks', []):
        if m.get('asset'):
            try:
                page, box, state = r2._asset_box(path, a, m['asset'], 0)
            except FileNotFoundError:
                box = None
            if box is not None:
                boxes.append(box)
        if m.get('whole'):
            boxes += [l.bbox for l in layer.lines if _is_type(l) and r2._whole(_text(l), m['whole'])]
    extra = r3._near_mask(rgb, a.get('mark_hexes', []), tol)
    for x0, y0, x1, y1 in boxes:
        sl = (slice(max(0, int(y0) - 3), int(y1) + 4), slice(max(0, int(x0) - 3), int(x1) + 4))
        off[sl] &= ~extra[sl]
    bad = {}
    for comp, st in r3._components(off):
        c = _hex(np.median(rgb[comp], axis=0))
        bad[c] = bad.get(c, 0) + int(st[4])
    if bad:
        top = sorted(bad.items(), key=lambda kv: -kv[1])[:5]
        return 'fail', {'outside_palette': [f'{c} ({n} px)' for c, n in top]}
    return 'pass', {'palette': a['hexes'], 'marks_found': len(boxes)}


def op_solid_raster(path, a):
    """Type, grounds and panels on an image are solid palette colours: every flat designed colour is a palette colour
    (a tint or transparency shows as an off-palette blend), no shaded (gradient) area outside the photographs, and no
    type over a photograph (where its transparency could not be seen). Off-palette colours and shaded areas go to a
    person: pixels cannot tell a tint from a wrong solid colour."""
    import cv2
    rgb, flat, outside = r3._designed(path, a)
    tol = r3._tol(path, a)
    h, w = rgb.shape[:2]
    off = flat & ~r3._near_mask(rgb, a['hexes'], tol)
    odd = [_hex(np.median(rgb[c], axis=0)) for c, st in r3._components(off)]
    loose = r3._flat(rgb, 6 if r3._lossy(path) else 2)
    edge = cv2.dilate(loose.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    smooth = outside & ~edge
    n, labels, stats, _ = cv2.connectedComponentsWithStats(smooth.astype(np.uint8), connectivity=8)
    shaded = [list(map(int, stats[i][:4])) for i in range(1, n) if stats[i][4] >= 0.003 * h * w]
    layer = _layer(path)
    over = [l.text for l in layer.lines if _is_type(l) and _in_photo(path, a, l.bbox) and not _photo_content(path, a, l.bbox)]
    if odd or shaded or over:
        return PERSON, {'reason': 'an off-palette flat colour, a shaded area or type over a photograph', 'colours': odd[:4],
                        'shaded': shaded[:3], 'type_on_photo': over[:3]}
    return 'pass', {'palette': a['hexes']}


# ---------------------------------------------------------------- line length and position by role


def _rows(lines):
    """OCR may split one set line into pieces: pieces on one row (sharing 60% of their height, gap under 1.5 line
    heights) are joined, left to right."""
    rows = []
    for l in sorted(lines, key=lambda l: (l.page, l.bbox[0])):
        for r in rows:
            last = r[-1]
            hgt = min(last.bbox[3] - last.bbox[1], l.bbox[3] - l.bbox[1])
            over = min(last.bbox[3], l.bbox[3]) - max(last.bbox[1], l.bbox[1])
            if last.page == l.page and hgt > 0 and over >= 0.6 * hgt and 0 <= l.bbox[0] - last.bbox[2] <= 1.5 * hgt:
                r.append(l)
                break
        else:
            rows.append([l])
    return rows


def op_line_chars(path, a):
    """No line of the selected text runs longer than max_chars (spaces included; tracked type counted with its
    letter spaces closed up). Selected: lines of the roles (body) and lines that are a named text or part of it
    (parts). Any line of any kind over the limit: a fail only for a selected line of live PDF text; any other line
    over the limit, or an OCR count within 3 of the limit, goes to a person (OCR may join or miss characters)."""
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    body, roles = _roles_b(layer)
    pdf = layer.source == 'pdf'
    lines = [l for l in layer.lines if pdf or (base._real(l) and not (_in_photo(path, a, l.bbox) and _photo_content(path, a, l.bbox)))]
    if not pdf and not getattr(base.merged(base.text_layers(path)), 'confident_all', True):
        low = [l.text for l in layer.lines if _wording(l) and l.conf < OCR_GOOD_CONF and not _in_photo(path, a, l.bbox)]
        if low:
            return PERSON, {'reason': 'some text read with low confidence', 'lines': low[:3]}
    sel = [{'roles': a.get('roles', [])}] + ([{'parts': a['parts']}] if a.get('parts') else [])
    longest, over, near = 0, [], []
    for row in (_rows(lines) if not pdf else [[l] for l in lines]):
        t = canon(' '.join(_text(l) for l in row))
        n = len(t)
        longest = max(longest, n)
        if n > a['max_chars']:
            chosen = any(_any(path, l, sel, roles) for l in row)
            over.append({'line': t[:80], 'chars': n, 'selected': chosen})
        elif not pdf and n > a['max_chars'] - 3:
            near.append({'line': t[:80], 'chars': n})
    if over:
        if pdf and any(o['selected'] for o in over):
            return 'fail', {'too_long': [o for o in over if o['selected']][:3], 'max': a['max_chars']}
        return PERSON, {'reason': 'a line over the limit that the definition does not settle, or read by OCR', 'lines': over[:3]}
    if near:
        return PERSON, {'reason': 'an OCR count close to the limit', 'lines': near[:3]}
    return 'pass', {'longest': longest, 'max': a['max_chars']}


def op_above_role(path, a):
    """The mark (whole: a line reading it; asset: the supplied file) sits above every line of the role (main: the
    largest heading), on the same page."""
    layer = _layer(path)
    body, roles = _roles_b(layer)
    target = roles.get(a['role'], [])
    if body is None or not target:
        return PERSON, {'reason': f'no {a["role"]} text found (no body size to set roles)'}
    box = None
    if a.get('asset'):
        try:
            page, box, state = r2._asset_box(path, a, a['asset'], 0)
        except FileNotFoundError:
            box = None
    if box is None and a.get('whole'):
        hits = [l for l in layer.lines if _is_type(l) and r2._whole(_text(l), a['whole']) and l not in target]
        box = hits[0].bbox if hits else None
    if box is None:
        return PERSON, {'reason': 'mark not found'}
    top = min(l.bbox[1] for l in target)
    hgt = max(l.bbox[3] - l.bbox[1] for l in target)
    ev = {'mark_bottom': round(box[3], 1), 'role_top': round(top, 1), 'role_text': target[0].text}
    if box[3] <= top + 2 - a.get('min_gap', 0) * hgt:
        return 'pass', ev
    if a.get('min_gap') and box[3] <= top + 2:
        return PERSON, dict(ev, reason='above, but close to the heading')
    if box[1] >= max(l.bbox[3] for l in target) - 2:
        return 'fail', ev
    return PERSON, dict(ev, reason='mark and heading overlap in height')


# ---------------------------------------------------------------- PDF type style by role


def _style_select(path, layer, roles, a):
    """Lines a PDF style check covers, and lines it may cover (a person decides those).
    select: role names ('main', 'secondary', 'body', 'text', 'fine', 'largest'), 'page_main' (each page's largest
    heading: only where it differs from the document's main heading, a doubtful line), or dicts: {'whole': [...]},
    {'products': names} (lines reading a name exactly), {'brand': word} (lines carrying it; running feet doubtful),
    {'colour': hex, 'foot': True} (running feet in the colour), {'below': texts} (the line directly below each),
    {'pattern': regex}, {'family': name} (lines set in that family).
    except: the same kinds of selector, left out."""
    sure, doubt = [], []
    lines = layer.lines
    for s in a.get('select', []):
        if isinstance(s, str):
            if s == 'page_main':
                main = roles.get('main', [])
                for p in sorted({l.page for l in lines}):
                    on = [l for l in lines if l.page == p and (not roles.get('body') or l in roles.get('heading', []))]
                    if not on:
                        continue
                    top = max(l.size for l in on)
                    doubt += [l for l in on if l.size >= top - 0.3 and l not in main]
            elif s.startswith('?'):
                doubt += roles.get(s[1:], [])
            else:
                sure += roles.get(s, [])
            continue
        if 'whole' in s:
            sure += [l for l in lines if r2._whole(_text(l), s['whole'])]
        if 'products' in s:
            sure += [l for l in lines if _product_of(_text(l), s['products'])]
        if 'brand' in s:
            for l in lines:
                if re.search(r'\b' + s['brand'] + r'\b', canon(_text(l), False), re.I):
                    (doubt if _footer(path, l) else sure).append(l)
        if 'colour' in s:
            sure += [l for l in lines if _footer(path, l) and any(base._near_hex(c, [s['colour']], 3) for c in l.colors)]
        if 'below' in s:
            for t in s['below']:
                for an in [l for l in lines if contains(_text(l), t, False)]:
                    nxt = r2._nearest(an, lines, 'below', 2.5 * an.size)
                    if nxt is not None:
                        sure.append(nxt)
        if 'pattern' in s:
            sure += [l for l in lines if r2._rxs(s['pattern'], _text(l))]
        if 'family' in s:
            fam = re.sub(r'[^a-z0-9]', '', s['family'].lower())
            sure += [l for l in lines if any(base._font_parts(f)[0] == fam for _, f, _, _ in l.fonts)]
    h1 = [l for s in a.get('select', []) if isinstance(s, dict) and 'h1' in s for l in lines if r2._whole(_text(l), s['h1'])]
    if h1 and 'main' in a.get('select', []) and not set(map(id, roles.get('main', []))) <= set(map(id, h1)):
        # the brand names its display heading by a sample line (THORNMERE HOME); where the largest heading is another
        # line, which of the two is "the main heading" is not settled: both are doubtful
        sure = [l for l in sure if l not in roles.get('main', [])]
        doubt += list(roles.get('main', [])) + h1
    out = lambda l: any(_style_hit(path, l, e, roles) for e in a.get('except', []))
    sure = [l for l in dict.fromkeys(sure) if not out(l)]
    doubt = [l for l in dict.fromkeys(doubt) if not out(l) and l not in sure]
    return sure, doubt


def _style_hit(path, l, e, roles):
    if isinstance(e, str):
        return l in roles.get(e, [])
    if 'whole' in e:
        return r2._whole(_text(l), e['whole'])
    if 'pattern' in e:
        return r2._rxs(e['pattern'], _text(l))
    return False


def _product_of(t: str, names):
    flat = re.sub(r'[^a-z0-9]', '', canon(t, False))
    for n in names:
        if flat == re.sub(r'[^a-z0-9]', '', canon(n, False)):
            return n
    return None


def _style_faults(l, a):
    faults = []
    if a.get('allowed_fonts'):
        allowed = [(re.sub(r'[^a-z0-9]', '', f.lower()), re.sub(r'[^a-z0-9]', '', w.lower())) for f, w in a['allowed_fonts']]
        for sp in l.spans:
            if sp['text'].strip() and base._font_parts(sp['font']) not in allowed:
                faults.append((sp['text'][:30], sp['font']))
        return faults
    want_fam = re.sub(r'[^a-z0-9]', '', a['family'].lower()) if a.get('family') else None
    want_wt = re.sub(r'[^a-z0-9]', '', a['weight'].lower()) if a.get('weight') else None
    for sp in l.spans:
        if not sp['text'].strip():
            continue
        fam, style = base._font_parts(sp['font'])
        if want_fam and fam != want_fam:
            faults.append((sp['text'][:30], sp['font']))
        elif want_wt and style != want_wt:
            faults.append((sp['text'][:30], sp['font']))
        elif 'size' in a and abs(sp['size'] - a['size']) > a.get('tolerance', 0.1):
            faults.append((sp['text'][:30], round(sp['size'], 2)))
    if a.get('caps') and re.search(r'[a-z]', _text(l)):
        faults.append((l.text[:30], 'lowercase'))
    if a.get('figures_same_size'):
        digits = [sp['size'] for sp in l.spans if re.search(r'\d', sp['text'])]
        letters = [sp['size'] for sp in l.spans if re.search(r'[A-Za-z]', sp['text'])]
        if digits and letters and max(abs(d - max(letters)) for d in digits) > 0.1:
            faults.append((l.text[:30], 'figure size'))
    return faults


def op_role_style(path, a):
    """PDF type style of a text role or named lines (see _style_select): family and weight, size, capitals, figures
    the same size as the letters round them, leading (baseline to baseline between consecutive lines of one block,
    within 0.5 pt; only_multi: the check applies only to a block of two or more lines). optional: none selected
    passes. Roles need a body size (a sentence in the running text); without one, role selectors go to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'type style is read from a PDF'}
    layer = _layer(path)
    if layer.source != 'pdf':
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    body, roles = _roles_b(layer)
    needs_body = [s for s in a.get('select', []) if isinstance(s, str) and s.lstrip('?') not in ('largest', 'main', 'page_main')]
    sure, doubt = _style_select(path, layer, roles, a)
    if needs_body and body is None:
        bad = [(l, f) for l in sure for f in _style_faults(l, a)] if 'leading' not in a else []
        if bad:
            return 'fail', {'not_matching': [(l.text[:40], f) for l, f in bad[:6]]}
        return PERSON, {'reason': 'no body text with a sentence found, so the roles cannot be set'}
    if 'leading' in a:
        return _leading(sure, doubt, a)
    bad = [(l.text[:40], f) for l in sure for f in _style_faults(l, a)]
    if bad:
        return 'fail', {'not_matching': bad[:8]}
    soft = [(l.text[:40], f) for l in doubt for f in _style_faults(l, a)]
    if soft:
        return PERSON, {'reason': 'a page heading that may or may not be a main heading does not match', 'lines': soft[:4]}
    if not sure:
        if a.get('optional'):
            return 'pass', {'reason': 'none present (the check applies only where they appear)'}
        return PERSON, {'reason': 'nothing selected'}
    return 'pass', {'lines': len(sure)}


def _blocks(lines):
    """Consecutive lines of one block: same page, same left edge (within 2 pt), next baseline under 2.2 sizes down."""
    out = []
    for l in sorted(lines, key=lambda l: (l.page, round(l.bbox[0]), l.baseline)):
        if out and out[-1][-1].page == l.page and abs(out[-1][-1].bbox[0] - l.bbox[0]) <= 2 and \
                0 < l.baseline - out[-1][-1].baseline < 2.2 * max(l.size, out[-1][-1].size):
            out[-1].append(l)
        else:
            out.append([l])
    return out


def _leading(sure, doubt, a):
    gaps, bad, soft = [], [], []
    for lines, out in ((sure, bad), (doubt, soft)):
        for block in _blocks(lines):
            for x, y in zip(block, block[1:]):
                g = round(y.baseline - x.baseline, 2)
                gaps.append(g)
                if abs(g - a['leading']) > a.get('tolerance', 0.5):
                    out.append({'lines': [x.text[:30], y.text[:30]], 'baseline_gap': g})
    if bad:
        return 'fail', {'not_matching': bad[:5], 'leading': a['leading']}
    if soft:
        return PERSON, {'reason': 'a block that may or may not be body text is set at another leading', 'blocks': soft[:4]}
    if not gaps:
        if a.get('optional') or a.get('only_multi'):
            return 'pass', {'reason': 'no block of two or more lines'}
        return PERSON, {'reason': 'no block of lines found'}
    return 'pass', {'baseline_gaps': sorted(set(gaps))}


# ---------------------------------------------------------------- PDF grounds, panels, bands and overlays


def _zorder(page):
    """Drawing order of a page: [(kind, rect)], kinds 'path', 'image', 'shade', 'text'."""
    out = []
    for kind, rect in page.get_bboxlog():
        k = 'image' if 'image' in kind else 'shade' if 'shade' in kind else 'text' if 'text' in kind else 'path' if 'path' in kind else None
        if k:
            out.append((k, tuple(rect)))
    return out


def _fills(page):
    """Filled shapes with their colour, box, opacity and whether a later image covers them (then unseen)."""
    import pymupdf  # noqa: F401
    order = _zorder(page)
    shapes = []
    used = set()
    for d in page.get_drawings():
        if d.get('fill') is None:
            continue
        r = tuple(d['rect'])
        z = next((i for i, (k, rr) in enumerate(order) if k == 'path' and i not in used and all(abs(p - q) <= 1.5 for p, q in zip(r, rr))), None)
        if z is not None:
            used.add(z)
        later = [rr for i, (k, rr) in enumerate(order) if k == 'image' and z is not None and i > z]
        covered = any(base._overlap(rr, r) >= 0.95 and (rr[2] - rr[0]) * (rr[3] - rr[1]) >= 0.95 * (r[2] - r[0]) * (r[3] - r[1]) for rr in later)
        shapes.append(dict(colour=base._hex(d['fill']), box=r, opacity=d.get('fill_opacity'), covered=covered))
    return shapes


def op_pdf_grounds(path, a):
    """PDF grounds, panels and bands. A panel: a filled shape of 2% of the page or more, both sides over 6 pt, not
    hidden under a later picture; the page ground: the commonest colour of the rendered page outside pictures.
    only: every panel (and the page ground, unless panels_only) is one of these colours; not: none is one of these
    (a smaller filled shape in it, both sides over 6 pt, may be a tile: a person decides); band: a band (a filled
    shape across 95% of the page width or height, 1.5% to 30% of the other side) is present on some page, one solid
    block in one of these colours; band_same: every page's band is one colour."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(path)
    bad, unsure, bands, panels = [], [], [], 0
    for page in doc:
        W, H = page.rect.width, page.rect.height
        if not a.get('panels_only') and (a.get('only') or a.get('not')):
            arr, mask, _ = base._flat_pixels(path, page.number)
            px = arr[mask].reshape(-1, 3)
            if len(px):
                values, counts = np.unique(px, axis=0, return_counts=True)
                g = '#%02X%02X%02X' % tuple(int(v) for v in values[counts.argmax()])
                if a.get('only') and not base._near_hex(g, a['only'], 3):
                    bad.append({'page': page.number + 1, 'page_ground': g})
                if a.get('not') and base._near_hex(g, a['not'], 3):
                    bad.append({'page': page.number + 1, 'page_ground': g})
        for s in _fills(page):
            x0, y0, x1, y1 = s['box']
            bw, bh = x1 - x0, y1 - y0
            if s['covered'] or min(bw, bh) <= 6:
                continue
            band = (bw >= 0.95 * W and 0.015 * H <= bh <= 0.3 * H) or (bh >= 0.95 * H and 0.015 * W <= bw <= 0.3 * W)
            if band:
                bands.append(dict(page=page.number + 1, colour=s['colour'], opacity=s['opacity']))
            whole_page = bw >= 0.95 * W and bh >= 0.95 * H
            is_panel = bw * bh >= 0.02 * W * H
            if a.get('panels_only') and whole_page:
                continue
            if is_panel:
                panels += 1
                if a.get('only') and not base._near_hex(s['colour'], a['only'], 3):
                    bad.append({'page': page.number + 1, 'panel': s['colour'], 'box': [round(v) for v in s['box']]})
                if a.get('not') and base._near_hex(s['colour'], a['not'], 3):
                    bad.append({'page': page.number + 1, 'panel': s['colour'], 'box': [round(v) for v in s['box']]})
            elif a.get('not') and base._near_hex(s['colour'], a['not'], 3):
                unsure.append({'page': page.number + 1, 'shape': s['colour'], 'box': [round(v) for v in s['box']]})
    if a.get('band') or a.get('band_same'):
        if not bands:
            return PERSON, {'reason': 'no band drawn as one shape (it may be built another way)'}
        if a.get('band'):
            off = [b for b in bands if not base._near_hex(b['colour'], a['band'], 3) or (b['opacity'] is not None and b['opacity'] < 0.999)]
            if len(off) == len(bands):
                return 'fail', {'bands': bands[:4]}
            if off:
                return PERSON, {'reason': 'several bands, not all in the colours', 'bands': bands[:4]}
            if 'sh' in b''.join(doc.xref_stream(x) or b'' for p in doc for x in p.get_contents()).decode('latin-1').split():
                return PERSON, {'reason': 'a shading is drawn somewhere on the pages', 'bands': bands[:4]}
            return 'pass', {'bands': bands[:4]}
        colours = {b['colour'] for b in bands}
        if len({base._near_hex(c, sorted(colours), 3) for c in colours}) > 1 or len(colours) > 1 and \
                any(not base._near_hex(c, [sorted(colours)[0]], 3) for c in colours):
            return 'fail', {'bands': bands[:6]}
        return 'pass', {'band': sorted(colours)[0], 'pages': len(bands)}
    if bad:
        return 'fail', {'not_allowed': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'a smaller filled shape in the colour (a tile or an icon)', 'shapes': unsure[:4]}
    return 'pass', {'panels': panels}


def op_pdf_overlay(path, a):
    """Nothing is laid over a placed picture: a semi-transparent or shaded fill drawn after the picture and covering
    2% of it or more fails; an opaque fill or another picture drawn over 2% or more of it goes to a person (a panel
    over part of a photo is not plainly an overlay). Text and thin strokes are not overlays. No picture: a pass, or a
    person where require_photo."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(path)
    bad, unsure, images = [], [], 0
    for page in doc:
        order = _zorder(page)
        drawings = [d for d in page.get_drawings() if d.get('fill') is not None]
        used = set()
        for i, (kind, rect) in enumerate(order):
            if kind != 'image':
                continue
            images += 1
            area = max(1e-6, (rect[2] - rect[0]) * (rect[3] - rect[1]))
            for j in range(i + 1, len(order)):
                k2, r2_ = order[j]
                ix = max(0, min(rect[2], r2_[2]) - max(rect[0], r2_[0]))
                iy = max(0, min(rect[3], r2_[3]) - max(rect[1], r2_[1]))
                if ix * iy < 0.02 * area or k2 == 'text':
                    continue
                if k2 == 'shade':
                    bad.append({'page': page.number + 1, 'over_image': [round(v) for v in rect], 'shading': True})
                elif k2 == 'image':
                    unsure.append({'page': page.number + 1, 'picture_over_picture': [round(v) for v in r2_]})
                else:
                    d = next((d for n, d in enumerate(drawings) if n not in used and all(abs(p - q) <= 1.5 for p, q in zip(tuple(d['rect']), r2_))), None)
                    if d is None:
                        continue                              # a stroke (a rule or frame), not a fill
                    used.add(drawings.index(d))
                    op = d.get('fill_opacity')
                    if op is not None and op < 0.999:
                        bad.append({'page': page.number + 1, 'fill_opacity': op, 'colour': base._hex(d['fill'])})
                    else:
                        unsure.append({'page': page.number + 1, 'opaque_fill': base._hex(d['fill']), 'box': [round(v) for v in r2_]})
    if bad:
        return 'fail', {'overlays': bad[:4]}
    if not images:
        return (PERSON, {'reason': 'no placed picture found'}) if a.get('require_photo') else ('pass', {'reason': 'no photograph'})
    if unsure:
        return PERSON, {'reason': 'a shape or picture drawn over part of a photo', 'over': unsure[:4]}
    return 'pass', {'pictures': images}


# ---------------------------------------------------------------- product text tied to its product (PDF)


def op_product_text(path, a):
    """Product names, care lines and prices against the product table (rows: [{name, care, price}]).
    names: every line close to a product name (85% or more alike, letter case and spaces aside) reads one exactly;
    a near miss, or a line set in the product-name style (font and size of the exact names) reading no name, goes to
    a person. care / price: each care line (care words) or price is tied to its product (the one product named on its
    page, else the nearest name above it sharing its width) and must equal that product's text word for word (case
    and spaces aside; a care line wrapped over lines is joined). Untied lines go to a person. require: none found
    goes to a person (the check expects some)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = _layer(path)
    if layer.source != 'pdf':
        return PERSON, {'reason': 'no live text'}
    rows = a['rows']
    names = [r['name'] for r in rows]
    flat = lambda t: re.sub(r'[^a-z0-9$]', '', canon(t, False))
    exact = [(l, _product_of(_text(l), names)) for l in layer.lines]
    exact = [(l, n) for l, n in exact if n]
    kind = a['mode']
    if kind == 'names':
        near = []
        for l in layer.lines:
            if any(l is e for e, _ in exact):
                continue
            t = flat(_text(l))
            for n in names:
                fn = flat(n)
                if len(t) >= 4 and (difflib.SequenceMatcher(None, t, fn).ratio() >= 0.85 or
                                    (fn in t and t != fn) or (len(t) >= len(fn) - 2 and difflib.SequenceMatcher(None, t[:len(fn)], fn).ratio() >= 0.85)):
                    near.append((l.text[:40], n))
                    break
        style = {(sp['font'], round(sp['size'], 1)) for l, _ in exact for sp in l.spans}
        mates = [l.text[:40] for l in layer.lines if not any(l is e for e, _ in exact)
                 and any((sp['font'], round(sp['size'], 1)) in style for sp in l.spans) and not _footer(path, l)]
        if near:
            return PERSON, {'reason': 'a line close to a product name but not exact (a typo or another name)', 'lines': near[:4]}
        if mates:
            return PERSON, {'reason': 'a line in the product-name style reading no product name', 'lines': mates[:4]}
        if not exact:
            return (PERSON, {'reason': 'no product name found'}) if a.get('require') else ('pass', {'reason': 'no product name shown'})
        return 'pass', {'names': sorted({n for _, n in exact})}
    by = {r['name']: r for r in rows}

    def owner(l):
        same = [(e, n) for e, n in exact if e.page == l.page]
        if len({n for _, n in same}) == 1:
            return same[0][1]
        above = [(e, n) for e, n in same if e.bbox[3] <= l.bbox[1] + 1 and r2._xoverlap(e.bbox, l.bbox)]
        if above:
            return max(above, key=lambda t: t[0].bbox[3])[1]
        return None
    found, bad, unsure = 0, [], []
    lines = sorted(layer.lines, key=lambda l: (l.page, l.bbox[1], l.bbox[0]))
    if kind in ('dims', 'materials'):
        field = {'dims': 'dims', 'materials': 'materials'}[kind]
        values = {flat(r[field]) for r in rows if r.get(field)}
        dim_rx = r'^(?:[hwld]\s?\d+\s?x\s?)?(?:[hwld]|dia)?\s?\d+(?:\s?x\s?(?:[hwld]|dia)?\s?\d+)*\s?(?:mm|cm)$'
        for l in lines:
            t = flat(_text(l))
            if kind == 'dims':
                hit = bool(re.match(dim_rx, canon(_text(l), False).replace(' ', ''))) or t in values
            else:
                hit = t in values or any(difflib.SequenceMatcher(None, t, v).ratio() >= 0.85 for v in values)
            if not hit:
                continue
            found += 1
            n = owner(l)
            if n is None:
                unsure.append({'line': l.text[:50], 'reason': 'not tied to a product'})
            elif t != flat(by[n][field]):
                bad.append({'line': l.text[:50], 'product': n, 'expected': by[n][field]})
    if kind == 'care':
        cue = r'dishwasher|handwash|microwave|machinewash|wipe|tumble|dryclean|layflat|iron|bleach|soak|rinse|airdry|hotwash|washwarm|washcold'
        skip = set()
        for i, l in enumerate(lines):
            if i in skip or not re.search(cue, flat(_text(l))):
                continue
            found += 1
            n = owner(l)
            if n is None:
                unsure.append({'line': l.text[:50], 'reason': 'not tied to a product'})
                continue
            want = flat(by[n]['care'])
            got = flat(_text(l))
            j = i
            while want.startswith(got) and got != want and j + 1 < len(lines) and lines[j + 1].page == l.page and \
                    abs(lines[j + 1].bbox[0] - l.bbox[0]) <= 2 and lines[j + 1].bbox[1] - lines[j].bbox[3] <= lines[j].size:
                j += 1
                skip.add(j)
                got += flat(_text(lines[j]))
            if got != want:
                bad.append({'line': l.text[:60], 'product': n, 'expected': by[n]['care']})
    else:
        for l in lines:
            for m in re.finditer(r'[$€£]\s?(\d[\d,]*(?:\.\d\d)?)', _text(l)):
                found += 1
                n = owner(l)
                if n is None:
                    unsure.append({'price': m.group(0), 'reason': 'not tied to a product'})
                    continue
                want = re.sub(r'[^\d.]', '', by[n]['price'])
                if re.sub(r'[^\d.]', '', m.group(1)).rstrip('0').rstrip('.') != want.rstrip('0').rstrip('.'):
                    bad.append({'price': m.group(0), 'product': n, 'expected': by[n]['price']})
    if bad:
        return 'fail', {'not_matching': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'some lines could not be tied to a product', 'lines': unsure[:4]}
    if not found:
        return (PERSON, {'reason': f'no {kind} line found'}) if a.get('require') else ('pass', {'reason': f'no {kind} shown'})
    return 'pass', {'checked': found}



# ---------------------------------------------------------------- a placed photo against its supplied file


def _scene_rgb(path: Path, page: int = 0):
    """The deliverable's pixels at the resolution photo matching uses (images as they are; PDF pages at 150 dpi)."""
    if path.suffix.lower() == '.pdf':
        return np.asarray(base.render_pdf(path, page, base.RENDER_DPI)).astype(np.float32)
    return r3._pixels(str(path)).astype(np.float32)


@functools.lru_cache(maxsize=6)
def _placed(key: str, name: str, dirs: tuple):
    """Where the supplied photo sits: {'page', 'src' (the supplied pixels laid over the deliverable, first reduced to
    about the shown size so both are compared at the shown scale), 'valid', 'scale', 'corners'}; None if not found."""
    import cv2
    path = Path(key)
    try:
        ap = base.asset_path({'_asset_dirs': list(dirs)}, name)
    except FileNotFoundError:
        return None
    asset = base._load_gray(ap)
    for i, scene in enumerate(base._scenes(path)):
        n, corners, state = base.find_asset(scene, asset)
        if state != 'found':
            continue
        h, w = asset.shape
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
        scale = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
        src = np.asarray(Image.open(ap).convert('RGB'))
        if scale < 0.95:
            small = cv2.resize(src, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
            S = np.diag([w / small.shape[1], h / small.shape[0], 1.0])
            H, src = H @ S, small
        size = (scene.shape[1], scene.shape[0])
        warped = cv2.warpPerspective(src, H, size, flags=cv2.INTER_LINEAR)          # uint8 in the cache; float where compared
        valid = cv2.warpPerspective(np.full(src.shape[:2], 255, np.uint8), H, size, flags=cv2.INTER_NEAREST) > 0
        valid = cv2.erode(valid.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        # the part actually shown (a crop): 16 px blocks whose structure correlates with the supplied pixels whatever
        # their tone, and the box round the largest group of them
        rgb = _scene_rgb(path, i)
        gs = cv2.cvtColor(np.clip(warped, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
        gd = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
        b = 16
        hb, wb = size[1] // b, size[0] // b
        shown = np.zeros((hb, wb), np.uint8)
        for by in range(hb):
            for bx in range(wb):
                sl = (slice(by * b, by * b + b), slice(bx * b, bx * b + b))
                if not valid[sl].all():
                    continue
                u, v = gs[sl] - gs[sl].mean(), gd[sl] - gd[sl].mean()
                if u.std() < 4 or v.std() < 2:
                    continue
                if (u * v).sum() / (np.sqrt((u * u).sum() * (v * v).sum()) + 1e-9) >= 0.7:
                    shown[by, bx] = 1
        if shown.sum() < 4:
            return None
        grown = cv2.dilate(shown, np.ones((5, 5), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
        k = 1 + int(np.argmax([int((shown & (labels == j)).sum()) for j in range(1, n)]))
        ys, xs = np.where(shown & (labels == k))
        box = (xs.min() * b, ys.min() * b, (xs.max() + 1) * b, (ys.max() + 1) * b)
        inside = np.zeros_like(valid)
        inside[box[1]:box[3], box[0]:box[2]] = True
        return {'page': i, 'src': warped, 'valid': valid & inside, 'scale': round(scale, 3), 'corners': np.float32(corners),
                'shown_box': [int(v) for v in box]}
    return None


def _lab(rgb):
    import cv2
    lab = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[..., 0] *= 100 / 255
    lab[..., 1:] -= 128
    return lab


def _photo_stats(path: Path, a, name):
    """Tile statistics of the placed photo against the supplied file (see _compare); None when not found."""
    got = _placed(str(path), name, tuple(a.get('_asset_dirs') or []))
    if got is None:
        return None
    rgb = _scene_rgb(path, got['page'])
    text = np.zeros(rgb.shape[:2], bool)
    if a.get('region') == 'shown':
        k = base.RENDER_DPI / 72 if path.suffix.lower() == '.pdf' else 1
        lines = [l for l in _layer(path).lines if l.page == got['page'] and (path.suffix.lower() == '.pdf' or _is_type(l))]
        for l in lines:
            x0, y0, x1, y1 = (int(round(v * k)) for v in l.bbox)
            text[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = True
    st = _compare(rgb, got['src'].astype(np.float32), got['valid'], a, text)
    if st is not None:
        st['scale'] = got['scale']
    return st


def _hue_stats(lab, mask):
    """Hue centre and spread (degrees) of the pixels with chroma over 4: a circular mean and its angular spread."""
    if mask.sum() < 50:
        return None, None
    a_, b_ = lab[..., 1][mask], lab[..., 2][mask]
    c = np.hypot(a_, b_)
    sel = c > 4
    if sel.sum() < 50:
        return None, 0.0
    ang = np.arctan2(b_[sel], a_[sel])
    m = np.hypot(np.cos(ang).mean(), np.sin(ang).mean())
    centre = float(np.degrees(np.arctan2(np.sin(ang).mean(), np.cos(ang).mean())) % 360)
    spread = float(np.degrees(np.sqrt(max(0.0, -2 * np.log(max(m, 1e-9))))))
    return round(centre, 1), round(spread, 1)


def _compare(rgb, src, valid, a, text=None):
    """The deliverable's pixels (rgb) against the supplied photo laid over them (src) where valid: one global
    per-channel tone fit (over the photo's textured pixels, refitted without what it could not explain), then tiles
    over the region (a['region']: 'subject' textured own pixels; 'own' all pixels the fit explains; 'shown' every
    shown pixel but type). Stats: de_max / de_mean (tile Delta E), rgb_max / rgb_median (largest channel difference
    of tile means), dc_max, ncc_min, hf_min / hf_median (fine detail against the source at the shown scale),
    noise_ratio (fine noise in plain tiles against the source), da / db / dL, chroma_ratio, gain_min, drift (bands
    of the photo departing from the global fit), hue centre and spread of the deliverable and the source."""
    import cv2
    if text is None:
        text = np.zeros(rgb.shape[:2], bool)
    if not valid.any():
        return None
    gray_s = cv2.cvtColor(np.clip(src, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    gray_d = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    std_s = np.sqrt(np.maximum(cv2.blur(gray_s * gray_s, (7, 7)) - cv2.blur(gray_s, (7, 7)) ** 2, 0))
    fit = np.empty_like(src)
    keep = valid & ~text & (std_s > 4) if (valid & ~text & (std_s > 4)).sum() >= 500 else valid & ~text
    gains = [1.0, 1.0, 1.0]
    for _ in range(2):
        gains = []
        for ch in range(3):
            x, y = src[..., ch][keep], rgb[..., ch][keep]
            g, o = np.polyfit(x, y, 1) if len(x) > 10 and x.std() > 1 else (1.0, float(y.mean() - x.mean()) if len(x) else 0.0)
            gains.append(float(g))
            fit[..., ch] = src[..., ch] * g + o
        keep = keep & (np.abs(rgb - fit).max(axis=2) < 40)
    close = cv2.blur(np.abs(rgb - fit).max(axis=2), (9, 9)) < 40
    own = valid & close & ~text
    region = a.get('region', 'subject')
    subject = own & (std_s > 4) if region == 'subject' else own if region == 'own' else valid & ~text
    ys, xs = np.where(valid)
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    t = int(max(12, min(bw, bh) // a.get('tiles_across', 10)))
    lab_s, lab_d = _lab(src), _lab(rgb)
    lap_s = cv2.Laplacian(gray_s, cv2.CV_32F)
    lap_d = cv2.Laplacian(gray_d, cv2.CV_32F)
    hp_s = gray_s - cv2.GaussianBlur(gray_s, (0, 0), 2)
    hp_d = gray_d - cv2.GaussianBlur(gray_d, (0, 0), 2)
    deep = cv2.erode(own.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0     # away from a cut-out's edge
    tiles = []
    for y in range(ys.min(), ys.max() - t + 2, t):
        for x in range(xs.min(), xs.max() - t + 2, t):
            m = subject[y:y + t, x:x + t]
            if m.mean() < 0.8:
                continue
            ls, ld = lab_s[y:y + t, x:x + t][m], lab_d[y:y + t, x:x + t][m]
            gs, gd = gray_s[y:y + t, x:x + t][m], gray_d[y:y + t, x:x + t][m]
            rs, rd = src[y:y + t, x:x + t][m], rgb[y:y + t, x:x + t][m]
            ncc = None
            if gs.std() >= 6 and gd.std() >= 1 and deep[y:y + t, x:x + t].all():
                u, v = gs - gs.mean(), gd - gd.mean()
                ncc = float((u * v).sum() / (np.sqrt((u * u).sum() * (v * v).sum()) + 1e-9))
            vs = float(lap_s[y:y + t, x:x + t][m].var())
            hf = float(lap_d[y:y + t, x:x + t][m].var() / vs) if vs >= 20 else None
            noise = None
            if gs.std() < 3:                                   # a plain tile: its fine noise is grain, not detail
                ns = float(hp_s[y:y + t, x:x + t][m].std())
                noise = float(hp_d[y:y + t, x:x + t][m].std() / max(ns, 0.3))
            tiles.append(dict(de=float(np.linalg.norm(ls.mean(axis=0) - ld.mean(axis=0))), ncc=ncc, hf=hf, noise=noise,
                              rgb=float(np.abs(rd.mean(axis=0) - rs.mean(axis=0)).max()),
                              dL=float(ld[:, 0].mean() - ls[:, 0].mean()), da=float(ld[:, 1].mean() - ls[:, 1].mean()),
                              db=float(ld[:, 2].mean() - ls[:, 2].mean()),
                              c_s=float(np.hypot(ls[:, 1].mean(), ls[:, 2].mean())), c_d=float(np.hypot(ld[:, 1].mean(), ld[:, 2].mean()))))
    resid = (rgb - fit).mean(axis=2)
    drift = 0.0
    for axis in (0, 1):
        lo_, hi_ = (ys.min(), ys.max()) if axis == 0 else (xs.min(), xs.max())
        step = max(1, (hi_ - lo_ + 1) // 6)
        band = []
        for i in range(lo_, hi_ - step + 2, step):
            sl = (slice(i, i + step), slice(None)) if axis == 0 else (slice(None), slice(i, i + step))
            m = keep[sl]
            if m.sum() >= 300:
                band.append(float(np.median(resid[sl][m])))
        if len(band) >= 2:
            drift = max(drift, max(band) - min(band))
    hue_d, spread_d = _hue_stats(lab_d, valid & ~text)
    hue_s, spread_s = _hue_stats(lab_s, valid & ~text)
    out = {'tiles': len(tiles), 'gain': [round(g, 3) for g in gains], 'gain_min': round(min(gains), 3), 'drift': round(drift, 1),
           'covered_share': round(float(1 - keep.sum() / max(1, valid.sum())), 3), 'hue': hue_d, 'hue_spread': spread_d,
           'src_hue': hue_s, 'src_hue_spread': spread_s,
           'warm_single': int(spread_d is not None and hue_d is not None and spread_d < 15 and 20 <= hue_d <= 70),
           'src_warm_single': int(spread_s is not None and hue_s is not None and spread_s < 15 and 20 <= hue_s <= 70)}
    if not tiles:
        return out
    nccs = [x['ncc'] for x in tiles if x['ncc'] is not None]
    hfs = [x['hf'] for x in tiles if x['hf'] is not None]
    noises = [x['noise'] for x in tiles if x['noise'] is not None]
    out.update({'de_max': round(max(x['de'] for x in tiles), 2), 'de_mean': round(float(np.mean([x['de'] for x in tiles])), 2),
                'rgb_max': round(max(x['rgb'] for x in tiles), 1), 'rgb_median': round(float(np.median([x['rgb'] for x in tiles])), 1),
                'dc_max': round(float(max(np.hypot(x['da'], x['db']) for x in tiles)), 2),
                'ncc_min': round(min(nccs), 3) if nccs else None, 'ncc_tiles': len(nccs),
                'hf_min': round(min(hfs), 3) if hfs else None, 'hf_median': round(float(np.median(hfs)), 3) if hfs else None,
                'noise_ratio': round(float(np.median(noises)), 2) if len(noises) >= 3 else None,
                'da': round(float(np.mean([x['da'] for x in tiles])), 2), 'db': round(float(np.mean([x['db'] for x in tiles])), 2),
                'dL': round(float(np.mean([x['dL'] for x in tiles])), 2),
                'chroma_ratio': round(float(np.mean([x['c_d'] for x in tiles]) / max(1e-6, np.mean([x['c_s'] for x in tiles]))), 3)})
    return out


@functools.lru_cache(maxsize=24)
def _small_asset(asset_file: str, max_side: int = 1600):
    """A supplied photo reduced to at most max_side pixels (PDF pictures are matched against this, so a 68-megapixel
    file is never held whole): (gray, rgb), both uint8."""
    import cv2
    im = Image.open(asset_file)
    im.draft('RGB', (max_side, max_side))                  # JPEG: decode at a reduced size straight away
    rgb = np.asarray(im.convert('RGB'))
    k = max_side / max(rgb.shape[:2])
    if k < 1:
        rgb = cv2.resize(rgb, (max(1, round(rgb.shape[1] * k)), max(1, round(rgb.shape[0] * k))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), rgb


@functools.lru_cache(maxsize=2)
def _pdf_photos(key: str, candidates: tuple, dirs: tuple):
    """Every picture placed in a PDF, read from its embedded pixels, and the supplied photo it shows (the candidate
    found in it with the most matched points): [{page, bbox, name or None, rgb, src, valid}]."""
    import cv2
    import pymupdf
    doc = pymupdf.open(key)
    assets = {}
    for name in candidates:
        try:
            ap = base.asset_path({'_asset_dirs': list(dirs)}, name)
        except FileNotFoundError:
            continue
        assets[name] = (ap, _small_asset(str(ap))[0])
    out = []
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            xref = info.get('xref')
            if not xref:
                continue
            pix = pymupdf.Pixmap(doc, xref)
            if pix.alpha:
                pix = pymupdf.Pixmap(pix, 0)
            if pix.n != 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3)
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            best = None
            # matched at a size near the picture's own: the supplied file reduced to 1600 px, then (for a small
            # thumbnail) to twice the picture's size, so fine detail is compared at a like scale
            sides = [1600] + ([max(160, 2 * max(gray.shape))] if 2 * max(gray.shape) < 1200 else [])
            for side in sides:
                for name, (ap, _) in assets.items():
                    ag = _small_asset(str(ap), side)[0]
                    n, corners, state = base.find_asset(gray, ag)
                    if state == 'found' and (best is None or n > best[0]):
                        best = (n, name, corners, side)
                if best is not None:
                    break
            rec = {'page': page.number, 'bbox': tuple(round(v, 1) for v in info['bbox']), 'name': None}
            if best is not None:
                n, name, corners, side = best
                ap = assets[name][0]
                ag = _small_asset(str(ap), side)[0]
                h, w = ag.shape
                H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
                scale = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
                src = _small_asset(str(ap), side)[1]
                if scale < 0.95:
                    small = cv2.resize(src, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
                    H, src = H @ np.diag([w / small.shape[1], h / small.shape[0], 1.0]), small
                size = (img.shape[1], img.shape[0])
                warped = cv2.warpPerspective(src, H, size, flags=cv2.INTER_LINEAR)
                valid = cv2.warpPerspective(np.full(src.shape[:2], 255, np.uint8), H, size, flags=cv2.INTER_NEAREST) > 0
                full = cv2.warpPerspective(np.full(src.shape[:2], 255, np.uint8), H, (int(np.ceil(np.float32(corners)[:, 0].max())) + 2,
                                                                                          int(np.ceil(np.float32(corners)[:, 1].max())) + 2),
                                           flags=cv2.INTER_NEAREST) > 0
                frame_share = float(valid.sum() / max(1, full.sum()))
                fills = float(valid.mean())
                valid = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                rec.update(name=name, rgb=img.copy(), src=warped, valid=valid, scale=round(scale, 3),
                           frame_share=round(frame_share, 3), fills_image=round(fills, 3))
            out.append(rec)
    return out


def op_pdf_photos(path, a):
    """Every picture placed in the PDF (above min_share of its page) against the supplied photos (photos): each must
    show one of them (an unmatched picture goes to a person; forbid: a picture showing one of these fails). then:
    pass_if / fail_if over each matched picture's stats (see _compare, read from the embedded pixels), as in
    op_photo_compare; only: limit the stats check to pictures showing these files."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    import pymupdf
    doc = pymupdf.open(path)
    pics = _pdf_photos(str(path), tuple(a.get('photos', []) + a.get('forbid', [])), tuple(a.get('_asset_dirs') or []))
    sizes = {p.number: p.rect.width * p.rect.height for p in doc}
    bad, unsure, ok = [], [], []
    for pic in pics:
        b = pic['bbox']
        if (b[2] - b[0]) * (b[3] - b[1]) < a.get('min_share', 0.005) * sizes[pic['page']]:
            continue
        where = {'page': pic['page'] + 1, 'bbox': [round(v) for v in b]}
        if pic['name'] is None:
            unsure.append(dict(where, reason='a picture not matched to a supplied photo'))
            continue
        if pic['name'] in a.get('forbid', []):
            bad.append(dict(where, photo=pic['name'], reason='a forbidden photo'))
            continue
        if a.get('only') and pic['name'] not in a['only']:
            continue
        rules = (a.get('by_photo') or {}).get(pic['name'], a)
        if a.get('by_photo') and pic['name'] not in a['by_photo']:
            ok.append(dict(where, photo=pic['name']))
            continue
        if not (rules.get('pass_if') or rules.get('fail_if')):
            ok.append(dict(where, photo=pic['name']))
            continue
        st = _compare(pic['rgb'].astype(np.float32), pic['src'].astype(np.float32), pic['valid'], rules)
        if st is None or st.get('tiles', 0) < rules.get('min_tiles', 6):
            unsure.append(dict(where, photo=pic['name'], reason='too little of the photo to compare'))
            continue
        st['frame_share'] = pic.get('frame_share')
        st['fills_image'] = pic.get('fills_image')
        show = {k: st.get(k) for k in ('tiles', 'rgb_max', 'rgb_median', 'de_max', 'ncc_min', 'noise_ratio', 'hue', 'hue_spread', 'warm_single',
                                       'frame_share', 'fills_image')}
        if rules.get('pass_if') and _holds(st, rules['pass_if']):
            ok.append(dict(where, photo=pic['name'], **show))
        elif rules.get('fail_if') and _holds(st, rules['fail_if']):
            bad.append(dict(where, photo=pic['name'], **show))
        else:
            unsure.append(dict(where, photo=pic['name'], **show))
    if bad:
        return 'fail', {'pictures': bad[:4]}
    if unsure:
        return PERSON, {'reason': 'some pictures could not be decided', 'pictures': unsure[:4]}
    if not ok:
        return ('pass', {'reason': 'no such picture'}) if a.get('optional', True) else (PERSON, {'reason': 'no picture found'})
    return 'pass', {'pictures': ok[:6], 'count': len(ok)}


def _holds(stats, conds):
    for stat, rel, value in conds:
        v = stats.get(stat)
        if v is None:
            return None
        if not ((rel == '>=' and v >= value) or (rel == '<=' and v <= value) or (rel == '>' and v > value) or (rel == '<' and v < value)):
            return False
    return True


def op_photo_compare(path, a):
    """The placed photo against its supplied file (photo; or photos, each one found), tile by tile over the photo's
    own pixels (see _photo_stats): pass_if / fail_if are lists of [stat, '>=' or '<=', value] over the stats
    (de_max: largest tile colour difference in Delta E; dc_max: largest tile shift of a* b* alone, lightness left
    out; ncc_min: lowest tile correlation; hf_min: lowest ratio of fine detail to the source at the shown scale;
    da, db, dL: mean shifts; chroma_ratio). Both decide only where every condition holds; otherwise a person
    answers. Not found: a person, or with absent 'pass' a pass when no unmatched photograph is on the file."""
    names = [a['photo']] if a.get('photo') else list(a.get('photos', []))
    results = []
    for name in names:
        st = _photo_stats(path, a, name)
        if st is not None:
            results.append((name, st))
    if not results:
        if a.get('absent') == 'pass':
            sub = {'op': 'v2_each_photo_pb', 'photos': [], 'known': a.get('known', []), 'then': {'op': 'v2_no_overlay'}}
            st, ev = op_each_photo(path, dict(sub, **{k: v for k, v in a.items() if k.startswith('_')}))
            return ('pass', {'reason': 'the photo is not used'}) if st == 'pass' else (PERSON, dict(ev, reason='supplied photo not found; another photograph is present'))
        return PERSON, {'reason': 'supplied photo not found'}
    verdicts = []
    for name, st in results:
        if st['tiles'] < a.get('min_tiles', 6):
            verdicts.append((PERSON, name, st))
            continue
        if a.get('pass_if') and _holds(st, a['pass_if']):
            verdicts.append(('pass', name, st))
        elif a.get('fail_if') and _holds(st, a['fail_if']):
            verdicts.append(('fail', name, st))
        else:
            verdicts.append((PERSON, name, st))
    ev = {'photos': [{'photo': n, **{k: v for k, v in s.items() if k in ('tiles', 'scale', 'de_max', 'rgb_max', 'rgb_median', 'dc_max', 'ncc_min',
                                                                         'hf_min', 'noise_ratio', 'da', 'db', 'dL', 'chroma_ratio', 'gain_min',
                                                                         'drift', 'hue', 'hue_spread', 'warm_single')}}
                     for _, n, s in verdicts]}
    states = {v for v, _, _ in verdicts}
    if 'fail' in states:
        return 'fail', ev
    if PERSON in states:
        return PERSON, dict(ev, reason='the measures do not settle it either way')
    return 'pass', ev


def op_mark_solid(path, a):
    """A mark printed in one colour (colour) is that colour, solid: found as the largest cluster of pixels near the
    colour, confirmed as the supplied artwork's letters (asset) by shape (each outline within 3 px of the other for
    60% of its ink once both fill the same box: a redrawn monogram still counts, a rule or a box does not), and every
    pixel of it lies on the blend between the colour and the ground round it (anti-aliasing),
    with no shadow, highlight or emboss colours. Not found in the colour: a person (it may be another colour)."""
    import cv2
    rgb = r3._pixels(str(path))
    box = r2._pixel_mark(rgb.astype(int), a['colour'], None, tol=14, min_px=30)
    if box is None:
        return PERSON, {'reason': 'no mark in the colour found'}
    x0, y0, x1, y1 = (int(v) for v in box)
    pad = 3
    X0, Y0, X1, Y1 = max(0, x0 - pad), max(0, y0 - pad), min(rgb.shape[1], x1 + pad), min(rgb.shape[0], y1 + pad)
    crop = rgb[Y0:Y1, X0:X1].astype(float)
    ring = np.concatenate([crop[:2].reshape(-1, 3), crop[-2:].reshape(-1, 3), crop[:, :2].reshape(-1, 3), crop[:, -2:].reshape(-1, 3)])
    values, counts = np.unique((ring // 4).astype(int), axis=0, return_counts=True)
    ground = np.median(ring[np.abs(ring - (values[counts.argmax()] * 4 + 2)).max(axis=1) <= 8], axis=0)
    c = r3._hex_rgb(a['colour']).astype(float)
    ink = np.abs(crop - ground).sum(axis=2) > 30
    if a.get('asset'):
        try:
            art = np.asarray(Image.open(base.asset_path(a, a['asset'])).convert('RGBA'))
        except FileNotFoundError:
            return PERSON, {'reason': 'supplied artwork not available'}
        alpha = art[..., 3] > 128
        ys, xs = np.where(alpha)
        if not len(ys):
            return PERSON, {'reason': 'supplied artwork has no ink'}
        alpha = alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
        mine = ink[pad:pad + (y1 - y0), pad:pad + (x1 - x0)].astype(np.uint8)
        if mine.shape[0] < 8 or mine.shape[1] < 8:
            return PERSON, {'reason': 'mark too small to compare'}
        ref = cv2.resize(alpha, (mine.shape[1], mine.shape[0]), interpolation=cv2.INTER_AREA) > 0
        k = np.ones((7, 7), np.uint8)
        near_ref = cv2.dilate(ref.astype(np.uint8), k) > 0
        near_mine = cv2.dilate(mine, k) > 0
        cover = min(float((mine.astype(bool) & near_ref).sum() / max(1, mine.sum())), float((ref & near_mine).sum() / max(1, ref.sum())))
        if cover < 0.6:
            return PERSON, {'reason': 'the mark in the colour does not match the supplied artwork', 'shape_cover': round(cover, 2)}
    px = crop[ink]
    d = c - ground
    t = np.clip(((px - ground) @ d) / (d @ d), 0, 1)
    resid = np.linalg.norm(px - (ground + t[:, None] * d), axis=1)
    off = float((resid > 25).mean())
    full = float((np.abs(px - c).max(axis=1) <= r3._tol(path, a) + 3).mean())
    ev = {'box': [x0, y0, x1, y1], 'ground': _hex(ground), 'off_blend_share': round(off, 3), 'full_ink_share': round(full, 3)}
    if a.get('asset'):
        ev['shape_cover'] = round(cover, 2)
    if off <= 0.03 and full >= 0.3:
        return 'pass', ev
    if off >= 0.15:
        return 'fail', dict(ev, reason='colours off the blend between the ink and the ground (a shadow, highlight or emboss)')
    return PERSON, dict(ev, reason='not clearly one solid colour')


# ---------------------------------------------------------------- a wordmark's own geometry


def _ink_mask(rgb, box, grow=0.35):
    """A typeset or placed mark's letters inside a box (grown by a share of its height): pixels past the midpoint
    between the ground (commonest colour round the grown box) and the ink (the pixels furthest from it).
    Returns (mask, ground, ink, (x0, y0)) or None."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = box
    m = grow * (y1 - y0)
    X0, Y0, X1, Y1 = int(max(0, x0 - m)), int(max(0, y0 - m)), int(min(w, x1 + m)), int(min(h, y1 + m))
    crop = rgb[Y0:Y1, X0:X1].astype(float)
    if crop.shape[0] < 6 or crop.shape[1] < 6:
        return None
    ring = np.concatenate([crop[:2].reshape(-1, 3), crop[-2:].reshape(-1, 3), crop[:, :2].reshape(-1, 3), crop[:, -2:].reshape(-1, 3)])
    values, counts = np.unique((ring // 4).astype(int), axis=0, return_counts=True)
    ground = np.median(ring[np.abs(ring - (values[counts.argmax()] * 4 + 2)).max(axis=1) <= 8], axis=0)
    d = np.abs(crop - ground).sum(axis=2)
    if d.max() < 60:
        return None
    ink = np.median(crop[d >= 0.9 * d.max()], axis=0)
    mask = d >= 0.5 * np.abs(ink - ground).sum()
    return mask, ground, ink, (X0, Y0)


def _letters(mask, min_px=6):
    import cv2
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    comps = [(stats[i], labels == i) for i in range(1, n) if stats[i][4] >= min_px]
    return sorted(comps, key=lambda c: c[0][0])


def _holes(comps):
    import cv2
    total = 0
    for st, m in comps:
        contours, hier = cv2.findContours(m.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
        if hier is not None:
            total += sum(1 for hh, c in zip(hier[0], contours) if hh[3] >= 0 and cv2.contourArea(c) >= 1)
    return total


def _geometry(mask):
    comps = _letters(mask)
    if not comps:
        return None
    xs0 = min(c[0][0] for c in comps); ys0 = min(c[0][1] for c in comps)
    xs1 = max(c[0][0] + c[0][2] for c in comps); ys1 = max(c[0][1] + c[0][3] for c in comps)
    hgt = ys1 - ys0
    gaps = [round((b[0][0] - (a[0][0] + a[0][2])) / hgt, 3) for a, b in zip(comps, comps[1:])]
    return {'width': int(xs1 - xs0), 'height': int(hgt), 'aspect': round((xs1 - xs0) / hgt, 3), 'letters': len(comps),
            'gaps': gaps, 'holes': _holes(comps), 'box': (int(xs0), int(ys0), int(xs1), int(ys1))}


@functools.lru_cache(maxsize=8)
def _asset_geometry(asset_file: str):
    art = np.asarray(Image.open(asset_file).convert('RGBA'))
    alpha = art[..., 3] > 127
    rgbw = np.where(alpha[..., None], art[..., :3], 255)
    dark = (rgbw.astype(int).sum(axis=2) < 3 * 128) & alpha
    return _geometry(dark)


def op_wordmark(path, a):
    """The wordmark's own letters, found where OCR reads it alone on a line (whole) or as the supplied file (asset),
    split from the ground at the midpoint between ground and ink. measure:
    height: letter height in pixels at most max_px (2 px either side of the limit goes to a person);
    aspect: letter block width over height within [lo, hi] (0.03 either side goes to a person);
    spacing: gaps between neighbouring letters over letter height within tol of the supplied file's;
    counters: as many enclosed counters as the supplied file (fewer fails only where the letters stand 24 px or taller);
    halo: an 8 px ring round the letters matches the ground beyond it (no box or halo);
    edges: pixels at the letters' edges lie on the blend between ink and ground (no grey fringe or ringing).
    Every placement found is checked; none found goes to a person."""
    import cv2
    rgb = r3._pixels(str(path)).astype(float)
    boxes = []
    layer = _layer(path)
    boxes += [tuple(l.bbox) for l in layer.lines if _is_type(l) and r2._whole(_text(l), a.get('whole', []))]
    if not boxes and a.get('asset'):
        try:
            page, box, state = r2._asset_box(path, a, a['asset'], 0)
        except FileNotFoundError:
            box = None
        if box is not None:
            boxes.append(tuple(box))
    if not boxes:
        return PERSON, {'reason': 'wordmark not found'}
    ref = None
    if a['measure'] in ('spacing', 'counters'):
        try:
            ref = _asset_geometry(str(base.asset_path(a, a['asset'])))
        except FileNotFoundError:
            return PERSON, {'reason': 'supplied wordmark not available'}
    verdicts = []
    for box in boxes:
        got = _ink_mask(rgb, box)
        if got is None:
            verdicts.append((PERSON, {'reason': 'letters not measurable'}))
            continue
        mask, ground, ink, (X0, Y0) = got
        g = _geometry(mask)
        if g is None:
            verdicts.append((PERSON, {'reason': 'letters not measurable'}))
            continue
        m = a['measure']
        ev = {'height': g['height'], 'aspect': g['aspect'], 'letters': g['letters']}
        if m == 'height':
            v = g['height']
            verdicts.append(('pass' if v <= a['max_px'] - 2 else 'fail' if v > a['max_px'] + 2 else PERSON, ev))
        elif m == 'aspect':
            v = g['aspect']
            lo, hi = a['range']
            verdicts.append(('pass' if lo + 0.03 <= v <= hi - 0.03 else 'fail' if v < lo - 0.03 or v > hi + 0.03 else PERSON, ev))
        elif m == 'spacing':
            if g['letters'] != ref['letters']:
                verdicts.append((PERSON, dict(ev, reason='letters touch or split differently from the supplied file', ref_letters=ref['letters'])))
                continue
            off = max(abs(x - y) for x, y in zip(g['gaps'], ref['gaps']))
            ev.update(gaps=g['gaps'], ref_gaps=ref['gaps'], largest_difference=round(off, 3))
            # within the tolerance plus half a pixel passes; past it by two and a half pixels fails (a pixel or two of
            # difference at the shown size may be the edge threshold, so it goes to a person)
            tol = a.get('tol', 0.02)
            verdicts.append(('pass' if off <= tol + 0.5 / g['height'] else 'fail' if off >= tol + 2.5 / g['height'] else PERSON, ev))
        elif m == 'counters':
            ev.update(holes=g['holes'], ref_holes=ref['holes'])
            if g['holes'] >= ref['holes']:
                verdicts.append(('pass', ev))
            else:
                verdicts.append(('fail' if g['height'] >= 24 else PERSON, ev))
        elif m in ('halo', 'edges'):
            letters = mask.astype(np.uint8)
            if m == 'halo':
                inner = cv2.dilate(letters, np.ones((5, 5), np.uint8)) > 0
                outer = cv2.dilate(letters, np.ones((21, 21), np.uint8)) > 0
                ring = outer & ~inner
                far = (cv2.dilate(letters, np.ones((35, 35), np.uint8)) > 0) & ~outer
                X1, Y1 = X0 + mask.shape[1], Y0 + mask.shape[0]
                crop = rgb[Y0:Y1, X0:X1]
                beyond = crop[far] if far.sum() >= 50 else np.asarray([ground])
                g0 = np.median(beyond, axis=0)
                diff = np.abs(crop[ring] - g0).max(axis=1)
                share = float((diff > r3._tol(path, a)).mean()) if len(diff) else 1.0
                ev.update(ring_off_share=round(share, 3), ground=_hex(g0))
                verdicts.append(('pass' if share <= 0.01 else 'fail' if share >= 0.1 else PERSON, ev))
            else:
                edge = (cv2.dilate(letters, np.ones((7, 7), np.uint8)) > 0) & ~(cv2.erode(letters, np.ones((3, 3), np.uint8)) > 0)
                X1, Y1 = X0 + mask.shape[1], Y0 + mask.shape[0]
                px = rgb[Y0:Y1, X0:X1][edge]
                d = ink - ground
                t = np.clip(((px - ground) @ d) / max(1e-6, d @ d), 0, 1)
                resid = np.abs(px - (ground + t[:, None] * d)).max(axis=1)
                share = float((resid > 10).mean())
                ev.update(off_blend_share=round(share, 3))
                verdicts.append(('pass' if share <= 0.03 else 'fail' if share >= 0.12 else PERSON, ev))
    states = [v for v, _ in verdicts]
    evs = [e for _, e in verdicts]
    if 'fail' in states:
        return 'fail', {'placements': evs[:3]}
    if PERSON in states:
        return PERSON, {'reason': 'a placement could not be decided', 'placements': evs[:3]}
    return 'pass', {'placements': evs[:3]}


# ---------------------------------------------------------------- a list of names with their prices (images)


def op_price_list(path, a):
    """The list of names set with a price on their own row (OCR). names: the expected names, each once (a fail where
    one is missing, repeated or another name is listed, if every line was read at 80% or more; else a person).
    block: no other text line and no photograph inside the box enclosing the listed names and prices."""
    layer = _layer(path)
    lines = [l for l in layer.lines if _is_type(l)]
    price = r'[$€£]\s?\d'
    prices = [l for l in lines if r2._rxs(price, l.text)]
    rows = []
    for l in lines:
        if l in prices:
            continue
        h = l.bbox[3] - l.bbox[1]
        mate = [p_ for p_ in prices if abs(r2._cy(p_.bbox) - r2._cy(l.bbox)) <= 0.6 * h and p_.bbox[0] >= l.bbox[2] - 2]
        if mate:
            rows.append((l, min(mate, key=lambda p_: p_.bbox[0])))
    if not rows:
        return PERSON, {'reason': 'no names with prices read'}
    reliable = getattr(base.merged(base.text_layers(path)), 'confident_all', False) if layer.source != 'pdf' else True
    got = [canon(l.text) for l, _ in rows]
    if a.get('prices'):
        # the price set on each named row (prices: {name: pattern}); a different price read clearly fails
        bad, unsure, ok = [], [], []
        for name, rx in a['prices'].items():
            mine = [(l, p_) for l, p_ in rows if r2._whole(_text(l), [name])]
            if not mine:
                unsure.append({'name': name, 'reason': 'no row read for it'})
                continue
            for l, p_ in mine:
                if re.search(rx, canon(p_.text), re.I):
                    ok.append({'name': name, 'price': p_.text})
                elif p_.conf >= OCR_GOOD_CONF and l.conf >= OCR_GOOD_CONF:
                    bad.append({'name': name, 'price': p_.text})
                else:
                    unsure.append({'name': name, 'price': p_.text, 'reason': 'read with low confidence'})
        if bad:
            return 'fail', {'wrong_price': bad}
        if unsure:
            return PERSON, {'reason': 'some rows could not be decided', 'rows': unsure}
        return 'pass', {'rows': ok}
    if a.get('names'):
        want = list(a['names'])
        missing = [n for n in want if sum(r2._whole(g, [n]) for g in got) == 0]
        twice = [n for n in want if sum(r2._whole(g, [n]) for g in got) > 1]
        extra = [g for g in got if not r2._whole(g, want)]
        ev = {'listed': got, 'missing': missing, 'repeated': twice, 'other': extra}
        if missing or twice or extra:
            return ('fail' if reliable else PERSON), dict(ev, reason='' if reliable else 'not every line read clearly')
        if not a.get('block'):
            return 'pass', ev
    items = [b for r in rows for b in (r[0].bbox, r[1].bbox)]
    box = (min(b[0] for b in items), min(b[1] for b in items), max(b[2] for b in items), max(b[3] for b in items))
    inside = [l.text for l in layer.lines if l not in [x for r in rows for x in r] and _wording(l)
              and base._overlap(l.bbox, box) > 0.5 and (l.bbox[2] - l.bbox[0]) * (l.bbox[3] - l.bbox[1]) > 0]
    mask = r3._photo_mask(path, a)
    x0, y0, x1, y1 = (int(v) for v in box)
    photo = float(mask[y0:y1, x0:x1].mean()) if y1 > y0 and x1 > x0 else 0.0
    ev = {'block': [x0, y0, x1, y1], 'other_text': inside[:4], 'photo_share': round(photo, 3)}
    if inside or photo > 0.05:
        return 'fail', ev
    return 'pass', ev


def op_window_flat(path, a):
    """Where the supplied photo (photo) is used, its blown-out area (supplied pixels at 250 or more in every channel)
    stays plain: cropped away, or shown with every channel's spread at most 3 and no edge. Texture or edges there
    (invented scenery) fail; in between a person. Not used: a pass when every photograph on the file belongs to
    another supplied file (known)."""
    import cv2
    got = _placed(str(path), a['photo'], tuple(a.get('_asset_dirs') or []))
    if got is None:
        st, ev = op_each_photo(path, dict({'op': 'v2_each_photo_pb', 'photos': [], 'known': a.get('known', []), 'then': {}},
                                          **{k: v for k, v in a.items() if k.startswith('_')}))
        return ('pass', {'reason': 'the photo is not used'}) if st == 'pass' else (PERSON, dict(ev, reason='photo not found; another photograph is present'))
    rgb = _scene_rgb(path, got['page'])
    blown = (got['src'] >= 250).all(axis=2) & got['valid']
    blown = cv2.erode(blown.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    if blown.sum() < 200:
        return 'pass', {'reason': 'the blown-out area is cropped away', 'px': int(blown.sum())}
    px = rgb[blown]
    spread = float(px.std(axis=0).max())
    gray = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120) > 0
    edge_share = float(edges[blown].mean())
    ev = {'px': int(blown.sum()), 'spread': round(spread, 2), 'edge_share': round(edge_share, 4)}
    if spread <= 3 and edge_share <= 0.002:
        return 'pass', ev
    if spread >= 8 and edge_share >= 0.01:
        return 'fail', ev
    return PERSON, dict(ev, reason='some variation in the blown-out area')


# ---------------------------------------------------------------- wording, ignoring lettering inside photographs


def op_text_pb(path, a):
    """Wording checks on the type of a file, leaving out lettering that belongs to a supplied photograph (photos)
    and judging OCR confidence on the type alone. expected: items that must appear (an item may list alternatives;
    {'regex': ...} allowed); forbidden: items that must not; if_any: the check applies only where this pattern
    appears. A fail needs a clear read: a forbidden item on a line read at 80% or more, or an expected item missing
    with every line of type read at 80% or more and nothing close to it; otherwise a person."""
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    pdf = layer.source == 'pdf'
    lines = [l for l in layer.lines if pdf or not (_in_photo(path, a, l.bbox) and _photo_content(path, a, l.bbox))]
    lines = [l for l in lines if pdf or base._real(l) or (_wording(l) and l.conf >= 60)]
    sure = pdf or all(l.conf >= OCR_GOOD_CONF for l in lines if _wording(l) and not _in_photo(path, a, l.bbox))
    hay = ' '.join(_text(l) for l in lines)
    hit = lambda text, item: re.search(item['regex'], canon(text), re.I) if isinstance(item, dict) else contains(text, item, False)
    if a.get('if_any') and not re.search(a['if_any'], canon(hay), re.I):
        return ('pass', {'reason': 'not shown (the check applies only where it appears)'}) if sure else \
            (PERSON, {'reason': 'could not rule out that it appears'})
    line_hit = lambda it: [l for l in lines if re.search(it['line'], canon(_text(l)), re.I) and len(_text(l).split()) <= it.get('max_words', 99)]
    found = [it if isinstance(it, str) else it.get('regex') or it['line'] for it in a.get('forbidden', [])
             if (line_hit(it) if isinstance(it, dict) and 'line' in it else hit(hay, it))]
    if found:
        strong = [l.text for l in lines if (pdf or l.conf >= OCR_GOOD_CONF) and any(
            (re.search(it['line'], canon(_text(l)), re.I) if isinstance(it, dict) and 'line' in it else hit(_text(l), it)) for it in a.get('forbidden', []))]
        if a.get('found') == PERSON:
            return PERSON, {'reason': 'present: a person checks it', 'found': found, 'lines': strong[:3]}
        return ('fail', {'found': found, 'lines': strong[:3]}) if strong else (PERSON, {'reason': 'read with low confidence', 'found': found})
    missing = []
    for opts in a.get('expected', []):
        opts = opts if isinstance(opts, list) else [opts]
        if not any((line_hit(o) if isinstance(o, dict) and 'line' in o else hit(hay, o)) for o in opts):
            missing.append([o if isinstance(o, str) else o.get('regex') or o['line'] for o in opts])
    if missing and a.get('missing') == PERSON:
        return PERSON, {'reason': 'not found as written: a person reads it', 'missing': missing}
    if missing:
        plain = [o for m in missing for o in m if not re.search(r'[\\\[\]()?*+|]', o)]
        near = max((base.near_miss(hay, o) for o in plain), default=0.0)
        if pdf or (sure and near < base.NEAR_MISS):
            return 'fail', {'missing': missing}
        return PERSON, {'reason': 'not read clearly', 'missing': missing, 'similarity': round(near, 2)}
    if not sure and (a.get('forbidden') and not a.get('expected')):
        return PERSON, {'reason': 'text not read clearly enough to rule it out'}
    return 'pass', {'checked': len(a.get('expected', [])) + len(a.get('forbidden', []))}


# ---------------------------------------------------------------- proportions of a placed photo


def op_photo_aspect(path, a):
    """The supplied photo is placed without stretching: from the matched corners, the horizontal and vertical scales
    agree within 1% and the corner angles stay square within 1 degree (a fail beyond 3% or 3 degrees; between, a
    person). PDFs: every page is searched. Not found: a person."""
    asset = None
    try:
        asset = base._load_gray(base.asset_path(a, a['photo']))
    except FileNotFoundError:
        return PERSON, {'reason': 'supplied photo not available'}
    for i, scene in enumerate(base._scenes(path)):
        n, corners, state = base.find_asset(scene, asset)
        if state != 'found':
            continue
        h, w = asset.shape
        c = np.float32(corners)
        top, bottom = np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[2] - c[3])
        left, right = np.linalg.norm(c[3] - c[0]), np.linalg.norm(c[2] - c[1])
        sx, sy = (top + bottom) / 2 / w, (left + right) / 2 / h
        ratio = float(sx / sy)
        def angle(p, q, r):
            u, v = q - p, r - p
            return float(np.degrees(np.arccos(np.clip((u @ v) / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9), -1, 1))))
        skew = max(abs(angle(c[0], c[1], c[3]) - 90), abs(angle(c[2], c[1], c[3]) - 90))
        ev = {'page': i + 1, 'scale_ratio': round(ratio, 4), 'skew_deg': round(skew, 2)}
        if abs(ratio - 1) <= 0.01 and skew <= 1:
            return 'pass', ev
        if abs(ratio - 1) >= 0.03 or skew >= 3:
            return 'fail', ev
        return PERSON, dict(ev, reason='a small difference in proportion')
    return PERSON, {'reason': 'supplied photo not found'}


# ---------------------------------------------------------------- blocks of PDF text


def _find_lines(layer, text):
    hits = [l for l in layer.lines if contains(_text(l), text, False)]
    return hits or base._span(layer, text, max_lines=6)


def op_pdf_block(path, a):
    """Named texts form one block on one page: texts (each found as a line or a run of lines); consecutive: they are
    consecutive lines sharing a left edge (within 2 pt); clear: nothing else overlaps the box enclosing them (no
    other text but allow, no placed picture, no filled shape but the page ground), and with drawn_after nothing is
    drawn after the texts over their boxes."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = _layer(path)

    def occurrences(t=None, rx=None):
        if rx is not None:
            return [[l] for l in layer.lines if r2._rxs(rx, _text(l))]
        hits = [l for l in layer.lines if contains(_text(l), t, False)]
        if hits:
            return [[l] for l in hits]
        span = base._span(layer, t, max_lines=6)
        return [span] if span else []
    first = occurrences(a['texts'][0])
    if not first:
        return PERSON, {'reason': f'text not found: {a["texts"][0][:40]}'}
    anchor = first[0]
    ay = (min(l.bbox[1] for l in anchor) + max(l.bbox[3] for l in anchor)) / 2
    groups = [anchor]
    # a text set more than once (an event name also inside a placeholder panel): the occurrence nearest the first
    # text is the one in its block
    for t, rx in [(t, None) for t in a['texts'][1:]] + [(None, rx) for rx in a.get('patterns', [])]:
        occ = [g for g in occurrences(t, rx) if g[0].page == anchor[0].page]
        if not occ:
            return PERSON, {'reason': f'text not found: {(t or rx)[:40]}'}
        groups.append(min(occ, key=lambda g: abs((min(l.bbox[1] for l in g) + max(l.bbox[3] for l in g)) / 2 - ay)))
    mine = [l for g in groups for l in g]
    pages = {l.page for l in mine}
    if len(pages) > 1:
        return 'fail', {'reason': 'the texts sit on different pages'}
    page = pages.pop()
    box = (min(l.bbox[0] for l in mine), min(l.bbox[1] for l in mine), max(l.bbox[2] for l in mine), max(l.bbox[3] for l in mine))
    ev = {'page': page + 1, 'box': [round(v, 1) for v in box]}
    if a.get('consecutive'):
        order = sorted(set(mine), key=lambda l: l.bbox[1])
        between = [l for l in layer.lines if l.page == page and l not in mine and box[1] < (l.bbox[1] + l.bbox[3]) / 2 < box[3]
                   and r2._xoverlap(l.bbox, box)]
        lefts = {round(l.bbox[0]) for l in order}
        if between or max(lefts) - min(lefts) > 2:
            return 'fail', dict(ev, reason='not consecutive lines on one left edge', between=[l.text[:30] for l in between][:3])
    doc = pymupdf.open(path)
    pg = doc[page]
    W, H = pg.rect.width, pg.rect.height
    others = [l.text[:40] for l in layer.lines if l.page == page and l not in mine and base._overlap(l.bbox, box) > 0.2
              and not any(re.search(p_, _text(l), re.I) for p_ in a.get('allow', []))]
    pics = [b for b in r2._pdf_images(str(path)).get(page, []) if base._overlap(b, box) > 0.02]
    shapes = []
    for d in pg.get_drawings():
        r = d['rect']
        if d.get('fill') is None or (r.width >= 0.95 * W and r.height >= 0.95 * H):
            continue
        ix = max(0, min(r.x1, box[2]) - max(r.x0, box[0]))
        iy = max(0, min(r.y1, box[3]) - max(r.y1 - r.height, box[1]))
        if ix * iy > 0 and min(r.width, r.height) > 2:
            shapes.append([round(v) for v in (r.x0, r.y0, r.x1, r.y1)])
    if others or pics or shapes:
        return 'fail', dict(ev, other_text=others[:3], pictures=len(pics), shapes=shapes[:3])
    return 'pass', ev


def op_pdf_covered(path, a):
    """Nothing is drawn over the named texts: no picture, filled shape or other text later in the drawing order
    overlaps their boxes."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = _layer(path)
    targets = [l for t in a['texts'] for l in _find_lines(layer, t)]
    if not targets:
        return PERSON, {'reason': 'texts not found'}
    doc = pymupdf.open(path)
    bad = []
    for page in {l.page for l in targets}:
        order = _zorder(doc[page])
        boxes = [l.bbox for l in targets if l.page == page]
        idx = [i for i, (k, r) in enumerate(order) if k == 'text' and any(base._overlap(r, b) > 0.5 for b in boxes)]
        if not idx:
            return PERSON, {'reason': 'texts not found in the drawing order'}
        last = max(idx)
        for k, r in order[last + 1:]:
            if k == 'text':
                if any(base._overlap(r, b) > 0.3 for b in boxes):
                    bad.append({'page': page + 1, 'kind': k, 'box': [round(v) for v in r]})
            elif any(max(0, min(r[2], b[2]) - max(r[0], b[0])) * max(0, min(r[3], b[3]) - max(r[1], b[1])) > 4 for b in boxes):
                bad.append({'page': page + 1, 'kind': k, 'box': [round(v) for v in r]})
    return ('fail', {'drawn_over': bad[:4]}) if bad else ('pass', {'lines': len(targets)})


def op_pdf_portraits(path, a):
    """The PDF carries exactly one placed picture, and it shows one of the supplied portraits (photos): two or more
    portraits, or none, fail; an unmatched picture goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    pics = _pdf_photos(str(path), tuple(a['photos'] + a.get('others', [])), tuple(a.get('_asset_dirs') or []))
    portraits = [p_ for p_ in pics if p_['name'] in a['photos']]
    other = [p_ for p_ in pics if p_['name'] in a.get('others', [])]
    unknown = [p_ for p_ in pics if p_['name'] is None]
    ev = {'portraits': [p_['name'] for p_ in portraits], 'others': [p_['name'] for p_ in other], 'unmatched': len(unknown)}
    if len(portraits) >= 2:
        return 'fail', ev
    if unknown:
        return PERSON, dict(ev, reason='a picture not matched to a supplied photo')
    if len(portraits) == 1 and not other:
        return 'pass', ev
    return 'fail', ev


# ---------------------------------------------------------------- the ground behind a cut-out sitter


def _sitter_panel(path, a):
    """(rgb, ground mask, sitter mask, tone) for the supplied photo's cut-out subject, or a reason string."""
    import cv2
    names = [a['photo']] if a.get('photo') else a.get('photos', [])
    found = _found_photos(path, a, names)
    if not found:
        return 'supplied photo not found'
    name, box = found[0]
    rgb = r3._pixels(str(path))
    ground = _sitter_ground_b(rgb, box)
    if ground is None:
        return 'no flat ground round the subject'
    got = _placed(str(path), name, tuple(a.get('_asset_dirs') or []))
    if got is None:
        return 'supplied photo not placed clearly'
    src, valid = got['src'], got['valid']
    sitter = valid & (cv2.blur(np.abs(rgb.astype(np.float32) - src).max(axis=2), (5, 5)) < 40)
    sitter = cv2.morphologyEx(sitter.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)) > 0
    return rgb, ground, sitter, np.median(rgb[ground], axis=0), name


def op_sitter_ground_even(path, a):
    """The ground behind a cut-out sitter is one flat, even tone: inside the box of the flat ground round the sitter,
    every pixel not the sitter (nor within 12 px of it, nor type) is within the tolerance of the ground's median
    colour. Off pixels over 5% of that area (a gradient, vignette or pattern) fail; 0.5% or less passes."""
    import cv2
    got = _sitter_panel(path, a)
    if isinstance(got, str):
        return PERSON, {'reason': got}
    rgb, ground, sitter, tone, name = got
    ys, xs = np.where(ground)
    panel = np.zeros(ground.shape, bool)
    panel[ys.min():ys.max() + 1, xs.min():xs.max() + 1] = True
    near = cv2.dilate(sitter.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0
    text = np.zeros(ground.shape, bool)
    for l in _layer(path).lines:
        x0, y0, x1, y1 = (int(v) for v in l.bbox)
        text[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = True
    area = panel & ~near & ~text
    if area.sum() < 1000:
        return PERSON, {'reason': 'too little ground to read'}
    off = float((np.abs(rgb[area] - tone).max(axis=1) > r3._tol(path, a)).mean())
    ev = {'photo': name, 'ground': _hex(tone), 'off_share': round(off, 4)}
    if off <= 0.005:
        return 'pass', ev
    return ('fail' if off >= 0.05 else PERSON), ev


def op_sitter_ground_same(path, a):
    """The ground behind a cut-out sitter is the same tone as on another delivered file (deliverable, with its own
    supplied photo other_photo): the medians of the two flat grounds within the tolerance pass; 30 or more apart
    fails; between, a person."""
    got = _sitter_panel(path, a)
    if isinstance(got, str):
        return PERSON, {'reason': got}
    other = Path(a['_artifacts']) / a['deliverable']
    if not other.is_file():
        return PERSON, {'reason': 'the reference file is not available'}
    ref = _sitter_panel(other, dict(a, photo=a['other_photo'], photos=None))
    if isinstance(ref, str):
        return PERSON, {'reason': 'reference: ' + ref}
    d = float(np.abs(got[3] - ref[3]).max())
    ev = {'ground': _hex(got[3]), 'reference_ground': _hex(ref[3]), 'max_channel_difference': round(d, 1)}
    if d <= r3._tol(path, a):
        return 'pass', ev
    return ('fail' if d >= 30 else PERSON), ev


# ---------------------------------------------------------------- PDF marks, paint and letter spacing


def op_pdf_printer_marks(path, a):
    """No crop or registration marks: no short thin strokes in the corners (within 15% of the page from a corner,
    under 40 pt long, 1 pt or thinner, in pairs) and no small circle crossed by lines (a registration target);
    no bleed box larger than the trim box."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    bad = []
    for page in pymupdf.open(path):
        W, H = page.rect.width, page.rect.height
        if page.bleedbox != page.trimbox and page.bleedbox.width > page.trimbox.width + 1:
            bad.append({'page': page.number + 1, 'bleed': [round(v) for v in page.bleedbox]})
        corner_strokes, circles = 0, 0
        for d in page.get_drawings():
            r = d['rect']
            for it in d['items']:
                if it[0] == 'l':
                    p0, p1 = it[1], it[2]
                    length = float(np.hypot(p1.x - p0.x, p1.y - p0.y))
                    cx, cy = (p0.x + p1.x) / 2, (p0.y + p1.y) / 2
                    in_corner = (min(cx, W - cx) <= 0.15 * W) and (min(cy, H - cy) <= 0.15 * H)
                    if length < 40 and (d.get('width') or 0) <= 1 and in_corner and d.get('color') is not None:
                        corner_strokes += 1
                elif it[0] == 'c' and r.width < 30 and abs(r.width - r.height) < 2:
                    circles += 1
        if corner_strokes >= 4:
            bad.append({'page': page.number + 1, 'corner_strokes': corner_strokes})
        if circles >= 4:
            bad.append({'page': page.number + 1, 'small_circles': circles})
    return ('fail', {'marks': bad[:4]}) if bad else ('pass', {'pages': len(pymupdf.open(path))})


def op_pdf_flat_paint(path, a):
    """Every shape and line of type is painted in one flat colour at full opacity: no fill or stroke opacity under 1,
    no shading or pattern, no soft mask or blend mode in the graphics states used, no transparent text."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(path)
    bad = []
    for page in doc:
        for d in page.get_drawings():
            for k in ('fill_opacity', 'stroke_opacity'):
                if d.get(k) is not None and d[k] < 0.999:
                    bad.append({'page': page.number + 1, k: d[k]})
        stream = b''.join(doc.xref_stream(x) or b'' for x in page.get_contents()).decode('latin-1')
        if re.search(r'(?<![\w/])sh\b', stream) or re.search(r'/Pattern\s+(?:cs|CS)\b', stream):
            bad.append({'page': page.number + 1, 'shading_or_pattern': True})
        for gs in set(re.findall(r'/(\S+)\s+gs\b', stream)):
            kind, val = doc.xref_get_key(page.xref, f'Resources/ExtGState/{gs}')
            if kind == 'xref':
                val = doc.xref_object(int(val.split()[0]))
            m = re.search(r'/BM\s*/(\w+)', val or '')
            if m and m.group(1) not in ('Normal', 'Compatible'):
                bad.append({'page': page.number + 1, 'blend': m.group(1)})
            if re.search(r'/SMask\s*(?!/None)\S', val or ''):
                bad.append({'page': page.number + 1, 'soft_mask': gs})
        for sp in (sp for l in _pdf_lines(str(path)) if l.page == page.number for sp in l.spans):
            if sp.get('alpha', 255) < 255:
                bad.append({'page': page.number + 1, 'text_alpha': sp['text'][:20]})
    return ('fail', {'not_flat': bad[:5]}) if bad else ('pass', {'pages': len(doc)})


def op_pdf_tracking(path, a):
    """Selected lines are tracked open: their letter spacing (median glyph gap over size, from the PDF) is at least
    open_em more than the commonest text's (the spacing carrying the most characters among the other lines); under
    tight_em more fails; between, a person. Selected: lines in the colour at the page foot (foot_colour), or lines
    reading a name exactly (names). None selected: a pass."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    chars = r2._pdf_lines_chars(str(path))
    lines = _pdf_lines(str(path))
    def pl(c):
        return next((l for l in lines if l.page == c['page'] and base._overlap(l.bbox, c['bbox']) > 0.5), None)
    picked, rest = [], []
    for c in chars:
        l = pl(c)
        if l is None:
            continue
        sel = False
        if a.get('foot_colour') and _footer(path, l) and any(base._near_hex(x, [a['foot_colour']], 3) for x in l.colors):
            sel = True
        if a.get('names') and _product_of(_text(l), a['names']):
            sel = True
        (picked if sel else rest).append((c, l))
    if not picked:
        return 'pass', {'reason': 'none present'}
    weight = {}
    for c, l in rest:
        k = round(c['tracking'], 2)
        weight[k] = weight.get(k, 0) + len(c['text'])
    if not weight:
        return PERSON, {'reason': 'no other text to compare with'}
    common = max(sorted(weight), key=weight.get)
    extra = [round(c['tracking'] - common, 3) for c, _ in picked]
    ev = {'commonest_em': common, 'extra_em': sorted(set(extra))[:6]}
    if min(extra) >= a.get('open_em', 0.08):
        return 'pass', ev
    if min(extra) < a.get('tight_em', 0.02):
        return 'fail', ev
    return PERSON, dict(ev, reason='only a little looser than the commonest text')


def op_ask(path, a):
    """Always a person: used where a check settles only the files without the element."""
    return PERSON, {'reason': a.get('reason', 'present: a person checks it')}


# ---------------------------------------------------------------- what is left of a photo's original background


def op_bg_remnant(path, a):
    """None of the supplied photo's original backdrop remains round the subject: the backdrop colour is read from the
    photo's top corners; pixels on the file still equal to the supplied photo there (within 12 per channel) and in
    that colour (within 18) are remnants. A remnant patch of 1% of the shown photo or 400 px fails; none passes,
    provided the backdrop colour differs from whatever replaced it (else a person). PDFs: the embedded pictures.
    Not found: a pass when no photograph on the file is unmatched (absent 'pass'), else a person."""
    import cv2
    names = [a['photo']] if a.get('photo') else a.get('photos', [])
    pairs = []
    if path.suffix.lower() == '.pdf':
        for pic in _pdf_photos(str(path), tuple(names), tuple(a.get('_asset_dirs') or [])):
            if pic['name']:
                pairs.append((pic['name'], pic['rgb'].astype(np.float32), pic['src'].astype(np.float32), pic['valid']))
    else:
        for name in names:
            got = _placed(str(path), name, tuple(a.get('_asset_dirs') or []))
            if got is not None:
                pairs.append((name, _scene_rgb(path, got['page']), got['src'].astype(np.float32), got['valid']))
                break
    if not pairs:
        if a.get('absent') == 'pass':
            if path.suffix.lower() == '.pdf':
                return ('pass', {'reason': 'no picture placed'}) if not r2._pdf_images(str(path)).get(0) else (PERSON, {'reason': 'a picture not matched'})
            st, ev = op_each_photo(path, dict({'photos': [], 'known': a.get('known', []), 'then': {}}, **{k: v for k, v in a.items() if k.startswith('_')}))
            return ('pass', {'reason': 'the photo is not used'}) if st == 'pass' else (PERSON, dict(ev, reason='supplied photo not found'))
        return PERSON, {'reason': 'supplied photo not found'}
    out = []
    for name, rgb, src, valid in pairs:
        full = np.asarray(Image.open(base.asset_path(a, name)).convert('RGB')).astype(np.float32)
        h, w = full.shape[:2]
        k = max(4, int(0.06 * min(h, w)))
        corners = np.concatenate([full[:k, :k].reshape(-1, 3), full[:k, -k:].reshape(-1, 3)])
        backdrop = np.median(corners, axis=0)
        if float(np.abs(corners - backdrop).max(axis=1).mean()) > 20:
            out.append((PERSON, {'photo': name, 'reason': 'the supplied photo has no plain backdrop at its top corners'}))
            continue
        if backdrop.max() < 70:
            out.append((PERSON, {'photo': name, 'backdrop': _hex(backdrop), 'reason': 'a dark backdrop looks like hair or a jacket'}))
            continue
        same = (np.abs(rgb - src).max(axis=2) <= 12) & valid
        drop = np.abs(src - backdrop).max(axis=2) <= 18
        remnant = cv2.morphologyEx((same & drop).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        ys_, xs_ = np.where(valid)
        upper = ys_.min() + 0.5 * (ys_.max() - ys_.min())
        n, labels, stats, _ = cv2.connectedComponentsWithStats(remnant, connectivity=8)
        tops = [int(stats[i][4]) for i in range(1, n) if stats[i][1] < upper]
        biggest = max(tops) if tops else 0
        shown = int(valid.sum())
        replaced = valid & drop & ~(same)
        new_ground = np.median(rgb[replaced], axis=0) if replaced.sum() >= 200 else None
        ev = {'photo': name, 'backdrop': _hex(backdrop), 'largest_remnant_px': biggest, 'shown_px': shown,
              'replaced_by': _hex(new_ground) if new_ground is not None else None}
        if biggest >= max(400, 0.01 * shown):
            out.append(('fail', ev))
        elif biggest <= 50 and new_ground is not None and float(np.abs(new_ground - backdrop).max()) >= 20:
            out.append(('pass', ev))
        else:
            out.append((PERSON, dict(ev, reason='little or no backdrop left, but the new ground is close to it')))
    states = [s_ for s_, _ in out]
    evs = [e for _, e in out]
    if 'fail' in states:
        return 'fail', {'photos': evs[:3]}
    if PERSON in states:
        return PERSON, {'reason': 'could not be decided', 'photos': evs[:3]}
    return 'pass', {'photos': evs[:3]}


# ---------------------------------------------------------------- a printed monogram: size, place and count


def _mark_groups(path, colour, page=0):
    """Groups of one colour on a page (the monogram's strokes), each a box in pixels at RENDER_DPI (PDF) or image
    pixels: pieces within 3% of the page's short side of each other form one group."""
    import cv2
    if path.suffix.lower() == '.pdf':
        rgb = np.asarray(base.render_pdf(path, page, base.RENDER_DPI)).astype(int)
    else:
        rgb = r3._pixels(str(path)).astype(int)
    m = (np.abs(rgb - r3._hex_rgb(colour)) <= 14).all(axis=2).astype(np.uint8)
    if m.sum() < 30:
        return rgb, []
    k = max(3, int(0.03 * min(rgb.shape[:2])))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(m, np.ones((k, k), np.uint8)), connectivity=8)
    groups = []
    for i in range(1, n):
        px = int(m[labels == i].sum())
        if px < 30:
            continue
        ys, xs = np.where((labels == i) & (m > 0))
        groups.append({'box': (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)), 'px': px})
    return rgb, sorted(groups, key=lambda g: -g['px'])


def op_monogram(path, a):
    """The monogram printed in its colour (colour), read from the page's pixels (PDFs rendered at 150 dpi):
    min_px: at least that many pixels wide (images); narrower: narrower than the line reading that text alone;
    beneath: that line sits directly beneath it (top within 1.5 of the line's height below the mark, overlapping it
    across); once: exactly one group in the colour of a mark's size (another group at least half the size of the
    first fails). Not found in the colour: a person."""
    rgb, groups = _mark_groups(path, a['colour'])
    if not groups:
        return PERSON, {'reason': 'no mark in the colour found'}
    mark = groups[0]
    x0, y0, x1, y1 = mark['box']
    ev = {'mark_box': [x0, y0, x1, y1], 'groups': len(groups)}
    if a.get('once'):
        big = [g for g in groups if g['px'] >= 0.5 * mark['px']]
        if len(big) > 1:
            return 'fail', dict(ev, reason='more than one mark in the colour', boxes=[g['box'] for g in big][:3])
        small = [g for g in groups[1:] if g['px'] >= 30]
        return (PERSON, dict(ev, reason='smaller pieces in the colour too')) if small else ('pass', ev)
    if a.get('min_px'):
        wpx = x1 - x0
        ev['width_px'] = wpx
        return ('pass' if wpx >= a['min_px'] else 'fail' if wpx <= a['min_px'] - 2 else PERSON), ev
    layer = _layer(path)
    k = base.RENDER_DPI / 72 if path.suffix.lower() == '.pdf' else 1
    names = [l for l in layer.lines if l.page == 0 and r2._whole(_text(l), [a['text']]) and (layer.source == 'pdf' or _is_type(l))]
    if not names:
        return PERSON, {'reason': 'name line not found'}
    boxes = [tuple(v * k for v in l.bbox) for l in names]
    below = [b for b in boxes if b[1] >= y1 - 0.2 * (b[3] - b[1])]
    name = min(below, key=lambda b: b[1] - y1) if below else min(boxes, key=lambda b: abs(b[1] - y1))
    ev['name_box'] = [round(v) for v in name]
    if a.get('narrower'):
        return ('pass' if x1 - x0 < (name[2] - name[0]) * 0.98 else 'fail' if x1 - x0 > name[2] - name[0] else PERSON), ev
    if a.get('beneath'):
        gap = name[1] - y1
        across = min(name[2], x1) - max(name[0], x0) > 0
        hgt = name[3] - name[1]
        ev['gap_px'] = round(gap, 1)
        if across and -0.2 * hgt <= gap <= 1.5 * hgt:
            return 'pass', ev
        if not across or gap > 3 * hgt or gap < -hgt:
            return 'fail', ev
        return PERSON, ev
    return PERSON, {'reason': 'nothing to check'}


# ---------------------------------------------------------------- serif type and supplied copy


def op_serif_spans(path, a):
    """No text is set in a serif face (the PDF's own serif flag) apart from lines reading the allowed texts alone.
    Images: a person (type faces are read from PDFs)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'type faces are read from a PDF'}
    layer = _layer(path)
    if layer.source != 'pdf':
        return PERSON, {'reason': 'no live text'}
    bad = [(sp['text'][:30], sp['font']) for l in layer.lines if not r2._whole(_text(l), a.get('allow', []))
           for sp in l.spans if sp['text'].strip() and sp.get('serif')]
    return ('fail', {'serif_spans': bad[:6]}) if bad else ('pass', {'lines': len(layer.lines)})


def _vocab(tid_files, extra=()):
    words = set(extra)
    for f in tid_files:
        if f and Path(f).is_file():
            words |= set(re.findall(r"[a-z0-9]+", canon(Path(f).read_text(encoding='utf-8', errors='replace'), False)))
    return words


def op_copy_only(path, a):
    """Every word of the type comes from the supplied copy (files, plus extra words), so nothing is invented:
    an email, phone number, web address or figure the files do not hold fails, as does a forbidden pattern on a line
    read clearly; a word outside the copy goes to a person (it may be harmless wording); all from the copy passes,
    provided every line of type was read at 80% or more."""
    layer = _layer(path)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    pdf = layer.source == 'pdf'
    lines = [l for l in layer.lines if pdf or not (_in_photo(path, a, l.bbox) and _photo_content(path, a, l.bbox))]
    lines = [l for l in lines if pdf or _wording(l)]
    files = [base.asset_path(a, f) if not Path(f).is_absolute() else Path(f) for f in a['files']]
    vocab = _vocab(files, [w.lower() for w in a.get('extra', [])])
    text_all = ' '.join(canon(Path(f).read_text(encoding='utf-8', errors='replace'), False) for f in files)
    bad, odd = [], []
    for l in lines:
        t = canon(_text(l), False)
        sure = pdf or l.conf >= OCR_GOOD_CONF
        for rx in a.get('forbidden', []):
            if re.search(rx, t, re.I):
                (bad if sure else odd).append({'line': l.text[:50], 'pattern': rx})
        for m in re.finditer(r'[\w.+-]+@[\w-]+\.[\w.]+|https?://\S+|www\.\S+|\+?\d[\d ()-]{7,}\d|\d[\d,.]*', t):
            v = m.group(0)
            if v.strip('.,') not in text_all:
                (bad if sure and not re.fullmatch(r'\d[\d,.]*', v) else odd).append({'line': l.text[:50], 'not_in_copy': v})
        new = [w for w in re.findall(r"[a-z0-9]+", t) if w not in vocab]
        if new:
            odd.append({'line': l.text[:50], 'words': new[:4]})
    if bad:
        return 'fail', {'invented': bad[:4]}
    unread = [l.text[:40] for l in lines if not pdf and l.conf < OCR_GOOD_CONF]
    if odd or unread:
        return PERSON, {'reason': 'wording not all from the supplied copy, or not read clearly', 'lines': (odd or unread)[:4]}
    return 'pass', {'lines': len(lines)}


def op_action_box(path, a):
    """The action line (a line matching line, e.g. starting "Book") and the flat button round it (the one-colour
    area its letters sit on) lie inside the box [x0, y0, x1, y1] (inside: the canvas, at least 1 px from each edge).
    No such line: a person (the action may be worded otherwise)."""
    import cv2
    layer = _layer(path)
    hits = [l for l in layer.lines if _is_type(l) and re.search(a['line'], canon(_text(l)), re.I)]
    if not hits:
        return PERSON, {'reason': 'no action line read'}
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    box = a.get('box') or [1, 1, w - 1, h - 1]
    out = []
    for l in hits:
        info = r3._ink_and_ground(rgb, l.bbox)
        x0, y0, x1, y1 = (int(v) for v in l.bbox)
        if info is not None and info[2] >= 0.6:
            ground = np.abs(rgb - info[1]).max(axis=2) <= 6
            n, labels, stats, _ = cv2.connectedComponentsWithStats(ground.astype(np.uint8), connectivity=4)
            cy, cx = min(h - 1, y1 + 2), min(w - 1, (x0 + x1) // 2)
            lab = labels[cy, cx]
            if lab > 0 and stats[lab][4] < 0.25 * h * w:
                bx, by, bw, bh = stats[lab][:4]
                x0, y0, x1, y1 = min(x0, bx), min(y0, by), max(x1, bx + bw), max(y1, by + bh)
        inside = x0 >= box[0] and y0 >= box[1] and x1 <= box[2] and y1 <= box[3]
        out.append((inside, [x0, y0, x1, y1], l.text))
    ev = {'action': [(t, b) for _, b, t in out][:3], 'within': box}
    if all(i for i, _, _ in out):
        return 'pass', ev
    return 'fail', ev


# ---------------------------------------------------------------- the ground a cut-out sitter was set on


def _sitter_ground_b(rgb, box, min_share=0.02):
    """The flat one-colour area a cut-out sitter was set on: of the flat regions touching the sitter's box, the one
    that runs down both its left and right sides for a quarter of its height or more (a ground wraps the sitter; a
    header band or a text panel the sitter merely touches at the top or bottom does not). Returns its mask, or None."""
    import cv2
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    flat = r3._flat(rgb, 2)
    left = np.zeros((h, w), bool)
    right = np.zeros((h, w), bool)
    left[max(0, y0):min(h, y1), max(0, x0 - 8):min(w, x0 + 3)] = True
    right[max(0, y0):min(h, y1), max(0, x1 - 3):min(w, x1 + 8)] = True
    cand = rgb[(left | right) & flat]
    if not len(cand):
        return None
    values, counts = np.unique(cand // 4, axis=0, return_counts=True)
    best = None
    for v in values[np.argsort(-counts)][:4]:
        m = flat & (np.abs(rgb // 4 - v).max(axis=2) <= 1)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        # the pieces of this colour touching the sitter's sides (a sitter standing on the panel's lower edge splits
        # its ground into a left and a right piece)
        region = np.zeros((h, w), bool)
        for i in range(1, n):
            if stats[i][4] >= min_share * h * w:
                piece = labels == i
                if (piece & (left | right)).any():
                    region |= piece
        # rows of contact on each side: a ground runs down both sides of the sitter, while a header band the
        # sitter's box reaches into touches only its top rows
        contact = min(int((region & left).any(axis=1).sum()), int((region & right).any(axis=1).sum()))
        if contact >= 0.25 * max(1, y1 - y0) and (best is None or contact > best[1]):
            best = (region, contact)
    return best[0] if best else None


def _designed_b(path: Path, a):
    """(rgb, flat pixels outside photographs, area outside photographs), where a cut-out sitter's own ground
    (_sitter_ground_b) is left out with the photos when sitter_ground_b is set."""
    rgb = r3._pixels(str(path))
    dirs = tuple(a.get('_asset_dirs') or [])
    mask = r3._photo_mask_cached(str(path), tuple(a.get('photos', [])), dirs, -1, False).copy()
    grounds = []
    if a.get('sitter_ground_b'):
        for name, box in _found_photos(path, a, a.get('photos', [])):
            g = _sitter_ground_b(rgb, box)
            if g is not None:
                mask |= g
                grounds.append(_hex(np.median(rgb[g], axis=0)))
    outside = ~mask
    return rgb, r3._flat(rgb, 2 if not r3._lossy(path) else 6) & outside, outside, grounds


def op_palette_sitter(path, a):
    """objective_ops_r3 palette check (every flat designed colour is a palette colour) with the cut-out sitter's
    own ground left out as found by _sitter_ground_b."""
    rgb, flat, outside, grounds = _designed_b(path, a)
    if flat.sum() < 200:
        return PERSON, {'reason': 'almost no flat designed area found'}
    if a.get('sitter_ground_b') and not grounds:
        return PERSON, {'reason': 'the ground round the sitter was not found'}
    off = flat & ~r3._near_mask(rgb, a['hexes'], r3._tol(path, a))
    bad = {}
    for comp, st in r3._components(off):
        c = _hex(np.median(rgb[comp], axis=0))
        bad[c] = bad.get(c, 0) + int(st[4])
    if bad:
        top = sorted(bad.items(), key=lambda kv: -kv[1])[:5]
        return 'fail', {'outside_palette': [f'{c} ({n} px)' for c, n in top], 'sitter_ground': grounds}
    return 'pass', {'palette': a['hexes'], 'sitter_ground': grounds}


def op_grounds_sitter(path, a):
    """objective_ops_r3 grounds check (flat areas of 1% or more, outside photographs, are allowed colours) with
    the cut-out sitter's own ground left out as found by _sitter_ground_b."""
    import cv2
    rgb, flat, outside, grounds = _designed_b(path, a)
    if a.get('sitter_ground_b') and not grounds:
        return PERSON, {'reason': 'the ground round the sitter was not found'}
    h, w = rgb.shape[:2]
    q = rgb // 4
    code = (q[..., 0].astype(np.int32) << 12) | (q[..., 1].astype(np.int32) << 6) | q[..., 2].astype(np.int32)
    values, counts = np.unique(code[flat], return_counts=True)
    regions = []
    for v, c in sorted(zip(values, counts), key=lambda t: -t[1])[:12]:
        if c < 0.01 * h * w:
            break
        m = cv2.morphologyEx((flat & (code == v)).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
        for comp, st in r3._components(m, int(0.01 * h * w)):
            if min(st[2], st[3]) >= 0.03 * min(h, w):
                regions.append(_hex(np.median(rgb[comp & flat], axis=0)))
    if not regions:
        return PERSON, {'reason': 'no ground or panel found outside the photographs'}
    tol = r3._tol(path, a)
    bad = sorted({c for c in regions if not base._near_hex(c, a['hexes'], tol)})
    return ('fail', {'grounds_outside': bad, 'sitter_ground': grounds}) if bad else ('pass', {'grounds': sorted(set(regions)), 'sitter_ground': grounds})


def op_tone_sitter(path, a):
    """The ground behind the cut-out sitter (_sitter_ground_b) is a tone between two colours: each channel within the
    range they span, give or take tol (8). No such ground found: a person."""
    found = _found_photos(path, a, [a['photo']])
    if not found:
        return PERSON, {'reason': 'supplied portrait not found'}
    rgb = r3._pixels(str(path))
    g = _sitter_ground_b(rgb, found[0][1])
    if g is None:
        return PERSON, {'reason': 'no flat ground wrapping the sitter'}
    tone = np.median(rgb[g], axis=0)
    lo = np.minimum(r3._hex_rgb(a['hexes'][0]), r3._hex_rgb(a['hexes'][1])) - a.get('tol', 8)
    hi = np.maximum(r3._hex_rgb(a['hexes'][0]), r3._hex_rgb(a['hexes'][1])) + a.get('tol', 8)
    ev = {'tone': _hex(tone)}
    if ((tone >= lo) & (tone <= hi)).all():
        return 'pass', ev
    return ('fail' if np.maximum(lo - tone, tone - hi).max() > 20 else PERSON), ev

OPS.update({
    'v2_type_ink_pb': op_type_ink,
    'v2_type_has_colour_pb': op_type_has_colour,
    'v2_colour_only_as_pb': op_colour_only_as,
    'v2_mark_ground_pb': op_mark_ground,
    'v2_sitter_ground_pb': op_sitter_ground,
    'v2_each_photo_pb': op_each_photo,
    'v2_palette_marks_pb': op_palette_marks,
    'v2_solid_raster_pb': op_solid_raster,
    'v2_line_chars_pb': op_line_chars,
    'v2_above_role_pb': op_above_role,
    'v2_role_style_pb': op_role_style,
    'v2_pdf_grounds_pb': op_pdf_grounds,
    'v2_pdf_overlay_pb': op_pdf_overlay,
    'v2_product_text_pb': op_product_text,
    'v2_photo_compare_pb': op_photo_compare,
    'v2_mark_solid_pb': op_mark_solid,
    'v2_wordmark_pb': op_wordmark,
    'v2_price_list_pb': op_price_list,
    'v2_window_flat_pb': op_window_flat,
    'v2_pdf_photos_pb': op_pdf_photos,
    'v2_text_pb': op_text_pb,
    'v2_photo_aspect_pb': op_photo_aspect,
    'v2_pdf_block_pb': op_pdf_block,
    'v2_pdf_covered_pb': op_pdf_covered,
    'v2_pdf_portraits_pb': op_pdf_portraits,
    'v2_sitter_ground_even_pb': op_sitter_ground_even,
    'v2_sitter_ground_same_pb': op_sitter_ground_same,
    'v2_pdf_printer_marks_pb': op_pdf_printer_marks,
    'v2_pdf_flat_paint_pb': op_pdf_flat_paint,
    'v2_pdf_tracking_pb': op_pdf_tracking,
    'v2_ask_pb': op_ask,
    'v2_bg_remnant_pb': op_bg_remnant,
    'v2_monogram_pb': op_monogram,
    'v2_serif_spans_pb': op_serif_spans,
    'v2_copy_only_pb': op_copy_only,
    'v2_action_box_pb': op_action_box,
    'v2_palette_sitter_pb': op_palette_sitter,
    'v2_grounds_sitter_pb': op_grounds_sitter,
    'v2_tone_sitter_pb': op_tone_sitter,
})

# registered also when this module is imported before objective_ops (the circular import then saw an empty OPS)
base.OPS.update(OPS)
r3.OPS_R3.update(OPS)
