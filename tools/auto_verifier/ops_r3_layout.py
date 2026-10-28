"""Round 3 operations for the layout, sticker and motion tasks (LAYOUT-15, LAYOUT-12, VECTOR-04, MOTION-11),
2026-10-28.

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person";
nothing passes on a failed read, and a "person" answer carries a reason. PDF operations read the page's own drawing
list, text spans and colour operators in drawing order, so a shape hidden under a photograph, or laid over one, is
told apart. Raster operations leave photographs out (textured areas, supplied photos where found, two-colour photo
treatments, capture footage matched to its source video) and read only flat colour, so anti-aliased edges never
decide a check. Colour tolerance follows the 2026-10-22 policy (5 per RGB channel; 8 on JPEG and video frames;
text ink read from letter cores gets 3 more; 30 or more from every allowed colour fails, in between a person).
"""
from __future__ import annotations

OPS: dict = {}          # filled at the end; defined first so a circular import finds it

import functools
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

import objective_ops as base
import objective_ops_r2 as r2
import objective_ops_r3 as r3
from objective_ops import PERSON, OCR_GOOD_CONF, canon, contains

TOL_PDF = 2               # colours written in a PDF or SVG are exact numbers
FAR = 30                  # this far (per channel) from every allowed colour is a sure miss
OPAQUE = 250              # alpha read as opaque when reading colour (supplied cut-outs hold their inside at 250 to 254)
DATE_RX = (r'(?<!\d)\d{1,2}\s*(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\b'
           r'|\b(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?\s*\d{1,2}(?!\d)')


def _dist(rgb, hexes):
    """Largest channel difference from the nearest of the colours."""
    return min(float(np.abs(np.asarray(rgb, float)[:3] - r3._hex_rgb(h)).max()) for h in hexes)


def _verdict(dist, tol):
    return 'ok' if dist <= tol else ('far' if dist >= FAR else 'near')


def _blend_residual(rgb, hexes):
    """How far a colour lies from every straight blend between two of the colours (anti-aliasing, a two-colour photo
    treatment or a tint mixes two colours along that line)."""
    c = np.asarray(rgb, float)[:3]
    best = 1e9
    for i, a in enumerate(hexes):
        for b in hexes[i + 1:]:
            p0, p1 = r3._hex_rgb(a).astype(float), r3._hex_rgb(b).astype(float)
            d = p1 - p0
            t = float(np.clip((c - p0) @ d / max(d @ d, 1e-9), 0, 1))
            best = min(best, float(np.abs(c - (p0 + t * d)).max()))
    return best


def _sub(a):
    return {k: v for k, v in a.items() if k.startswith('_')}


# ================================================================ PDF: pages, drawings in drawing order


def _area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def _inter(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _within(inner, outer, slack=1.0):
    return inner[0] >= outer[0] - slack and inner[1] >= outer[1] - slack and inner[2] <= outer[2] + slack and inner[3] <= outer[3] + slack


@functools.lru_cache(maxsize=16)
def _pdf_pages(key: str):
    """Per page: size, placed pictures and gradient fills with their place in the drawing order (the page's bbox log),
    and the drawings (each with its own sequence number in that order)."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        log = page.get_bboxlog()
        out.append(dict(
            W=page.rect.width, H=page.rect.height,
            images=[(i, tuple(r)) for i, (kind, r) in enumerate(log) if kind == 'fill-image'],
            shades=[(i, tuple(r)) for i, (kind, r) in enumerate(log) if kind == 'fill-shade'],
            texts=[(i, tuple(r)) for i, (kind, r) in enumerate(log) if 'text' in kind],
            drawings=page.get_drawings()))
    return out


def _raster_page(info) -> bool:
    """Placed pictures cover 90% or more of the page: the design itself may be a picture, unreadable as vectors."""
    W, H = info['W'], info['H']
    m = np.zeros((int(H // 4) + 1, int(W // 4) + 1), bool)
    for _, (x0, y0, x1, y1) in info['images']:
        m[max(0, int(y0 // 4)):max(0, int(y1 // 4) + 1), max(0, int(x0 // 4)):max(0, int(x1 // 4) + 1)] = True
    return m.mean() >= 0.9


def op_gate(path, a):
    """Runs a PDF vector check only where the design is drawn as vectors: a page mostly covered by placed pictures
    (or, with full_width_image, carrying a picture as wide as the page, which could hide a full-width rule) goes to a
    person, never to the check."""
    if path.suffix.lower() == '.pdf':
        for n, info in enumerate(_pdf_pages(str(path))):
            if _raster_page(info):
                return PERSON, {'reason': 'the page is mostly a placed picture; its shapes cannot be read as vectors', 'page': n + 1}
            if a.get('full_width_image') and any((b[2] - b[0]) >= 0.95 * info['W'] for _, b in info['images']):
                return PERSON, {'reason': 'a picture spans the page width and could carry a rule inside it', 'page': n + 1}
            if not info['drawings'] and not info['texts']:
                return PERSON, {'reason': 'no vector shapes or live text on the page', 'page': n + 1}
    return base.run(path, dict(a['check'], **_sub(a)))


def _kind(d, which):
    """A drawing's role from its geometry: a rule (a straight stroke 6 pt wide or less, or a filled bar 6 pt deep or
    less and 8 times as long), a keyline (any other stroke 3 pt wide or less: an outline or frame line), a frame (a
    wider outline) or an area (any other fill). Returns (kind, thickness pt, length pt)."""
    r = d['rect']
    short, long_ = sorted((r.width, r.height))
    if which == 'stroke':
        w = float(d.get('width') or 1.0)
        items = d.get('items') or []
        straight = (len(items) == 1 and items[0][0] == 'l') or short <= 0.5
        if straight:
            return ('rule' if w <= 6 else 'area'), round(w, 2), long_ + (0 if items and items[0][0] == 'l' else 0)
        return ('keyline' if w <= 3 else 'frame'), round(w, 2), long_
    if short <= 6 and long_ >= 8 * max(short, 0.25):
        return 'rule', round(short, 2), long_
    return 'area', round(short, 2), long_


def _uses(info, hexes, skip_in_images=True):
    """Every visible use of the colours on one page as a drawing: hidden ones (wholly under a picture drawn later)
    and, with skip_in_images, ones lying inside a placed picture's frame are left out."""
    out = []
    W = info['W']
    for d in info['drawings']:
        r = d['rect']
        box = (r.x0, r.y0, r.x1, r.y1)
        seq = d.get('seqno', 0)
        fill, stroke = d.get('fill'), d.get('color')
        parts = []
        if fill is not None:
            parts.append(('fill', fill))
        if stroke is not None and not (fill is not None and base._hex(fill) == base._hex(stroke)):
            parts.append(('stroke', stroke))          # a stroke in the fill's own colour is the shape's edge, not a line
        for which, c in parts:
            h = base._hex(c)
            if not base._near_hex(h, hexes, TOL_PDF):
                continue
            if any(i > seq and _within(box, ib, 0.5) for i, ib in info['images']):
                continue
            if skip_in_images and any(_within(box, ib, 1.0) for _, ib in info['images']):
                continue
            kind, thick, length = _kind(d, which)
            out.append(dict(kind=kind, thick=thick, length=round(length, 1), box=tuple(round(v, 1) for v in box), colour=h,
                            horizontal=r.width >= r.height, full_width=r.width >= 0.95 * W and r.width >= r.height,
                            seq=seq, fill=which == 'fill'))
    return out


def _mark_charts(uses, info):
    """Chart marks: three or more filled shapes in one colour, each no more than 3% of the page, standing on a
    shared baseline (bars) or starting from a shared left edge (horizontal bars), within 1.5 pt."""
    cand = [u for u in uses if u['kind'] == 'area' and u['fill'] and _area(u['box']) <= 0.03 * info['W'] * info['H']]
    for key in (3, 0):                                   # bottom edge, then left edge
        groups = {}
        for u in cand:
            groups.setdefault((u['colour'], round(u['box'][key] / 1.5)), []).append(u)
        for g in groups.values():
            if len(g) >= 3:
                for u in g:
                    u['kind'] = 'chart'


def op_pdf_colour_use(path, a):
    """Where colours appear in a PDF, from its drawings in drawing order (photographs' own pixels are never read).
    mode "only": every use is one of the allowed kinds (rule, keyline, chart; see _kind and _mark_charts), with
    full_width every rule runs the page width, with count that many distinct rules per page; and no type is set in
    the colours. mode "thickness": every full-width rule in the colours is that many pt thick (within 0.15).
    mode "none_of": no use is one of the forbidden kinds."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    pages = _pdf_pages(str(path))
    if any(_raster_page(p) for p in pages):
        return PERSON, {'reason': 'a page is mostly a placed picture; its shapes cannot be read as vectors'}
    hexes, mode = a['hexes'], a.get('mode', 'only')
    if mode == 'only' and not a.get('type_ok'):
        text = [sp['text'] for sp in r2._pdf_spans(str(path)) if base._near_hex(sp['color'], hexes, TOL_PDF)]
        if text:
            return 'fail', {'type_in_colour': text[:3]}
    allow = set(a.get('allow', []))
    bad, unsure, seen = [], [], 0
    for n, info in enumerate(pages):
        uses = _uses(info, hexes, a.get('skip_in_images', True))
        if 'chart' in allow:
            _mark_charts(uses, info)
        seen += len(uses)
        rules = [u for u in uses if u['kind'] == 'rule' and u['full_width']]
        if mode == 'only':
            for u in uses:
                if u['kind'] == 'rule' and a.get('full_width') and not u['full_width']:
                    bad.append(dict(page=n + 1, kind='rule not running the page width', box=u['box']))
                elif u['kind'] not in allow:
                    (unsure if u['kind'] == 'frame' else bad).append(dict(page=n + 1, kind=u['kind'], box=u['box'], colour=u['colour']))
            if a.get('count') is not None:
                ys = []
                for u in sorted(rules, key=lambda u: u['box'][1]):
                    y = (u['box'][1] + u['box'][3]) / 2
                    if not ys or y - ys[-1] > 1.5:
                        ys.append(y)
                if len(ys) != a['count']:
                    bad.append(dict(page=n + 1, full_width_rules=len(ys), at_pt=[round(y, 1) for y in ys]))
        elif mode == 'thickness':
            if not rules:
                unsure.append(dict(page=n + 1, reason='no full-width rule in that colour'))
            for u in rules:
                if abs(u['thick'] - a['thickness']) > 0.15:
                    bad.append(dict(page=n + 1, thickness_pt=u['thick'], at_pt=u['box'][1]))
        elif mode == 'none_of':
            for u in uses:
                if u['kind'] in a['forbid']:
                    bad.append(dict(page=n + 1, kind=u['kind'], colour=u['colour'], box=u['box']))
    if bad:
        return 'fail', {'not_allowed': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'a use of the colour that needs a look', 'items': unsure[:4]}
    return 'pass', {'uses': seen}


def _baseline(key, line):
    """The baseline of a PDF line (the first span's origin), in pt."""
    for sp in r2._pdf_spans(key):
        if sp['page'] == line.page and base._overlap(sp['bbox'], line.bbox) > 0.5:
            return sp['bbox'][3] - 0.21 * sp['size'], sp['size']        # descender room below the baseline
    return line.bbox[3] - 0.21 * line.size, line.size


@functools.lru_cache(maxsize=16)
def _pdf_origins(key: str):
    """Every span's baseline (its origin's y) and size, keyed by page and rounded box."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip():
                        out.append((page.number, tuple(s['bbox']), s['origin'][1], s['size']))
    return out


def op_pdf_rule_at_text(path, a):
    """A rule in the colours running the page width sits on the named text (where "on": the rule lies between a
    quarter of the type size above its baseline and three quarters of it below, under the text's width) or directly
    above it (where "above": no more than three line heights above the text's top, no other text between).
    The text may run over several lines."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    hits = [l for l in layer.lines if contains(l.text, a['text'], False)] or base._span(layer, a['text'], max_lines=12)
    if not hits:
        return PERSON, {'reason': f'text not found: {a["text"][:40]}'}
    page = hits[0].page
    info = _pdf_pages(key)[page]
    if _raster_page(info):
        return PERSON, {'reason': 'the page is mostly a placed picture'}
    rules = [u for u in _uses(info, a['hexes'], skip_in_images=False) if u['kind'] == 'rule' and u['full_width']]
    others = [l for l in layer.lines if l.page == page and l not in hits]
    if a['where'] == 'on':
        last = max(hits, key=lambda l: l.bbox[3])
        spans = [o for o in _pdf_origins(key) if o[0] == page and base._overlap(o[1], last.bbox) > 0.5]
        base_y = max(o[2] for o in spans) if spans else last.bbox[3] - 0.21 * last.size
        size = max(o[3] for o in spans) if spans else last.size
        near = [u for u in rules if base_y - 0.25 * size <= (u['box'][1] + u['box'][3]) / 2 <= base_y + 0.75 * size]
        ev = {'baseline_pt': round(base_y, 1), 'rules_at_pt': [round((u['box'][1] + u['box'][3]) / 2, 1) for u in rules]}
    else:
        top = min(l.bbox[1] for l in hits)
        lh = max(l.bbox[3] - l.bbox[1] for l in hits)
        def clear(y0, y1):
            return not any(l.bbox[1] < y1 and l.bbox[3] > y0 and min(l.bbox[3], y1) - max(l.bbox[1], y0) > 1 for l in others)
        near = [u for u in rules if -0.4 * lh <= top - u['box'][3] <= max(3 * lh, 12) and clear(u['box'][3], top)]
        ev = {'text_top_pt': round(top, 1), 'rules_at_pt': [round(u['box'][1], 1) for u in rules]}
    if near:
        return 'pass', ev
    if not rules and any((b[2] - b[0]) >= 0.95 * info['W'] for _, b in info['images']):
        return PERSON, dict(ev, reason='no vector rule; a picture spans the page width and could carry it')
    return 'fail', ev


def _glyph_paths(info, outside=()):
    """Filled curved paths the size of letters outside pictures: lettering converted to outlines."""
    n = 0
    for d in info['drawings']:
        r = d['rect']
        box = (r.x0, r.y0, r.x1, r.y1)
        if d.get('fill') is None or r.height > 80 or r.height < 2:
            continue
        if any(_within(box, ib, 1.0) for _, ib in info['images']) or any(_within(box, ob, 1.0) for ob in outside):
            continue
        if any(it[0] == 'c' for it in d.get('items') or []):
            n += 1
    return n


def op_pdf_text_colour(path, a):
    """PDF type colour: every span of the selected text is one of the colours. texts: each named text, which may run
    over several lines (only the spans that belong to it count); patterns; all_text (+ except, except_patterns).
    Lettering drawn as outlines cannot be read as type, so a page carrying eight or more letter-like curved paths
    goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    if not layer.readable:
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    pages = _pdf_pages(key)
    if any(_glyph_paths(p) >= 8 for p in pages):
        return PERSON, {'reason': 'letter-like outlines on the page: some type may be drawn as shapes'}
    picks = []
    for t in a.get('texts', []):
        hits = [l for l in layer.lines if contains(l.text, t, False)] or base._span(layer, t, max_lines=12)
        if not hits:
            if a.get('optional'):
                continue
            return PERSON, {'reason': f'text not found: {t[:40]}'}
        picks += [(l, t) for l in hits]
    for p in a.get('patterns', []):
        picks += [(l, None) for l in layer.lines if r2._rxs(p, l.text)]
    if a.get('all_text'):
        picks += [(l, None) for l in layer.lines if not any(contains(l.text, e, False) for e in a.get('except', []))
                  and not any(r2._rxs(p, l.text) for p in a.get('except_patterns', []))]
    if not picks:
        return ('pass', {'reason': 'no such text'}) if a.get('optional') else (PERSON, {'reason': 'nothing selected'})
    bad, n = [], 0
    for l, t in picks:
        spans = [s for s in l.fonts if s[0].strip()]
        if t:
            own = [s for s in spans if canon(s[0], False).strip() in canon(t, False)]
            spans = own or spans
        for s_text, font, size, colour in spans:
            n += 1
            if not base._near_hex(colour, a['colors'], TOL_PDF):
                bad.append((s_text[:30], colour))
    return ('fail', {'not_matching': bad[:8]}) if bad else ('pass', {'spans': n})


def _blend_modes(key: str) -> bool:
    """The document sets a blend mode other than Normal anywhere (multiply, screen, overlay...)."""
    import pymupdf
    doc = pymupdf.open(key)
    for x in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(x, compressed=True)
        except Exception:
            continue
        for m in re.finditer(r'/BM\s*/(\w+)', obj):
            if m.group(1) not in ('Normal', 'Compatible'):
                return True
    return False


def op_pdf_photo_overlay(path, a):
    """No scrim, gradient or overlay over a photograph, read in drawing order: for every placed picture of 1% of the
    page or more, nothing semi-transparent and no gradient is drawn after it over 2% or more of it (a fail); an
    opaque shape or another picture over a fifth of it or more, or a blend mode on a shape over it, goes to a
    person. No placed photograph: nothing to overlay (a pass)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    pages = _pdf_pages(key)
    blend = _blend_modes(key)
    photos, bad, unsure = 0, [], []
    for n, info in enumerate(pages):
        if _raster_page(info):
            return PERSON, {'reason': 'the page is mostly a placed picture: an overlay inside it cannot be read', 'page': n + 1}
        for i, ib in info['images']:
            area = _area(ib)
            if area < 0.01 * info['W'] * info['H']:
                continue
            photos += 1
            for d in info['drawings']:
                if d.get('seqno', 0) <= i:
                    continue
                r = d['rect']
                ov = _inter((r.x0, r.y0, r.x1, r.y1), ib)
                if ov < 0.02 * area:
                    continue
                fo, so = d.get('fill_opacity'), d.get('stroke_opacity')
                if (d.get('fill') is not None and fo is not None and fo < 0.999) or (d.get('color') is not None and so is not None and so < 0.999):
                    bad.append(dict(page=n + 1, over_pct=round(100 * ov / area, 1), opacity=fo if d.get('fill') is not None else so))
                elif blend:
                    unsure.append(dict(page=n + 1, reason='a shape over the photograph, and the file uses blend modes'))
                elif d.get('fill') is not None and ov >= 0.2 * area:
                    unsure.append(dict(page=n + 1, reason='an opaque shape covers a fifth of the photograph or more'))
            for j, sb in info['shades']:
                if j > i and _inter(sb, ib) >= 0.02 * area:
                    bad.append(dict(page=n + 1, gradient_over_pct=round(100 * _inter(sb, ib) / area, 1)))
            for j, ob in info['images']:
                if j > i and _inter(ob, ib) >= 0.2 * area:
                    unsure.append(dict(page=n + 1, reason='another picture is laid over the photograph'))
    if bad:
        return 'fail', {'overlays': bad[:4]}
    if unsure:
        return PERSON, {'reason': 'something is drawn over a photograph', 'items': unsure[:3]}
    return 'pass', {'photographs': photos} if photos else {'reason': 'no photograph placed'}


def op_pdf_area_share(path, a):
    """The colours together cover no more than max_pct of the designed area (the page less its placed pictures), read
    from the page rendered at 200 dpi. Edge pixels blend into their neighbours and go uncounted, so the reading is a
    floor: above the limit fails; at or under 60% of it passes; in between goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    worst = 0.0
    for n, info in enumerate(_pdf_pages(key)):
        if _raster_page(info):
            return PERSON, {'reason': 'the page is mostly a placed picture', 'page': n + 1}
        rgb = np.asarray(base.render_pdf(path, n, 200)).astype(np.int16)
        keep = np.ones(rgb.shape[:2], bool)
        k = rgb.shape[1] / info['W']
        for _, (x0, y0, x1, y1) in info['images']:
            keep[max(0, int(y0 * k)):max(0, int(np.ceil(y1 * k))), max(0, int(x0 * k)):max(0, int(np.ceil(x1 * k)))] = False
        if keep.sum() < 0.05 * keep.size:
            return PERSON, {'reason': 'almost all of the page is photograph', 'page': n + 1}
        hit = r3._near_mask(rgb, a['hexes'], 3) & keep
        worst = max(worst, 100 * hit.sum() / keep.sum())
    ev = {'share_pct': round(worst, 2), 'limit_pct': a['max_pct']}
    if worst > a['max_pct']:
        return 'fail', ev
    if worst <= 0.6 * a['max_pct']:
        return 'pass', ev
    return PERSON, dict(ev, reason='close to the limit')


# ================================================================ grounds and panels (PDF and images)


def _regions(rgb, keep, tol_flat, min_share=0.01, min_side=0.03):
    """Grounds and panels: flat areas of one colour covering min_share of the image or more, both sides at least
    min_side of its short side, inside keep. Returns [(hex, share, box)] largest first, and the share of the kept
    area that is smooth but not one colour (a gradient)."""
    import cv2
    h, w = rgb.shape[:2]
    flat = r3._flat(rgb, tol_flat) & keep
    q = rgb // 4
    code = (q[..., 0].astype(np.int32) << 12) | (q[..., 1].astype(np.int32) << 6) | q[..., 2].astype(np.int32)
    values, counts = np.unique(code[flat], return_counts=True)
    regions, covered = [], np.zeros((h, w), bool)
    for v, c in sorted(zip(values, counts), key=lambda t: -t[1])[:16]:
        if c < min_share * h * w:
            break
        m = flat & (np.abs(q.astype(np.int32) - np.array([(v >> 12) & 63, (v >> 6) & 63, v & 63])).max(axis=2) <= 1)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < min_share * h * w or min(bw, bh) < min_side * min(h, w):
                continue
            comp = (labels == i) & flat
            if not comp.any() or (covered & comp).sum() > 0.5 * comp.sum():
                continue
            covered |= labels == i
            regions.append((r3._to_hex(np.median(rgb[comp], axis=0)), round(float(area) / (h * w), 4), (int(x), int(y), int(x + bw), int(y + bh))))
    smooth = r3._flat(rgb, 3) & keep & ~covered
    n, labels, stats, _ = cv2.connectedComponentsWithStats(smooth.astype(np.uint8), connectivity=8)
    gradient = 0.0
    for i in range(1, n):
        if stats[i][4] >= min_share * h * w:
            px = rgb[labels == i]
            if np.ptp(px, axis=0).max() > 24:
                gradient = max(gradient, stats[i][4] / (h * w))
    regions.sort(key=lambda r: -r[1])
    return regions, gradient


def _pdf_keep(key, n, info, scale):
    """Pixels of a rendered PDF page that are neither a placed picture nor type."""
    import pymupdf
    page = pymupdf.open(key)[n]
    h, w = int(round(info['H'] * scale)), int(round(info['W'] * scale))
    keep = np.ones((h, w), bool)
    for _, (x0, y0, x1, y1) in info['images']:
        keep[max(0, int(y0 * scale) - 1):max(0, int(np.ceil(y1 * scale)) + 1), max(0, int(x0 * scale) - 1):max(0, int(np.ceil(x1 * scale)) + 1)] = False
    for _, (x0, y0, x1, y1) in info['texts']:
        keep[max(0, int(y0 * scale) - 2):max(0, int(np.ceil(y1 * scale)) + 2), max(0, int(x0 * scale) - 2):max(0, int(np.ceil(x1 * scale)) + 2)] = False
    return keep


def op_grounds(path, a):
    """Every ground and panel (a flat area of one colour covering 1% of the page or image or more, both sides at
    least 3% of its short side, photographs and type left out) is one of the colours; main: the largest of them is
    the first colour; forbid: none of them is one of these colours. PDFs are rendered with their placed pictures and
    type spans left out; images leave out photographs (see _photos) and the boxes of lines OCR reads. A large smooth
    area that is not one colour (a gradient ground) goes to a person."""
    pdf = path.suffix.lower() == '.pdf'
    tol = 5 if pdf else r3._tol(path, a)
    found, bad, unsure = [], [], []
    frames = _frames_of(path)
    pages = range(len(_pdf_pages(str(path)))) if pdf else frames
    for n in pages:
        if pdf:
            info = _pdf_pages(str(path))[n]
            if _raster_page(info):
                return PERSON, {'reason': 'the page is mostly a placed picture', 'page': n + 1}
            scale = 50 / 72
            rgb = np.asarray(base.render_pdf(path, n, 50)).astype(np.int16)
            keep = _pdf_keep(str(path), n, info, scale)[:rgb.shape[0], :rgb.shape[1]]
            if keep.shape != rgb.shape[:2]:
                keep = np.pad(keep, ((0, rgb.shape[0] - keep.shape[0]), (0, rgb.shape[1] - keep.shape[1])))
            tol_flat = 2
        else:
            rgb, alpha = _rgba(path, n)
            if a.get('capture'):
                keep = _keep_capture(path, a, rgb, alpha)
                if keep is None:
                    return PERSON, {'reason': 'the capture frame the design is built on was not matched'}
                keep &= ~_text_boxes(path, n)
            else:
                keep = ~_photos(path, a, n) & ~_text_boxes(path, n)
                if alpha is not None:
                    keep &= alpha >= OPAQUE
            tol_flat = 2 if not r3._lossy(path) else 6
        regions, gradient = _regions(rgb, keep, tol_flat)
        if gradient >= 0.01:
            unsure.append({'frame_or_page': n if not pdf else n + 1, 'reason': 'a smooth area that is not one colour (a gradient?)'})
        for hx, share, box in regions:
            found.append(hx)
            if a.get('main_only'):
                continue
            if a.get('forbid'):
                if _dist(r3._hex_rgb(hx), a['forbid']) <= tol + 3:
                    bad.append({'ground': hx, 'share': share})
                continue
            v = _verdict(_dist(r3._hex_rgb(hx), a['hexes']), tol)
            if v == 'far':
                bad.append({'ground': hx, 'share': share})
            elif v == 'near':
                unsure.append({'ground': hx, 'share': share})
        if a.get('main') and regions:
            v = _verdict(_dist(r3._hex_rgb(regions[0][0]), a['hexes'][:1]), tol)
            if v != 'ok':
                (bad if v == 'far' else unsure).append({'main_ground': regions[0][0]})
    if bad:
        return 'fail', {'grounds': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'a ground or panel colour needs a look', 'items': unsure[:4]}
    if not found and not a.get('forbid'):
        return PERSON, {'reason': 'no ground or panel found'}
    return 'pass', {'grounds': sorted(set(found))}


# ================================================================ images: frames, alpha, photographs, type boxes

VIDEO_FPS = 4.0           # films are read at 4 frames a second; a frame equal to the one before it is held still


def _video(key: str):
    return base.video_frames(key, VIDEO_FPS)


def _frames_of(path: Path, which='held'):
    """Frames to read: -1 for an image, PDF page 1 or SVG; for a film, indexes into its frames at 4 a second:
    "held" (equal to the frame before, mean difference under 1.5 levels: still for a quarter second or more),
    "last" (the last held frame, the end card), or "all"."""
    if path.suffix.lower() != '.mp4':
        return [-1]
    frames = _video(str(path))
    if which == 'all':
        return list(range(len(frames)))
    held = [i for i in range(1, len(frames))
            if np.abs(np.asarray(frames[i], np.int16) - np.asarray(frames[i - 1], np.int16)).mean() < 1.5]
    if which == 'last':
        return held[-1:] or [len(frames) - 1]
    return held or [len(frames) - 1]


def _frame_rgb(path: Path, f=-1):
    if path.suffix.lower() == '.mp4':
        return np.asarray(_video(str(path))[f]).astype(np.int16)
    return r3._pixels(str(path), f)



@functools.lru_cache(maxsize=24)
def _rgba_cached(key: str, frame: int):
    path = Path(key)
    if path.suffix.lower() == '.png':
        im = Image.open(path)
        if im.mode in ('RGBA', 'LA', 'P') and 'A' in im.convert('RGBA').getbands():
            rgba = np.asarray(im.convert('RGBA'))
            alpha = rgba[..., 3]
            if (alpha < 255).any():
                return r3._pixels(key, frame), alpha
    return _frame_rgb(path, frame), None


def _rgba(path: Path, frame=-1):
    """RGB (transparent parts shown on white) and the alpha channel where the image has transparent pixels."""
    return _rgba_cached(str(path), frame)


def _two_colour_blocks(rgb, block=16):
    """Photographs in a two-colour treatment, which the texture test misses: blocks with many tones that lie along
    one colour line with half or more of them mid-way between its ends (anti-aliased type keeps most of its pixels
    at the two ends; a flat panel or slow gradient has few tones in a block)."""
    import cv2
    h, w = rgb.shape[:2]
    by, bx = h // block, w // block
    out = np.zeros((by, bx), bool)
    sub = rgb[:by * block, :bx * block].reshape(by, block, bx, block, 3).transpose(0, 2, 1, 3, 4).reshape(by, bx, -1, 3).astype(float)
    q = (rgb[:by * block, :bx * block] >> 3).astype(np.int32)
    code = ((q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]).reshape(by, block, bx, block).transpose(0, 2, 1, 3).reshape(by, bx, -1)
    for y in range(by):
        for x in range(bx):
            if len(np.unique(code[y, x])) < 16:
                continue
            c = sub[y, x] - sub[y, x].mean(axis=0)
            u, s, vt = np.linalg.svd(c, full_matrices=False)
            t = c @ vt[0]
            lo, hi = np.percentile(t, 2), np.percentile(t, 98)
            if hi - lo < 40:
                continue
            tt = (t - lo) / (hi - lo)
            if ((tt > 0.2) & (tt < 0.8)).mean() >= 0.45:
                out[y, x] = True
    m = np.kron(out, np.ones((block, block), bool))
    m = np.pad(m, ((0, h - m.shape[0]), (0, w - m.shape[1])))
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((33, 33), np.uint8)) > 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    keep = np.zeros((h, w), bool)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area >= 0.01 * h * w:
            keep[max(0, y - 3):y + bh + 3, max(0, x - 3):x + bw + 3] = True
    return keep


@functools.lru_cache(maxsize=48)
def _photos_cached(key: str, photos: tuple, dirs: tuple, frame: int):
    import cv2
    path = Path(key)
    if path.suffix.lower() != '.mp4':
        a = {'photos': list(photos), '_asset_dirs': list(dirs)}
        return r3._photo_mask(path, a, frame) | _two_colour_blocks(r3._pixels(key, frame))
    # a film frame: textured areas, two-colour photo treatments, and each supplied picture found on this frame
    rgb = _frame_rgb(path, frame)
    h, w = rgb.shape[:2]
    t = r3._textured(rgb)
    t = np.pad(t, ((0, h - t.shape[0]), (0, w - t.shape[1])))
    t = cv2.morphologyEx(t.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((33, 33), np.uint8)) > 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(t.astype(np.uint8), connectivity=8)
    mask = np.zeros((h, w), bool)
    for i in range(1, n):
        if stats[i][4] >= 0.01 * h * w:
            mask |= cv2.dilate((labels == i).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    mask |= _two_colour_blocks(rgb)
    gray = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    for name in photos:
        try:
            asset = base._load_gray(base.asset_path({'_asset_dirs': list(dirs)}, name))
        except FileNotFoundError:
            continue
        n_, corners, state = base.find_asset(gray, asset)
        if state != 'found':
            continue
        x0, y0 = max(0, int(corners[:, 0].min()) - 3), max(0, int(corners[:, 1].min()) - 3)
        mask[y0:int(corners[:, 1].max()) + 4, x0:int(corners[:, 0].max()) + 4] = True
    return mask


@functools.lru_cache(maxsize=24)
def _asset_only_cached(key: str, photos: tuple, dirs: tuple):
    path = Path(key)
    rgb = r3._pixels(key)
    m = np.zeros(rgb.shape[:2], bool)
    for name in photos:
        try:
            page, box, state = r2._asset_box(path, {'_asset_dirs': list(dirs)}, name, 0)
        except FileNotFoundError:
            continue
        if box is not None:
            x0, y0, x1, y1 = (int(round(v)) for v in box)
            m[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = True
    return m


def _keep_capture(path: Path, a, rgb, alpha):
    """Designed pixels of a thumbnail built on a capture frame: everything but the matched capture (pixels within 40
    levels of the source frame after a 9 px blur) and the supplied cut-outs found. None when the frame was not
    matched."""
    cap = _capture_match(str(path), a['capture'], tuple(a.get('_asset_dirs') or []))
    if cap is None:
        return None
    keep = ~cap['loose'] & ~_asset_only_cached(str(path), tuple(a.get('photos', [])), tuple(a.get('_asset_dirs') or []))
    if alpha is not None:
        keep &= alpha >= OPAQUE
    return keep


def _photos(path: Path, a, frame=-1):
    """Photographs to leave out of a raster check: textured areas, the supplied photos and cut-outs where found
    (setting photos), and photographs in a two-colour treatment."""
    return _photos_cached(str(path), tuple(a.get('photos', [])), tuple(a.get('_asset_dirs') or []), frame)


@functools.lru_cache(maxsize=48)
def _ocr(key: str, frame: int):
    """OCR of an image, an SVG's render or one video frame (never an SVG's live text, which has no position)."""
    path = Path(key)
    if path.suffix.lower() == '.png' or path.suffix.lower() in ('.jpg', '.jpeg'):
        return base.ocr_layer_cached(key)
    return base.ocr_image(Image.fromarray(_frame_rgb(path, frame).astype(np.uint8)))


def _text_boxes(path: Path, frame=-1, pad=0.25):
    """Boxes of every line OCR reads (any confidence), padded: type is never a ground or panel."""
    rgb = _frame_rgb(path, frame)
    m = np.zeros(rgb.shape[:2], bool)
    for l in _ocr(str(path), frame).lines:
        x0, y0, x1, y1 = l.bbox
        p = pad * (y1 - y0)
        m[max(0, int(y0 - p)):int(y1 + p) + 1, max(0, int(x0 - p)):int(x1 + p) + 1] = True
    return m


# ================================================================ images: palette, share, colour presence


def op_raster_palette(path, a):
    """Every flat colour of the designed parts of an image, SVG render or held video frame is one of the colours.
    Left out: photographs (see _photos), transparent pixels and anti-aliased edges (only pixels whose neighbours share
    their colour count), and with capture the capture frame the design is laid over. An odd colour must cover a real
    area (30 flat pixels in one piece): 30 or more from every colour and not a blend of two of them fails; a blend of
    two colours (anti-aliasing, a photo treatment or a tint) or a near miss goes to a person. transparent_only: an
    image with no transparent pixels goes to a person (its ground is not part of the artwork)."""
    tol = r3._tol(path, a)
    bad, unsure = {}, {}
    for f in _frames_of(path):
        rgb, alpha = _rgba(path, f)
        if a.get('transparent_only') and alpha is None:
            return PERSON, {'reason': 'the proof has no transparent surround; its ground is for a person to judge'}
        if a.get('capture'):
            keep = _keep_capture(path, a, rgb, alpha)
            if keep is None:
                return PERSON, {'reason': 'the capture frame the design is built on was not matched'}
        else:
            keep = ~_photos(path, a, f)
            if alpha is not None:
                keep &= alpha >= OPAQUE
        if path.suffix.lower() == '.mp4' and _footage(rgb, keep):
            return PERSON, {'reason': 'a held frame shows footage, which code cannot tell apart from graphics', 'frame': f}
        flat = r3._flat(rgb, 2 if not r3._lossy(path) else 6) & keep
        if flat.sum() < 200:
            return PERSON, {'reason': 'almost no flat designed area found'}
        off = flat & ~r3._near_mask(rgb, a['hexes'], tol)
        for comp, st in r3._components(off):
            c = np.median(rgb[comp], axis=0)
            hx = r3._to_hex(c)
            d = _dist(c, a['hexes'])
            if d >= FAR and _blend_residual(c, a['hexes']) > 8:
                bad[hx] = bad.get(hx, 0) + int(st[4])
            else:
                unsure[hx] = unsure.get(hx, 0) + int(st[4])
    if bad:
        return 'fail', {'outside_palette': [f'{c} ({n} px)' for c, n in sorted(bad.items(), key=lambda kv: -kv[1])[:5]]}
    if unsure:
        return PERSON, {'reason': 'colours near the palette or blends of two palette colours', 'colours': sorted(unsure, key=lambda c: -unsure[c])[:5]}
    return 'pass', {'palette': a['hexes']}


def _footage(rgb, keep):
    """A held frame shows footage: textured areas cover a twentieth of the kept frame or more."""
    t = r3._textured(rgb)
    t = np.pad(t, ((0, rgb.shape[0] - t.shape[0]), (0, rgb.shape[1] - t.shape[1])))
    return (t & keep).sum() >= 0.05 * max(1, keep.sum())


def op_raster_share(path, a):
    """The colours cover no more than max_pct of the designed area (image or held frame less photographs, transparent
    pixels, the capture frame with capture, and with except_texts the boxes of those text lines in the numerator
    only). Over 1.15 times the limit fails; at or under 0.9 times passes; between goes to a person."""
    tol = r3._tol(path, a)
    worst = 0.0
    for f in _frames_of(path):
        rgb, alpha = _rgba(path, f)
        if a.get('capture'):
            keep = _keep_capture(path, a, rgb, alpha)
            if keep is None:
                return PERSON, {'reason': 'the capture frame the design is built on was not matched'}
        else:
            keep = ~_photos(path, a, f)
            if alpha is not None:
                keep &= alpha >= OPAQUE
        if path.suffix.lower() == '.mp4' and _footage(rgb, keep):
            return PERSON, {'reason': 'a held frame shows footage', 'frame': f}
        area = keep.sum() if not a.get('whole_frame') else keep.size
        if area < 0.02 * keep.size:
            return PERSON, {'reason': 'almost no designed area'}
        hit = r3._near_mask(rgb, a['hexes'], tol) & keep
        if a.get('except_texts') or a.get('except_words'):
            for l in _ocr(str(path), f).lines:
                if any(contains(l.text, t, False) for t in a.get('except_texts', [])) or (a.get('except_words') and _only_words(l.text, a['except_words'])):
                    x0, y0, x1, y1 = (int(round(v)) for v in l.bbox)
                    hit[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = False
        worst = max(worst, 100 * hit.sum() / area)
    ev = {'share_pct': round(worst, 2), 'limit_pct': a['max_pct']}
    if worst <= 0.9 * a['max_pct']:
        return 'pass', ev
    return ('fail' if worst > 1.15 * a['max_pct'] else PERSON), ev


def op_raster_present(path, a):
    """The colour appears in the designed parts (photographs, supplied cut-outs and, with capture, the capture frame
    left out) as a flat area of 30 pixels or more, on the image or any held frame."""
    tol = r3._tol(path, a)
    for f in _frames_of(path, 'all'):
        rgb, alpha = _rgba(path, f)
        if a.get('capture'):
            keep = _keep_capture(path, a, rgb, alpha)
            if keep is None:
                return PERSON, {'reason': 'the capture frame the design is built on was not matched'}
        else:
            keep = ~_photos(path, a, f)
            if alpha is not None:
                keep &= alpha >= OPAQUE
        hit = r3._flat(rgb, 2 if not r3._lossy(path) else 6) & keep & r3._near_mask(rgb, a['hexes'], tol)
        comps = r3._components(hit)
        if comps:
            return 'pass', {'pixels': int(sum(st[4] for _, st in comps)), 'frame': f}
    return 'fail', {'reason': 'not found in the designed parts', 'hexes': a['hexes']}


# ================================================================ images: colour of text lines and marks


def _only_words(text, words) -> bool:
    """The line is made only of these words (a title set over several lines, read line by line)."""
    own = [_norm_word(x) for x in text.split() if _norm_word(x)]
    allowed = {_norm_word(w) for w in words}
    return bool(own) and all(x in allowed for x in own)


def _select_lines(layer, a, rgb_shape=None, exclude=()):
    picks = []
    for l in layer.lines:
        if not base._real(l):
            continue
        if any(base._overlap(l.bbox, b) > 0.3 for b in exclude):
            continue
        t = canon(l.text)
        if any(contains(t, e, False) for e in a.get('except', [])) or any(r2._rxs(p, t) for p in a.get('except_patterns', [])):
            continue
        if a.get('except_words') and _only_words(l.text, a['except_words']):
            continue
        if a.get('texts') and any(contains(t, x, False) for x in a['texts']):
            picks.append(l)
        elif a.get('patterns') and any(r2._rxs(p, t) for p in a['patterns']):
            picks.append(l)
        elif a.get('all_text'):
            picks.append(l)
    if a.get('largest_only') and picks:
        top = max(l.size for l in picks)
        picks = [l for l in picks if l.size >= 0.92 * top]
    return picks


def _asset_boxes(path: Path, a, names, frame=-1):
    boxes = []
    for name in names or []:
        try:
            page, box, state = r2._asset_box(path, a, name, 0)
        except FileNotFoundError:
            continue
        if box is not None:
            boxes.append(box)
    return boxes


def op_raster_text_colour(path, a):
    """Ink and ground of text lines on an image, SVG render or held video frame, read by OCR: the ground is the
    commonest colour round the line's box, the ink the letter cores furthest from it. Selection: texts, patterns or
    all_text (+ except, except_patterns), largest_only; lines over a supplied mark (exclude_assets) are left out.
    grounds: only lines on these grounds count (a line whose ground is not one colour goes to a person); colors:
    allowed inks, primary: allowed inks for the largest line counted; ground_must: the line's ground must be one of
    these. Within tolerance passes; 30 or more off on a confident read fails, with fail_if (a pattern the line must
    match, e.g. lowercase letters) also required; anything else goes to a person. Nothing selected: a pass only
    where optional and OCR read every wording line confidently."""
    tol = r3._tol(path, a) + 3
    frames = _frames_of(path, 'last' if a.get('frame') == 'last' else 'held')
    checked, bad, unsure, confident = [], [], [], True
    exclude = _asset_boxes(path, a, a.get('exclude_assets'))
    cap = None
    if a.get('capture'):
        cap = _capture_match(str(path), a['capture'], tuple(a.get('_asset_dirs') or []))
        if cap is None:
            return PERSON, {'reason': 'the capture frame the design is built on was not matched'}
    for f in frames:
        rgb = _frame_rgb(path, f)
        layer = _ocr(str(path), f)
        lines = layer.lines
        if cap is not None:
            # lines read inside the capture frame (game text) are footage, not design
            lines = [l for l in lines if _capture_share(cap, l.bbox) < 0.8]
        wording = [l for l in lines if len(re.findall(r'[A-Za-z0-9]', l.text)) >= 3 or re.search(r'[\d$€£@]', l.text)]
        confident = confident and bool(wording) and all(l.conf >= OCR_GOOD_CONF for l in wording)
        for l in _select_lines(base.Layer(lines, layer.source), a, exclude=exclude):
            got = r3._ink_and_ground(rgb, l.bbox)
            if got is None:
                unsure.append({'line': l.text, 'reason': 'ink not measurable'})
                continue
            ink, ground, share = got
            g_hex, i_hex = r3._to_hex(ground), r3._to_hex(ink)
            if a.get('ground_must'):
                if share < 0.5:
                    unsure.append({'line': l.text, 'reason': 'ground not one colour'})
                    continue
                v = _verdict(_dist(ground, a['ground_must']), tol + 3)
                checked.append(l)
                if v != 'ok':
                    (bad if v == 'far' and l.conf >= OCR_GOOD_CONF else unsure).append({'line': l.text, 'ground': g_hex})
                continue
            if a.get('grounds'):
                if share < 0.5:
                    if _dist(ground, a['grounds']) <= tol + 3 or a.get('strict_grounds'):
                        unsure.append({'line': l.text, 'reason': 'ground not one colour'})
                    continue
                if _dist(ground, a['grounds']) > tol + 3:
                    continue
            checked.append(l)
            v = _verdict(_dist(ink, a['colors']), tol)
            if v == 'ok':
                continue
            sure = v == 'far' and l.conf >= OCR_GOOD_CONF and (not a.get('fail_if') or re.search(a['fail_if'], l.text))
            (bad if sure else unsure).append({'line': l.text, 'ink': i_hex, 'ground': g_hex})
        if a.get('primary') and checked:
            top = max(checked, key=lambda l: l.size)
            got = r3._ink_and_ground(rgb, top.bbox)
            if got is not None and _verdict(_dist(got[0], a['primary']), tol) != 'ok':
                (bad if _dist(got[0], a['primary']) >= FAR else unsure).append({'line': top.text, 'ink': r3._to_hex(got[0]), 'reason': 'the main line'})
    if bad:
        return 'fail', {'not_matching': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'some lines need a look', 'lines': unsure[:4]}
    if a.get('need_confident') and not confident:
        return PERSON, {'reason': 'not every line read clearly enough to rule out another'}
    if not checked:
        if a.get('optional', True) and confident:
            return 'pass', {'reason': 'no such text (the check applies only where it appears)'}
        return PERSON, {'reason': 'text not found' if not a.get('optional', True) else 'not every line read clearly enough to rule it out'}
    return 'pass', {'lines_checked': len(checked)}


def _capture_share(cap, bbox):
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    sub = cap['capture'][max(0, y0):y1 + 1, max(0, x0):x1 + 1]
    return float(sub.mean()) if sub.size else 0.0


def op_mark_on_ground(path, a):
    """A supplied mark found in an image sits on one of the grounds: the commonest colour of a band 3 to 10 pixels
    round the mark's box, when that colour covers 60% of the band or more."""
    page, box, state = r2._asset_box(path, a, a['asset'], 0)
    if box is None:
        return PERSON, {'reason': 'mark not found' if state == 'none' else 'possible mark, unclear'}
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    band = np.zeros((h, w), bool)
    band[max(0, y0 - 10):min(h, y1 + 10), max(0, x0 - 10):min(w, x1 + 10)] = True
    band[max(0, y0 - 3):min(h, y1 + 3), max(0, x0 - 3):min(w, x1 + 3)] = False
    px = rgb[band]
    if len(px) < 50:
        return PERSON, {'reason': 'mark at the image edge'}
    values, counts = np.unique(px // 4, axis=0, return_counts=True)
    mode = values[counts.argmax()] * 4 + 2
    near = px[np.abs(px - mode).max(axis=1) <= 8]
    share = len(near) / len(px)
    ground = np.median(near, axis=0)
    ev = {'ground': r3._to_hex(ground), 'share': round(share, 2)}
    if share < 0.6:
        return PERSON, dict(ev, reason='the ground round the mark is not one colour')
    v = _verdict(_dist(ground, a['grounds']), r3._tol(path, a) + 3)
    return ('pass' if v == 'ok' else 'fail' if v == 'far' else PERSON), ev


# ================================================================ text roles and type (PDF, SVG, OCR)


def _role_band(layer):
    """Body size and every line set between 0.85 and 1.3 times it (body and billing sizes), by the text roles of
    objective_ops_r3._roles. Returns (body_size, lines) or (None, [])."""
    body, roles = r3._roles(layer)
    if body is None:
        return None, []
    tol = 0.3 if layer.source == 'pdf' else 0.08 * body
    lines = [l for l in layer.lines if base._real(l) and l.size_ok and 0.85 * body - tol <= l.size < 1.3 * body]
    return body, lines


def _svg_lines(path: Path):
    """An SVG's live text as lines: runs of one <text> that share a baseline and a size form a line (text position
    flows run to run, as SVG places it: an absolute y resets it, a dy moves it). Returns
    [(text, baseline y, font size, family, x)] in user units, or [] when the type is drawn as outlines."""
    from xml.etree import ElementTree as ET
    root = ET.fromstring(path.read_text())
    out = []

    def num(v):
        m = re.match(r'\s*(-?[\d.]+)', v or '')
        return float(m.group(1)) if m else None

    def style(e, key, inherited):
        m = re.search(rf'{key}\s*:\s*([^;]+)', e.get('style') or '')
        return (m.group(1) if m else e.get(key) or inherited)

    def walk(e, size, fam, pos, rows):
        if e.get('y'):
            pos['y'] = num(e.get('y').split()[0])
        if e.get('x'):
            pos['x'] = num(e.get('x').split()[0])
        if e.get('dy'):
            pos['y'] = (pos['y'] or 0) + (num(e.get('dy').split()[0]) or 0)
        size = num(style(e, 'font-size', None)) or size
        fam = (style(e, 'font-family', fam) or '').strip('\'" ')
        own = (e.text or '').strip()
        if own:
            rows.append([own, pos['y'], size, fam, pos['x']])
        for c in e:
            walk(c, size, fam, pos, rows)
            if c.tail and c.tail.strip():
                rows.append([c.tail.strip(), pos['y'], size, fam, pos['x']])
        return rows

    for t in root.iter():
        if t.tag.split('}')[-1] != 'text':
            continue
        rows = walk(t, None, None, {'x': None, 'y': None}, [])
        lines = []
        for r in rows:
            same = [l for l in lines if l[1] is not None and r[1] is not None and abs(l[1] - r[1]) < 1e-6 and l[2] == r[2] and l[3] == r[3]]
            if same:
                same[0][0] += ' ' + r[0]
            else:
                lines.append(list(r))
        out += [tuple(l) for l in lines]
    return out


def op_line_chars(path, a):
    """No line of the selected text runs over max_chars characters (spaces included). scope "billing": the lines
    naming a support act (texts) and every line set at their size; scope "body": body lines by the text roles plus
    lines carrying the texts; scope "band": lines set between 0.85 and 1.3 times the body size (see _role_band);
    scope "all": every line. PDFs and
    SVG live text can fail; on images (OCR may join two columns into one line) a long line goes to a person."""
    if path.suffix.lower() == '.svg':
        rows = _svg_lines(path)
        if rows:
            long_ = [(t, len(canon(t))) for t, *_ in rows if len(canon(t)) > a['max_chars']]
            return ('fail', {'too_long': long_[:3]}) if long_ else ('pass', {'lines': len(rows), 'longest': max(len(canon(t)) for t, *_ in rows)})
        layer = _ocr(str(path), -1)
    elif path.suffix.lower() == '.pdf':
        layer = base.pdf_layer(str(path))
    else:
        layer = _ocr(str(path), -1)
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    if a.get('scope') == 'billing':
        # billing: the lines naming a support act, and every line set at their size (body copy shares it)
        own = [l for l in layer.lines if any(contains(l.text, t, False) for t in a.get('texts', []))]
        if not own:
            return PERSON, {'reason': 'no billing line found to set the size'}
        size = float(np.median([l.size for l in own]))
        tol = 0.3 if layer.source == 'pdf' else 0.08 * size
        lines = [l for l in layer.lines if abs(l.size - size) <= tol]
    elif a.get('scope') in ('band', 'body'):
        if a['scope'] == 'band':
            body, lines = _role_band(layer)
        else:
            body, roles = r3._roles(layer)
            lines = roles.get('body', [])
        if body is None:
            return PERSON, {'reason': 'no running text found to set the body size'}
        lines = lines + [l for l in layer.lines if any(contains(l.text, t, False) for t in a.get('texts', [])) and l not in lines]
    else:
        lines = [l for l in layer.lines if base._real(l)]
    if not lines:
        return ('pass', {'reason': 'no such lines'}) if layer.source == 'pdf' or layer.confident else (PERSON, {'reason': 'text not read clearly'})
    long_ = [(l.text, len(canon(l.text))) for l in lines if len(canon(l.text)) > a['max_chars']]
    if long_:
        return ('fail' if layer.source == 'pdf' else PERSON), {'too_long': long_[:3]}
    if layer.source != 'pdf' and not layer.confident:
        return PERSON, {'reason': 'text not read clearly enough to rule out a long line'}
    return 'pass', {'lines': len(lines), 'longest': max(len(canon(l.text)) for l in lines)}


def op_role_font(path, a):
    """PDF type family and weight of lines chosen by role: band (lines between 0.85 and 1.3 times the body size,
    see _role_band), texts (lines carrying these names; only the spans that belong to the name and a leading "with"
    count), chart (lines inside a chart: the box of three or more bars on a shared baseline, grown by 40 pt).
    except_patterns leaves lines out (date lines, door lines). Every span must be in the family and weight."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'type style is read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    if not layer.readable:
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    if any(_glyph_paths(p) >= 8 for p in _pdf_pages(key)):
        return PERSON, {'reason': 'letter-like outlines on the page: some type may be drawn as shapes'}
    picks = []
    if 'band' in a.get('roles', []) or 'body' in a.get('roles', []):
        if 'band' in a['roles']:
            body, lines = _role_band(layer)
        else:
            body, roles = r3._roles(layer)
            lines = roles.get('body', [])
        if body is None:
            return PERSON, {'reason': 'no running text found to set the body size'}
        picks += [(l, None) for l in lines]
    for t in a.get('texts', []):
        hits = [l for l in layer.lines if contains(l.text, t, False)]
        if not hits and not a.get('optional'):
            return PERSON, {'reason': f'text not found: {t}'}
        picks += [(l, t) for l in hits]
    if 'chart' in a.get('roles', []):
        for n, info in enumerate(_pdf_pages(key)):
            bars = []
            uses = [dict(kind='area', fill=True, box=(d['rect'].x0, d['rect'].y0, d['rect'].x1, d['rect'].y1), colour=base._hex(d['fill']))
                    for d in info['drawings'] if d.get('fill') is not None]
            _mark_charts(uses, info)
            bars = [u['box'] for u in uses if u['kind'] == 'chart']
            if bars:
                zone = (min(b[0] for b in bars) - 40, min(b[1] for b in bars) - 40, max(b[2] for b in bars) + 40, max(b[3] for b in bars) + 40)
                picks += [(l, None) for l in layer.lines if l.page == n and _within(l.bbox, zone, 0)]
    picks = [(l, t) for l, t in picks if not any(r2._rxs(p, l.text) for p in a.get('except_patterns', []))]
    if not picks:
        return ('pass', {'reason': 'none present'}) if a.get('optional') else (PERSON, {'reason': 'nothing selected'})
    fam = re.sub(r'[^a-z0-9]', '', a['family'].lower())
    wt = re.sub(r'[^a-z0-9]', '', a['weight'].lower())
    bad, n = [], 0
    seen = set()
    for l, t in picks:
        spans = [s for s in l.fonts if s[0].strip()]
        if t:
            spans = [s for s in spans if contains(t, s[0], False) or contains(s[0], t, False) or re.fullmatch(r'\s*with\s*', s[0], re.I)] or spans
        for s in spans:
            if (id(l), s) in seen:
                continue
            seen.add((id(l), s))
            n += 1
            f, w = base._font_parts(s[1])
            if f != fam or w != wt:
                bad.append((s[0][:30], s[1]))
    return ('fail', {'not_matching': bad[:8]}) if bad else ('pass', {'spans': n})


def op_tracking_vs_body(path, a):
    """Lines matching the pattern (door lines) are letterspaced more openly than the body text (running lines at the
    body size, see objective_ops_r3._roles), by their glyph positions in the PDF (median gap over size)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'letter spacing is read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    body, roles = r3._roles(layer)
    rows = r2._pdf_lines_chars(key)
    sel = [r for r in rows if r2._rxs(a['pattern'], r['text'])]
    if not sel:
        return ('pass', {'reason': 'none present'}) if a.get('optional') else (PERSON, {'reason': 'lines not found'})
    if body is None or not roles.get('body'):
        return PERSON, {'reason': 'no running text found to set the body size'}
    def match(l):
        return [r for r in rows if r['page'] == l.page and base._overlap(r['bbox'], l.bbox) > 0.5]
    body_rows = [r for l in roles['body'] for r in match(l) if not r2._rxs(a['pattern'], r['text'])]
    if not body_rows:
        return PERSON, {'reason': 'body lines not measured'}
    ref = float(np.median([r['tracking'] for r in body_rows]))
    bad = [{'line': r['text'], 'em': round(r['tracking'], 3)} for r in sel if not r['tracking'] > ref + 0.005]
    ev = {'body_em': round(ref, 3), 'lines': [round(r['tracking'], 3) for r in sel]}
    return ('fail', dict(ev, not_more_open=bad[:4])) if bad else ('pass', ev)


def op_svg_leading(path, a):
    """SVG live text: where text of a role runs over two or more lines (consecutive lines of one family and size,
    no more than 2.2 times the type size apart), their baselines are leading_mm apart (within 0.1 mm). Role by the brand's type scale (family and size range in pt). No such wrapped text: a pass. Type drawn
    as outlines (no live text) goes to a person."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    from xml.etree import ElementTree as ET
    root = ET.fromstring(path.read_text())
    mm = r2._doc_mm(root)
    vb = [float(v) for v in re.split(r'[\s,]+', (root.get('viewBox') or '').strip()) if v]
    if not mm or len(vb) != 4 or vb[2] <= 0:
        return PERSON, {'reason': 'document size or viewBox not in physical units'}
    unit = mm[0] / vb[2]                                       # mm per user unit
    rows = _svg_lines(path)
    if not rows:
        outlined = any(e.tag.split('}')[-1] == 'path' for e in root.iter())
        return PERSON, {'reason': 'no live text (type may be drawn as outlines)' if outlined else 'no text'}
    fam_rx = a['family']
    lo, hi = a['size_pt']
    pick = []
    for t, y, size, fam, x in rows:
        if y is None or size is None:
            continue
        pt = size * unit * 72 / 25.4
        if re.search(fam_rx, fam or '', re.I) and lo <= pt < hi:
            pick.append((y * unit, size, t))
    pick.sort()
    gaps = []
    for (y0, s0, t0), (y1, s1, t1) in zip(pick, pick[1:]):
        if abs(s0 - s1) < 1e-6 and 0 < y1 - y0 <= 2.2 * s0 * unit:
            gaps.append(round(y1 - y0, 3))
    if not gaps:
        return 'pass', {'reason': 'no wrapped text of that role'}
    off = [g for g in gaps if abs(g - a['leading_mm']) > 0.1]
    return ('fail', {'baseline_gaps_mm': off}) if off else ('pass', {'baseline_gaps_mm': gaps})


# ================================================================ PDF colour spaces (production sheets)


_TOKEN = re.compile(rb"""
    (?P<ws>\s+|%[^\r\n]*)
  | (?P<str>\()
  | (?P<dict><<|>>)
  | (?P<hex><[0-9A-Fa-f\s]*>)
  | (?P<arr>\[|\])
  | (?P<name>/[^\s/\[\]()<>{}%]*)
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))
  | (?P<op>[A-Za-z'"*][A-Za-z0-9'"*]*)
  | (?P<other>.)
""", re.X | re.S)


def _content_ops(data: bytes):
    """A PDF content stream as (operands, operator) pairs: numbers, names (with their slash), arrays as lists;
    strings, hex strings and dictionaries kept as placeholders; inline images skipped."""
    out, stack, i, n = [], [[]], 0, len(data)
    while i < n:
        m = _TOKEN.match(data, i)
        if not m:
            i += 1
            continue
        kind, tok = m.lastgroup, m.group()
        i = m.end()
        if kind == 'ws' or kind == 'other':
            continue
        if kind == 'str':
            depth, j = 1, i
            while j < n and depth:
                c = data[j:j + 1]
                if c == b'\\':
                    j += 2
                    continue
                depth += 1 if c == b'(' else -1 if c == b')' else 0
                j += 1
            i = j
            stack[-1].append('(string)')
        elif kind == 'hex':
            stack[-1].append('<hex>')
        elif kind == 'dict':
            if tok == b'<<':
                stack.append([])
            elif len(stack) > 1:
                stack.pop()
                stack[-1].append('<<dict>>')
        elif kind == 'arr':
            if tok == b'[':
                stack.append([])
            elif len(stack) > 1:
                arr = stack.pop()
                stack[-1].append(arr)
        elif kind == 'name':
            stack[-1].append(tok.decode('latin-1'))
        elif kind == 'num':
            stack[-1].append(float(tok))
        else:
            op = tok.decode('latin-1')
            if op == 'BI':
                j = data.find(b'EI', i)
                while j != -1 and not (data[j - 1:j].isspace() and (j + 2 >= n or data[j + 2:j + 3].isspace())):
                    j = data.find(b'EI', j + 2)
                i = n if j == -1 else j + 2
                stack = [[]]
                continue
            out.append((stack[0], op))
            stack = [[]]
    return out


def _obj_text(doc, value):
    """A PDF value given by PyMuPDF as (type, text), following an indirect reference to its object's text."""
    kind, text = value
    if kind == 'xref':
        return doc.xref_object(int(text.split()[0]), compressed=True)
    return text


def _res_entry(doc, holder: int, path: str):
    """The text of a resource entry (e.g. ColorSpace/CS0) of the object holding resources, or None."""
    kind, text = doc.xref_get_key(holder, path)
    if kind in ('null', None) or text in ('null', ''):
        return None
    return _obj_text(doc, (kind, text))


def _cs_kind_text(doc, text: str) -> str:
    """The kind of a colour space written as PDF text: rgb, cmyk, gray, spot:<name>, devicen:<names>, lab, pattern,
    indexed:<base> or other."""
    t = (text or '').strip()
    simple = {'/DeviceRGB': 'rgb', '/RGB': 'rgb', '/DeviceCMYK': 'cmyk', '/CMYK': 'cmyk', '/DeviceGray': 'gray', '/G': 'gray',
              '/Pattern': 'pattern', '/CalRGB': 'rgb', '/CalGray': 'gray', '/Lab': 'lab'}
    if t in simple:
        return simple[t]
    m = re.match(r'\[\s*/Separation\s*/([^\s/\[\]]+)', t)
    if m:
        return 'spot:' + m.group(1)
    m = re.match(r'\[\s*/DeviceN\s*\[([^\]]*)\]', t)
    if m:
        return 'devicen:' + ','.join(x.lstrip('/') for x in m.group(1).split())
    m = re.match(r'\[\s*/ICCBased\s+(\d+)\s+0\s+R', t)
    if m:
        k, v = doc.xref_get_key(int(m.group(1)), 'N')
        return {'1': 'gray', '3': 'rgb', '4': 'cmyk'}.get(v.strip(), 'other')
    m = re.match(r'\[\s*/(?:Indexed|I)\s*(/\w+|\[[^\]]*\]|\d+\s+0\s+R)', t)
    if m:
        base_ = m.group(1)
        if re.fullmatch(r'\d+\s+0\s+R', base_):
            base_ = doc.xref_object(int(base_.split()[0]), compressed=True)
        return 'indexed:' + _cs_kind_text(doc, base_)
    m = re.match(r'\[\s*/(CalRGB|CalGray|Lab|Pattern)', t)
    if m:
        return {'CalRGB': 'rgb', 'CalGray': 'gray', 'Lab': 'lab', 'Pattern': 'pattern'}[m.group(1)]
    return 'other'


def _cs_of(doc, holder, name: str) -> str:
    """The kind of a colour space operand (a device name, or a resource name of the holder's ColorSpace table)."""
    base_ = _cs_kind_text(doc, name)
    if base_ != 'other':
        return base_
    entry = _res_entry(doc, holder, f'Resources/ColorSpace/{name.lstrip("/")}') if holder else None
    return _cs_kind_text(doc, entry) if entry else 'other'


@functools.lru_cache(maxsize=8)
def _pdf_paint(key: str):
    """Every paint operation of every page, forms followed with their own resources: dicts with kind (path, text,
    image, shading), what (fill or stroke), colour space kind, colour values, and the optional-content layer names
    in force (marked content /OC). Images record their own colour space. Read with PyMuPDF's raw streams."""
    import pymupdf
    doc = pymupdf.open(key)
    out = []

    def ocg_name(holder, operand):
        if isinstance(operand, str) and operand.startswith('/') and holder:
            kind, text = doc.xref_get_key(holder, f'Resources/Properties/{operand.lstrip("/")}')
            if kind == 'xref':
                k2, v2 = doc.xref_get_key(int(text.split()[0]), 'Name')
                return v2.strip('()') if v2 else ''
        return ''

    def run(data: bytes, holder, depth, layers):
        if depth > 8:
            return
        state = {'fill_cs': 'gray', 'stroke_cs': 'gray', 'fill': (0.0,), 'stroke': (0.0,)}
        stack, mc = [], []
        for operands, op in _content_ops(data):
            if op == 'q':
                stack.append(dict(state))
            elif op == 'Q' and stack:
                state = stack.pop()
            elif op == 'BDC':
                mc.append(ocg_name(holder, operands[1]) if len(operands) > 1 and operands[0] == '/OC' else '')
            elif op == 'BMC':
                mc.append('')
            elif op == 'EMC' and mc:
                mc.pop()
            elif op in ('cs', 'CS') and operands:
                state['fill_cs' if op == 'cs' else 'stroke_cs'] = _cs_of(doc, holder, str(operands[0]))
            elif op in ('sc', 'scn', 'SC', 'SCN'):
                state['fill' if op in ('sc', 'scn') else 'stroke'] = tuple(v for v in operands if isinstance(v, float))
            elif op in ('rg', 'RG', 'k', 'K', 'g', 'G'):
                kind = {'rg': 'rgb', 'k': 'cmyk', 'g': 'gray'}[op.lower()]
                vals = tuple(v for v in operands if isinstance(v, float))
                if op.islower():
                    state['fill_cs'], state['fill'] = kind, vals
                else:
                    state['stroke_cs'], state['stroke'] = kind, vals
            else:
                names = tuple(n for n in list(layers) + mc if n)
                if op in ('f', 'F', 'f*', 'B', 'B*', 'b', 'b*'):
                    out.append(dict(kind='path', what='fill', cs=state['fill_cs'], values=state['fill'], layers=names))
                if op in ('S', 's', 'B', 'B*', 'b', 'b*'):
                    out.append(dict(kind='path', what='stroke', cs=state['stroke_cs'], values=state['stroke'], layers=names))
                if op in ('Tj', 'TJ', "'", '"'):
                    out.append(dict(kind='text', what='fill', cs=state['fill_cs'], values=state['fill'], layers=names))
                if op == 'sh':
                    out.append(dict(kind='shading', what='fill', cs='shading', values=(), layers=names))
                if op == 'Do' and operands and holder:
                    kind, text = doc.xref_get_key(holder, f'Resources/XObject/{str(operands[0]).lstrip("/")}')
                    if kind != 'xref':
                        continue
                    x = int(text.split()[0])
                    sub = doc.xref_get_key(x, 'Subtype')[1]
                    if sub == '/Form':
                        own = doc.xref_get_key(x, 'Resources')[0]
                        run(doc.xref_stream(x) or b'', x if own not in ('null', None) else holder, depth + 1, names)
                    elif sub == '/Image':
                        cs_kind, cs_text = doc.xref_get_key(x, 'ColorSpace')
                        if cs_kind in ('null', None):
                            k = 'mask' if doc.xref_get_key(x, 'ImageMask')[1] == 'true' else 'other'
                        else:
                            k = _cs_kind_text(doc, _obj_text(doc, (cs_kind, cs_text)))
                        out.append(dict(kind='image', what='fill', cs=k, values=(), layers=names))

    for page in doc:
        data = b''.join(doc.xref_stream(x) or b'' for x in page.get_contents())
        run(data, page.xref, 0, ())
    return out


CUT_RX = re.compile(r'cut\s*contour|cut[-_ ]?line|die[-_ ]?cut|kiss[-_ ]?cut|\bcut\b', re.I)


def _is_cut(op) -> bool:
    return any(CUT_RX.search(n) for n in op['layers']) or (op['cs'].startswith('spot:') and CUT_RX.search(op['cs']))


def op_pdf_cut_spot(path, a):
    """The cut paths are painted in a spot colour (a Separation) named CutContour. Cut paths: paths on a layer named
    as a cut line (CutContour, cut line, die cut, kiss cut) or painted in a spot named so. All of them in that spot
    passes; any in another colour space fails; none found goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    ops = [o for o in _pdf_paint(str(path)) if o['kind'] == 'path' and _is_cut(o)]
    if not ops:
        return PERSON, {'reason': 'no cut paths found (no cut layer and no cut spot colour)'}
    spot = [o for o in ops if re.fullmatch(r'spot:cut\s*contour', o['cs'].replace('#20', ' '), re.I)]
    other = sorted({o['cs'] for o in ops if o not in spot})
    if other:
        return 'fail', {'cut_paths_in': other, 'in_spot': len(spot)}
    return 'pass', {'cut_paths': len(spot)}


def op_pdf_process_only(path, a):
    """The sheet's artwork uses only CMYK process colour plus the CutContour spot: every path, shading and image is
    DeviceCMYK (or a CMYK ICC space, or a DeviceN of process inks), or a cut path in the CutContour spot. An RGB path
    or image fails; grey, Lab or another spot goes to a person; RGB only in type (labels or sticker lettering) goes
    to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    ops = _pdf_paint(str(path))
    if not ops:
        return PERSON, {'reason': 'no paint operations read'}
    process = re.compile(r'^(cmyk|devicen:(?:cyan|magenta|yellow|black|,)+|indexed:cmyk)$', re.I)
    rgb_art, odd, rgb_text = [], set(), 0
    for o in ops:
        cs = o['cs']
        if _is_cut(o) and re.fullmatch(r'spot:cut\s*contour', cs.replace('#20', ' '), re.I):
            continue
        if process.match(cs) or cs == 'mask':
            continue
        if cs in ('rgb', 'indexed:rgb'):
            if o['kind'] == 'text':
                rgb_text += 1
            else:
                rgb_art.append(o['kind'])
            continue
        odd.add(cs)
    if rgb_art:
        return 'fail', {'rgb_objects': len(rgb_art), 'kinds': sorted(set(rgb_art))}
    if odd or rgb_text:
        return PERSON, {'reason': 'colour spaces that need a look', 'spaces': sorted(odd), 'rgb_text_runs': rgb_text}
    return 'pass', {'paint_operations': len(ops)}


@functools.lru_cache(maxsize=4)
def _cmyk_to_srgb_table(icc: str):
    from PIL import ImageCms
    src = ImageCms.getOpenProfile(icc)
    dst = ImageCms.createProfile('sRGB')
    return ImageCms.buildTransform(src, dst, 'CMYK', 'RGB', renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)


def _to_srgb(cs, values, icc):
    if cs in ('rgb',) and len(values) == 3:
        return np.array(values) * 255
    if cs == 'gray' and len(values) == 1:
        return np.array(values * 3) * 255
    if cs == 'cmyk' and len(values) == 4:
        if icc is None:
            return None
        im = Image.new('CMYK', (1, 1), tuple(int(round(v * 255)) for v in values))
        from PIL import ImageCms
        out = ImageCms.applyTransform(im, _cmyk_to_srgb_table(str(icc)))
        return np.array(out.getpixel((0, 0)), float)
    return None


def op_pdf_managed_palette(path, a):
    """With colour management on, every colour painted on the sheet except the cut paths is a palette colour: RGB
    values as written; CMYK values converted to sRGB through the supplied output profile (icc). Within 5 passes;
    30 or more from every palette colour fails; between, or a colour space that cannot be converted (a spot other
    than the cut one, Lab, an image's pixels), goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    try:
        icc = base.asset_path(a, a['icc']) if a.get('icc') else None
    except FileNotFoundError:
        icc = None
    seen, bad, unsure = {}, [], []
    for o in _pdf_paint(str(path)):
        if _is_cut(o):
            continue
        if o['kind'] in ('image', 'shading'):
            if o['cs'] != 'mask':
                unsure.append(f"{o['kind']} in {o['cs']}")
            continue
        if o['cs'] == 'pattern':
            unsure.append('pattern fill')
            continue
        c = _to_srgb(o['cs'], o['values'], icc)
        if c is None:
            unsure.append(f"colour in {o['cs']}")
            continue
        hx = r3._to_hex(c)
        if hx in seen:
            continue
        v = _verdict(_dist(c, a['hexes']), 5)
        seen[hx] = v
        if v == 'far':
            bad.append(hx)
        elif v == 'near':
            unsure.append(hx)
    if bad:
        return 'fail', {'outside_palette': bad[:6]}
    if unsure:
        return PERSON, {'reason': 'colours that need a look', 'items': sorted(set(unsure))[:6]}
    if not seen:
        return PERSON, {'reason': 'no colours read'}
    return 'pass', {'colours': sorted(seen)}


def op_pdf_labels_colour(path, a):
    """Labels, slugs and die-line notes on a production sheet (live type lying outside every cut path's box, so not
    part of a sticker) are in the colours; secondary colours (e.g. Ash Green for a secondary line) only on lines no
    larger than the largest line in a primary colour. Lettering drawn as outlines outside the stickers goes to a
    person; no label: a pass."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    import pymupdf
    key = str(path)
    doc = pymupdf.open(key)
    spans = r2._pdf_spans(key)
    # sticker boxes: the cut paths, read from the drawings painted on a cut layer or in the cut spot (their colour
    # in the drawing list is the one the cut operations set); fall back to the placed forms' boxes
    cut_boxes = {}
    cut_colours = set()
    paint = [o for o in _pdf_paint(key) if o['kind'] == 'path' and _is_cut(o)]
    if paint:
        for n, info in enumerate(_pdf_pages(key)):
            for d in info['drawings']:
                if d.get('fill') is None and d.get('color') is not None:
                    cut_colours.add(base._hex(d['color']))
        # the cut stroke colour: the stroke colour used by drawings that no artwork fill shares
        art = {base._hex(d['fill']) for info in _pdf_pages(key) for d in info['drawings'] if d.get('fill') is not None}
        cut_colours = {c for c in cut_colours if c not in art}
    for n, info in enumerate(_pdf_pages(key)):
        cut_boxes[n] = [tuple(d['rect']) for d in info['drawings'] if d.get('fill') is None and d.get('color') is not None
                        and base._hex(d['color']) in cut_colours and d['rect'].width > 20 and d['rect'].height > 20]
        if any(_glyph_paths(info, cut_boxes[n] or [tuple(r) for _, r in info['images']]) >= 8 for _ in [0]) and not cut_boxes[n]:
            return PERSON, {'reason': 'the stickers cannot be told from labels (no cut paths found) and some lettering may be outlined'}
    labels = [s for s in spans if not any(_within(s['bbox'], b, 1.0) for b in cut_boxes.get(s['page'], []))]
    if not labels:
        return 'pass', {'reason': 'no labels'}
    # type painted in CMYK or a spot: its colour is read through the output profile, not the reader's RGB, so the
    # comparison is for a person
    if any(o['kind'] == 'text' and o['cs'] not in ('rgb', 'gray') for o in _pdf_paint(key)):
        return PERSON, {'reason': 'labels painted in CMYK or a spot colour; their colour needs the output profile'}
    allowed = a['colors'] + a.get('secondary', [])
    bad = [(s['text'][:30], s['color']) for s in labels if not base._near_hex(s['color'], allowed, TOL_PDF)]
    if bad:
        return 'fail', {'not_matching': bad[:6]}
    prim = [s['size'] for s in labels if base._near_hex(s['color'], a['colors'], TOL_PDF)]
    sec = [s for s in labels if base._near_hex(s['color'], a.get('secondary', []), TOL_PDF) and not base._near_hex(s['color'], a['colors'], TOL_PDF)]
    if sec and (not prim or max(s['size'] for s in sec) > max(prim) + 0.01):
        return 'fail', {'reason': 'a secondary colour on the main label line', 'lines': [s['text'][:30] for s in sec][:3]}
    return 'pass', {'labels': len(labels), 'cut_boxes': sum(len(v) for v in cut_boxes.values())}


# ================================================================ stickers: placed masters, fine detail


def _render_sheet(path: Path, dpi=100):
    """The sheet rendered with colour management on (CMYK through MuPDF's colour engine), then switched off again."""
    import pymupdf
    pymupdf.TOOLS.set_icc(True)
    try:
        return np.asarray(base.render_pdf(path, 0, dpi)).astype(np.int16)
    finally:
        pymupdf.TOOLS.set_icc(False)


def op_placed_master(path, a):
    """A delivered sticker placed on the production sheet is that file: the delivered SVG (cut layer left out) is
    rendered and found on the sheet (rendered at 200 dpi, colour management on) by feature matching, or by template
    matching at its own proportions. Proportions: the placed copy's aspect within 2% of the file's passes, 5% or more
    off fails. Colours: the file is drawn into the sheet's pixels at the found place; at the file's solid pixels
    (eroded 3 px, thin lines left out) the sheet's pixel must fall nearest the same palette colour as the file's:
    2% or fewer differing passes; more goes to a person (never a fail). Not found goes to a person."""
    import cv2
    master = Path(a['_artifacts']) / a['deliverable']
    if not master.is_file():
        return PERSON, {'reason': 'the delivered sticker file is not available', 'file': a['deliverable']}
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from the PDF sheet'}
    has_text = any(r2._local(e.tag) == 'text' for e in r2._svg_root(master).iter())
    sheet = _render_sheet(path, 200)
    sheet_gray = cv2.cvtColor(sheet.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    rgba = r2._render_svg_text(r2._svg_without_cut(master), 600)
    m_rgb = np.asarray(Image.alpha_composite(Image.new('RGBA', (rgba.shape[1], rgba.shape[0]), (255, 255, 255, 255)),
                                             Image.fromarray(rgba)).convert('RGB')).astype(np.int16)
    m_gray = cv2.cvtColor(m_rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    n, corners, state = base.find_asset(sheet_gray, m_gray)
    if state != 'found':
        return PERSON, {'reason': 'the delivered sticker was not found on the sheet (it may be redrawn)'}
    ok, change = base._shape_ok(np.float32(corners), m_gray.shape, tol=0.02)
    ev = {'aspect_change': float(change)}
    if change >= 0.05:
        return (PERSON if has_text else 'fail'), dict(ev, reason='proportions changed')
    h, w = m_gray.shape
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
    size = (sheet.shape[1], sheet.shape[0])
    on_sheet = cv2.warpPerspective(rgba.astype(np.uint8), H, size, flags=cv2.INTER_AREA).astype(np.int16)
    solid = r3._flat(on_sheet[..., :3], 2) & (on_sheet[..., 3] == 255)
    solid = cv2.erode(solid.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if solid.sum() < 200:
        return PERSON, dict(ev, reason='too few solid pixels to compare')
    pal = np.array([r3._hex_rgb(x) for x in a['hexes']], float)
    def nearest(px):
        return np.abs(px[:, None, :].astype(float) - pal[None, :, :]).max(axis=2).argmin(axis=1)
    differ = float((nearest(on_sheet[..., :3][solid]) != nearest(sheet[solid])).mean())
    ev['colour_differs_share'] = round(differ, 3)
    # a colour difference goes to a person: the sheet's CMYK and fine line work rendered at sheet resolution do not
    # settle it alone; only changed proportions fail
    if change > 0.02 or differ > 0.02:
        return PERSON, ev
    return 'pass', ev


def op_ink_detail(path, a):
    """If the colour (Ink Black) appears on a transparent sticker proof, it is fine detail only: no piece of it covers
    5% or more of the sticker's inked (opaque) area (a main shape), no piece runs along the sticker's outer edge (a
    backing shape), all of it together covers no more than 5% of the inked area (the brand's limit for fine detail;
    5 to 5.75% goes to a person), and no line OCR reads is inked in it. Five or more pieces of letter height in a row
    (lettering such as a wordmark) go to a person. Not present: a pass."""
    import cv2
    rgb, alpha = _rgba(path)
    if alpha is None:
        return PERSON, {'reason': 'no transparent surround: the sticker area cannot be told'}
    inked = alpha >= 128
    tol = r3._tol(path, a)
    hit = r3._near_mask(rgb, a['hexes'], tol) & (alpha >= OPAQUE)
    comps = r3._components(hit)
    if not comps:
        return 'pass', {'reason': 'not present'}
    total = 100 * hit.sum() / max(1, inked.sum())
    edge = cv2.dilate((~inked).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    ev = {'share_of_ink_pct': round(total, 2), 'pieces': len(comps)}
    ys, xs = np.where(inked)
    sticker_h = ys.max() - ys.min() + 1
    tall = []
    for comp, st in comps:
        if st[4] >= 0.05 * inked.sum():
            return 'fail', dict(ev, reason='a main shape in the colour', piece_px=int(st[4]))
        on_edge = (comp & edge).sum() / st[4]
        if on_edge >= 0.3 and max(st[2], st[3]) >= 0.2 * sticker_h:
            return 'fail', dict(ev, reason='a backing shape along the sticker edge in the colour')
        if st[3] >= 0.03 * sticker_h:
            tall.append(st)
    if total > 5.75:
        return 'fail', dict(ev, reason='more than fine detail')
    for l in _ocr(str(path), -1).lines:
        if not base._real(l):
            continue
        got = r3._ink_and_ground(rgb, l.bbox)
        if got is not None and _dist(got[0], a['hexes']) <= tol + 3:
            return ('fail' if l.conf >= OCR_GOOD_CONF else PERSON), dict(ev, reason='type in the colour', line=l.text)
    if len(tall) >= 5:
        hs = sorted(st[3] for st in tall)
        if hs[len(hs) // 2] > 0 and sum(abs(x - hs[len(hs) // 2]) <= 0.3 * hs[len(hs) // 2] for x in hs) >= 5:
            return PERSON, dict(ev, reason='letter-like pieces in the colour (lettering?)')
    if total > 5.0:
        return PERSON, dict(ev, reason='close to the 5% limit')
    return 'pass', ev


# ================================================================ motion: capture frames, title letters, title size


@functools.lru_cache(maxsize=6)
def _video_small(key: str, width: int = 480):
    """Every frame of a video at a small width (for finding the right frame), as uint8 RGB arrays."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['ffmpeg', '-v', 'error', '-i', key, '-vf', f'scale={width}:-2', str(Path(tmp) / 'f%05d.png')],
                       check=True, timeout=600)
        return tuple(np.asarray(Image.open(p).convert('RGB')) for p in sorted(Path(tmp).glob('f*.png')))


@functools.lru_cache(maxsize=32)
def _video_frame(key: str, index: int):
    """One frame of a video at full size (frame number index, counting from 0)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'f.png'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', key, '-vf', f'select=eq(n\\,{index})', '-vsync', '0', '-frames:v', '1', str(out)],
                       check=True, timeout=600)
        return np.asarray(Image.open(out).convert('RGB')) if out.is_file() else None


@functools.lru_cache(maxsize=12)
def _capture_match(key: str, capture: str, dirs: tuple):
    """Where the capture frame shows in a thumbnail: every frame of the capture video is compared with the thumbnail
    (whole-image correlation at 480 px), the best three are aligned by feature matching at full size, then their
    neighbours, and the frame whose warped pixels agree with the most of the thumbnail wins. Thumbnail pixels within
    24 levels of it (after a 5 px blur) are the capture; the rest is graphics laid over it. None when no frame
    matches over a third of the thumbnail."""
    import cv2
    try:
        cap = base.asset_path({'_asset_dirs': list(dirs)}, capture)
    except FileNotFoundError:
        return None
    thumb = r3._pixels(key).astype(np.float32)
    h, w = thumb.shape[:2]
    small = _video_small(str(cap))
    t_small = cv2.resize(cv2.cvtColor(thumb.astype(np.uint8), cv2.COLOR_RGB2GRAY), (480, round(480 * h / w)), interpolation=cv2.INTER_AREA).astype(float)
    scores = []
    for f in small:
        g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (t_small.shape[1], t_small.shape[0]), interpolation=cv2.INTER_AREA).astype(float)
        x, y = t_small - t_small.mean(), g - g.mean()
        scores.append(float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9)))
    t_gray = cv2.cvtColor(thumb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    best, tried = None, set()

    def attempt(i):
        nonlocal best
        if i in tried or not 0 <= i < len(small):
            return
        tried.add(i)
        f = _video_frame(str(cap), i)
        if f is None:
            return
        fg = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY)
        fs = cv2.resize(fg, (960, round(960 * fg.shape[0] / fg.shape[1])), interpolation=cv2.INTER_AREA)
        n, corners, state = base.find_asset(t_gray, fs)
        if state != 'found':
            return
        k = fs.shape[1] / fg.shape[1]
        src = np.float32([[0, 0], [fs.shape[1], 0], [fs.shape[1], fs.shape[0]], [0, fs.shape[0]]]) / k
        H = cv2.getPerspectiveTransform(src, np.float32(corners))
        warped = cv2.warpPerspective(f.astype(np.float32), H, (w, h), flags=cv2.INTER_LINEAR)
        valid = cv2.warpPerspective(np.full(f.shape[:2], 255, np.uint8), H, (w, h), flags=cv2.INTER_NEAREST) > 0
        diff = cv2.blur(np.abs(thumb - warped).mean(axis=2), (5, 5))
        capm = valid & (diff < 24)
        capm = cv2.morphologyEx(capm.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
        share = float(capm.sum() / capm.size)
        if best is None or share > best['share']:
            loose = valid & (cv2.blur(np.abs(thumb - warped).mean(axis=2), (9, 9)) < 40)
            best = dict(capture=capm, loose=loose, valid=valid, frame=warped, share=share, index=i)
    for i in list(np.argsort(scores)[::-1][:3]):
        attempt(int(i))
    if best is not None:
        for i in range(best['index'] - 3, best['index'] + 4):
            attempt(i)
    if best is None or best['share'] < 0.33:
        return None
    return best


def _local_stats(a, b, k=15):
    """Local means, standard deviations and correlation of two grey images over k x k windows."""
    import cv2
    a, b = a.astype(np.float32), b.astype(np.float32)
    ma, mb = cv2.blur(a, (k, k)), cv2.blur(b, (k, k))
    va = np.maximum(cv2.blur(a * a, (k, k)) - ma * ma, 0)
    vb = np.maximum(cv2.blur(b * b, (k, k)) - mb * mb, 0)
    cov = cv2.blur(a * b, (k, k)) - ma * mb
    return ma, mb, np.sqrt(va), np.sqrt(vb), cov / (np.sqrt(va * vb) + 1e-6)


def op_capture_wash(path, a):
    """No scrim or colour wash over the capture frame. The capture's visible parts are where the thumbnail keeps the
    matched source frame's detail (15 px windows correlating at 0.8 or more where the frame has texture); there each
    colour channel is fitted to the frame (iteratively, outliers left out), and the leftover tone shift is smoothed.
    Pass: gains 0.92 to 1.10, offsets under 16 levels, and under 3% of the visible capture shifted by 12 levels or
    more. Fail: an even darkening or lightening of everything (a gain under 0.75), or a fifth or more of the visible
    capture shifted one way by 25 levels or more (a partial scrim or vignette). Anything else goes to a person."""
    import cv2
    cap = _capture_match(str(path), a['capture'], tuple(a.get('_asset_dirs') or []))
    if cap is None:
        return PERSON, {'reason': 'the capture frame the thumbnail is built on was not matched'}
    thumb = r3._pixels(str(path)).astype(np.float32)
    frame = cap['frame']
    tg = cv2.cvtColor(np.clip(thumb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    fg = cv2.cvtColor(np.clip(frame, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    mt, mf, st, sf, ncc = _local_stats(tg, fg)
    vis = cap['valid'] & (sf >= 8) & (ncc >= 0.8)
    vis = cv2.erode(vis.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    if vis.mean() < 0.15:
        return PERSON, {'reason': 'too little of the capture visible to compare', 'visible_share': round(float(vis.mean()), 3)}
    gains, offs = [], []
    for ch in range(3):
        x, y = frame[..., ch][vis], thumb[..., ch][vis]
        keep = np.ones(len(x), bool)
        for _ in range(4):
            g, o = np.polyfit(x[keep], y[keep], 1)
            keep = np.abs(y - (g * x + o)) < 20
        gains.append(float(g))
        offs.append(float(o))
    resid = (thumb - (frame * np.array(gains) + np.array(offs))).mean(axis=2)
    smooth = cv2.blur(np.where(vis, resid, 0).astype(np.float32), (31, 31)) / np.maximum(cv2.blur(vis.astype(np.float32), (31, 31)), 1e-3)
    shifted = vis & (np.abs(smooth) >= 12)
    share = float(shifted.sum() / vis.sum())
    strong = vis & (np.abs(smooth) >= 25)
    sign = float(np.sign(np.median(smooth[strong]))) if strong.any() else 0.0
    one_way = float((vis & (smooth * sign >= 25)).sum() / vis.sum()) if sign else 0.0
    ev = {'gain': [round(g, 3) for g in gains], 'offset': [round(o, 1) for o in offs], 'shifted_share': round(share, 3),
          'visible_share': round(float(vis.mean()), 3)}
    if min(gains) >= 0.92 and max(gains) <= 1.10 and max(abs(o) for o in offs) < 16 and share < 0.03:
        return 'pass', ev
    if (min(gains) < 0.75 and share < 0.03) or one_way >= 0.2:
        return 'fail', ev
    return PERSON, dict(ev, reason='the capture\'s tones differ from the source frame (a grade or a wash; a person decides)')


@functools.lru_cache(maxsize=24)
def _ocr_words(key: str, frame: int):
    """Word boxes read by Tesseract (sparse text at 1x and 2x, normal and inverted), overlapping reads merged,
    the more confident kept."""
    from PIL import ImageOps
    im = Image.fromarray(_frame_rgb(Path(key), frame).astype(np.uint8))
    words = []
    for scale in (1.0, 2.0):
        sim = im if scale == 1 else im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
        gray = ImageOps.grayscale(sim)
        for cand in (gray, ImageOps.invert(gray)):
            for wd in base._tesseract(cand, 11, scale):
                clash = [o for o in words if base._overlap(wd['bbox'], o['bbox']) > 0.5]
                if not clash:
                    words.append(wd)
                elif wd['conf'] > max(o['conf'] for o in clash) and len(re.sub(r'\W', '', wd['text'])) >= max(len(re.sub(r'\W', '', o['text'])) for o in clash):
                    words = [o for o in words if o not in clash] + [wd]
    return words


def _norm_word(t):
    return re.sub(r'[^A-Z0-9]', '', t.upper())


def _title_word_boxes(key, frame, title):
    """Boxes of the title's words of two or more letters (single letters are not read reliably), each from a
    confident OCR read; None if a word was not read."""
    words = _ocr_words(key, frame)
    want = [w for w in dict.fromkeys(_norm_word(x) for x in title.split()) if len(w) >= 2]
    found = {}
    for w in want:
        hits = [o for o in words if _norm_word(o['text']) == w and o['conf'] >= OCR_GOOD_CONF]
        if not hits:
            return None, w
        found[w] = hits
    hs = sorted(o['bbox'][3] - o['bbox'][1] for hits in found.values() for o in hits)
    med = hs[len(hs) // 2]
    boxes = [(w, o['bbox']) for w, hits in found.items() for o in hits if o['bbox'][3] - o['bbox'][1] >= 0.6 * med]
    return boxes, None


def op_title_letters(path, a):
    """The title's words (OCR word boxes; video: the last held frame, or every held frame with frames "held"): mode
    "fill": each word's letters are filled in an allowed colour: letter-sized pieces in those colours, not touching
    the box's padded edge, cover 55% or more of the word's width (passes); 10% or less (letters left transparent or in
    another colour) fails; between goes to a person. mode "outline": round each filled letter, the ring 1.5 to 3.5 px
    out is the outline colour on 85% or more of its pixels (an outline); 30% or less fails; where that colour runs
    on 14 px or more all round, the letters sit on a ground of that colour and an outline cannot be told from it (a
    person); a dark-grey fringe outside the outline on 35% or more of the next 3 px (a blurred edge) goes to a person."""
    import cv2
    frames = _frames_of(path, 'held' if a.get('frames') == 'held' else 'last')
    tol = r3._tol(path, a) + 3
    verdicts = []
    for f in frames:
        rgb = _frame_rgb(path, f)
        boxes, missing = _title_word_boxes(str(path), f, a['title'])
        if boxes is None:
            if a.get('frames') == 'held':
                continue                              # the title is not on this held frame
            return PERSON, {'reason': f'title word not read: {missing}'}
        fill_any = r3._near_mask(rgb, a['fills'], tol)
        for word, (x0, y0, x1, y1) in boxes:
            hgt = y1 - y0
            pad = int(round(0.35 * hgt))
            X0, Y0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
            X1, Y1 = min(rgb.shape[1], int(x1) + pad), min(rgb.shape[0], int(y1) + pad)
            crop_fill = fill_any[Y0:Y1, X0:X1]
            n, labels, stats, _ = cv2.connectedComponentsWithStats(crop_fill.astype(np.uint8), connectivity=8)
            letters = np.zeros_like(crop_fill)
            for i in range(1, n):
                x, y, bw, bh, area = stats[i]
                if bh < 0.35 * hgt or area < 0.01 * hgt * hgt:
                    continue
                if x == 0 or y == 0 or x + bw >= crop_fill.shape[1] or y + bh >= crop_fill.shape[0]:
                    continue                          # a band or ground in a fill colour, not a letter
                letters |= labels == i
            cols = letters[:, int(x0) - X0:int(x1) - X0].any(axis=0)
            cover = float(cols.mean()) if cols.size else 0.0
            if a['mode'] == 'fill':
                verdicts.append((word, 'pass' if cover >= 0.55 else 'fail' if cover <= 0.10 else PERSON, {'cover': round(cover, 2)}))
                continue
            if cover < 0.55:
                verdicts.append((word, PERSON, {'reason': 'letters not found filled', 'cover': round(cover, 2)}))
                continue
            crop = rgb[Y0:Y1, X0:X1]
            dist = cv2.distanceTransform((~letters).astype(np.uint8), cv2.DIST_L2, 3)
            black = r3._near_mask(crop, [a['outline']], tol)
            def share(d0, d1):
                ring = (dist > d0) & (dist <= d1) & ~crop_fill
                return float(black[ring].mean()) if ring.sum() >= 20 else None
            s1 = share(1.5, 3.5)
            if s1 is None:
                verdicts.append((word, PERSON, {'reason': 'no room round the letters'}))
                continue
            if s1 <= 0.30:
                verdicts.append((word, 'fail', {'outline_share': round(s1, 2)}))
                continue
            if s1 < 0.85:
                verdicts.append((word, PERSON, {'outline_share': round(s1, 2)}))
                continue
            wdt = 3
            for d in range(4, 15):
                s = share(d - 1, d)
                if s is None or s < 0.85:
                    break
                wdt = d
            if wdt >= 14:
                verdicts.append((word, PERSON, {'reason': 'the letters sit on a ground of the outline colour; an outline cannot be told'}))
                continue
            ring = (dist > wdt + 1) & (dist <= wdt + 4) & ~crop_fill
            dev = np.abs(crop[ring] - r3._hex_rgb(a['outline'])).max(axis=1)
            grey = float(((dev >= 16) & (dev <= 90)).mean()) if ring.sum() else 0.0
            if grey >= 0.35:
                verdicts.append((word, PERSON, {'reason': 'the outline\'s outer edge may be blurred', 'grey_share': round(grey, 2)}))
                continue
            verdicts.append((word, 'pass', {'outline_px': wdt}))
    if not verdicts:
        return (PERSON, {'reason': 'title not found on any held frame'})
    for st in ('fail', PERSON):
        hit = [(w, ev) for w, s, ev in verdicts if s == st]
        if hit:
            return st, {'words': [dict(ev, word=w) for w, ev in hit[:4]]}
    return 'pass', {'words': len(verdicts)}


def op_title_largest(path, a):
    """On every held frame showing a title stack (lines made only of the words of one of the titles, e.g. the
    channel name or an upload title), the title is the largest text: its smallest line at least 8% larger (letter
    height) than every other line passes; another line 8% larger than its largest line fails; otherwise a person.
    No title on any held frame: a pass where every frame was read confidently."""
    frames = _frames_of(path, 'all')
    results, confident = [], True
    titles = [[_norm_word(w) for w in t.split() if _norm_word(w)] for t in a['titles']]
    for f in frames:
        layer = _ocr(str(path), f)
        confident = confident and layer.confident
        lines = [l for l in layer.lines if base._real(l)]
        for words in titles:
            own = [l for l in lines if [_norm_word(x) for x in l.text.split() if _norm_word(x)] and
                   all(_norm_word(x) in words for x in l.text.split() if _norm_word(x))]
            if not own or not set(words) <= {_norm_word(x) for l in own for x in l.text.split()}:
                continue
            rest = [l for l in lines if l not in own]
            if not all(l.size_ok for l in own):
                results.append((PERSON, {'frame': f, 'reason': 'title letter height not measured'}))
                continue
            big = max((l for l in rest if l.size_ok), key=lambda l: l.size, default=None)
            t_min, t_max = min(l.size for l in own), max(l.size for l in own)
            if big is None or t_min >= 1.08 * big.size:
                results.append(('pass', {'frame': f}))
            elif big.size >= 1.08 * t_max and big.conf >= OCR_GOOD_CONF:
                results.append(('fail', {'frame': f, 'larger': big.text}))
            else:
                results.append((PERSON, {'frame': f, 'reason': 'sizes too close to call', 'other': big.text}))
    if not results:
        return ('pass', {'reason': 'no title stack on a held frame'}) if confident else (PERSON, {'reason': 'not every frame read clearly'})
    for st in ('fail', PERSON):
        hit = [ev for s, ev in results if s == st]
        if hit:
            return st, hit[0]
    return 'pass', {'frames': len(results)}


def op_raster_roles(path, a):
    """On an image, the colours appear only as hairlines or dividers (pieces at most thin_px across, 8 times as long),
    photographs (see _photos, two-colour treatments included) left out: a solid piece 400 px or larger in box that is
    neither (a panel, a shape or type) fails; a thicker straight line or a small piece goes to a person."""
    rgb, alpha = _rgba(path)
    keep = ~_photos(path, a)
    if alpha is not None:
        keep &= alpha >= OPAQUE
    h, w = rgb.shape[:2]
    thin = a.get('thin_px', max(3, round(0.004 * min(h, w))))
    hit = r3._near_mask(rgb, a['hexes'], r3._tol(path, a)) & keep
    bad, unsure, ok = [], [], 0
    for comp, st in r3._components(hit, 12):
        x, y, bw, bh, area = st
        short, long_ = sorted((bw, bh))
        if short <= thin and long_ >= 8 * short:
            ok += 1
        elif short <= 3 * thin and long_ >= 8 * short or bw * bh < 400:
            unsure.append([int(x), int(y), int(bw), int(bh)])
        else:
            bad.append([int(x), int(y), int(bw), int(bh)])
    if bad:
        return 'fail', {'not_a_hairline': bad[:4]}
    if unsure:
        return PERSON, {'reason': 'pieces that may be thick rules or small marks', 'boxes': unsure[:4]}
    return 'pass', {'hairlines': ok}


def op_no_panel(path, a):
    """The colours are never a ground or panel: no flat area in them covers 1% of the image or held frame or more,
    and none of 0.2% or more holds a line of text (a label panel); smaller pieces (highlight shapes) are allowed.
    Photographs and, with capture, the capture frame are left out; a held video frame showing footage goes to a
    person."""
    import cv2
    tol = r3._tol(path, a)
    for f in _frames_of(path):
        rgb, alpha = _rgba(path, f)
        if a.get('capture'):
            keep = _keep_capture(path, a, rgb, alpha)
            if keep is None:
                return PERSON, {'reason': 'the capture frame the design is built on was not matched'}
        else:
            keep = ~_photos(path, a, f)
            if alpha is not None:
                keep &= alpha >= OPAQUE
        if path.suffix.lower() == '.mp4' and _footage(rgb, keep):
            return PERSON, {'reason': 'a held frame shows footage', 'frame': f}
        h, w = rgb.shape[:2]
        hit = r3._flat(rgb, 2 if not r3._lossy(path) else 6) & keep & r3._near_mask(rgb, a['hexes'], tol)
        hit = cv2.morphologyEx(hit.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
        lines = [l for l in _ocr(str(path), f).lines if base._real(l)]
        for comp, st in r3._components(hit, int(0.002 * h * w)):
            x, y, bw, bh, area = st
            if area >= 0.01 * h * w:
                return 'fail', {'panel_share': round(float(area) / (h * w), 4), 'box': [int(x), int(y), int(bw), int(bh)], 'frame': f}
            for l in lines:
                if _inter(l.bbox, (x, y, x + bw, y + bh)) >= 0.7 * _area(l.bbox):
                    return 'fail', {'reason': 'a panel carrying text', 'line': l.text, 'frame': f}
    return 'pass', {'reason': 'no ground or panel in the colour'}


def op_raster_photo_overlay(path, a):
    """No scrim or overlay over a photograph on an image. No photograph found at all (no textured or two-colour photo
    area of 1% of the image, no supplied photo matched) on an image that is mostly flat colour (85% of its pixels):
    nothing to overlay, a pass. Otherwise the supplied photo found is compared with its file
    (objective_ops_r3.op_no_overlay: a pass, an even scrim a fail, anything else a person)."""
    rgb = r3._pixels(str(path))
    m = _photos(path, a)
    flat = r3._flat(rgb, 2).mean()
    if m.mean() < 0.01 and flat >= 0.85:
        return 'pass', {'reason': 'no photograph on the image', 'flat_share': round(float(flat), 2)}
    return r3.op_no_overlay(path, a)



# ================================================================ PDF type: typeface identity, sizes, spacing


@functools.lru_cache(maxsize=8)
def _font_file(path: str):
    from fontTools.ttLib import TTFont
    return TTFont(path)


def _grid(font):
    """Instances to try across a variable font's axes: weight by 50, width by 5, optical size at common sizes."""
    if 'fvar' not in font:
        return [{}]
    axes = {a.axisTag: a for a in font['fvar'].axes}
    vals = {}
    for tag, ax in axes.items():
        if tag == 'wght':
            v = list(range(int(np.ceil(ax.minValue / 50) * 50), int(ax.maxValue) + 1, 50))
        elif tag == 'wdth':
            v = list(range(int(np.ceil(ax.minValue / 5) * 5), int(ax.maxValue) + 1, 5))
        elif tag == 'opsz':
            v = [x for x in (6, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 60, 72, 96, 144) if ax.minValue <= x <= ax.maxValue]
        else:
            v = []
        vals[tag] = sorted(set(v + [ax.minValue, ax.defaultValue, ax.maxValue]))
    out = [{}]
    for tag, v in vals.items():
        out = [dict(o, **{tag: x}) for o in out for x in v]
    return out


@functools.lru_cache(maxsize=4096)
def _advance(path: str, loc: tuple, ch: str):
    font = _font_file(path)
    gid = font.getBestCmap().get(ord(ch))
    if gid is None:
        return None
    gs = font.getGlyphSet(location=dict(loc)) if 'fvar' in font else font.getGlyphSet()
    return gs[gid].width / font['head'].unitsPerEm


def _fit(path, chars):
    """Mean relative difference between measured advance widths (em) and the font's, at every instance tried."""
    font = _font_file(path)
    out = []
    for loc in _grid(font):
        key = tuple(sorted(loc.items()))
        errs = []
        for ch, wd in chars:
            ref = _advance(path, key, ch)
            if ref:
                errs.append(abs(wd - ref) / ref)
        if len(errs) >= max(3, 0.8 * len(chars)):
            out.append((float(np.mean(errs)), loc))
    return out


@functools.lru_cache(maxsize=16)
def _pdf_glyphs(key: str):
    """Every text span with its characters' advance widths in em (box width over size) and its paint mode."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        stroked = [tuple(t['bbox']) for t in page.get_texttrace() if t.get('type', 0) not in (0, 3)]
        for b in page.get_text('rawdict')['blocks']:
            for l in b.get('lines', []):
                for sp in l['spans']:
                    text = ''.join(c['c'] for c in sp['chars'])
                    if not text.strip():
                        continue
                    chars = [(c['c'], (c['bbox'][2] - c['bbox'][0]) / sp['size']) for c in sp['chars'] if c['c'].strip() and sp['size'] > 0]
                    out.append(dict(text=text, font=sp['font'], size=sp['size'], bbox=tuple(sp['bbox']), page=page.number, chars=chars,
                                    line=tuple(l['bbox']), stroked=any(base._overlap(sb, sp['bbox']) > 0.5 for sb in stroked)))
    return out


@functools.lru_cache(maxsize=64)
def _embedded_family(key: str, fontname: str):
    """The family name recorded inside the embedded font program (name IDs 16 or 1), or None when unreadable."""
    import io
    import pymupdf
    from fontTools.ttLib import TTFont
    doc = pymupdf.open(key)
    for page in doc:
        for xref, ext, ftype, basefont, name, enc, *_ in page.get_fonts(full=True):
            if basefont.split('+', 1)[-1] != fontname.split('+', 1)[-1]:
                continue
            try:
                buf = doc.extract_font(xref)[3]
                names = TTFont(io.BytesIO(buf))['name']
                fam = names.getDebugName(16) or names.getDebugName(1)
                return re.sub(r'[^a-z0-9]', '', fam.lower()) if fam else None
            except Exception:
                return None
    return None


def _select_spans(key, layer, a):
    """Spans a type check is about: texts (lines carrying each named text, which may run over several lines; only
    spans that belong to it), digits (every span with a figure), all_text."""
    spans = _pdf_glyphs(key)
    picks = []
    for t in a.get('texts', []):
        hits = [l for l in layer.lines if contains(l.text, t, False)] or base._span(layer, t, max_lines=12)
        if not hits:
            if a.get('optional'):
                continue
            return None, t
        for l in hits:
            picks += [sp for sp in spans if sp['page'] == l.page and base._overlap(sp['bbox'], l.bbox) > 0.5
                      and canon(sp['text'], False).strip() in canon(t, False)]
    if a.get('digits'):
        picks += [sp for sp in spans if re.search(r'\d', sp['text'])]
    if a.get('labels'):
        picks += _labels(key)[0]
    if a.get('all_text'):
        picks += spans
    uniq = []
    for sp in picks:
        if sp not in uniq:
            uniq.append(sp)
    return uniq, None


def op_font_is(path, a):
    """PDF type is set in the named typeface (family and weight), told from the glyphs' advance widths against the
    supplied font file at every instance of its axes (weight by 50, width by 5, optical sizes), together with the
    font name the PDF records and the family named inside the embedded font. A span passes when the named weight
    fits its widths within 0.6% and either its font name says the same family and weight or no instance 100 or more
    weight units away also fits (within 1%). It fails when both names say another family and no instance of the
    named family fits within 0.6%, or when another weight fits within 0.6% and the named one is 2% or more off. Anything else, stroked (faux-bold) type, or spans with
    fewer than three letters to measure go to a person. skip_digits leaves figure-only spans out and measures letters
    only."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'type style is read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    if not layer.readable:
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    try:
        font_path = str(base.asset_path(a, a['font']))
    except FileNotFoundError:
        return PERSON, {'reason': 'the supplied font file is not available'}
    spans, missing = _select_spans(key, layer, a)
    if spans is None:
        return PERSON, {'reason': f'text not found: {missing[:40]}'}
    want = a.get('axes', {})
    fam = re.sub(r'[^a-z0-9]', '', a['family'].lower())
    wt = re.sub(r'[^a-z0-9]', '', a['weight'].lower())
    checked, bad, unsure = 0, [], []
    for sp in spans:
        chars = sp['chars']
        if a.get('skip_digits'):
            if re.fullmatch(r'[\d\s.,/#:;()\-–]+', sp['text']):
                continue
            chars = [(c, w) for c, w in chars if not c.isdigit()]
        if a.get('digits_only'):
            chars = [(c, w) for c, w in chars if c.isdigit()] or chars
        if sp['stroked']:
            unsure.append((sp['text'][:24], 'stroked type'))
            continue
        name_fam, name_wt = base._font_parts(sp['font'])
        name_ok = name_fam == fam and name_wt == wt
        fits = _fit(font_path, chars)
        if not fits or len(chars) < 3:
            unsure.append((sp['text'][:24], 'too few letters to measure'))
            continue
        checked += 1
        best_err, best_loc = min(fits, key=lambda t: t[0])
        req = [e for e, loc in fits if all(abs(loc.get(k, v) - v) <= 1e-6 for k, v in want.items())]
        req_err = min(req) if req else 1.0
        far = [e for e, loc in fits if 'wght' in want and abs(loc.get('wght', want['wght']) - want['wght']) >= 100]
        unique = not far or min(far) > 0.01
        if req_err <= 0.006 and (name_ok or unique):
            continue
        # another family: the PDF's font name and the embedded font's own family name both say so (one witness when
        # the font program cannot be read) and no instance of the named family fits the widths within 0.6%
        emb = _embedded_family(key, sp['font'])
        other_family = name_fam != fam and (emb is None or emb != fam)
        if (other_family and best_err > 0.006) or (best_err <= 0.006 and req_err >= 0.02):
            bad.append({'text': sp['text'][:30], 'font': sp['font'], 'fits': {k: v for k, v in best_loc.items()}, 'off_pct': round(100 * req_err, 1)})
        else:
            unsure.append((sp['text'][:24], sp['font'], round(100 * req_err, 2)))
    if bad:
        return 'fail', {'not_matching': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'typeface not certain from the glyphs', 'spans': unsure[:4]}
    if not checked:
        return ('pass', {'reason': 'no such type'}) if a.get('optional') else (PERSON, {'reason': 'no type to measure'})
    return 'pass', {'spans': checked}


def op_digit_size(path, a):
    """In the lines carrying the named texts, figures are set at the size of the letters round them: every figure
    span's size within 0.1 pt of the letter spans' passes, 15% or more off fails, between a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    spans, missing = _select_spans(key, layer, {'texts': a['texts']})
    if spans is None:
        return PERSON, {'reason': f'text not found: {missing[:40]}'}
    letters = [sp['size'] for sp in spans if re.search(r'[A-Za-z]', sp['text'])]
    figures = [sp['size'] for sp in spans if re.search(r'\d', sp['text'])]
    if not letters or not figures:
        return PERSON, {'reason': 'figures or letters not found'}
    ref = float(np.median(letters))
    worst = max(abs(x - ref) / ref for x in figures)
    ev = {'letters_pt': round(ref, 2), 'figures_pt': sorted({round(x, 2) for x in figures})}
    if all(abs(x - ref) <= 0.1 for x in figures):
        return 'pass', ev
    return ('fail' if worst >= 0.15 else PERSON), ev


def op_text_leading(path, a):
    """Consecutive lines of the named text (which runs over several lines) have baselines leading_pt apart, within
    tol_pt, read from the PDF's glyph origins. One line only: a pass."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    hits = [l for l in layer.lines if contains(l.text, a['text'], False)] or base._span(layer, a['text'], max_lines=12)
    if not hits:
        return PERSON, {'reason': 'text not found'}
    origins = _pdf_origins(key)
    ys = []
    for l in sorted(hits, key=lambda l: l.bbox[1]):
        o = [y for pg, bb, y, size in origins if pg == l.page and base._overlap(bb, l.bbox) > 0.5]
        if o:
            ys.append(float(np.median(o)))
    if len(ys) < 2:
        return 'pass', {'reason': 'one line'}
    gaps = [round(b - a_, 2) for a_, b in zip(ys, ys[1:])]
    off = [g for g in gaps if abs(g - a['leading_pt']) > a.get('tol_pt', 0.25)]
    return ('fail', {'baseline_gaps_pt': gaps}) if off else ('pass', {'baseline_gaps_pt': sorted(set(gaps))})


def op_text_smallest(path, a):
    """The named text (over several lines) is set smaller than every other text on the page: its largest span under
    the smallest other span, by font size in the PDF."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    spans, missing = _select_spans(key, layer, {'texts': [a['text']]})
    if not spans:
        return PERSON, {'reason': 'text not found'}
    mine = max(sp['size'] for sp in spans)
    others = [sp for sp in _pdf_glyphs(key) if sp not in spans and re.search(r'\w', sp['text'])]
    if not others:
        return 'pass', {'reason': 'no other text'}
    low = min(others, key=lambda sp: sp['size'])
    ev = {'text_pt': round(mine, 2), 'smallest_other_pt': round(low['size'], 2), 'other': low['text'][:30]}
    return ('pass' if mine < low['size'] - 0.01 else 'fail'), ev


def op_text_size_vs_file(path, a):
    """The named text is set no smaller than the same text on another delivered file (smallest span, within 0.05 pt)."""
    other = Path(a['_artifacts']) / a['deliverable']
    if path.suffix.lower() != '.pdf' or not other.is_file():
        return PERSON, {'reason': 'both files are read as PDFs'}
    sizes = []
    for f, t in ((path, a['text']), (other, a['other_text'])):
        spans, missing = _select_spans(str(f), base.pdf_layer(str(f)), {'texts': [t]})
        if not spans:
            return PERSON, {'reason': f'text not found on {f.name}'}
        sizes.append(min(sp['size'] for sp in spans))
    ev = {'this_pt': round(sizes[0], 2), 'other_pt': round(sizes[1], 2)}
    return ('pass' if sizes[0] >= sizes[1] - 0.05 else 'fail'), ev


def op_tracking_of(path, a):
    """The named text is not letterspaced: its letter spacing (median gap between glyph advance boxes, over size)
    at most pass_em passes, at least fail_em fails, between goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'letter spacing is read from a PDF'}
    rows = [r for r in r2._pdf_lines_chars(str(path)) if contains(r['text'], a['text'], False)]
    if not rows:
        return PERSON, {'reason': 'text not found'}
    em = max(r['tracking'] for r in rows)
    ev = {'tracking_em': round(em, 4)}
    if em <= a['pass_em']:
        return 'pass', ev
    return ('fail' if em >= a['fail_em'] else PERSON), ev


def op_pdf_solid_all(path, a):
    """Every type, panel, rule and ground is solid at full opacity with no tint effect: no opacity under 1, no
    gradient shading, no soft mask, no blend mode other than Normal (objective_ops_r3.op_solid_pdf plus soft masks and
    blend modes), and no shadow: no span repeated within 6 pt of itself in another colour."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    st, ev = r3.op_solid_pdf(path, a)
    if st != 'pass':
        return st, ev
    import pymupdf
    doc = pymupdf.open(str(path))
    for x in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(x, compressed=True)
        except Exception:
            continue
        if re.search(r'/SMask\s*<<', obj) or re.search(r'/SMask\s+\d+\s+0\s+R', obj) and '/ExtGState' in obj:
            return 'fail', {'soft_mask': True}
    if _blend_modes(str(path)):
        return 'fail', {'blend_mode': True}
    spans = r2._pdf_spans(str(path))
    for i, s1 in enumerate(spans):
        for s2 in spans[i + 1:]:
            if s1['page'] == s2['page'] and s1['text'].strip() == s2['text'].strip() and s1['color'] != s2['color']:
                dx, dy = abs(s1['bbox'][0] - s2['bbox'][0]), abs(s1['bbox'][1] - s2['bbox'][1])
                if dx <= 6 and dy <= 6:
                    return 'fail', {'shadow': s1['text'][:30]}
    return 'pass', ev


def op_only_supplied(path, a):
    """The page carries only supplied material: its live text, read in order, is the allowed texts and nothing more
    (letter case and spacing aside), with no exclamation mark; every drawing is a rectangle or a straight line (no curves:
    no burst, logo or illustration); every placed picture is one of the allowed supplied files (feature match).
    All true passes; anything else goes to a person (it may be fine; a person reads it). Never a fail."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    import pymupdf
    key = str(path)
    layer = base.pdf_layer(key)
    # the page's text, read in order, must be the allowed texts and nothing more: each allowed text is taken out
    # once (where it appears whole); any letter or figure left over is other wording (a repeated piece of the copy,
    # such as a town set again as a heading, is left over too)
    norm = lambda t: re.sub(r'\s+', ' ', canon(t, False)).strip()
    rest = ' ' + ' '.join(norm(l.text) for l in layer.lines) + ' '
    for t in sorted((norm(x) for x in a.get('texts', [])), key=len, reverse=True):
        if t and t in rest:
            rest = rest.replace(t, ' ', 1)
    left = re.findall(r'[a-z0-9]+', rest)
    if left:
        return PERSON, {'reason': 'other wording on the page', 'words': left[:6]}
    if '!' in layer.text:
        return PERSON, {'reason': 'an exclamation mark'}
    for info in _pdf_pages(key):
        for d in info['drawings']:
            kinds = {it[0] for it in d.get('items') or []}
            if kinds - {'l', 're', 'qu'}:
                return PERSON, {'reason': 'a drawn shape with curves (a symbol, burst or illustration?)'}
    doc = pymupdf.open(key)
    allow = a.get('images', [])
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            b = info['bbox']
            if (b[2] - b[0]) * (b[3] - b[1]) < 4:
                continue
            if not allow:
                return PERSON, {'reason': 'a placed picture'}
            pix = pymupdf.Pixmap(doc, info['xref'])
            if pix.n - pix.alpha >= 3:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., 0]
            ok = False
            for name in allow:
                try:
                    asset = base._load_gray(base.asset_path(a, name))
                except FileNotFoundError:
                    continue
                n, corners, state = base.find_asset(img, asset)
                if state == 'found':
                    ok = True
                    break
            if not ok:
                return PERSON, {'reason': 'a placed picture that is not the supplied file'}
    return 'pass', {'lines': len(layer.lines)}


def op_photo_proportions(path, a):
    """The supplied picture, found in the deliverable by feature matching, keeps its proportions: the fitted placement's
    aspect within 2% of the file's passes, 4% or more off fails, between goes to a person (a crop keeps proportions;
    only a stretch changes them). Flat artwork that feature matching misses is template-matched at its own
    proportions; a match there passes. Not found goes to a person."""
    asset = base._load_gray(base.asset_path(a, a['asset']))
    scenes = base._scenes(path)
    for scene in scenes:
        n, corners, state = base.find_asset(scene, asset)
        if state != 'found':
            continue
        ok, change = base._shape_ok(np.float32(corners), asset.shape, tol=0.02)
        ev = {'aspect_change': float(change)}
        if change >= 0.04:
            return 'fail', ev
        return ('pass' if ok else PERSON), ev
    # flat artwork with few features (a wordmark): template matching at the file's own proportions; a match at
    # FLAT_MIN_SCORE or more means its proportions are kept (a 2% stretch already scores under it)
    if base._flat_asset(a['asset']) or 'wordmark' in a['asset'] or 'mark' in a['asset']:
        flat = base._load_gray(base.asset_path(a, a['asset']), width=1600)
        for scene in scenes:
            score, corners = base.find_flat(scene, flat)
            if score >= base.FLAT_MIN_SCORE:
                return 'pass', {'template_score': round(score, 3), 'reason': 'found at its own proportions'}
    return PERSON, {'reason': 'supplied picture not found'}


def op_region_kept(path, a):
    """A region of a supplied photo (box in the file's own pixels) is kept as photographed: the photo is found by
    feature matching and the region mapped into the deliverable. Lying outside the shown picture passes (cropped
    away, not painted over); its shown part correlating with the file at 0.9 or more passes, under 0.5 fails (painted,
    cloned or generated over); between goes to a person."""
    import cv2
    asset = base._load_gray(base.asset_path(a, a['asset']))
    full = np.asarray(Image.open(base.asset_path(a, a['asset'])).convert('L'))
    sx, sy = asset.shape[1] / full.shape[1], asset.shape[0] / full.shape[0]
    x0, y0, x1, y1 = a['box']
    box = (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))
    pdf = path.suffix.lower() == '.pdf'
    for i, scene in enumerate(base._scenes(path)):
        n, corners, state = base.find_asset(scene, asset)
        if state != 'found':
            continue
        h, w = asset.shape
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
        shown = np.zeros(scene.shape, np.uint8)
        if pdf:
            k = base.RENDER_DPI / 72
            for b in r2._pdf_images(str(path)).get(i, []):
                shown[int(b[1] * k):int(b[3] * k), int(b[0] * k):int(b[2] * k)] = 255
        else:
            shown[:] = 255
        inv = np.linalg.inv(H)
        vis = cv2.warpPerspective(shown, inv, (w, h), flags=cv2.INTER_NEAREST) > 0
        back = cv2.warpPerspective(scene, inv, (w, h), flags=cv2.INTER_AREA)
        region = np.zeros((h, w), bool)
        region[box[1]:box[3], box[0]:box[2]] = True
        sel = region & vis
        if sel.sum() < 0.1 * region.sum():
            return 'pass', {'reason': 'the region is outside the shown picture'}
        x, y = asset[sel].astype(float), back[sel].astype(float)
        x, y = x - x.mean(), y - y.mean()
        ncc = float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9))
        ev = {'ncc': round(ncc, 3), 'shown_share': round(float(sel.sum() / region.sum()), 2)}
        if ncc >= 0.9:
            return 'pass', ev
        return ('fail' if ncc < 0.5 else PERSON), ev
    return PERSON, {'reason': 'supplied photo not found'}


def op_photo_natural(path, a):
    """The placed photo keeps its natural colour: compared with the supplied file (well inside the matched area,
    where the file has detail), each colour channel fits one gain and offset (a white-balance change); gains 0.85 to
    1.15 with offsets under 20 levels and a small leftover (median 8 levels) pass; colourfulness under a quarter of the
    file's (monochrome), or nearly every pixel on one colour line (a two-colour treatment), fails; anything else
    goes to a person."""
    pair = r3._photo_pair(path, a)
    if pair is None:
        return PERSON, {'reason': 'supplied photo not found'}
    src, back, m = pair
    if m.mean() < 0.15:
        return PERSON, {'reason': 'most of the photo is covered or cropped away'}
    import cv2
    lab_s = cv2.cvtColor(src.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(float)
    lab_d = cv2.cvtColor(np.clip(back, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(float)
    cs = np.hypot(lab_s[..., 1] - 128, lab_s[..., 2] - 128)[m].mean()
    cd = np.hypot(lab_d[..., 1] - 128, lab_d[..., 2] - 128)[m].mean()
    chroma = cd / max(cs, 1e-6)
    px = back[m].astype(float)
    c = px - px.mean(axis=0)
    sv = np.linalg.svd(c[:: max(1, len(c) // 20000)], compute_uv=False)
    line = sv[1] / max(sv[0], 1e-6)
    gains, offs, res = [], [], []
    for ch in range(3):
        g, o = np.polyfit(src[..., ch][m], back[..., ch][m], 1)
        gains.append(float(g))
        offs.append(float(o))
        res.append(float(np.median(np.abs(back[..., ch][m] - (g * src[..., ch][m] + o)))))
    ev = {'gain': [round(g, 3) for g in gains], 'offset': [round(o, 1) for o in offs], 'chroma_ratio': round(float(chroma), 2), 'leftover': round(max(res), 1)}
    if chroma < 0.25 or line < 0.03:
        return 'fail', ev
    if all(0.85 <= g <= 1.15 for g in gains) and max(abs(o) for o in offs) < 20 and max(res) <= 8 and chroma >= 0.6:
        return 'pass', ev
    return PERSON, dict(ev, reason='the photo\'s colour differs from the supplied file (a correction or a tint; a person decides)')


def op_inside_trim(path, a):
    """The whole named text is present as live text, every line of it inside the trim (TrimBox, or the page when
    none is set) by 0.5 pt, and its closing words are read by OCR on the rendered page (it is not hidden or clipped).
    The text missing its ending, or a line outside the trim, fails; the ending not read by OCR goes to a person."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    layer = base.pdf_layer(key)
    if not layer.readable:
        return PERSON, {'reason': 'no live text'}
    text = a['text']
    hits = [l for l in layer.lines if contains(l.text, text, False)] or base._span(layer, text, max_lines=14)
    if not hits:
        start = ' '.join(text.split()[:6])
        if contains(layer.text, start, False) or base._span(layer, start, max_lines=3):
            return 'fail', {'reason': 'the text starts but does not run to its end'}
        return PERSON, {'reason': 'text not found'}
    doc = pymupdf.open(key)
    page = doc[hits[0].page]
    trim = page.trimbox
    out = [l.text[:30] for l in hits if l.bbox[0] < trim.x0 - 0.5 or l.bbox[1] < trim.y0 - 0.5 or l.bbox[2] > trim.x1 + 0.5 or l.bbox[3] > trim.y1 + 0.5]
    if out:
        return 'fail', {'outside_trim': out[:3]}
    img = base.render_pdf(path, hits[0].page, 300)
    last = max(hits, key=lambda l: l.bbox[1])
    k = 300 / 72
    crop = img.crop((max(0, int(last.bbox[0] * k) - 10), max(0, int(last.bbox[1] * k) - 10), int(last.bbox[2] * k) + 10, int(last.bbox[3] * k) + 10))
    read = ' '.join(l.text for l in base.ocr_image(crop).lines)
    ending = [w for w in re.findall(r'[A-Za-z]{3,}', a.get('ending') or text)[-3:]]
    if all(contains(read, w, False) for w in ending):
        return 'pass', {'lines': len(hits)}
    return PERSON, {'reason': 'the closing words were not read on the rendered page', 'read': read[:60]}


def op_combined_pages(path, a):
    """Every page of a combined file measures width_mm x height_mm (within 0.5 mm) and shows its card unscaled: the
    page whose producer name matches an individual card renders like that card (mean difference under 3 levels at
    50 dpi). A page of another size fails; a page unlike its card goes to a person."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(str(path))
    cards = {}
    for name, rel in a['cards'].items():
        f = Path(a['_artifacts']) / rel
        if f.is_file():
            cards[name] = f
    bad, unsure = [], []
    for page in doc:
        w, h = page.trimbox.width * r2.PT_MM, page.trimbox.height * r2.PT_MM
        if abs(w - a['width_mm']) > 0.5 or abs(h - a['height_mm']) > 0.5:
            bad.append({'page': page.number + 1, 'mm': [round(w, 1), round(h, 1)]})
            continue
        text = page.get_text('text')
        own = [n for n in cards if contains(text, n, False)]
        if len(own) != 1:
            unsure.append({'page': page.number + 1, 'reason': 'card not identified'})
            continue
        x = np.asarray(base.render_pdf(path, page.number, 50)).astype(float)
        y = np.asarray(base.render_pdf(cards[own[0]], 0, 50)).astype(float)
        if x.shape != y.shape or np.abs(x - y).mean() >= 3:
            unsure.append({'page': page.number + 1, 'reason': 'differs from its card'})
    if bad:
        return 'fail', {'pages': bad[:4]}
    if unsure:
        return PERSON, {'reason': 'pages that need a look', 'pages': unsure[:4]}
    return 'pass', {'pages': len(doc)}


# ================================================================ placed pictures, wordmarks and type case


def _placed(path: Path, min_share=0.005):
    """Placed pictures of a PDF: (page, bbox, grey pixels of the image object, rgb pixels)."""
    import pymupdf
    doc = pymupdf.open(str(path))
    out = []
    for page in doc:
        area = page.rect.width * page.rect.height
        for info in page.get_image_info(xrefs=True):
            b = info['bbox']
            if not info.get('xref') or (b[2] - b[0]) * (b[3] - b[1]) < min_share * area:
                continue
            pix = pymupdf.Pixmap(doc, info['xref'])
            if pix.n - pix.alpha != 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
            rgb = arr[..., :3].astype(float)
            if pix.alpha:
                # a cut-out (a wordmark with transparency) keeps its letter shapes: composite it on a ground of the
                # opposite tone to its ink, as the colour under its transparent parts is undefined
                al = arr[..., 3:4].astype(float) / 255
                lum = (rgb @ [0.299, 0.587, 0.114])[al[..., 0] > 0.5]
                ground = 0.0 if len(lum) and lum.mean() > 128 else 255.0
                rgb = rgb * al + ground * (1 - al)
            rgb = rgb.astype(np.uint8)
            gray = (rgb.astype(float) @ [0.299, 0.587, 0.114]).astype(np.uint8)
            out.append((page.number, tuple(b), gray, rgb))
    return out


def _is_delivered_render(gray, a):
    """The placed picture is a render of one of the delivered files (a poster shown in a deck), not a photograph."""
    for rel in a.get('deliverables', []):
        f = Path(a['_artifacts']) / rel
        if f.is_file():
            n, corners, state = base.find_asset(gray, _render_gray(str(f)))
            if state == 'found':
                return True
    return False


def _which(gray, a, names):
    """The supplied file a picture is (feature match of the file inside the picture, or of the picture inside it)."""
    for name in names:
        try:
            asset = base._load_gray(base.asset_path(a, name))
        except FileNotFoundError:
            continue
        n, corners, state = base.find_asset(gray, asset)
        if state == 'found':
            return name, corners, asset
    return None, None, None


@functools.lru_cache(maxsize=8)
def _render_gray(key: str, dpi: int = 40):
    return np.asarray(base.render_pdf(Path(key), 0, dpi).convert('L'))


def op_images_are(path, a):
    """Every placed picture (half a percent of the page or more) is one of the supplied files (assets), found by
    feature matching in the picture, or a render of one of the delivered files (deliverables). All found passes; no
    picture passes; any other goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    other = []
    for page, b, gray, rgb in _placed(path):
        name, corners, asset = _which(gray, a, a.get('assets', []))
        if name:
            continue
        ok = False
        for rel in a.get('deliverables', []):
            f = Path(a['_artifacts']) / rel
            if f.is_file():
                n, corners, state = base.find_asset(gray, _render_gray(str(f)))
                if state == 'found':
                    ok = True
                    break
        if not ok:
            other.append({'page': page + 1, 'box': [round(v) for v in b]})
    if other:
        return PERSON, {'reason': 'a placed picture that is not a supplied or delivered file', 'pictures': other[:3]}
    return 'pass', {'reason': 'every placed picture is a supplied or delivered file'}


def _photo_region(path: Path, a):
    """The photograph on an image: its supplied archive file found in the image (box), else the photo-like area
    (textured or two-colour treatment) when it covers 1% or more. Returns (box or None, mask)."""
    rgb = r3._pixels(str(path))
    m = _photos(path, dict(a, photos=[]))
    for name in a.get('assets', []):
        try:
            page, box, state = r2._asset_box(path, a, name, 0)
        except FileNotFoundError:
            continue
        if box is not None:
            return name, box, m
    return None, None, m


def op_photo_two_colour(path, a):
    """A photograph is reproduced in two palette colours: its pixels (the placed image object in a PDF; on an image
    the photo area, type and marks left out) lie within 24 levels of the blend line between one pair of palette
    colours: 98% or more passes; under 80% for every pair (full colour) fails; between goes to a person. Supplied
    marks (exclude assets) are not photographs. No photograph: a pass."""
    hexes = a['hexes']
    pairs = [(x, y) for i, x in enumerate(hexes) for y in hexes[i + 1:]]
    def share_on(px):
        px = px[:: max(1, len(px) // 40000)].astype(float)
        best = (0.0, None)
        for x, y in pairs:
            p0, p1 = r3._hex_rgb(x).astype(float), r3._hex_rgb(y).astype(float)
            d = p1 - p0
            t = np.clip(((px - p0) @ d) / (d @ d), 0, 1)
            resid = np.abs(px - (p0 + t[:, None] * d)).max(axis=1)
            share = float((resid <= 24).mean())
            if share > best[0]:
                best = (share, (x, y))
        return best
    results = []
    if path.suffix.lower() == '.pdf':
        for page, b, gray, rgb in _placed(path, 0.01):
            name, corners, asset = _which(gray, a, a.get('exclude', []))
            if name or _is_delivered_render(gray, a):
                continue
            results.append(share_on(rgb.reshape(-1, 3)))
    else:
        rgb = r3._pixels(str(path))
        m = _photos(path, dict(a, photos=a.get('assets', []))) & ~_text_boxes(path)
        for b in _asset_boxes(path, a, a.get('exclude', [])):
            x0, y0, x1, y1 = (int(round(v)) for v in b)
            m[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = False
        if m.mean() < 0.01:
            flat = r3._flat(rgb, 2).mean()
            return ('pass', {'reason': 'no photograph on the image'}) if flat >= 0.85 else (PERSON, {'reason': 'photo area not found'})
        results.append(share_on(rgb[m]))
    if not results:
        return 'pass', {'reason': 'no photograph placed'}
    worst = min(results, key=lambda r: r[0])
    ev = {'on_two_colour_line': round(worst[0], 3), 'pair': worst[1]}
    if worst[0] >= 0.98:
        return 'pass', ev
    return ('fail' if worst[0] < 0.8 else PERSON), ev


def _pair_share(px, hexes):
    """The palette pair whose blend line holds the most of the pixels (within 24 levels), and that share."""
    pairs = [(x, y) for i, x in enumerate(hexes) for y in hexes[i + 1:]]
    px = px[:: max(1, len(px) // 40000)].astype(float)
    best = (0.0, None)
    for x, y in pairs:
        p0, p1 = r3._hex_rgb(x).astype(float), r3._hex_rgb(y).astype(float)
        d = p1 - p0
        t = np.clip(((px - p0) @ d) / (d @ d), 0, 1)
        share = float((np.abs(px - (p0 + t[:, None] * d)).max(axis=1) <= 24).mean())
        if share > best[0]:
            best = (share, (x, y))
    return best


def _photo_pixels(path: Path, a):
    """A post's photograph pixels (photo area, type and marks left out); None when the image has no photograph
    (mostly flat colour with no photo area); [] when a photo area cannot be told."""
    rgb = r3._pixels(str(path))
    m = _photos(path, dict(a, photos=a.get('assets', []))) & ~_text_boxes(path)
    for b in _asset_boxes(path, a, a.get('exclude', [])):
        x0, y0, x1, y1 = (int(round(v)) for v in b)
        m[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = False
    if m.mean() < 0.01:
        return None if r3._flat(rgb, 2).mean() >= 0.85 else []
    return rgb[m]


def op_photo_pair_same(path, a):
    """The photograph on this image is in the same two palette colours as on the reference image: each photo's pixels
    are fitted to every palette pair's blend line (24 levels); both on one pair (98% or more) and the same pair passes;
    both on a pair but different pairs, or this one in full colour (under 80% on every pair) against a two-colour
    reference, fails; no photograph on either passes; anything else goes to a person."""
    ref = Path(a['_artifacts']) / a['deliverable']
    if not ref.is_file() or path.suffix.lower() == '.pdf':
        return PERSON, {'reason': 'reference image not available'}
    mine, theirs = _photo_pixels(path, a), _photo_pixels(ref, a)
    if mine is None and theirs is None:
        return 'pass', {'reason': 'no photograph on either'}
    if mine is None or theirs is None or not len(mine) or not len(theirs):
        return PERSON, {'reason': 'a photograph on only one of them, or not found'}
    s1, p1 = _pair_share(mine, a['hexes'])
    s2, p2 = _pair_share(theirs, a['hexes'])
    ev = {'this': [round(s1, 3), p1], 'reference': [round(s2, 3), p2]}
    if s1 >= 0.98 and s2 >= 0.98:
        return ('pass' if set(p1) == set(p2) else 'fail'), ev
    if s1 < 0.8 and s2 >= 0.98:
        return 'fail', ev
    return PERSON, ev


def op_photo_as_shot(path, a):
    """Every performance photograph is used as shot: its supplied archive file is found by feature matching, the
    shown picture lies inside the file's frame (not extended past its edges by more than 1%), and every cell of a
    4 x 4 grid over the shown part correlates with the file at 0.8 or more (correlation ignores the two-colour tone
    mapping). Extended past the edges fails; a low cell (something added or removed) or a photograph not found goes
    to a person. No photograph: a pass."""
    import cv2
    def check(gray, box_shown=None):
        name, corners, asset = _which(gray, a, a['assets'])
        if not name:
            return PERSON, {'reason': 'photograph not matched to an archive frame'}
        h, w = asset.shape
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
        inv = np.linalg.inv(H)
        gh, gw = gray.shape
        shown = np.zeros(gray.shape, np.uint8)
        if box_shown is None:
            shown[:] = 255
        else:
            x0, y0, x1, y1 = box_shown
            shown[y0:y1, x0:x1] = 255
        pts = cv2.perspectiveTransform(np.float32([[[0, 0]], [[gw, 0]], [[gw, gh]], [[0, gh]]]) if box_shown is None else
                                       np.float32([[[box_shown[0], box_shown[1]]], [[box_shown[2], box_shown[1]]], [[box_shown[2], box_shown[3]]], [[box_shown[0], box_shown[3]]]]), inv).reshape(-1, 2)
        if (pts[:, 0].min() < -0.01 * w or pts[:, 1].min() < -0.01 * h or pts[:, 0].max() > 1.01 * w or pts[:, 1].max() > 1.01 * h):
            return 'fail', {'asset': name, 'reason': 'the picture extends past the supplied frame'}
        back = cv2.warpPerspective(gray, inv, (w, h), flags=cv2.INTER_AREA)
        vis = cv2.warpPerspective(shown, inv, (w, h), flags=cv2.INTER_NEAREST) > 0
        ys, xs = np.where(vis)
        low = []
        for gy in range(4):
            for gx in range(4):
                y0 = ys.min() + (ys.max() - ys.min()) * gy // 4
                y1 = ys.min() + (ys.max() - ys.min()) * (gy + 1) // 4
                x0 = xs.min() + (xs.max() - xs.min()) * gx // 4
                x1 = xs.min() + (xs.max() - xs.min()) * (gx + 1) // 4
                cell = vis[y0:y1, x0:x1]
                if cell.mean() < 0.5:
                    continue
                p, q = asset[y0:y1, x0:x1][cell].astype(float), back[y0:y1, x0:x1][cell].astype(float)
                if p.std() < 6:
                    continue
                p, q = p - p.mean(), q - q.mean()
                ncc = float((p * q).sum() / (np.sqrt((p * p).sum() * (q * q).sum()) + 1e-9))
                if ncc < 0.8:
                    low.append((gy, gx, round(ncc, 2)))
        if low:
            return PERSON, {'asset': name, 'reason': 'parts differ from the supplied frame', 'cells': low[:4]}
        return 'pass', {'asset': name}
    results = []
    if path.suffix.lower() == '.pdf':
        for page, b, gray, rgb in _placed(path, 0.01):
            name, corners, asset = _which(gray, a, a.get('exclude', []))
            if name or _is_delivered_render(gray, a):
                continue
            results.append(check(gray) if not a.get('match_only') else (('pass', {}) if _which(gray, a, a['assets'])[0] else (PERSON, {'reason': 'photograph not matched to an archive frame'})))
    else:
        rgb = r3._pixels(str(path))
        gray = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
        if a.get('match_only'):
            m = _photos(path, dict(a, photos=[]))
            if m.mean() < 0.01 and r3._flat(rgb, 2).mean() >= 0.85:
                return 'pass', {'reason': 'no photograph on the image'}
            return ('pass', {'found': True}) if _which(gray, a, a['assets'])[0] else (PERSON, {'reason': 'photograph not matched to an archive frame'})
        m = _photos(path, dict(a, photos=a['assets']))
        if m.mean() < 0.01:
            return ('pass', {'reason': 'no photograph on the image'}) if r3._flat(rgb, 2).mean() >= 0.85 else (PERSON, {'reason': 'photo area not found'})
        ys, xs = np.where(m)
        results.append(check(gray, (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)))
    if not results:
        return 'pass', {'reason': 'no photograph placed'}
    for st in ('fail', PERSON):
        hit = [ev for s_, ev in results if s_ == st]
        if hit:
            return st, hit[0]
    return 'pass', {'photographs': len(results)}


def op_clipped_flat(path, a):
    """Where a supplied frame with clipped white (assets) appears, its clipped area (the file's pixels at 250 or more,
    eroded 5 px) stays flat: mapped into the deliverable and blurred to remove grain, its tone varies by no more
    than 8 levels (standard deviation) passes; 25 or more with edges fails (detail painted in); between goes to a
    person. Neither file used: a pass."""
    import cv2
    pictures = [(gray, None) for page, b, gray, rgb in _placed(path, 0.01) if not _is_delivered_render(gray, a)] if path.suffix.lower() == '.pdf' else \
        [(cv2.cvtColor(r3._pixels(str(path)).astype(np.uint8), cv2.COLOR_RGB2GRAY), None)]
    seen, verdicts = 0, []
    for gray, _ in pictures:
        for name in a['assets']:
            try:
                full = np.asarray(Image.open(base.asset_path(a, name)).convert('L'))
            except FileNotFoundError:
                continue
            asset = base._load_gray(base.asset_path(a, name))
            n, corners, state = base.find_asset(gray, asset)
            if state != 'found':
                continue
            seen += 1
            clip = cv2.resize((full >= 250).astype(np.uint8), (asset.shape[1], asset.shape[0]), interpolation=cv2.INTER_NEAREST)
            clip = cv2.erode(clip, np.ones((5, 5), np.uint8)) > 0
            h, w = asset.shape
            H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
            back = cv2.warpPerspective(gray, np.linalg.inv(H), (w, h), flags=cv2.INTER_AREA).astype(np.float32)
            valid = cv2.warpPerspective(np.full(gray.shape, 255, np.uint8), np.linalg.inv(H), (w, h), flags=cv2.INTER_NEAREST) > 0
            sel = clip & valid
            if sel.sum() < 200:
                continue
            blur = cv2.GaussianBlur(back, (0, 0), 3)
            sd = float(blur[sel].std())
            edges = float((cv2.Canny(blur.astype(np.uint8), 30, 90) > 0)[sel].mean())
            verdicts.append(('pass' if sd <= 8 else 'fail' if sd >= 25 and edges > 0.02 else PERSON, {'asset': name, 'tone_sd': round(sd, 1)}))
    if not seen:
        return 'pass', {'reason': 'neither frame used'}
    for st in ('fail', PERSON):
        hit = [ev for s_, ev in verdicts if s_ == st]
        if hit:
            return st, hit[0]
    return 'pass', {'checked': len(verdicts)}


DISTINCT_LOWER = set('abdefghilmnqrty')     # lowercase letters whose shape differs from their capital


def op_caps(path, a):
    """The selected text is set in capitals: texts (largest_only: only the largest occurrences) or patterns. PDF live
    text with a lowercase letter fails; on images, two or more lowercase letters whose shape differs from their
    capital (a, b, d, e, f, g, h, i, l, m, n, q, r, t, y) read confidently fail; one goes to a person (OCR may misread
    case). Not found goes to a person."""
    layer = base.pdf_layer(str(path)) if path.suffix.lower() == '.pdf' else _ocr(str(path), -1)
    lines = [l for l in layer.lines if base._real(l)]
    picks = [l for l in lines if any(contains(l.text, t, False) for t in a.get('texts', [])) or any(r2._rxs(p, l.text) for p in a.get('patterns', []))]
    if a.get('texts') and not picks:
        picks = [l for t in a['texts'] for l in base._span(layer, t)]
    if a.get('largest_only') and picks:
        top = max(l.size for l in picks)
        picks = [l for l in picks if l.size >= 0.8 * top]
    if not picks:
        return PERSON, {'reason': 'text not found'}
    pdf = layer.source == 'pdf'
    for l in picks:
        seg = l.text
        for t in a.get('texts', []):
            if contains(l.text, t, False):
                seg = base._segment(l.text, t)
        lower = re.findall(r'[a-z]', seg)
        if pdf and lower:
            return 'fail', {'line': l.text}
        sure = [c for c in lower if c in DISTINCT_LOWER]
        if not pdf and len(sure) >= 2 and l.conf >= OCR_GOOD_CONF:
            return 'fail', {'line': l.text}
        if not pdf and lower:
            return PERSON, {'reason': 'a letter read in lower case', 'line': l.text}
    return 'pass', {'lines': len(picks)}


def op_title_stack(path, a):
    """The series title is a compact stack: its words (top, bottom) on two lines, the bottom directly under the top,
    baselines no more than 0.9 times the type size apart (PDF). Both words on one line fails (PDF, or OCR read
    confidently); a looser stack, or an image, goes to a person."""
    pdf = path.suffix.lower() == '.pdf'
    layer = base.pdf_layer(str(path)) if pdf else _ocr(str(path), -1)
    lines = [l for l in layer.lines if base._real(l)]
    tops = [l for l in lines if contains(l.text, a['top'], False)]
    bottoms = [l for l in lines if contains(l.text, a['bottom'], False)]
    if not tops or not bottoms:
        return PERSON, {'reason': 'title not found'}
    big = max(l.size for l in tops + bottoms)
    one = [l for l in tops if contains(l.text, a['bottom'], False) and l.size >= 0.8 * big]
    if one:
        return ('fail' if pdf or one[0].conf >= OCR_GOOD_CONF else PERSON), {'one_line': one[0].text}
    pairs = [(t, b) for t in tops for b in bottoms if b.bbox[1] > t.bbox[1] and r2._xoverlap(t.bbox, b.bbox) and t.size >= 0.8 * big]
    if not pairs:
        return PERSON, {'reason': 'title lines not found one over the other'}
    if not pdf:
        return PERSON, {'reason': 'stacked; the leading is read from a PDF'}
    t, b = min(pairs, key=lambda p: p[1].bbox[1] - p[0].bbox[1])
    yt, st_ = _baseline(str(path), t)
    yb, sb = _baseline(str(path), b)
    ev = {'baseline_gap_pt': round(yb - yt, 1), 'size_pt': round(max(st_, sb), 1)}
    return ('pass' if yb - yt <= 0.9 * max(st_, sb) + 0.5 else PERSON), ev


def op_mark_not_retyped(path, a):
    """A wordmark uses the supplied letter shapes: the supplied file found (feature or template match) passes; not
    found, with the act name set a second time as live text in another font than its billing line, fails (retyped);
    anything else goes to a person."""
    pdf = path.suffix.lower() == '.pdf'
    page, box, state = r2._asset_box(path, a, a['asset'], None if pdf else 0)
    if box is not None:
        return 'pass', {'found': a['asset']}
    if pdf:
        layer = base.pdf_layer(str(path))
        hits = [l for l in layer.lines if contains(l.text, a['text'], False)]
        fonts = {base._font_parts(f)[0] for l in hits for _, f, _, _ in l.fonts}
        if len(hits) >= 2 and len(fonts) >= 2:
            return 'fail', {'reason': 'the name is set again in another font', 'fonts': sorted(fonts)}
    return PERSON, {'reason': 'supplied wordmark not found (it may be absent or redrawn)'}


def op_mark_beside(path, a):
    """Each placement of the supplied lettering (assets: the wordmark file and the photo whose shirt carries it)
    stands with its own act: the nearest act-name line (by distance between centres) is that act. Beside another
    named act (forbid) fails; no placement passes; anything else goes to a person. text_absent: on an image the
    lettering's words read nowhere (OCR confident) and no supplied placement found passes; found fails."""
    pdf = path.suffix.lower() == '.pdf'
    layer = base.pdf_layer(str(path)) if pdf else _ocr(str(path), -1)
    acts = [l for l in layer.lines if any(contains(l.text, x, False) for x in a['acts'])]
    found, bad, unsure = 0, [], []
    for name in a['assets']:
        try:
            page, box, state = r2._asset_box(path, a, name, None if pdf else 0)
        except FileNotFoundError:
            continue
        if box is None:
            if state == 'unsure':
                unsure.append(name)
            continue
        found += 1
        if a.get('text_absent'):
            return 'fail', {'found': name}
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        near = min((l for l in acts if l.page == (page or 0)), key=lambda l: abs((l.bbox[1] + l.bbox[3]) / 2 - cy) + 0.25 * abs((l.bbox[0] + l.bbox[2]) / 2 - cx), default=None)
        if near is None:
            unsure.append(name)
        elif contains(near.text, a['forbid'], False):
            bad.append({'asset': name, 'beside': near.text})
        elif not contains(near.text, a['own'], False):
            unsure.append(name)
    if a.get('text_absent'):
        words = [w for w in a['words'] if contains(layer.text, w, False)]
        if words:
            return ('fail' if pdf or layer.confident else PERSON), {'read': words}
        if unsure or not (pdf or layer.confident):
            return PERSON, {'reason': 'not read clearly enough to rule it out'}
        return 'pass', {'reason': 'no such lettering'}
    if bad:
        return 'fail', {'placements': bad}
    if unsure:
        return PERSON, {'reason': 'a placement that needs a look', 'assets': unsure}
    return 'pass', {'placements': found}


def op_mark_letters(path, a):
    """Every letter of a supplied wordmark is complete where it is placed: the file's ink is split into letters (ink
    pieces grouped by overlapping columns), the placement found by feature or template matching, and each letter's
    ink checked in the deliverable (a pixel 40 or more levels from the ground round the mark counts as ink). Every
    letter keeping 90% of its ink passes; one under 50% fails; between, or not found, goes to a person."""
    import cv2
    pdf = path.suffix.lower() == '.pdf'
    page, box, state = r2._asset_box(path, a, a['asset'], None if pdf else 0)
    if box is None:
        return PERSON, {'reason': 'wordmark not found'} if not a.get('optional_absent') else (PERSON, {'reason': 'wordmark not found'})
    im = Image.open(base.asset_path(a, a['asset'])).convert('RGBA')
    alpha = np.asarray(im)[..., 3] > 128
    ys, xs = np.where(alpha)
    alpha = alpha[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    rgb = np.asarray(base.render_pdf(path, page or 0, 300)).astype(np.int16) if pdf else r3._pixels(str(path))
    k = 300 / 72 if pdf else 1
    x0, y0, x1, y1 = (int(round(v * k)) for v in box)
    crop = rgb[max(0, y0):y1, max(0, x0):x1]
    if crop.size == 0:
        return PERSON, {'reason': 'placement at the edge'}
    th, tw = crop.shape[:2]
    tmpl = cv2.resize(alpha.astype(np.uint8), (tw, th), interpolation=cv2.INTER_NEAREST) > 0
    ring = np.concatenate([rgb[max(0, y0 - 6):max(0, y0 - 2), max(0, x0):x1].reshape(-1, 3), rgb[y1 + 2:y1 + 6, max(0, x0):x1].reshape(-1, 3)])
    if not len(ring):
        return PERSON, {'reason': 'ground not readable'}
    values, counts = np.unique(ring // 4, axis=0, return_counts=True)
    ground = values[counts.argmax()] * 4 + 2
    ink = np.abs(crop - ground).max(axis=2) >= 40
    cols = tmpl.any(axis=0)
    letters, start = [], None
    for x, c in enumerate(list(cols) + [False]):
        if c and start is None:
            start = x
        elif not c and start is not None:
            if x - start >= 3:
                letters.append((start, x))
            start = None
    shares = []
    for s0, s1 in letters:
        t = tmpl[:, s0:s1]
        if t.sum() < 20:
            continue
        got = (ink[:, s0:s1] & cv2.dilate(t.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool) & t).sum() / t.sum()
        shares.append(round(float(got), 2))
    if not shares:
        return PERSON, {'reason': 'letters not separated'}
    ev = {'letters': len(shares), 'lowest_share': min(shares)}
    if min(shares) >= 0.9:
        return 'pass', ev
    return ('fail' if min(shares) < 0.5 else PERSON), ev


def op_chart_scale(path, a):
    """A bar chart keeps a truthful scale: the chart's bars (filled shapes on a shared baseline, as many as values)
    read left to right have heights in proportion to the values: every ratio within 2% of their median passes, any
    5% or more off fails, between goes to a person; bars not found go to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    vals = a['values']
    for info in _pdf_pages(str(path)):
        uses = [dict(kind='area', fill=True, box=(d['rect'].x0, d['rect'].y0, d['rect'].x1, d['rect'].y1), colour=base._hex(d['fill']))
                for d in info['drawings'] if d.get('fill') is not None]
        groups = {}
        for u in uses:
            if _area(u['box']) <= 0.03 * info['W'] * info['H']:
                groups.setdefault((u['colour'], round(u['box'][3] / 1.5)), []).append(u)
        for g in groups.values():
            if len(g) != len(vals):
                continue
            hs = [u['box'][3] - u['box'][1] for u in sorted(g, key=lambda u: u['box'][0])]
            ratios = [h / v for h, v in zip(hs, vals)]
            med = float(np.median(ratios))
            off = max(abs(r - med) / med for r in ratios)
            ev = {'heights_pt': [round(h, 1) for h in hs], 'worst_off_pct': round(100 * off, 1)}
            if off <= 0.02:
                return 'pass', ev
            return ('fail' if off >= 0.05 else PERSON), ev
    return PERSON, {'reason': 'chart bars not found'}


def op_numbers_from(path, a):
    """Every figure in the PDF's live text appears in the supplied sources (text and CSV files, plus extra values):
    all found passes; any other goes to a person to judge (never a fail)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    pool = set(str(x) for x in a.get('extra', []))
    for name in a['sources']:
        try:
            txt = base.asset_path(a, name).read_text(errors='replace')
        except FileNotFoundError:
            return PERSON, {'reason': f'source not available: {name}'}
        pool |= {n.lstrip('0') or '0' for n in re.findall(r'\d+', txt)}
    layer = base.pdf_layer(str(path))
    found = {n.lstrip('0') or '0' for n in re.findall(r'\d+', layer.text)}
    other = sorted(found - pool)
    if other:
        return PERSON, {'reason': 'figures not found in the sources', 'figures': other[:8]}
    return 'pass', {'figures': len(found)}


def op_text_anywhere(path, a):
    """Each expected pattern is found in the PDF's live text or, failing that, by OCR of its rendered pages: all found
    passes; one found in neither, with every page read confidently, fails; otherwise a person."""
    layer = base.pdf_layer(str(path))
    hay = layer.text
    missing = [p for p in a['expected'] if not re.search(p, canon(hay), re.I)]
    if not missing:
        return 'pass', {'found': a['expected']}
    import pymupdf
    confident, more = True, ''
    for n in range(len(pymupdf.open(str(path)))):
        lay = base.ocr_image(base.render_pdf(path, n, 150))
        confident = confident and lay.confident
        more += ' ' + ' '.join(l.text for l in lay.lines)
    still = [p for p in missing if not re.search(p, canon(more), re.I)]
    if not still:
        return 'pass', {'found': a['expected']}
    return ('fail' if confident else PERSON), {'missing': still}


def op_artwork_only(path, a):
    """Named texts are live type and the only artwork is supplied: every named text found as live text, every placed
    picture a supplied file (feature match), and every drawing a rectangle, straight line or circle (no lettering or
    illustration drawn as curves). All true passes; anything else goes to a person (never a fail)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = base.pdf_layer(str(path))
    missing = [t for t in a['texts'] if not any(contains(l.text, t, False) for l in layer.lines)]
    if missing:
        return PERSON, {'reason': 'not live type', 'texts': missing}
    for page, b, gray, rgb in _placed(path):
        name, corners, asset = _which(gray, a, a['assets'])
        if not name:
            return PERSON, {'reason': 'a placed picture that is not a supplied file', 'box': [round(v) for v in b]}
    for info in _pdf_pages(str(path)):
        for d in info['drawings']:
            kinds = {it[0] for it in d.get('items') or []}
            if kinds - {'l', 're', 'qu'}:
                r = d['rect']
                if not (abs(r.width - r.height) <= 0.05 * max(r.width, r.height) and kinds <= {'c'}):
                    return PERSON, {'reason': 'curved artwork drawn on the page'}
    return 'pass', {'texts': a['texts']}


def op_soft_edges(path, a):
    """No soft colour on an image (photographs left out): anti-aliased edges between flat colours are at most 3 px
    wide; a band of slowly changing colour (each step 12 levels or less) 4 px or more from any flat pixel, over
    200 px in one piece, is a gradient, glow, soft shadow or blur (a fail); transparent pixels inside the artwork (alpha between 1 and 254, 3 px or more from
    the edge) fail too."""
    import cv2
    rgb, alpha = _rgba(path)
    keep = ~_photos(path, a)
    flat = r3._flat(rgb, 2)
    dist = cv2.distanceTransform((~flat).astype(np.uint8), cv2.DIST_L2, 3)
    # smooth: every step to a neighbour 12 levels or less (a gradient, glow or blur changes slowly; dense small type
    # jumps between ink and ground, so its tight clusters are not soft)
    smooth = np.ones(rgb.shape[:2], bool)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        smooth &= (np.abs(np.roll(np.roll(rgb, dy, 0), dx, 1) - rgb) <= 12).all(axis=2)
    soft = (dist > 3.5) & smooth & keep
    if alpha is not None:
        soft &= alpha >= OPAQUE
        # outside the image counts as transparent, so an edge running along the image border is not 'inside'
        inner = cv2.erode((alpha > 0).astype(np.uint8), np.ones((7, 7), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0) > 0
        part = inner & (alpha < 250) & (alpha > 0)
        # an area of see-through ink, not the anti-aliasing of a hairline gap: a piece of 50 px or more, at least
        # 6 px across both ways
        areas = [st for _, st in r3._components(part, 50) if min(st[2], st[3]) >= 6]
        if areas:
            return 'fail', {'reason': 'partly transparent ink inside the artwork', 'pixels': int(sum(st[4] for st in areas))}
    comps = r3._components(soft, 200)
    if comps:
        return 'fail', {'soft_areas_px': [int(st[4]) for _, st in comps[:4]]}
    return 'pass', {'reason': 'edges no wider than 3 px'}


# ================================================================ sticker files: SVG structure, proofs, production sheet

MM = 72 / 25.4


def op_svg_viewbox(path, a):
    """The SVG's root declares a viewBox of four numbers with positive width and height."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    vb = r2._svg_root(path).get('viewBox')
    nums = re.findall(r'-?[\d.]+(?:e-?\d+)?', vb or '')
    ok = len(nums) == 4 and float(nums[2]) > 0 and float(nums[3]) > 0
    return ('pass' if ok else 'fail'), {'viewBox': vb}


def _cut_groups(root):
    out = []
    for parent in root.iter():
        for e in parent:
            if r2._is_cut_layer(e, top_level=parent is root):
                out.append(e)
    return out


def _subpaths(d):
    """Subpaths of an SVG path's d, each with whether it closes (Z, or ending where it began)."""
    parts = [x for x in re.split(r'(?=[Mm])', d or '') if x.strip()]
    out = []
    for part in parts:
        nums = [float(v) for v in re.findall(r'-?[\d.]+(?:e-?\d+)?', part)]
        closed = bool(re.search(r'[Zz]\s*$', part.strip())) or (len(nums) >= 4 and abs(nums[0] - nums[-2]) < 1e-3 and abs(nums[1] - nums[-1]) < 1e-3)
        out.append(closed)
    return out


def op_svg_cut_file(path, a):
    """A separate cut-contour SVG: mode "name": its cut path sits in a group whose id or inkscape:label is exactly
    CutContour; mode "only": it holds stroked paths with no fill and nothing else (no text, image or filled shape);
    mode "one": exactly one path with one closed subpath, whose box encloses the delivered artwork's ink in the same
    millimetre coordinates (both files' viewBox mapped to mm)."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    root = r2._svg_root(path)
    loc = r2._local
    shapes = ('path', 'circle', 'ellipse', 'rect', 'polygon', 'polyline', 'line')
    if a['mode'] == 'name':
        groups = [e for e in root.iter() if loc(e.tag) == 'g' and any(e.get(k) == 'CutContour' for k in e.attrib if loc(k) in ('id', 'label'))]
        paths_in = [x for g in groups for x in g.iter() if loc(x.tag) in shapes]
        all_paths = [x for x in root.iter() if loc(x.tag) in shapes]
        if groups and paths_in and len(paths_in) == len(all_paths):
            return 'pass', {'group': 'CutContour'}
        return 'fail', {'reason': 'the cut path is not in a group named exactly CutContour'}
    if a['mode'] == 'only':
        bad = []
        for e in root.iter():
            t = loc(e.tag)
            if t in ('text', 'image', 'use', 'foreignObject'):
                bad.append(t)
            elif t in shapes:
                style = e.get('style') or ''
                fill = (re.search(r'fill\s*:\s*([^;]+)', style).group(1).strip() if re.search(r'fill\s*:', style) else e.get('fill', 'black')).lower()
                stroke = (re.search(r'stroke\s*:\s*([^;]+)', style).group(1).strip() if re.search(r'stroke\s*:', style) else e.get('stroke', 'none')).lower()
                if fill not in ('none', 'transparent') or stroke in ('none', ''):
                    bad.append(f'{t} filled or unstroked')
        return ('fail', {'not_cut_only': bad[:4]}) if bad else ('pass', {'reason': 'stroked paths only'})
    paths = [e for e in root.iter() if loc(e.tag) in shapes]
    if len(paths) != 1:
        return 'fail', {'paths': len(paths)}
    sub = _subpaths(paths[0].get('d')) if loc(paths[0].tag) == 'path' else [True]
    if len(sub) != 1 or not sub[0]:
        return 'fail', {'subpaths': len(sub), 'closed': sub}
    art = Path(a['_artifacts']) / a['deliverable']
    if not art.is_file():
        return PERSON, {'reason': 'the artwork file is not available'}
    def ink_box_mm(svg_path, text=None):
        rt = r2._svg_root(svg_path)
        mm = r2._doc_mm(rt)
        vb = [float(v) for v in re.split(r'[\s,]+', (rt.get('viewBox') or '').strip()) if v]
        if not mm or len(vb) != 4:
            return None
        arr = r2._render_svg_text(text or r2._svg_without_cut(svg_path), 1200)
        ys, xs = np.where(arr[..., 3] > 16)
        if not len(xs):
            return None
        kx, ky = mm[0] / arr.shape[1], mm[1] / arr.shape[0]
        ox, oy = vb[0] * mm[0] / vb[2], vb[1] * mm[1] / vb[3]
        return (ox + xs.min() * kx, oy + ys.min() * ky, ox + (xs.max() + 1) * kx, oy + (ys.max() + 1) * ky)
    cut = ink_box_mm(path, path.read_text())
    ink = ink_box_mm(art)
    if not cut or not ink:
        return PERSON, {'reason': 'sizes not in millimetres in both files'}
    ok = cut[0] <= ink[0] + 0.05 and cut[1] <= ink[1] + 0.05 and cut[2] >= ink[2] - 0.05 and cut[3] >= ink[3] - 0.05
    return ('pass' if ok else 'fail'), {'cut_box_mm': [round(v, 2) for v in cut], 'art_box_mm': [round(v, 2) for v in ink]}


def op_svg_solid(path, a):
    """SVG artwork (any separate cut layer left out) is solid: no opacity, fill-opacity or stroke-opacity under 1,
    no gradient, pattern or filter, no mix-blend-mode, and every colour a palette hex (attributes, styles and CSS
    rules read, and the rendered artwork's solid pixels checked, so a colour set through a class is caught)."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    root = r2._svg_root(path)
    cut = {id(x) for g in _cut_groups(root) for x in g.iter()}
    text = path.read_text()
    bad = []
    for e in root.iter():
        if id(e) in cut:
            continue
        t = r2._local(e.tag)
        if t in ('linearGradient', 'radialGradient', 'pattern', 'filter', 'mask'):
            bad.append(t)
        style = (e.get('style') or '') + ';' + ';'.join(f'{r2._local(k)}:{v}' for k, v in e.attrib.items())
        for m in re.finditer(r'(?:^|;)\s*((?:fill-|stroke-)?opacity)\s*:\s*([\d.]+)', style):
            if float(m.group(2)) < 0.999:
                bad.append(f'{m.group(1)} {m.group(2)}')
        if re.search(r'mix-blend-mode|filter\s*:\s*url|url\(#', style):
            bad.append('blend, filter or paint server')
    css = ' '.join(x.text or '' for x in root.iter() if r2._local(x.tag) == 'style')
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', css)
    for m in re.finditer(r'opacity\s*:\s*([\d.]+)', css):
        if float(m.group(1)) < 0.999:
            bad.append(f'css opacity {m.group(1)}')
    if re.search(r'gradient|mix-blend-mode|filter\s*:', css):
        bad.append('css gradient, blend or filter')
    if bad:
        return 'fail', {'not_solid': sorted(set(bad))[:5]}
    arr = r2._render_svg_text(r2._svg_without_cut(path), 900)
    px = r2._solid_colours(arr)
    if not len(px):
        return PERSON, {'reason': 'nothing drawn'}
    ok = np.zeros(len(px), bool)
    for h in a['hexes']:
        ok |= (np.abs(px - r3._hex_rgb(h)).max(axis=1) <= 3)
    off = px[~ok]
    if len(off) > 0.001 * len(px):
        values, counts = np.unique(off, axis=0, return_counts=True)
        return 'fail', {'outside_palette': [r3._to_hex(v) for v in values[np.argsort(-counts)][:4]]}
    return 'pass', {'reason': 'solid palette colours'}


def _proof_and_render(path, svg):
    """The proof's RGBA and the delivered SVG rendered at the proof's ink size, aligned on their ink boxes."""
    proof = np.asarray(Image.open(path).convert('RGBA')).astype(np.int16)
    pa = proof[..., 3] > 128
    ys, xs = np.where(pa)
    if not len(xs):
        return None
    pbox = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    probe = r2._render_svg_text(r2._svg_without_cut(svg), 800)
    ry, rx = np.where(probe[..., 3] > 128)
    if not len(rx):
        return None
    frac = (rx.max() + 1 - rx.min()) / probe.shape[1]
    width = int(round((pbox[2] - pbox[0]) / max(frac, 1e-6)))
    rend = r2._render_svg_text(r2._svg_without_cut(svg), max(16, width)).astype(np.int16)
    ry, rx = np.where(rend[..., 3] > 128)
    rbox = (rx.min(), ry.min(), rx.max() + 1, ry.max() + 1)
    return proof, pbox, rend, rbox


def op_proof_vs_svg(path, a):
    """A transparent proof is its delivered SVG: the SVG (cut layer left out) is rendered at the proof's ink width and
    aligned on the ink boxes. mode "same": ink boxes of the same proportions (within 2%), ink masks overlapping at
    IoU 0.97 or more and colours of solid pixels within 5 levels (median) pass; IoU under 0.9 or proportions 2% or
    more apart fail; between goes to a person. mode "transparent": wherever the SVG has no ink, beyond a 2 px edge
    band, the proof is fully transparent (98% of those pixels at alpha 0 passes; an opaque fill over 2% of them
    fails). Where the SVG has live type (rendered in whatever font is at hand) a difference goes to a person."""
    import cv2
    svg = Path(a['_artifacts']) / a['deliverable']
    if path.suffix.lower() != '.png' or not svg.is_file():
        return PERSON, {'reason': 'proof or SVG not available'}
    got = _proof_and_render(path, svg)
    if got is None:
        return PERSON, {'reason': 'nothing drawn'}
    proof, pbox, rend, rbox = got
    # live SVG type renders in whatever font the renderer finds (an embedded web font is not loaded), so where the
    # SVG has live text a difference is for a person, never a fail
    has_text = any(r2._local(e.tag) == 'text' for e in r2._svg_root(svg).iter())
    pw, ph, rw, rh = pbox[2] - pbox[0], pbox[3] - pbox[1], rbox[2] - rbox[0], rbox[3] - rbox[1]
    aspect = abs((pw / ph) / (rw / rh) - 1)
    crop_p = proof[pbox[1]:pbox[3], pbox[0]:pbox[2]]
    crop_r = cv2.resize(rend[rbox[1]:rbox[3], rbox[0]:rbox[2]].astype(np.uint8), (pw, ph), interpolation=cv2.INTER_AREA).astype(np.int16)
    mp, mr = crop_p[..., 3] > 128, crop_r[..., 3] > 128
    if a.get('mode') == 'transparent':
        empty = cv2.erode((~mr).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        if empty.sum() < 100:
            return 'pass', {'reason': 'no open space inside the artwork'}
        opaque = float((crop_p[..., 3][empty] > 16).mean())
        ev = {'opaque_share_of_open_space': round(opaque, 3)}
        return ('pass' if opaque <= 0.02 else 'fail' if aspect < 0.02 and not has_text else PERSON), ev
    iou = float((mp & mr).sum() / max(1, (mp | mr).sum()))
    solid = r3._flat(crop_r[..., :3], 2) & r3._flat(crop_p[..., :3], 2) & mp & mr
    diff = float(np.median(np.abs(crop_p[..., :3][solid] - crop_r[..., :3][solid]).max(axis=1))) if solid.sum() > 100 else 99.0
    ev = {'iou': round(iou, 3), 'aspect_change': round(aspect, 3), 'colour_diff': round(diff, 1)}
    if iou >= 0.97 and aspect < 0.02 and diff <= 5:
        return 'pass', ev
    if (iou < 0.9 or aspect >= 0.02) and not has_text:
        return 'fail', ev
    return PERSON, ev


def op_built_from_raster(path, a):
    """The drawing (a proof composited on white, or an SVG rendered) is traced from the named photo, not the others:
    feature matching against each, its own giving 30 or more matched points and three times any other's passes; an
    other clearly ahead the same way fails; else a person. An other may be a supplied PDF (its first page rendered)."""
    if path.suffix.lower() == '.svg':
        rgba = Image.fromarray(r2._render_svg_text(r2._svg_without_cut(path), 700))
    else:
        rgba = Image.open(path).convert('RGBA')
        rgba = rgba.resize((700, round(700 * rgba.height / rgba.width)), Image.LANCZOS)
    drawing = np.asarray(Image.alpha_composite(Image.new('RGBA', rgba.size, (255, 255, 255, 255)), rgba).convert('L'))
    points = {}
    for name in [a['photo']] + a['others']:
        try:
            src = base.asset_path(a, name)
        except FileNotFoundError:
            return PERSON, {'reason': f'supplied file not available: {name}'}
        gray = np.asarray(base.render_pdf(src, 0, 150).convert('L')) if src.suffix.lower() == '.pdf' else r2._photo_gray(str(src))
        n, _, state = base.find_asset(gray, drawing)
        points[name] = n if state != 'none' else 0
    own, other = points[a['photo']], max(points[o] for o in a['others'])
    ev = {'matched_points': points}
    if own >= 30 and own >= 3 * other:
        return 'pass', ev
    if other >= 30 and other >= 3 * own:
        return 'fail', ev
    return PERSON, ev


def _sheet_cuts(key: str):
    """Cut paths on a production sheet: drawings on a layer named as a cut line, or stroked in a cut spot colour."""
    out = []
    for n, info in enumerate(_pdf_pages(key)):
        for d in info['drawings']:
            if CUT_RX.search(d.get('layer') or ''):
                out.append((n, d))
    return out


def _bezier_points(d, step=0.5):
    pts = []
    for it in d.get('items') or []:
        if it[0] == 'l':
            p0, p1 = it[1], it[2]
            k = max(2, int(abs(p1 - p0) / step))
            pts += [(p0.x + (p1.x - p0.x) * t, p0.y + (p1.y - p0.y) * t) for t in np.linspace(0, 1, k)]
        elif it[0] == 'c':
            p0, c1, c2, p1 = it[1], it[2], it[3], it[4]
            k = max(4, int((abs(c1 - p0) + abs(c2 - c1) + abs(p1 - c2)) / step))
            for t in np.linspace(0, 1, k):
                u = 1 - t
                pts.append((u ** 3 * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t ** 3 * p1.x,
                            u ** 3 * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t ** 3 * p1.y))
        elif it[0] == 're':
            r = it[1]
            pts += [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
    return np.array(pts) if pts else np.zeros((0, 2))


def _ocg_names(key: str):
    import pymupdf
    doc = pymupdf.open(key)
    try:
        return [v['name'] for v in doc.get_ocgs().values()]
    except Exception:
        return []


def op_sheet_cuts(path, a):
    """Production sheet cut paths (drawings on the cut layer). mode "margin": every cut path at least min_mm from
    every sheet edge (stroke included); "gutter": every two cut paths at least min_mm apart (closest points); "art_
    margin": every drawing inside a cut path's box (the sticker artwork) at least min_mm from the edges; "art_size":
    each sticker's artwork (drawings inside its cut path, cut path left out) long_mm on its long edge; "layer": the
    cut layer holds only stroked paths (no fill, type or picture); "count": the cut layer holds exactly count paths,
    each closed; "name": the cut layer is named exactly CutContour. Distances within 0.2 mm of the limit go to a
    person; no cut paths go to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    mode = a['mode']
    if mode == 'name':
        names = _ocg_names(key)
        cutty = [x for x in names if CUT_RX.search(x)]
        if 'CutContour' in names:
            return 'pass', {'layers': names}
        return ('fail', {'layers': names}) if cutty else (PERSON, {'reason': 'no cut layer', 'layers': names})
    if mode == 'layer':
        ops = [o for o in _pdf_paint(key) if any(n == 'CutContour' for n in o['layers'])]
        if not ops:
            return 'fail', {'reason': 'no layer named CutContour holding paths'}
        bad = sorted({f"{o['kind']} {o['what']}" for o in ops if not (o['kind'] == 'path' and o['what'] == 'stroke')})
        return ('fail', {'on_cut_layer': bad}) if bad else ('pass', {'cut_paths': len(ops)})
    cuts = _sheet_cuts(key)
    if not cuts:
        return PERSON, {'reason': 'no cut paths found'}
    info0 = _pdf_pages(key)[cuts[0][0]]
    W, H = info0['W'], info0['H']
    if mode == 'count':
        closed = []
        for n, d in cuts:
            pts = _bezier_points(d)
            closed.append(bool(d.get('closePath')) or (len(pts) > 2 and np.hypot(*(pts[0] - pts[-1])) < 0.3))
        ev = {'paths': len(cuts), 'closed': sum(closed)}
        return ('pass' if len(cuts) == a['count'] and all(closed) else 'fail'), ev
    if mode == 'margin':
        dist = min(min(d['rect'].x0, d['rect'].y0, W - d['rect'].x1, H - d['rect'].y1) - (d.get('width') or 0) / 2 for n, d in cuts) / MM
        ev = {'closest_mm': round(dist, 2)}
        return ('pass' if dist >= a['min_mm'] else 'fail' if dist < a['min_mm'] - 0.2 else PERSON), ev
    if mode == 'gutter':
        pts = [_bezier_points(d) for n, d in cuts]
        best = 1e9
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                if len(pts[i]) and len(pts[j]):
                    for k in range(0, len(pts[j]), 2000):          # closest pair, in chunks to bound memory
                        d = np.sqrt(((pts[i][:, None, :] - pts[j][None, k:k + 2000, :]) ** 2).sum(axis=2)).min()
                        best = min(best, float(d))
        width = max((d.get('width') or 0) for n, d in cuts)
        gap = (best - width) / MM
        ev = {'closest_gap_mm': round(gap, 2)}
        return ('pass' if gap >= a['min_mm'] else 'fail' if gap < a['min_mm'] - 0.2 else PERSON), ev
    boxes = [(n, (d['rect'].x0, d['rect'].y0, d['rect'].x1, d['rect'].y1)) for n, d in cuts]
    art = {i: [] for i in range(len(boxes))}
    stray = 0
    for n, info in enumerate(_pdf_pages(key)):
        for d in info['drawings']:
            if CUT_RX.search(d.get('layer') or ''):
                continue
            r = (d['rect'].x0, d['rect'].y0, d['rect'].x1, d['rect'].y1)
            own = [i for i, (pn, b) in enumerate(boxes) if pn == n and _within(r, b, 0.5)]
            if own:
                art[own[0]].append(r)
            elif d.get('fill') is not None and _area(r) < 0.9 * W * H:
                stray += 1
    if mode == 'art_margin':
        rs = [r for v in art.values() for r in v]
        if not rs:
            return PERSON, {'reason': 'no artwork inside the cut paths'}
        dist = min(min(r[0], r[1], W - r[2], H - r[3]) for r in rs) / MM
        ev = {'closest_mm': round(dist, 2), 'unassigned_shapes': stray}
        if dist < a['min_mm'] - 0.2:
            return 'fail', ev
        return ('pass' if dist >= a['min_mm'] and not stray else PERSON), ev
    if mode == 'art_size':
        sizes = []
        for i, rs in art.items():
            if not rs:
                return PERSON, {'reason': 'a cut path with no artwork inside'}
            bw = (max(r[2] for r in rs) - min(r[0] for r in rs)) / MM
            bh = (max(r[3] for r in rs) - min(r[1] for r in rs)) / MM
            sizes.append(round(max(bw, bh), 2))
        off = [x for x in sizes if abs(x - a['long_mm']) > 0.5]
        ev = {'long_edges_mm': sizes}
        if not off:
            return 'pass', ev
        return ('fail' if any(abs(x - a['long_mm']) > 1.0 for x in off) else PERSON), ev
    return PERSON, {'reason': 'unknown mode'}


def _labels(key):
    """Live type on a production sheet lying outside every cut path's box (labels, slugs, die-line notes)."""
    boxes = {}
    for n, d in _sheet_cuts(key):
        boxes.setdefault(n, []).append((d['rect'].x0, d['rect'].y0, d['rect'].x1, d['rect'].y1))
    return [sp for sp in _pdf_glyphs(key) if not any(_within(sp['bbox'], b, 1.0) for b in boxes.get(sp['page'], []))], bool(boxes)


def op_labels(path, a):
    """Labels, slugs and die-line notes on a production sheet (live type outside every cut path's box): mode "caps":
    no lowercase letter; mode "leading": where a label runs over two or more lines (one size, lines no more than 2.2
    sizes apart, sharing a left edge), baselines leading_pt apart within 0.25 pt. No labels: a pass. No cut paths
    to tell stickers from labels: a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    labels, has_cuts = _labels(str(path))
    if not has_cuts:
        return PERSON, {'reason': 'no cut paths to tell the stickers from labels'}
    if not labels:
        return 'pass', {'reason': 'no labels'}
    if a['mode'] == 'caps':
        low = [sp['text'][:30] for sp in labels if re.search(r'[a-z]', sp['text'])]
        return ('fail', {'lowercase': low[:4]}) if low else ('pass', {'labels': len(labels)})
    rows = sorted(labels, key=lambda sp: (sp['page'], sp['bbox'][0], sp['bbox'][1]))
    origins = {(pg, tuple(round(v, 1) for v in bb)): y for pg, bb, y, size in _pdf_origins(str(path))}
    gaps = []
    for x, y in zip(rows, rows[1:]):
        if x['page'] == y['page'] and abs(x['bbox'][0] - y['bbox'][0]) < 1 and abs(x['size'] - y['size']) < 0.05 and 0 < y['bbox'][1] - x['bbox'][1] <= 2.2 * x['size']:
            gaps.append(round(y['bbox'][3] - x['bbox'][3], 2))
    if not gaps:
        return 'pass', {'reason': 'no label runs over two lines'}
    off = [g for g in gaps if abs(g - a['leading_pt']) > 0.25]
    return ('fail', {'baseline_gaps_pt': off}) if off else ('pass', {'baseline_gaps_pt': gaps})


def op_svg_arch(path, a):
    """A wordmark set as SVG live text arches: set flat (no textPath and no per-letter rotation, the words on one
    straight baseline) fails; on a path or rotated goes to a person (the arc's angle is measured by a person); no
    such wordmark as live text passes."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    root = r2._svg_root(path)
    hits = [e for e in root.iter() if r2._local(e.tag) == 'text' and re.search(a['text'], ''.join(e.itertext()), re.I)]
    if not hits:
        outlined = any(r2._local(e.tag) == 'path' for e in root.iter())
        return (PERSON, {'reason': 'no live wordmark (it may be drawn as outlines)'}) if outlined else ('pass', {'reason': 'no wordmark'})
    for t in hits:
        curved = any(r2._local(x.tag) == 'textPath' or len(re.findall(r'-?[\d.]+', x.get('rotate') or '')) > 1 for x in t.iter())
        if not curved and 'rotate(' not in (t.get('transform') or ''):
            return 'fail', {'reason': 'the wordmark is set on a straight baseline'}
    return PERSON, {'reason': 'set on a path or rotated; the arc is for a person to measure'}


def op_no_photo_texture(path, a):
    """An image carries no photograph or photographic texture: photo-like areas (textured or a two-colour photo
    treatment, objective_ops_r3._textured and _two_colour_blocks) under 0.5% of the inked area pass; 5% or more
    fail; between goes to a person."""
    rgb, alpha = _rgba(path)
    m = _photos(path, dict(a, photos=[]))
    inked = (alpha >= 128) if alpha is not None else np.ones(m.shape, bool)
    share = float((m & inked).sum() / max(1, inked.sum()))
    ev = {'photo_like_share': round(share, 4)}
    return ('pass' if share < 0.005 else 'fail' if share >= 0.05 else PERSON), ev


def op_sheet_no_raster(path, a):
    """A production sheet places no continuous-tone picture: no placed image (or only images of a few flat colours:
    16 or fewer colours covering 98% of their pixels) and no field of more than 40 tiny vector specks (under 0.5 mm).
    A continuous-tone image fails; a speck field or an unclear image goes to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    for page, b, gray, rgb in _placed(path, 0.0):
        q = (rgb.reshape(-1, 3) // 8).astype(np.int32)
        code = (q[:, 0] << 10) | (q[:, 1] << 5) | q[:, 2]
        values, counts = np.unique(code, return_counts=True)
        top = np.sort(counts)[::-1][:16].sum() / counts.sum()
        if top < 0.98:
            return ('fail' if len(values) > 256 else PERSON), {'reason': 'a continuous-tone picture', 'colours': int(len(values))}
    specks = sum(1 for info in _pdf_pages(str(path)) for d in info['drawings'] if max(d['rect'].width, d['rect'].height) < 0.5 * MM)
    if specks > 40:
        return PERSON, {'reason': 'many tiny specks (a halftone field?)', 'specks': specks}
    return 'pass', {'specks': specks}


# ================================================================ films and thumbnails: end cards, Scrap, title rows, capture


def op_frame_text(path, a):
    """A line of the last held frame (the end card; an image: the image) reads the expected text exactly, spacing
    aside: found passes; a near miss goes to a person; absent with every line read confidently fails."""
    f = _frames_of(path, 'last')[-1]
    layer = _ocr(str(path), f)
    lines = [l for l in layer.lines if base._real(l)]
    target = base.squash(canon(a['text'])).upper()
    if any(target in base.squash(canon(l.text)).upper() for l in lines):
        return 'pass', {'found': a['text']}
    near = max((base.near_miss(l.text, a['text']) for l in lines), default=0.0)
    if near >= base.NEAR_MISS or not layer.confident:
        return PERSON, {'reason': 'not read clearly', 'similarity': round(near, 2)}
    return 'fail', {'missing': a['text']}


def op_end_hold(path, a):
    """A film ends on a held, still frame: its last frames, read at the film's own frame rate, stay the same (mean
    difference under 1 level) for a second or more (passes); under a quarter second fails; between goes to a person."""
    key = str(path)
    probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=r_frame_rate,nb_frames',
                            '-of', 'csv=p=0', key], capture_output=True, text=True, timeout=60).stdout.strip().split(',')
    try:
        num, den = probe[0].split('/')
        fps = float(num) / float(den)
    except (ValueError, IndexError):
        return PERSON, {'reason': 'frame rate not read'}
    frames = _video_small(key, 320)
    held = 0
    for i in range(len(frames) - 1, 0, -1):
        if np.abs(frames[i].astype(np.int16) - frames[i - 1].astype(np.int16)).mean() < 1.0:
            held += 1
        else:
            break
    seconds = (held + 1) / fps
    ev = {'held_seconds': round(seconds, 2), 'fps': round(fps, 2)}
    return ('pass' if seconds >= 1.0 else 'fail' if seconds < 0.25 else PERSON), ev


def _find_asset_frames(path, a, which='all'):
    """(frame, corners) for every frame (at 4 a second for films) where the supplied file is found."""
    asset = base._load_gray(base.asset_path(a, a['asset']))
    out = []
    for f in _frames_of(path, which):
        gray = np.asarray(Image.fromarray(_frame_rgb(path, f).astype(np.uint8)).convert('L'))
        n, corners, state = base.find_asset(gray, asset)
        if state == 'found':
            out.append((f, corners))
    return out, asset


def op_asset_found(path, a):
    """The supplied file (a mascot cut-out) is found in the image or in a frame of the film (4 a second) by feature
    matching: found passes; not found goes to a person (it may be absent, or redrawn)."""
    try:
        hits, asset = _find_asset_frames(path, a)
    except FileNotFoundError:
        return PERSON, {'reason': 'supplied file not available'}
    return ('pass', {'frames': [f for f, _ in hits][:6]}) if hits else (PERSON, {'reason': 'not found (absent or redrawn)'})


def op_asset_pixels(path, a):
    """Where the supplied cut-out is found and held still, its own pixels are unchanged: inside its opaque area
    (eroded 4 px), select "all", or only its orange or purple pixels, the deliverable warped back onto the file
    differs by no more than tol per channel (median) (passes); 30 or more, or a shift toward the ground behind (a
    blend), fails; between goes to a person. Not found goes to a person."""
    import cv2
    try:
        hits, asset = _find_asset_frames(path, a, 'held' if path.suffix.lower() == '.mp4' else 'all')
    except FileNotFoundError:
        return PERSON, {'reason': 'supplied file not available'}
    if not hits:
        return PERSON, {'reason': 'not found (absent or redrawn)'}
    src = Image.open(base.asset_path(a, a['asset'])).convert('RGBA')
    k = asset.shape[1] / src.width
    src = np.asarray(src.resize((asset.shape[1], asset.shape[0]), Image.LANCZOS)).astype(np.int16)
    m = cv2.erode((src[..., 3] >= OPAQUE).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    if a.get('select') in ('orange', 'purple'):
        import colorsys
        hsv = np.asarray(Image.fromarray(src[..., :3].astype(np.uint8)).convert('HSV')).astype(int)
        hue = hsv[..., 0] * 360 / 255
        m &= (hsv[..., 1] > 100) & (((hue >= 5) & (hue <= 40)) if a['select'] == 'orange' else ((hue >= 250) & (hue <= 300)))
    if m.sum() < 100:
        return PERSON, {'reason': 'too few pixels of that kind'}
    worst = 0.0
    for f, corners in hits:
        rgb = _frame_rgb(path, f).astype(np.float32)
        h, w = asset.shape
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
        back = cv2.warpPerspective(rgb, np.linalg.inv(H), (w, h), flags=cv2.INTER_AREA)
        diff = float(np.median(np.abs(back[m] - src[..., :3][m]).max(axis=1)))
        worst = max(worst, diff)
    tol = a.get('tol', 8)
    ev = {'median_difference': round(worst, 1), 'frames': len(hits)}
    return ('pass' if worst <= tol else 'fail' if worst >= 30 else PERSON), ev


def _title_rows(path, f, title):
    """OCR lines on a frame made only of the title's words (a title set over several rows), top to bottom."""
    layer = _ocr(str(path), f)
    rows = [l for l in layer.lines if base._real(l) and _only_words(l.text, title.split())]
    return sorted(rows, key=lambda l: l.bbox[1]), layer


def op_last_row(path, a):
    """The title's last row (the lowest line made only of title words) reads exactly the final word (letters only):
    passes; another reading fails where that row was read confidently and every title word was read in the rows
    (so no row was missed); title rows not found, or an unclear read, go to a person."""
    f = _frames_of(path, 'last')[-1]
    rows, layer = _title_rows(path, f, a['title'])
    if not rows:
        return PERSON, {'reason': 'title not read'}
    last = rows[-1]
    got = re.sub(r'[^A-Z0-9]', '', last.text.upper())
    want = re.sub(r'[^A-Z0-9]', '', a['word'].upper())
    if got == want:
        return 'pass', {'last_row': last.text}
    # every title word read in the rows found: no row was missed, so the last row is known
    words = {_norm_word(w) for w in a['title'].split() if len(_norm_word(w)) >= 2}
    seen = {_norm_word(x) for l in rows for x in l.text.split()}
    sure = last.conf >= OCR_GOOD_CONF and (layer.confident or words <= seen)
    return ('fail' if sure else PERSON), {'last_row': last.text, 'expected': a['word']}


def _word_fill_height(path, f, word, fills, tol):
    """Median height of the letter fills (pixels in the fill colours, outline left out) inside an OCR word box."""
    import cv2
    boxes, missing = _title_word_boxes(str(path), f, word)
    if not boxes:
        return None
    rgb = _frame_rgb(path, f)
    hs = []
    for _, (x0, y0, x1, y1) in boxes:
        pad = int(0.3 * (y1 - y0))
        X0, Y0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
        crop = r3._near_mask(rgb[Y0:int(y1) + pad, X0:int(x1) + pad], fills, tol)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(crop.astype(np.uint8), connectivity=8)
        cand = [stats[i][3] for i in range(1, n) if stats[i][3] >= 0.35 * (y1 - y0) and stats[i][4] >= 20
                and stats[i][0] > 0 and stats[i][1] > 0 and stats[i][0] + stats[i][2] < crop.shape[1] and stats[i][1] + stats[i][3] < crop.shape[0]]
        if cand:
            hs.append(float(np.median(cand)))
    return float(np.median(hs)) if hs else None


def op_cap_height(path, a):
    """The capitals of a title word (its letters' fill, outline left out, on the image or the end card) stand between
    min_px and max_px tall at full size: within passes; 5 px or more outside fails; within 5 px of a limit, or not
    measured, goes to a person."""
    f = _frames_of(path, 'last')[-1]
    tol = r3._tol(path, a) + 3
    hs = [x for x in (_word_fill_height(path, f, w, a['fills'], tol) for w in a['words']) if x]
    if not hs:
        return PERSON, {'reason': 'letters not measured'}
    lo, hi = min(hs), max(hs)
    ev = {'cap_heights_px': [round(x) for x in hs]}
    if a['min_px'] <= lo and hi <= a['max_px']:
        return 'pass', ev
    if lo < a['min_px'] - 5 or hi > a['max_px'] + 5:
        return 'fail', ev
    return PERSON, ev


def op_word_shorter(path, a):
    """The final word's capitals (fill height, outline left out) are shorter than every other word's named in upper:
    5% or more shorter passes; as tall or taller fails; between goes to a person."""
    f = _frames_of(path, 'last')[-1]
    tol = r3._tol(path, a) + 3
    low = _word_fill_height(path, f, a['word'], a['fills'], tol)
    ups = [x for x in (_word_fill_height(path, f, w, a['fills'], tol) for w in a['upper']) if x]
    if not low or not ups:
        return PERSON, {'reason': 'letters not measured'}
    ev = {'final_px': round(low), 'setup_px': [round(x) for x in ups]}
    if low <= 0.95 * min(ups):
        return 'pass', ev
    return ('fail' if low >= min(ups) else PERSON), ev


def op_frame_inside(path, a):
    """No line on the last held frame is cut at the frame edge: every line read lies 2 px or more inside (passes,
    when every line was read confidently); a confident line touching an edge fails; otherwise a person."""
    f = _frames_of(path, 'last')[-1]
    rgb = _frame_rgb(path, f)
    h, w = rgb.shape[:2]
    layer = _ocr(str(path), f)
    lines = [l for l in layer.lines if base._real(l)]
    edge = [l for l in lines if l.bbox[0] < 2 or l.bbox[1] < 2 or l.bbox[2] > w - 2 or l.bbox[3] > h - 2]
    if edge:
        return ('fail' if edge[0].conf >= OCR_GOOD_CONF else PERSON), {'at_edge': edge[0].text}
    if not lines or not layer.confident:
        return PERSON, {'reason': 'not every line read clearly'}
    return 'pass', {'lines': len(lines)}


def _capture_index(key, dirs):
    """Small grey frames of every supplied capture, for telling which capture a footage frame comes from."""
    out = {}
    for i in range(1, 7):
        name = f'staticfox_captures/staticfox_capture_0{i}.mp4'
        try:
            cap = base.asset_path({'_asset_dirs': list(dirs)}, name)
        except FileNotFoundError:
            continue
        out[i] = [np.asarray(Image.fromarray(f).convert('L').resize((160, 90))).astype(float) for f in _video_small(str(cap), 320)[::6]]
    return out


def op_footage(path, a):
    """Footage in a film, frame by frame at 4 a second: a frame is footage where textured areas cover a tenth of it
    or more; its capture is the supplied capture whose frames correlate best with it (0.6 or more, 0.15 ahead of any
    other). mode "none": no footage frame passes; a frame matching a capture fails; unmatched footage goes to a
    person. mode "only_captures": every footage frame matched passes. mode "min_captures": with every footage frame
    matched, at least count different captures passes, fewer fails. mode "not_used": capture number not among the
    matched ones (all footage matched) passes; used goes to a person."""
    idx = _capture_index(str(path), tuple(a.get('_asset_dirs') or []))
    used, unmatched, footage = set(), 0, 0
    for f in _frames_of(path, 'all'):
        rgb = _frame_rgb(path, f)
        t = r3._textured(rgb)
        if t.mean() < 0.10:
            continue
        footage += 1
        g = np.asarray(Image.fromarray(rgb.astype(np.uint8)).convert('L').resize((160, 90))).astype(float)
        g = g - g.mean()
        best = {}
        for i, frames in idx.items():
            sc = []
            for c in frames:
                c = c - c.mean()
                sc.append(float((g * c).sum() / (np.sqrt((g * g).sum() * (c * c).sum()) + 1e-9)))
            best[i] = max(sc) if sc else -1
        if not best:
            unmatched += 1
            continue
        order = sorted(best.items(), key=lambda kv: -kv[1])
        if order[0][1] >= 0.6 and (len(order) == 1 or order[0][1] - order[1][1] >= 0.15):
            used.add(order[0][0])
        else:
            unmatched += 1
    ev = {'footage_frames': footage, 'captures': sorted(used), 'unmatched': unmatched}
    mode = a['mode']
    if mode == 'none':
        return ('fail', ev) if used else (PERSON, ev) if unmatched else ('pass', ev)
    if unmatched:
        return PERSON, dict(ev, reason='footage not matched to a capture')
    if mode == 'only_captures':
        return 'pass', ev
    if mode == 'min_captures':
        return ('pass' if len(used) >= a['count'] else 'fail'), ev
    if mode == 'not_used':
        return ('pass' if a['capture'] not in used else PERSON), ev
    return PERSON, ev


def op_capture_colour(path, a):
    """The capture frame keeps its game colours: on the capture's visible parts (see op_capture_wash), the thumbnail's
    colour differs from the matched source frame by no more than 8 levels per channel on average (passes); a hue
    shift of 30 degrees or more on average, or a shift toward a palette colour of 30 levels or more, fails; between
    goes to a person."""
    import cv2
    cap = _capture_match(str(path), a['capture'], tuple(a.get('_asset_dirs') or []))
    if cap is None:
        return PERSON, {'reason': 'the capture frame the thumbnail is built on was not matched'}
    thumb = r3._pixels(str(path)).astype(np.float32)
    frame = cap['frame']
    tg = cv2.cvtColor(np.clip(thumb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    fg = cv2.cvtColor(np.clip(frame, 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY)
    _, _, _, sf, ncc = _local_stats(tg, fg)
    vis = cap['valid'] & (sf >= 8) & (ncc >= 0.8)
    if vis.mean() < 0.15:
        return PERSON, {'reason': 'too little of the capture visible to compare'}
    d = np.abs(thumb[vis] - frame[vis]).mean(axis=0)
    hs = cv2.cvtColor(np.clip(thumb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)[..., 0][vis].astype(float) * 2
    hf = cv2.cvtColor(np.clip(frame, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)[..., 0][vis].astype(float) * 2
    sat = cv2.cvtColor(np.clip(frame, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)[..., 1][vis] > 60
    dh = np.abs((hs - hf + 180) % 360 - 180)[sat]
    shift = float(np.mean(dh)) if len(dh) > 100 else 0.0
    ev = {'mean_difference': [round(float(x), 1) for x in d], 'hue_shift_deg': round(shift, 1)}
    if d.max() <= 8:
        return 'pass', ev
    if shift >= 30:
        return 'fail', ev
    return PERSON, ev


def op_capture_used(path, a):
    """The capture frame is used as recorded: the matched source frame covers the whole thumbnail, and every 64 px
    cell that shows capture (80% or more of its pixels) correlates with it at 0.9 or more (passes); anything else goes
    to a person (never a fail: covered areas may hide nothing)."""
    import cv2
    cap = _capture_match(str(path), a['capture'], tuple(a.get('_asset_dirs') or []))
    if cap is None:
        return PERSON, {'reason': 'the capture frame the thumbnail is built on was not matched'}
    if cap['valid'].mean() < 0.995:
        return PERSON, {'reason': 'the source frame does not cover the whole thumbnail (extended?)', 'covered': round(float(cap['valid'].mean()), 3)}
    thumb = cv2.cvtColor(r3._pixels(str(path)).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(float)
    frame = cv2.cvtColor(np.clip(cap['frame'], 0, 255).astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(float)
    h, w = thumb.shape
    low = []
    for y in range(0, h - 63, 64):
        for x in range(0, w - 63, 64):
            if cap['capture'][y:y + 64, x:x + 64].mean() < 0.8:
                continue
            p, q = thumb[y:y + 64, x:x + 64], frame[y:y + 64, x:x + 64]
            if q.std() < 4:
                continue
            p, q = p - p.mean(), q - q.mean()
            ncc = float((p * q).sum() / (np.sqrt((p * p).sum() * (q * q).sum()) + 1e-9))
            if ncc < 0.9:
                low.append((y // 64, x // 64))
    return ('pass', {'reason': 'every visible cell matches the source frame'}) if not low else (PERSON, {'reason': 'cells differ from the source frame', 'cells': low[:5]})

OPS.update({
    'v2_gate': op_gate,
    'v2_raster_roles': op_raster_roles,
    'v2_no_panel': op_no_panel,
    'v2_raster_photo_overlay': op_raster_photo_overlay,
    'v2_pdf_colour_use': op_pdf_colour_use,
    'v2_pdf_rule_at_text': op_pdf_rule_at_text,
    'v2_pdf_text_colour': op_pdf_text_colour,
    'v2_pdf_photo_overlay': op_pdf_photo_overlay,
    'v2_pdf_area_share': op_pdf_area_share,
    'v2_grounds': op_grounds,
    'v2_raster_palette': op_raster_palette,
    'v2_raster_share': op_raster_share,
    'v2_raster_present': op_raster_present,
    'v2_raster_text_colour': op_raster_text_colour,
    'v2_mark_on_ground': op_mark_on_ground,
    'v2_line_chars': op_line_chars,
    'v2_role_font': op_role_font,
    'v2_tracking_vs_body': op_tracking_vs_body,
    'v2_svg_leading': op_svg_leading,
    'v2_pdf_cut_spot': op_pdf_cut_spot,
    'v2_pdf_process_only': op_pdf_process_only,
    'v2_pdf_managed_palette': op_pdf_managed_palette,
    'v2_pdf_labels_colour': op_pdf_labels_colour,
    'v2_placed_master': op_placed_master,
    'v2_ink_detail': op_ink_detail,
    'v2_capture_wash': op_capture_wash,
    'v2_title_letters': op_title_letters,
    'v2_title_largest': op_title_largest,
    'v2_font_is': op_font_is,
    'v2_digit_size': op_digit_size,
    'v2_text_leading': op_text_leading,
    'v2_text_smallest': op_text_smallest,
    'v2_text_size_vs_file': op_text_size_vs_file,
    'v2_tracking_of': op_tracking_of,
    'v2_pdf_solid_all': op_pdf_solid_all,
    'v2_only_supplied': op_only_supplied,
    'v2_photo_proportions': op_photo_proportions,
    'v2_region_kept': op_region_kept,
    'v2_photo_natural': op_photo_natural,
    'v2_inside_trim': op_inside_trim,
    'v2_combined_pages': op_combined_pages,
    'v2_images_are': op_images_are,
    'v2_photo_two_colour': op_photo_two_colour,
    'v2_photo_as_shot': op_photo_as_shot,
    'v2_clipped_flat': op_clipped_flat,
    'v2_caps': op_caps,
    'v2_title_stack': op_title_stack,
    'v2_mark_not_retyped': op_mark_not_retyped,
    'v2_mark_beside': op_mark_beside,
    'v2_mark_letters': op_mark_letters,
    'v2_chart_scale': op_chart_scale,
    'v2_numbers_from': op_numbers_from,
    'v2_text_anywhere': op_text_anywhere,
    'v2_artwork_only': op_artwork_only,
    'v2_soft_edges': op_soft_edges,
    'v2_svg_viewbox': op_svg_viewbox,
    'v2_svg_cut_file': op_svg_cut_file,
    'v2_svg_solid': op_svg_solid,
    'v2_proof_vs_svg': op_proof_vs_svg,
    'v2_built_from_raster': op_built_from_raster,
    'v2_sheet_cuts': op_sheet_cuts,
    'v2_labels': op_labels,
    'v2_svg_arch': op_svg_arch,
    'v2_no_photo_texture': op_no_photo_texture,
    'v2_sheet_no_raster': op_sheet_no_raster,
    'v2_frame_text': op_frame_text,
    'v2_end_hold': op_end_hold,
    'v2_asset_found': op_asset_found,
    'v2_asset_pixels': op_asset_pixels,
    'v2_last_row': op_last_row,
    'v2_cap_height': op_cap_height,
    'v2_word_shorter': op_word_shorter,
    'v2_frame_inside': op_frame_inside,
    'v2_footage': op_footage,
    'v2_capture_colour': op_capture_colour,
    'v2_capture_used': op_capture_used,
    'v2_photo_pair_same': op_photo_pair_same,
})
base.OPS.update(OPS)
