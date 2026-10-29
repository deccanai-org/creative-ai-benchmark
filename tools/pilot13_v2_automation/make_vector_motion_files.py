#!/usr/bin/env python3
"""Make VECTOR-04 and MOTION-11 test deliverables (no run produced any): a correct set and three sets with known defects.

good: every round-1, round-2 and round-3 rule holds.
VECTOR-04: six sticker SVGs measuring 55 mm on the long edge (width in mm, viewBox in mm, the artwork filling it). The
three bag stickers are traced with OpenCV from their own bag photos: the moth in Roast Brown, the pour-over cone in
Ash Green, and the ridge line, whose halftone is blurred into its tone and redrawn as solid shapes and line hatching,
in Brick Red, each on a Kraft die-cut backing. The window mark is the traced leaf in an Ash Green roundel inside a Warm
Cream hairline ring, open (transparent) between ring and roundel as on the glass, under arched lettering drawn as
outlines, on a Kraft backing. The two companions (two coffee beans in Brick Red on an arched Warm Cream badge, a cup in
Ash Green on a Warm Cream tile) carry MERIDIAN & ASH as live DM Serif Display capitals at 18 pt arched on a 40 degree
curve (a textPath), the ampersand at 1.6 times the capitals hanging below the arc, and the $3 single / $9 four-pack
prices in Libre Franklin 400 at 7 pt on 10.5 pt. Ink Black is not used. Some stickers keep their kiss-cut path on a
hidden 'CutContour' layer, never in the artwork. Also the six cut-contour SVGs, six transparent 1600 px proofs and the
imposed 305 x 457 mm sheet: every colour in PSO Coated v3 CMYK (the palette's sRGB converted with PSOcoated_v3.icc,
which the sheet carries as its output intent), the cut paths stroked in a CutContour spot colour on the CutContour
layer, and the labels in Libre Franklin Bold capitals at 6 pt on 8.5 pt, tracked 0.04 em, in Roast Brown.
MOTION-11: 1920 x 1080 thumbnails on a native-size frame of their own capture: the title set as the brand's stack
(Anton setup rows at 190 px, the payoff word alone on the last row in Archivo Black at 150 px tracked -0.015 em; 96 and
76 px on the two long titles), White and Acid Signal fills with a hard Jet Black outline on a Static Purple band over a
Fox Orange rule, and Scrap (the supplied cutout, solid inside his anti-aliased edge) standing on the bottom edge, clear
of the title and of capture 04's webcam window, with nothing laid over the capture. The channel animation (24 fps, 7 s,
silent) slides Scrap in and scales the outlined STATIC FOX stack up, then holds the end card for 3 s. The two teasers
(24 fps, the music bed cut from staticfox_bed.wav) open on the tagline, cut native-size shots from five captures
(three of them, letterboxed below native size, in the upright cutdown) without reusing source time, and close on a held
end card with the upload line, SUBSCRIBE OR DAVE WINS and @STATICFOX in Inter SemiBold, and Scrap.
bad: the round-1 defects (PLANTED in decide_moves.py) on the good content: an off-palette red set through a CSS class
(invisible to an attribute scan), Ink Black over 5% of the ink, a $14 price on a sticker, its proof and a $12 one on
the sheet; a title cut off at the edge, a misspelt title, a caption larger than the title, a changed upload line,
a wrong channel name.
bad2: the good set with one round-2 defect in some files (DEFECTS2, written to <out>/defects2_vector_motion.json).
bad3: the good set with one round-3 defect in each file DEFECTS3 names, merged into <out>/defects3.json (whose
LAYOUT-12 keys make_layout12_files.py writes). Derived files keep the good artwork, as in bad2, so a defect in a
sticker SVG also shows where its proof (R001) or the sheet (R047 to R049) is compared with it.

bad4 (round 4, MOTION-11 only): the good set with one round-4 defect in each file DEFECTS4_VIDEO names, written by
python make_vector_motion_files.py --bad4 <out dir> (defects in <out>/defects4_video.json).

Usage: python make_vector_motion_files.py <out dir>   (writes <out>/{good,bad,bad2,bad3}/<TASK>/deliverables/...)
Run with the benchmark_v4 venv (PyMuPDF, cairosvg, OpenCV, fontTools) with ffmpeg on PATH.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import wave
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('DYLD_FALLBACK_LIBRARY_PATH', '/opt/homebrew/lib:/usr/local/lib:/usr/lib')  # Homebrew Cairo
import cairosvg  # noqa: E402
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pymupdf  # noqa: E402
from fontTools.pens.boundsPen import BoundsPen  # noqa: E402
from fontTools.pens.svgPathPen import SVGPathPen  # noqa: E402
from fontTools.pens.transformPen import TransformPen  # noqa: E402
from fontTools.subset import Options, Subsetter  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from fontTools.varLib.instancer import instantiateVariableFont  # noqa: E402
from PIL import Image, ImageCms, ImageDraw, ImageFilter, ImageFont  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
V04, M11 = REFRESH / 'sources/VECTOR-04', REFRESH / 'sources/MOTION-11'
ROAST, KRAFT, ASH, CREAM, BRICK, INK = '#3E2A20', '#C8A97E', '#5B6B54', '#F3E7D3', '#A8442E', '#201914'
PALETTE = (ROAST, KRAFT, ASH, CREAM, BRICK, INK)
TITLE_FONT = REFRESH / 'fonts/anton/Anton-Regular.ttf'
PAYOFF_FONT = REFRESH / 'fonts/archivoblack/ArchivoBlack-Regular.ttf'
INTER = REFRESH / 'upload/MOTION-11/fonts/Inter[opsz,wght].ttf'
DISPLAY = str(REFRESH / 'fonts/dmserifdisplay/DMSerifDisplay-Regular.ttf')     # brand display face
FRANKLIN = str(REFRESH / 'fonts/librefranklin/LibreFranklin[wght].ttf')        # brand text face (variable)
ICC = REFRESH / 'upload/VECTOR-04/PSOcoated_v3.icc'                          # the printer's output profile
LONG_MM = 55          # every sticker artwork measures 55 mm on its long edge
PX_MM = 20            # raster resolution for tracing and offsetting, pixels per millimetre
PT = 72 / 25.4        # PDF points per millimetre
LEAD_MM = 10.5 / PT   # type scale step 03: sticker copy at 7 pt on 10.5 pt
NS = ('xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
      'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"')

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
    'MOTION-11/thumbnail-do-not-open-that-door': (
        ['R018'], 'the title stack is set against the right edge and runs past it: the last letters of THAT and DOOR '
                  'are cut in half'),
    'MOTION-11/thumbnail-kitchen-gone': (
        ['R033'], 'built on a frame from staticfox_capture_06.mp4 (the burning base), not capture 03'),
    'MOTION-11/thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi': (
        ['R033'], 'built on a frame from staticfox_capture_03.mp4 (the kitchen fire), not capture 06'),
    'MOTION-11/channel-animation': (['R119'], 'held end card: SUBSCRIBE OR DAVE WINS set larger than STATIC FOX'),
}
# round-3 defects planted in the bad3 set: file -> (every rule it breaks, what is wrong)
DEFECTS3 = {
    'VECTOR-04/recovered-sticker-window-mark': (
        ['R051'], 'the hairline ring is filled in as a solid Warm Cream disc behind the roundel, with no open space '
                  'between ring and roundel'),
    'VECTOR-04/recovered-sticker-bag-design-1': (
        ['R100', 'R045', 'R054'], 'a soft drop shadow (the moth again in Roast Brown at 40% opacity through a '
                                  'Gaussian blur filter) sits behind the moth, rendering an off-palette tint'),
    'VECTOR-04/recovered-sticker-bag-design-2': (
        ['R071', 'R100', 'R079'], 'an Ink Black copy of the cone sits 0.2 mm behind it as a hard offset shadow, a '
                                  'main shape in Ink Black showing on just over 5% of the ink'),
    'VECTOR-04/recovered-sticker-bag-design-3': (['R100'], 'the ridge line ink is set to the Multiply blend mode'),
    'VECTOR-04/new-sticker-companion-1': (
        ['R089'], 'MERIDIAN & ASH is set flat on one straight baseline, not arched on the 40 degree curve'),
    'VECTOR-04/new-sticker-companion-2': (['R070'], 'the price lines are set in Brick Red on the Warm Cream tile'),
    'VECTOR-04/sticker-cut-window-mark': (['R007'], 'the cut path is offset 1.5 mm from the artwork, not 2.5 mm'),
    'VECTOR-04/sticker-cut-bag-design-1': (
        ['R008'], 'the cut path is offset 2.5 mm with its corners left unrounded (inner corners sharp, outer ones '
                  '2.5 mm)'),
    'VECTOR-04/sticker-cut-bag-design-2': (['R009'], 'a second closed path cuts round an island inside the artwork'),
    'VECTOR-04/sticker-cut-bag-design-3': (['R020'], "the cut path's layer is named Layer 1, not CutContour"),
    'VECTOR-04/sticker-cut-companion-1': (
        ['R021', 'R009'], 'the sticker artwork is copied into the CutContour layer beside the cut path'),
    'VECTOR-04/sticker-cut-companion-2': (['R017'], 'the SVG declares no viewBox'),
    'VECTOR-04/sticker-proof-window-mark': (
        ['R076', 'R001'], 'the ash leaf is Kraft, not Warm Cream, so the proof no longer matches the SVG'),
    'VECTOR-04/sticker-proof-bag-design-1': (
        ['R018', 'R057', 'R001'], 'an opaque white rectangle fills the whole proof behind the sticker'),
    'VECTOR-04/sticker-proof-bag-design-2': (
        ['R101', 'R001'], 'a soft, semi-transparent drop shadow is painted under the sticker'),
    'VECTOR-04/sticker-proof-bag-design-3': (
        ['R022', 'R057', 'R001'], 'the magenta cut line is drawn round the artwork'),
    'VECTOR-04/sticker-proof-companion-1': (
        ['R097', 'R001'], 'the wordmark is set at 13 pt, its capitals about 88 px tall'),
    'VECTOR-04/sticker-proof-companion-2': (['R074', 'R062', 'R001'], 'the price lines are set in Ink Black'),
    'VECTOR-04/gang-sheet': (['R080'], 'the Bag design 1 sticker is left in RGB; everything else is CMYK'),
    'MOTION-11/thumbnail-we-broke-the-map': (['R055'], 'the payoff word MAP has no Jet Black outline'),
    'MOTION-11/thumbnail-everyone-off-the-platform': (
        ['R078', 'R058'], 'a 45% Jet Black scrim darkens the capture below the title panel'),
    'MOTION-11/thumbnail-kitchen-gone': (['R064', 'R065'], 'the title panel is Acid Signal, not Static Purple'),
    'MOTION-11/thumbnail-do-not-open-that-door': (['R048'], "Scrap stands over half of capture 04's webcam window"),
    'MOTION-11/thumbnail-we-spent-six-hours-building-a-bridge-and-then-drove-straight-pas': (
        ['R082', 'R120'], 'the long title stack is set at 64 px, its setup capitals about 55 px tall'),
    'MOTION-11/thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi': (
        ['R086', 'R098'], 'the payoff word FIRE is set in Anton at the setup size, not in Archivo Black'),
    'MOTION-11/channel-teaser': (['R028'], "capture 02's shot is played twice and capture 06's dropped"),
    'MOTION-11/channel-teaser-vertical': (['R037'], 'the music is a synthesised loop, not staticfox_bed.wav'),
    'MOTION-11/channel-animation': (['R066'], 'STATIC and FOX carry no Jet Black outline on the end card'),
}

# ---------------------------------------------------------------- type as outlines and as embedded fonts


@lru_cache(maxsize=None)
def font(path: str, weight: int = 400) -> TTFont:
    f = TTFont(path)
    # the Libre Franklin file's default instance is Thin: set the weight the type system names
    return instantiateVariableFont(f, {'wght': weight}) if 'fvar' in f else f


def static_font(var_path, family: str, style: str, axes: dict, out: Path) -> Path:
    """A named static instance of a variable font, so a PDF records e.g. LibreFranklin-Bold, not the default Thin."""
    f = instantiateVariableFont(TTFont(var_path), axes)
    ps = f'{family.replace(" ", "")}-{style}'
    for rec in f['name'].names:
        if rec.nameID in (1, 16):
            rec.string = family
        elif rec.nameID in (2, 17):
            rec.string = style
        elif rec.nameID == 4:
            rec.string = f'{family} {style}'
        elif rec.nameID == 6:
            rec.string = ps
    path = out / f'{ps}.ttf'
    f.save(path)
    return path


def num(v: float) -> str:
    return f'{v:.3f}'.rstrip('0').rstrip('.')


def rgb255(h: str) -> tuple:
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


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

# ---------------------------------------------------------------- the arched wordmark (type scale step 01)


WORDMARK_PT, AMP, DROP, ARC_DEG = 18, 1.6, 0.36, 40


def arch(size: float, amp: float = AMP, cx: float = 27.5, base_y: float = 6.4) -> SimpleNamespace:
    """MERIDIAN & ASH on a circle: the capitals at size (mm), the ampersand at amp times their size hanging DROP of the
    capitals' size below the arc, the circle chosen so the inked letters, from the M's left edge to the H's right edge,
    span ARC_DEG degrees, centred on the apex (baseline base_y). Letter spacing stays 0: the +0.03 em the type scale
    opens on the curve would carry the 40 degree arch past the 55 mm sticker. The path runs from 10 degrees beyond
    the text's start to 10 degrees beyond its end; start is the run's offset along it."""
    f = font(DISPLAY)
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f['head'].unitsPerEm
    drop = DROP * size if amp > 1 else 0.0
    runs = [('MERIDIAN ', size, 0.0), ('&', size * amp, drop), (' ASH', size, 0.0)]
    total = sum(text_width(DISPLAY, t, s) for t, s, _ in runs)

    def bounds(ch):
        bp = BoundsPen(gs)
        gs[cmap[ord(ch)]].draw(bp)
        return bp.bounds
    lsb = bounds('M')[0] * size / upm
    rsb = (gs[cmap[ord('H')]].width - bounds('H')[2]) * size / upm
    ink = total - lsb - rsb
    r = ink / math.radians(ARC_DEG)
    beta = math.radians(ARC_DEG / 2 + 10)
    return SimpleNamespace(runs=runs, cx=cx, cy=base_y + r, r=r, beta=beta, start=beta * r - lsb - ink / 2, total=total)


def arc_d(a) -> str:
    y = a.cy - a.r * math.cos(a.beta)
    return (f'M{num(a.cx - a.r * math.sin(a.beta))},{num(y)}A{num(a.r)},{num(a.r)} 0 0,1 '
            f'{num(a.cx + a.r * math.sin(a.beta))},{num(y)}')


def arch_outline(a) -> str:
    """The arched wordmark as outlines, placed the way an SVG textPath places glyphs: each glyph's advance centred on
    its point of the arc, turned to the arc there, the ampersand moved its drop towards the centre."""
    f = font(DISPLAY)
    gs, cmap, upm = f.getGlyphSet(), f.getBestCmap(), f['head'].unitsPerEm
    pen = SVGPathPen(gs, ntos=num)
    s = a.start
    for text, size, drop in a.runs:
        k = size / upm
        for ch in text:
            g = gs[cmap[ord(ch)]]
            adv = g.width * k
            ang = (s + adv / 2) / a.r - a.beta
            tx, ty = math.cos(ang), math.sin(ang)                     # along the arc
            nx, ny = math.sin(ang), -math.cos(ang)                    # away from the centre (up at the apex)
            px, py = a.cx + a.r * math.sin(ang), a.cy - a.r * math.cos(ang)
            g.draw(TransformPen(pen, (k * tx, k * ty, k * nx, k * ny, px - adv / 2 * tx - drop * nx,
                                      py - adv / 2 * ty - drop * ny)))
            s += adv
    return pen.getCommands()


def arch_live(a, colour: str = ROAST) -> tuple[str, str]:
    """(defs, text): the arched wordmark as live type on a textPath, the ampersand a larger tspan moved down."""
    (_, s1, _), (_, s2, d), (_, s3, _) = a.runs
    defs = f'<defs><path id="arch" d="{arc_d(a)}" fill="none"/></defs>'
    text = (f'<text font-family="DM Serif Display" font-size="{num(s1)}" fill="{colour}">'
            f'<textPath href="#arch" xlink:href="#arch" startOffset="{num(a.start)}">MERIDIAN '
            f'<tspan font-size="{num(s2)}" dy="{num(d)}">&amp;</tspan><tspan font-size="{num(s3)}" dy="{num(-d)}"> '
            f'ASH</tspan></textPath></text>')
    return defs, text

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


def ellipse_d(cx: float, cy: float, rx: float, ry: float) -> str:
    return (f'M{num(cx - rx)},{num(cy)}a{num(rx)},{num(ry)} 0 1,0 {num(2 * rx)},0'
            f'a{num(rx)},{num(ry)} 0 1,0 {num(-2 * rx)},0Z')


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
                           back_d=back_d, ink_d=ink_d, colour=colour)


def variant(st: SimpleNamespace, body: str, defs: str = '') -> SimpleNamespace:
    """A sticker with the same size and backing but another body (a defect)."""
    return SimpleNamespace(**dict(vars(st), body=body, outlined=body, defs=defs))

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
def window_sticker(leaf_ink: str = CREAM, open_ring: bool = True) -> SimpleNamespace:
    """The window mark: the Ash Green roundel and Warm Cream ring fitted to meridian_window_mark.jpg, its painted leaf
    traced, and MERIDIAN & ASH arched over it as Roast Brown outlines, on a Kraft die-cut backing with the gap between
    ring and roundel left open (transparent), as the glass shows between them. open_ring=False fills ring and gap in
    as one Warm Cream disc behind the roundel (a defect); leaf_ink recolours the leaf (a defect)."""
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
    ring = ellipse_d(cx, cy, ax * 1.163, ay * 1.163) + ellipse_d(cx, cy, ax * 1.127, ay * 1.127)
    disc = (f'<path d="{ring}" fill="{CREAM}" fill-rule="evenodd"/>' if open_ring else
            f'<path d="{ellipse_d(cx, cy, ax * 1.163, ay * 1.163)}" fill="{CREAM}"/>')
    px_body = (disc + f'<ellipse cx="{num(cx)}" cy="{num(cy)}" rx="{num(ax)}" ry="{num(ay)}" fill="{ASH}"/>'
               f'<path d="{mask_path(leaf, 1, 0, 0)}" fill="{leaf_ink}" fill-rule="evenodd"/>'
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
    # the open gap: the backing has a hole the size of the ring's inner edge, which the roundel then covers
    hole = ellipse_d((cx - x0) * k, (cy - y0) * k, ax * 1.127 * k, ay * 1.127 * k) if open_ring else ''
    body = (f'<path d="{mask_path(back, 2 * k, x0 / 2, y0 / 2, outer_only=True)}{hole}" fill="{KRAFT}" '
            f'fill-rule="evenodd"/>'
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


def wordmark(cx: float, base: float, amp: float, outlined: bool, size: float = 11 / PT) -> str:
    """MERIDIAN & ASH set flat on one baseline in DM Serif Display capitals (a defect on the companions, which arch
    it), the ampersand at amp times their size hanging below the baseline (at 1.0 it sits on it at cap height)."""
    track = 0.02 * size if size < 12 / PT else 0.0
    drop = DROP * size if amp > 1 else 0.0
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


def copy_line(text: str, cx: float, base: float, outlined: bool, size: float = 7 / PT, colour: str = ROAST) -> str:
    """A line of sticker copy in Libre Franklin Regular 400, centred."""
    x = cx - text_width(FRANKLIN, text, size) / 2
    if outlined:
        return f'<path d="{outline(FRANKLIN, text, x, base, size)[0]}" fill="{colour}"/>'
    return (f'<text x="{num(x)}" y="{num(base)}" font-family="Libre Franklin" font-weight="400" font-size="{num(size)}" '
            f'fill="{colour}">{text}</text>')


def companion(n: int, price_lines, amp: float = AMP, cut_line: bool = False, word_pt: float = WORDMARK_PT,
              flat: bool = False, copy_ink: str = ROAST) -> SimpleNamespace:
    """An original companion, 55 mm wide under the arched wordmark: 1 is two coffee beans in Brick Red on an arched
    Warm Cream badge (its top concentric with the wordmark's arc), 2 a cup of coffee in Ash Green on a Warm Cream
    tile; both carry the wordmark (live type on a textPath; outlines for proofs and the sheet) and the prices as
    Libre Franklin copy, two lines on 10.5 pt leading. Defects: flat (the wordmark on a straight line), word_pt (its
    size), copy_ink (the copy colour), amp (the ampersand's size), cut_line (a cut line drawn into the art)."""
    a = arch(word_pt / PT, amp)

    def body(outlined):
        w, h = 55.0, 50.0
        if n == 1:
            top = a.cy - math.sqrt(a.cy ** 2 - 27.5 ** 2)          # where the badge's arc meets its sides
            art = (f'<path d="M0,44V{num(top)}A{num(a.cy)},{num(a.cy)} 0 0,1 55,{num(top)}V44A6,6 0 0,1 49,50H6'
                   f'A6,6 0 0,1 0,44Z" fill="{CREAM}"/>')
            oval1, crease1 = bean(24.0, 27.0, 11.6, 7.7, -28)
            oval2, crease2 = bean(41.0, 31.0, 5.0, 3.4, 38)
            art += f'<path d="{oval1}{oval2}" fill="{BRICK}"/><path d="{crease1}{crease2}" fill="{CREAM}"/>'
            base = 45.2
            edge = 'M0.8,44V5.6A78,78 0 0,1 54.2,5.6V44A5.2,5.2 0 0,1 49,49.2H6A5.2,5.2 0 0,1 0.8,44Z'
        else:
            steam = ''.join(taper(curve(np.array([x, 21.0]), np.array([x - 3, 17.0]), np.array([x + 3, 14.5]),
                                        np.array([x, 11.2])), 1.5) for x in (16.5, 21.0, 25.5))
            cup = 'M9.5,23.5L32.5,23.5L31.0,36.5C30.6,40.5 27.5,42.0 21.0,42.0C14.5,42.0 11.4,40.5 11.0,36.5Z'
            handle = 'M31.2,26.0C37.8,25.6 39.2,34.4 30.4,35.8L30.6,33.4C35.4,32.6 35.0,28.0 31.4,28.4Z'
            saucer = 'M5.5,43.2C5.5,41.4 36.5,41.4 36.5,43.2C36.5,45.6 5.5,45.6 5.5,43.2Z'
            art = (f'<rect x="0" y="0" width="55" height="50" rx="6" fill="{CREAM}"/>'
                   f'<g transform="translate(27.5 30) scale(0.82) translate(-21 -33)">'
                   f'<path d="{steam}{cup}{handle}{saucer}" fill="{ASH}"/>'
                   f'<ellipse cx="21" cy="24.6" rx="10.6" ry="0.9" fill="{ROAST}"/></g>')
            base = 47.9 - LEAD_MM * (len(price_lines) - 1)
            edge = ('M6.8,0.8H48.2A6,6 0 0,1 54.2,6.8V43.2A6,6 0 0,1 48.2,49.2H6.8A6,6 0 0,1 0.8,43.2V6.8'
                    'A6,6 0 0,1 6.8,0.8Z')
        if flat:
            mark = wordmark(27.5, 8.4, amp, outlined, word_pt / PT)
        else:
            mark = f'<path d="{arch_outline(a)}" fill="{ROAST}"/>' if outlined else arch_live(a)[1]
        art += mark + ''.join(copy_line(t, 27.5, base + LEAD_MM * i, outlined, colour=copy_ink)
                              for i, t in enumerate(price_lines))
        if cut_line:   # the die line baked into the picture, the way the printer says it must never be
            art += f'<path id="cut-line" d="{edge}" fill="none" stroke="{ROAST}" stroke-width="0.3"/>'
        return w, h, art
    w, h, live = body(False)
    copy = ''.join(sorted(set(''.join(price_lines))))
    defs = (f'<style>{font_face("DM Serif Display", DISPLAY, 400, "MERIDIAN &ASH")}'
            f'{font_face("Libre Franklin", FRANKLIN, 400, copy)}</style>' + ('' if flat else arch_live(a)[0]))
    return SimpleNamespace(name=f'c{n}', w=w, h=h, body=live, outlined=body(True)[2], defs=defs)


@lru_cache(maxsize=None)
def cut_contour(st_key: str, offset: float = 2.5, round_mm: float = 3.0) -> tuple[np.ndarray, str]:
    """The kiss-cut contour of a sticker: its outer edge offset 2.5 mm outward, corners rounded to at least 3 mm,
    as (points in mm, path data). round_mm=0 leaves the offset's corners as they come (a defect)."""
    st = STICKERS[st_key]
    pad = 8.0                      # more than the offset plus the corner closing, so nothing reaches the raster edge
    W = round((st.w + 2 * pad) * PX_MM)
    svg = (f'<svg {NS} width="{num(st.w + 2 * pad)}mm" height="{num(st.h + 2 * pad)}mm" '
           f'viewBox="{-pad} {-pad} {num(st.w + 2 * pad)} {num(st.h + 2 * pad)}">{st.outlined}</svg>')
    alpha = np.asarray(Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_width=W))).convert('RGBA'))
    m = grow(fill_holes(alpha[..., 3] > 0), offset * PX_MM)
    if round_mm:
        m = shrink(grow(m, round_mm * PX_MM), round_mm * PX_MM)
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


def island_d(key: str) -> str:
    """Path data round the largest uninked island inside a sticker's ink (the inside of the carafe), for a cut file
    that cuts it out as well (a defect)."""
    st = STICKERS[key]
    W = round(st.w * PX_MM)
    svg = (f'<svg {NS} width="{num(st.w)}mm" height="{num(st.h)}mm" viewBox="0 0 {num(st.w)} {num(st.h)}">'
           f'<path d="{st.ink_d}" fill="#000" fill-rule="evenodd"/></svg>')
    ink = np.asarray(Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_width=W))).convert('RGBA'))[..., 3] > 128
    holes = fill_holes(ink) & ~ink
    n, lab, stats, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8), connectivity=4)
    m = shrink(lab == 1 + int(np.argmax(stats[1:, 4])), 0.4 * PX_MM)
    c = cv2.approxPolyDP(outer(m).astype(np.int32).reshape(-1, 1, 2), 0.6, True).reshape(-1, 2) / PX_MM
    return 'M' + ' '.join(f'{num(x)},{num(y)}' for x, y in c) + 'Z'


def cut_file(key: str, offset: float = 2.5, round_mm: float = 3.0, layer: str = 'CutContour', art: bool = False,
             view_box: bool = True, island: bool = False) -> str:
    """The separate cut-contour file: one closed path on a CutContour layer, the canvas including the offset. The
    other settings plant defects: the offset, unrounded corners, the layer's name, the artwork copied in, no viewBox,
    a second path round an island."""
    st = STICKERS[key]
    paths = f'<path d="{cut_contour(key, offset, round_mm)[1]}" fill="none" stroke="#EC008C" stroke-width="0.25"/>'
    if island:
        paths += f'<path d="{island_d(key)}" fill="none" stroke="#EC008C" stroke-width="0.25"/>'
    if art:
        paths = st.outlined + paths
    lid = layer.replace(' ', '_')
    vb = f' viewBox="-2.5 -2.5 {num(st.w + 5)} {num(st.h + 5)}"' if view_box else ''
    return (f'<svg {NS} width="{num(st.w + 5)}mm" height="{num(st.h + 5)}mm"{vb}><g id="{lid}" '
            f'inkscape:groupmode="layer" inkscape:label="{layer}">{paths}</g></svg>')


def proof(svg: str, white: bool = False, shadow: bool = False) -> bytes:
    """The transparent 1600 x 1600 px proof: the artwork's long edge across the canvas, centred, alpha around it.
    white=True fills the canvas opaque white behind it; shadow=True paints a soft drop shadow under it (defects)."""
    art = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_width=1600))).convert('RGBA')
    if art.height > 1600:
        art = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_height=1600))).convert('RGBA')
    canvas = Image.new('RGBA', (1600, 1600), (255, 255, 255, 255) if white else (0, 0, 0, 0))
    at = ((1600 - art.width) // 2, (1600 - art.height) // 2)
    if shadow:
        a = np.asarray(art)[..., 3].astype(np.float32) * 0.45
        sh = np.zeros((1600, 1600, 4), np.uint8)
        sh[..., :3] = rgb255(ROAST)
        sh[at[1] + 18:at[1] + 18 + art.height, at[0] + 18:at[0] + 18 + art.width, 3] = a[:1600 - at[1] - 18, :1600 - at[0] - 18]
        canvas.alpha_composite(Image.fromarray(sh).filter(ImageFilter.GaussianBlur(14)))
    canvas.alpha_composite(art, at)
    buf = io.BytesIO()
    canvas.save(buf, 'PNG')
    return buf.getvalue()

# ---------------------------------------------------------------- the CMYK production sheet


@lru_cache(maxsize=None)
def pso(hex_: str) -> tuple:
    """A colour in PSO Coated v3 CMYK (0 to 1): its sRGB value converted with PSOcoated_v3.icc, relative
    colorimetric, as the brief asks for the print PDF."""
    t = ImageCms.buildTransform(ImageCms.createProfile('sRGB'), ImageCms.getOpenProfile(str(ICC)), 'RGB', 'CMYK',
                                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
    return tuple(v / 255 for v in ImageCms.applyTransform(Image.new('RGB', (1, 1), rgb255(hex_)), t).getpixel((0, 0)))


def cmyk_pdf(svg: str, keep_rgb: bool = False) -> pymupdf.Document:
    """A sticker's artwork as a one-page PDF (cairo), every RGB colour operator rewritten as the PSO Coated v3 CMYK
    of its colour (a palette colour within one level is taken as that palette colour), and the page's RGB blending
    group dropped (nothing on it is transparent). keep_rgb leaves it in RGB (a defect)."""
    doc = pymupdf.open('pdf', cairosvg.svg2pdf(bytestring=svg.encode()))
    if keep_rgb:
        return doc
    pal = {rgb255(h): h for h in PALETTE}

    def repl(m):
        rgb = tuple(round(float(v) * 255) for v in m.groups()[:3])
        near = min(pal, key=lambda p: max(abs(a - b) for a, b in zip(p, rgb)))
        hx = pal[near] if max(abs(a - b) for a, b in zip(near, rgb)) <= 1 else '#%02X%02X%02X' % rgb
        return ' '.join(f'{v:.4f}' for v in pso(hx)) + (' k' if m.group(4) == 'rg' else ' K')
    for page in doc:
        for x in page.get_contents():
            s = doc.xref_stream(x).decode('latin-1')
            s = re.sub(r'(?<![\w.])(\d*\.?\d+) (\d*\.?\d+) (\d*\.?\d+) (rg|RG)\b', repl, s)
            doc.update_stream(x, s.encode('latin-1'))
        doc.xref_set_key(page.xref, 'Group', 'null')
    return doc


CUT_STAND_IN = (0.11, 0.22, 0.33)       # the cut stroke's colour as drawn, before it is repainted in the spot


def cut_spot(doc: pymupdf.Document, page: pymupdf.Page):
    """Repaint the cut paths (stroked in CUT_STAND_IN) in a Separation colour named CutContour, magenta as its
    alternate, added to the page's colour spaces."""
    for x in page.get_contents():
        s = doc.xref_stream(x).decode('latin-1')
        doc.update_stream(x, re.sub(r'\.11 \.22 \.33 RG', '/CutContour CS 1 SCN', s).encode('latin-1'))
    spot = ('<</CutContour [/Separation /CutContour /DeviceCMYK <</FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] '
            '/C1 [0 1 0 0] /N 1>>]>>')
    kind, val = doc.xref_get_key(page.xref, 'Resources')
    if kind == 'xref':
        doc.xref_set_key(int(val.split()[0]), 'ColorSpace', spot)
    else:
        doc.xref_set_key(page.xref, 'Resources/ColorSpace', spot)


def output_intent(doc: pymupdf.Document):
    """The PSO Coated v3 profile as the PDF's output intent, so a colour-managed viewer proofs the CMYK as printed."""
    x = doc.get_new_xref()
    doc.update_object(x, '<< /N 4 >>')
    doc.update_stream(x, ICC.read_bytes())
    doc.xref_set_key(doc.pdf_catalog(), 'OutputIntents',
                     f'[<< /Type /OutputIntent /S /GTS_PDFX /OutputConditionIdentifier (PSO Coated v3) '
                     f'/Info (PSO Coated v3) /DestOutputProfile {x} 0 R >>]')


def gang_sheet(path: Path, stickers, price_line: str, rgb_key: str | None = None):
    """The 305 x 457 mm imposed sheet: the six stickers (name, key, outlined svg) at 55 mm in CMYK, their cut contours
    on a CutContour layer that can be selected apart from the artwork, stroked in the CutContour spot, 10 mm clear of
    the edge and at least 6 mm apart; slug labels in Libre Franklin Bold 700 capitals at 6 pt on 8.5 pt, tracked
    0.04 em, in the CMYK of Roast Brown. rgb_key leaves that sticker in RGB (a defect)."""
    doc = pymupdf.open()
    page = doc.new_page(width=305 * PT, height=457 * PT)
    oc = doc.add_ocg('CutContour', on=True)
    with tempfile.TemporaryDirectory() as tmp:
        bold = static_font(FRANKLIN, 'Libre Franklin', 'Bold', {'wght': 700}, Path(tmp))

        def label(x, y, text):
            sh = page.new_shape()
            sh.insert_text((x * PT, y * PT), text, fontsize=6, fontname='lfb', fontfile=str(bold), color=pso(ROAST))
            sh.text_cont = sh.text_cont.replace(' Tf ', f' Tf {0.04 * 6:.3f} Tc ', 1)
            sh.commit()
        for i, (name, key, svg) in enumerate(stickers):
            st = STICKERS[key]
            cx, cy = 305 / 2 + (i % 2 - 0.5) * 90, 80 + (i // 2) * 105
            x0, y0 = cx - st.w / 2, cy - st.h / 2
            art = cmyk_pdf(svg, keep_rgb=key == rgb_key)
            page.show_pdf_page(pymupdf.Rect(x0 * PT, y0 * PT, (x0 + st.w) * PT, (y0 + st.h) * PT), art, 0)
            pts, _ = cut_contour(key)
            shape = page.new_shape()
            shape.draw_polyline([pymupdf.Point((x0 + x) * PT, (y0 + y) * PT) for x, y in pts])
            shape.finish(color=CUT_STAND_IN, width=0.25 * PT, closePath=True, oc=oc)
            shape.commit()
            label(cx - 30, cy + 36, f'{name.upper().replace("-", " ")} · 55 MM')
        label(20, 431, price_line)
        label(20, 431 + 8.5 / PT, 'GANG SHEET · 55 MM · CUT CONTOUR ON ITS OWN LAYER')
        cut_spot(doc, page)
        output_intent(doc)
        doc.save(path, garbage=3, deflate=True)


def build_stickers():
    """Every sticker variant the four sets use, traced once."""
    register('window-mark', window_sticker())
    register('window-mark-closed', window_sticker(open_ring=False))
    register('window-mark-kraftleaf', window_sticker(leaf_ink=KRAFT))
    register('bag-design-1', bag_sticker('moth'))
    register('bag-design-2', bag_sticker('pourover'))
    register('bag-design-3', bag_sticker('ridgeline'))
    register('bag-design-3-halftone', bag_sticker('ridgeline', halftone=True))
    good_price, two_lines = ['$3 SINGLE / $9 FOUR-PACK'], ['$3 SINGLE', '$9 FOUR-PACK']
    register('companion-1', companion(1, good_price))
    register('companion-2', companion(2, two_lines))
    register('companion-1-bad', companion(1, ['$14 SINGLE']))
    register('companion-1-amp', companion(1, good_price, amp=1.0))
    register('companion-2-cutline', companion(2, two_lines, cut_line=True))
    register('companion-1-flat', companion(1, good_price, flat=True))
    register('companion-1-small', companion(1, good_price, word_pt=13))
    register('companion-2-brick', companion(2, two_lines, copy_ink=BRICK))
    register('companion-2-ink', companion(2, two_lines, copy_ink=INK))
    # Ink Black over 5%: the moth given a heavy black drop shadow
    st = STICKERS['bag-design-1']
    register('bag-design-1-ink', variant(st, st.back_d + f'<path d="{st.ink_d}" fill="{INK}" fill-rule="evenodd" '
                                         f'transform="translate(1.1 1.1)"/><path d="{st.ink_d}" fill="{ROAST}" '
                                         f'fill-rule="evenodd"/>'))
    # round 3: a soft shadow through a blur filter; an Ink Black hard shadow; the Multiply blend mode
    register('bag-design-1-soft', variant(
        st, st.back_d + f'<path d="{st.ink_d}" fill="{ROAST}" fill-opacity="0.4" fill-rule="evenodd" '
        f'filter="url(#soft)" transform="translate(0.5 0.5)"/><path d="{st.ink_d}" fill="{ROAST}" fill-rule="evenodd"/>',
        '<defs><filter id="soft" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="0.5"/>'
        '</filter></defs>'))
    st = STICKERS['bag-design-2']
    register('bag-design-2-inkshadow', variant(
        st, st.back_d + f'<path d="{st.ink_d}" fill="{INK}" fill-rule="evenodd" transform="translate(0.2 0.2)"/>'
        f'<path d="{st.ink_d}" fill="{ASH}" fill-rule="evenodd"/>'))
    st = STICKERS['bag-design-3']
    register('bag-design-3-multiply', variant(
        st, st.back_d + f'<path d="{st.ink_d}" fill="{BRICK}" fill-rule="evenodd" style="mix-blend-mode:multiply"/>'))


CUT_LAYER = {'window-mark', 'bag-design-2', 'companion-1'}       # stickers that keep a hidden CutContour layer
NAMES = ('window-mark', 'bag-design-1', 'bag-design-2', 'bag-design-3', 'companion-1', 'companion-2')


def prefix(name: str) -> str:
    return 'new-sticker' if name.startswith('companion') else 'recovered-sticker'


def vector04(out: Path, bad: bool):
    d = out / 'VECTOR-04' / 'deliverables'
    d.mkdir(parents=True, exist_ok=True)
    keys = {name: name for name in NAMES}
    if bad:
        keys.update({'bag-design-1': 'bag-design-1-ink', 'companion-1': 'companion-1-bad'})
    files, outlined = {}, {}
    for name, key in keys.items():
        st = STICKERS[key]
        style, extra = '', ''
        if bad and name == 'window-mark':   # off-palette red set through a CSS class
            style = '.accent{fill:#FF0000}'
            extra = f'<circle class="accent" cx="{num(st.w / 2)}" cy="{num(st.h * 0.8)}" r="3"/>'
        files[name] = artwork(key, cut=name in CUT_LAYER, style=style, extra=extra)
        outlined[name] = artwork(key, outlined=True, style=style, extra=extra)
        (d / f'{prefix(name)}-{name}.svg').write_text(files[name])
        (d / f'sticker-cut-{name}.svg').write_text(cut_file(key))
        (d / f'sticker-proof-{name}.png').write_bytes(proof(outlined[name]))
    gang_sheet(d / 'gang-sheet.pdf', [(name, key, outlined[name]) for name, key in keys.items()],
               f'COMPANION STICKERS: {"$12" if bad else "$3"} SINGLE, $9 FOUR-PACK')


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


def vector04_bad3(out: Path, good: Path):
    """The good files with one round-3 defect in each file DEFECTS3 names (proofs and the sheet keep the good art
    unless their own defect changes them)."""
    shutil.copytree(good / 'VECTOR-04', out / 'VECTOR-04')
    d = out / 'VECTOR-04' / 'deliverables'
    for name, key in (('window-mark', 'window-mark-closed'), ('bag-design-1', 'bag-design-1-soft'),
                      ('bag-design-2', 'bag-design-2-inkshadow'), ('bag-design-3', 'bag-design-3-multiply'),
                      ('companion-1', 'companion-1-flat'), ('companion-2', 'companion-2-brick')):
        (d / f'{prefix(name)}-{name}.svg').write_text(artwork(key, cut=name in CUT_LAYER))
    for name, kw in (('window-mark', {'offset': 1.5}), ('bag-design-1', {'round_mm': 0}), ('bag-design-2', {'island': True}),
                     ('bag-design-3', {'layer': 'Layer 1'}), ('companion-1', {'art': True}),
                     ('companion-2', {'view_box': False})):
        (d / f'sticker-cut-{name}.svg').write_text(cut_file(name, **kw))
    ring = f'<path d="{cut_contour("bag-design-3")[1]}" fill="none" stroke="#EC008C" stroke-width="0.3"/>'
    st = STICKERS['bag-design-3']
    ringed = (f'<svg {NS} width="{num(st.w + 6)}mm" height="{num(st.h + 6)}mm" viewBox="-3 -3 {num(st.w + 6)} '
              f'{num(st.h + 6)}">{st.outlined}{ring}</svg>')
    for name, png in (('window-mark', proof(artwork('window-mark-kraftleaf', outlined=True))),
                      ('bag-design-1', proof(artwork('bag-design-1', outlined=True), white=True)),
                      ('bag-design-2', proof(artwork('bag-design-2', outlined=True), shadow=True)),
                      ('bag-design-3', proof(ringed)),
                      ('companion-1', proof(artwork('companion-1-small', outlined=True))),
                      ('companion-2', proof(artwork('companion-2-ink', outlined=True)))):
        (d / f'sticker-proof-{name}.png').write_bytes(png)
    gang_sheet(d / 'gang-sheet.pdf', [(name, name, artwork(name, outlined=True)) for name in NAMES],
               'COMPANION STICKERS: $3 SINGLE, $9 FOUR-PACK', rgb_key='bag-design-1')

# ---------------------------------------------------------------- MOTION-11


JET, ORANGE, WHITE, ACID, PURPLE = (16, 16, 20), (255, 90, 31), (255, 255, 255), (182, 255, 46), (122, 47, 242)
CAPTURES = M11 / 'staticfox_captures'
FRAME_AT = {1: 2.5, 2: 0.6, 3: 1.2, 4: 2.5, 5: 4.5, 6: 1.0}      # seconds: the moment each upload's joke lands
FPS = 24
SETUP_PX, PAYOFF_PX, LONG_PX = 190, 150, 96   # type scale steps 01 and 02; the whole stack drops to 96 px on long copy
CAP_ANTON = 1760 / 2048
TAGLINE, UPLOAD, SUBSCRIBE, HANDLE = 'Co op disasters and bad decisions.', 'NEW ONE EVERY OTHER DAY', \
    'SUBSCRIBE OR DAVE WINS', '@STATICFOX'
MEMBERS = 'Members get the Sunday chaos stream and the bloopers nobody should see. Link in the description.'
# the wide teaser's shots (capture, first frame, frames) and the upright cutdown's, the same moments cut shorter
SHOTS = [(1, 43, 34), (2, 5, 34), (3, 14, 33), (5, 82, 34), (6, 10, 33)]
UPRIGHT = [(1, 48, 24), (3, 19, 24), (5, 87, 24)]
WEBCAM_04 = (1500, 634, 1852, 986)      # capture 04's webcam window (frame pixels)


@lru_cache(maxsize=None)
def inter(px: int) -> ImageFont.FreeTypeFont:
    """Inter SemiBold 600 (type scale steps 03 and 04), a static instance of the supplied variable font."""
    path = Path(tempfile.gettempdir()) / 'staticfox-Inter-SemiBold.ttf'
    if not path.is_file():
        f = instantiateVariableFont(TTFont(INTER), {'wght': 600, 'opsz': 32})
        f.save(path)
    return ImageFont.truetype(str(path), px)


def say(img: Image.Image, x, base, text, px, colour, anchor='ls'):
    """A line of Inter SemiBold; x may be 'c' to centre it on the image."""
    dr = ImageDraw.Draw(img)
    f = inter(px)
    if x == 'c':
        x, anchor = img.width / 2, 'ms'
    dr.text((x, base), text, font=f, fill=colour, anchor=anchor)


def wrap(text, px, width):
    dr = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    rows, line = [], ''
    for word in text.split():
        trial = (line + ' ' + word).strip()
        if (dr.textlength(trial, font=inter(px)) > width or len(trial) > 65) and line:
            rows.append(line)
            line = word
        else:
            line = trial
    return rows + [line]


def type_line(img: Image.Image, x, base, text, font_path, px, fill, track, outline_px) -> float:
    """A line of title type set letter by letter with tracking (em): first every letter's hard Jet Black outline,
    then the fills over them, so neighbouring letters share one outline. Returns the line's width."""
    f = ImageFont.truetype(str(font_path), px)
    dr = ImageDraw.Draw(img)
    xs, cx = [], x
    for ch in text:
        xs.append(cx)
        cx += f.getlength(ch) + track * px
    if outline_px:
        for ch, xx in zip(text, xs):
            dr.text((xx, base), ch, font=f, fill=JET, anchor='ls', stroke_width=outline_px, stroke_fill=JET)
    for ch, xx in zip(text, xs):
        dr.text((xx, base), ch, font=f, fill=fill, anchor='ls')
    return cx - track * px - x


def line_width(text, font_path, px, track) -> float:
    f = ImageFont.truetype(str(font_path), px)
    return sum(f.getlength(ch) + track * px for ch in text) - track * px


def stack(title: str, px: int = 0, payoff_font=PAYOFF_FONT):
    """The title as the brand's stack: (setup rows, payoff word, setup px, payoff px). The setup words in Anton,
    wrapped to 1500 px, at 190 px (96 px on long copy); the payoff word alone in Archivo Black at 150/190 of that."""
    setup_px = px or (LONG_PX if len(title) >= 30 else SETUP_PX)
    words = title.split()
    rows, line = [], ''
    for w in words[:-1]:
        trial = (line + ' ' + w).strip()
        if line and line_width(trial, TITLE_FONT, setup_px, -0.01) > 1500:
            rows.append(line)
            line = w
        else:
            line = trial
    rows.append(line)
    return rows, words[-1], setup_px, round(setup_px * PAYOFF_PX / SETUP_PX) if payoff_font == PAYOFF_FONT else setup_px


def draw_stack(img, title, x, top, right=None, px=0, payoff_font=PAYOFF_FONT, outlined=True, payoff_outline=True,
               fills=(WHITE, ACID)) -> float:
    """Set the stack with its first cap line at top; right: rows end there (set against an edge) instead of starting
    at x. Leading 200/190 for setup rows, 165/190 for the payoff row. Returns the payoff row's baseline."""
    rows, payoff, setup_px, payoff_px = stack(title, px, payoff_font)
    o = max(5, round(setup_px / 30)) if outlined else 0   # 6 px at 190 px, 5 px at 96 px: hard, and still read by OCR
    base = top + CAP_ANTON * setup_px
    for i, r in enumerate(rows + [payoff]):
        last = i == len(rows)
        fpath, size, track = (payoff_font, payoff_px, -0.015) if last else (TITLE_FONT, setup_px, -0.01)
        if last:
            base += setup_px * (165 if payoff_font == PAYOFF_FONT else 200) / 190 - setup_px * 200 / 190
        rx = x if right is None else right - line_width(r, fpath, size, track) + 0.55 * line_width(r[-1], fpath, size, 0)
        type_line(img, rx, base, r, fpath, size, fills[1] if last else fills[0], track,
                  (o if payoff_outline else 0) if last else o)
        if not last:
            base += setup_px * 200 / 190
    return base


@lru_cache(maxsize=None)
def scrap_cutout() -> Image.Image:
    """The supplied Scrap cutout made solid inside (the file holds his fur and headset at 99% opacity), its
    anti-aliased edge kept and the faint specks it holds at 1% or less dropped."""
    a = np.asarray(Image.open(REFRESH / 'upload/MOTION-11/staticfox_scrap_transparent.png').convert('RGBA')).copy()
    al = a[..., 3]
    al[al <= 3] = 0
    al[al >= 240] = 255
    return Image.fromarray(a)


@lru_cache(maxsize=None)
def scrap(px: int, stretch: float = 1.0) -> Image.Image:
    """Scrap px tall, resampled with premultiplied alpha so no dark fringe forms; stretch widens him (a defect)."""
    return scrap_cutout().convert('RGBa').resize((round(px * stretch), px), Image.LANCZOS).convert('RGBA')


def stand(img: Image.Image, x: int, px: int):
    """Scrap px tall with his left edge at x, his flat-cut base on the image's bottom edge."""
    s = scrap(px)
    img.paste(s, (x, img.height - round(px * 1237 / 1254)), s)


@lru_cache(maxsize=None)
def capture_frame(n: int, size=(1920, 1080)) -> Image.Image:
    """One frame of staticfox_capture_0n.mp4 at its native pixels, centre-cropped (1920 x 1088 to 1920 x 1080)."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-ss', str(FRAME_AT[n]), '-i',
                        str(CAPTURES / f'staticfox_capture_{n:02d}.mp4'), '-frames:v', '1', str(Path(tmp) / 'f.png')],
                       check=True)
        img = Image.open(Path(tmp) / 'f.png').convert('RGB')
    x, y = (img.width - size[0]) // 2, (img.height - size[1]) // 2
    return img.crop((x, y, x + size[0], y + size[1]))


def thumbnail(title: str, capture: int, defect: str | None = None, size=(1920, 1080)) -> Image.Image:
    """The capture frame as recorded, the title stack on a Static Purple panel (from the top left edge to a margin
    past its longest row; top right on capture 04, where the monster lunges in at the left) with a Fox Orange rule
    under it, and Scrap standing on the bottom edge below the panel (on the left for capture 04, whose webcam window
    sits bottom right). Defects: round 1 cut, spelling, caption; round 2 clipped; round 3 no_outline, scrim,
    acid_band, webcam_cut, small_stack, anton_payoff."""
    img = capture_frame(capture, size).copy()
    W, H = size
    if defect == 'enlarged':   # round 4: the middle quarter of the capture frame blown up 2x, nearest neighbour (blocky)
        img = img.crop((W // 4, H // 4, W // 4 + W // 2, H // 4 + H // 2)).resize(size, Image.NEAREST)
    if defect == 'enlarged_soft':   # round 4: the capture frame blown up 1.5x, bilinear
        w2, h2 = round(W / 1.5), round(H / 1.5)
        img = img.crop(((W - w2) // 2, (H - h2) // 2, (W - w2) // 2 + w2, (H - h2) // 2 + h2)).resize(size, Image.BILINEAR)
    shown = 'WE BROKE THE MAPS' if defect == 'spelling' else title
    payoff_font = TITLE_FONT if defect == 'anton_payoff' else PAYOFF_FONT
    rows, payoff, setup_px, payoff_px = stack(shown, 64 if defect == 'small_stack' else 0, payoff_font)
    top = round(0.3 * setup_px)
    band = round(top + CAP_ANTON * setup_px + (len(rows) - 1) * setup_px * 200 / 190
                 + setup_px * (165 if defect != 'anton_payoff' else 200) / 190 + 0.36 * setup_px)
    margin = round(W / 20)
    x, right = margin, None
    if defect == 'cut':        # round 1: the title pushed off the right edge
        x = round(W * 0.594)
    if defect == 'clipped':    # round 2: set against the right edge, the last letters half outside the frame
        right = W
    widest = max([line_width(r, TITLE_FONT, setup_px, -0.01) for r in rows]
                 + [line_width(payoff, payoff_font, payoff_px, -0.015)])
    if right or defect == 'cut':
        x0, x1 = 0, W
    elif capture == 4:         # the monster lunges in at the left of capture 04: the title takes the top right
        x0, x1 = W - round(widest + 3 * margin), W
        x = x0 + margin
    else:                      # two margins past the title: OCR reads its rows apart from the capture beside them
        x0, x1 = 0, min(W, round(x + widest + 2 * margin))
    if defect == 'scrim':   # round 3: a 45% Jet Black wash over the capture below the panel
        a = np.asarray(img, np.float32)
        a[band:] = a[band:] * 0.55 + np.array(JET, np.float32) * 0.45
        img = Image.fromarray(a.round().astype(np.uint8))
    dr = ImageDraw.Draw(img)
    dr.rectangle((x0, 0, x1, band), fill=ACID if defect == 'acid_band' else PURPLE)
    dr.rectangle((x0, band, x1, band + 15), fill=ORANGE)
    draw_stack(img, shown, x, top, right, setup_px if defect == 'small_stack' else 0, payoff_font,
               payoff_outline=defect != 'no_outline')
    if defect == 'caption':    # round 1: a caption larger than the title
        f = ImageFont.truetype(str(TITLE_FONT), 230)
        for i, row in enumerate(('NEW ONE EVERY', 'OTHER DAY')):
            yb = band + 270 + i * 240
            dr.rectangle((margin - 20, yb - 220, margin + dr.textlength(row, font=f) + 20, yb + 20), fill=JET)
            dr.text((margin, yb), row, font=f, fill=ACID, anchor='ls')
    sx = {'webcam_cut': 1120}.get(defect, 60 if capture == 4 else W - 60 - 600)
    stand(img, sx, 600)
    return img


def video(path: Path, frames, size, audio: Path | None = None, crf: int = 14):
    """Frames (RGB images or arrays) piped to ffmpeg: H.264 yuv420p at FPS, with an AAC music track when given."""
    cmd = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{size[0]}x{size[1]}',
           '-r', str(FPS), '-i', '-']
    if audio:
        cmd += ['-i', str(audio), '-c:a', 'aac', '-b:a', '320k']
    cmd += ['-c:v', 'libx264', '-preset', 'fast', '-crf', str(crf), '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
            str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(np.asarray(f, np.uint8)).tobytes())
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f'ffmpeg failed on {path}')


def capture_clip(n: int, first: int, count: int) -> np.ndarray:
    """count frames of staticfox_capture_0n.mp4 from frame first, at native size."""
    path = str(CAPTURES / f'staticfox_capture_{n:02d}.mp4')
    w, h = (int(v) for v in subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                             'stream=width,height', '-of', 'csv=p=0', path],
                                            capture_output=True, text=True, check=True).stdout.split(','))
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-vf', f'select=between(n\\,{first}\\,{first + count - 1})',
                          '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)[:count]


def music(path: Path, seconds: float, synth: bool = False) -> Path:
    """The first seconds of staticfox_bed.wav as a WAV file; synth=True writes a synthesised loop instead (a defect)."""
    with wave.open(str(M11 / 'staticfox_bed.wav')) as w:
        params = w.getparams()
        data = w.readframes(round(seconds * params.framerate))
    if synth:
        t = np.arange(round(seconds * params.framerate)) / params.framerate
        beat = (t * 2) % 1
        sig = 0.5 * np.sin(2 * np.pi * 55 * t) * np.exp(-6 * beat) + 0.2 * np.sin(2 * np.pi * 220 * t) * (beat < 0.5)
        data = np.repeat((sig * 20000).astype('<i2')[:, None], params.nchannels, axis=1).tobytes()
    with wave.open(str(path), 'wb') as w:
        w.setparams(params)
        w.writeframes(data)
    return path


def card(size, ground=JET) -> Image.Image:
    return Image.new('RGB', size, ground)


def tagline_card(size) -> Image.Image:
    """The opening card: the tagline in Inter SemiBold, White on Jet Black, under a Fox Orange bar."""
    img = card(size)
    W, H = size
    ImageDraw.Draw(img).rectangle((W / 2 - 200, H / 2 - 110, W / 2 + 200, H / 2 - 96), fill=ORANGE)
    rows = wrap(TAGLINE, 54, W - 160)
    for i, r in enumerate(rows):
        say(img, 'c', H / 2 + i * 62, r, 54, WHITE)
    return img


def teaser_end(size, upload=UPLOAD) -> Image.Image:
    """The closing card, held: the upload line in Acid Signal, SUBSCRIBE OR DAVE WINS in Signal White, a Fox Orange
    bar, @STATICFOX in Fox Orange (Inter SemiBold on Jet Black), and Scrap on the bottom edge."""
    img = card(size)
    W, H = size
    if W > H:
        x, y = 120, 470
        stand(img, W - 80 - 760, 760)
    else:
        x, y = 'c', 520
        stand(img, (W - 700) // 2, 700)
    say(img, x, y, upload, 54, ACID)
    say(img, x, y + 75, SUBSCRIBE, 54, WHITE)
    bx = 120 if W > H else W / 2 - 220
    ImageDraw.Draw(img).rectangle((bx, y + 120, bx + 440, y + 134), fill=ORANGE)
    say(img, x, y + 220, HANDLE, 54, ORANGE)
    return img


def teaser(path: Path, size, shots, upload=UPLOAD, synth=False, zoom=None, wash=None):
    """A teaser at FPS: the tagline card, shots cut from the captures at native size (letterboxed below native size
    on an upright canvas), the held end card; the music bed under it all. Round-4 defects: zoom {capture: factor}
    blows that capture's shot up from its middle (nearest neighbour, blocky); wash {capture: (rgb, opacity)} lays a
    flat colour over that capture's shot."""
    W, H = size
    wide = W > H
    open_n, end_n = (36, 108) if wide else (30, 66)

    def treat(n, f):
        if zoom and n in zoom:
            k = zoom[n]
            h0, w0 = f.shape[:2]
            cw, ch = round(w0 / k), round(h0 / k)
            x0, y0 = (w0 - cw) // 2, (h0 - ch) // 2
            f = cv2.resize(f[y0:y0 + ch, x0:x0 + cw], (w0, h0), interpolation=cv2.INTER_NEAREST)
        if wash and n in wash:
            rgb, op = wash[n]
            f = (f.astype(np.float32) * (1 - op) + np.array(rgb, np.float32) * op).round().astype(np.uint8)
        return f

    def frames():
        yield from [np.asarray(tagline_card(size))] * open_n
        for n, first, count in shots:
            for f in (treat(n, g) for g in capture_clip(n, first, count)):
                if wide:
                    y = (f.shape[0] - H) // 2
                    yield f[y:y + H, :W]
                else:
                    h = round(f.shape[0] * W / f.shape[1])
                    canvas = np.zeros((H, W, 3), np.uint8)
                    canvas[:] = JET
                    canvas[(H - h) // 2:(H - h) // 2 + h] = cv2.resize(f, (W, h), interpolation=cv2.INTER_AREA)
                    yield canvas
        yield from [np.asarray(teaser_end(size, upload))] * end_n
    total = open_n + sum(c for _, _, c in shots) + end_n
    with tempfile.TemporaryDirectory() as tmp:
        video(path, frames(), size, music(Path(tmp) / 'bed.wav', total / FPS, synth))


def ease(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return 1 - (1 - u) ** 3


def ease_back(u: float, k: float = 1.4) -> float:
    """Ease out with a small overshoot (the title pops past full size, then settles)."""
    u = min(1.0, max(0.0, u)) - 1
    return 1 + (k + 1) * u ** 3 + k * u ** 2


def animation(path: Path, name: str, defect: str | None = None, size=(1920, 1080)):
    """The channel title (24 fps, 7 s, silent): Scrap slides in from the right and bobs; the STATIC FOX stack (White
    and Acid Signal, Jet Black outlines, Anton 190 px over Archivo Black 150 px) scales up from 30% with a small
    overshoot from 0.5 s to 2.5 s; a Fox Orange bar wipes in under it; the end card copy (Inter SemiBold) rises in
    line by line; from 4 s everything holds still on the Static Purple end card. Defects: subscribe (round 2: SUBSCRIBE
    OR DAVE WINS set larger than the name), no_outline (round 3)."""
    W, H = size
    small = defect == 'subscribe'
    title = Image.new('RGBA', size, (0, 0, 0, 0))
    top = 30 if small else 87
    base = draw_stack(title, name, 110, top, px=64 if small else 0, outlined=defect != 'no_outline',
                      fills=(WHITE, ACID))
    anchor = (110, base)
    tbox = title.getbbox()
    lines = []                                     # (text, colour, baseline, px, font)
    y = base + 145
    if small:
        lines.append((SUBSCRIBE, WHITE, base + 190, 150, 'anton'))
        y = base + 290
    lines += [(UPLOAD, ACID, y, 54, 'inter')]
    if not small:
        lines.append((SUBSCRIBE, WHITE, y + 70, 54, 'inter'))
    y += 70 if small else 175
    for i, r in enumerate(wrap(MEMBERS, 54, 950)):
        lines.append((r, WHITE, y + i * 62, 54, 'inter'))
    lines.append((HANDLE, ACID, y + 62 * len(wrap(MEMBERS, 54, 950)) + 80, 54, 'inter'))
    bar = (110, base + 45, 560, base + 59)
    scrap_px, scrap_x = 760, W - 60 - 760
    pieces = []                                    # each copy line drawn once: (crop, left, top)
    for text, colour, yb, px, face in lines:
        layer = Image.new('RGBA', size, (0, 0, 0, 0))
        if face == 'anton':
            type_line(layer, 110, yb, text, TITLE_FONT, px, colour, -0.01, max(5, round(px / 30)))
        else:
            say(layer, 110, yb, text, px, colour)
        box = layer.getbbox()
        pieces.append((layer.crop(box), box[0], box[1]))

    def at(f):
        t = f / FPS
        img = Image.new('RGB', size, PURPLE)
        dr = ImageDraw.Draw(img)
        if t >= 2.5:
            dr.rectangle((bar[0], bar[1], bar[0] + (bar[2] - bar[0]) * ease((t - 2.5) / 0.5), bar[3]), fill=ORANGE)
        for i, (crop, left, top_) in enumerate(pieces):
            u = (t - 2.75 - 0.2 * i) / 0.25
            if u >= 0:                             # each line rises 40 px into place over a quarter second
                img.paste(crop, (left, top_ + round(40 * (1 - ease(u)))), crop)
        if t >= 0.5:
            s = 0.3 + 0.7 * ease_back((t - 0.5) / 2.0)
            crop = title.crop(tbox)
            if abs(s - 1) > 1e-3:
                crop = crop.convert('RGBa').resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))),
                                                   Image.LANCZOS).convert('RGBA')
            px_, py_ = round(anchor[0] + (tbox[0] - anchor[0]) * s), round(anchor[1] + (tbox[1] - anchor[1]) * s)
            img.paste(crop, (px_, py_), crop)
        dx = round(900 * (1 - ease(t / 1.0)))
        dy = round(12 * math.sin(2 * math.pi * (t - 1.0) / 1.5)) if 1.0 <= t < 4.0 else 0
        if defect == 'scrap_still':                # round 4: Scrap stands in place from the first frame, never moving
            dx = dy = 0
        sc = scrap(scrap_px)
        img.paste(sc, (scrap_x + dx, H - round(scrap_px * 1237 / 1254) + dy), sc)
        return np.asarray(img)
    held = at(4 * FPS)                             # from 4 s nothing moves: the end card, held for 3 s
    # a lower crf keeps the small end card copy (and its full stops) crisp for OCR; flat graphics stay small
    video(path, (at(f) if f < 4 * FPS else held for f in range(7 * FPS)), size, crf=8)


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
    upload = 'NEW ONE EVERY DAY' if bad else UPLOAD
    teaser(d / 'deliverables' / 'channel-teaser.mp4', (1920, 1080), SHOTS, upload)
    teaser(d / 'deliverables' / 'channel-teaser-vertical.mp4', (1080, 1920), UPRIGHT, upload)
    animation(d / 'deliverables' / 'channel-animation.mp4', 'STATIC FAX' if bad else 'STATIC FOX')


def motion11_bad2(out: Path, good: Path):
    """The good files with one round-2 defect in each file DEFECTS2 names."""
    shutil.copytree(good / 'MOTION-11', out / 'MOTION-11')
    d = out / 'MOTION-11' / 'deliverables'
    thumbnail('DO NOT OPEN THAT DOOR', 4, 'clipped').save(d / 'thumbnail-do-not-open-that-door.png')
    thumbnail('KITCHEN. GONE.', 6).save(d / 'thumbnail-kitchen-gone.png')
    thumbnail('I GAVE MY TEAM ONE SIMPLE JOB AND THEY SET THE ENTIRE BASE ON FIRE', 3).save(
        d / 'thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi.png')
    animation(d / 'channel-animation.mp4', 'STATIC FOX', 'subscribe')


def motion11_bad3(out: Path, good: Path):
    """The good files with one round-3 defect in each file DEFECTS3 names."""
    shutil.copytree(good / 'MOTION-11', out / 'MOTION-11')
    d = out / 'MOTION-11' / 'deliverables'
    for file, title, capture, defect in (
            ('thumbnail-we-broke-the-map', 'WE BROKE THE MAP', 1, 'no_outline'),
            ('thumbnail-everyone-off-the-platform', 'EVERYONE OFF THE PLATFORM', 2, 'scrim'),
            ('thumbnail-kitchen-gone', 'KITCHEN. GONE.', 3, 'acid_band'),
            ('thumbnail-do-not-open-that-door', 'DO NOT OPEN THAT DOOR', 4, 'webcam_cut'),
            ('thumbnail-we-spent-six-hours-building-a-bridge-and-then-drove-straight-pas',
             'WE SPENT SIX HOURS BUILDING A BRIDGE AND THEN DROVE STRAIGHT PAST IT', 5, 'small_stack'),
            ('thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi',
             'I GAVE MY TEAM ONE SIMPLE JOB AND THEY SET THE ENTIRE BASE ON FIRE', 6, 'anton_payoff')):
        thumbnail(title, capture, defect).save(d / f'{file}.png')
    teaser(d / 'channel-teaser.mp4', (1920, 1080), SHOTS[:4] + [SHOTS[1]])          # capture 02's shot looped
    teaser(d / 'channel-teaser-vertical.mp4', (1080, 1920), UPRIGHT, synth=True)
    animation(d / 'channel-animation.mp4', 'STATIC FOX', 'no_outline')


# round-4 defects planted in the bad4 set (MOTION-11, video helper): file -> (every rule it breaks, what is wrong)
DEFECTS4_VIDEO = {
    'MOTION-11/channel-animation': (['R017'], 'Scrap stands still in one place for the whole film: no slide in, no bob'),
    'MOTION-11/channel-teaser': (
        ['R054'], "capture 03's shot is the middle half of the capture blown up 2x with nearest neighbour (blocky)"),
    'MOTION-11/channel-teaser-vertical': (
        ['R079', 'R052'], "a 40% Static Purple wash lies over capture 05's shot"),
    'MOTION-11/thumbnail-we-broke-the-map': (
        ['R053'], 'the capture frame is the middle quarter of the frame blown up 2x with nearest neighbour (blocky)'),
    'MOTION-11/thumbnail-kitchen-gone': (
        ['R053'], 'the capture frame is blown up 1.5x (bilinear) from its middle'),
}


def motion11_bad4(out: Path, good: Path):
    """The good MOTION-11 files with one round-4 defect in each file DEFECTS4_VIDEO names (others stay as good)."""
    d = out / 'MOTION-11' / 'deliverables'
    if not d.is_dir():
        shutil.copytree(good / 'MOTION-11', out / 'MOTION-11')
    animation(d / 'channel-animation.mp4', 'STATIC FOX', 'scrap_still')
    teaser(d / 'channel-teaser.mp4', (1920, 1080), SHOTS, zoom={3: 2.0})
    teaser(d / 'channel-teaser-vertical.mp4', (1080, 1920), UPRIGHT, wash={5: (PURPLE, 0.4)})
    thumbnail('WE BROKE THE MAP', 1, 'enlarged').save(d / 'thumbnail-we-broke-the-map.png')
    thumbnail('KITCHEN. GONE.', 3, 'enlarged_soft').save(d / 'thumbnail-kitchen-gone.png')
    (out.parent / 'defects4_video.json').write_text(json.dumps(
        {k: {'rules': rules, 'defect': why} for k, (rules, why) in DEFECTS4_VIDEO.items()}, indent=1) + '\n')


def main():
    if sys.argv[1] == '--bad4':   # python make_vector_motion_files.py --bad4 <out dir>: MOTION-11 bad4 files only
        out = Path(sys.argv[2])
        motion11_bad4(out / 'bad4', out / 'good')
        print('made', out / 'bad4' / 'MOTION-11')
        return
    out = Path(sys.argv[1])
    for kind in ('good', 'bad', 'bad2', 'bad3'):
        for tid in ('VECTOR-04', 'MOTION-11'):
            shutil.rmtree(out / kind / tid, ignore_errors=True)
    build_stickers()
    for kind in ('good', 'bad'):
        vector04(out / kind, kind == 'bad')
        motion11(out / kind, kind == 'bad')
    vector04_bad2(out / 'bad2', out / 'good')
    motion11_bad2(out / 'bad2', out / 'good')
    vector04_bad3(out / 'bad3', out / 'good')
    motion11_bad3(out / 'bad3', out / 'good')
    (out / 'defects2_vector_motion.json').write_text(json.dumps(
        {k: {'rules': rules, 'defect': why} for k, (rules, why) in DEFECTS2.items()}, indent=1) + '\n')
    # defects3.json is shared with make_layout12_files.py: replace this generator's keys, keep the others
    path3 = out / 'defects3.json'
    defects3 = {k: v for k, v in (json.loads(path3.read_text()) if path3.is_file() else {}).items()
                if not k.startswith(('VECTOR-04/', 'MOTION-11/'))}
    defects3.update({k: {'rules': rules, 'defect': why} for k, (rules, why) in DEFECTS3.items()})
    path3.write_text(json.dumps(dict(sorted(defects3.items())), indent=1, ensure_ascii=False) + '\n')
    print('made', out)


if __name__ == '__main__':
    main()
