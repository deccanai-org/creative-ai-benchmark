"""Round 3 of the deterministic checks moved from human review (pilot-13 v2, 2026-10-28): colour on images.

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person", and
nothing passes on a failed read. On a raster deliverable, colour is read only from the designed parts: photographs
are left out (the supplied photos where they are found, plus any textured region), and only flat pixels count (a
pixel whose neighbours all share its colour), so anti-aliased edges and photo texture never decide a check.
Tolerance follows the 2026-10-22 colour policy: within 5 per RGB channel (8 on JPEG and video frames).
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

import numpy as np
from PIL import Image

import objective_ops as base
from objective_ops import PERSON, OCR_GOOD_CONF, canon, contains, merged, text_layers

TOL = 5
TOL_LOSSY = 8
MIN_COMPONENT = 30            # flat pixels: smaller specks of an odd colour decide nothing

# ---------------------------------------------------------------- reading a deliverable as pixels


def _hex_rgb(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)])


def _to_hex(c):
    return '#%02X%02X%02X' % tuple(int(round(v)) for v in c[:3])


@functools.lru_cache(maxsize=24)
def _pixels(key: str, frame: int = -1):
    """The deliverable as an RGB array (images as they are; PDFs page 1 at 100 dpi; SVGs rendered on white; videos
    the held frame asked for, the last by default)."""
    path = Path(key)
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        return np.asarray(base.render_pdf(path, max(frame, 0), 100)).astype(np.int16)
    if suffix == '.svg':
        return np.asarray(base.svg_render(path).convert('RGB')).astype(np.int16)
    if suffix == '.mp4':
        frames = base.video_frames(key)
        return np.asarray(frames[frame]).astype(np.int16)
    im = Image.open(path)
    if im.mode in ('RGBA', 'LA', 'P'):
        rgba = im.convert('RGBA')
        im = Image.alpha_composite(Image.new('RGBA', rgba.size, (255, 255, 255, 255)), rgba)
    return np.asarray(im.convert('RGB')).astype(np.int16)


def _lossy(path: Path) -> bool:
    return path.suffix.lower() in ('.jpg', '.jpeg', '.mp4')


def _tol(path: Path, a) -> int:
    return a.get('tol', TOL_LOSSY if _lossy(path) else TOL)


def _flat(rgb: np.ndarray, tol: int) -> np.ndarray:
    """Pixels whose eight neighbours all share their colour (within tol): grounds, panels, rules and the cores of
    letters, never an anti-aliased edge or photo texture."""
    same = np.ones(rgb.shape[:2], bool)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
        same &= (np.abs(np.roll(np.roll(rgb, dy, 0), dx, 1) - rgb) <= tol).all(axis=2)
    same[0, :] = same[-1, :] = False
    same[:, 0] = same[:, -1] = False
    return same


def _textured(rgb: np.ndarray, block: int = 16) -> np.ndarray:
    """Photograph-like blocks: many colours spread in more than one direction. Designed areas are flat colours
    plus blends between two colours (a letter's edge), which lie on one line in colour space."""
    h, w = rgb.shape[:2]
    by, bx = h // block, w // block
    out = np.zeros((by, bx), bool)
    q = (rgb[:by * block, :bx * block] >> 3).astype(np.int32)
    code = (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]
    blocks = code.reshape(by, block, bx, block).transpose(0, 2, 1, 3).reshape(by, bx, -1)
    colours = rgb[:by * block, :bx * block].reshape(by, block, bx, block, 3).transpose(0, 2, 1, 3, 4).reshape(by, bx, -1, 3).astype(float)
    for y in range(by):
        for x in range(bx):
            uniq = len(np.unique(blocks[y, x]))
            if uniq < 12:
                continue
            c = colours[y, x]
            c = c - c.mean(axis=0)
            s = np.linalg.svd(c, compute_uv=False)
            # second spread direction: photo texture; a two-colour blend has almost none
            if s[1] > 0.12 * s[0] and s[1] / np.sqrt(len(c)) > 3:
                out[y, x] = True
    return np.kron(out, np.ones((block, block), bool)).astype(bool)


def _ground_round(rgb, box, min_share=0.02):
    """The flat area of one colour that surrounds a placed photo's subject (a cut-out sitter's new ground):
    the largest flat one-colour region touching the subject's box. Returns its mask or None."""
    import cv2
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    flat = _flat(rgb, 2)
    ring = np.zeros((h, w), bool)
    ring[max(0, y0 - 6):min(h, y1 + 6), max(0, x0 - 6):min(w, x1 + 6)] = True
    ring[max(0, y0 + 2):max(0, y1 - 2), max(0, x0 + 2):max(0, x1 - 2)] = False
    cand = rgb[ring & flat]
    if not len(cand):
        return None
    values, counts = np.unique(cand // 4, axis=0, return_counts=True)
    best = None
    for v in values[np.argsort(-counts)][:3]:
        m = flat & (np.abs(rgb // 4 - v).max(axis=2) <= 1)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        for i in range(1, n):
            if stats[i][4] < min_share * h * w:
                continue
            region = labels == i
            contact = int((region & ring).sum())
            if contact and (best is None or contact > best[1]):
                best = (region, contact)                       # the ground wrapping the subject, not the largest panel
    return best[0] if best else None


@functools.lru_cache(maxsize=24)
def _photo_mask_cached(key: str, assets: tuple, dirs: tuple, frame: int = -1, with_ground: bool = False):
    import cv2
    rgb = _pixels(key, frame)
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), bool)
    t = _textured(rgb)
    t = np.pad(t, ((0, h - t.shape[0]), (0, w - t.shape[1])))
    t = cv2.morphologyEx(t.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((33, 33), np.uint8)) > 0
    n, labels, stats, _ = cv2.connectedComponentsWithStats(t.astype(np.uint8), connectivity=8)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 0.01 * h * w:
            continue
        region = labels == i
        if area >= 0.6 * bw * bh:
            mask[max(0, y - 3):y + bh + 3, max(0, x - 3):x + bw + 3] = True        # a rectangular photo: its whole frame
        else:
            mask |= cv2.dilate(region.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    path = Path(key)
    if assets and path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.pdf'):
        import objective_ops_r2 as r2
        for name in assets:
            try:
                page, box, state = r2._asset_box(path, {'_asset_dirs': list(dirs)}, name, 0)
            except FileNotFoundError:
                continue
            if box is None:
                continue
            k = 100 / 72 if path.suffix.lower() == '.pdf' else 1
            x0, y0, x1, y1 = (int(round(v * k)) for v in box)
            mask[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = True
            if with_ground:
                ground = _ground_round(rgb, (x0, y0, x1, y1))
                if ground is not None:
                    mask |= ground
    return mask


def _photo_mask(path: Path, a, frame: int = -1):
    """Photographs to leave out; sitter_ground: also the flat ground a cut-out subject was set on."""
    dirs = tuple(a.get('_asset_dirs') or [])
    return _photo_mask_cached(str(path), tuple(a.get('photos', [])), dirs, frame, bool(a.get('sitter_ground')))


def _designed(path: Path, a, frame: int = -1):
    """(rgb, flat pixels outside photographs, area outside photographs)."""
    rgb = _pixels(str(path), frame)
    outside = ~_photo_mask(path, a, frame)
    return rgb, _flat(rgb, 2 if not _lossy(path) else 6) & outside, outside


def _near_mask(rgb, hexes, tol):
    m = np.zeros(rgb.shape[:2], bool)
    for h in hexes:
        m |= (np.abs(rgb - _hex_rgb(h)) <= tol).all(axis=2)
    return m


def _components(mask, min_px=MIN_COMPONENT):
    import cv2
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [(labels == i, stats[i]) for i in range(1, n) if stats[i][4] >= min_px]


def _frames(path: Path):
    """Frames to read: one for an image or PDF page 1; every held (repeated) frame of a video."""
    if path.suffix.lower() != '.mp4':
        return [-1]
    frames = base.video_frames(str(path))
    keep = []
    for i in range(1, len(frames)):
        if np.abs(np.asarray(frames[i], np.int16) - np.asarray(frames[i - 1], np.int16)).mean() < 1.5:
            keep.append(i)
    return sorted(set(keep)) or [len(frames) - 1]


# ---------------------------------------------------------------- palette, presence, share, ground


def op_palette_raster(path, a):
    """Every flat colour in the designed parts (photographs left out) is a palette colour within tolerance; an odd
    colour must cover a real area (MIN_COMPONENT flat pixels in one piece) to count."""
    tol = _tol(path, a)
    bad = {}
    for f in _frames(path):
        rgb, flat, outside = _designed(path, a, f)
        if flat.sum() < 200:
            return PERSON, {'reason': 'almost no flat designed area found'}
        off = flat & ~_near_mask(rgb, a['hexes'], tol)
        for comp, st in _components(off):
            colour = _to_hex(np.median(rgb[comp], axis=0))
            bad[colour] = bad.get(colour, 0) + int(st[4])
    if bad:
        top = sorted(bad.items(), key=lambda kv: -kv[1])[:5]
        return 'fail', {'outside_palette': [f'{c} ({n} px)' for c, n in top]}
    return 'pass', {'palette': a['hexes']}


def op_colour_present_raster(path, a):
    """The colour appears in the designed parts (outside photographs) as a real area of flat pixels."""
    tol = _tol(path, a)
    rgb, flat, outside = _designed(path, a)
    hit = flat & _near_mask(rgb, a['hexes'], tol)
    comps = _components(hit)
    if comps:
        return 'pass', {'pixels': int(sum(st[4] for _, st in comps))}
    return 'fail', {'reason': 'not found outside the photographs', 'hexes': a['hexes']}


def op_area_share_raster(path, a):
    """The named colours together cover no more than max_pct of the area outside photographs."""
    tol = _tol(path, a)
    worst = 0.0
    for f in _frames(path):
        rgb, flat, outside = _designed(path, a, f)
        area = outside.sum()
        if area < 0.05 * outside.size:
            return PERSON, {'reason': 'almost all of it is photograph'}
        hit = _near_mask(rgb, a['hexes'], tol) & outside
        if a.get('except_text'):
            pass
        worst = max(worst, 100 * hit.sum() / area)
    ev = {'share_pct': round(worst, 2)}
    if worst <= a['max_pct']:
        return 'pass', ev
    return ('fail' if worst > a['max_pct'] * 1.15 else PERSON), ev


def op_ground_raster(path, a):
    """Grounds and panels (flat areas of one colour covering at least 1% of the image, outside photographs) are
    all one of the allowed colours; main=True: the largest of them is the first colour."""
    import cv2
    tol = _tol(path, a)
    rgb, flat, outside = _designed(path, a)
    h, w = rgb.shape[:2]
    q = (rgb // 4)
    code = (q[..., 0].astype(np.int32) << 12) | (q[..., 1].astype(np.int32) << 6) | q[..., 2].astype(np.int32)
    values, counts = np.unique(code[flat], return_counts=True)
    regions = []
    for v, c in sorted(zip(values, counts), key=lambda t: -t[1])[:12]:
        if c < 0.01 * h * w:
            break
        m = flat & (code == v)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
        for comp, st in _components(m, int(0.01 * h * w)):
            if min(st[2], st[3]) >= 0.03 * min(h, w):          # an area, not a long thin rule
                x, y, bw, bh = st[0], st[1], st[2], st[3]
                edges = (x <= 2) + (y <= 2) + (x + bw >= w - 2) + (y + bh >= h - 2)
                if a.get('panels_only') and edges >= 3:
                    continue                                    # the page ground, not a panel
                regions.append((_to_hex(np.median(rgb[comp & flat], axis=0)), int(st[4])))
    if not regions:
        if a.get('panels_only'):
            return 'pass', {'reason': 'no panel apart from the page ground'}
        return PERSON, {'reason': 'no ground or panel found outside the photographs'}
    regions.sort(key=lambda r: -r[1])
    ok = lambda c: base._near_hex(c, a['hexes'], tol)
    if a.get('main'):
        top = regions[0][0]
        return ('pass' if base._near_hex(top, a['hexes'][:1], tol) else 'fail'), {'main_ground': top}
    bad = sorted({c for c, _ in regions if not ok(c)})
    return ('fail', {'grounds_outside': bad, 'regions': len(regions)}) if bad else ('pass', {'grounds': sorted({c for c, _ in regions})})


def op_colour_role_raster(path, a):
    """The colour appears only in the allowed roles: thin (a rule or divider: one side at most thin_px), small
    (a label or caption: letters no taller than small_px), never a panel or ground (an area)."""
    tol = _tol(path, a)
    rgb, flat, outside = _designed(path, a)
    h, w = rgb.shape[:2]
    thin = a.get('thin_px', max(3, round(0.004 * min(h, w))))
    hit = _near_mask(rgb, a['hexes'], tol) & outside
    roles = {'thin': 0, 'small': 0, 'area': 0, 'type': 0}
    bad = []
    for comp, st in _components(hit, 12):
        x, y, bw, bh, area = st
        fill = area / max(1, bw * bh)
        if min(bw, bh) <= thin:
            role = 'thin'
        elif bw * bh >= 0.004 * h * w and fill > 0.6 and min(bw, bh) > 4 * thin:
            role = 'area'
        elif bh <= a.get('small_px', 0.025 * h):
            role = 'small'
        else:
            role = 'type'
        roles[role] += 1
        if role not in a['allowed']:
            bad.append({'role': role, 'box': [int(x), int(y), int(bw), int(bh)]})
    ev = {'pieces': roles}
    if bad:
        # a large piece is a sure panel or type; small odd pieces may be anti-aliasing a person should look at
        sure = [b for b in bad if b['role'] in ('area', 'type') and b['box'][2] * b['box'][3] >= 400]
        return ('fail' if sure else PERSON), dict(ev, not_allowed=bad[:4])
    return 'pass', ev


# ---------------------------------------------------------------- the colour of a text line or mark on an image


def _ink_and_ground(rgb, box, pad=3):
    """Ground: the commonest colour round a box; ink: the pixels in the box furthest from the ground (the letters'
    cores, past their anti-aliased edges). Returns (ink, ground, contrast) or None."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return None
    ring = np.concatenate([rgb[max(0, y0 - pad):y0, x0:x1].reshape(-1, 3), rgb[y1:y1 + pad, x0:x1].reshape(-1, 3),
                           rgb[y0:y1, max(0, x0 - pad):x0].reshape(-1, 3), rgb[y0:y1, x1:x1 + pad].reshape(-1, 3)])
    inner = rgb[y0:y1, x0:x1].reshape(-1, 3)
    if not len(ring):
        ring = inner
    values, counts = np.unique(ring // 4, axis=0, return_counts=True)
    ground = values[counts.argmax()] * 4 + 2
    share = (np.abs(ring - ground).max(axis=1) <= 8).mean()
    d = np.abs(inner - ground).sum(axis=1)
    if d.max() < 60:
        return None
    core = inner[d >= 0.92 * d.max()]
    ink = np.median(core, axis=0)
    ground = np.median(ring[np.abs(ring - ground).max(axis=1) <= 8], axis=0) if share > 0 else ground
    return ink, ground, share


def _lines(path: Path, a, frame=None):
    layer = merged(text_layers(path)) if frame is None else base.ocr_image(Image.fromarray(_pixels(str(path), frame).astype(np.uint8)))
    picks = []
    for l in layer.lines:
        if not base._real(l):
            continue
        t = canon(l.text)
        if a.get('texts') and any(contains(t, x, False) for x in a['texts']):
            picks.append(l)
        elif a.get('patterns') and any(re.search(p, t, re.I) or re.search(p, base.squash(t), re.I) for p in a['patterns']):
            picks.append(l)
        elif (a.get('all_text') or (a.get('roles') and not a.get('texts') and not a.get('patterns'))) and \
                not any(contains(t, x, False) for x in a.get('except', [])):
            picks.append(l)
    if a.get('roles'):
        body, roles = _roles(layer)
        picks = [l for l in picks if any(l in roles.get(r, []) for r in a['roles'])] if picks else \
            [l for r in a['roles'] for l in roles.get(r, [])]
    if a.get('largest_only') and picks:
        top = max(l.size for l in picks)
        picks = [l for l in picks if l.size >= 0.92 * top]
    return layer, picks


def op_text_colour_raster(path, a):
    """Each selected text line on an image: its ink (letter cores) and ground (round it) are measured. grounds: the
    check applies to lines on these grounds; colors: allowed inks; ground_must: the line's ground must be one of these.
    Within tol of an allowed colour passes; 30 or more from every allowed colour fails; between goes to a person."""
    tol = _tol(path, a) + 3                                     # letter cores of small type carry some blending
    frames = _frames(path) if path.suffix.lower() == '.mp4' else [None]
    checked, bad, unsure = 0, [], []
    for f in frames:
        rgb = _pixels(str(path), -1 if f is None else f)
        layer, picks = _lines(path, a, f)
        if not picks:
            continue
        for l in picks:
            got = _ink_and_ground(rgb, l.bbox)
            if got is None:
                unsure.append(l.text)
                continue
            ink, ground, share = got
            g_hex, i_hex = _to_hex(ground), _to_hex(ink)
            if a.get('ground_must'):
                checked += 1
                if share < 0.5:
                    unsure.append(l.text)
                elif not base._near_hex(g_hex, a['ground_must'], tol + 3):
                    bad.append({'line': l.text, 'ground': g_hex})
                continue
            if a.get('grounds') and (share < 0.5 or not base._near_hex(g_hex, a['grounds'], tol + 3)):
                continue
            checked += 1
            dist = min(np.abs(ink - _hex_rgb(c)).max() for c in a['colors'])
            if dist <= tol:
                continue
            (bad if dist >= 30 and l.conf >= OCR_GOOD_CONF else unsure).append({'line': l.text, 'ink': i_hex, 'ground': g_hex})
    if bad:
        return 'fail', {'not_matching': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'some line colours not clear enough to call', 'lines': unsure[:4]}
    if not checked:
        if a.get('optional', True):
            return 'pass', {'reason': 'no such text (the check applies only where it appears)'}
        return PERSON, {'reason': 'text not found'}
    return 'pass', {'lines_checked': checked}


def op_mark_colour_raster(path, a):
    """A mark found by its supplied file (or a text line) is inked in one of the colours (and solid: its ink pixels
    one colour), optionally on one of the grounds."""
    import objective_ops_r2 as r2
    rgb = _pixels(str(path))
    box = None
    if a.get('asset'):
        page, box, state = r2._asset_box(path, a, a['asset'], 0)
        if box is not None and path.suffix.lower() == '.pdf':
            box = tuple(v * 100 / 72 for v in box)
    elif a.get('text'):
        layer, picks = _lines(path, {'texts': [a['text']]})
        box = picks[0].bbox if picks else None
    if box is None:
        if a.get('optional'):
            return PERSON, {'reason': 'mark not found (it may be absent or redrawn)'}
        return PERSON, {'reason': 'mark not found'}
    got = _ink_and_ground(rgb, box)
    if got is None:
        return PERSON, {'reason': 'mark ink not measurable'}
    ink, ground, share = got
    tol = _tol(path, a) + 3
    ev = {'ink': _to_hex(ink), 'ground': _to_hex(ground)}
    if a.get('grounds') and not base._near_hex(_to_hex(ground), a['grounds'], tol + 3):
        return ('pass', dict(ev, reason='not on that ground')) if a.get('only_on_grounds') else ('fail', dict(ev, reason='ground'))
    if a.get('pairs'):
        # allowed (ink, ground) combinations, such as blue on lime or lime on blue
        best = min(max(np.abs(ink - _hex_rgb(i)).max(), np.abs(ground - _hex_rgb(g)).max()) for i, g in a['pairs'])
        if best <= tol + 3:
            return 'pass', ev
        return ('fail' if best >= 30 else PERSON), ev
    dist = min(np.abs(ink - _hex_rgb(c)).max() for c in a['colors'])
    if dist <= tol:
        return 'pass', ev
    return ('fail' if dist >= 30 else PERSON), ev


# ---------------------------------------------------------------- photographs: overlays, colour, two-colour treatment


def _photo_pair(path, a):
    """The supplied photo found in the deliverable (photo, or the first of photos found), and the deliverable's
    pixels warped back onto it."""
    if not a.get('photo') and a.get('photos'):
        for name in a['photos']:
            got = _photo_pair(path, dict(a, photo=name, photos=None))
            if got is not None:
                return got
        return None
    import cv2
    asset_p = base.asset_path(a, a['photo'])
    src = np.asarray(Image.open(asset_p).convert('RGB')).astype(np.float32)
    scale = 900 / max(src.shape[:2])
    if scale < 1:
        src = cv2.resize(src, (round(src.shape[1] * scale), round(src.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    rgb = _pixels(str(path)).astype(np.float32)
    gray_scene = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    gray_src = cv2.cvtColor(src.astype(np.uint8), cv2.COLOR_RGB2GRAY)
    n, corners, state = base.find_asset(gray_scene, gray_src)
    if state != 'found':
        return None
    h, w = gray_src.shape
    H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
    back = cv2.warpPerspective(rgb, np.linalg.inv(H), (w, h), flags=cv2.INTER_AREA)
    valid = cv2.warpPerspective(np.full(rgb.shape[:2], 255, np.uint8), np.linalg.inv(H), (w, h), flags=cv2.INTER_NEAREST) > 0
    same = cv2.blur(np.abs(back - src).mean(axis=2), (15, 15)) < 60       # the photo's own area, not text laid on it
    # well inside it: a cut-out's edges blend into a new ground, which is not a change to the photo; and only where
    # the supplied photo has detail, since a plain studio backdrop may itself have been replaced by a new ground
    inner = cv2.erode((valid & same).astype(np.uint8), np.ones((17, 17), np.uint8)) > 0
    g = cv2.cvtColor(src.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
    detail = np.sqrt(np.maximum(cv2.blur(g * g, (7, 7)) - cv2.blur(g, (7, 7)) ** 2, 0)) > 6
    return src, back, inner & detail


def op_no_overlay(path, a):
    """No scrim, gradient or tint over a photograph. PDFs: nothing semi-transparent, shaded or gradient is drawn over
    a placed image, read from the page's drawings. Images: the photo, compared with the supplied file, keeps its
    tones (per channel gain within 0.92 to 1.08, offset within 12 levels) with no difference that runs across it."""
    if path.suffix.lower() == '.pdf':
        import pymupdf
        doc = pymupdf.open(path)
        bad = []
        for page in doc:
            images = [tuple(i['bbox']) for i in page.get_image_info()]
            for d in page.get_drawings():
                r = tuple(d['rect'])
                over = [i for i in images if base._overlap(i, r) > 0.05 and (r[2] - r[0]) * (r[3] - r[1]) > 0.02 * (i[2] - i[0]) * (i[3] - i[1])]
                if not over or d.get('fill') is None:
                    continue
                if (d.get('fill_opacity') or 1) < 0.999 or d.get('type') == 'sh':
                    bad.append({'page': page.number + 1, 'fill_opacity': d.get('fill_opacity')})
            if 'sh' in b''.join(doc.xref_stream(x) or b'' for x in page.get_contents()).decode('latin-1').split():
                bad.append({'page': page.number + 1, 'shading': True})
        return ('fail', {'overlays': bad[:4]}) if bad else ('pass', {'pages': len(doc)})
    if not a.get('photo') and not a.get('photos'):
        return PERSON, {'reason': 'no supplied photo named to compare with'}
    pair = _photo_pair(path, a)
    if pair is None:
        return PERSON, {'reason': 'supplied photo not found'}
    src, back, m = pair
    if m.mean() < 0.15:
        return PERSON, {'reason': 'most of the photo is covered or cropped away'}
    gains, offsets = [], []
    for ch in range(3):
        x, y = src[..., ch][m], back[..., ch][m]
        g, o = np.polyfit(x, y, 1)
        gains.append(g)
        offsets.append(o)
    resid = (back - (src * np.array(gains) + np.array(offsets))).mean(axis=2)
    # a gradient scrim shifts whole bands of the photo: median signed difference per band, across and down
    meds = []
    for axis in (0, 1):
        n = m.shape[axis]
        step = max(1, n // 6)
        band = []
        for i in range(0, n - step + 1, step):
            sl = (slice(i, i + step), slice(None)) if axis == 0 else (slice(None), slice(i, i + step))
            sel = m[sl]
            if sel.sum() >= 500:
                band.append(float(np.median(resid[sl][sel])))
        if len(band) >= 2:
            meds.append(max(band) - min(band))
    drift = max(meds) if meds else 0.0
    ev = {'gain': [round(g, 3) for g in gains], 'offset': [round(o, 1) for o in offsets], 'drift': round(drift, 1)}
    # a scrim or tint blends the photo with a colour, so it lowers contrast (gain under 1); a levels or contrast lift
    # (gain over 1) is not an overlay
    if min(gains) >= 0.92 and drift < 12:
        return 'pass', ev
    # an even scrim over the whole photo lowers contrast everywhere alike; anything uneven may be a cut-out on a new
    # ground or a treatment, which pixels alone cannot tell from a gradient overlay, so a person decides
    if min(gains) < 0.7 and drift < 12:
        return 'fail', ev
    return PERSON, dict(ev, reason='tones differ from the supplied photo (a treatment, a new ground or an overlay; a person decides)')


def op_chroma_kept(path, a):
    """The photo stays in colour: its colourfulness is at least 60% of the supplied file's (Lab chroma); under 25%,
    or one narrow hue (sepia), fails."""
    import cv2
    pair = _photo_pair(path, a)
    if pair is None:
        return PERSON, {'reason': 'supplied photo not found'}
    src, back, m = pair
    lab_s = cv2.cvtColor(src.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(float)
    lab_d = cv2.cvtColor(back.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(float)
    cs = np.hypot(lab_s[..., 1] - 128, lab_s[..., 2] - 128)[m].mean()
    cd = np.hypot(lab_d[..., 1] - 128, lab_d[..., 2] - 128)[m].mean()
    ratio = cd / max(cs, 1e-6)
    ev = {'chroma_ratio': round(float(ratio), 2)}
    if ratio >= 0.6:
        return 'pass', ev
    return ('fail' if ratio < 0.25 else PERSON), ev


def op_two_colour(path, a):
    """The photograph is reproduced in two colours: every photo pixel lies on the blend line between two colours
    (the palette pair, or the pair found on a reference deliverable)."""
    rgb, flat, outside = _designed(path, a)
    photo = _photo_mask(path, a)
    px = rgb[photo].astype(float)
    if len(px) < 500:
        return PERSON, {'reason': 'no photograph found'}
    pair = [_hex_rgb(h).astype(float) for h in a['pair']] if a.get('pair') else None
    if pair is None:
        return PERSON, {'reason': 'no colour pair given'}
    p0, p1 = pair
    d = p1 - p0
    t = np.clip(((px - p0) @ d) / (d @ d), 0, 1)
    resid = np.linalg.norm(px - (p0 + t[:, None] * d), axis=1)
    share_off = float((resid > 30).mean())
    ev = {'off_line_share': round(share_off, 3)}
    if share_off <= 0.03:
        return 'pass', ev
    return ('fail' if share_off > 0.2 else PERSON), ev


def op_tone_between(path, a):
    """The ground behind the sitter is a tone between two colours: each channel within the range they span, give or
    take tol. The ground is the flat area round the matched sitter (a cut-out on a new ground), else the placed
    photo's own border strip."""
    import objective_ops_r2 as r2
    rgb = _pixels(str(path))
    page, box, state = r2._asset_box(path, a, a['photo'], 0)
    if box is None:
        return PERSON, {'reason': 'supplied portrait not found'}
    ground = _ground_round(rgb, box)
    if ground is not None:
        tone = np.median(rgb[ground], axis=0)
    else:
        pair = _photo_pair(path, a)
        if pair is None:
            return PERSON, {'reason': 'supplied portrait not found'}
        src, back, m = pair
        h, w = m.shape
        strip = np.zeros_like(m)
        strip[:max(1, h // 8)] = True
        strip[:, :max(1, w // 10)] = True
        strip[:, -max(1, w // 10):] = True
        sel = strip & m
        if sel.sum() < 100:
            return PERSON, {'reason': 'background not visible'}
        tone = np.median(back[sel], axis=0)
    lo = np.minimum(_hex_rgb(a['hexes'][0]), _hex_rgb(a['hexes'][1])) - a.get('tol', 8)
    hi = np.maximum(_hex_rgb(a['hexes'][0]), _hex_rgb(a['hexes'][1])) + a.get('tol', 8)
    ev = {'tone': _to_hex(tone)}
    if ((tone >= lo) & (tone <= hi)).all():
        return 'pass', ev
    far = np.maximum(lo - tone, tone - hi).max()
    return ('fail' if far > 20 else PERSON), ev


def op_legible_at(path, a):
    """Shown at a smaller width, every word of the text is still read by OCR. Never a fail: OCR missing a word is
    not proof a person cannot read it."""
    rgb = _pixels(str(path)).astype(np.uint8)
    im = Image.fromarray(rgb)
    w = a['width']
    small = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    big = small.resize(im.size, Image.LANCZOS)                   # read at the shown size, enlarged for OCR alone
    layer = base.ocr_image(big)
    hay = ' '.join(l.text for l in layer.lines if l.conf >= OCR_GOOD_CONF)
    words = [x for x in re.findall(r"[\w'&]+", a['text']) if len(x) > 1 or x.isalnum()]
    missing = [x for x in words if not contains(hay, x, False)]
    if not missing:
        return 'pass', {'width': w, 'words': len(words)}
    return PERSON, {'reason': 'some words not read at that size', 'missing': missing[:6]}


# ---------------------------------------------------------------- PDF shapes: rules, panels and where a colour goes


def _pdf_shapes(key: str):
    """Every drawn shape of every page: colour (fill or stroke), box, thickness, kind (rule, panel or other), and
    whether it lies over a placed image. A rule is thin (2 pt or less across); a panel is a filled area of 2% or
    more of the page with both sides over 6 pt."""
    import pymupdf
    out = []
    for page in pymupdf.open(key):
        W, H = page.rect.width, page.rect.height
        images = [tuple(i['bbox']) for i in page.get_image_info()]
        for d in page.get_drawings():
            r = d['rect']
            for k in ('fill', 'color'):
                c = d.get(k)
                if c is None:
                    continue
                width = (d.get('width') or 0) if k == 'color' else 0
                bw, bh = r.width + width, r.height + width
                thick = min(bw, bh)
                kind = 'rule' if thick <= 2.0 else ('panel' if k == 'fill' and bw * bh >= 0.02 * W * H and min(bw, bh) > 6 else 'other')
                out.append(dict(page=page.number, colour=base._hex(c), box=(r.x0, r.y0, r.x1, r.y1), thick=round(thick, 2), kind=kind,
                                full_width=bw >= 0.95 * W, horizontal=bw >= bh, opacity=d.get('fill_opacity' if k == 'fill' else 'stroke_opacity'),
                                on_image=any(base._overlap(i, (r.x0, r.y0, r.x1, r.y1)) > 0.5 for i in images), page_w=W, page_h=H))
    return out


def op_pdf_shapes(path, a):
    """Shapes of a colour, from the PDF's drawings (photographs left out):
    only_rules: every shape in the colour is a thin rule (full_width: running the page width; count: how many);
    no text set in it either. thickness: every rule in the colour is that many pt thick (within 0.15).
    grounds: every panel (a filled area of 2% of the page or more) is one of these colours.
    rules_not: no thin rule is one of these colours."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    shapes = [s for s in _pdf_shapes(str(path)) if not s['on_image']]
    import objective_ops_r2 as r2
    if a.get('grounds'):
        panels = [s for s in shapes if s['kind'] == 'panel']
        bad = sorted({s['colour'] for s in panels if not base._near_hex(s['colour'], a['grounds'], 3)})
        return ('fail', {'panels_outside': bad}) if bad else ('pass', {'panels': len(panels)})
    if a.get('rules_not'):
        bad = sorted({s['colour'] for s in shapes if s['kind'] == 'rule' and base._near_hex(s['colour'], a['rules_not'], 3)})
        return ('fail', {'rules_in': bad}) if bad else ('pass', {'rules': sum(1 for s in shapes if s['kind'] == 'rule')})
    mine = [s for s in shapes if base._near_hex(s['colour'], a['hexes'], 3)]
    if a.get('thickness') is not None:
        rules = [s for s in mine if s['kind'] == 'rule' and (s['full_width'] or not a.get('full_width'))]
        if not rules:
            return PERSON, {'reason': 'no rule in that colour'}
        off = [s['thick'] for s in rules if abs(s['thick'] - a['thickness']) > 0.15]
        return ('fail', {'thickness_pt': off}) if off else ('pass', {'rules': len(rules), 'thickness_pt': a['thickness']})
    if a.get('only_rules'):
        text = [sp['text'] for sp in r2._pdf_spans(str(path)) if base._near_hex(sp['color'], a['hexes'], 3)]
        if text:
            return 'fail', {'type_in_colour': text[:3]}
        bad = [s for s in mine if s['kind'] != 'rule' or (a.get('full_width') and not s['full_width'])]
        if bad:
            return 'fail', {'not_a_rule': [{'page': s['page'] + 1, 'box': [round(v) for v in s['box']], 'kind': s['kind']} for s in bad[:3]]}
        if a.get('count') is not None:
            per_page = {}
            for s in mine:
                per_page.setdefault(s['page'], set()).add(round(s['box'][1]))
            counts = sorted({len(v) for v in per_page.values()}) or [0]
            if counts != [a['count']]:
                return 'fail', {'rules_per_page': counts}
        return 'pass', {'rules': len(mine)}
    return PERSON, {'reason': 'nothing to check'}


def op_pdf_rule_by_text(path, a):
    """A thin rule in the colour, running the page width, sits directly below (where "below") or directly above
    (where "above") the named text: no more than gap_lines line heights between them, nothing in between."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = base.pdf_layer(str(path))
    hits = [l for l in layer.lines if contains(l.text, a['text'], False)] or base._span(layer, a['text'], max_lines=8)
    if not hits:
        return PERSON, {'reason': f'text not found: {a["text"][:40]}'}
    top, bottom, page = min(l.bbox[1] for l in hits), max(l.bbox[3] for l in hits), hits[0].page
    lh = max(l.bbox[3] - l.bbox[1] for l in hits)
    rules = [s for s in _pdf_shapes(str(path)) if s['page'] == page and s['kind'] == 'rule' and s['horizontal'] and s['full_width']
             and base._near_hex(s['colour'], a['hexes'], 3)]
    gap = max(3 * lh, 12)
    others = [l for l in layer.lines if l.page == page and l not in hits]
    def clear(y0, y1):                                      # no other line of text between the rule and the text
        return not any(l.bbox[1] < y1 and l.bbox[3] > y0 and min(l.bbox[3], y1) - max(l.bbox[1], y0) > 1 for l in others)
    if a['where'] == 'below':
        # "sits on" a rule: the rule may run along the baseline, inside the line box's descender room
        near = [s for s in rules if -0.4 * lh <= s['box'][1] - bottom <= gap and clear(bottom, s['box'][1])]
    else:
        near = [s for s in rules if -0.4 * lh <= top - s['box'][3] <= gap and clear(s['box'][3], top)]
    if near:
        return 'pass', {'rule_y': round(near[0]['box'][1], 1)}
    return 'fail', {'rules_y': [round(s['box'][1], 1) for s in rules], 'text_box': [round(top, 1), round(bottom, 1)]}


def op_pdf_rules_match(path, a):
    """The rules in the colour sit at the same heights (within 1 pt) as on another delivered file."""
    other = Path(a['_artifacts']) / a['deliverable']
    if not other.is_file():
        return PERSON, {'reason': 'the other delivered file is not available'}
    ys = lambda p: sorted(round(s['box'][1], 1) for s in _pdf_shapes(str(p)) if s['kind'] == 'rule' and base._near_hex(s['colour'], a['hexes'], 3) and s['page'] == 0)
    mine, ref = ys(path), ys(other)
    if not mine or not ref:
        return PERSON, {'reason': 'rules not found on one of the files'}
    if len(mine) != len(ref):
        return 'fail', {'heights': mine, 'reference': ref}
    off = [abs(x - y) for x, y in zip(mine, ref)]
    return ('pass' if max(off) <= 1.0 else 'fail'), {'heights': mine, 'reference': ref}


def op_colour_only_in_mark(path, a):
    """The colour is used for the mark and nothing else. PDFs: no type set in it, and every shape in it lies in one
    cluster no bigger than max_mm. Images: outside its largest cluster (the mark), no flat area in the colour."""
    tol = _tol(path, a)
    if path.suffix.lower() == '.pdf':
        import objective_ops_r2 as r2
        text = [sp['text'] for sp in r2._pdf_spans(str(path)) if base._near_hex(sp['color'], a['hexes'], 3)]
        if text:
            return 'fail', {'type_in_colour': text[:3]}
        mine = [s for s in _pdf_shapes(str(path)) if base._near_hex(s['colour'], a['hexes'], 3)]
        if not mine:
            return 'pass', {'reason': 'colour not used'}
        bad = [s for s in mine if s['kind'] == 'panel']
        pages = {}
        for s_ in mine:
            pages.setdefault(s_['page'], []).append(s_['box'])
        spread = max((max(b[2] for b in bx) - min(b[0] for b in bx)) * 25.4 / 72 for bx in pages.values())
        if bad or spread > a.get('max_mm', 60):
            return 'fail', {'panels': len(bad), 'spread_mm': round(spread, 1)}
        return 'pass', {'shapes': len(mine), 'spread_mm': round(spread, 1)}
    import cv2
    rgb, flat, outside = _designed(path, a)
    hit = (_near_mask(rgb, a['hexes'], tol + 4) & outside).astype(np.uint8)
    if hit.sum() < 20:
        return 'pass', {'reason': 'colour not used'}
    grown = cv2.dilate(hit, np.ones((15, 15), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
    sizes = [(int((hit & (labels == i)).sum()), i) for i in range(1, n)]
    sizes.sort(reverse=True)
    rest = [s for s, _ in sizes[1:] if s >= MIN_COMPONENT]
    if rest:
        return 'fail', {'other_pieces_px': rest[:5]}
    return 'pass', {'mark_px': sizes[0][0]}


def op_solid_pdf(path, a):
    """All type and filled shapes are solid: no transparency (opacity under 1) and no gradient shading."""
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
        if re.search(r'(?<![\w/])sh\b', stream):
            bad.append({'page': page.number + 1, 'shading': True})
        for b in page.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for sp in l['spans']:
                    if sp['text'].strip() and sp.get('alpha', 255) < 255:
                        bad.append({'page': page.number + 1, 'text': sp['text'][:30], 'alpha': sp['alpha']})
    return ('fail', {'not_solid': bad[:4]}) if bad else ('pass', {'pages': len(doc)})


# ---------------------------------------------------------------- text roles: body, headings, fine print


def _roles(layer):
    """Text roles, read the same way on every file. Running text is sentences: lines with lowercase letters, not
    repeated three or more times with only figures changed (a running head, a data line such as "Minimum stay 3
    nights"). The body size carries the most characters among running lines of four words or more. Roles:
    body = running lines at the body size; heading = lines at 1.3 times it or more (main = the largest size);
    fine = lines under 0.85 times it, split into caption (sentence case) and label (capitals).
    Returns (body_size, {role: [lines]})."""
    lines = [l for l in layer.lines if base._real(l) and l.size_ok and l.text.strip()]
    skeleton = lambda t: re.sub(r'\d+', '#', canon(t, False)).strip()
    seen = {}
    for l in lines:
        seen[skeleton(l.text)] = seen.get(skeleton(l.text), 0) + 1
    running = [l for l in lines if re.search(r'[a-z]', l.text) and seen[skeleton(l.text)] < 3]
    long_lines = [l for l in running if len(l.text.split()) >= 4]
    if not long_lines:
        return None, {}
    weight = {}
    for l in long_lines:
        key = round(l.size * 2) / 2 if layer.source == 'pdf' else round(l.size)
        weight[key] = weight.get(key, 0) + len(l.text)
    body = max(weight, key=weight.get)
    tol = 0.3 if layer.source == 'pdf' else 0.08 * body
    roles = {'body': [], 'heading': [], 'main': [], 'fine': [], 'caption': [], 'label': []}
    top = max(l.size for l in lines)
    for l in lines:
        if abs(l.size - body) <= tol and l in running:
            roles['body'].append(l)
        elif l.size >= 1.3 * body:
            roles['heading'].append(l)
            if l.size >= top - (0.3 if layer.source == 'pdf' else 0.08 * top):
                roles['main'].append(l)
        elif l.size < 0.85 * body:
            roles['fine'].append(l)
            roles['caption' if re.search(r'[a-z]', l.text) else 'label'].append(l)
    return body, roles


def op_role_lines(path, a):
    """Lines of a role (body, heading, main, secondary = headings other than the main one, fine) meet a condition:
    max_chars per line; family/weight (PDF); size in pt (PDF); leading between consecutive lines of a block (PDF);
    smaller_than / larger_than another role. Roles are read by size (see _roles)."""
    layer = merged(text_layers(path))
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    body, roles = _roles(layer)
    if body is None:
        return PERSON, {'reason': 'no running text found to set the body size'}
    roles['secondary'] = [l for l in roles['heading'] if l not in roles['main']]
    sel = roles.get(a['role'], [])
    if not sel:
        return ('pass', {'reason': f'no {a["role"]} text'}) if a.get('optional', True) else (PERSON, {'reason': f'no {a["role"]} text found'})
    pdf = layer.source == 'pdf'
    if 'max_chars' in a:
        long_ = [(l.text, len(canon(l.text))) for l in sel if len(canon(l.text)) > a['max_chars']]
        if not long_:
            return 'pass', {'lines': len(sel), 'longest': max(len(canon(l.text)) for l in sel)}
        # OCR may join two columns into one line: only live PDF text can fail on length
        return ('fail' if pdf else PERSON), {'too_long': long_[:3]}
    if not pdf and any(k in a for k in ('family', 'weight', 'size', 'leading')):
        return PERSON, {'reason': 'type style is read from a PDF'}
    if 'family' in a or 'weight' in a:
        fam = re.sub(r'[^a-z0-9]', '', a.get('family', '').lower())
        wt = re.sub(r'[^a-z0-9]', '', a.get('weight', '').lower())
        bad = []
        for l in sel:
            for t, font, size, colour in l.fonts:
                if not t.strip() or (a.get('except_digits') and re.fullmatch(r'[\d\s.,/-]+', t)):
                    continue
                f, w = base._font_parts(font)
                if (fam and f != fam) or (wt and w != wt):
                    bad.append((t[:30], font))
        return ('fail', {'not_matching': bad[:6]}) if bad else ('pass', {'lines': len(sel)})
    if 'size' in a:
        bad = sorted({round(l.size, 2) for l in sel if abs(l.size - a['size']) > a.get('tolerance', 0.1)})
        return ('fail', {'sizes': bad}) if bad else ('pass', {'lines': len(sel), 'size': a['size']})
    if 'leading' in a:
        gaps = []
        ordered = sorted(sel, key=lambda l: (l.page, l.bbox[1]))
        for x, y in zip(ordered, ordered[1:]):
            if x.page == y.page and abs(x.bbox[0] - y.bbox[0]) < 2 and 0 < y.bbox[3] - x.bbox[3] < 2.2 * x.size:
                gaps.append(round(y.bbox[3] - x.bbox[3], 2))
        if not gaps:
            return 'pass', {'reason': 'no wrapped block'}
        bad = [g for g in gaps if abs(g - a['leading']) > a.get('tolerance', 0.5)]
        return ('fail', {'baseline_gaps': bad[:6]}) if bad else ('pass', {'baseline_gaps': sorted(set(gaps))})
    if 'smaller_than' in a or 'larger_than' in a:
        other = roles.get(a.get('smaller_than') or a.get('larger_than'), [])
        if not other:
            return 'pass', {'reason': 'nothing to compare with'}
        margin = 0.01 if pdf else base.SIZE_MARGIN
        if 'smaller_than' in a:
            ok = max(l.size for l in sel) < min(l.size for l in other) * (1 - margin)
        else:
            ok = min(l.size for l in sel) > max(l.size for l in other) * (1 + margin)
        return ('pass' if ok else ('fail' if pdf else PERSON)), {'sizes': [round(max(l.size for l in sel), 1), round(min(l.size for l in other), 1)]}
    return PERSON, {'reason': 'nothing to check'}


def _gold(rgb_list):
    """Gold, brass or metallic yellow-browns: hue 30 to 58 degrees, saturation 0.35 or more, value 0.4 to 0.95."""
    import colorsys
    out = []
    for c in rgb_list:
        hh, ss, vv = colorsys.rgb_to_hsv(*(np.asarray(c[:3], float) / 255))
        if 30 / 360 <= hh <= 58 / 360 and ss >= 0.35 and 0.4 <= vv <= 0.95:
            out.append(_to_hex(c))
    return out


def op_no_gold(path, a):
    """No gold or metallic colour in the designed parts: type and shape colours (PDF) or flat areas outside
    photographs (images). Gold: hue 30 to 58 degrees, saturation 0.35 or more, value 0.4 to 0.95; palette colours
    listed in allow are never counted."""
    allow = a.get('allow', [])
    if path.suffix.lower() == '.pdf':
        fills, text = base._pdf_colours(path)
        used = {h for h, *_ in fills} | {h for h, _ in text}
        bad = [h for h in _gold([_hex_rgb(h) for h in used]) if not base._near_hex(h, allow, 3)]
        return ('fail', {'gold': bad}) if bad else ('pass', {'colours': len(used)})
    rgb, flat, outside = _designed(path, a)
    px = rgb[flat]
    if not len(px):
        return PERSON, {'reason': 'no flat designed area found'}
    values, counts = np.unique(px // 4, axis=0, return_counts=True)
    cand = [v * 4 + 2 for v, c in zip(values, counts) if c >= MIN_COMPONENT]
    bad = [h for h in _gold(cand) if not base._near_hex(h, allow, _tol(path, a))]
    return ('fail', {'gold': bad[:5]}) if bad else ('pass', {'colours': len(cand)})


def op_role_colour_pdf(path, a):
    """PDF type of a role (body, heading, main, fine; see _roles) or matching patterns is set in allowed colours;
    with grounds, only where it sits on one of those grounds (the colour behind it read from the rendered page)."""
    import objective_ops_r2 as r2
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = base.pdf_layer(str(path))
    body, roles = _roles(layer)
    if body is None:
        return PERSON, {'reason': 'no running text found to set the body size'}
    chosen = [l for r in a.get('roles', []) for l in roles.get(r, [])]
    chosen += [l for l in layer.lines if any(re.search(p_, canon(l.text), re.I) or re.search(p_, base.squash(canon(l.text)), re.I) for p_ in a.get('patterns', []))]
    chosen += [l for l in layer.lines if any(contains(l.text, t, False) for t in a.get('texts', []))]
    chosen = list(dict.fromkeys(chosen))
    if not chosen:
        return 'pass', {'reason': 'no such text'}
    bad, checked = [], 0
    spans = r2._pdf_spans(str(path))
    for l in chosen:
        for sp in spans:
            if sp['page'] != l.page or base._overlap(sp['bbox'], l.bbox) < 0.5:
                continue
            if a.get('grounds'):
                g = r2._ground(str(path), sp['page'], sp['bbox'], sp['color'])
                if g in ('photo', 'mixed') or not base._near_hex(g, a['grounds'], 6):
                    continue
            checked += 1
            if not base._near_hex(sp['color'], a['colors'], 2):
                bad.append((sp['text'][:30], sp['color']))
    return ('fail', {'not_matching': bad[:6]}) if bad else ('pass', {'spans_checked': checked})


OPS_R3 = {
    'v2_no_gold': op_no_gold,
    'v2_role_colour_pdf': op_role_colour_pdf,

    'v2_pdf_shapes': op_pdf_shapes,
    'v2_pdf_rule_by_text': op_pdf_rule_by_text,
    'v2_pdf_rules_match': op_pdf_rules_match,
    'v2_colour_only_in_mark': op_colour_only_in_mark,
    'v2_solid_pdf': op_solid_pdf,
    'v2_role_lines': op_role_lines,

    'v2_palette_raster': op_palette_raster,
    'v2_colour_present_raster': op_colour_present_raster,
    'v2_area_share_raster': op_area_share_raster,
    'v2_ground_raster': op_ground_raster,
    'v2_colour_role_raster': op_colour_role_raster,
    'v2_text_colour_raster': op_text_colour_raster,
    'v2_mark_colour_raster': op_mark_colour_raster,
    'v2_no_overlay': op_no_overlay,
    'v2_chroma_kept': op_chroma_kept,
    'v2_two_colour': op_two_colour,
    'v2_tone_between': op_tone_between,
    'v2_legible_at': op_legible_at,
}


# task-family extensions written with the round-3 handlers (tools/auto_verifier/ops_r3_<family>.py, each with OPS);
# an op name may be defined once only, or one module's code would silently run another module's rules
_owner = dict.fromkeys(OPS_R3, 'objective_ops_r3')
if 'objective_ops' in __import__('sys').modules:   # rounds 1 and 2, registered before this module is loaded
    _owner.update(dict.fromkeys(__import__('sys').modules['objective_ops'].OPS, 'objective_ops (rounds 1-2)'))
for _name in ('ops_r3_photo_a', 'ops_r3_photo_b', 'ops_r3_layout', 'ops_r3_fonts'):
    try:
        _ops = __import__(_name).OPS
    except ModuleNotFoundError as _e:
        if _e.name != _name:
            raise
        continue
    for _op in _ops:
        if _op in _owner:
            raise ValueError(f'{_name} defines {_op}, already defined in {_owner[_op]}; op names must be unique')
        _owner[_op] = _name
    OPS_R3.update(_ops)
