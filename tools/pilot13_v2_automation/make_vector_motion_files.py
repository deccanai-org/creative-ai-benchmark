#!/usr/bin/env python3
"""Make VECTOR-04 and MOTION-11 test deliverables (no run produced any): a correct set and two sets with known defects.

good: every round-1 and round-2 rule holds.
VECTOR-04: six sticker SVGs measuring 55 mm on the long edge (width in mm, viewBox in mm, the artwork filling it). The
three bag stickers are traced with OpenCV from their own bag photos: the moth in Roast Brown, the pour-over cone in
Ash Green, and the ridge line, whose halftone is blurred into its tone and redrawn as solid shapes and line hatching,
in Brick Red, each on a Kraft die-cut backing. The window mark is the traced leaf in an Ash Green roundel under arched
lettering drawn as outlines; the two companions carry live DM Serif Display "MERIDIAN & ASH" with the ampersand at 1.6
times the capitals, and the $3 single / $9 four-pack prices. Some stickers keep their kiss-cut path on a hidden
'CutContour' layer, never in the artwork. Also the six cut-contour SVGs, six transparent 1600 px proofs and the
imposed 305 x 457 mm sheet, with only palette inks and a little Ink Black.
MOTION-11: 1920 x 1080 thumbnails built on a frame of their own capture with the title whole on a solid band, teasers
with the tagline and upload line, and the channel animation with the STATIC FOX title stack (Anton over Archivo
Black), the supplied Scrap cutout and a held end card led by STATIC FOX with the members line.
bad: the round-1 defects (PLANTED in decide_moves.py) on the good content: an off-palette red set through a CSS class
(invisible to an attribute scan), Ink Black over 5% of the ink, a $14 price on a sticker, its proof and a $12 one on
the sheet; a title cut off at the edge, a misspelt title, a caption larger than the title, a changed upload line,
a wrong channel name.
bad2: the good set with one round-2 defect in some files (DEFECTS2, written to <out>/defects2_vector_motion.json).

Usage: python make_vector_motion_files.py <out dir>   (writes <out>/{good,bad,bad2}/<TASK>/deliverables/...)
Run with the benchmark_v4 venv (PyMuPDF, cairosvg, OpenCV, fontTools) with ffmpeg on PATH.
"""
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('DYLD_FALLBACK_LIBRARY_PATH', '/opt/homebrew/lib:/usr/local/lib:/usr/lib')  # Homebrew Cairo
import cairosvg  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from fontTools.pens.svgPathPen import SVGPathPen  # noqa: E402
from fontTools.pens.transformPen import TransformPen  # noqa: E402
from fontTools.subset import Options, Subsetter  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.varLib.instancer import instantiateVariableFont  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
V04, M11 = REFRESH / 'sources/VECTOR-04', REFRESH / 'sources/MOTION-11'
ROAST, KRAFT, ASH, CREAM, BRICK, INK = '#3E2A20', '#C8A97E', '#5B6B54', '#F3E7D3', '#A8442E', '#201914'
TITLE_FONT = REFRESH / 'fonts/anton/Anton-Regular.ttf'
PAYOFF_FONT = REFRESH / 'fonts/archivoblack/ArchivoBlack-Regular.ttf'
BODY_FONT = '/System/Library/Fonts/Supplemental/Arial.ttf'
DISPLAY = str(REFRESH / 'fonts/dmserifdisplay/DMSerifDisplay-Regular.ttf')     # brand display face
FRANKLIN = str(REFRESH / 'fonts/librefranklin/LibreFranklin[wght].ttf')        # brand text face (variable)
LONG_MM = 55          # every sticker artwork measures 55 mm on its long edge
PX_MM = 20            # raster resolution for tracing and offsetting, pixels per millimetre
PT = 72 / 25.4        # PDF points per millimetre
NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'

# round-2 defects planted in the bad2 set: file -> (round-2 rules it breaks, what is wrong)
DEFECTS2 = {
    'VECTOR-04/recovered-sticker-window-mark': (
        ['R016'], 'artwork set at 70 mm on its long edge (width 70mm, the artwork filling it), not 55 mm'),
    'VECTOR-04/recovered-sticker-bag-design-1': (
        ['R040', 'R068'], 'traced from meridian_bag_ridgeline.jpg: the Brick Red ridge line instead of the Roast Brown moth'),
    'VECTOR-04/recovered-sticker-bag-design-2': (
        ['R033', 'R055'], 'traced from meridian_bag_moth.jpg: the Roast Brown moth instead of the Ash Green pour-over cone'),
    'VECTOR-04/recovered-sticker-bag-design-3': (
        ['R034', 'R056'], 'traced from meridian_bag_pourover.jpg: the Ash Green cone instead of the Brick Red ridge line '
                          '(solid shapes, no halftone, so R043 still holds)'),
    'VECTOR-04/sticker-proof-bag-design-3': (
        ['R043'], 'the ridge line rendered as halftone dots screened from the photo, not solid shapes and hatching'),
    'VECTOR-04/new-sticker-companion-1': (
        ['R090'], 'the DM Serif Display ampersand set at the size of MERIDIAN and ASH (cap height) on their baseline, '
                  'not at 1.6 times'),
    'VECTOR-04/new-sticker-companion-2': (
        ['R019'], 'the cut line drawn into the artwork layer as a closed Roast Brown stroke (id cut-line) along the '
                  'sticker edge, with no CutContour layer'),
    'MOTION-11/thumbnail-do-not-open-that-door': (['R018'], 'the title runs off the right edge: the last R is cut off'),
    'MOTION-11/thumbnail-kitchen-gone': (
        ['R033'], 'built on a frame from staticfox_capture_06.mp4 (the burning base), not capture 03'),
    'MOTION-11/thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi': (
        ['R033'], 'built on a frame from staticfox_capture_03.mp4 (the kitchen fire), not capture 06'),
    'MOTION-11/channel-animation': (['R119'], 'held end card: SUBSCRIBE OR DAVE WINS set larger than STATIC FOX'),
}

# ---------------------------------------------------------------- type as outlines and as embedded fonts


@lru_cache(maxsize=None)
def font(path: str, weight: int = 400) -> TTFont:
    f = TTFont(path)
    # the Libre Franklin file's default instance is Thin: set the weight the type system names
    return instantiateVariableFont(f, {'wght': weight}) if 'fvar' in f else f


def num(v: float) -> str:
    return f'{v:.3f}'.rstrip('0').rstrip('.')


def text_width(path: str, text: str, size: float, spacing: float = 0.0, weight: int = 400) -> float:
    f = font(path, weight)
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f['head'].unitsPerEm
    return sum(gs[cmap[ord(c)]].width * size / upm + spacing for c in text)


def outline(path: str, text: str, x: float, y: float, size: float, spacing: float = 0.0, weight: int = 400,
            sx: float = 1.0, matrix=None) -> tuple[str, float]:
    """Path data for text set at (x, baseline y); returns (d, x after the last letter). matrix places each letter
    instead ((letter index, advance, x scale, y scale) -> affine), for lettering set on a curve."""
    f = font(path, weight)
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f['head'].unitsPerEm
    pen = SVGPathPen(gs, ntos=num)
    s = size / upm
    for i, ch in enumerate(text):
        g = gs[cmap[ord(ch)]]
        t = (s * sx, 0, 0, -s, x, y) if matrix is None else matrix(i, g.width * s * sx, s * sx, s)
        g.draw(TransformPen(pen, t))
        x += g.width * s * sx + spacing
    return pen.getCommands(), x


@lru_cache(maxsize=None)
def font_face(family: str, path: str, weight: int, chars: str) -> str:
    """An @font-face rule embedding just the letters the text uses, so a browser shows the real typeface."""
    f = TTFont(path)
    if 'fvar' in f:
        f = instantiateVariableFont(f, {'wght': weight})
    sub = Subsetter(Options())
    sub.populate(text=chars)
    sub.subset(f)
    buf = io.BytesIO()
    f.save(buf)
    return (f"@font-face{{font-family:'{family}';font-weight:{weight};"
            f"src:url(data:font/ttf;base64,{base64.b64encode(buf.getvalue()).decode()})}}")

# ---------------------------------------------------------------- masks and paths


def grow(m: np.ndarray, r: float) -> np.ndarray:
    """Dilation by a disk of radius r pixels (exact distances, fast for large radii)."""
    return cv2.distanceTransform((~m).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) <= r


def shrink(m: np.ndarray, r: float) -> np.ndarray:
    return cv2.distanceTransform(m.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) > r


def fill_holes(m: np.ndarray) -> np.ndarray:
    flood = np.pad(m, 1).astype(np.uint8)
    cv2.floodFill(flood, None, (0, 0), 2)
    return flood[1:-1, 1:-1] != 2


def clean(m: np.ndarray, min_px: int) -> np.ndarray:
    """Drop specks and fill pinholes smaller than min_px pixels."""
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    keep = np.r_[False, st[1:, cv2.CC_STAT_AREA] >= min_px]
    m = keep[lab]
    n, lab, st, _ = cv2.connectedComponentsWithStats((~m).astype(np.uint8), connectivity=4)
    return m | np.r_[False, st[1:, cv2.CC_STAT_AREA] < min_px][lab]


def smooth(m: np.ndarray, sigma: float) -> np.ndarray:
    return cv2.GaussianBlur(m.astype(np.float32), (0, 0), sigma) > 0.5


def mask_path(m: np.ndarray, k: float, ox: float, oy: float, outer_only: bool = False) -> str:
    """SVG path data (even-odd) tracing every outline and hole of a mask; pixel p maps to (p - o) * k."""
    mode = cv2.RETR_EXTERNAL if outer_only else cv2.RETR_CCOMP
    parts = []
    for c in cv2.findContours(m.astype(np.uint8), mode, cv2.CHAIN_APPROX_NONE)[0]:
        c = cv2.approxPolyDP(c, 0.7, True).reshape(-1, 2)
        if len(c) >= 3:
            parts.append('M' + ' '.join(f'{num((x - ox) * k)},{num((y - oy) * k)}' for x, y in c) + 'Z')
    return ''.join(parts)


def outer(m: np.ndarray) -> np.ndarray:
    """Points of the largest outline of a mask."""
    return max(cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0],
               key=cv2.contourArea).reshape(-1, 2).astype(float)


def die_cut(sil: np.ndarray, border_px: float, bridge_px: float) -> np.ndarray:
    """A die-cut backing: the silhouette grown by the border, with gaps under bridge_px closed and edges smoothed."""
    back = grow(sil, border_px)
    back = shrink(grow(back, bridge_px), bridge_px)
    back = smooth(back, 0.5 * PX_MM)
    n, lab, st, _ = cv2.connectedComponentsWithStats(back.astype(np.uint8), connectivity=8)
    return lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))


def sticker(name: str, back: np.ndarray, ink: np.ndarray | None, colour: str) -> SimpleNamespace:
    """Place a traced ink mask on its Kraft backing in a millimetre space where the long edge is 55."""
    pts = outer(back)
    x0, y0 = pts.min(axis=0)
    w, h = pts.max(axis=0) - (x0, y0)
    k = LONG_MM / max(w, h)
    back_d = f'<path d="{mask_path(back, k, x0, y0, outer_only=True)}" fill="{KRAFT}"/>'
    ink_d = '' if ink is None else mask_path(ink, k, x0, y0)
    body = back_d + (f'<path d="{ink_d}" fill="{colour}" fill-rule="evenodd"/>' if ink_d else '')
    return SimpleNamespace(name=name, w=w * k, h=h * k, body=body, outlined=body, defs='', k=k, x0=x0, y0=y0,
                           back_d=back_d, ink_d=ink_d)

# ---------------------------------------------------------------- VECTOR-04 stickers


# where each bag photo prints its motif (crop box in photo pixels) and the ink it is printed in
BAGS = {'moth': ('meridian_bag_moth.jpg', (1459, 1033, 3952, 2523), ROAST),
        'pourover': ('meridian_bag_pourover.jpg', (2067, 486, 3344, 3283), ASH),
        'ridgeline': ('meridian_bag_ridgeline.jpg', (1580, 1033, 3800, 3131), BRICK)}
RIDGE_DENSE, RIDGE_TEXTURE = 96, 18     # blurred green level of the dense screen; dot texture of any screen


@lru_cache(maxsize=None)
def bag_ink(name: str):
    """The printed motif of a bag photo, cropped to its bounds: (solid ink, light tone, tone image). Only the ridge
    line has a light tone: its halftone is blurred into a continuous tone so the trace never follows the dots."""
    file, (x0, y0, x1, y1), _ = BAGS[name]
    rgb = np.asarray(Image.open(V04 / file).convert('RGB'))[y0:y1, x0:x1].astype(np.float32)
    r, g, b = (rgb[..., i] for i in range(3))
    tone = None
    if name == 'moth':        # dark brown ink on kraft
        solid = cv2.GaussianBlur(0.3 * r + 0.59 * g + 0.11 * b, (0, 0), 2) < 115
        light = np.zeros_like(solid)
    elif name == 'pourover':  # green ink has no red cast, unlike the kraft and its shadowed side
        solid = (cv2.GaussianBlur(r - g, (0, 0), 2) < 14) & (cv2.GaussianBlur(g, (0, 0), 2) < 150)
        light = np.zeros_like(solid)
    else:
        tone = cv2.GaussianBlur(g, (0, 0), 10)
        texture = np.sqrt(np.maximum(cv2.GaussianBlur(g * g, (0, 0), 10) - tone * tone, 0))
        block = (texture > RIDGE_TEXTURE) | (tone < RIDGE_DENSE)    # the screen is textured, plain kraft is not
        block = grow(shrink(block, 12), 12)                           # no thin strips along the bag's fold
        n, lab, st, _ = cv2.connectedComponentsWithStats(block.astype(np.uint8), connectivity=8)
        block = fill_holes(lab == 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])))
        solid = block & (tone < RIDGE_DENSE)
        light = block & ~solid
    solid = clean(solid, 400)
    n, lab, st, _ = cv2.connectedComponentsWithStats((solid | light).astype(np.uint8), connectivity=8)
    big = int(np.argmax(st[1:, cv2.CC_STAT_AREA])) + 1
    # the motif: its largest part and every part near it (steam above the cone, antennae, eye spots)
    x, y, w, h = st[big, :4]
    near = np.zeros(n, bool)
    for i in range(1, n):
        bx, by, bw, bh = st[i, :4]
        near[i] = (st[i, 4] >= 400 and bx >= x - 300 and by >= y - 900
                   and bx + bw <= x + w + 300 and by + bh <= y + h + 300)
    keep = near[lab]
    ys, xs = np.where(keep)
    crop = (slice(ys.min(), ys.max() + 1), slice(xs.min(), xs.max() + 1))
    return solid[crop] & keep[crop], light[crop] & keep[crop], None if tone is None else tone[crop]


HATCH_MM, BORDER_MM = 0.8, 1.6          # line hatching pitch for the ridge line's light tone; kraft border


@lru_cache(maxsize=None)
def bag_sticker(name: str, halftone: bool = False) -> SimpleNamespace:
    """A bag design traced from its photo: the ink as solid shapes (and line hatching for a light tone) on a Kraft
    die-cut backing. halftone=True screens the tone into dots instead, the way the bag was printed (a defect)."""
    solid, light, tone = bag_ink(name)
    s = (LONG_MM - 2 * BORDER_MM) * PX_MM / max(solid.shape)
    pad = int((BORDER_MM + 5 + 3) * PX_MM)          # room for the border and the 5 mm closing inside the raster

    def scaled(m):
        return np.pad(cv2.resize(m.astype(np.float32), None, fx=s, fy=s, interpolation=cv2.INTER_AREA) > 0.5, pad)
    solid, light = scaled(solid), scaled(light)
    rows = np.arange(solid.shape[0])[:, None]
    hatch = light & ((rows % round(HATCH_MM * PX_MM)) < round(HATCH_MM * PX_MM / 2))
    ink = clean(solid | hatch, 12)
    back = die_cut(fill_holes(solid | light), BORDER_MM * PX_MM, 5 * PX_MM)
    if not halftone:
        return sticker(name, back, ink, BAGS[name][2])
    # the screen: dots on a 0.6 mm grid, each as large as the blurred photo's ink coverage there
    t = np.pad(cv2.resize(tone, None, fx=s, fy=s, interpolation=cv2.INTER_AREA), pad, constant_values=255)
    cover = np.clip((150 - t) / (150 - 45), 0, 1) * (solid | light)
    step = 0.6 * PX_MM
    st = sticker(name, back, None, BRICK)
    for row, cy in enumerate(np.arange(step / 2, cover.shape[0], step)):
        for cx in np.arange(step / 2 * (1 + row % 2), cover.shape[1], step):
            c = cover[int(cy), int(cx)]
            if c > 0.05:
                st.body += (f'<circle cx="{num((cx - st.x0) * st.k)}" cy="{num((cy - st.y0) * st.k)}" '
                            f'r="{num(step * 0.62 * np.sqrt(c) * st.k)}" fill="{BRICK}"/>')
    st.outlined = st.body
    return st


@lru_cache(maxsize=None)
def window_sticker() -> SimpleNamespace:
    """The window mark: the Ash Green roundel and Warm Cream ring fitted to meridian_window_mark.jpg, its painted leaf
    traced, and MERIDIAN & ASH arched over it as Roast Brown outlines, on a Kraft die-cut backing."""
    rgb = np.asarray(Image.open(V04 / 'meridian_window_mark.jpg').convert('RGB')).astype(np.float32)
    r, g, b = (cv2.GaussianBlur(rgb[..., i], (0, 0), 2) for i in range(3))
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    green = ((g - r) >= 4) & ((g - b) >= 8) & (lum > 40) & (lum < 140)
    n, lab, st, _ = cv2.connectedComponentsWithStats(green.astype(np.uint8), connectivity=8)
    (cx, cy), (dx, dy), _ = cv2.fitEllipse(outer(lab == 1 + int(np.argmax(st[1:, 4]))).astype(np.float32))
    ax, ay = dx / 2, dy / 2
    yy, xx = np.mgrid[0:rgb.shape[0], 0:rgb.shape[1]]
    inside = ((xx - cx) / ax) ** 2 + ((yy - cy) / ay) ** 2 < 0.94 ** 2
    leaf = clean(smooth((lum > 112) & inside, 1.5), 300)
    n, lab, st, _ = cv2.connectedComponentsWithStats(leaf.astype(np.uint8), connectivity=8)
    leaf = fill_holes(lab == 1 + int(np.argmax(st[1:, 4]))) & leaf
    # lettering on an arc centred below the roundel, as painted: MERIDIAN up the left, the ampersand over the
    # top right hanging below the arc, ASH down the right
    ox, oy, rad, size, sx = cx, cy + 545, 1370, 380, 0.8

    def letters(text, start_deg, size_, drop=0.0):
        out, a = [], np.deg2rad(start_deg)
        for ch in text:
            adv = text_width(DISPLAY, ch, size_) * sx + 0.03 * size_
            mid = a - adv / 2 / rad
            px, py = ox + (rad - drop) * np.cos(mid), oy - (rad - drop) * np.sin(mid)
            rot = np.pi / 2 - mid                       # the letter's up points away from the centre
            cs, sn = np.cos(rot), np.sin(rot)
            w = text_width(DISPLAY, ch, size_) * sx

            def place(i, _adv, kx, ky, cs=cs, sn=sn, px=px, py=py, w=w):
                # letter space (x right, y up) -> photo pixels: centre the letter on its arc point, then turn it
                return (kx * cs, kx * sn, ky * sn, -ky * cs, px - w / 2 * cs, py - w / 2 * sn)
            d, _ = outline(DISPLAY, ch, 0, 0, size_, sx=sx, matrix=place)
            out.append(d)
            a -= adv / rad
        return out, np.rad2deg(a)
    glyphs, end = letters('MERIDIAN', 141.5, size)
    amp, end = letters('&', end - 3.0, size * 1.25, drop=70)
    rest, _ = letters('ASH', end - 3.0, size)
    lettering = ''.join(glyphs + amp + rest)
    ring = (f'M{num(cx - ax * 1.163)},{num(cy)}a{num(ax * 1.163)},{num(ay * 1.163)} 0 1,0 {num(2 * ax * 1.163)},0'
            f'a{num(ax * 1.163)},{num(ay * 1.163)} 0 1,0 {num(-2 * ax * 1.163)},0Z'
            f'M{num(cx - ax * 1.127)},{num(cy)}a{num(ax * 1.127)},{num(ay * 1.127)} 0 1,0 {num(2 * ax * 1.127)},0'
            f'a{num(ax * 1.127)},{num(ay * 1.127)} 0 1,0 {num(-2 * ax * 1.127)},0Z')
    px_body = (f'<ellipse cx="{num(cx)}" cy="{num(cy)}" rx="{num(ax)}" ry="{num(ay)}" fill="{ASH}"/>'
               f'<path d="{ring}" fill="{CREAM}" fill-rule="evenodd"/>'
               f'<path d="{mask_path(leaf, 1, 0, 0)}" fill="{CREAM}" fill-rule="evenodd"/>'
               f'<path d="{lettering}" fill="{ROAST}"/>')
    # the backing comes from a half-scale render of everything drawn
    H, W = rgb.shape[:2]
    svg = f'<svg {NS} width="{W}" height="{H}" viewBox="0 0 {W} {H}">{px_body}</svg>'
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=W // 2)
    drawn = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA'))[..., 3] > 0
    ys, xs = np.where(drawn)
    mm_px = max(np.ptp(xs), np.ptp(ys)) / (LONG_MM - 2 * BORDER_MM)    # half-scale pixels per sticker millimetre
    hull = np.zeros(drawn.shape, np.uint8)       # a badge-shaped backing: the hull of the arch and the roundel
    cv2.fillConvexPoly(hull, cv2.convexHull(np.c_[xs, ys].astype(np.int32)), 1)
    back = die_cut(hull.astype(bool), BORDER_MM * mm_px, 2 * mm_px)
    pts = outer(back) * 2
    x0, y0 = pts.min(axis=0)
    w, h = pts.max(axis=0) - (x0, y0)
    k = LONG_MM / max(w, h)
    body = (f'<path d="{mask_path(back, 2 * k, x0 / 2, y0 / 2, outer_only=True)}" fill="{KRAFT}"/>'
            f'<g transform="matrix({num(k)} 0 0 {num(k)} {num(-x0 * k)} {num(-y0 * k)})">{px_body}</g>')
    return SimpleNamespace(name='window', w=w * k, h=h * k, body=body, outlined=body, defs='')


def taper(points, width: float) -> str:
    """A filled brush stroke along a polyline, full width in the middle and pointed at both ends."""
    p = np.asarray(points, float)
    d = np.gradient(p, axis=0)
    nrm = np.c_[-d[:, 1], d[:, 0]] / np.linalg.norm(d, axis=1)[:, None]
    t = np.linspace(0, 1, len(p))
    half = width / 2 * np.sin(np.pi * t) ** 0.6
    side = np.r_[p + nrm * half[:, None], (p - nrm * half[:, None])[::-1]]
    return 'M' + ' '.join(f'{num(x)},{num(y)}' for x, y in side) + 'Z'


def curve(p0, p1, p2, p3, n=40):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def bean(cx, cy, rx, ry, deg) -> tuple[str, str]:
    """A coffee bean: the oval and its S-shaped crease (as a filled brush stroke)."""
    a = np.deg2rad(deg)
    u, v = np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])
    c = np.array([cx, cy])
    e0, e1 = c - u * rx, c + u * rx
    oval = (f'M{num(e0[0])},{num(e0[1])}A{num(rx)},{num(ry)} {num(deg)} 1,0 {num(e1[0])},{num(e1[1])}'
            f'A{num(rx)},{num(ry)} {num(deg)} 1,0 {num(e0[0])},{num(e0[1])}Z')
    crease = curve(c - u * rx * 0.8, c - u * rx * 0.3 + v * ry * 0.45, c + u * rx * 0.3 - v * ry * 0.45, c + u * rx * 0.8)
    return oval, taper(crease, ry * 0.2)


def wordmark(cx: float, base: float, amp: float, outlined: bool) -> str:
    """MERIDIAN & ASH in DM Serif Display capitals at 11 pt, tracked 0.020 em, the ampersand at amp times their size
    hanging below the baseline (at 1.0 it sits on the baseline at cap height)."""
    size, track = 11 / PT, 0.02 * 11 / PT
    drop = 0.36 * size if amp > 1 else 0.0
    width = (text_width(DISPLAY, 'MERIDIAN ', size, track) + text_width(DISPLAY, '&', size * amp, track)
             + text_width(DISPLAY, ' ASH', size, track))
    x = cx - width / 2
    if outlined:
        d1, x = outline(DISPLAY, 'MERIDIAN ', x, base, size, track)
        d2, x = outline(DISPLAY, '&', x, base + drop, size * amp, track)
        d3, _ = outline(DISPLAY, ' ASH', x, base, size, track)
        return f'<path d="{d1}{d2}{d3}" fill="{ROAST}"/>'
    return (f'<text x="{num(x)}" y="{num(base)}" font-family="DM Serif Display" font-size="{num(size)}" '
            f'letter-spacing="{num(track)}" fill="{ROAST}">MERIDIAN <tspan font-size="{num(size * amp)}" '
            f'dy="{num(drop)}">&amp;</tspan><tspan dy="{num(-drop)}"> ASH</tspan></text>')


def copy_line(text: str, cx: float, base: float, outlined: bool, size: float = 7 / PT) -> str:
    """A line of sticker copy in Libre Franklin Regular 400, centred."""
    x = cx - text_width(FRANKLIN, text, size) / 2
    if outlined:
        return f'<path d="{outline(FRANKLIN, text, x, base, size)[0]}" fill="{ROAST}"/>'
    return (f'<text x="{num(x)}" y="{num(base)}" font-family="Libre Franklin" font-weight="400" font-size="{num(size)}" '
            f'fill="{ROAST}">{text}</text>')


def companion(n: int, price_lines, amp: float = 1.6, cut_line: bool = False) -> SimpleNamespace:
    """An original companion: 1 is two coffee beans in Brick Red on a Warm Cream disc, 2 a cup of coffee in Ash Green
    on a Warm Cream tile; both with the wordmark and the prices as live type (outlined for proofs and the sheet)."""
    def body(outlined):
        if n == 1:
            w, h = 55.0, 55.0
            oval1, crease1 = bean(24.5, 29.5, 12.6, 8.4, -28)
            oval2, crease2 = bean(43.0, 32.5, 5.4, 3.7, 38)
            art = (f'<circle cx="27.5" cy="27.5" r="27.5" fill="{CREAM}"/>'
                   f'<path d="{oval1}{oval2}" fill="{BRICK}"/><path d="{crease1}{crease2}" fill="{CREAM}"/>'
                   + wordmark(27.5, 12.6, amp, outlined)
                   + ''.join(copy_line(t, 27.5, 46.2 + 3.4 * i, outlined) for i, t in enumerate(price_lines)))
            edge = 'M1.2,27.5a26.3,26.3 0 1,0 52.6,0a26.3,26.3 0 1,0 -52.6,0Z'
        else:
            w, h = 42.0, 55.0
            steam = ''.join(taper(curve(np.array([x, 21.0]), np.array([x - 3, 17.0]), np.array([x + 3, 14.5]),
                                        np.array([x, 11.2])), 1.5) for x in (16.5, 21.0, 25.5))
            cup = 'M9.5,23.5L32.5,23.5L31.0,36.5C30.6,40.5 27.5,42.0 21.0,42.0C14.5,42.0 11.4,40.5 11.0,36.5Z'
            handle = 'M31.2,26.0C37.8,25.6 39.2,34.4 30.4,35.8L30.6,33.4C35.4,32.6 35.0,28.0 31.4,28.4Z'
            saucer = 'M5.5,43.2C5.5,41.4 36.5,41.4 36.5,43.2C36.5,45.6 5.5,45.6 5.5,43.2Z'
            art = (f'<rect x="0" y="0" width="42" height="55" rx="6" fill="{CREAM}"/>'
                   f'<path d="{steam}{cup}{handle}{saucer}" fill="{ASH}"/>'
                   f'<ellipse cx="21" cy="24.6" rx="10.6" ry="0.9" fill="{INK}"/>'
                   + wordmark(21.0, 8.6, amp, outlined)
                   + ''.join(copy_line(t, 21.0, 52.6 + 3.0 * i - 3.0 * (len(price_lines) - 1), outlined)
                             for i, t in enumerate(price_lines)))
            edge = 'M6.8,0.8H35.2A6,6 0 0,1 41.2,6.8V48.2A6,6 0 0,1 35.2,54.2H6.8A6,6 0 0,1 0.8,48.2V6.8A6,6 0 0,1 6.8,0.8Z'
        if cut_line:   # the die line baked into the picture, the way the printer says it must never be
            art += f'<path id="cut-line" d="{edge}" fill="none" stroke="{ROAST}" stroke-width="0.3"/>'
        return w, h, art
    w, h, live = body(False)
    chars = 'MERIDIAN &ASH'
    copy = ''.join(sorted(set(''.join(price_lines))))
    defs = (f'<style>{font_face("DM Serif Display", DISPLAY, 400, chars)}'
            f'{font_face("Libre Franklin", FRANKLIN, 400, copy)}</style>')
    return SimpleNamespace(name=f'c{n}', w=w, h=h, body=live, outlined=body(True)[2], defs=defs)


@lru_cache(maxsize=None)
def cut_contour(st_key: str) -> tuple[np.ndarray, str]:
    """The kiss-cut contour of a sticker: its outer edge offset 2.5 mm outward, corners rounded to at least 3 mm,
    as (points in mm, path data)."""
    st = STICKERS[st_key]
    pad = 8.0                      # more than the offset plus the corner closing, so nothing reaches the raster edge
    W = round((st.w + 2 * pad) * PX_MM)
    svg = (f'<svg {NS} width="{num(st.w + 2 * pad)}mm" height="{num(st.h + 2 * pad)}mm" '
           f'viewBox="{-pad} {-pad} {num(st.w + 2 * pad)} {num(st.h + 2 * pad)}">{st.outlined}</svg>')
    alpha = np.asarray(Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_width=W))).convert('RGBA'))
    m = grow(alpha[..., 3] > 0, 2.5 * PX_MM)
    m = shrink(grow(m, 3 * PX_MM), 3 * PX_MM)
    c = cv2.approxPolyDP(outer(m).astype(np.int32).reshape(-1, 1, 2), 0.6, True).reshape(-1, 2) / PX_MM - pad
    return c, 'M' + ' '.join(f'{num(x)},{num(y)}' for x, y in c) + 'Z'


STICKERS: dict = {}


def register(key: str, st: SimpleNamespace) -> str:
    STICKERS[key] = st
    return key


def artwork(key: str, long_mm: float = LONG_MM, cut: bool = False, outlined: bool = False, style: str = '',
            extra: str = '') -> str:
    """A sticker artwork file: width and height in millimetres, a viewBox in millimetres and the artwork filling it.
    cut=True keeps the kiss-cut path on its own hidden layer named CutContour, outside the artwork."""
    st = STICKERS[key]
    s = long_mm / LONG_MM
    W, H = st.w * s, st.h * s

    def wrap(g):
        return g if s == 1 else f'<g transform="scale({num(s)})">{g}</g>'
    layer = ''
    if cut:   # a palette ink, as the sheet's attribute scan sees every stroke; the layer itself never prints
        path = f'<path d="{cut_contour(key)[1]}" fill="none" stroke="{ROAST}" stroke-width="0.25"/>'
        layer = (f'<g id="CutContour" inkscape:groupmode="layer" inkscape:label="CutContour" style="display:none">'
                 f'{wrap(path)}</g>')
    defs = (st.defs if not outlined else '') + (f'<style>{style}</style>' if style else '')
    return (f'<svg {NS} width="{num(W)}mm" height="{num(H)}mm" viewBox="0 0 {num(W)} {num(H)}">{defs}'
            f'<g id="artwork" inkscape:groupmode="layer" inkscape:label="Artwork">'
            f'{wrap((st.outlined if outlined else st.body) + extra)}</g>{layer}</svg>')


def cut_file(key: str) -> str:
    """The separate cut-contour file: one closed path on a CutContour layer, the canvas including the offset."""
    st = STICKERS[key]
    return (f'<svg {NS} width="{num(st.w + 5)}mm" height="{num(st.h + 5)}mm" viewBox="-2.5 -2.5 {num(st.w + 5)} '
            f'{num(st.h + 5)}"><g id="CutContour" inkscape:groupmode="layer" inkscape:label="CutContour">'
            f'<path d="{cut_contour(key)[1]}" fill="none" stroke="#EC008C" stroke-width="0.25"/></g></svg>')


def proof(svg: str) -> bytes:
    """The transparent 1600 x 1600 px proof: the artwork's long edge across the canvas, centred, alpha around it."""
    art = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_width=1600))).convert('RGBA')
    if art.height > 1600:
        art = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_height=1600))).convert('RGBA')
    canvas = Image.new('RGBA', (1600, 1600), (0, 0, 0, 0))
    canvas.alpha_composite(art, ((1600 - art.width) // 2, (1600 - art.height) // 2))
    buf = io.BytesIO()
    canvas.save(buf, 'PNG')
    return buf.getvalue()


def gang_sheet(path: Path, stickers, price_line: str):
    """The 305 x 457 mm imposed sheet: the six stickers (name, key, outlined svg) at 55 mm, their cut contours on a
    CutContour layer that can be selected apart from the artwork, 10 mm clear of the edge and at least 6 mm apart."""
    doc = pymupdf.open()
    page = doc.new_page(width=305 * PT, height=457 * PT)
    oc = doc.add_ocg('CutContour', on=True)
    with tempfile.TemporaryDirectory() as tmp:
        bold = Path(tmp) / 'LibreFranklin-Bold.ttf'
        font(FRANKLIN, 700).save(bold)
        for i, (name, key, svg) in enumerate(stickers):
            st = STICKERS[key]
            cx, cy = 305 / 2 + (i % 2 - 0.5) * 90, 80 + (i // 2) * 105
            x0, y0 = cx - st.w / 2, cy - st.h / 2
            art = pymupdf.open('pdf', cairosvg.svg2pdf(bytestring=svg.encode()))
            page.show_pdf_page(pymupdf.Rect(x0 * PT, y0 * PT, (x0 + st.w) * PT, (y0 + st.h) * PT), art, 0)
            pts, _ = cut_contour(key)
            shape = page.new_shape()
            shape.draw_polyline([pymupdf.Point((x0 + x) * PT, (y0 + y) * PT) for x, y in pts])
            shape.finish(color=(0.93, 0, 0.55), width=0.25 * PT, closePath=True, oc=oc)
            shape.commit()
            page.insert_text(((cx - 30) * PT, (cy + 36) * PT), f'{name.upper()} · 55 MM', fontsize=6, fontname='lfb',
                             fontfile=str(bold), color=(0.243, 0.165, 0.125))
        page.insert_text((20 * PT, 440 * PT), 'GANG SHEET · 55 MM · CUT CONTOUR ON ITS OWN LAYER', fontsize=6,
                         fontname='lfb', fontfile=str(bold), color=(0.243, 0.165, 0.125))
        page.insert_text((20 * PT, 431 * PT), price_line, fontsize=11, fontname='lfb', fontfile=str(bold),
                         color=(0.243, 0.165, 0.125))
        doc.save(path)


def build_stickers():
    """Every sticker variant the three sets use, traced once."""
    register('window-mark', window_sticker())
    register('bag-design-1', bag_sticker('moth'))
    register('bag-design-2', bag_sticker('pourover'))
    register('bag-design-3', bag_sticker('ridgeline'))
    register('bag-design-3-halftone', bag_sticker('ridgeline', halftone=True))
    good_price = ['$3 SINGLE / $9 FOUR-PACK']
    register('companion-1', companion(1, good_price))
    register('companion-2', companion(2, ['$3 SINGLE', '$9 FOUR-PACK']))
    register('companion-1-bad', companion(1, ['$14 SINGLE']))
    register('companion-1-amp', companion(1, good_price, amp=1.0))
    register('companion-2-cutline', companion(2, ['$3 SINGLE', '$9 FOUR-PACK'], cut_line=True))
    # Ink Black over 5%: the moth given a heavy black drop shadow
    st = STICKERS['bag-design-1']
    heavy = (st.back_d + f'<path d="{st.ink_d}" fill="{INK}" fill-rule="evenodd" transform="translate(1.1 1.1)"/>'
             f'<path d="{st.ink_d}" fill="{ROAST}" fill-rule="evenodd"/>')
    register('bag-design-1-ink', SimpleNamespace(**dict(vars(st), body=heavy, outlined=heavy)))


CUT_LAYER = {'window-mark', 'bag-design-2', 'companion-1'}       # stickers that keep a hidden CutContour layer


def vector04(out: Path, bad: bool):
    d = out / 'VECTOR-04' / 'deliverables'
    d.mkdir(parents=True, exist_ok=True)
    keys = {'window-mark': 'window-mark', 'bag-design-1': 'bag-design-1-ink' if bad else 'bag-design-1',
            'bag-design-2': 'bag-design-2', 'bag-design-3': 'bag-design-3',
            'companion-1': 'companion-1-bad' if bad else 'companion-1', 'companion-2': 'companion-2'}
    files, outlined = {}, {}
    for name, key in keys.items():
        st = STICKERS[key]
        style, extra = '', ''
        if bad and name == 'window-mark':   # off-palette red set through a CSS class
            style = '.accent{fill:#FF0000}'
            extra = f'<circle class="accent" cx="{num(st.w / 2)}" cy="{num(st.h * 0.8)}" r="3"/>'
        files[name] = artwork(key, cut=name in CUT_LAYER, style=style, extra=extra)
        outlined[name] = artwork(key, outlined=True, style=style, extra=extra)
        prefix = 'new-sticker' if name.startswith('companion') else 'recovered-sticker'
        (d / f'{prefix}-{name}.svg').write_text(files[name])
        (d / f'sticker-cut-{name}.svg').write_text(cut_file(key))
        (d / f'sticker-proof-{name}.png').write_bytes(proof(outlined[name]))
    gang_sheet(d / 'gang-sheet.pdf', [(name, key, outlined[name]) for name, key in keys.items()],
               f'Companion stickers: {"$12" if bad else "$3"} single, $9 four-pack')


def vector04_bad2(out: Path, good: Path):
    """The good files with one round-2 defect in each file DEFECTS2 names."""
    shutil.copytree(good / 'VECTOR-04', out / 'VECTOR-04')
    d = out / 'VECTOR-04' / 'deliverables'
    (d / 'recovered-sticker-window-mark.svg').write_text(artwork('window-mark', long_mm=70, cut=True))
    for n, photo in ((1, 'bag-design-3'), (2, 'bag-design-1'), (3, 'bag-design-2')):   # each traced from the wrong bag
        (d / f'recovered-sticker-bag-design-{n}.svg').write_text(artwork(photo, cut=f'bag-design-{n}' in CUT_LAYER))
    (d / 'sticker-proof-bag-design-3.png').write_bytes(proof(artwork('bag-design-3-halftone', outlined=True)))
    (d / 'new-sticker-companion-1.svg').write_text(artwork('companion-1-amp', cut=True))
    (d / 'new-sticker-companion-2.svg').write_text(artwork('companion-2-cutline'))

# ---------------------------------------------------------------- MOTION-11


JET, ORANGE, WHITE, ACID = (16, 16, 20), (255, 90, 31), (255, 255, 255), (182, 255, 46)
CAPTURES = M11 / 'staticfox_captures'
FRAME_AT = {1: 2.5, 2: 0.6, 3: 1.2, 4: 2.5, 5: 4.4, 6: 1.0}      # seconds: the moment each upload's joke lands
TITLE_PX = (132, 108)       # title size for short and long upload titles (the sizes OCR reads every title at)


def frame(size, lines, ground=JET):
    """lines: (text, x, y, px, colour, font); x may be 'c' to centre."""
    img = Image.new('RGB', size, ground)
    dr = ImageDraw.Draw(img)
    for text, x, y, px, colour, font_ in lines:
        f = ImageFont.truetype(str(font_), px)
        if x == 'c':
            x = (size[0] - dr.textlength(text, font=f)) / 2
        dr.text((x, y), text, fill=colour, font=f)
    return img


def wrap_title(title, size, px, font_, margin=60, right=None):
    f = ImageFont.truetype(str(font_), px)
    dr = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    width = (right or size[0]) - 2 * margin
    rows, line = [], ''
    for word in title.split():
        trial = (line + ' ' + word).strip()
        if dr.textlength(trial, font=f) > width and line:
            rows.append(line)
            line = word
        else:
            line = trial
    rows.append(line)
    return rows


def video(path: Path, frames, fps=2):
    with tempfile.TemporaryDirectory() as tmp:
        for i, img in enumerate(frames):
            img.save(Path(tmp) / f'f{i:04d}.png')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(fps), '-i', str(Path(tmp) / 'f%04d.png'),
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', str(path)], check=True)


@lru_cache(maxsize=None)
def capture_frame(n: int, size=(1920, 1080)) -> Image.Image:
    """One frame of staticfox_capture_0n.mp4, scaled to cover the thumbnail and centre-cropped."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(FRAME_AT[n]), '-i',
                        str(CAPTURES / f'staticfox_capture_{n:02d}.mp4'), '-frames:v', '1', str(Path(tmp) / 'f.png')],
                       check=True)
        img = Image.open(Path(tmp) / 'f.png').convert('RGB')
    s = max(size[0] / img.width, size[1] / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x, y = (img.width - size[0]) // 2, (img.height - size[1]) // 2
    return img.crop((x, y, x + size[0], y + size[1]))


def thumbnail(title: str, capture: int, defect: str | None = None, size=(1920, 1080),
              px: int | None = None) -> Image.Image:
    """The capture frame under the title, set white on a solid Jet Black band with a Fox Orange rule, and the
    upload line in Acid Signal on its own Jet Black tag."""
    img = capture_frame(capture, size).copy()
    dr = ImageDraw.Draw(img)
    shown = 'WE BROKE THE MAPS' if defect == 'spelling' else title
    px = px or (TITLE_PX[0] if len(title) < 30 else TITLE_PX[1])
    f = ImageFont.truetype(str(TITLE_FONT), px)
    margin = round(size[0] / 20)
    rows = wrap_title(shown, size, px, TITLE_FONT, margin=margin)
    # a band with clear room above and below the title, so nothing of the frame sits on the title's lines
    cap, lead, top, below = round(px * 0.86), round(px * 1.12), round(px * 0.45), round(px * 0.7)
    band = top + cap + (len(rows) - 1) * lead + below
    dr.rectangle((0, 0, size[0], band), fill=JET)
    dr.rectangle((0, band, size[0], band + round(px / 12)), fill=ORANGE)
    x = margin
    if defect == 'cut':        # round 1: the title pushed off the right edge
        x = round(size[0] * 0.594)
    if defect == 'clipped':    # round 2: the last letter half outside the frame
        last = dr.textlength(rows[-1][-1], font=f)
        x = size[0] - dr.textlength(rows[0], font=f) + last * 0.55
    for i, r in enumerate(rows):
        dr.text((x, top + cap + i * lead), r, font=f, fill=WHITE, anchor='ls')
    u = size[0] / 1920
    cpx = round((170 if defect == 'caption' else 45) * u)
    cf = ImageFont.truetype(str(TITLE_FONT), cpx)
    upload, base, pad = 'NEW ONE EVERY OTHER DAY', size[1] - round(60 * u), round(24 * u)
    dr.rectangle((margin - pad, base - round(cpx * 0.86) - pad, margin + dr.textlength(upload, font=cf) + pad, base + pad),
                 fill=JET)
    dr.text((margin, base), upload, font=cf, fill=ACID, anchor='ls')
    return img


def name_stack(name, x, y, px):
    """The channel name as the brand's title stack: the setup word in Anton over the payoff word in Archivo Black at
    150/190 of its size (lines for frame())."""
    setup, payoff = name.split(' ', 1)
    return [(setup, x, y, px, ORANGE, TITLE_FONT),
            (payoff, x, y + round(px * 1.3), round(px * 150 / 190), ORANGE, PAYOFF_FONT)]


def end_card(size, name='STATIC FOX', defect=None):
    """The held end card: the STATIC FOX stack first and largest, the end card copy, the members line, the handle."""
    members = 'Members get the Sunday chaos stream and the bloopers nobody should see. Link in the description.'
    rows = wrap_title(members, size, 38, BODY_FONT, margin=80)
    lines = [(r, 80, 475 + i * 52, 38, WHITE, BODY_FONT) for i, r in enumerate(rows)]
    lines.append(('@STATICFOX', 80, 650, 34, ORANGE, BODY_FONT))
    if defect == 'subscribe':   # round 2: the subscribe joke outshouts the channel name
        return frame(size, lines + name_stack(name, 80, 30, 56) + [
            ('SUBSCRIBE OR DAVE WINS', 80, 175, 104, WHITE, TITLE_FONT),
            ('NEW ONE EVERY OTHER DAY', 80, 365, 44, ACID, TITLE_FONT)])
    return frame(size, lines + name_stack(name, 80, 30, 127) + [
        ('NEW ONE EVERY OTHER DAY', 80, 335, 44, ACID, TITLE_FONT),
        ('SUBSCRIBE OR DAVE WINS', 80, 395, 44, WHITE, TITLE_FONT)])


def motion11(out: Path, bad: bool):
    spec = json.loads((ROOT / 'docs/gatsby-v7/tasks/MOTION-11/TASK_SPEC.json').read_text())
    titles = [line.split('. ', 1)[1] for line in (M11 / 'staticfox_titles.txt').read_text().splitlines()
              if line[:2] in {f'{i}.' for i in range(1, 7)}]
    d = out / 'MOTION-11'
    (d / 'deliverables').mkdir(parents=True, exist_ok=True)
    for o in spec['deliverables']:
        if not o['path'].endswith('.png') or 'thumbnail' not in o['path']:
            continue
        title = o['name'].split(' - ', 1)[1]
        defect = None
        if bad:
            defect = {'thumbnail-everyone-off-the-platform.png': 'cut', 'thumbnail-we-broke-the-map.png': 'spelling',
                      'thumbnail-kitchen-gone.png': 'caption'}.get(Path(o['path']).name)
        thumbnail(title, titles.index(title) + 1, defect).save(d / o['path'])
    tagline, upload = 'Co op disasters and bad decisions.', 'NEW ONE EVERY OTHER DAY'
    shown_upload = 'NEW ONE EVERY DAY' if bad else upload
    for name, vsize in (('channel-teaser.mp4', (1280, 720)), ('channel-teaser-vertical.mp4', (720, 1280))):
        frames = [frame(vsize, [('STATIC FOX', 'c', vsize[1] // 3, 110, ORANGE, TITLE_FONT)])] * 2
        frames += [frame(vsize, [(tagline, 'c', vsize[1] // 2, 40, WHITE, BODY_FONT)])] * 3
        frames += [frame(vsize, [(shown_upload, 'c', vsize[1] // 2, 60, ACID, TITLE_FONT)])] * 3
        video(d / 'deliverables' / name, frames)
    animation(d / 'deliverables' / 'channel-animation.mp4', 'STATIC FAX' if bad else 'STATIC FOX')


def animation(path: Path, name: str, defect: str | None = None):
    size = (1280, 720)
    scrap = Image.open(REFRESH / 'upload/MOTION-11/staticfox_scrap_transparent.png').convert('RGBA')
    scrap = scrap.resize((360, round(360 * scrap.height / scrap.width)))
    title_card = frame(size, name_stack(name, 120, 170, 127))
    title_card.paste(scrap, (880, 330), scrap)
    video(path, [title_card] * 3 + [end_card(size, name, defect)] * 5)


def motion11_bad2(out: Path, good: Path):
    """The good files with one round-2 defect in each file DEFECTS2 names."""
    shutil.copytree(good / 'MOTION-11', out / 'MOTION-11')
    d = out / 'MOTION-11' / 'deliverables'
    thumbnail('DO NOT OPEN THAT DOOR', 4, 'clipped').save(d / 'thumbnail-do-not-open-that-door.png')
    thumbnail('KITCHEN. GONE.', 6).save(d / 'thumbnail-kitchen-gone.png')
    thumbnail('I GAVE MY TEAM ONE SIMPLE JOB AND THEY SET THE ENTIRE BASE ON FIRE', 3).save(
        d / 'thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi.png')
    animation(d / 'channel-animation.mp4', 'STATIC FOX', 'subscribe')


def main():
    out = Path(sys.argv[1])
    for kind in ('good', 'bad', 'bad2'):
        for tid in ('VECTOR-04', 'MOTION-11'):
            shutil.rmtree(out / kind / tid, ignore_errors=True)
    build_stickers()
    for kind in ('good', 'bad'):
        vector04(out / kind, kind == 'bad')
        motion11(out / kind, kind == 'bad')
    vector04_bad2(out / 'bad2', out / 'good')
    motion11_bad2(out / 'bad2', out / 'good')
    (out / 'defects2_vector_motion.json').write_text(json.dumps(
        {k: {'rules': rules, 'defect': why} for k, (rules, why) in DEFECTS2.items()}, indent=1) + '\n')
    print('made', out)


if __name__ == '__main__':
    main()
