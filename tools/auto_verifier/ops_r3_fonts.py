"""Round 3, typefaces on images (2026-10-28): which font, weight and slant a line of type on a raster image is set in,
whether it is stretched, and how open its letter spacing is.

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person"; nothing
passes on a failed read, and a person answer carries a 'reason'. Loaded by objective_ops_r3 (OPS below).

Method, the same on every file (deterministic; no trained model):
- Lines are read by OCR (objective_ops). A line's ink coverage is measured against its ground (commonest colour round
  the line); letters of neighbouring lines, rules and specks are dropped. Lines on a textured ground, or read below
  80% OCR confidence, are not judged (a person answers).
- The line's own text is rendered in every candidate font: each brand family at every 100 of weight (and its optical
  sizes), brand italics, and the open stand-ins installed on the checking machine (Liberation Sans, Serif and Mono,
  the metric clones of Arial or Helvetica, Times and Courier; DejaVu; Noto Sans and Serif). Each rendering is scaled to the line's measured letter height, laid out word by
  word with the letter spacing that fits each word's width, each letter nudged to its best local position, and
  compared with the image (normalised difference of ink coverage: 0 identical, 1 nothing in common).
- A font is read only when it is clearly the best: within the fit a true match reaches at that letter height, and
  better than every other family by a calibrated margin. A different font is reported only when it is clearly better
  than the expected one by the same kind of margin; anything closer goes to a person. Weight is read within the family
  from the fits of neighbouring weights and from the ink mass (stroke thickness), each with its own margin.
- Margins were set on synthetic lines of known font, weight, size (10 to 120 px letters), colour, ground noise, JPEG
  quality and letter spacing, drawn by three renderers (FreeType, MuPDF, Chrome), so that no synthetic line was read
  wrongly; fonts outside the candidate list never passed as a brand font.
"""
from __future__ import annotations

OPS: dict = {}          # filled at the end; defined first so a circular import finds it

import functools
import re
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np
from PIL import Image, ImageFont

import objective_ops as base
import objective_ops_r3 as r3
from objective_ops import PERSON, OCR_GOOD_CONF, canon, contains

ADOBE = Path(__file__).resolve().parents[4]
FONT_DIR = ADOBE / 'reviews/pilot13-refresh-2026-10-14/fonts'
REF = 128.0                       # px per em of the reference glyph renders
WEIGHT_NAMES = {'thin': 100, 'extralight': 200, 'light': 300, 'regular': 400, 'book': 400, 'medium': 500,
                'semibold': 600, 'bold': 700, 'extrabold': 800, 'black': 900}
WNAME = {100: 'Thin', 200: 'ExtraLight', 300: 'Light', 400: 'Regular', 500: 'Medium', 600: 'SemiBold', 700: 'Bold',
         800: 'ExtraBold', 900: 'Black'}


class Face(NamedTuple):
    family: str
    weight: int
    italic: bool
    path: str
    index: int
    axes: tuple            # (('wght', 400.0), ('opsz', 14.0)) for variable fonts
    note: str = ''

    @property
    def label(self):
        return (f'{self.family} {WNAME.get(self.weight, self.weight)}{" Italic" if self.italic else ""}'
                f'{(" (" + self.note + ")") if self.note else ""}')


# ---------------------------------------------------------------- candidate fonts

BRAND = {   # family: (file, italic file, weight range, optical sizes tried, fixed axes)
    'Inter': ('inter/Inter[opsz,wght].ttf', 'inter/Inter-Italic[opsz,wght].ttf', (100, 900), (14, 22, 32), {}),
    'Source Sans 3': ('sourcesans3/SourceSans3[wght].ttf', 'sourcesans3/SourceSans3-Italic[wght].ttf', (200, 900), (), {}),
    'Source Serif 4': ('sourceserif4/SourceSerif4[opsz,wght].ttf', 'sourceserif4/SourceSerif4-Italic[opsz,wght].ttf', (200, 900), (8, 20, 40, 60), {}),
    'Cormorant Garamond': ('cormorantgaramond/CormorantGaramond[wght].ttf', 'cormorantgaramond/CormorantGaramond-Italic[wght].ttf', (300, 700), (), {}),
    'Libre Franklin': ('librefranklin/LibreFranklin[wght].ttf', 'librefranklin/LibreFranklin-Italic[wght].ttf', (100, 900), (), {}),
    'Piazzolla': ('piazzolla/Piazzolla[opsz,wght].ttf', 'piazzolla/Piazzolla-Italic[opsz,wght].ttf', (100, 900), (8, 18, 30), {}),
    'Archivo': ('archivo/Archivo[wdth,wght].ttf', 'archivo/Archivo-Italic[wdth,wght].ttf', (100, 900), (), {'wdth': 100.0}),
    'Archivo Narrow': ('archivonarrow/ArchivoNarrow[wght].ttf', 'archivonarrow/ArchivoNarrow-Italic[wght].ttf', (400, 700), (), {}),
    'Sora': ('sora/Sora[wght].ttf', None, (100, 800), (), {}),
    'Lexend': ('lexend/Lexend[wght].ttf', None, (100, 900), (), {}),
    'IBM Plex Sans': ('ibmplexsans/IBMPlexSans[wdth,wght].ttf', 'ibmplexsans/IBMPlexSans-Italic[wdth,wght].ttf', (100, 700), (), {'wdth': 100.0}),
}
STATIC_BRAND = {
    'Anton': [(400, False, 'anton/Anton-Regular.ttf')],
    'Archivo Black': [(900, False, 'archivoblack/ArchivoBlack-Regular.ttf')],
    'DM Serif Display': [(400, False, 'dmserifdisplay/DMSerifDisplay-Regular.ttf'), (400, True, 'dmserifdisplay/DMSerifDisplay-Italic.ttf')],
    'Instrument Serif': [(400, False, 'instrumentserif/InstrumentSerif-Regular.ttf'), (400, True, 'instrumentserif/InstrumentSerif-Italic.ttf')],
    'IBM Plex Mono': [(w, False, f'ibmplexmono/IBMPlexMono-{n}.ttf') for n, w in (('Light', 300), ('Regular', 400), ('Medium', 500),
                                                                                  ('SemiBold', 600), ('Bold', 700))]
                     + [(400, True, 'ibmplexmono/IBMPlexMono-Italic.ttf')],
    'Barlow Condensed': [(w, False, f'barlowcondensed/BarlowCondensed-{n}.ttf') for n, w in (('Light', 300), ('Regular', 400), ('Medium', 500),
                                                                                             ('SemiBold', 600), ('Bold', 700), ('Black', 900))],
}
OPEN = Path('/usr/share/fonts/truetype')
STAND_INS = [   # open stand-ins installed on the checking machine: metric clones of Arial, Helvetica, Times and Courier,
    # and the DejaVu and Noto families (family, weight, italic, file)
    ('Liberation Sans', 400, False, 'liberation/LiberationSans-Regular.ttf'), ('Liberation Sans', 700, False, 'liberation/LiberationSans-Bold.ttf'),
    ('Liberation Sans', 400, True, 'liberation/LiberationSans-Italic.ttf'), ('Liberation Sans', 700, True, 'liberation/LiberationSans-BoldItalic.ttf'),
    ('Liberation Sans Narrow', 400, False, 'liberation/LiberationSansNarrow-Regular.ttf'),
    ('Liberation Sans Narrow', 700, False, 'liberation/LiberationSansNarrow-Bold.ttf'),
    ('Liberation Sans Narrow', 400, True, 'liberation/LiberationSansNarrow-Italic.ttf'),
    ('Liberation Serif', 400, False, 'liberation/LiberationSerif-Regular.ttf'), ('Liberation Serif', 700, False, 'liberation/LiberationSerif-Bold.ttf'),
    ('Liberation Serif', 400, True, 'liberation/LiberationSerif-Italic.ttf'), ('Liberation Serif', 700, True, 'liberation/LiberationSerif-BoldItalic.ttf'),
    ('Liberation Mono', 400, False, 'liberation/LiberationMono-Regular.ttf'), ('Liberation Mono', 700, False, 'liberation/LiberationMono-Bold.ttf'),
    ('Liberation Mono', 400, True, 'liberation/LiberationMono-Italic.ttf'),
    ('DejaVu Sans', 400, False, 'dejavu/DejaVuSans.ttf'), ('DejaVu Sans', 700, False, 'dejavu/DejaVuSans-Bold.ttf'),
    ('DejaVu Serif', 400, False, 'dejavu/DejaVuSerif.ttf'), ('DejaVu Serif', 700, False, 'dejavu/DejaVuSerif-Bold.ttf'),
    ('DejaVu Sans Mono', 400, False, 'dejavu/DejaVuSansMono.ttf'), ('DejaVu Sans Mono', 700, False, 'dejavu/DejaVuSansMono-Bold.ttf'),
    ('DejaVu Sans Mono', 400, True, 'dejavu/DejaVuSansMono-Oblique.ttf'),
    ('Noto Sans', 400, False, 'noto/NotoSans-Regular.ttf'), ('Noto Sans', 700, False, 'noto/NotoSans-Bold.ttf'),
    ('Noto Sans', 400, True, 'noto/NotoSans-Italic.ttf'), ('Noto Sans', 700, True, 'noto/NotoSans-BoldItalic.ttf'),
    ('Noto Sans Display', 400, False, 'noto/NotoSansDisplay-Regular.ttf'), ('Noto Sans Display', 700, False, 'noto/NotoSansDisplay-Bold.ttf'),
    ('Noto Sans Display', 400, True, 'noto/NotoSansDisplay-Italic.ttf'),
    ('Noto Serif', 400, False, 'noto/NotoSerif-Regular.ttf'), ('Noto Serif', 700, False, 'noto/NotoSerif-Bold.ttf'),
    ('Noto Serif', 400, True, 'noto/NotoSerif-Italic.ttf'), ('Noto Serif', 700, True, 'noto/NotoSerif-BoldItalic.ttf'),
    ('Noto Sans Mono', 400, False, 'noto/NotoSansMono-Regular.ttf'), ('Noto Sans Mono', 700, False, 'noto/NotoSansMono-Bold.ttf'),
    ('Noto Mono', 400, False, 'noto/NotoMono-Regular.ttf'),
]


def brand_faces(family: str, weights=None, italic: bool = False) -> list:
    """Faces of a brand family: every 100 of weight in its range (or the given weights), each optical size tried."""
    out = []
    if family in STATIC_BRAND:
        for w, it, f in STATIC_BRAND[family]:
            if it == italic and (weights is None or w in weights) and (FONT_DIR / f).is_file():
                out.append(Face(family, w, it, str(FONT_DIR / f), 0, ()))
        return out
    f, fi, (lo, hi), sizes, fixed = BRAND[family]
    path = fi if italic else f
    if path is None or not (FONT_DIR / path).is_file():
        return out
    for w in [w for w in range(100, 1000, 100) if lo <= w <= hi and (weights is None or w in weights)]:
        for o in sizes or (None,):
            axes = (('wght', float(w)),) + ((('opsz', float(o)),) if o else ()) + tuple(fixed.items())
            out.append(Face(family, w, italic, str(FONT_DIR / path), 0, axes, f'opsz {o}' if o else ''))
    return out


@functools.lru_cache(maxsize=2)
def system_faces() -> tuple:
    """The open stand-ins that are installed."""
    return tuple(Face(fam, w, it, str(OPEN / f), 0, ()) for fam, w, it, f in STAND_INS if (OPEN / f).is_file())


@functools.lru_cache(maxsize=2)
def all_faces() -> tuple:
    """Every candidate: each brand family at every 100 of weight and its optical sizes, brand italics at 300, 400 and
    700 (all of a static family's italics), and the system stand-ins."""
    fs = []
    for fam in list(BRAND) + list(STATIC_BRAND):
        fs += brand_faces(fam)
        fs += brand_faces(fam, weights=None if fam in STATIC_BRAND else (300, 400, 700), italic=True)
    fs += system_faces()
    return tuple(dict.fromkeys(fs))


def stand_ins_ok() -> bool:
    """The brand fonts and the open stand-ins are installed: without them a wrong font has nothing to lose to, so no
    font check may pass or fail."""
    return len(system_faces()) >= 0.9 * len(STAND_INS) and (FONT_DIR / BRAND['Inter'][0]).is_file()


# ---------------------------------------------------------------- rendering

AXIS_TAGS = {b'Weight': 'wght', b'Optical size': 'opsz', b'Optical Size': 'opsz', b'Width': 'wdth', b'Grade': 'GRAD'}


@functools.lru_cache(maxsize=1024)
def pil_font(face: Face, size: float = REF):
    f = ImageFont.truetype(face.path, size, index=face.index, layout_engine=ImageFont.Layout.BASIC)
    if face.axes:
        want = dict(face.axes)
        vals = []
        for ax in f.get_variation_axes():
            name = ax['name']
            tag = AXIS_TAGS.get(name, name.decode() if isinstance(name, bytes) else name)
            vals.append(min(max(want.get(tag, ax['default']), ax['minimum']), ax['maximum']))
        f.set_variation_by_axes(vals)
    return f


@functools.lru_cache(maxsize=256)
def _cmap(path: str, index: int) -> frozenset:
    from fontTools.ttLib import TTFont
    return frozenset(TTFont(path, fontNumber=index, lazy=True).getBestCmap() or {})


def has_glyphs(face: Face, text: str) -> bool:
    cm = _cmap(face.path, face.index)
    return all(ord(c) in cm for c in text if not c.isspace())


@functools.lru_cache(maxsize=40000)
def glyph(face: Face, ch: str):
    """Reference render (REF px per em): (coverage, left, top relative to the baseline origin, advance, ink box)."""
    f = pil_font(face)
    adv = float(f.getlength(ch))
    if ch.isspace():
        return None, 0, 0, adv, None
    core, (ox, oy) = f.getmask2(ch, mode='L', anchor='ls')
    a = np.asarray(Image.Image()._new(core), np.uint8)
    if a.size == 0 or a.max() <= 127:
        return None, 0, 0, adv, None
    a = np.pad(a, 2)
    l, t = ox - 2, oy - 2
    rows = np.nonzero(a.max(axis=1) > 127)[0]
    cols = np.nonzero(a.max(axis=0) > 127)[0]
    return a, l, t, adv, (l + cols[0], t + rows[0], l + cols[-1] + 1, t + rows[-1] + 1)


@functools.lru_cache(maxsize=6000)
def _blurred(face: Face, ch: str, sq: int):
    a = glyph(face, ch)[0].astype(np.float32) / 255.0
    return cv2.GaussianBlur(a, (0, 0), sq / 4.0) if sq >= 2 else a


@functools.lru_cache(maxsize=30000)
def scaled(face: Face, ch: str, kq: int, blurq: int, px: int = 0, py: int = 0, xs: int = 1000):
    """The glyph at scale k = kq / 4000 (horizontal scale times xs / 1000), extra blur blurq / 100 px, sub-pixel phase
    (px, py) / 4: (image, dx, dy) with (dx, dy) the image's top-left relative to the glyph origin."""
    a, l, t, adv, ink = glyph(face, ch)
    k = kq / 4000.0
    kx = k * xs / 1000.0
    src = _blurred(face, ch, int(round(4 * 0.42 / min(k, kx))))
    blur = blurq / 100.0
    pad = int(np.ceil(2.5 * blur)) + 1
    gx, gy = l * kx + px / 4.0, t * k + py / 4.0
    ix, iy = int(np.floor(gx)), int(np.floor(gy))
    fx, fy = gx - ix, gy - iy
    oh, ow = int(np.ceil(a.shape[0] * k)) + 2 + 2 * pad, int(np.ceil(a.shape[1] * kx)) + 2 + 2 * pad
    M = np.float32([[kx, 0, fx + pad], [0, k, fy + pad]])
    g = cv2.warpAffine(src, M, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=0)
    if blur > 0:
        g = cv2.GaussianBlur(g, (0, 0), blur)
    return g, ix - pad, iy - pad


def _put(canvas, img, x, y):
    H, W = canvas.shape
    h, w = img.shape
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x1 > x0 and y1 > y0:
        np.maximum(canvas[y0:y1, x0:x1], img[y0 - y:y1 - y, x0 - x:x1 - x], out=canvas[y0:y1, x0:x1])


# ---------------------------------------------------------------- one line on the image

def _coverage(rgb: np.ndarray, bbox, pad_x=0.4, pad_y=0.55):
    """Ink coverage round an OCR line box (0 ground, 1 ink): ink = the letter cores (the pixels in the box furthest
    from the ground), ground = the colour of the crop's pixels away from anything ink-like (this line's letters, a
    neighbouring line's, outlines round letters). flat: share of those ground pixels within 12 of the ground colour;
    noise: their spread along the ink axis. None when there is too little contrast."""
    H, W = rgb.shape[:2]
    x0, y0, x1, y1 = (float(v) for v in bbox)
    hb = max(4.0, y1 - y0)
    X0, Y0 = int(max(0, np.floor(x0 - pad_x * hb))), int(max(0, np.floor(y0 - pad_y * hb)))
    X1, Y1 = int(min(W, np.ceil(x1 + pad_x * hb))), int(min(H, np.ceil(y1 + pad_y * hb)))
    crop = rgb[Y0:Y1, X0:X1].astype(np.float32)
    if crop.shape[0] < 6 or crop.shape[1] < 6:
        return None
    ring = np.concatenate([crop[:2].reshape(-1, 3), crop[-2:].reshape(-1, 3), crop[:, :2].reshape(-1, 3), crop[:, -2:].reshape(-1, 3)])
    q = (ring // 6).astype(np.int32)
    _, inv, counts = np.unique(q, axis=0, return_inverse=True, return_counts=True)
    g = ring[inv.ravel() == counts.argmax()].mean(axis=0)
    inner = crop[max(0, int(y0 - Y0)):int(np.ceil(y1 - Y0)), max(0, int(x0 - X0)):int(np.ceil(x1 - X0))].reshape(-1, 3)
    d = np.abs(inner - g).sum(axis=1)
    if not len(d) or d.max() < 60:
        return None
    ink = np.median(inner[d >= 0.85 * d.max()], axis=0)
    for _ in range(2):                    # ground from the pixels away from ink, then the coverage against it
        v = ink - g
        cov = np.clip(((crop - g) @ v) / float(v @ v), 0, 1)
        rad = max(2, int(round(0.08 * hb)))
        near = cv2.dilate((cov > 0.25).astype(np.uint8), np.ones((2 * rad + 1, 2 * rad + 1), np.uint8)) > 0
        gp = crop[~near]
        if len(gp) < 50:
            gp = ring
        g = np.median(gp, axis=0)
    v = ink - g
    if np.abs(v).sum() < 60:
        return None
    cov = np.clip(((crop - g) @ v) / float(v @ v), 0, 1)
    flat = float((np.abs(gp - g).max(axis=1) <= 12).mean())
    noise = float(np.std(((gp - g) @ v) / float(v @ v)))
    return dict(cov=cov.astype(np.float32), origin=(X0, Y0), box=(x0 - X0, y0 - Y0, x1 - X0, y1 - Y0), ground=g, ink=ink,
                flat=flat, contrast=float(np.abs(v).sum()), noise=noise)


def _parts(cov, box):
    """The line's own letters: components centred in the OCR box's band (neighbouring lines, rules, specks dropped)."""
    bx0, by0, bx1, by1 = box
    hb = by1 - by0
    n, lab, st, _ = cv2.connectedComponentsWithStats((cov > 0.5).astype(np.uint8), connectivity=8)
    keep = []
    for i in range(1, n):
        x, y, w, h, area = (int(v) for v in st[i])
        if area < max(2, 0.002 * hb * hb):
            continue
        if not (by0 - 0.15 * hb <= y + h / 2 <= by1 + 0.15 * hb):
            continue
        if x + w < bx0 - 0.1 * hb or x > bx1 + 0.1 * hb:
            continue
        if w > 2.5 * hb and h < 0.2 * hb:
            continue
        keep.append(i)
    if not keep:
        return None
    mask = cv2.dilate(np.isin(lab, keep).astype(np.uint8), np.ones((3, 3), np.uint8))
    boxes = [tuple(int(v) for v in st[i][:4]) for i in keep]
    bottoms = np.array([y + h for x, y, w, h in boxes], float)
    tol = max(1.0, 0.04 * hb)
    votes = [np.sum(np.abs(bottoms - b) <= tol) for b in bottoms]
    base_ = float(np.median(bottoms[np.abs(bottoms - bottoms[int(np.argmax(votes))]) <= tol]))
    return dict(clean=cov * mask, base=base_, top=float(min(b[1] for b in boxes)), left=float(min(b[0] for b in boxes)),
                right=float(max(b[0] + b[2] for b in boxes)), bottom=float(max(b[1] + b[3] for b in boxes)), boxes=boxes)


def _word_spans(clean, nwords):
    """Ink spans of the words: the n-1 widest gaps, when they stand clearly apart from the letter gaps."""
    xs = np.nonzero((clean > 0.35).any(axis=0))[0]
    if not len(xs):
        return None
    runs, start, prev = [], xs[0], xs[0]
    for x in xs[1:]:
        if x > prev + 1:
            runs.append((start, prev + 1))
            start = x
        prev = x
    runs.append((start, prev + 1))
    if nwords == 1:
        return [(runs[0][0], runs[-1][1])]
    gaps = sorted(((runs[i + 1][0] - runs[i][1], i) for i in range(len(runs) - 1)), reverse=True)
    if len(gaps) < nwords - 1:
        return None
    chosen, rest = gaps[:nwords - 1], gaps[nwords - 1:]
    if rest and chosen[-1][0] < 1.4 * rest[0][0] + 1:
        return None
    spans, s = [], runs[0][0]
    for i in sorted(i for _, i in chosen):
        spans.append((s, runs[i][1]))
        s = runs[i + 1][0]
    spans.append((s, runs[-1][1]))
    return spans


MAX_LETTERS = 30            # a line is matched on its first words up to this many letters (enough to tell fonts apart)


def read_line(rgb, bbox, text, words=None, budget=MAX_LETTERS):
    """A line prepared for matching (native coverage plus the analysis copy at() makes), or None when its ink cannot
    be separated from the ground. words: indexes of the words to keep (the rest of the line is blanked)."""
    lc = _coverage(rgb, bbox)
    if lc is None:
        return None
    parts = _parts(lc['cov'], lc['box'])
    if parts is None:
        return None
    toks = text.split()
    spans = _word_spans(parts['clean'], len(toks))
    clean = parts['clean']
    if words is None and spans and budget and _alnum(text) > budget:
        n, words = 0, []
        for i, t in enumerate(toks):
            if words and n + _alnum(t) > budget:
                break
            words.append(i)
            n += _alnum(t)
    if words is not None:
        if not spans:
            return None
        keep = np.zeros(clean.shape[1], bool)
        for i in words:
            keep[spans[i][0]:spans[i][1]] = True
        clean = clean * keep[None, :]
        toks = [toks[i] for i in words]
        spans = [spans[i] for i in words]
    rows = np.nonzero((clean > 0.5).any(axis=1))[0]
    cols = np.nonzero((clean > 0.5).any(axis=0))[0]
    if not len(rows):
        return None
    top, bottom, left, right = float(rows[0]), float(rows[-1] + 1), float(cols[0]), float(cols[-1] + 1)
    h = parts['base'] - top
    if h < 4:
        return None
    P0 = dict(clean=clean, base0=parts['base'], top0=top, bottom0=bottom, left0=left, right0=right, toks=toks,
              spans=spans, h=h, split=bool(spans), flat=lc['flat'], noise=lc['noise'], contrast=lc['contrast'],
              text=' '.join(toks))
    return at(P0, 'fine')


def at(P0, level):
    """The analysis copy of a line: 'fine' (letters about 36 to 64 px tall) or 'coarse' (about 20 px)."""
    h = P0['h']
    if level == 'coarse':
        A = 20.0 / h
    else:
        A = float(min(3, int(np.ceil(36 / h)))) if h < 28 else (48.0 / h if h > 64 else 1.0)
    clean = P0['clean']
    if A > 1:
        I = cv2.resize(clean, None, fx=A, fy=A, interpolation=cv2.INTER_LINEAR)
    elif A < 1:
        I = cv2.resize(clean, None, fx=A, fy=A, interpolation=cv2.INTER_AREA)
    else:
        I = clean.copy()
    toks, spans = P0['toks'], P0['spans']
    units = ([(w, (s0 * A, s1 * A)) for w, (s0, s1) in zip(toks, spans)] if spans
             else [(' '.join(toks), (P0['left0'] * A, P0['right0'] * A))])
    blur = float(np.sqrt(max(0.0, A * A / 4 - 1 / 12))) if A > 1 else 0.0
    hA = h * A
    r0 = int(max(0, np.floor(P0['top0'] * A - 0.25 * hA)))
    r1 = int(min(I.shape[0], np.ceil(P0['bottom0'] * A + 0.25 * hA)))
    c0 = int(max(0, np.floor(P0['left0'] * A - 0.3 * hA)))
    c1 = int(min(I.shape[1], np.ceil(P0['right0'] * A + 0.3 * hA)))
    I = np.ascontiguousarray(I[r0:r1, c0:c1], np.float32)
    units = [(w, (a - c0, b - c0)) for w, (a, b) in units]
    return dict(P0, I=I, A=A, base=P0['base0'] * A - r0, top=P0['top0'] * A - r0, units=units, blur=blur,
                mass=float(I.sum()), level=level)


# ---------------------------------------------------------------- fitting one face to a line

def _layout(face, units, k, xs=1.0):
    out, tracks = [], []
    for word, (x0, x1) in units:
        pens, p = [], 0.0
        for c in word:
            pens.append(p)
            p += glyph(face, c)[3]
        idx = [i for i, c in enumerate(word) if glyph(face, c)[4] is not None]
        if not idx:
            continue
        first, last = idx[0], idx[-1]
        kx = k * xs
        left = (pens[first] + glyph(face, word[first])[4][0]) * kx
        right = (pens[last] + glyph(face, word[last])[4][2]) * kx
        gaps = last - first
        t = ((x1 - x0) - (right - left)) / gaps if gaps else 0.0
        shift = (x0 + x1) / 2 - (left + right) / 2 if not gaps else x0 - left - first * t
        out.append([(word[i], shift + pens[i] * kx + i * t, i, pens[i] * kx) for i in idx])
        tracks.append((t, gaps))
    return out, tracks


def _compose(face, units, k, base_, shape, blurq, shifts=None, coarse=False, xs=1000):
    R = np.zeros(shape, np.float32)
    kq = int(round(k * 400)) * 10 if coarse else int(round(k * 4000))
    j = 0
    for unit in units:
        for c, x, i, pen in unit:
            dx, dy = shifts[j] if shifts is not None else (0, 0)
            xx, yy = x + dx, base_ + dy
            if coarse:
                g, ox, oy = scaled(face, c, kq, blurq, 0, 0, xs)
                _put(R, g, int(round(xx)) + ox, int(round(yy)) + oy)
            else:
                ix, iy = int(np.floor(xx)), int(np.floor(yy))
                g, ox, oy = scaled(face, c, kq, blurq, int((xx - ix) * 4), int((yy - iy) * 4), xs)
                _put(R, g, ix + ox, iy + oy)
            j += 1
    return R


def _l1(I, R):
    s = float(I.sum() + R.sum())
    return float(np.abs(I - R).sum()) / s if s else 1.0


def _refine(face, units, k, base_, P, rx, ry, blurq, xs=1000):
    I = P['I']
    kq = int(round(k * 4000))
    shifts = []
    for unit in units:
        for c, x, i, pen in unit:
            ix, iy = int(np.floor(x)), int(np.floor(base_))
            g, ox, oy = scaled(face, c, kq, blurq, int((x - ix) * 4), int((base_ - iy) * 4), xs)
            gx, gy = ix + ox, iy + oy
            h, w = g.shape
            X0, Y0 = max(0, gx - rx), max(0, gy - ry)
            X1, Y1 = min(I.shape[1], gx + w + rx), min(I.shape[0], gy + h + ry)
            if X1 - X0 < w or Y1 - Y0 < h or g.sum() < 1e-3:
                shifts.append((0, 0))
                continue
            m = cv2.matchTemplate(I[Y0:Y1, X0:X1], g, cv2.TM_CCORR_NORMED)
            yy, xx = np.unravel_index(int(np.argmax(m)), m.shape)
            shifts.append((X0 + xx - gx, Y0 + yy - gy))
    return shifts


def fit(face, P, fine=False, scales=(1.0,), xs=1.0):
    """Best match of the line in this face: (score, details) or None when the face lacks a letter."""
    text = P['text']
    if not has_glyphs(face, text):
        return None
    tops = [glyph(face, c)[4][1] for c in text if glyph(face, c)[4] is not None]
    if not tops:
        return None
    k0 = (P['base'] - P['top']) / -min(tops)
    blurq = int(round(P['blur'] * 100))
    xq = int(round(xs * 1000))
    best = None
    for s in scales:
        k = k0 * s
        units, tracks = _layout(face, P['units'], k, xs)
        shifts = None
        if fine:
            em = REF * k
            shifts = _refine(face, units, k, P['base'], P, max(2, int(round(0.06 * em))), max(1, int(round(0.025 * em))), blurq, xq)
        R = _compose(face, units, k, P['base'], P['I'].shape, blurq, shifts, coarse=not fine, xs=xq)
        score = _l1(P['I'], R)
        if best is None or score < best[0]:
            best = (score, dict(k=k, s=s, units=units, tracks=tracks, shifts=shifts, mass=P['mass'] / max(float(R.sum()), 1e-6)))
    return best


def tracking(det) -> float | None:
    """Letter spacing of the fitted line in thousandths of an em: least squares over the letter positions of every
    word of three letters or more (each word's letters weighted equally)."""
    em = REF * det['k']
    num = den = 0.0
    j = 0
    for unit, (t, gaps) in zip(det['units'], det['tracks']):
        if det['shifts'] is not None and len(unit) >= 3:
            xs = np.array([x + det['shifts'][j + n][0] for n, (c, x, i, pen) in enumerate(unit)])
            ii = np.array([i for c, x, i, pen in unit], float)
            pens = np.array([pen for c, x, i, pen in unit])
            slope = np.polyfit(ii, xs - pens, 1)[0]
            num += slope / em * 1000 * (len(unit) - 1)
            den += len(unit) - 1
        j += len(unit)
    return num / den if den else None


def match(P, faces, keep=12, always=(), scales=(0.97, 1.0, 1.03), family_ratio=1.6):
    """Coarse fit of every face, then a fine fit (letters nudged, scale searched) of the best `keep`, of `always`, and
    of the best face of each other family within family_ratio of the best coarse score. [(score, face, details)]."""
    coarse = []
    for f in faces:
        r = fit(f, P)
        if r is not None:
            coarse.append((r[0], f))
    if not coarse:
        return []
    coarse.sort(key=lambda x: x[0])
    chosen = [f for s, f in coarse[:keep]]
    fams = {f.family for f in chosen}
    for s, f in coarse[keep:]:
        if f.family not in fams and s <= family_ratio * coarse[0][0]:
            chosen.append(f)
            fams.add(f.family)
    fitted = {f for s, f in coarse}
    chosen += [f for f in always if f in fitted and f not in chosen]
    out = []
    for f in chosen:
        r = fit(f, P, fine=True, scales=scales)
        out.append((r[0], f, r[1]))
    out.sort(key=lambda x: x[0])
    return out


# ---------------------------------------------------------------- slant

def slant(P) -> tuple[float, float]:
    """Slant of the line's letters in degrees (positive leans right, as italics do): the shear that makes the
    letters' vertical strokes most vertical (sharpest column profile). Returns (angle, peak sharpness gain over the
    upright reading)."""
    I = P['I']
    base_ = P['base']
    best, at0 = None, None
    for deg in np.arange(-24.0, 24.01, 0.5):
        t = float(np.tan(np.radians(deg)))
        M = np.float32([[1, t, -base_ * t], [0, 1, 0]])
        pad = int(abs(t) * I.shape[0]) + 2
        W = cv2.warpAffine(I, M + np.float32([[0, 0, pad], [0, 0, 0]]), (I.shape[1] + 2 * pad, I.shape[0]),
                           flags=cv2.INTER_LINEAR, borderValue=0)
        prof = W.sum(axis=0)
        sharp = float((prof ** 2).sum())
        if abs(deg) < 1e-9:
            at0 = sharp
        if best is None or sharp > best[1]:
            best = (float(deg), sharp)
    return best[0], best[1] / at0 if at0 else 1.0


# ---------------------------------------------------------------- decisions (margins set on the synthetic calibration)

H_BANDS = (12, 18, 28, 48)       # letter-height bands (top-to-baseline px) the fit thresholds are set for


def _band(h: float) -> int:
    return sum(h >= b for b in H_BANDS)


def good_fit(h: float, cal=None) -> float:
    """The worst fit a true match reaches at this letter height: smaller type fits less well."""
    return (cal or CAL)['T'][_band(h)]


def _weight_reading(fits, family, italic):
    """Weight read within a family: (by fit: parabola round the best weight; by ink: where the ink-mass ratio of image
    to rendering crosses 1), on the optical size of the family's best fit."""
    fam = [f for f in fits if f[1].family == family and f[1].italic == italic]
    if not fam:
        return None, None
    best = min(fam, key=lambda f: f[0])
    grp = sorted([f for f in fam if f[1].note == best[1].note], key=lambda f: f[1].weight)
    ws = np.array([f[1].weight for f in grp], float)
    sc = np.array([f[0] for f in grp], float)
    ms = np.array([f[2]['mass'] for f in grp], float)
    if len(ws) == 1:
        return float(ws[0]), float(ws[0])
    i = int(np.argmin(sc))
    w_s = float(ws[i])
    if 0 < i < len(ws) - 1 and ws[i + 1] - ws[i] == ws[i] - ws[i - 1]:
        a, b, c = sc[i - 1], sc[i], sc[i + 1]
        den = a - 2 * b + c
        if den > 0:
            w_s = float(ws[i] + np.clip(0.5 * (a - c) / den, -0.5, 0.5) * (ws[i + 1] - ws[i]))
    w_m = None
    for j in range(len(ws) - 1):
        if (ms[j] - 1) * (ms[j + 1] - 1) <= 0 and ms[j] != ms[j + 1]:
            w_m = float(ws[j] + (ms[j] - 1) / (ms[j] - ms[j + 1]) * (ws[j + 1] - ws[j]))
            break
    if w_m is None:
        w_m = float(ws[0] - 100) if ms[0] < 1 else float(ws[-1] + 100)
    return w_s, w_m


def _render(P, face, det):
    return _compose(face, det['units'], det['k'], P['base'], P['I'].shape, int(round(P['blur'] * 100)), det['shifts'])


def letter_errors(P, fa):
    """Error of each letter of a fitted face (normalised ink difference inside the letter's box): a true match fits
    every letter about equally well, a near look-alike misses a few. Returns the errors, worst first."""
    face, det = fa[1], fa[2]
    R = _render(P, face, det)
    I = P['I']
    kq = int(round(det['k'] * 4000))
    blurq = int(round(P['blur'] * 100))
    errs, j = [], 0
    for unit in det['units']:
        for c, x, i, pen in unit:
            dx, dy = det['shifts'][j] if det['shifts'] is not None else (0, 0)
            j += 1
            xx, yy = x + dx, P['base'] + dy
            ix, iy = int(np.floor(xx)), int(np.floor(yy))
            g, ox, oy = scaled(face, c, kq, blurq, int((xx - ix) * 4), int((yy - iy) * 4))
            x0, y0 = max(0, ix + ox), max(0, iy + oy)
            x1, y1 = min(I.shape[1], ix + ox + g.shape[1]), min(I.shape[0], iy + oy + g.shape[0])
            if x1 <= x0 or y1 <= y0 or g.sum() < 0.02 * (REF * det['k']) ** 2:
                continue                      # punctuation and specks decide nothing
            a_, r_ = I[y0:y1, x0:x1], R[y0:y1, x0:x1]
            s_ = float(a_.sum() + r_.sum())
            if s_ > 0:
                errs.append(float(np.abs(a_ - r_).sum()) / s_)
    return sorted(errs, reverse=True)


def pair(P, fa, fb):
    """How much better face a explains the line than face b, judged only where their renderings differ:
    d = (|I - Rb|^2 - |I - Ra|^2) / |Ra - Rb|^2, which is +1 when the image is exactly a's rendering and -1 when it
    is exactly b's. Returns (d, difference energy as a share of the line's ink)."""
    Ra, Rb = _render(P, fa[1], fa[2]), _render(P, fb[1], fb[2])
    I = P['I']
    den = float(((Ra - Rb) ** 2).sum())
    if den <= 1e-9:
        return 0.0, 0.0
    return float(((I - Rb) ** 2).sum() - ((I - Ra) ** 2).sum()) / den, den / max(P['mass'], 1e-6)


def line_stats(P, fits, specs, opsz=None):
    """The measurements a decision about specs [(family, weights or None, italic)] rests on; opsz: {family: [allowed
    optical sizes]} adds a test between the allowed optical size and the others at the same weight."""
    fams = {(f, it) for f, ws, it in specs}
    A = [f for f in fits if (f[1].family, f[1].italic) in fams]
    O = [f for f in fits if (f[1].family, f[1].italic) not in fams]
    if not A:
        return None
    a = A[0]                                            # fits are sorted best first
    o = O[0] if O else None                             # no other family came near enough to be fitted finely
    st = dict(h=P['h'], a=a[1].label, a_family=a[1].family, a_fit=a[0], o=o[1].label if o else 'none near',
              o_fit=o[0] if o else 1.0, letters=_alnum(P['text']), flat=P['flat'], noise=P['noise'])
    le = letter_errors(P, a)
    st['a_worst'] = le[0] if le else None
    st['a_worst2'] = le[1] if len(le) > 1 else st['a_worst']
    st['a_median'] = float(np.median(le)) if le else None
    st['fail_d'], st['fail_e'] = pair(P, o, a) if o and o[0] < a[0] else (None, None)
    em = REF * a[2]['k']                                # spacing the expected font needs to span the words, per em
    st['a_track'] = max((abs(t / em * 1000) for t, g in a[2]['tracks'] if g), default=0.0)
    rivals, seen = [], set()
    for f in O:
        if f[1].family not in seen and f[0] <= a[0] * CAL['consider']:
            rivals.append(f)
            seen.add(f[1].family)
    st['pass_d'] = st['pass_e'] = None
    for r in rivals:
        d, e = pair(P, a, r)
        if st['pass_d'] is None or d < st['pass_d']:
            st['pass_d'], st['pass_e'], st['pass_rival'] = d, e, r[1].label
    allowed = [ws for f, ws, it in specs if f == a[1].family and it == a[1].italic]
    st['weights'] = None if any(ws is None for ws in allowed) else sorted({w for ws in allowed for w in ws})
    if st['weights']:
        W = st['weights']
        fam = [f for f in A if f[1].family == a[1].family and f[1].note == a[1].note]
        ok = [f for f in fam if f[1].weight in W]
        bad = [f for f in fam if f[1].weight not in W]
        st['w_pass_d'] = st['w_fail_d'] = None
        if ok and bad:
            aw = ok[0]
            near = []
            for side in (-1, 1):
                cand = [f for f in bad if (f[1].weight - aw[1].weight) * side > 0]
                if cand:
                    near.append(min(cand, key=lambda f: abs(f[1].weight - aw[1].weight)))
            for n in near:
                d, e = pair(P, aw, n)
                if st['w_pass_d'] is None or d < st['w_pass_d']:
                    st['w_pass_d'], st['w_pass_vs'] = d, n[1].label
            for n in bad:
                if min(abs(n[1].weight - w) for w in W) >= 100 and n[0] < aw[0]:
                    d, e = pair(P, n, aw)
                    if st['w_fail_d'] is None or d > st['w_fail_d']:
                        st['w_fail_d'], st['w_fail_vs'] = d, n[1].label
            st['aw'], st['aw_fit'] = aw[1].label, aw[0]
    if opsz and a[1].family in opsz:
        allowed_o = {f'opsz {int(v)}' for v in opsz[a[1].family]}
        same = [f for f in A if f[1].family == a[1].family and f[1].italic == a[1].italic and f[1].weight == a[1].weight]
        ok = [f for f in same if f[1].note in allowed_o]
        bad = [f for f in same if f[1].note not in allowed_o]
        st['o_pass_d'] = st['o_fail_d'] = None
        if ok and bad:
            for n in bad:
                d, e = pair(P, ok[0], n)
                if st['o_pass_d'] is None or d < st['o_pass_d']:
                    st['o_pass_d'] = d
                if st['o_fail_d'] is None or -d > st['o_fail_d']:
                    st['o_fail_d'] = -d
            st['opsz_best'] = min(same, key=lambda f: f[0])[1].note
    return st


def decide(st, cal=None):
    """pass / fail / person from line_stats, with the calibrated margins. A fail needs another candidate to explain
    the letters clearly better than the expected font where the two differ (pair d), and either that candidate fits as
    well as true matches do, or the expected font fits worse than any true match was seen to (a clean line only)."""
    c = cal or CAL
    if st is None:
        return PERSON, 'the expected fonts could not be rendered for this text'
    b = _band(st['h'])
    T = c['T'][b]
    if st['letters'] < c['min_letters']:
        return PERSON, 'too few letters to tell fonts apart'
    if st['h'] < c['min_h']:
        return PERSON, 'letters too small to tell fonts apart'
    fd, fe = st['fail_d'], st['fail_e']
    if fd is not None and fe is not None and fe >= c['min_energy']:
        if st['o_fit'] <= T and fd >= c['d_fail']:
            return 'fail', 'another typeface matches the letters clearly better'
        if (st['a_fit'] >= c['T_mis'][b] and fd >= c['d_fail_mis'] and st['flat'] >= c['mis_flat']
                and st['noise'] <= c['mis_noise'] and st['h'] >= c['mis_min_h'] and st.get('a_track', 0) <= c['mis_track']):
            return 'fail', 'the expected typeface does not match these letters'
    tight = c['tight'].get(st.get('a_family'), 1.0)     # families with close look-alikes outside the candidate list
    if not (st['a_fit'] <= T * tight and (st['pass_d'] is None or (st['pass_d'] >= c['d_pass'] and st['pass_e'] >= c['min_energy']))):
        return PERSON, 'typeface not clear enough to call'
    if st.get('a_worst2') is not None and (st['a_worst2'] > c['G'][b] * tight or
                                           st['a_worst2'] > c['G_ratio'] * max(st['a_median'], 1e-3)):
        return PERSON, 'some letters do not match the expected typeface closely'
    if 'o_pass_d' in st:
        if st['o_fail_d'] is not None and st['o_fail_d'] >= c['dw_fail']:
            return 'fail', 'the right typeface at another optical size'
        if st['o_pass_d'] is None or st['o_pass_d'] < c['dw_pass']:
            return PERSON, 'optical size not clear enough to call'
    if st['weights'] is None:
        return 'pass', 'typeface'
    if st['h'] < c['w_min_h']:
        return PERSON, 'letters too small to read the weight'
    if st.get('w_fail_d') is not None and st['w_fail_d'] >= c['dw_fail']:
        return 'fail', 'the right typeface at another weight'
    if st.get('w_pass_d') is not None and st['w_pass_d'] >= c['dw_pass'] and st['a'] == st.get('aw', st['a']):
        return 'pass', 'typeface and weight'
    return PERSON, 'weight not clear enough to call'


def verdict(P, fits, specs, opsz=None):
    st = line_stats(P, fits, specs, opsz)
    status, why = decide(st)
    ev = {} if st is None else {'best': st['a'] if st['a_fit'] <= st['o_fit'] else st['o'], 'expected_fit': round(st['a_fit'], 3),
                                'closest_other': st['o'], 'other_fit': round(st['o_fit'], 3)}
    if st and st.get('pass_d') is not None:
        ev['vs_rival'] = round(st['pass_d'], 2)
    if st and st.get('fail_d') is not None:
        ev['other_vs_expected'] = round(st['fail_d'], 2)
    if st and st.get('weights'):
        ev.update({k: (round(v, 2) if isinstance(v, float) else v) for k, v in st.items() if k.startswith('w_') or k == 'aw'})
    if status != 'pass':
        ev['reason'] = why
    return status, ev


# Margins from the synthetic calibration (round3/fonts/search.py on 1,648 lines: 1,233 in brand fonts and macOS
# fonts, 415 in further fonts; on the checking machine every macOS font is outside the candidate list): zero wrong
# answers on every line, each margin then moved one step back towards strict. Inter never passes: SF Pro, SF
# Compact, Helvetica Neue and Avenir Next lines fit it about as well as Inter itself does.
CAL = dict(T=(0.16, 0.15, 0.14, 0.13, 0.12), T_mis=(0.35, 0.3, 0.25, 0.2, 0.15), consider=1.5, min_letters=3,
           d_fail=0.9, d_fail_mis=0.6, mis_flat=0.9, mis_noise=0.04, d_pass=0.4, min_energy=0.2, dw_fail=0.95,
           dw_pass=0.8, G=(0.45, 0.43, 0.41, 0.39, 0.37), G_ratio=3.5, min_h=10, w_min_h=20, mis_min_h=16,
           tight={'Inter': 0.0, 'Source Serif 4': 0.8, 'Cormorant Garamond': 0.6},
           mis_track=150)   # a misfit fail only where the reading's words span the ink plausibly (OCR can drop a space)


# ---------------------------------------------------------------- reading a deliverable: pages, lines, fits

@functools.lru_cache(maxsize=24)
def _page(key: str, frame: int):
    """(RGB array, OCR layer) of an image, or of one held frame of a video."""
    path = Path(key)
    rgb = r3._pixels(key, frame).astype(np.uint8)
    if path.suffix.lower() in ('.png', '.jpg', '.jpeg'):
        return rgb, base.merged(base.text_layers(path))
    return rgb, base.ocr_image(Image.fromarray(rgb))


def _frames_of(path: Path, which: str = 'all'):
    """Frames to read: -1 for an image; for a video every sampled frame (one a second, objective_ops.video_frames), a
    run of identical frames read once; which='last': the last held frame (objective_ops_r3._frames), the end card."""
    if path.suffix.lower() != '.mp4':
        return [-1]
    if which == 'last':
        return r3._frames(path)[-1:]
    frames = base.video_frames(str(path))
    keep = []
    for i in range(len(frames)):
        if keep and np.abs(np.asarray(frames[i], np.int16) - np.asarray(frames[keep[-1]], np.int16)).mean() < 1.5:
            continue
        keep.append(i)
    return keep


def _key(text: str) -> str:
    return re.sub(r'[^a-z0-9]', '', canon(text, False))


def _alnum(text: str) -> int:
    return len(re.findall(r'[A-Za-z0-9]', text))


def _part_of(text: str, whole: str) -> bool:
    """The line's words are a run of the words of `whole` (letter case and punctuation aside)."""
    lk = [_key(x) for x in text.split() if _key(x)]
    wk = [_key(x) for x in whole.split() if _key(x)]
    n = len(lk)
    return bool(lk) and any(wk[i:i + n] == lk for i in range(len(wk) - n + 1))


def select_lines(layer, a):
    """Lines a check is about. Any of: texts (lines containing one of them), whole (lines that are exactly one of them,
    case and punctuation aside), part_of (lines whose words are a run of one of them, e.g. one line of a wrapped
    title), patterns (regular expressions), roles (text roles of objective_ops_r3._roles, plus 'secondary' = headings
    other than the main one), shares (lines sharing a run of two words or more with one of them), all_text. Left out: except, except_whole, except_patterns, except_roles. Kept only:
    lowercase_only / figures_only (lines with a lowercase letter / a figure), below (lines under the line holding one
    of these texts), within_roles (lines of these roles), largest_only (the largest of the picked lines). None when a
    selection uses roles and the page has no running text to set the body size (roles cannot be read)."""
    lines = [l for l in layer.lines if canon(l.text).strip()]
    cache = {}
    if (a.get('roles') or a.get('within_roles') or a.get('except_roles')) and r3._roles(layer)[0] is None:
        return None                          # no running text sets a body size: roles cannot be read

    def roles():
        if 'r' not in cache:
            body, rl = r3._roles(layer)
            rl = dict(rl)
            rl['secondary'] = [l for l in rl.get('heading', []) if l not in rl.get('main', [])]
            cache['r'] = rl
        return cache['r']
    floor = None
    if a.get('below'):
        anchors = [l for l in lines if any(_key(l.text) == _key(x) or contains(canon(l.text), x, False) for x in a['below'])]
        if not anchors:
            return []
        floor = min(l.bbox[3] for l in anchors)
    picks = []
    for l in lines:
        t = canon(l.text)
        if any(_key(t) == _key(x) for x in a.get('except_whole', [])):
            continue
        if any(contains(t, x, False) for x in a.get('except', [])):
            continue
        if any(re.search(p, t, re.I) for p in a.get('except_patterns', [])):
            continue
        if a.get('except_roles') and any(l in roles().get(r, []) for r in a['except_roles']):
            continue
        hit = bool(a.get('all_text'))
        hit = hit or any(contains(t, x, False) or (len(_key(x)) >= 4 and _key(x) in _key(t)) for x in a.get('texts', []))
        hit = hit or any(_key(t) == _key(x) for x in a.get('whole', []))
        hit = hit or any(_part_of(t, x) for x in a.get('part_of', []))
        hit = hit or any(_run_of([_key(w) for w in t.split()], x) for x in a.get('shares', []))
        hit = hit or any(re.search(p, t, re.I) for p in a.get('patterns', []))
        hit = hit or bool(a.get('roles') and any(l in roles().get(r, []) for r in a['roles']))
        if not hit:
            continue
        if a.get('lowercase_only') and not re.search(r'[a-z]', t):
            continue
        if a.get('figures_only') and not re.search(r'\d', t):
            continue
        if floor is not None and l.bbox[1] < floor - 1:
            continue
        if a.get('within_roles') and not any(l in roles().get(r, []) for r in a['within_roles']):
            continue
        picks.append(l)
    if a.get('largest_only') and picks:
        top = max(l.size for l in picks)
        picks = [l for l in picks if l.size >= 0.92 * top]
    return picks


def render_text(line, a) -> str:
    """The text to render: the OCR reading, or the check's own wording where the line is exactly that wording (its
    spelling, in the line's letter case)."""
    t = canon(line.text)
    for x in list(a.get('whole', [])) + list(a.get('texts', [])):
        if _key(t) == _key(x):
            return x.upper() if (t.upper() == t and t.lower() != t) else x
    return t


_FITS: dict = {}


def line_fits(key, frame, rgb, line_or_bbox, text, words=None, families=(), all_opsz=()):
    """Fits of the candidates to one line, cached per line: (P, [(score, face, details)]) best first, or (None, why).
    Every candidate is fitted coarsely; finely fitted (letters nudged, scale searched) are the best CAL['keep'], the
    best of each family within CAL['family_ratio'] of the best, every weight of each family in `families` [(family,
    italic)] at the optical size of its best coarse fit, and every face of the families in all_opsz."""
    bbox = tuple(round(float(v), 1) for v in getattr(line_or_bbox, 'bbox', line_or_bbox))
    k = (key, frame, bbox, text, tuple(words) if words else None)
    if k not in _FITS:
        P = read_line(rgb, bbox, text, words)
        if P is None:
            _FITS[k] = (None, 'the words of the line could not be separated' if words else 'ink not separable from its ground')
        elif P['flat'] < CAL['min_flat'] or P['noise'] > CAL['max_noise']:
            _FITS[k] = (None, 'line on a textured or uneven ground')
        else:
            _FITS[k] = (P, {'coarse': None, 'fine': {}})
        if len(_FITS) > 200:
            _FITS.pop(next(iter(_FITS)))
    P, store = _FITS[k]
    if P is None:
        return None, store
    if store['coarse'] is None:
        Pc = at(P, 'coarse')
        coarse = []
        for f in all_faces():
            r = fit(f, Pc)
            if r is not None:
                coarse.append((r[0], f))
        coarse.sort(key=lambda x: x[0])
        store['coarse'] = coarse
    coarse = store['coarse']
    if not coarse:
        return None, 'no candidate font has these letters'
    if 'soft' not in store:            # the image's softness (video, JPEG, resampling), read with the best coarse face
        base_blur, best_soft = P['blur'], None
        for e in CAL['soft_grid']:
            P['blur'] = float(np.hypot(base_blur, e))
            r = fit(coarse[0][1], P, fine=True, scales=(1.0,))
            if r and (best_soft is None or r[0] < best_soft[0] - 1e-4):
                best_soft = (r[0], e)
        store['soft'] = best_soft[1] if best_soft else 0.0
        P['blur'] = float(np.hypot(base_blur, store['soft']))
    chosen = [f for s, f in coarse[:CAL['keep']]]
    fams = {f.family for f in chosen}
    for s, f in coarse[CAL['keep']:]:
        if f.family not in fams and s <= CAL['family_ratio'] * coarse[0][0]:
            chosen.append(f)
            fams.add(f.family)
    for fam, it in families:
        mine = [(s, f) for s, f in coarse if f.family == fam and f.italic == it]
        if mine:
            chosen += [f for s, f in mine if f.note == mine[0][1].note]
    chosen += [f for s, f in coarse if f.family in all_opsz]
    for f in dict.fromkeys(chosen):
        if f not in store['fine']:
            store['fine'][f] = fit(f, P, fine=True, scales=(0.97, 1.0, 1.03))
    fits = sorted(((r[0], f, r[1]) for f, r in store['fine'].items()), key=lambda x: x[0])
    return P, fits


def _specs(fonts, italic=False):
    """[(family, weights or None, italic)] from fonts: [[family, weight names or numbers or None], ...]; italic True,
    False or 'any' (upright or italic)."""
    out = []
    for fam, ws in fonts:
        if ws is not None:
            ws = [WEIGHT_NAMES[re.sub(r'[^a-z]', '', w.lower())] if isinstance(w, str) else int(w) for w in ws]
        for it in ((False, True) if italic == 'any' else (bool(italic),)):
            out.append((fam, ws, it))
    return out


def _families(specs):
    return tuple(dict.fromkeys((fam, it) for fam, ws, it in specs))


def _run_of(keys, phrase):
    """Indexes of the longest run of words shared with phrase (two words at least, or the whole phrase)."""
    pk = [_key(x) for x in phrase.split() if _key(x)]
    best = []
    for i in range(len(keys)):
        for j in range(len(pk)):
            n = 0
            while i + n < len(keys) and j + n < len(pk) and keys[i + n] and keys[i + n] == pk[j + n]:
                n += 1
            if n > len(best):
                best = list(range(i, i + n))
    return best if len(best) >= min(2, len(pk)) else []


def _words_of(text, sel):
    """Indexes of the words a check is about within its line, or None to leave the line out. sel: {'only': w} (the
    last w), {'before': w} (the words before the last w; every word of a line without w, i.e. an earlier line of the
    same title), {'digits': True} (words with a figure), {'no_figures': True} (words without one), {'phrase': p} (the run of words shared with p),
    {'drop': p} (every word but the run shared with p)."""
    toks = text.split()
    keys = [_key(t) for t in toks]
    if sel.get('digits'):
        return [i for i, t in enumerate(toks) if re.search(r'\d', t)] or None
    if sel.get('no_figures'):
        return [i for i, t in enumerate(toks) if not re.search(r'\d', t) and keys[i]] or None
    if sel.get('phrase'):
        return _run_of(keys, sel['phrase']) or None
    if sel.get('drop'):
        run = set(_run_of(keys, sel['drop']))
        return [i for i in range(len(toks)) if i not in run and keys[i]] or None
    w = _key(sel.get('only') or sel.get('before') or '')
    if w and w in keys:
        i = len(keys) - 1 - keys[::-1].index(w)
        return [i] if sel.get('only') else (list(range(0, i)) or None)
    if sel.get('before'):
        return list(range(len(toks)))
    return None


def _gate(line, a):
    if line.conf < OCR_GOOD_CONF:
        return 'OCR read below 80% confidence'
    if _alnum(line.text) < a.get('min_chars', 2):
        return 'too few letters to judge'
    return None


def _speck(rgb, line) -> bool:
    """An OCR reading that is not a line of type: under three letters or figures, or read uncertainly over a
    photograph (letters guessed from texture)."""
    if _alnum(line.text) < 3:
        return True
    lc = _coverage(rgb, line.bbox)
    return lc is None or lc['flat'] < CAL['min_flat']


def _in_families(P, fits, families):
    """Is the line clearly set in one of these families (any weight, upright or italic)? 'pass' yes, 'fail' no."""
    st = line_stats(P, fits, [(fam, None, it) for fam in families for it in (False, True)])
    return decide(st)[0]


def op_typeface_raster(path, a):
    """Selected text lines on an image (videos: held frames) are set in one of the allowed fonts (fonts: [[family,
    [weights] or None], ...]; italic: the allowed slant, default upright; opsz: {family: [optical sizes]}). Modes:
    forbid: [families] the lines must not be in; if_family: [families] only lines set in these are checked;
    unless_families: [families] lines set in these are not checked. words narrows a line to some of its words (see
    _words_of). Each line's text is rendered in every candidate font and compared with its letters (module notes).
    optional: kept for the record only; no such line never passes (OCR can miss a whole small line while reading the
    rest with full confidence), so a person confirms the absence."""
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.mp4'):
        return PERSON, {'reason': 'typeface is read on images and video frames only'}
    if not stand_ins_ok():
        return PERSON, {'reason': 'the comparison fonts are not installed on this machine'}
    specs = _specs(a['fonts'], a.get('italic')) if a.get('fonts') else [(fam, None, False) for fam in a['forbid']]
    gate_fams = list(a.get('if_family') or a.get('unless_families') or [])
    fams = _families(specs) + tuple((f, it) for f in gate_fams for it in (False, True))
    results, seen = [], set()
    confident = True
    for fr in _frames_of(path, a.get('frames', 'all')):
        rgb, layer = _page(str(path), fr)
        confident &= bool(layer.confident)
        picked = select_lines(layer, a)
        if picked is None:
            results.append((PERSON, {'reason': 'text roles cannot be read: no running text sets the body size'}))
            picked = []
        for l in picked:
            text = render_text(l, a)
            words = None
            if a.get('words'):
                words = _words_of(text, a['words'])
                if words is None:
                    continue
                if len(words) == len(text.split()):
                    words = None
            shown = ' '.join(text.split()[i] for i in words) if words else text
            sig = (_key(text), tuple(words or ()))
            if sig in seen:
                continue
            seen.add(sig)
            why = _gate(l, a) or (None if _alnum(shown) >= a.get('min_chars', 2) else 'too few letters to judge')
            if why:
                if a.get('all_text') and _speck(rgb, l):
                    continue
                results.append((PERSON, {'line': shown, 'reason': why}))
                continue
            P, fits = line_fits(str(path), fr, rgb, l, text, words, fams, tuple((a.get('opsz') or {}).keys()))
            if P is None:
                if a.get('all_text') and 'textured' in str(fits) and _alnum(text) < 4:
                    continue
                results.append((PERSON, {'line': shown, 'reason': fits}))
                continue
            if gate_fams:
                g = _in_families(P, fits, gate_fams)
                if g == PERSON:
                    results.append((PERSON, {'line': shown, 'reason': 'not clear whether the line is set in ' + ' or '.join(gate_fams)}))
                    continue
                if (g == 'pass') != bool(a.get('if_family')):
                    results.append(('skip', {'line': shown}))
                    continue
            st, ev = verdict(P, fits, specs, a.get('opsz'))
            if a.get('forbid'):
                st = {'pass': 'fail', 'fail': 'pass'}.get(st, PERSON)
                ev = dict(ev, reason='set in a typeface it must not be in') if st == 'fail' else ev
            results.append((st, dict(ev, line=shown, box=[int(round(v)) for v in l.bbox], frame=fr)))
    checked = [(st, ev) for st, ev in results if st != 'skip']
    if not checked:
        # never a pass on absence: OCR can miss a whole small line (a plate numeral did) with full confidence elsewhere
        if results:
            return PERSON, {'reason': 'no line in the checked typefaces was found; a person confirms none was missed'}
        if a.get('optional') and confident:
            return PERSON, {'reason': 'no such text found; a person confirms it is absent'}
        return PERSON, {'reason': 'text not found' if not a.get('optional') else 'text not found and the reading is incomplete'}
    fails = [ev for st, ev in checked if st == 'fail']
    if fails:
        return 'fail', {'lines': fails[:4], 'checked': len(checked)}
    unsure = [ev for st, ev in checked if st == PERSON]
    if unsure:
        return PERSON, {'reason': unsure[0].get('reason', 'not clear'), 'lines': unsure[:4]}
    return 'pass', {'lines': [ev for st, ev in checked][:4], 'checked': len(checked)}


def op_upright_raster(path, a):
    """Selected lines are upright, not italic: the slant of their letters' vertical strokes (shear that makes them
    most vertical) is within UPRIGHT degrees; SLANTED degrees or more is italic."""
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.mp4'):
        return PERSON, {'reason': 'slant is read on images and video frames only'}
    results = []
    confident = True
    for fr in _frames_of(path, a.get('frames', 'all')):
        rgb, layer = _page(str(path), fr)
        confident &= bool(layer.confident)
        picked = select_lines(layer, a)
        if picked is None:
            results.append((PERSON, {'reason': 'text roles cannot be read: no running text sets the body size'}))
            picked = []
        for l in picked:
            text = render_text(l, a)
            words = _words_of(text, a['words']) if a.get('words') else None
            if a.get('words') and words is None:
                continue
            if words is not None and len(words) == len(text.split()):
                words = None
            why = _gate(l, a)
            if why:
                results.append((PERSON, {'line': text, 'reason': why}))
                continue
            P = read_line(rgb, l.bbox, text, words)
            if P is None or P['flat'] < CAL['min_flat']:
                results.append((PERSON, {'line': text, 'reason': 'ink not separable from its ground'}))
                continue
            deg, gain = slant(P)
            ev = {'line': text, 'slant_degrees': deg}
            if -CAL['upright_back'] <= deg <= CAL['upright']:
                results.append(('pass', ev))
            elif deg >= CAL['slanted']:
                results.append(('fail', dict(ev, reason='letters lean like italics')))
            else:
                results.append((PERSON, dict(ev, reason='slant between upright and italic')))
    if not results:
        if a.get('optional') and confident:   # never a pass on absence (see op_typeface_raster)
            return PERSON, {'reason': 'no such text found; a person confirms it is absent'}
        return PERSON, {'reason': 'text not found'}
    fails = [ev for st, ev in results if st == 'fail']
    if fails:
        return 'fail', {'lines': fails[:4]}
    unsure = [ev for st, ev in results if st == PERSON]
    if unsure:
        return PERSON, {'reason': unsure[0].get('reason', 'not clear'), 'lines': unsure[:4]}
    return 'pass', {'lines': [ev for st, ev in results][:4]}


CAL.update(soft_grid=(0.0, 0.6, 1.2, 1.8), min_flat=0.5, max_noise=0.08, keep=12, family_ratio=1.6, upright=4.0, upright_back=5.0, slanted=6.0)


def _tracked(path, sel, fonts=None):
    """Letter spacing (thousandths of an em) of the lines a selection picks, each read in its best-fitting font:
    [(text, tracking, font, fit)] or (None, reason)."""
    out = []
    specs = _specs(fonts) if fonts else []
    always = _families(specs) if specs else ()
    for fr in _frames_of(path, sel.get('frames', 'all')):
        rgb, layer = _page(str(path), fr)
        picked = select_lines(layer, sel)
        if picked is None:
            return None, 'text roles cannot be read: no running text sets the body size'
        for l in picked:
            text = render_text(l, sel)
            why = _gate(l, sel)
            if why:
                return None, f'{text}: {why}'
            P, fits = line_fits(str(path), fr, rgb, l, text, None, always)
            if P is None:
                return None, f'{text}: {fits}'
            best = fits[0]
            if best[0] > good_fit(P['h']):
                return None, f'{text}: no candidate font fits the letters closely'
            if P['h'] < CAL['track_min_h']:
                return None, f'{text}: letters too small to measure spacing reliably'
            if best[1].family in BRAND and BRAND[best[1].family][3]:
                return None, f'{text}: best font has optical sizes, whose widths differ'
            t = tracking(best[2])
            if t is None:
                return None, f'{text}: too few letters per word to measure spacing'
            out.append((text, t, best[1].label, round(best[0], 3)))
    return out, None


def op_tracking_raster(path, a):
    """Line a is letterspaced more open than line b: each line's letter spacing is fitted (least squares over its
    letter positions, in its best-fitting font) and the difference compared with the measuring error."""
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.mp4'):
        return PERSON, {'reason': 'spacing is read on images and video frames only'}
    if not stand_ins_ok():
        return PERSON, {'reason': 'the comparison fonts are not installed on this machine'}
    ta, why_a = _tracked(path, a['a'], a.get('fonts_a'))
    tb, why_b = _tracked(path, a['b'], a.get('fonts_b'))
    if ta is None or tb is None:
        return PERSON, {'reason': why_a or why_b}
    if not ta or not tb:
        if a.get('optional') and (not ta or not tb):   # never a pass on absence (see op_typeface_raster)
            return PERSON, {'reason': 'one of the lines was not found; a person confirms it is absent'}
        return PERSON, {'reason': 'line not found', 'a': [x[0] for x in ta], 'b': [x[0] for x in tb]}
    lo_a, hi_b = min(x[1] for x in ta), max(x[1] for x in tb)
    hi_a, lo_b = max(x[1] for x in ta), min(x[1] for x in tb)
    ev = {'a': [(x[0], round(x[1]), x[2]) for x in ta][:3], 'b': [(x[0], round(x[1]), x[2]) for x in tb][:3]}
    if lo_a - hi_b >= CAL['track_pass']:
        return 'pass', ev
    if hi_a - lo_b <= CAL['track_fail']:
        return 'fail', dict(ev, reason='not letterspaced more open')
    return PERSON, dict(ev, reason='spacing difference too small to call')


def op_not_stretched_raster(path, a):
    """No selected line is stretched or condensed: each line is fitted in its best fonts at their natural width and
    at horizontal scales from 80% to 125%. Natural width fitting 5% better than every scaled version passes (not for a
    family with optical sizes, whose wider sizes look like stretched type); anything else goes to a person. No line
    fails automatically: a brand font scaled horizontally can imitate a natural font outside the candidate list (Georgia
    Bold reads as Source Serif 4 Bold at 92% width), so stretched type is left to a person."""
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.mp4'):
        return PERSON, {'reason': 'type width is read on images and video frames only'}
    if not stand_ins_ok():
        return PERSON, {'reason': 'the comparison fonts are not installed on this machine'}
    specs = _specs(a['fonts']) if a.get('fonts') else []
    always = _families(specs) if specs else ()
    results, seen = [], set()
    for fr in _frames_of(path, a.get('frames', 'all')):
        rgb, layer = _page(str(path), fr)
        picked = select_lines(layer, a)
        if picked is None:
            results.append((PERSON, {'reason': 'text roles cannot be read: no running text sets the body size'}))
            picked = []
        for l in picked:
            text = render_text(l, a)
            if _key(text) in seen:
                continue
            seen.add(_key(text))
            if a.get('all_text') and (l.conf < OCR_GOOD_CONF or _alnum(text) < 3):
                continue
            why = _gate(l, a)
            if why:
                results.append((PERSON, {'line': text, 'reason': why}))
                continue
            P, fits = line_fits(str(path), fr, rgb, l, text, None, always)
            if P is None:
                if a.get('all_text') and 'textured' in str(fits):
                    continue        # type over a photograph is read by a person under other checks
                results.append((PERSON, {'line': text, 'reason': fits}))
                continue
            natural = fits[0]
            tryfaces = [f for s, f, d in fits[:2]]
            for fam, ws, it in specs:
                fam_fits = [x for x in fits if x[1].family == fam and x[1].italic == it]
                if fam_fits:
                    tryfaces.append(min(fam_fits, key=lambda x: x[0])[1])
            best_x = None
            for f in dict.fromkeys(tryfaces):
                for xs in CAL['xs_grid']:
                    r = fit(f, P, fine=True, scales=(1.0,), xs=xs)
                    if r and (best_x is None or r[0] < best_x[0]):
                        best_x = (r[0], f, xs)
            ev = {'line': text, 'natural': natural[1].label, 'natural_fit': round(natural[0], 3)}
            T = good_fit(P['h'])
            if best_x:
                ev.update(scaled=f'{best_x[1].label} at {round(best_x[2] * 100)}% width', scaled_fit=round(best_x[0], 3))
            opsz = natural[1].family in BRAND and bool(BRAND[natural[1].family][3])
            if natural[0] <= T and not opsz and (best_x is None or best_x[0] >= natural[0] * (1 + CAL['stretch_keep'])):
                results.append(('pass', ev))
            elif CAL['stretch_fail'] and best_x and best_x[0] <= T and natural[0] >= best_x[0] * (1 + CAL['stretch_fail']):
                results.append(('fail', dict(ev, reason='letters fit a font scaled horizontally, not its natural width')))
            else:
                results.append((PERSON, dict(ev, reason='width not clear enough to call' if not opsz else
                                             'a font with optical sizes: a wider optical size looks like stretched type')))
    if not results:
        return PERSON, {'reason': 'no text read confidently'}
    fails = [ev for st, ev in results if st == 'fail']
    if fails:
        return 'fail', {'lines': fails[:4], 'checked': len(results)}
    unsure = [ev for st, ev in results if st == PERSON]
    if unsure:
        return PERSON, {'reason': unsure[0].get('reason', 'not clear'), 'lines': unsure[:4]}
    return 'pass', {'checked': len(results), 'lines': [ev for st, ev in results][:3]}


CAL.update(track_pass=28, track_fail=-10, track_min_h=30, xs_grid=(0.8, 0.86, 0.92, 1.08, 1.16, 1.25), stretch_keep=0.05, stretch_fail=None)

OPS.update({
    'v2_typeface_raster': op_typeface_raster,
    'v2_upright_raster': op_upright_raster,
    'v2_tracking_raster': op_tracking_raster,
    'v2_not_stretched_raster': op_not_stretched_raster,
})
