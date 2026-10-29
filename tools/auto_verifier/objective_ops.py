"""Deterministic checks moved from human review (pilot-13 v2, 2026-10-27).

Every operation returns (status, evidence). Status is "pass", "fail" or "person": "person" means the code could not
decide (text it could not read, an element it could not find, a near miss that could be a misreading), so a person
answers that row. Nothing passes on a failed read.

Tools are pinned: Tesseract 5.5.3 (eng), opencv-python-headless 5.0.0.93, PyMuPDF 2.0. Settings are fixed constants
below, so the same file always gets the same answer.
"""
from __future__ import annotations

import csv
import difflib
import functools
import io
import re
import subprocess
import tempfile
import unicodedata
from datetime import date
from pathlib import Path

import ctypes.util

import numpy as np
from PIL import Image, ImageOps

_find_library = ctypes.util.find_library
_homebrew_cairo = Path('/opt/homebrew/lib/libcairo.2.dylib')
if _homebrew_cairo.exists() and not _find_library('cairo'):
    ctypes.util.find_library = lambda name: str(_homebrew_cairo) if 'cairo' in name else _find_library(name)

PERSON = 'person'
OCR_PSMS = (11, 3)            # sparse text finds isolated words; automatic layout keeps lines together
OCR_MIN_CONF = 60             # words below this are noise (photo texture read as letters)
OCR_GOOD_CONF = 80            # a read this confident can support a fail or an absence
OCR_SCALE = 2                 # upscale before OCR so fine print is read reliably
NEAR_MISS = 0.8               # a window this similar to the expected text may be a misreading: a person decides
SIZE_MARGIN = 0.08            # text sizes closer than 8% are too close for code to call
RENDER_DPI = 150

# ---------------------------------------------------------------- text normalisation

DASHES = dict.fromkeys(map(ord, '‐‑‒–—―−'), '-')
QUOTES = {ord('‘'): "'", ord('’'): "'", ord('“'): '"', ord('”'): '"', ord(' '): ' '}


def canon(text: str, case: bool = True) -> str:
    text = unicodedata.normalize('NFKC', text).translate(DASHES).translate(QUOTES)
    text = re.sub(r'\s+', ' ', text).strip()
    return text if case else text.casefold()


def squash(text: str) -> str:
    """Letter-spaced type ("T H O R N M E R E") reads the same once spaces are removed."""
    return re.sub(r'\s+', '', text)


def contains(haystack: str, needle: str, case: bool, spaced: bool = True) -> bool:
    h, n = canon(haystack, case), canon(needle, case)
    if not n:
        return False
    # a word boundary only where the needle starts or ends with a letter or digit: "&nbsp;" is found in "8:00&nbsp;PM"
    lead = r'(?<![\w])' if re.match(r'\w', n) else ''
    trail = r'(?![\w])' if re.search(r'\w$', n) else ''
    if re.search(lead + re.escape(n) + trail, h):
        return True
    if not spaced:
        return False
    # letter-spaced type only: runs of single letters separated by spaces
    runs = re.findall(r'(?:\b\w\b ){3,}\b\w\b', h)
    return any(squash(n) in squash(run) for run in runs) and len(squash(n)) >= 4


def near_miss(haystack: str, needle: str) -> float:
    """Best similarity between the needle and any window of words of about its length."""
    words, target = canon(haystack, False).split(), canon(needle, False)
    size = max(1, len(target.split()))
    best = 0.0
    for width in (size - 1, size, size + 1):
        if width < 1:
            continue
        for i in range(0, max(1, len(words) - width + 1)):
            best = max(best, difflib.SequenceMatcher(None, ' '.join(words[i:i + width]), target).ratio())
    return best

# ---------------------------------------------------------------- text layers


class Line:
    __slots__ = ('text', 'bbox', 'size', 'conf', 'fonts', 'colors', 'page', 'source', 'size_ok')

    def __init__(self, text, bbox, size, conf=100.0, fonts=(), colors=(), page=0, source='pdf'):
        self.text, self.bbox, self.size, self.conf = text, bbox, size, conf
        self.fonts, self.colors, self.page, self.source = list(fonts), list(colors), page, source
        self.size_ok = True          # False when letter height could not be measured (OCR only)


class Layer:
    """All text of a deliverable as lines with position, size and, for live text, font and colour."""

    def __init__(self, lines, source, readable=True, width=0, height=0):
        self.lines, self.source, self.readable, self.width, self.height = lines, source, readable, width, height

    @property
    def text(self):
        return ' '.join(l.text for l in self.lines)

    @property
    def confident(self):
        """OCR read the deliverable well enough to support a fail or an absence: every line that could carry
        wording (three letters or digits, or any digit, currency sign or @) was read confidently. Specks of one or
        two letters picked out of a photograph cannot hide a phrase, price or address, so they do not count."""
        if self.source == 'pdf':
            return True
        wording = [l for l in self.lines if len(re.findall(r'[A-Za-z0-9]', l.text)) >= 3 or re.search(r'[\d$€£@]', l.text)]
        return bool(wording) and all(l.conf >= OCR_GOOD_CONF for l in wording)


def _letter_ratio(word: str) -> float:
    """Box height divided by cap height, from which letters a word has."""
    up = bool(re.search(r'[A-Z0-9bdfhklt&?!]', word))
    down = bool(re.search(r'[gjpqy,;]', word))
    if up and down:
        return 1.28
    if up:
        return 1.0
    return 1.28 if down else 0.72


def _tesseract(image: Image.Image, psm: int, scale: float = OCR_SCALE):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / 'in.png'
        image.save(src)
        out = subprocess.run(['tesseract', str(src), 'stdout', '--psm', str(psm), '-l', 'eng', 'tsv'],
                             capture_output=True, timeout=180)
        if out.returncode:
            raise RuntimeError(out.stderr.decode(errors='replace')[-300:])
        rows = list(csv.DictReader(io.StringIO(out.stdout.decode('utf-8', errors='replace')), delimiter='\t',
                                   quoting=csv.QUOTE_NONE))
    words = []
    for r in rows:
        text = (r.get('text') or '').strip()
        try:
            conf = float(r['conf'])
        except (TypeError, ValueError):
            continue
        if text and conf >= OCR_MIN_CONF:
            x, y, w, h = (int(r[k]) / scale for k in ('left', 'top', 'width', 'height'))
            words.append(dict(text=text, conf=conf, bbox=(x, y, x + w, y + h),
                              line=(scale, psm, r['block_num'], r['par_num'], r['line_num'])))
    return words


def _overlap(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1
    return inter / small


@functools.lru_cache(maxsize=64)
def ocr_layer_cached(key: str) -> Layer:
    image = Image.open(Path(key))
    if image.mode in ('RGBA', 'LA', 'P'):
        # a transparent surround (sticker proofs) reads as white paper, not as whatever colour hides under alpha
        rgba = image.convert('RGBA')
        image = Image.alpha_composite(Image.new('RGBA', rgba.size, (255, 255, 255, 255)), rgba)
    return ocr_image(image.convert('RGB'))


OCR_EXTRA_SCALES = (1, 0.5)    # display type far larger than body text is read best without enlarging


def _alnum(text: str) -> int:
    return len(re.findall(r'[A-Za-z0-9]', text))


def _ocr_lines(image: Image.Image, scale: float, psms) -> list:
    width, height = image.size
    im = image if scale == 1 else image.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.LANCZOS)
    gray = ImageOps.grayscale(im)
    words = []
    for candidate in (gray, ImageOps.invert(gray)):
        for psm in psms:
            for w in _tesseract(candidate, psm, scale):
                if not any(_overlap(w['bbox'], o['bbox']) > 0.5 for o in words):
                    words.append(w)
    # group words into lines by Tesseract's own line ids
    groups = {}
    for w in words:
        groups.setdefault(w['line'], []).append(w)
    lines = []
    for ws in groups.values():
        ws.sort(key=lambda w: w['bbox'][0])
        text = ' '.join(w['text'] for w in ws)
        box = (min(w['bbox'][0] for w in ws), min(w['bbox'][1] for w in ws), max(w['bbox'][2] for w in ws), max(w['bbox'][3] for w in ws))
        caps = sorted((w['bbox'][3] - w['bbox'][1]) / _letter_ratio(w['text']) for w in ws)
        lines.append(Line(text, box, caps[len(caps) // 2], min(w['conf'] for w in ws), source='ocr'))
    return lines


def ocr_image(image: Image.Image) -> Layer:
    """Read at 2x (fine print), then at 1x and 0.5x (display type); where readings of the same area differ, the one
    recovering more letters and figures wins, provided it was read about as confidently."""
    width, height = image.size
    lines = _ocr_lines(image, OCR_SCALE, OCR_PSMS)
    for scale in OCR_EXTRA_SCALES:
        for l in _ocr_lines(image, scale, (11,)):
            over = [k for k in lines if _overlap(k.bbox, l.bbox) > 0.3]
            if not over:
                if l.conf >= OCR_GOOD_CONF and _alnum(l.text) >= 2:
                    lines.append(l)
            elif _alnum(l.text) > sum(_alnum(k.text) for k in over) and l.conf >= min(k.conf for k in over) - 5:
                lines = [k for k in lines if k not in over] + [l]
    lines.sort(key=lambda l: (round(l.bbox[1] / 4), l.bbox[0]))
    layer = Layer(lines, 'ocr', readable=bool(lines), width=width, height=height)
    gray_small = np.asarray(ImageOps.grayscale(image))
    for l in lines:
        measured = cap_height(gray_small, l.bbox, l.text)
        if measured:
            l.size = measured
        else:
            l.size_ok = False
    return layer


def cap_height(gray: np.ndarray, bbox, text: str = '') -> float | None:
    """Height of the tall letters (capitals and ascenders) standing on the line's baseline, measured in pixels.

    Letters are separated as ink blobs; those sitting on the baseline are kept. Where tall blobs stand out from the
    x-height ones, the second tallest is taken (one stray blob cannot inflate it, and a short "t" cannot shrink it).
    A line set in capitals or figures is all tall. A line of x-height letters only ("summer") has no tall letter to
    measure, so its size is unknown and comparisons that need it go to a person."""
    import cv2
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    pad = max(2, (y1 - y0) // 4)
    crop = gray[max(0, y0 - pad):min(gray.shape[0], y1 + pad), max(0, x0 - 2):min(gray.shape[1], x1 + 2)]
    if crop.size == 0 or crop.shape[0] < 4:
        return None
    _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if ink.mean() > 127:
        ink = 255 - ink                      # light text on a dark ground
    n, _, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    comps = [stats[i] for i in range(1, n) if stats[i][cv2.CC_STAT_AREA] >= 4 and stats[i][cv2.CC_STAT_HEIGHT] >= 3]
    if len(comps) < 2:
        return None
    bottoms = np.array([c[cv2.CC_STAT_TOP] + c[cv2.CC_STAT_HEIGHT] for c in comps])
    base = float(np.median(bottoms))
    tol = max(1.5, 0.08 * (y1 - y0))
    heights = np.array([c[cv2.CC_STAT_HEIGHT] for c, b in zip(comps, bottoms) if abs(b - base) <= tol], float)
    if not len(heights):
        return None
    hs = np.sort(heights[heights >= 0.35 * heights.max()])      # punctuation and specks are not letters
    # the commonest height: x-height in running text, cap height in a line set in capitals
    counts = [int(np.sum(np.abs(hs - h) <= max(1.0, 0.04 * h))) for h in hs]
    common = float(hs[int(np.argmax(counts))])
    tall = hs[hs >= 1.18 * common]
    if len(tall):                                                   # capitals and ascenders above the x-height
        return float(tall[-2] if len(tall) >= 2 else tall[-1])
    # one height class: tall if the line has capitals, figures or ascenders, else x-height only (unknown)
    if re.search(r'[A-Z0-9bdfhklt]', text):
        return float(np.median(hs))
    return None


def _hex(color) -> str:
    if isinstance(color, int):
        return '#%06X' % color
    return '#%02X%02X%02X' % tuple(int(round(max(0.0, min(1.0, c)) * 255)) for c in color[:3])


@functools.lru_cache(maxsize=32)
def pdf_layer(key: str) -> Layer:
    import pymupdf
    doc = pymupdf.open(key)
    lines = []
    for page in doc:
        for block in page.get_text('dict')['blocks']:
            for line in block.get('lines', []):
                spans = [s for s in line['spans'] if s['text'].strip()]
                if not spans:
                    continue
                text = ''.join(s['text'] for s in line['spans']).strip()
                x0 = min(s['bbox'][0] for s in spans); y0 = min(s['bbox'][1] for s in spans)
                x1 = max(s['bbox'][2] for s in spans); y1 = max(s['bbox'][3] for s in spans)
                lines.append(Line(text, (x0, y0, x1, y1), max(s['size'] for s in spans),
                                  fonts=[(s['text'], s['font'], round(s['size'], 2), _hex(s['color'])) for s in spans],
                                  colors=[_hex(s['color']) for s in spans], page=page.number, source='pdf'))
    first = doc[0].rect if len(doc) else None
    layer = Layer(lines, 'pdf', readable=bool(lines), width=first.width if first else 0, height=first.height if first else 0)
    layer.pages = len(doc)
    return layer


def render_pdf(path: Path, page: int = 0, dpi: int = RENDER_DPI) -> Image.Image:
    import pymupdf
    doc = pymupdf.open(path)
    pix = doc[page].get_pixmap(dpi=dpi)
    return Image.frombytes('RGB', (pix.width, pix.height), pix.samples)


@functools.lru_cache(maxsize=8)
def video_frames(key: str, fps: float = 1.0):
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(['ffmpeg', '-v', 'error', '-i', key, '-vf', f'fps={fps}', str(Path(tmp) / 'f%04d.png')], check=True, timeout=600)
        return tuple(Image.open(p).convert('RGB').copy() for p in sorted(Path(tmp).glob('f*.png')))


def text_layers(path: Path):
    """The text of a deliverable: live PDF text where there is any, OCR otherwise. Video gives one layer per frame."""
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        layer = pdf_layer(str(path))
        if layer.readable:
            return [layer]
        import pymupdf
        pages = len(pymupdf.open(path))
        return [ocr_image(render_pdf(path, p, 200)) for p in range(pages)]
    if suffix in ('.png', '.jpg', '.jpeg'):
        return [ocr_layer_cached(str(path))]
    if suffix == '.mp4':
        return [ocr_image(f) for f in video_frames(str(path))]
    if suffix == '.svg':
        # live <text> plus OCR of the render: type converted to outlines is only visible in the render
        from xml.etree import ElementTree as ET
        root = ET.fromstring(path.read_text())
        texts = [''.join(e.itertext()) for e in root.iter() if e.tag.split('}')[-1] == 'text']
        lines = [Line(t, (0, 0, 0, 0), 0, source='pdf') for t in texts if t.strip()]
        return [Layer(lines, 'pdf', readable=bool(lines)), ocr_image(svg_render(path).convert('RGB'))]
    raise ValueError(f'No text layer for {suffix}')


def svg_render(path: Path, width: int = 1600) -> Image.Image:
    """The SVG drawn on a white ground (transparent areas stay white), for OCR and pixel checks."""
    import cairosvg
    png = cairosvg.svg2png(url=str(path), output_width=width)
    img = Image.open(io.BytesIO(png)).convert('RGBA')
    return Image.alpha_composite(Image.new('RGBA', img.size, (255, 255, 255, 255)), img)


def merged(layers):
    lines = [l for layer in layers for l in layer.lines]
    # any OCR layer makes the whole reading OCR-grade: confidence rules then apply to every decision
    source = 'ocr' if any(layer.source == 'ocr' for layer in layers) else 'pdf'
    out = Layer(lines, source if layers else 'ocr', readable=any(l.readable for l in layers),
                width=layers[0].width if layers else 0, height=layers[0].height if layers else 0)
    out.confident_all = all(l.confident for l in layers) if layers else False
    return out

# ---------------------------------------------------------------- operations


def _match(hay: str, item, case: bool) -> bool:
    """An expected item is plain text, or {"regex": ...} for the forms a check allows ("25 SEP", "SEP 25").
    A pattern describes forms of a value (a date, a time, a figure beside "sleeps"), so it ignores letter case."""
    if isinstance(item, dict):
        return re.search(item['regex'], canon(hay), re.I) is not None
    return contains(hay, item, case)


def _forbidden_hit(hay: str, item) -> bool:
    """A forbidden text is found where it stands on its own. {"text": X, "outside": [E]} ignores X inside E
    ("Meridian Certified" inside "Meridian Certified Plus"); letter-spaced runs never count as a run-together word."""
    if isinstance(item, dict) and 'text' in item:
        h = canon(hay, False)
        for e in item.get('outside', []):
            h = h.replace(canon(e, False), ' | ')
        return contains(h, item['text'], False, spaced=False)
    if isinstance(item, dict):
        return _match(hay, item, False)
    return contains(hay, item, False, spaced=False)


def _label(item):
    if isinstance(item, dict):
        return item.get('regex') or item.get('text')
    return item


def op_text_present(path, a):
    """Each expected item appears (an item may list alternatives). Forbidden items must not appear.

    line_has: only lines containing this keyword count ("sleeps", "standing"); with optional, no such line is a pass.
    if_any: the check applies only where this pattern appears; otherwise it passes.
    whole_line: some line must read exactly the expected text, with nothing added.
    """
    layer = merged(text_layers(path))
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    case = not a.get('any_case', False)
    lines = layer.lines
    if a.get('line_has'):
        lines = [l for l in lines if re.search(a['line_has'], canon(l.text), re.I)]
        if not lines:
            if a.get('optional') and (layer.source == 'pdf' or layer.confident):
                return 'pass', {'reason': 'field not shown (the check applies only where it appears)'}
            return PERSON, {'reason': f'no line with {a["line_has"]!r} read'}
    hay = ' '.join(l.text for l in lines)
    if layer.source == 'ocr':
        clean = ' '.join(l.text for l in lines if _real(l))
        hay = clean + ' \n ' + hay if clean != hay else hay
    if a.get('if_any') and not re.search(a['if_any'], canon(hay), re.I):
        if layer.source == 'pdf' or layer.confident:
            return 'pass', {'reason': 'not shown (the check applies only where it appears)'}
        return PERSON, {'reason': 'could not rule out that it appears'}
    forbidden = [_label(f) for f in a.get('forbidden', []) if _forbidden_hit(hay, f)]
    if forbidden:
        if layer.source == 'ocr' and not any(l.conf >= OCR_GOOD_CONF and any(_forbidden_hit(l.text, f) for f in a['forbidden']) for l in lines):
            return PERSON, {'reason': 'forbidden text read with low confidence', 'found': forbidden}
        return 'fail', {'forbidden_found': forbidden}
    missing = []
    for options in a['expected']:
        options = options if isinstance(options, list) else [options]
        if not any(_match(hay, o, case) for o in options):
            missing.append([_label(o) for o in options])
    if not missing and a.get('whole_line'):
        target = [canon(_label(o if not isinstance(o, list) else o[0]), False) for o in a['expected']]
        if not any(canon(l.text, False).strip(' .,') in target for l in lines):
            return 'fail' if layer.source == 'pdf' or layer.confident else PERSON, {'reason': 'the line carries more than the expected text'}
    if not missing:
        return 'pass', {'found': [_label(o) if not isinstance(o, list) else [_label(x) for x in o] for o in a['expected']]}
    plain = [o for opts in missing for o in opts if not o.startswith('(?') and not re.search(r'[\\\[\]()?*+|]', o)]
    # the same words in another letter case (SPRING for Spring) are for a person to judge, never a fail,
    # unless the check is about letter case itself ("in sentence case, not in capitals")
    if plain and not a.get('case_matters') and all(any(contains(hay, o, False) for o in opts) for opts in missing):
        return PERSON, {'reason': 'found with different letter case', 'missing': missing}
    if layer.source == 'pdf':
        return 'fail', {'missing': missing}
    # OCR: a near miss could be a misreading or a real typo, so a person decides; only a clear read can fail
    near = max((near_miss(hay, o) for o in plain), default=0.0)
    if near >= NEAR_MISS or not layer.confident or len(plain) < sum(len(m) for m in missing):
        return PERSON, {'reason': 'not read clearly', 'similarity': round(near, 2), 'missing': missing}
    return 'fail', {'missing': missing, 'similarity': round(near, 2)}


def op_text_absent(path, a):
    """None of the listed texts or patterns appears."""
    layer = merged(text_layers(path))
    if not layer.readable:
        return (PERSON, {'reason': 'no readable text'}) if layer.source != 'pdf' else ('pass', {'reason': 'no text'})
    hay = layer.text
    found = [t for t in a.get('texts', []) if contains(hay, t, False)]
    for name, rx in a.get('patterns', {}).items():
        for m in re.finditer(rx, canon(hay), re.I):
            value = m.group(0)
            if not any(re.fullmatch(allow, value, re.I) for allow in a.get('allow', [])):
                found.append(f'{name}: {value}')
    if found:
        if layer.source == 'ocr':
            strong = [l for l in layer.lines if any(contains(l.text, f.split(': ', 1)[-1], False) for f in found) and l.conf >= OCR_GOOD_CONF]
            if not strong:
                return PERSON, {'reason': 'possible match read with low confidence', 'found': found}
        if a.get('found_is') == PERSON:
            # the words appear, but whether they make an entry or offer (rather than a note) is a person's call
            lines = [l.text for l in layer.lines if any(contains(l.text, f.split(': ', 1)[-1], False) for f in found)]
            return PERSON, {'reason': 'mentioned; a person decides whether this is an entry or offer', 'lines': lines[:3]}
        return 'fail', {'found': found}
    if layer.source == 'ocr' and not layer.confident:
        return PERSON, {'reason': 'text not read clearly enough to rule it out'}
    return 'pass', {'checked': a.get('texts', []) + list(a.get('patterns', {}))}


PRICE = r'(?:[$€£]\s?\d[\d,]*(?:\.\d{2})?(?:\s?(?:-|\bto\b)\s?[$€£]?\d[\d,]*)?)'   # a band may read "-" or "to"


def op_prices(path, a):
    """Every price shown meets the rule: none at all, only the listed values, or inside a range."""
    layer = merged(text_layers(path))
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    prices = re.findall(PRICE, canon(layer.text))
    bad = []
    for p in prices:
        flat = re.sub(r'\s*\bto\b\s*', '-', p).replace(' ', '')
        if a['mode'] == 'none':
            bad.append(p)
        elif a['mode'] == 'only' and not any(flat == v.replace(' ', '') for v in a['allowed']):
            bad.append(p)
        elif a['mode'] == 'range':
            nums = [float(n.replace(',', '')) for n in re.findall(r'\d[\d,]*(?:\.\d+)?', flat)]
            if any(n < a['min'] or n > a['max'] for n in nums):
                bad.append(p)
    if bad:
        if layer.source == 'ocr' and not layer.confident:
            return PERSON, {'reason': 'prices read with low confidence', 'found': bad}
        return 'fail', {'prices': prices, 'not_allowed': bad}
    if layer.source == 'ocr' and not layer.confident:
        return PERSON, {'reason': 'text not read clearly enough', 'prices': prices}
    return 'pass', {'prices': prices}


def _font_parts(name: str):
    name = name.split('+', 1)[-1]
    family, _, style = name.partition('-')
    if not style:
        m = re.match(r'(.+?)(MT|PS)?$', family)
        family, style = m.group(1), 'Regular'
    style = re.sub(r'(?i)italic|oblique', ' Italic', style)
    norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    return norm(family), norm(style) or 'regular'


def _occurrences(layer: Layer, text: str):
    """Lines (PDF) whose text contains the given text, letter case ignored."""
    return [l for l in layer.lines if contains(l.text, text, False)]


def _select(layer, a):
    """The lines a style check is about: named texts, lines matching patterns, or all text except named ones."""
    picks = []
    for text in a.get('texts', []):
        hits = _occurrences(layer, text)
        if not hits and not a.get('optional'):
            return None, text
        picks += [(text, l) for l in hits]
    for rx in a.get('patterns', []):
        hits = [l for l in layer.lines if re.search(rx, canon(l.text), re.I)]
        if not hits and not a.get('optional'):
            return None, rx
        picks += [(None, l) for l in hits]
    if a.get('all_text'):
        for l in layer.lines:
            if any(contains(l.text, e, False) for e in a.get('except', [])):
                continue
            if any(re.search(rx, canon(l.text), re.I) for rx in a.get('except_patterns', [])):
                continue
            picks.append((None, l))
    return picks, None


def op_pdf_text_style(path, a):
    """Every occurrence of the selected text is set in the family and weight, at the size, in capitals or in the colour."""
    layer = pdf_layer(str(path))
    if not layer.readable:
        return PERSON, {'reason': 'no live text (lettering may be outlined)'}
    picks, missing = _select(layer, a)
    if picks is None:
        return PERSON, {'reason': f'text not found: {missing}'}
    if not picks:
        return 'pass', {'reason': 'none present (the check applies only where they appear)'}
    bad = []
    for text, line in picks:
        spans = line.fonts
        if text:
            spans = [s for s in line.fonts if s[0].strip() and (contains(text, s[0], False) or contains(s[0], text, False)
                                                                 or len(squash(s[0])) <= 2)] or line.fonts
        for s_text, font, size, color in spans:
            fam, style = _font_parts(font)
            if 'family' in a and fam != re.sub(r'[^a-z0-9]', '', a['family'].lower()):
                bad.append((s_text, font))
            elif 'weight' in a and style != re.sub(r'[^a-z0-9]', '', a['weight'].lower()):
                bad.append((s_text, font))
            elif 'size' in a and abs(size - a['size']) > a.get('tolerance', 0.1):
                bad.append((s_text, size))
            elif 'colors' in a and not _near_hex(color, a['colors'], 2):
                bad.append((s_text, color))
        if a.get('caps') and re.search(r'[a-z]', _segment(line.text, text) if text else line.text):
            bad.append((line.text, 'lowercase'))
    return ('fail', {'not_matching': bad[:12]}) if bad else ('pass', {'occurrences': len(picks)})


def _segment(line_text: str, text: str) -> str:
    """The part of a line that is the named text (case ignored)."""
    i = canon(line_text, False).find(canon(text, False))
    return canon(line_text)[i:i + len(canon(text))] if i >= 0 else line_text


def _real(line) -> bool:
    """A line worth comparing: live text, or OCR read confidently with at least three letters or digits."""
    return line.source == 'pdf' or (line.conf >= OCR_GOOD_CONF and len(re.findall(r'[A-Za-z0-9]', line.text)) >= 3)


def _span(layer, text, max_lines=4):
    """Consecutive lines that together read the text (a heading set over several lines), junk OCR left out."""
    lines = [l for l in layer.lines if _real(l)]
    for n in range(2, max_lines + 1):
        for i in range(len(lines) - n + 1):
            window = lines[i:i + n]
            joined = ' '.join(l.text for l in window)
            if contains(joined, text, False) and not contains(' '.join(l.text for l in window[1:]), text, False) \
                    and not contains(' '.join(l.text for l in window[:-1]), text, False):
                return window
    return []


def _cap_size(layer, text):
    """Size of the text where it is largest; a heading over several lines counts at its smallest line."""
    hits = [l for l in layer.lines if contains(l.text, text, False)]
    if hits:
        return max(l.size for l in hits), hits
    span = _span(layer, text)
    return (min(l.size for l in span), span) if span else (None, [])


def op_largest_text(path, a):
    layers = text_layers(path)
    layer = merged(layers if 'page' not in a or path.suffix.lower() != '.pdf' else layers)
    if 'page' in a and layer.source == 'pdf':
        layer = Layer([l for l in layer.lines if l.page == a['page'] - 1], 'pdf', width=layer.width, height=layer.height)
    size, hits = _cap_size(layer, a['text'])
    if size is None:
        return PERSON, {'reason': f'text not found: {a["text"]}'}
    if not all(l.size_ok for l in hits):
        return PERSON, {'reason': 'letter height of the text could not be measured', 'text': a['text']}
    def bare(text):
        return re.sub(r'[^0-9a-z]', '', canon(text, False))

    def excepted(line):
        # the excepted text, or a piece of it read as a line of its own ("UMBRA /" and "LOFT", or "UMBRA LOFT" with
        # the slash unread, for "UMBRA / LOFT"); punctuation is ignored in this comparison
        piece = bare(line.text)
        return any(contains(line.text, e, False) or (len(piece) >= 3 and piece in bare(e)) for e in a.get('except', []))
    others = [l for l in layer.lines if l not in hits and _real(l) and not excepted(l)]
    unsure = [l for l in others if not l.size_ok and l.size >= size * 0.8]
    if unsure:
        return PERSON, {'reason': 'another line\'s letter height could not be measured', 'other': unsure[0].text}
    biggest = max(others, key=lambda l: l.size, default=None)
    if biggest is None or size >= biggest.size * (1 + (SIZE_MARGIN if layer.source == 'ocr' else 0)):
        return 'pass', {'size': round(size, 1), 'next_largest': round(biggest.size, 1) if biggest else None}
    if layer.source == 'ocr' and size >= biggest.size * (1 - SIZE_MARGIN):
        return PERSON, {'reason': 'sizes too close to call from pixels', 'size': round(size, 1), 'other': biggest.text}
    if layer.source == 'pdf' and size >= biggest.size - 0.01:
        return 'pass', {'size': size, 'tied_with': biggest.text}
    return 'fail', {'size': round(size, 1), 'larger': biggest.text, 'larger_size': round(biggest.size, 1)}


def op_relation(path, a):
    """A sits above B, or A is set larger / smaller than every B. With several A texts, each must hold."""
    if isinstance(a['a'], list):
        results = [op_relation(path, dict(a, a=one)) for one in a['a']]
        for status in ('fail', PERSON):
            for st, ev in results:
                if st == status:
                    return st, ev
        return 'pass', {'checked': a['a']}
    layer = merged(text_layers(path))
    sa, ha = _cap_size(layer, a['a'])
    bs = [_cap_size(layer, b) for b in a['b']]
    if sa is None or any(s is None for s, _ in bs):
        return (PERSON, {'reason': 'text not found'}) if not a.get('optional') or sa is not None else ('pass', {'reason': 'not present'})
    margin = SIZE_MARGIN if layer.source == 'ocr' else 0.01
    if a['rel'] in ('larger', 'smaller') and not all(l.size_ok for l in ha + [l for _, hb in bs for l in hb]):
        return PERSON, {'reason': 'letter height could not be measured on every line compared'}
    if a['rel'] in ('larger', 'smaller'):
        for sb, hb in bs:
            ratio = sa / sb if sb else 99
            ok = ratio > 1 + margin if a['rel'] == 'larger' else ratio < 1 - margin
            close = abs(ratio - 1) <= margin
            if not ok:
                return (PERSON if close and layer.source == 'ocr' else 'fail'), {'a': round(sa, 1), 'b': round(sb, 1)}
        return 'pass', {'a': round(sa, 1), 'b': [round(s, 1) for s, _ in bs]}
    top_a = min(l.bbox[1] for l in ha)
    for sb, hb in bs:
        top_b = min(l.bbox[1] for l in hb)
        if a['rel'] == 'above' and not top_a < top_b:
            return 'fail', {'a_top': top_a, 'b_top': top_b}
        if a['rel'] == 'below' and not top_a > top_b:
            return 'fail', {'a_top': top_a, 'b_top': top_b}
    return 'pass', {'a_top': round(top_a, 1)}


def op_text_inside(path, a):
    """Each named text is read in full and its box lies inside the page or image.
    whole_line: only a line reading exactly the text counts (a mark's letters standing on their own)."""
    layers = text_layers(path)
    layer = merged(layers)
    for text in a['texts']:
        if a.get('whole_line'):
            hits = [l for l in layer.lines if squash(l.text).lower() == squash(text).lower() and (l.source == 'pdf' or l.conf >= OCR_GOOD_CONF)]
        else:
            hits = [l for l in layer.lines if contains(l.text, text, False)]
        if not hits:
            return PERSON, {'reason': f'not read in full: {text}'}
        for l in hits:
            x0, y0, x1, y1 = l.bbox
            if x0 < 0.5 or y0 < 0.5 or x1 > layer.width - 0.5 or y1 > layer.height - 0.5:
                return 'fail', {'text': text, 'bbox': l.bbox}
    return 'pass', {'texts': a['texts']}


def op_line_count(path, a):
    """The named text runs over no more than the stated number of lines."""
    layer = merged(text_layers(path))
    words = canon(a['text'], False).split()
    rows = [l for l in layer.lines if any(contains(l.text, w, False) for w in words)]
    if not rows:
        return (PERSON, {'reason': 'text not found'}) if not a.get('optional') else ('pass', {'reason': 'not present'})
    whole = [l for l in rows if contains(l.text, a['text'], False)]
    if whole:
        return 'pass', {'lines': 1}
    joined = ' '.join(l.text for l in rows)
    if contains(joined, a['text'], False) and len(rows) <= a['max_lines']:
        return 'pass', {'lines': len(rows)}
    return ('fail' if layer.source == 'pdf' else PERSON), {'lines': len(rows)}


def op_order(path, a):
    """The named texts appear in this reading order (top to bottom, then left to right)."""
    layer = merged(text_layers(path))
    pos = []
    for t in a['texts']:
        hits = [l for l in layer.lines if contains(l.text, t, False)]
        if not hits:
            return PERSON, {'reason': f'not found: {t}'}
        l = min(hits, key=lambda l: (l.page, l.bbox[1], l.bbox[0]))
        pos.append((l.page, round(l.bbox[1]), l.bbox[0]))
    return ('pass', {'order': a['texts']}) if pos == sorted(pos) else ('fail', {'positions': pos})


def op_weekdays(path, a):
    """Every weekday shown beside a date is correct for the year.

    A weekday pairs with the date right after it ("FRI 25 SEP"), or with the date right before it ("25 SEP, FRI",
    "25 SEP (FRI)"), never across a slash or dash that separates two entries ("SAT 3 OCT / SUN 4 OCT"). Pairs are read
    within a line, plus a weekday standing alone on the line above its date.
    """
    layer = merged(text_layers(path))
    months = {m: i for i, m in enumerate(['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'], 1)}
    days = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN']
    wd_rx = r'(MON|TUE|WED|THU|FRI|SAT|SUN)[A-Z]*\.?'
    date_rx = r'(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.?'
    texts = [(canon(l.text).upper(), l) for l in layer.lines]
    units = list(texts)
    for (t1, l1), (t2, l2) in zip(texts, texts[1:]):
        if re.fullmatch(wd_rx, t1.strip(' ,.')) and re.match(date_rx, t2):
            units.append((t1 + ' ' + t2, l1))
    wrong, low, seen = [], [], 0
    for text, line in units:
        used = []
        pairs = []
        for m in re.finditer(r'\b' + wd_rx + r',?\s*' + date_rx, text):
            pairs.append((m.group(0), m.group(1), m.group(2), m.group(3)))
            used.append(m.span())
        for m in re.finditer(r'\b' + date_rx + r'(?:,\s*|\s+|\s*\(\s*)' + wd_rx, text):
            if any(a0 < m.end() and m.start() < a1 for a0, a1 in used):
                continue
            pairs.append((m.group(0), m.group(3), m.group(1), m.group(2)))
        for whole, wd, d, mo in pairs:
            seen += 1
            try:
                actual = days[date(a['year'], months[mo], int(d)).weekday()]
            except ValueError:
                continue
            if actual != wd:
                (low if line.source == 'ocr' and line.conf < OCR_GOOD_CONF else wrong).append(whole)
    if wrong:
        return 'fail', {'wrong': wrong}
    if low:
        return PERSON, {'reason': 'a weekday that looks wrong was read with low confidence', 'read': low}
    if not seen and layer.source == 'ocr' and not layer.confident:
        return PERSON, {'reason': 'no weekday read, and the text was not read clearly enough to rule one out'}
    return 'pass', {'weekdays_checked': seen}

# ---------------------------------------------------------------- colour from vector files


def _pdf_colours(path):
    import pymupdf
    doc = pymupdf.open(path)
    fills, text = [], []
    for page in doc:
        for d in page.get_drawings():
            for key in ('fill', 'color'):
                if d.get(key) is not None:
                    fills.append((_hex(d[key]), key, d.get('rect')))
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    if s['text'].strip():
                        text.append((_hex(s['color']), s['text']))
    return fills, text


def _near_hex(h, palette, tol=2):
    r, g, b = (int(h[i:i + 2], 16) for i in (1, 3, 5))
    for p in palette:
        pr, pg, pb = (int(p[i:i + 2], 16) for i in (1, 3, 5))
        if abs(r - pr) <= tol and abs(g - pg) <= tol and abs(b - pb) <= tol:
            return p
    return None


def op_palette_only(path, a):
    if path.suffix.lower() == '.svg':
        from xml.etree import ElementTree as ET
        root = ET.fromstring(path.read_text())
        used = set()
        for e in root.iter():
            for attr in ('fill', 'stroke'):
                v = e.get(attr)
                style = e.get('style') or ''
                m = re.search(rf'{attr}\s*:\s*(#[0-9A-Fa-f]{{3,6}})', style)
                v = m.group(1) if m else v
                if v and v.startswith('#'):
                    v = v.upper()
                    used.add('#' + ''.join(c * 2 for c in v[1:]) if len(v) == 4 else v)
        bad = sorted(u for u in used if not _near_hex(u, a['hexes'], 0))
        if bad:
            return 'fail', {'outside_palette': bad}
        if any(e.tag.split('}')[-1] == 'image' for e in root.iter()):
            return PERSON, {'reason': 'an embedded image: its colours are not fills or strokes', 'colours': sorted(used)}
        # colours set by a <style> sheet, by name, by gradient or by the default black fill only show in the render
        share, off = _svg_offpalette(path, a['hexes'])
        if share > 0.001:
            return 'fail', {'rendered_outside_palette': off, 'share_pct': round(share * 100, 2)}
        return 'pass', {'colours': sorted(used)}
    fills, text = _pdf_colours(path)
    used = {h for h, *_ in fills} | {h for h, _ in text}
    bad = sorted(u for u in used if not _near_hex(u, a['hexes']))
    return ('fail', {'outside_palette': bad}) if bad else ('pass', {'colours': sorted(used)})


def _svg_offpalette(path, hexes):
    """Share of solid interior pixels (3x3 neighbourhood opaque and one colour, so anti-aliased edges are left out)
    whose colour is not a palette hex, and the commonest such colours."""
    import cairosvg
    png = cairosvg.svg2png(url=str(path), output_width=900)
    arr = np.asarray(Image.open(io.BytesIO(png)).convert('RGBA')).astype(int)
    solid = arr[..., 3] == 255
    same = solid.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            same &= (np.abs(np.roll(np.roll(arr, dy, 0), dx, 1) - arr) <= 2).all(axis=2)
    px = arr[same][:, :3]
    if not len(px):
        return 0.0, []
    ok = np.zeros(len(px), bool)
    for h in hexes:
        ok |= (np.abs(px - np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)])) <= 3).all(axis=1)
    bad = px[~ok]
    if not len(bad):
        return 0.0, []
    values, counts = np.unique(bad, axis=0, return_counts=True)
    top = ['#%02X%02X%02X' % tuple(v) for v in values[np.argsort(-counts)][:5]]
    return len(bad) / len(px), top


def op_colours_present(path, a):
    fills, text = _pdf_colours(path)
    used = {h for h, *_ in fills} | {h for h, _ in text}
    missing = [h for h in a['hexes'] if not any(_near_hex(u, [h]) for u in used)]
    return ('fail', {'missing': missing}) if missing else ('pass', {'present': a['hexes']})


def _flat_pixels(path, page=0):
    """Rendered page with placed images blanked out, so only type and shapes are counted."""
    import pymupdf
    doc = pymupdf.open(path)
    pg = doc[page]
    img = render_pdf(path, page, 72)
    arr = np.asarray(img).copy()
    mask = np.ones(arr.shape[:2], bool)
    sx, sy = arr.shape[1] / pg.rect.width, arr.shape[0] / pg.rect.height
    for info in pg.get_image_info():
        x0, y0, x1, y1 = info['bbox']
        mask[max(0, int(y0 * sy)):int(y1 * sy) + 1, max(0, int(x0 * sx)):int(x1 * sx) + 1] = False
    return arr, mask, len(doc)


def op_main_ground(path, a):
    import pymupdf
    pages = len(pymupdf.open(path))
    wrong = []
    for p in range(pages):
        arr, mask, _ = _flat_pixels(path, p)
        px = arr[mask]
        if not len(px):
            continue
        values, counts = np.unique(px.reshape(-1, 3), axis=0, return_counts=True)
        top = '#%02X%02X%02X' % tuple(values[counts.argmax()])
        if not _near_hex(top, [a['hex']], 3):
            wrong.append((p + 1, top))
    return ('fail', {'pages': wrong}) if wrong else ('pass', {'hex': a['hex']})


def op_area_share(path, a):
    import pymupdf
    pages = len(pymupdf.open(path)) if path.suffix.lower() == '.pdf' else 1
    worst = 0.0
    for p in range(pages):
        if path.suffix.lower() == '.svg':
            import cairosvg
            png = cairosvg.svg2png(url=str(path), output_width=800)
            img = Image.open(io.BytesIO(png)).convert('RGBA')
            arr = np.asarray(img)
            mask = arr[..., 3] > 0
            arr = arr[..., :3]
        else:
            arr, mask, _ = _flat_pixels(path, p)
        px = arr[mask].reshape(-1, 3).astype(int)
        if not len(px):
            continue
        hit = np.zeros(len(px), bool)
        for h in a['hexes']:
            rgb = np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)])
            hit |= (np.abs(px - rgb) <= 3).all(axis=1)
        share = hit.mean() * 100
        if a.get('compare_hexes'):
            other = np.zeros(len(px), bool)
            for h in a['compare_hexes']:
                rgb = np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)])
                other |= (np.abs(px - rgb) <= 3).all(axis=1)
            if not hit.sum() > other.sum():
                return 'fail', {'page': p + 1, 'share': round(share, 2), 'compare_share': round(other.mean() * 100, 2)}
        worst = max(worst, share)
    if 'max_pct' in a and worst > a['max_pct']:
        return 'fail', {'share_pct': round(worst, 2)}
    return 'pass', {'share_pct': round(worst, 2)}

# ---------------------------------------------------------------- image matching


def _load_gray(path: Path, width: int | None = None):
    import cv2
    suffix = path.suffix.lower()
    if suffix == '.svg':
        import cairosvg
        png = cairosvg.svg2png(url=str(path), output_width=width or 900)
        img = Image.open(io.BytesIO(png)).convert('RGBA')
    elif suffix == '.pdf':
        img = render_pdf(path, 0, RENDER_DPI).convert('RGBA')
    else:
        img = Image.open(path).convert('RGBA')
    alpha = np.asarray(img)[..., 3]
    lum = np.asarray(img.convert('L'))
    opaque = lum[alpha > 128]
    # a light mark on a transparent ground would vanish on white, so it goes on black
    ground = (0, 0, 0, 255) if len(opaque) and opaque.mean() > 200 else (255, 255, 255, 255)
    flat = np.asarray(Image.alpha_composite(Image.new('RGBA', img.size, ground), img).convert('L'))
    if (alpha < 255).any():
        # a cutout is compared on its own pixels only: the ground behind it in a deliverable is not part of the file
        _ALPHA_MASKS[(flat.shape, hash(flat.tobytes()))] = alpha > 128
    return flat


_ALPHA_MASKS: dict = {}


_SIFT_CACHE: dict = {}
MATCH_NCC = 0.8           # a true placement correlates 0.93 to 1.0 with the supplied file; look-alikes stay under 0.45
MATCH_UNSURE_NCC = 0.5    # between the two, a person looks
MATCH_MIN_HULL = 0.05     # the matched points must cover at least 5% of the supplied file
MATCH_MIN_SCALE = 0.02    # a homography that squeezes the file to a speck is not a placement


def find_asset(scene_gray: np.ndarray, asset_gray: np.ndarray):
    """SIFT features plus a RANSAC homography, then a check that the matched area really looks like the file.
    Returns (inliers, corners, state) with state 'found', 'unsure' or 'none'."""
    key = (scene_gray.shape, hash(scene_gray.tobytes()), asset_gray.shape, hash(asset_gray.tobytes()))
    if key not in _SIFT_CACHE:
        _SIFT_CACHE[key] = _find_asset(scene_gray, asset_gray)
    return _SIFT_CACHE[key]


def _verify(scene, template, H, inlier_pts):
    """Normalised correlation between the file and the scene warped back onto it, inside the matched points' hull."""
    import cv2
    h, w = template.shape
    scale = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
    if abs(np.linalg.det(H)) < 1e-12:
        return 0.0, 0.0, scale                     # a degenerate homography is not a placement
    inv = np.linalg.inv(H)
    back = cv2.warpPerspective(scene, inv, (w, h), flags=cv2.INTER_AREA, borderValue=0)
    valid = cv2.warpPerspective(np.full(scene.shape, 255, np.uint8), inv, (w, h), flags=cv2.INTER_NEAREST, borderValue=0) > 0
    hull = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(hull, cv2.convexHull(inlier_pts.astype(np.int32)), 255)
    m = (hull > 0) & valid
    own = _ALPHA_MASKS.get((template.shape, hash(template.tobytes())))
    if own is None:
        own = _ALPHA_MASKS.get((template.shape, hash((255 - template).tobytes())))   # the inverted template
    if own is not None:
        m &= own
    share = float(m.sum()) / (h * w)
    if m.sum() < 100:
        return 0.0, share, scale
    a, b = template[m].astype(float), back[m].astype(float)
    a, b = a - a.mean(), b - b.mean()
    ncc = float((a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9))
    return ncc, share, scale


def _find_asset(scene_gray: np.ndarray, asset_gray: np.ndarray):
    import cv2
    cv2.setRNGSeed(0)
    sift = cv2.SIFT_create(nfeatures=5000)
    best = (0, None, 'none')
    rank = {'none': 0, 'unsure': 1, 'found': 2}
    ks, ds = sift.detectAndCompute(scene_gray, None)
    for template in (asset_gray, 255 - asset_gray):
        ka, da = sift.detectAndCompute(template, None)
        if da is None or ds is None or len(ka) < 8:
            continue
        matches = cv2.BFMatcher(cv2.NORM_L2).knnMatch(da, ds, k=2)
        good = [m for m, n in (p for p in matches if len(p) == 2) if m.distance < 0.75 * n.distance]
        if len(good) < 10:
            continue
        src = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([ks[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, inl = cv2.findHomography(src, dst, cv2.RANSAC, 4.0, maxIters=5000, confidence=0.999)
        if H is None:
            continue
        inl = inl.ravel().astype(bool)
        n = int(inl.sum())
        if n < MIN_INLIERS:
            continue
        ncc, share, scale = _verify(scene_gray, template, H, src.reshape(-1, 2)[inl])
        if scale < MATCH_MIN_SCALE or share < MATCH_MIN_HULL or ncc < MATCH_UNSURE_NCC:
            continue
        state = 'found' if ncc >= MATCH_NCC else 'unsure'
        if (rank[state], n) > (rank[best[2]], best[0]):
            h, w = template.shape
            corners = cv2.perspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2), H).reshape(-1, 2)
            best = (n, corners, state)
    return best


def _scenes(path: Path):
    suffix = path.suffix.lower()
    if suffix == '.mp4':
        return [np.asarray(ImageOps.grayscale(f)) for f in video_frames(str(path))]
    if suffix == '.pdf':
        import pymupdf
        n = len(pymupdf.open(path))
        return [np.asarray(ImageOps.grayscale(render_pdf(path, p, RENDER_DPI))) for p in range(n)]
    return [_load_gray(path)]


MIN_INLIERS = 15
FLAT_MIN_SCORE = 0.93     # template correlation for the supplied artwork itself; a 2% stretch already scores about 0.91
FLAT_MIN_WIDTH = 32


def _ink_crop(gray: np.ndarray, tol: int = 30) -> np.ndarray:
    ground = np.median(np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]]))
    ys, xs = np.where(np.abs(gray.astype(int) - ground) > tol)
    return gray[ys.min():ys.max() + 1, xs.min():xs.max() + 1] if len(ys) else gray


_FLAT_CACHE: dict = {}
FLAT_WORK_WIDTH = 240     # larger placements are matched on a reduced copy, which keeps every scale cheap


def find_flat(scene: np.ndarray, asset: np.ndarray, step: float = 1.03):
    """Multi-scale normalised correlation at the artwork's own proportions, either polarity.
    Returns (score, corners) for the best placement fully inside the scene."""
    import cv2
    key = (scene.shape, hash(scene.tobytes()), asset.shape, hash(asset.tobytes()))
    if key in _FLAT_CACHE:
        return _FLAT_CACHE[key]
    t0 = _ink_crop(asset)
    h0, w0 = t0.shape
    best = (-1.0, None)
    reduced = {}
    w = FLAT_MIN_WIDTH
    while w <= scene.shape[1] and round(w * h0 / w0) <= scene.shape[0]:
        f = max(1, int(w // FLAT_WORK_WIDTH))
        if f not in reduced:
            reduced[f] = scene if f == 1 else cv2.resize(scene, (scene.shape[1] // f, scene.shape[0] // f), interpolation=cv2.INTER_AREA)
        sc = reduced[f]
        tw, th = round(w / f), max(8, round(w * h0 / w0 / f))
        if tw <= sc.shape[1] and th <= sc.shape[0]:
            t = cv2.resize(t0, (tw, th), interpolation=cv2.INTER_AREA)
            if t.std() >= 1:
                r = cv2.matchTemplate(sc, t, cv2.TM_CCOEFF_NORMED)
                lo, hi, lo_at, hi_at = cv2.minMaxLoc(r)
                for score, (x, y) in ((hi, hi_at), (-lo, lo_at)):
                    if score > best[0]:
                        x, y, ww, hh = x * f, y * f, tw * f, th * f
                        best = (float(score), np.float32([[x, y], [x + ww, y], [x + ww, y + hh], [x, y + hh]]))
        w = max(w + 1, round(w * step))
    _FLAT_CACHE[key] = best
    return best


def _flat_asset(name: str) -> bool:
    return Path(name).suffix.lower() in ('.svg', '.pdf', '.ai', '.eps') or 'logo' in name or 'mark' in name


def _shape_ok(corners, asset_shape, tol=0.03):
    h, w = asset_shape
    top = np.linalg.norm(corners[1] - corners[0]); bottom = np.linalg.norm(corners[2] - corners[3])
    left = np.linalg.norm(corners[3] - corners[0]); right = np.linalg.norm(corners[2] - corners[1])
    if min(top, bottom, left, right) <= 1:
        return False, 0
    aspect = ((top + bottom) / 2) / ((left + right) / 2)
    change = abs(aspect / (w / h) - 1)
    parallel = abs(top - bottom) / max(top, bottom) <= tol and abs(left - right) / max(left, right) <= tol
    return change <= tol and parallel, round(change, 3)


def asset_path(a, name) -> Path:
    for d in a.get('_asset_dirs') or [a.get('_asset_dir')]:
        if d and (Path(d) / name).is_file():
            return Path(d) / name
    raise FileNotFoundError(f'supplied file not available locally: {name}')


def op_contains_asset(path, a):
    """One of the supplied files is found in the deliverable with its own proportions."""
    scenes = _scenes(path)
    best = None
    unsure = []
    for name in a['assets']:
        asset = _load_gray(asset_path(a, name))
        for i, scene in enumerate(scenes):
            n, corners, state = find_asset(scene, asset)
            if state == 'unsure':
                unsure.append((name, i))
            if state == 'found' and (best is None or n > best[0]):
                best = (n, name, i, corners, asset.shape)
    if best is None:
        for name in (n for n in a['assets'] if _flat_asset(n)):
            asset = _load_gray(asset_path(a, name), width=1600)
            for i, scene in enumerate(scenes):
                score, corners = find_flat(scene, asset)
                if score >= FLAT_MIN_SCORE and (best is None or score > best[0]):
                    best = (round(score, 3), name, i, corners, _ink_crop(asset).shape)
    if best is None and unsure:
        return PERSON, {'reason': 'a possible match that does not clearly look like the supplied file', 'where': unsure[:3]}
    if best is None:
        if a.get('optional'):
            return PERSON, {'reason': 'no supplied version found; a person checks whether a redrawn one is present'}
        return 'fail' if a.get('fail_if_absent') else PERSON, {'reason': 'supplied file not found'}
    n, name, i, corners, shape = best
    if a.get('shape', True):
        ok, change = _shape_ok(corners, shape)
        if not ok:
            return 'fail', {'asset': name, 'inliers': n, 'aspect_change': change}
    evidence = {'asset': name, 'inliers': n, 'frame_or_page': i}
    if a.get('inside'):
        h, w = scenes[i].shape
        if corners[:, 0].min() < -1 or corners[:, 1].min() < -1 or corners[:, 0].max() > w + 1 or corners[:, 1].max() > h + 1:
            return 'fail', dict(evidence, reason='partly outside the image')
    if a.get('max_scale'):
        width = np.linalg.norm(corners[1] - corners[0])
        if width > shape[1] * a['max_scale'] * 1.01:
            return 'fail', dict(evidence, shown_width=round(float(width)), native_width=shape[1])
    return 'pass', evidence


def op_lacks_asset(path, a):
    """None of the named supplied files is found."""
    scenes = _scenes(path)
    unsure = []
    for name in a['assets']:
        asset = _load_gray(asset_path(a, name))
        for i, scene in enumerate(scenes):
            n, _, state = find_asset(scene, asset)
            if state == 'found':
                return 'fail', {'found': name, 'inliers': n, 'page_or_frame': i}
            if state == 'unsure':
                unsure.append((name, i))
    if unsure:
        return PERSON, {'reason': 'a possible match that does not clearly look like the supplied file', 'where': unsure[:3]}
    return 'pass', {'checked': a['assets']}


def op_image_ppi(path, a):
    """The placed photo that is the supplied file has at least the stated effective resolution (pixels over placed size)."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'effective resolution is read from a PDF'}
    asset = _load_gray(asset_path(a, a['asset']))
    doc = pymupdf.open(path)
    found = []
    for pno, page in enumerate(doc):
        for info in page.get_image_info(xrefs=True):
            if not info.get('xref'):
                continue
            pix = pymupdf.Pixmap(doc, info['xref'])
            if pix.n - pix.alpha >= 3:
                pix = pymupdf.Pixmap(pymupdf.csGRAY, pix)
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., 0]
            n, _, state = find_asset(img, asset)
            if state != 'found':
                continue
            a_, b_, c_, d_ = info['transform'][:4]
            placed_w, placed_h = (a_ * a_ + b_ * b_) ** 0.5, (c_ * c_ + d_ * d_) ** 0.5
            ppi = min(info['width'] * 72 / placed_w, info['height'] * 72 / placed_h)
            found.append({'page': pno + 1, 'ppi': round(ppi, 1), 'pixels': [info['width'], info['height']],
                          'placed_mm': [round(placed_w / 72 * 25.4, 1), round(placed_h / 72 * 25.4, 1)]})
    if not found:
        return PERSON, {'reason': f'{a["asset"]} not found as a placed image'}
    low = [f for f in found if f['ppi'] < a['min_ppi']]
    return ('fail', {'below': low}) if low else ('pass', {'placements': found})


def op_line_lengths(path, a):
    """Every line that carries part of the named texts has at most max_chars characters, spaces included."""
    layer = merged(text_layers(path))
    if layer.source != 'pdf':
        return PERSON, {'reason': 'line lengths are read from live PDF text'}
    report = []
    for text in a['texts']:
        target = canon(text, False)
        parts = [l for l in layer.lines if len(canon(l.text).strip()) >= 6 and
                 (canon(l.text, False).strip() in target or target in canon(l.text, False))]
        covered = ' '.join(canon(l.text, False).strip() for l in parts)
        if not parts or any(w not in covered for w in target.split()):
            return PERSON, {'reason': 'text not found line by line', 'text': text}
        for l in parts:
            n = len(canon(l.text).strip())
            report.append({'line': l.text.strip(), 'chars': n})
            if n > a['max_chars']:
                return 'fail', {'line': l.text.strip(), 'chars': n, 'max': a['max_chars']}
    return 'pass', {'lines': report}


def op_any_of(path, a):
    """Passes when a part passes and no part fails; parts that disagree go to a person; all failing fails."""
    results = [run(path, dict(sub, **{k: v for k, v in a.items() if k.startswith('_')})) for sub in a['checks']]
    states = {st for st, _ in results}
    if 'pass' in states and 'fail' not in states:
        return 'pass', next(ev for st, ev in results if st == 'pass')
    if states == {'fail'}:
        return 'fail', results[0][1]
    return PERSON, {'reason': 'the routes disagree or none could decide', 'parts': [st for st, _ in results]}


def op_all_of(path, a):
    """Every part must pass; any fail fails; otherwise a part a person must answer sends the whole check to a person."""
    outcome = ('pass', {'parts': len(a['checks'])})
    for sub in a['checks']:
        status, evidence = run(path, dict(sub, **{k: v for k, v in a.items() if k.startswith('_')}))
        if status == 'fail':
            return status, evidence
        if status == PERSON:
            outcome = (status, evidence)
    return outcome


OPS = {
    'v2_all_of': op_all_of,
    'v2_any_of': op_any_of,
    'v2_image_ppi': op_image_ppi,
    'v2_line_lengths': op_line_lengths,
    'v2_text_present': op_text_present,
    'v2_text_absent': op_text_absent,
    'v2_prices': op_prices,
    'v2_pdf_text_style': op_pdf_text_style,
    'v2_largest_text': op_largest_text,
    'v2_relation': op_relation,
    'v2_text_inside': op_text_inside,
    'v2_line_count': op_line_count,
    'v2_order': op_order,
    'v2_weekdays': op_weekdays,
    'v2_palette_only': op_palette_only,
    'v2_colours_present': op_colours_present,
    'v2_main_ground': op_main_ground,
    'v2_area_share': op_area_share,
    'v2_contains_asset': op_contains_asset,
    'v2_lacks_asset': op_lacks_asset,
}


def run(path: Path, assertion: dict):
    return OPS[assertion['op']](Path(path), assertion)


# round 2 (2026-10-28): layout, colour-behind-text, geometry and picture operations, in their own module
from objective_ops_r2 import OPS_R2  # noqa: E402
if [k for k in OPS_R2 if OPS.get(k, OPS_R2[k]) is not OPS_R2[k]]:
    raise ValueError(f'round 2 redefines {[k for k in OPS_R2 if OPS.get(k, OPS_R2[k]) is not OPS_R2[k]]}')
OPS.update(OPS_R2)

# round 3 (2026-10-28): colour on images, PDF shapes and text roles
from objective_ops_r3 import OPS_R3  # noqa: E402
if [k for k in OPS_R3 if OPS.get(k, OPS_R3[k]) is not OPS_R3[k]]:   # some extensions also register here themselves
    raise ValueError(f'round 3 redefines {[k for k in OPS_R3 if OPS.get(k, OPS_R3[k]) is not OPS_R3[k]]}')
OPS.update(OPS_R3)

# round 4 (2026-10-28): geometry, type measurements, photographs against their files, video and audio
from objective_ops_r4 import OPS_R4  # noqa: E402
if [k for k in OPS_R4 if OPS.get(k, OPS_R4[k]) is not OPS_R4[k]]:
    raise ValueError(f'round 4 redefines {[k for k in OPS_R4 if OPS.get(k, OPS_R4[k]) is not OPS_R4[k]]}')
OPS.update(OPS_R4)

# round 5 (2026-10-29): close calls settled by code, and objective look, count and read checks by a vision model
from objective_ops_r5 import OPS_R5  # noqa: E402
if [k for k in OPS_R5 if OPS.get(k, OPS_R5[k]) is not OPS_R5[k]]:
    raise ValueError(f'round 5 redefines {[k for k in OPS_R5 if OPS.get(k, OPS_R5[k]) is not OPS_R5[k]]}')
OPS.update(OPS_R5)
