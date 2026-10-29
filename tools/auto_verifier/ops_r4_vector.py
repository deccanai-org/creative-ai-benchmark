"""Round 4 operations for VECTOR-04 (Meridian & Ash stickers), 2026-10-28: cut-path geometry (offset from the artwork,
corner radius), cut lines drawn into proofs and the production sheet, sheet notes, live SVG type (family, weight,
case, the hanging ampersand), and four corrected round-3 checks (solid SVG ink, flat proof ink, open space in proofs,
proof against its SVG).

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person"; nothing
passes on a failed or partial read. Geometry is read in millimetres: an SVG's user units are mapped to millimetres by
its width and height (physical units) over its viewBox, and two SVGs are compared in those coordinates (a cut file and
its artwork share their origin, as the brief's files do); a PDF in points (72 per inch).
"""
from __future__ import annotations

OPS: dict = {}

import math
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image

import objective_ops as base
import objective_ops_r2 as r2
import objective_ops_r3 as r3
import ops_r3_layout as l3
from objective_ops import PERSON

PT_MM = 72 / 25.4          # PDF points per millimetre
SHAPES = ('path', 'polygon', 'polyline', 'rect', 'circle', 'ellipse', 'line')


# ================================================================ SVG geometry: transforms, path data, mm frame

def _tf(s: str | None) -> np.ndarray:
    m = np.eye(3)
    for name, args in re.findall(r'(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)', s or ''):
        v = [float(x) for x in re.findall(r'-?[\d.]+(?:e-?\d+)?', args)]
        if name == 'matrix' and len(v) == 6:
            t = np.array([[v[0], v[2], v[4]], [v[1], v[3], v[5]], [0, 0, 1]])
        elif name == 'translate':
            t = np.array([[1, 0, v[0]], [0, 1, v[1] if len(v) > 1 else 0], [0, 0, 1]])
        elif name == 'scale':
            t = np.array([[v[0], 0, 0], [0, v[1] if len(v) > 1 else v[0], 0], [0, 0, 1]])
        elif name == 'rotate':
            a = math.radians(v[0])
            t = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
            if len(v) == 3:
                t = np.array([[1, 0, v[1]], [0, 1, v[2]], [0, 0, 1]]) @ t @ np.array([[1, 0, -v[1]], [0, 1, -v[2]], [0, 0, 1]])
        elif name == 'skewX':
            t = np.array([[1, math.tan(math.radians(v[0])), 0], [0, 1, 0], [0, 0, 1]])
        else:
            t = np.array([[1, 0, 0], [math.tan(math.radians(v[0])), 1, 0], [0, 0, 1]])
        m = m @ t
    return m


def _arc(p0, rx, ry, phi, fa, fs, p1, step):
    x1, y1 = p0
    x2, y2 = p1
    if rx == 0 or ry == 0:
        return [p1]
    phi = math.radians(phi)
    c, s = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = c * dx + s * dy, -s * dx + c * dy
    rx, ry = abs(rx), abs(ry)
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    coef = math.sqrt(max(0.0, num / den)) if den else 0.0
    if fa == fs:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx
    cx, cy = c * cxp - s * cyp + (x1 + x2) / 2, s * cxp + c * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    th1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dth = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not fs and dth > 0:
        dth -= 2 * math.pi
    elif fs and dth < 0:
        dth += 2 * math.pi
    n = max(4, int(abs(dth) * max(rx, ry) / step))
    out = []
    for t in np.linspace(0, 1, n + 1)[1:]:
        th = th1 + dth * t
        out.append((cx + rx * math.cos(th) * c - ry * math.sin(th) * s, cy + rx * math.cos(th) * s + ry * math.sin(th) * c))
    return out


def _path_subpaths(d: str, step: float = 0.05):
    """Subpaths of SVG path data as point lists (curves and arcs sampled every step user units), each with whether
    it closes. Every command of the SVG path grammar is read (absolute and relative)."""
    toks = re.findall(r'[MmLlHhVvCcSsQqTtAaZz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', d or '')
    i, cmd = 0, None
    cur = (0.0, 0.0)
    start = cur
    subs, pts, closed = [], [], False
    last_c = last_q = None

    def nums(k):
        nonlocal i
        v = [float(t) for t in toks[i:i + k]]
        i += k
        return v

    def bez(p0, ctrl, p1):
        pts_ = [p0] + ctrl + [p1]
        L = sum(math.dist(pts_[j], pts_[j + 1]) for j in range(len(pts_) - 1))
        n = max(4, int(L / step))
        out = []
        for t in np.linspace(0, 1, n + 1)[1:]:
            if len(ctrl) == 2:
                u = 1 - t
                out.append((u ** 3 * p0[0] + 3 * u * u * t * ctrl[0][0] + 3 * u * t * t * ctrl[1][0] + t ** 3 * p1[0],
                            u ** 3 * p0[1] + 3 * u * u * t * ctrl[0][1] + 3 * u * t * t * ctrl[1][1] + t ** 3 * p1[1]))
            else:
                u = 1 - t
                out.append((u * u * p0[0] + 2 * u * t * ctrl[0][0] + t * t * p1[0], u * u * p0[1] + 2 * u * t * ctrl[0][1] + t * t * p1[1]))
        return out
    while i < len(toks):
        t = toks[i]
        if re.fullmatch(r'[A-Za-z]', t):
            cmd = t
            i += 1
            if cmd in 'Zz':
                if pts:
                    subs.append((pts, True))
                pts, cur = [], start
                last_c = last_q = None
                continue
        elif cmd is None:
            return None
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        if c == 'M':
            x, y = nums(2)
            if pts:
                subs.append((pts, False))
            cur = start = (ox + x, oy + y)
            pts = [cur]
            cmd = 'l' if rel else 'L'
        elif c == 'L':
            x, y = nums(2)
            cur = (ox + x, oy + y)
            pts.append(cur)
        elif c == 'H':
            (x,) = nums(1)
            cur = ((cur[0] if rel else 0) + x, cur[1])
            pts.append(cur)
        elif c == 'V':
            (y,) = nums(1)
            cur = (cur[0], (cur[1] if rel else 0) + y)
            pts.append(cur)
        elif c == 'C':
            v = nums(6)
            c1, c2, p1 = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3]), (ox + v[4], oy + v[5])
            pts += bez(cur, [c1, c2], p1)
            cur, last_c = p1, c2
            continue
        elif c == 'S':
            v = nums(4)
            c1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) if last_c else cur
            c2, p1 = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3])
            pts += bez(cur, [c1, c2], p1)
            cur, last_c = p1, c2
            continue
        elif c == 'Q':
            v = nums(4)
            q, p1 = (ox + v[0], oy + v[1]), (ox + v[2], oy + v[3])
            pts += bez(cur, [q], p1)
            cur, last_q = p1, q
            continue
        elif c == 'T':
            v = nums(2)
            q = (2 * cur[0] - last_q[0], 2 * cur[1] - last_q[1]) if last_q else cur
            p1 = (ox + v[0], oy + v[1])
            pts += bez(cur, [q], p1)
            cur, last_q = p1, q
            continue
        elif c == 'A':
            v = nums(7)
            p1 = (ox + v[5], oy + v[6])
            pts += _arc(cur, v[0], v[1], v[2], int(v[3]), int(v[4]), p1, step)
            cur = p1
        last_c = last_q = None
    if pts:
        subs.append((pts, len(pts) > 2 and math.dist(pts[0], pts[-1]) < 1e-3))
    return subs


def _shape_d(e) -> str | None:
    t = r2._local(e.tag)
    f = lambda k, dflt=0.0: float(re.match(r'-?[\d.]+(?:e-?\d+)?', e.get(k) or str(dflt)).group(0))
    if t == 'path':
        return e.get('d')
    if t in ('polygon', 'polyline'):
        v = re.findall(r'-?[\d.]+(?:e-?\d+)?', e.get('points') or '')
        if len(v) < 4:
            return None
        return 'M' + ' '.join(f'{v[k]},{v[k + 1]}' for k in range(0, len(v) - 1, 2)) + ('Z' if t == 'polygon' else '')
    if t == 'rect':
        x, y, w, h = f('x'), f('y'), f('width'), f('height')
        rx = f('rx', 0) if e.get('rx') else (f('ry', 0) if e.get('ry') else 0)
        ry = f('ry', 0) if e.get('ry') else rx
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx <= 0:
            return f'M{x},{y}H{x + w}V{y + h}H{x}Z'
        return (f'M{x + rx},{y}H{x + w - rx}A{rx},{ry} 0 0,1 {x + w},{y + ry}V{y + h - ry}A{rx},{ry} 0 0,1 {x + w - rx},{y + h}'
                f'H{x + rx}A{rx},{ry} 0 0,1 {x},{y + h - ry}V{y + ry}A{rx},{ry} 0 0,1 {x + rx},{y}Z')
    if t in ('circle', 'ellipse'):
        cx, cy = f('cx'), f('cy')
        rx = f('r') if t == 'circle' else f('rx')
        ry = f('r') if t == 'circle' else f('ry')
        return f'M{cx - rx},{cy}A{rx},{ry} 0 1,1 {cx + rx},{cy}A{rx},{ry} 0 1,1 {cx - rx},{cy}Z'
    if t == 'line':
        return f"M{f('x1')},{f('y1')}L{f('x2')},{f('y2')}"
    return None


def _paint(e, parents) -> dict:
    """Effective fill and stroke of an element (presentation attributes and style, inherited)."""
    out = {'fill': 'black', 'stroke': 'none'}
    for x in parents + [e]:
        for k in ('fill', 'stroke'):
            if x.get(k):
                out[k] = x.get(k).strip().lower()
            m = re.search(rf'(?:^|;)\s*{k}\s*:\s*([^;]+)', x.get('style') or '')
            if m:
                out[k] = m.group(1).strip().lower()
    return out


def _frame(root):
    """(mm per user unit, viewBox) when the SVG's size is in physical units and its aspect matches its viewBox."""
    mm = r2._doc_mm(root)
    vb = [float(v) for v in re.split(r'[\s,]+', (root.get('viewBox') or '').strip()) if v]
    if not mm or len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0:
        return None
    sx, sy = mm[0] / vb[2], mm[1] / vb[3]
    if abs(sx / sy - 1) > 0.01:
        return None
    return sx, vb, mm


def _svg_cut_paths(path: Path):
    """The cut paths of a separate cut file: every stroked, unfilled shape, as closed point lists in mm (transforms
    applied). Returns (paths, error)."""
    root = r2._svg_root(path)
    fr = _frame(root)
    if fr is None:
        return None, 'size not in millimetres or no viewBox'
    s = fr[0]
    out = []

    def walk(e, parents, m):
        m = m @ _tf(e.get('transform'))
        if r2._local(e.tag) in ('defs', 'clipPath', 'mask', 'symbol', 'style'):
            return
        if r2._local(e.tag) in SHAPES:
            p = _paint(e, parents)
            if p['stroke'] not in ('none', '') and p['fill'] in ('none', 'transparent'):
                subs = _path_subpaths(_shape_d(e), 0.02 / s)
                if subs is None:
                    raise ValueError('unreadable path data')
                for pts, closed in subs:
                    xy = np.array(pts, float)
                    xy = (np.c_[xy, np.ones(len(xy))] @ m.T)[:, :2] * s
                    out.append((xy, closed))
        for c in e:
            walk(c, parents + [e], m)
    try:
        walk(root, [], np.eye(3))
    except (ValueError, TypeError, IndexError) as ex:
        return None, f'path data not read: {ex}'
    return out, None


def _render_mm(svg_text: str, root, px_mm: float, pad_mm: float):
    """The SVG rendered at px_mm pixels per mm on a canvas padded by pad_mm: (alpha, x0_mm, y0_mm, mm per pixel)."""
    fr = _frame(root)
    if fr is None:
        return None
    s, vb, mm = fr
    width = max(16, int(round(mm[0] * px_mm)))
    arr = r2._render_svg_text(svg_text, width)
    k = mm[0] / arr.shape[1]
    pad = int(round(pad_mm / k))
    alpha = np.zeros((arr.shape[0] + 2 * pad, arr.shape[1] + 2 * pad), np.uint8)
    alpha[pad:pad + arr.shape[0], pad:pad + arr.shape[1]] = arr[..., 3]
    return alpha, vb[0] * s - pad * k, vb[1] * s - pad * k, k, arr


def _fill_holes(m: np.ndarray) -> np.ndarray:
    import cv2
    ff = np.zeros((m.shape[0] + 2, m.shape[1] + 2), np.uint8)
    ff[1:-1, 1:-1] = m.astype(np.uint8)
    mask = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, mask, (0, 0), 2)
    return ff[1:-1, 1:-1] != 2


def _resample(xy: np.ndarray, ds: float, closed=True) -> np.ndarray:
    if closed and math.dist(xy[0], xy[-1]) > 1e-9:
        xy = np.vstack([xy, xy[:1]])
    seg = np.hypot(*np.diff(xy, axis=0).T)
    keep = np.r_[True, seg > 1e-9]
    xy = xy[keep]
    seg = np.hypot(*np.diff(xy, axis=0).T)
    s = np.r_[0, np.cumsum(seg)]
    if s[-1] <= 0:
        return xy
    n = max(8, int(s[-1] / ds))
    t = np.linspace(0, s[-1], n, endpoint=not closed)
    return np.c_[np.interp(t, s, xy[:, 0]), np.interp(t, s, xy[:, 1])]


def _area(xy):
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _distances(samples_mm, alpha, x0, y0, k):
    """Distance (mm) from each sample to the nearest inked pixel (alpha >= 128), and whether it lies inside the
    artwork's filled outline (holes filled)."""
    import cv2
    ink = alpha >= 128
    dist = cv2.distanceTransform((~ink).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    filled = _fill_holes(ink)
    cols = (samples_mm[:, 0] - x0) / k - 0.5
    rows = (samples_mm[:, 1] - y0) / k - 0.5
    ok = (cols >= 0) & (rows >= 0) & (cols <= alpha.shape[1] - 1) & (rows <= alpha.shape[0] - 1)
    if not ok.all():
        return None, None
    d = cv2.remap(dist, cols.astype(np.float32).reshape(1, -1), rows.astype(np.float32).reshape(1, -1), cv2.INTER_LINEAR).ravel() * k
    inside = filled[np.round(rows).astype(int), np.round(cols).astype(int)]
    return d, inside


def _offset_verdict(d, inside, a):
    off, tol, fail_mm, share = a.get('offset_mm', 2.5), a.get('tol', 0.15), a.get('fail_mm', 0.5), a.get('min_share', 0.9)
    med, lo = float(np.median(d)), float(d.min())
    on = float((np.abs(d - off) <= tol).mean())
    ev = {'median_mm': round(med, 3), 'closest_mm': round(lo, 3), 'share_at_offset': round(on, 3),
          'inside_artwork_share': round(float(inside.mean()), 4)}
    if inside.any() or lo < off - fail_mm or abs(med - off) > fail_mm:
        return 'fail', ev
    if lo >= off - tol and abs(med - off) <= tol and on >= share:
        return 'pass', ev
    return PERSON, ev


def _art_layers_ok(art: Path, px_mm):
    """The artwork's alpha in mm (cut layer left out); live type that changes the outer edge goes to a person."""
    root = r2._svg_root(art)
    text = r2._svg_without_cut(art)
    got = _render_mm(text, root, px_mm, 12.0)
    if got is None:
        return None, 'artwork size not in millimetres or no viewBox'
    if any(r2._local(e.tag) == 'text' for e in ET.fromstring(text).iter()):
        t2 = ET.fromstring(text)
        for parent in list(t2.iter()):
            for c in list(parent):
                if r2._local(c.tag) == 'text':
                    parent.remove(c)
        ET.register_namespace('', 'http://www.w3.org/2000/svg')
        alt = _render_mm(ET.tostring(t2, encoding='unicode'), root, px_mm, 12.0)
        if alt is None or alt[0].shape != got[0].shape or (_fill_holes(alt[0] >= 128) != _fill_holes(got[0] >= 128)).sum() > 0:
            return None, 'live type reaches the artwork edge (its font decides the edge)'
    return got, None


# ================================================================ cut path offset and corners

def op_cut_offset(path, a):
    """The cut path sits offset_mm (2.5) outside the artwork's edge all the way round. SVG cut file: its stroked,
    unfilled paths, against the delivered artwork SVG (cut layer left out) rendered at px_mm (40) px per mm in the same mm
    coordinates; PDF sheet: every path on the cut layer against the page rendered (px_mm) with the cut layer off, inside that
    path's box. Distances are read every 0.02 mm along the outer cut path. Pass: closest point at least offset_mm
    minus tol (0.15 mm), median within tol of offset_mm, and min_share (90%) of the path within tol of it (the rest
    may lie further out where rounded corners bridge inlets). Fail: the path runs into the artwork, comes closer than
    offset_mm minus fail_mm (0.5 mm), or its median is more than fail_mm off. Else a person; also a person: a second
    cut path in the file, live type forming the edge, or files that only agree when centred on each other."""
    px_mm = a.get('px_mm', 40)
    if path.suffix.lower() == '.pdf':
        return _sheet_offset(path, a)
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG or PDF'}
    art = Path(a['_artifacts']) / a['deliverable']
    if not art.is_file():
        return PERSON, {'reason': 'the artwork file is not available'}
    cuts, err = _svg_cut_paths(path)
    if err or not cuts:
        return PERSON, {'reason': err or 'no stroked cut path'}
    closed = [xy for xy, c in cuts if c and len(xy) > 3]
    if not closed:
        return 'fail', {'reason': 'no closed cut path'}
    outer = max(closed, key=_area)
    got, err = _art_layers_ok(art, px_mm)
    if err:
        return PERSON, {'reason': err}
    alpha, x0, y0, k, _ = got
    samples = _resample(outer, 0.02)
    d, inside = _distances(samples, alpha, x0, y0, k)
    if d is None:
        return PERSON, {'reason': 'the cut path lies far outside the artwork canvas'}
    st, ev = _offset_verdict(d, inside, a)
    if len(closed) > 1 and st != 'fail':
        return PERSON, dict(ev, reason='more than one closed cut path in the file', paths=len(closed))
    if st == 'fail':
        # the two files may not share an origin: centred on each other, would the path sit right?
        ys, xs = np.where(alpha >= 128)
        art_c = np.array([x0 + (xs.min() + xs.max() + 1) / 2 * k, y0 + (ys.min() + ys.max() + 1) / 2 * k])
        cut_c = (outer.min(axis=0) + outer.max(axis=0)) / 2
        shift = art_c - cut_c
        if np.hypot(*shift) > 0.2:
            d2, in2 = _distances(samples + shift, alpha, x0, y0, k)
            if d2 is not None and _offset_verdict(d2, in2, a)[0] == 'pass':
                return PERSON, dict(ev, reason='the files agree only when centred on each other (origins differ?)',
                                    shift_mm=[round(float(v), 2) for v in shift])
    return st, ev


def _sheet_render_clip(key, page_no, rect, px_mm):
    """A sheet page area rendered with every cut layer turned off: (rgb, x0_pt, y0_pt, pt per pixel)."""
    import pymupdf
    doc = pymupdf.open(key)
    off = [x for x, v in doc.get_ocgs().items() if l3.CUT_RX.search(v.get('name') or '')]
    if off:
        doc.set_layer(-1, off=off)
        for c in doc.layer_ui_configs():
            if l3.CUT_RX.search(c.get('text') or ''):
                doc.set_layer_ui_config(c['number'], 2)
    page = doc[page_no]
    zoom = px_mm / PT_MM
    clip = pymupdf.Rect(rect)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False)
    rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
    return rgb, clip.x0, clip.y0, 1 / zoom, bool(off)


def _sheet_offset(path, a):
    px_mm = a.get('px_mm', 40)
    key = str(path)
    cuts = l3._sheet_cuts(key)
    if not cuts:
        return PERSON, {'reason': 'no cut paths found'}
    worst, evs = None, []
    order = {'fail': 2, PERSON: 1, 'pass': 0}
    for n, d in cuts:
        pts = l3._bezier_points(d, 0.05)
        if len(pts) < 4:
            return PERSON, {'reason': 'a cut path not read'}
        r = d['rect']
        pad = 1.0
        rgb, x0, y0, k, had_layer = _sheet_render_clip(key, n, (r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad), px_mm)
        if not had_layer:
            return PERSON, {'reason': 'the cut paths are not on their own layer, so the artwork cannot be shown without them'}
        ink = (np.abs(rgb.astype(int) - 255).max(axis=2) > 12)
        # the artwork: ink inside the cut path (anything outside it, such as a label, is left out)
        import cv2
        poly = np.round((pts - [x0, y0]) / k).astype(np.int32)
        inner = np.zeros(ink.shape, np.uint8)
        cv2.fillPoly(inner, [poly], 1)
        outside_ink = ink & ~cv2.dilate(inner, np.ones((5, 5), np.uint8)).astype(bool)
        # the cut stroke itself (and its anti-aliasing) is never artwork: a band of half its width plus 2 px round it
        band = np.zeros(ink.shape, np.uint8)
        cv2.polylines(band, [poly], True, 1, thickness=int(2 * math.ceil((d.get('width') or 0) / 2 / k + 2)) + 1)
        ink &= ~band.astype(bool)
        outside_ink &= ~band.astype(bool)
        art = ink & inner.astype(bool)
        if not art.any():
            return PERSON, {'reason': 'no artwork inside a cut path'}
        alpha = np.where(art, 255, 0).astype(np.uint8)
        samples = _resample(pts / PT_MM, 0.02) * PT_MM
        dd, inside = _distances(samples, alpha, x0, y0, k)
        if dd is None:
            return PERSON, {'reason': 'cut path outside its render'}
        st, ev = _offset_verdict(dd / PT_MM, inside, a)
        # ink right outside the path along it: artwork cut through (the path runs into the art)
        ring = cv2.dilate(inner, np.ones((5, 5), np.uint8)).astype(bool) & ~cv2.erode(inner, np.ones((5, 5), np.uint8)).astype(bool)
        if (outside_ink & cv2.dilate(ring.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)).sum() > 20:
            st, ev = 'fail', dict(ev, reason='artwork ink runs across the cut path')
        evs.append(ev)
        if worst is None or order[st] > order[worst]:
            worst = st
    return worst, {'stickers': evs}


def _corner_stats(xy: np.ndarray, a):
    """Smallest radius of curvature along a closed path (mm): resampled every 0.02 mm and smoothed with a Gaussian
    of sigma_mm (0.5 mm, so a curve drawn as short straight pieces reads as the curve), and the sharpest turn over
    any turn_window_mm (0.3 mm) of the path smoothed at turn_sigma_mm (0.1 mm, so one-pixel jogs of a traced outline
    are not read as corners), in degrees."""
    ds = 0.02
    p = _resample(xy, ds)
    n = len(p)
    sig = a.get('sigma_mm', 0.5) / ds
    half = int(4 * sig)
    kern = np.exp(-0.5 * (np.arange(-half, half + 1) / sig) ** 2)
    kern /= kern.sum()
    if n <= 2 * half + 2:
        return None
    ext = np.vstack([p[-half:], p, p[:half]])
    sm = np.c_[np.convolve(ext[:, 0], kern, 'valid'), np.convolve(ext[:, 1], kern, 'valid')]
    d1 = (np.roll(sm, -1, 0) - np.roll(sm, 1, 0)) / (2 * ds)
    d2 = (np.roll(sm, -1, 0) - 2 * sm + np.roll(sm, 1, 0)) / ds ** 2
    curv = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / np.maximum(np.hypot(d1[:, 0], d1[:, 1]) ** 3, 1e-12)
    r_min = float(1 / max(curv.max(), 1e-9))
    w = max(1, int(a.get('turn_window_mm', 0.3) / ds / 2))
    sig2 = a.get('turn_sigma_mm', 0.1) / ds
    h2 = int(4 * sig2)
    k2 = np.exp(-0.5 * (np.arange(-h2, h2 + 1) / sig2) ** 2)
    k2 /= k2.sum()
    e2 = np.vstack([p[-h2:], p, p[:h2]])
    p = np.c_[np.convolve(e2[:, 0], k2, 'valid'), np.convolve(e2[:, 1], k2, 'valid')]
    head = np.arctan2(*(np.roll(p, -1, 0) - p)[:, ::-1].T)
    turn = np.abs((np.roll(head, -w) - np.roll(head, w) + np.pi) % (2 * np.pi) - np.pi)
    return r_min, float(np.degrees(turn.max())), p[int(curv.argmax())]


def _corner_verdict(stats, a):
    radius, tol, fail_r, max_turn = a.get('radius_mm', 3.0), a.get('tol', 0.15), a.get('fail_mm', 2.2), a.get('max_turn_deg', 25)
    r_min, turn, where = stats
    ev = {'smallest_radius_mm': round(r_min, 2), 'sharpest_turn_deg': round(turn, 1), 'at_mm': [round(float(v), 1) for v in where]}
    if r_min < fail_r:
        return 'fail', ev
    if r_min >= radius - tol and turn <= max_turn:
        return 'pass', ev
    return PERSON, ev


def op_cut_corners(path, a):
    """Every corner of the cut path has a radius of at least radius_mm (3). The path (SVG: every stroked, unfilled
    closed shape of the cut file, transforms applied; PDF: every path on the cut layer) is read exactly from its
    geometry. Pass: smallest radius of curvature (sigma_mm smoothing) at least radius_mm minus tol (0.15 mm) and no
    turn sharper than max_turn_deg (25 degrees) within turn_window_mm (0.3 mm); fail: a radius under fail_mm (2.2 mm:
    a true radius well under 3 mm, or a sharp corner turning about 33 degrees or more); between, a person. A sharp
    bend turning less than max_turn_deg is not told apart from a curve drawn as short straight pieces."""
    order = {'fail': 2, PERSON: 1, 'pass': 0}
    if path.suffix.lower() == '.pdf':
        cuts = l3._sheet_cuts(str(path))
        if not cuts:
            return PERSON, {'reason': 'no cut paths found'}
        paths = [l3._bezier_points(d, 0.05) / PT_MM for n, d in cuts]
    elif path.suffix.lower() == '.svg':
        cuts, err = _svg_cut_paths(path)
        if err or not cuts:
            return PERSON, {'reason': err or 'no stroked cut path'}
        paths = [xy for xy, c in cuts if c and len(xy) > 3]
        if not paths:
            return 'fail', {'reason': 'no closed cut path'}
    else:
        return PERSON, {'reason': 'read from the SVG or PDF'}
    worst, evs = 'pass', []
    outer = max(range(len(paths)), key=lambda i: _area(paths[i]))
    for i, xy in enumerate(paths):
        stats = _corner_stats(xy, a)
        if stats is None:
            return PERSON, {'reason': 'a cut path too short to read'}
        st, ev = _corner_verdict(stats, a)
        if i != outer and path.suffix.lower() == '.svg' and st == 'fail':
            st = PERSON          # a second path in a cut file (another rule's defect): its corners go to a person
            ev['second_path'] = True
        evs.append(ev)
        if order[st] > order[worst]:
            worst = st
    return worst, {'paths': evs}


# ================================================================ SVG ink: solid, no shadow (R100)

def _artwork_elements(root):
    cut = {id(x) for g in l3._cut_groups(root) for x in g.iter()}
    return [e for e in root.iter() if id(e) not in cut]


def op_svg_solid_ink(path, a):
    """SVG artwork (any separate cut layer left out) is solid ink: no opacity, fill-opacity or stroke-opacity under 1,
    no gradient, pattern, filter or mask in use, no mix-blend-mode (attributes, styles and CSS rules read), no
    embedded picture, and no shape repeated at a small offset behind itself (a hard shadow: the same geometry drawn
    twice, the copies up to max_shift_mm (5 mm) apart). Colours are not judged here (palette rules do that)."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    root = r2._svg_root(path)
    els = _artwork_elements(root)
    bad = []
    used = set()
    for e in els:
        style = (e.get('style') or '') + ';' + ';'.join(f'{r2._local(k)}:{v}' for k, v in e.attrib.items())
        used |= set(re.findall(r'url\(\s*#([^)\s]+)\s*\)', style))
        for m in re.finditer(r'(?:^|;)\s*((?:fill-|stroke-)?opacity)\s*:\s*([\d.]+)(%?)', style):
            v = float(m.group(2)) / (100 if m.group(3) else 1)
            if v < 0.999:
                bad.append(f'{m.group(1)} {m.group(2)}{m.group(3)}')
        if re.search(r'mix-blend-mode\s*:\s*(?!normal)', style):
            bad.append('blend mode')
    css = ' '.join(x.text or '' for x in root.iter() if r2._local(x.tag) == 'style')
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', css)
    for m in re.finditer(r'opacity\s*:\s*([\d.]+)(%?)', css):
        if float(m.group(1)) / (100 if m.group(2) else 1) < 0.999:
            bad.append(f'css opacity {m.group(1)}')
    if re.search(r'gradient|mix-blend-mode\s*:\s*(?!normal)|filter\s*:\s*(?!none)|mask\s*:', css):
        bad.append('css gradient, blend, filter or mask')
    used |= set(re.findall(r'url\(\s*#([^)\s]+)\s*\)', css))
    for e in root.iter():
        if r2._local(e.tag) in ('linearGradient', 'radialGradient', 'pattern', 'filter', 'mask') and e.get('id') in used:
            bad.append(f'{r2._local(e.tag)} in use')
    if any(r2._local(e.tag) == 'image' for e in els):
        return PERSON, {'reason': 'an embedded picture in the artwork'}
    # the same shape drawn twice, a small offset apart (a hard shadow)
    fr = _frame(root)
    s = fr[0] if fr else None
    seen = {}

    def walk(e, m):
        m = m @ _tf(e.get('transform'))
        if r2._local(e.tag) in ('defs', 'clipPath', 'mask', 'symbol', 'style'):
            return
        if r2._local(e.tag) in SHAPES:
            d = _shape_d(e)
            if d:
                seen.setdefault(re.sub(r'\s+', ' ', d.strip()), []).append(m)
        for c in e:
            if id(c) in cut_ids:
                continue
            walk(c, m)
    cut_ids = {id(x) for g in l3._cut_groups(root) for x in g.iter()}
    walk(root, np.eye(3))
    shadows = []
    for d, ms in seen.items():
        for i in range(len(ms)):
            for j in range(i + 1, len(ms)):
                lin = np.abs(ms[i][:2, :2] - ms[j][:2, :2]).max()
                shift = np.hypot(*(ms[i][:2, 2] - ms[j][:2, 2])) * (s or 1)
                if lin < 1e-6 and 0 < shift and (s is None or shift <= a.get('max_shift_mm', 5)):
                    shadows.append(round(float(shift), 2))
    if shadows:
        bad.append(f'a shape repeated {shadows[0]} {"mm" if s else "units"} behind itself (hard shadow)')
    if bad:
        return 'fail', {'not_solid': sorted(set(bad))[:5]}
    return 'pass', {'reason': 'solid ink: no opacity, gradient, filter, blend mode or repeated offset shape'}


# ================================================================ proofs against their SVG

def _proof_rgba(path):
    return np.asarray(Image.open(path).convert('RGBA')).astype(np.int16)


def _box(m):
    ys, xs = np.where(m)
    return (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1) if len(xs) else None


def _aligned(path: Path, svg: Path, thin_px: int):
    """Proof crop and the SVG (cut layer left out) rendered and resized to it, aligned on the ink boxes; thin ink
    (pieces no more than thin_px across, such as a drawn line) is left out of the proof's box."""
    import cv2
    proof = _proof_rgba(path)
    pa = (proof[..., 3] > 128).astype(np.uint8)
    k = 2 * thin_px + 1
    solid = cv2.morphologyEx(pa, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    pbox = _box(solid)
    if pbox is None:
        return None
    text = r2._svg_without_cut(svg)
    probe = r2._render_svg_text(text, 800)
    pb = _box(probe[..., 3] > 128)
    if pb is None:
        return None
    frac = (pb[2] - pb[0]) / probe.shape[1]
    width = int(round((pbox[2] - pbox[0]) / max(frac, 1e-6)))
    rend = r2._render_svg_text(text, max(16, width)).astype(np.int16)
    rbox = _box(rend[..., 3] > 128)
    pw, ph = pbox[2] - pbox[0], pbox[3] - pbox[1]
    rw, rh = rbox[2] - rbox[0], rbox[3] - rbox[1]
    aspect = abs((pw / ph) / (rw / rh) - 1)
    crop_r = cv2.resize(rend[rbox[1]:rbox[3], rbox[0]:rbox[2]].astype(np.uint8), (pw, ph), interpolation=cv2.INTER_AREA).astype(np.int16)
    return proof, pbox, crop_r, aspect, solid


def _has_text(svg: Path) -> bool:
    return any(r2._local(e.tag) == 'text' for e in r2._svg_root(svg).iter())


def _text_keep(svg: Path, shape, grow_px: int):
    """Pixels of a proof crop (shape) away from the SVG's live type (its text rendered alone, aligned on the SVG's ink
    box, grown by grow_px): all True when the SVG has no live type."""
    import cv2
    if not _has_text(svg):
        return np.ones(shape, bool)
    t = ET.fromstring(r2._svg_without_cut(svg))
    for parent in list(t.iter()):
        for c in list(parent):
            if r2._local(c.tag) in SHAPES + ('image', 'use'):
                parent.remove(c)
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    probe = r2._render_svg_text(r2._svg_without_cut(svg), 800)
    pb = _box(probe[..., 3] > 128)
    full = r2._render_svg_text(ET.tostring(t, encoding='unicode'), 800)
    tm = (full[pb[1]:pb[3], pb[0]:pb[2], 3] > 0).astype(np.uint8)
    tm = cv2.resize(tm, (shape[1], shape[0]), interpolation=cv2.INTER_NEAREST)
    return ~(cv2.dilate(tm, np.ones((2 * grow_px + 1, 2 * grow_px + 1), np.uint8)) > 0)


def op_proof_same(path, a):
    """A transparent proof shows its delivered SVG unchanged: the SVG (cut layer left out) rendered at the proof's ink
    size, aligned on the ink boxes. Shape: ink masks overlapping at IoU min_iou (0.97) or more, proportions within
    max_aspect (2%). Opacity: over max_opacity_share (1%) of the ink (its 2 px edge left out) differing in opacity by
    more than 16 levels (either way), or ink (alpha over 16) on over max_opacity_share of the area where the SVG has
    none, fails (live type and 10 px round it left out). Colour, region by region: among pixels flat in both images,
    a patch of min_px (150) or more pixels whose colour differs by far (30) or more on a channel is a changed region.
    Pass: shape holds, no changed region and at most max_changed_share (0.1%) of the ink differing; fail: IoU under
    fail_iou (0.9), proportions max_aspect or more apart, or a changed region; else a person.
    Where the SVG has live type (rendered in a stand-in font, as an embedded web font is not loaded) the check never
    passes or fails on colour: a person."""
    import cv2
    svg = Path(a['_artifacts']) / a['deliverable']
    if path.suffix.lower() != '.png' or not svg.is_file():
        return PERSON, {'reason': 'proof or SVG not available'}
    got = _aligned(path, svg, 0)
    if got is None:
        return PERSON, {'reason': 'nothing drawn'}
    proof, pbox, crop_r, aspect, _ = got
    crop_p = proof[pbox[1]:pbox[3], pbox[0]:pbox[2]]
    mp, mr = crop_p[..., 3] > 128, crop_r[..., 3] > 128
    iou = float((mp & mr).sum() / max(1, (mp | mr).sum()))
    flat = r3._flat(crop_r[..., :3], 2) & r3._flat(crop_p[..., :3], 2) & (crop_p[..., 3] >= 250) & (crop_r[..., 3] >= 250)
    diff = np.abs(crop_p[..., :3] - crop_r[..., :3]).max(axis=2)
    changed = flat & (diff >= a.get('far', 30))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(changed.astype(np.uint8), connectivity=8)
    big = sorted((int(st[4]) for st in stats[1:] if st[4] >= a.get('min_px', 150)), reverse=True)
    share = float(changed.sum() / max(1, mp.sum()))
    ev = {'iou': round(iou, 4), 'aspect_change': round(aspect, 4), 'changed_regions_px': big[:5], 'changed_share': round(share, 4)}
    text = _has_text(svg)
    # opacity: the proof's ink as opaque as the SVG's, and no ink where the SVG has none
    keep = _text_keep(svg, mp.shape, 10)
    # opacity differing either way by more than 16 levels inside the ink (edges, 2 px, left out): see-through ink where
    # the SVG is opaque, or the reverse
    core = cv2.erode((mp & mr).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    see_through = float(((np.abs(crop_r[..., 3] - crop_p[..., 3]) > 16) & core & keep).sum() / max(1, (core & keep).sum()))
    outside = np.ones(proof.shape[:2], bool)
    outside[pbox[1]:pbox[3], pbox[0]:pbox[2]] = (crop_r[..., 3] <= 16) & keep
    extra = float(((proof[..., 3] > 16) & outside).sum() / max(1, outside.sum()))
    ev.update(see_through_share=round(see_through, 4), extra_ink_share=round(extra, 4))
    if see_through > a.get('max_opacity_share', 0.01) or extra > a.get('max_opacity_share', 0.01):
        return 'fail', dict(ev, reason='the proof\'s ink is see-through, or ink lies where the SVG has none')
    if iou < a.get('fail_iou', 0.9) or aspect >= a.get('max_aspect', 0.02):
        return ('fail', ev) if not text else (PERSON, dict(ev, reason='live type in the SVG'))
    if text:
        return PERSON, dict(ev, reason='live type in the SVG: its font is not rendered, so a person compares')
    if big:
        return 'fail', ev
    if iou >= a.get('min_iou', 0.97) and aspect < a.get('max_aspect', 0.02) and share <= a.get('max_changed_share', 0.001):
        return 'pass', ev
    return PERSON, ev


def op_proof_open(path, a):
    """The open space of a transparent proof is transparent: wherever its SVG has no ink (beyond a 2 px edge band),
    filled areas of the proof are counted; thin strokes (pieces no more than thin_px (12) pixels across, such as a cut
    line drawn round the art) are left out, as another rule judges them. Filled ink over max_share (2%) of that space
    fails; 2% or less passes; a proof with no transparent pixel at all (its SVG having open space) fails. Proportions
    2% or more apart, or live type in the SVG with a fill found, go to a person."""
    import cv2
    svg = Path(a['_artifacts']) / a['deliverable']
    if path.suffix.lower() != '.png' or not svg.is_file():
        return PERSON, {'reason': 'proof or SVG not available'}
    thin = a.get('thin_px', 12)
    got = _aligned(path, svg, thin)
    if got is None:
        return PERSON, {'reason': 'nothing drawn'}
    proof, pbox, crop_r, aspect, _ = got
    crop_p = proof[pbox[1]:pbox[3], pbox[0]:pbox[2]]
    mr = crop_r[..., 3] > 128
    empty = cv2.erode((~mr).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    # the whole canvas outside the box counts as open space too (a rectangle behind the sticker fills it)
    outside = np.ones(proof.shape[:2], bool)
    outside[pbox[1]:pbox[3], pbox[0]:pbox[2]] = False
    k = 2 * thin + 1
    opaque = (proof[..., 3] > 16).astype(np.uint8)
    filled = cv2.morphologyEx(opaque, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    inner_share = float(filled[pbox[1]:pbox[3], pbox[0]:pbox[2]][empty].mean()) if empty.sum() >= 100 else 0.0
    out_share = float(filled[outside].mean()) if outside.sum() >= 100 else 0.0
    ev = {'filled_share_of_open_space': round(inner_share, 4), 'filled_share_outside_art': round(out_share, 4), 'aspect_change': round(aspect, 4)}
    if (proof[..., 3] < 250).mean() < 0.001 and (~mr).mean() >= 0.01:
        return 'fail', dict(ev, reason='the proof has no transparent pixel, though its SVG has open space')
    if inner_share <= a.get('max_share', 0.02) and out_share <= a.get('max_share', 0.02):
        return 'pass', ev
    if aspect < 0.02 and not (_has_text(svg) and inner_share > a.get('max_share', 0.02) and out_share <= a.get('max_share', 0.02)):
        return 'fail', ev
    return PERSON, ev


def op_proof_flat(path, a):
    """Apart from anti-aliased edges, every inked area of a proof is flat and opaque with no shadow: the round-3 soft
    test (objective ops v2_soft_edges: gradients, glows, blurs, see-through ink) fails a proof; then its SVG is read for
    hard shadows (op_svg_solid_ink): a shadow there, with the proof showing that SVG (ink masks at IoU 0.97 or more),
    fails; a proof showing its solid SVG (IoU 0.97 or more, no ink beyond the SVG's) passes; else a person. Colours
    are not judged (palette rules do that)."""
    st, ev = l3.op_soft_edges(path, a)
    if st == 'fail':
        return st, ev
    svg = Path(a['_artifacts']) / a['deliverable'] if a.get('deliverable') else None
    if not svg or not svg.is_file():
        return PERSON, {'reason': 'the proof\'s SVG is not available, so a hard shadow is not ruled out'}
    sst, sev = op_svg_solid_ink(svg, a)
    got = _aligned(path, svg, 0)
    if got is None:
        return PERSON, {'reason': 'nothing drawn'}
    proof, pbox, crop_r, aspect, _ = got
    crop_p = proof[pbox[1]:pbox[3], pbox[0]:pbox[2]]
    mp, mr = crop_p[..., 3] > 128, crop_r[..., 3] > 128
    iou = float((mp & mr).sum() / max(1, (mp | mr).sum()))
    ev = {'soft_test': st, 'svg_solid': sst, 'iou_with_svg': round(iou, 4)}
    if iou >= 0.97 and aspect < 0.02:
        if sst == 'fail' and any('shadow' in x for x in sev.get('not_solid', [])):
            return 'fail', dict(ev, reason='the proof shows its SVG\'s hard shadow')
        if sst == 'pass' and st == 'pass':
            return 'pass', ev
    return PERSON, ev


def op_proof_no_cutline(path, a):
    """A proof shows no cut line drawn into the artwork. Fail: a thin line (a piece no more than thin_px (12) pixels
    across) runs round the whole artwork with open space between, at a steady distance (the cut path drawn in), or
    a long thin piece in the cut-line magenta (#EC008C or #FF00FF, within 40; over 100 px, 30% of the art's width or
    height or more, filling no more than 10% of its own box), or, against its SVG, a thin line of
    changed colour running round cover (85%) or more of the art's width and height inside its edge. Pass: none of these, and
    the proof shows its SVG (ink masks at IoU 0.97 or more, solid colours outside the SVG's live type the same) whose
    own artwork has no cut line (objective ops svg_no_cutline). Else a person."""
    import cv2
    if path.suffix.lower() != '.png':
        return PERSON, {'reason': 'read from the proof image'}
    thin = a.get('thin_px', 12)
    proof = _proof_rgba(path)
    opaque = (proof[..., 3] > 128).astype(np.uint8)
    k = 2 * thin + 1
    solid = cv2.morphologyEx(opaque, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    thin_ink = opaque.astype(bool) & ~cv2.dilate(solid.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    rgb = proof[..., :3]
    mag = np.zeros(opaque.shape, bool)
    for h in ('#EC008C', '#FF00FF'):
        mag |= (np.abs(rgb - r3._hex_rgb(h)).max(axis=2) <= 40)
    mag &= opaque.astype(bool)
    ev = {}
    sb = _box(solid)
    if sb is None:
        return PERSON, {'reason': 'nothing drawn'}
    nm, _, stm, _ = cv2.connectedComponentsWithStats(mag.astype(np.uint8), connectivity=8)
    for x, y, w, h, area in stm[1:]:
        # a long thin piece in the cut-line magenta (inside or outside the art): 30% of the art's width or height or
        # more, filling no more than 10% of its own box
        if area > 100 and (w >= 0.3 * (sb[2] - sb[0]) or h >= 0.3 * (sb[3] - sb[1])) and area <= 0.1 * w * h:
            return 'fail', {'reason': 'a thin line in the cut-line magenta', 'pixels': int(area)}
    n, lab, stats, _ = cv2.connectedComponentsWithStats(thin_ink.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if x <= sb[0] and y <= sb[1] and x + w >= sb[2] and y + h >= sb[3] and area >= 200:
            ring = lab == i
            dist = cv2.distanceTransform((~solid).astype(np.uint8), cv2.DIST_L2, 5)
            dd = dist[ring]
            ev = {'ring_px': int(area), 'median_gap_px': round(float(np.median(dd)), 1), 'gap_spread_px': round(float(np.percentile(dd, 90) - np.percentile(dd, 10)), 1)}
            if np.median(dd) >= 5 and np.percentile(dd, 10) >= 0.5 * np.median(dd):
                return 'fail', dict(ev, reason='a thin line runs round the whole artwork at a steady distance')
            return PERSON, dict(ev, reason='a thin line runs round the artwork')
    svg = Path(a['_artifacts']) / a['deliverable'] if a.get('deliverable') else None
    if not svg or not svg.is_file():
        return PERSON, {'reason': 'the proof\'s SVG is not available'}
    if r2.op_svg_no_cutline(svg, {})[0] != 'pass':
        return PERSON, {'reason': 'the SVG itself has a line drawn into the art'}
    got = _aligned(path, svg, 0)
    if got is None:
        return PERSON, {'reason': 'nothing drawn'}
    proof, pbox, crop_r, aspect, _ = got
    crop_p = proof[pbox[1]:pbox[3], pbox[0]:pbox[2]]
    mp, mr = crop_p[..., 3] > 128, crop_r[..., 3] > 128
    iou = float((mp & mr).sum() / max(1, (mp | mr).sum()))
    # live type is left out of the colour comparison (its stand-in font differs)
    keep = _text_keep(svg, mp.shape, 20)
    flat = r3._flat(crop_r[..., :3], 2) & r3._flat(crop_p[..., :3], 2) & (crop_p[..., 3] >= 250) & (crop_r[..., 3] >= 250) & keep
    changed = flat & (np.abs(crop_p[..., :3] - crop_r[..., :3]).max(axis=2) >= 30)
    nn, _, st2, _ = cv2.connectedComponentsWithStats(cv2.dilate(changed.astype(np.uint8), np.ones((5, 5), np.uint8)), connectivity=8)
    big = [int(s[4]) for s in st2[1:] if s[4] >= 150]
    H, Wd = mp.shape
    for x, y, w, h, area in st2[1:]:
        # a thin line of changed colour running round most of the art inside its edge: a cut line drawn into it
        if iou >= 0.97 and aspect < 0.02 and w >= a.get('cover', 0.85) * Wd and h >= a.get('cover', 0.85) * H and area <= 0.08 * w * h:
            return 'fail', {'reason': 'a thin line drawn round the artwork inside its edge', 'line_box_px': [int(x), int(y), int(w), int(h)],
                            'line_px': int(area)}
    ev = {'iou_with_svg': round(iou, 4), 'changed_regions_px': sorted(big, reverse=True)[:4], 'aspect_change': round(aspect, 4)}
    if iou >= 0.97 and aspect < 0.02 and not big:
        return 'pass', ev
    return PERSON, ev


# ================================================================ production sheet: cut lines in the art, notes

def op_sheet_no_cutline(path, a):
    """No cut line drawn into the sticker artwork on a production sheet: inside each cut path's box, no drawing off
    the cut layer is an unfilled stroke whose box covers cover (85%) or more of that sticker's artwork box, and no
    drawing off the cut layer is stroked in a cut spot colour. The page's drawing list is read completely; no cut
    paths go to a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    cuts = l3._sheet_cuts(key)
    if not cuts:
        return PERSON, {'reason': 'no cut paths found'}
    paints = l3._pdf_paint(key)
    spot_strokes = [o for o in paints if o['kind'] == 'path' and o['what'] == 'stroke' and o['cs'].startswith('spot:')
                    and l3.CUT_RX.search(o['cs']) and not any(l3.CUT_RX.search(n) for n in o['layers'])]
    if spot_strokes:
        return 'fail', {'reason': 'a cut spot colour stroke off the cut layer', 'count': len(spot_strokes)}
    bad = []
    pages = l3._pdf_pages(key)
    for n, cd in cuts:
        b = (cd['rect'].x0, cd['rect'].y0, cd['rect'].x1, cd['rect'].y1)
        inside = [d for d in pages[n]['drawings'] if not l3.CUT_RX.search(d.get('layer') or '')
                  and l3._within((d['rect'].x0, d['rect'].y0, d['rect'].x1, d['rect'].y1), b, 0.5)]
        if not inside:
            continue
        art = (min(d['rect'].x0 for d in inside), min(d['rect'].y0 for d in inside), max(d['rect'].x1 for d in inside), max(d['rect'].y1 for d in inside))
        art_area = max(1e-6, (art[2] - art[0]) * (art[3] - art[1]))
        for d in inside:
            if d.get('type') == 's' and d.get('fill') is None:
                r = d['rect']
                cover = (r.x1 - r.x0) * (r.y1 - r.y0) / art_area
                if cover >= a.get('cover', 0.85):
                    bad.append({'box_pt': [round(v) for v in (r.x0, r.y0, r.x1, r.y1)], 'cover': round(cover, 2)})
    if bad:
        return 'fail', {'reason': 'an unfilled stroke round a sticker\'s artwork', 'strokes': bad[:3]}
    return 'pass', {'stickers': len(cuts)}


def op_sheet_notes(path, a):
    """A production sheet carries a note for each sticker matching a pattern (weeding of interior islands: the words
    weed or island): live text lines read from the PDF; each cut path's nearest note line (by distance between boxes)
    must be its own. Pass: every sticker has a matching line nearer to it than to any other sticker; fail: the sheet's
    live text has fewer matching lines than stickers, with live labels present (the text layer is read completely);
    else a person (no live text: the notes may be outlines)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    cuts = l3._sheet_cuts(key)
    if not cuts:
        return PERSON, {'reason': 'no cut paths found'}
    layer = base.pdf_layer(key)
    lines = [l for l in layer.lines if l.text.strip()]
    if not lines:
        return PERSON, {'reason': 'no live text on the sheet'}
    rx = re.compile(a.get('pattern', r'weed|island'), re.I)
    notes = [l for l in lines if rx.search(l.text)]
    if len(notes) < len(cuts):
        return 'fail', {'stickers': len(cuts), 'note_lines': len(notes), 'notes': [l.text[:60] for l in notes[:6]]}

    def gap(b, r):
        dx = max(r.x0 - b[2], b[0] - r.x1, 0)
        dy = max(r.y0 - b[3], b[1] - r.y1, 0)
        return math.hypot(dx, dy)
    boxes = [(n, cd['rect']) for n, cd in cuts]
    owner = {}
    for l in notes:
        page = getattr(l, 'page', 0) or 0
        b = l.bbox
        cand = [(gap(b, r), i) for i, (n, r) in enumerate(boxes) if n == page]
        if cand:
            owner.setdefault(min(cand)[1], []).append(l.text[:60])
    missing = [i for i in range(len(boxes)) if i not in owner]
    ev = {'stickers': len(cuts), 'notes_by_sticker': {str(i): v for i, v in owner.items()}}
    if not missing:
        return 'pass', ev
    return PERSON, dict(ev, reason='a sticker with no note beside it', missing=missing)


# ================================================================ live SVG type: family, weight, case, ampersand

def _css_rules(root):
    css = ' '.join(x.text or '' for x in root.iter() if r2._local(x.tag) == 'style')
    css = re.sub(r'@font-face\s*\{[^}]*\}', '', css)
    rules = {}
    for sel, body in re.findall(r'([^{}]+)\{([^}]*)\}', css):
        for s in sel.split(','):
            s = s.strip()
            if re.fullmatch(r'[.#]?[\w-]+', s):
                rules.setdefault(s, '')
                rules[s] += ';' + body
    return rules


PROPS = ('font-family', 'font-size', 'font-weight', 'font-style', 'text-transform', 'baseline-shift', 'letter-spacing')


def _props(e, inherited: dict, rules: dict) -> dict:
    p = dict(inherited)
    srcs = [rules.get(r2._local(e.tag), '')]
    for c in (e.get('class') or '').split():
        srcs.append(rules.get('.' + c, ''))
    if e.get('id'):
        srcs.append(rules.get('#' + e.get('id'), ''))
    for k in PROPS:
        if e.get(k) is not None:
            p[k] = e.get(k)
    for src in srcs + [e.get('style') or '']:
        for k in PROPS:
            m = re.search(rf'(?:^|;)\s*{k}\s*:\s*([^;]+)', src)
            if m:
                p[k] = m.group(1).strip()
    return p


def _first_family(v: str) -> str:
    return (v or '').split(',')[0].strip().strip('\'"')


def _size_units(v, parent=16.0) -> float | None:
    m = re.fullmatch(r'\s*(-?[\d.]+)\s*(px|pt|mm|em|%)?\s*', v or '')
    if not m:
        return None
    x, u = float(m.group(1)), m.group(2) or ''
    return {'': x, 'px': x, 'pt': x * 4 / 3, 'mm': x * 96 / 25.4, 'em': x * parent, '%': x * parent / 100}[u]


def _svg_type(path: Path):
    """Live type of an SVG (cut layer left out): per text element, its runs (text, family, weight, style, size in
    user units, vertical shift down in user units, text-transform) and whether it is set on a path or rotated."""
    root = r2._svg_root(path)
    rules = _css_rules(root)
    cut = {id(x) for g in l3._cut_groups(root) for x in g.iter()}
    out = []

    def runs_of(e, props, shift, acc):
        p = _props(e, props, rules)
        size = _size_units(p.get('font-size'), _size_units(props.get('font-size'), 16.0) or 16.0) or 16.0
        p['font-size'] = str(size)
        dy = sum(float(v) for v in re.findall(r'-?[\d.]+(?:e-?\d+)?', e.get('dy') or '')[:1])
        bs = p.get('baseline-shift') if e.get('baseline-shift') or 'baseline-shift' in (e.get('style') or '') else None
        own = shift + dy
        if bs:
            v = {'sub': 0.33 * size, 'super': -0.33 * size}.get(bs.strip())
            if v is None:
                u = _size_units(bs, size)
                v = -(u or 0.0)
            own += v
        if e.text:
            acc.append(dict(text=e.text, family=_first_family(p.get('font-family')), weight=str(p.get('font-weight', '400')).strip(),
                            style=str(p.get('font-style', 'normal')).strip(), size=size, shift=own,
                            transform=str(p.get('text-transform', 'none')).strip(), spacing=str(p.get('letter-spacing', '0'))))
        for c in e:
            own = runs_of(c, p, own, acc)
            if c.tail:
                acc.append(dict(text=c.tail, family=_first_family(p.get('font-family')), weight=str(p.get('font-weight', '400')).strip(),
                                style=str(p.get('font-style', 'normal')).strip(), size=size, shift=own,
                                transform=str(p.get('text-transform', 'none')).strip(), spacing=str(p.get('letter-spacing', '0'))))
        return own if r2._local(e.tag) == 'tspan' else shift

    def walk(e, props, m):
        if id(e) in cut or r2._local(e.tag) in ('defs', 'style', 'clipPath', 'mask', 'symbol'):
            return
        m = m @ _tf(e.get('transform'))
        p = _props(e, props, rules)
        if r2._local(e.tag) == 'text':
            acc = []
            runs_of(e, props, 0.0, acc)
            curved = any(r2._local(x.tag) == 'textPath' or len(re.findall(r'-?[\d.]+', x.get('rotate') or '')) > 0 for x in e.iter())
            rotated = abs(m[0, 1]) > 1e-6 or abs(m[1, 0]) > 1e-6
            scale = math.sqrt(abs(np.linalg.det(m[:2, :2])))
            out.append(dict(runs=acc, text=''.join(r['text'] for r in acc), curved=curved or rotated, scale=scale))
            return
        for c in e:
            walk(c, p, m)
    walk(root, {}, np.eye(3))
    fr = _frame(root)
    return out, (fr[0] if fr else None), root


def _is_wordmark(text: str) -> bool:
    t = re.sub(r'\s+', ' ', text).upper()
    return 'MERIDIAN' in t and 'ASH' in t


def _regular(run, family_rx) -> bool:
    w = run['weight'].lower()
    return bool(re.fullmatch(family_rx, run['family'], re.I)) and w in ('400', 'normal', 'regular', '') and run['style'].lower() in ('normal', '')


def _caps(run) -> bool:
    return run['transform'].lower() == 'uppercase' or not re.search(r'[a-z]', run['text'])


def op_svg_type(path, a):
    """Live type of a sticker SVG (cut layer left out), read completely from the file. Roles: the wordmark is a text
    element reading MERIDIAN and ASH; a title line is other live text at title_pt (9 pt) or more (midway between the
    type scale's 7 pt copy and 11 pt title steps), set flat (not on a path, not rotated); copy is other live text under
    title_pt. what: "wordmark_font" (the wordmark in DM Serif Display Regular), "wordmark_caps" (a DM Serif Display
    wordmark in capitals), "title_font" (title lines in DM Serif Display Regular), "title_caps" (title lines in
    capitals), "copy_font" (copy in Libre Franklin Regular 400), "amp_hangs" (a DM Serif Display ampersand moved down
    from the baseline by at least min_drop (5%) of its size: pass; not moved down: fail). A run in another family,
    weight or style, or lowercase where capitals are asked, fails. No text of that role: a pass, unless the file has
    no live type at all or the wordmark is not live type (it may be outlines): a person. A wordmark split over
    several text elements goes to a person."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    texts, s, root = _svg_type(path)
    what = a['what']
    if not texts:
        return PERSON, {'reason': 'no live type in the file (type may be drawn as outlines)'}
    joined = ''.join(t['text'] for t in texts)
    marks = [t for t in texts if _is_wordmark(t['text'])]
    if not marks and _is_wordmark(joined) and not any(_is_wordmark(t['text']) for t in texts):
        return PERSON, {'reason': 'the wordmark is split over several text elements'}
    dm = r'dm\s*serif\s*display'
    if what in ('wordmark_font', 'wordmark_caps', 'amp_hangs'):
        if not marks:
            return PERSON, {'reason': 'no live wordmark (it may be drawn as outlines)'}
        runs = [r for t in marks for r in t['runs'] if r['text'].strip()]
        if what == 'wordmark_font':
            off = [f"{r['text'].strip()}: {r['family']} {r['weight']} {r['style']}" for r in runs if not _regular(r, dm)]
            return ('fail', {'not_dm_serif_regular': off[:4]}) if off else ('pass', {'wordmark': marks[0]['text'].strip()})
        if what == 'wordmark_caps':
            runs = [r for r in runs if re.fullmatch(dm, r['family'], re.I)]
            if not runs:
                return 'pass', {'reason': 'no DM Serif Display wordmark'}
            low = [r['text'].strip() for r in runs if not _caps(r)]
            return ('fail', {'lowercase': low[:4]}) if low else ('pass', {'wordmark': marks[0]['text'].strip()})
        amps = []
        for t in marks:
            base_shift = next((r['shift'] for r in t['runs'] if re.search(r'[A-Za-z]', r['text'])), 0.0)
            for r in t['runs']:
                if '&' in r['text'] and re.fullmatch(dm, r['family'], re.I):
                    if re.search(r'[A-Za-z]', r['text']):
                        amps.append(0.0)       # set in the same run as the letters: on their baseline
                    else:
                        amps.append((r['shift'] - base_shift) / r['size'])
        if not amps:
            return 'pass', {'reason': 'no DM Serif Display ampersand'}
        drop = min(amps)
        ev = {'drop_of_size': round(drop, 3)}
        if drop >= a.get('min_drop', 0.05):
            return 'pass', ev
        return ('fail' if drop <= 0.0 else PERSON), ev
    if s is None:
        return PERSON, {'reason': 'size not in millimetres, so type sizes cannot be read'}
    others = []
    for t in texts:
        if t in marks:
            continue
        for r in t['runs']:
            if r['text'].strip():
                pt = r['size'] * t['scale'] * s * PT_MM
                others.append(dict(r, pt=pt, curved=t['curved']))
    title_pt = a.get('title_pt', 9.0)
    if what in ('title_font', 'title_caps'):
        rows = [r for r in others if r['pt'] >= title_pt and not r['curved']]
        if what == 'title_font':
            off = [f"{r['text'].strip()[:30]}: {r['family']} {r['weight']}" for r in rows if not _regular(r, dm)]
        else:
            off = [r['text'].strip()[:30] for r in rows if not _caps(r)]
    elif what == 'copy_font':
        rows = [r for r in others if r['pt'] < title_pt]
        off = [f"{r['text'].strip()[:30]}: {r['family']} {r['weight']}" for r in rows if not _regular(r, r'libre\s*franklin')]
    else:
        return PERSON, {'reason': 'unknown check'}
    ev = {'lines': [f"{r['text'].strip()[:30]} ({r['pt']:.1f} pt)" for r in rows][:6]}
    if off:
        return 'fail', dict(ev, off=off[:4])
    return 'pass', ev if rows else {'reason': 'no live text in that role'}


# ================================================================ one drawing against another (R003)

def op_svg_other_drawing(path, a):
    """The SVG is a different drawing from another delivered SVG: both (cut layers left out) rendered at 600 px on
    white, scaled to the same box. Pass: ink masks overlapping at IoU under max_iou (0.8), or min_differ (20%) or more
    of the inked pixels differing in colour by 30 or more; fail: IoU 0.97 or more with under 1% differing (the same
    drawing); else a person."""
    import cv2
    other = Path(a['_artifacts']) / a['deliverable']
    if path.suffix.lower() != '.svg' or not other.is_file():
        return PERSON, {'reason': 'both SVGs needed'}

    def render(p):
        arr = r2._render_svg_text(r2._svg_without_cut(p), 600).astype(np.int16)
        b = _box(arr[..., 3] > 128)
        if b is None:
            return None
        crop = arr[b[1]:b[3], b[0]:b[2]].astype(np.uint8)
        crop = cv2.resize(crop, (400, 400), interpolation=cv2.INTER_AREA).astype(np.int16)
        al = crop[..., 3:4] / 255.0
        return crop[..., 3] > 128, (crop[..., :3] * al + 255 * (1 - al))
    x, y = render(path), render(other)
    if x is None or y is None:
        return PERSON, {'reason': 'nothing drawn'}
    iou = float((x[0] & y[0]).sum() / max(1, (x[0] | y[0]).sum()))
    ink = x[0] | y[0]
    differ = float(((np.abs(x[1] - y[1]).max(axis=2) >= 30) & ink).sum() / max(1, ink.sum()))
    ev = {'iou': round(iou, 3), 'differing_share': round(differ, 3)}
    if iou < a.get('max_iou', 0.8) or differ >= a.get('min_differ', 0.2):
        return 'pass', ev
    if iou >= 0.97 and differ < 0.01:
        return 'fail', ev
    return PERSON, ev


OPS.update({
    'cut_offset_r4v': op_cut_offset,
    'cut_corners_r4v': op_cut_corners,
    'svg_solid_ink_r4v': op_svg_solid_ink,
    'proof_same_r4v': op_proof_same,
    'proof_open_r4v': op_proof_open,
    'proof_flat_r4v': op_proof_flat,
    'proof_no_cutline_r4v': op_proof_no_cutline,
    'sheet_no_cutline_r4v': op_sheet_no_cutline,
    'sheet_notes_r4v': op_sheet_notes,
    'svg_type_r4v': op_svg_type,
    'svg_other_drawing_r4v': op_svg_other_drawing,
})


# ================================================================ window mark parts: wordmark, roundel, leaf, ring

def _fill_of(e, parents, rules) -> tuple:
    """Effective fill colour and opacity of a shape (attributes, style, CSS class rules, inherited)."""
    fill, op = 'black', 1.0
    for x in parents + [e]:
        srcs = [rules.get(r2._local(x.tag), '')] + [rules.get('.' + c, '') for c in (x.get('class') or '').split()]
        if x.get('id'):
            srcs.append(rules.get('#' + x.get('id'), ''))
        srcs.append(x.get('style') or '')
        vals = {k: x.get(k) for k in ('fill', 'fill-opacity', 'opacity') if x.get(k) is not None}
        for src in srcs:
            for k in ('fill', 'fill-opacity', 'opacity'):
                m = re.search(rf'(?:^|;)\s*{k}\s*:\s*([^;]+)', src)
                if m:
                    vals[k] = m.group(1).strip()
        if 'fill' in vals:
            fill = vals['fill'].strip().lower()
        for k in ('fill-opacity', 'opacity'):
            if k in vals:
                try:
                    v = vals[k].strip()
                    op *= float(v[:-1]) / 100 if v.endswith('%') else float(v)
                except ValueError:
                    pass
    return fill, op


def _parts(svg: Path, width: int = 800):
    """Each shape of the artwork (cut layer left out) rendered alone at width px: list of dicts (element index in
    drawing order, fill, opacity, mask), plus the full render."""
    import copy
    text = r2._svg_without_cut(svg)
    root = ET.fromstring(text)
    rules = _css_rules(root)
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    def walk(e, parents, acc):
        if r2._local(e.tag) in ('defs', 'clipPath', 'mask', 'symbol', 'style', 'text'):
            return acc
        if r2._local(e.tag) in SHAPES:
            acc.append((e, parents))
        for c in e:
            walk(c, parents + [e], acc)
        return acc
    shapes = walk(root, [], [])
    full = r2._render_svg_text(text, width)
    out = []
    for i, (e, parents) in enumerate(shapes):
        r = copy.deepcopy(root)
        mine = walk(r, [], [])
        up = {c: pa for pa in r.iter() for c in pa}
        for j, (x, _) in enumerate(mine):
            if j != i:
                up[x].remove(x)
        for x in [x for x in r.iter() if r2._local(x.tag) in ('text', 'image', 'use')]:
            up[x].remove(x)
        arr = r2._render_svg_text(ET.tostring(r, encoding='unicode'), width)
        fill, op = _fill_of(e, parents, rules)
        out.append(dict(i=i, fill=fill, opacity=op, mask=arr[..., 3] > 128))
    return out, full


def _ellipse_fit(m):
    import cv2
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    c = max(cs, key=cv2.contourArea)
    if len(c) < 5:
        return None
    (cx, cy), (w, h), ang = cv2.fitEllipse(c)
    em = np.zeros(m.shape, np.uint8)
    cv2.ellipse(em, ((cx, cy), (w, h), ang), 1, -1)
    filled = _fill_holes(m)
    iou = float((em.astype(bool) & filled).sum() / max(1, (em.astype(bool) | filled).sum()))
    return dict(cx=cx, cy=cy, size=max(w, h), iou=iou, filled=filled, solid=float(m.sum() / max(1, filled.sum())))


def _window_roles(parts):
    """Roles by geometry: backing (the shape whose outline holds 90% of every other shape's ink), roundel (the
    largest solid ellipse: fitted ellipse IoU 0.95 or more, 90% solid; a second solid ellipse concentric with it sends
    the check to a person), ring (an ellipse outline concentric with the roundel, within 5% of its size, larger, at
    most 35% solid), leaf (the largest shape 90% inside the roundel; another shape there of 10% of its size or more in
    another colour sends it to a person), wordmark (other shapes 90% outside the ring's outline, with five or more
    separate pieces: lettering). Returns (roles, reason)."""
    import cv2
    if len(parts) < 4:
        return None, 'too few shapes to tell the parts apart'
    info = []
    for p in parts:
        if not p['mask'].any():
            continue
        f = _ellipse_fit(p['mask'])
        if f:
            info.append(dict(p, **f))
    union = np.zeros(parts[0]['mask'].shape, bool)
    for p in info:
        union |= p['mask']
    back = max(info, key=lambda p: p['filled'].sum())
    if (back['filled'] & union).sum() < 0.98 * union.sum():
        back = None
    rest = [p for p in info if p is not back]
    roundels = [p for p in rest if p['iou'] >= 0.95 and p['solid'] >= 0.9]
    if not roundels:
        return None, 'no filled roundel found'
    roundel = max(roundels, key=lambda p: p['mask'].sum())
    nested = [p for p in roundels if p is not roundel and math.hypot(p['cx'] - roundel['cx'], p['cy'] - roundel['cy']) <= 0.05 * roundel['size']]
    if nested:
        return None, 'two filled ellipses one inside the other: which is the roundel is for a person'
    rings = [p for p in rest if p is not roundel and p['iou'] >= 0.95 and p['solid'] <= 0.35
             and math.hypot(p['cx'] - roundel['cx'], p['cy'] - roundel['cy']) <= 0.05 * roundel['size']
             and p['filled'].sum() > 1.05 * roundel['filled'].sum()]
    ring = max(rings, key=lambda p: p['filled'].sum()) if len(rings) >= 1 else None
    inside = [p for p in rest if p is not roundel and p is not ring and (p['mask'] & roundel['filled']).sum() >= 0.9 * p['mask'].sum()]
    # the leaf: the largest shape inside the roundel; any other sizeable shape there (10% of its size or more) in
    # another colour makes the leaf's colour a question for a person
    leaf = [max(inside, key=lambda p: p['mask'].sum())] if inside else []
    if leaf:
        others = [p for p in inside if p is not leaf[0] and p['mask'].sum() >= 0.1 * leaf[0]['mask'].sum() and p['fill'] != leaf[0]['fill']]
        if others:
            leaf = []
    outline = ring['filled'] if ring else roundel['filled']
    word = []
    for p in rest:
        if p is roundel or p is ring or p in leaf:
            continue
        if (p['mask'] & outline).sum() <= 0.1 * p['mask'].sum():
            n, _ = cv2.connectedComponents(p['mask'].astype(np.uint8))
            if n - 1 >= 5:
                word.append(p)
    return dict(backing=back, roundel=roundel, ring=ring, leaf=leaf, wordmark=word), None


def _hex_verdict(colours, target, tol=2, far=30):
    t = np.array(r3._hex_rgb(target))
    d = [int(np.abs(np.array(c) - t).max()) for c in colours]
    return ('pass' if max(d) <= tol else 'fail' if max(d) >= far else PERSON), d


def op_window_part(path, a):
    """A part of the window mark is solid in one colour (hex). Parts are found by geometry from the delivered SVG
    (each shape rendered alone; roles as _window_roles). SVG: every shape of the part filled with hex (within 2 per
    channel) at full opacity passes; another colour (30 or more off) or opacity under 1 fails; else a person. Proof
    (PNG, against its SVG aligned on the ink boxes, IoU 0.97 or more): the proof's flat opaque pixels where the part
    shows (shapes drawn over it left out, 3 px edge left out) within tol (5) of hex for pass_share (95%) or more pass;
    a median far (30) or more off fails; else a person. A part not found goes to a person."""
    import cv2
    svg = path if path.suffix.lower() == '.svg' else (Path(a['_artifacts']) / a['deliverable'] if a.get('deliverable') else None)
    if not svg or not svg.is_file():
        return PERSON, {'reason': 'the SVG is not available'}
    parts, full = _parts(svg)
    roles, why = _window_roles(parts)
    if not roles:
        return PERSON, {'reason': why}
    role = roles.get(a['part'])
    sel = role if isinstance(role, list) else ([role] if role else [])
    if not sel:
        return PERSON, {'reason': f"no {a['part']} found"}
    if path.suffix.lower() == '.svg':
        bad = [p['fill'] for p in sel if not re.fullmatch(r'#[0-9a-f]{6}|#[0-9a-f]{3}', p['fill'])]
        if bad:
            return PERSON, {'reason': 'fill not a plain colour', 'fills': bad[:3]}
        cols = [r3._hex_rgb(p['fill'] if len(p['fill']) == 7 else '#' + ''.join(ch * 2 for ch in p['fill'][1:])) for p in sel]
        st, d = _hex_verdict(cols, a['hex'], 2, a.get('far', 30))
        ev = {'fills': sorted({p['fill'] for p in sel}), 'opacity': [round(p['opacity'], 3) for p in sel]}
        if any(p['opacity'] < 0.999 for p in sel):
            return 'fail', dict(ev, reason='not solid: opacity under 100%')
        return st, ev
    got = _aligned(path, svg, 0)
    if got is None:
        return PERSON, {'reason': 'nothing drawn'}
    proof, pbox, crop_r, aspect, _ = got
    crop_p = proof[pbox[1]:pbox[3], pbox[0]:pbox[2]]
    mp, mr = crop_p[..., 3] > 128, crop_r[..., 3] > 128
    iou = float((mp & mr).sum() / max(1, (mp | mr).sum()))
    if iou < 0.97 or aspect >= 0.02:
        return PERSON, {'reason': 'the proof does not line up with its SVG', 'iou': round(iou, 3)}
    fb = _box(full[..., 3] > 128)
    vis = np.zeros(full.shape[:2], bool)
    for p in sel:
        m = p['mask'].copy()
        for q in parts:
            if q['i'] > p['i']:
                m &= ~q['mask']
        vis |= m
    vis = vis[fb[1]:fb[3], fb[0]:fb[2]].astype(np.uint8)
    vis = cv2.resize(vis, (mp.shape[1], mp.shape[0]), interpolation=cv2.INTER_NEAREST)
    vis = cv2.erode(vis, np.ones((7, 7), np.uint8)) > 0
    px = crop_p[..., :3][vis & (crop_p[..., 3] >= 250) & r3._flat(crop_p[..., :3], 2)]
    if len(px) < 100:
        return PERSON, {'reason': 'too little of the part shows'}
    t = np.array(r3._hex_rgb(a['hex']))
    share = float((np.abs(px - t).max(axis=1) <= a.get('tol', 5)).mean())
    med = np.median(px, axis=0)
    off = int(np.abs(med - t).max())
    ev = {'share_at_colour': round(share, 3), 'median': r3._to_hex(med.astype(int)), 'pixels': int(len(px))}
    if share >= a.get('pass_share', 0.95):
        return 'pass', ev
    return ('fail' if off >= a.get('far', 30) else PERSON), ev


def op_window_arch(path, a):
    """The wordmark arches above the filled roundel (window mark): parts found by geometry from the SVG (a proof is
    read through its SVG, which it must match exactly, op_proof_same). Pass: the letters of the wordmark's middle
    fifth end above the roundel's top (plus 10% of the roundel's height), the whole wordmark ends above the roundel's
    centre and spans across it, and its letters' lowest points rise to the middle (the two outer fifths sit lower than
    the middle fifth by min_rise (2%) of the wordmark's width or more: an arch); fail: the wordmark's centre lies below the
    roundel's centre, or level with it beside the roundel; else a person."""
    import cv2
    svg = path if path.suffix.lower() == '.svg' else (Path(a['_artifacts']) / a['deliverable'] if a.get('deliverable') else None)
    if not svg or not svg.is_file():
        return PERSON, {'reason': 'the SVG is not available'}
    if path.suffix.lower() == '.png':
        st, ev = op_proof_same(path, dict(a, deliverable=a['deliverable']))
        if st != 'pass':
            return PERSON, {'reason': 'the proof does not match its SVG exactly', 'proof_vs_svg': st}
    parts, full = _parts(svg)
    roles, why = _window_roles(parts)
    if not roles or not roles['wordmark']:
        return PERSON, {'reason': why or 'no wordmark found'}
    word = np.zeros(full.shape[:2], bool)
    for p in roles['wordmark']:
        word |= p['mask']
    rb = _box(roles['roundel']['mask'])
    wb = _box(word)
    rh = rb[3] - rb[1]
    wcy, rcy = (wb[1] + wb[3]) / 2, (rb[1] + rb[3]) / 2
    n, lab, stats, cents = cv2.connectedComponentsWithStats(word.astype(np.uint8), connectivity=8)
    big = [i for i in range(1, n) if stats[i][4] >= 0.002 * word.sum()]
    xs = np.array([cents[i][0] for i in big])
    bottoms = np.array([stats[i][1] + stats[i][3] for i in big])
    ev = {'wordmark_box': [int(v) for v in wb], 'roundel_box': [int(v) for v in rb]}
    if wcy > rcy or (abs(wcy - rcy) < 0.25 * rh and (wb[2] <= rb[0] or wb[0] >= rb[2])):
        return 'fail', dict(ev, reason='the wordmark sits below or beside the roundel')
    if len(big) < 5:
        return PERSON, dict(ev, reason='letters not told apart')
    w = wb[2] - wb[0]
    rel = (xs - wb[0]) / max(1, w)
    outer = bottoms[(rel < 0.2) | (rel > 0.8)]
    mid = bottoms[(rel > 0.4) & (rel < 0.6)]
    if not len(outer) or not len(mid):
        return PERSON, dict(ev, reason='letters not spread across the wordmark')
    rise = float((np.median(outer) - np.median(mid)) / max(1, w))
    ev['arch_rise_of_width'] = round(rise, 3)
    mid_low = float(np.max(mid))
    ev['middle_letters_lowest'] = int(mid_low)
    if mid_low <= rb[1] + 0.1 * rh and wb[3] <= rcy and wb[0] < (rb[0] + rb[2]) / 2 < wb[2] and rise >= a.get('min_rise', 0.02):
        return 'pass', ev
    return PERSON, ev


OPS.update({'window_part_r4v': op_window_part, 'window_arch_r4v': op_window_arch})


# ================================================================ the wordmark's arch angle (R089)

def _embedded_fonts(root) -> dict:
    """Fonts embedded in the SVG's CSS (@font-face with a base64 data URL), by family name (lower case)."""
    import base64
    import io as _io
    from fontTools.ttLib import TTFont
    css = ' '.join(x.text or '' for x in root.iter() if r2._local(x.tag) == 'style')
    out = {}
    for block in re.findall(r'@font-face\s*\{([^}]*)\}', css):
        fam = re.search(r'font-family\s*:\s*([^;]+)', block)
        src = re.search(r'url\(\s*[\'"]?data:[^;,]+;base64,([A-Za-z0-9+/=]+)', block)
        if fam and src:
            try:
                out[_first_family(fam.group(1)).lower()] = TTFont(_io.BytesIO(base64.b64decode(src.group(1))))
            except Exception:
                continue
    return out


def op_svg_arch_angle(path, a):
    """A MERIDIAN & ASH wordmark set as live DM Serif Display text arches on a curve spanning deg (40) degrees: the
    text runs on a textPath whose path is one circular arc (radius r); the inked span, from the first letter's left
    edge to the last letter's right edge, is the runs' advance widths (from the font embedded in the SVG, at each
    run's size, plus any letter-spacing) less the first glyph's left and the last glyph's right side bearing; its
    angle is that length over r. Within tol_deg (2 degrees) of deg passes; fail_deg (5 degrees) or more off fails;
    set flat (no textPath, no per-letter rotation) fails; else, or no live wordmark, or no embedded font, a person."""
    if path.suffix.lower() != '.svg':
        return PERSON, {'reason': 'read from the SVG'}
    root = r2._svg_root(path)
    hits = [e for e in root.iter() if r2._local(e.tag) == 'text' and _is_wordmark(''.join(e.itertext()))]
    if not hits:
        return PERSON, {'reason': 'no live wordmark (it may be drawn as outlines)'}
    texts, s, _ = _svg_type(path)
    marks = [t for t in texts if _is_wordmark(t['text'])]
    runs = [r for t in marks[:1] for r in t['runs'] if r['text']]
    if not runs or not all(re.fullmatch(r'dm\s*serif\s*display', r['family'], re.I) for r in runs if r['text'].strip()):
        return 'pass', {'reason': 'no wordmark set in DM Serif Display'}
    e = hits[0]
    tp = [x for x in e.iter() if r2._local(x.tag) == 'textPath']
    rotated = any(len(re.findall(r'-?[\d.]+', x.get('rotate') or '')) > 1 for x in e.iter())
    if not tp:
        return (PERSON, {'reason': 'letters rotated one by one; the arc is for a person'}) if rotated else \
               ('fail', {'reason': 'the wordmark is set on a straight baseline'})
    ref = next((v for k, v in tp[0].attrib.items() if r2._local(k) == 'href'), '').lstrip('#')
    arc_el = next((x for x in root.iter() if x.get('id') == ref), None)
    m = re.fullmatch(r'\s*M\s*([-\d.e]+)[\s,]+([-\d.e]+)\s*A\s*([-\d.e]+)[\s,]+([-\d.e]+)[\s,]+[-\d.e]+[\s,]+[01][\s,]*[01][\s,]*([-\d.e]+)[\s,]+([-\d.e]+)\s*',
                     (arc_el.get('d') if arc_el is not None else '') or '')
    if not m:
        return PERSON, {'reason': 'the text path is not one circular arc'}
    rx, ry = float(m.group(3)), float(m.group(4))
    if abs(rx - ry) > 0.01 * max(rx, ry) or (arc_el.get('transform') or '').strip():
        return PERSON, {'reason': 'the text path is not one circular arc'}
    fonts = _embedded_fonts(root)
    f = fonts.get(runs[0]['family'].lower())
    if f is None:
        return PERSON, {'reason': 'the wordmark\'s font is not embedded, so its letter widths are not known'}
    cmap, hmtx, upm = f.getBestCmap(), f['hmtx'], f['head'].unitsPerEm
    gs = f.getGlyphSet()
    from fontTools.pens.boundsPen import BoundsPen
    total, first, last = 0.0, None, None
    for r in runs:
        ls = _size_units(r.get('spacing') or '0', r['size']) or 0.0
        for ch in r['text']:
            g = cmap.get(ord(ch))
            if g is None:
                return PERSON, {'reason': f'no glyph for {ch!r} in the embedded font'}
            total += hmtx[g][0] * r['size'] / upm + ls
            if not ch.isspace():
                last = (g, r['size'])
                first = first or (g, r['size'])

    def bounds(g):
        bp = BoundsPen(gs)
        gs[g].draw(bp)
        return bp.bounds
    lsb = bounds(first[0])[0] * first[1] / upm
    rsb = (hmtx[last[0]][0] - bounds(last[0])[2]) * last[1] / upm
    ink = total - lsb - rsb
    deg = math.degrees(ink / rx)
    ev = {'arc_radius': round(rx, 3), 'inked_length': round(ink, 3), 'span_deg': round(deg, 2)}
    off = abs(deg - a.get('deg', 40))
    if off <= a.get('tol_deg', 2):
        return 'pass', ev
    return ('fail' if off >= a.get('fail_deg', 5) else PERSON), ev


OPS.update({'svg_arch_angle_r4v': op_svg_arch_angle})
