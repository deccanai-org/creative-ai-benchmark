"""Round 4 operations for photographs (pilot-13 v2, 2026-10-28): palette reads with whole placed photo frames left
out, a placed photo's shadow detail and clipped whites against its supplied file, the white border of a restored
print, a wordmark's counters and lettering, and visible grain.

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person";
nothing passes on a failed or partial read, a supplied file not found goes to a person, and a near miss goes to a
person, never to a fail. Every limit is a setting of the assertion, named in its op's docstring. Loaded by
objective_ops_r4 (op names end in _r4p).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

import objective_ops as base
import objective_ops_r3 as r3
import ops_r3_photo_a as pa
from objective_ops import PERSON


def _cv2():
    import cv2
    return cv2


# ---------------------------------------------------------------- whole placed photo frames


def _ground(rgb, tol):
    """The page ground: the colour of the outer 4 px ring when one colour covers half of it or more, else None."""
    ring = np.concatenate([rgb[:4].reshape(-1, 3), rgb[-4:].reshape(-1, 3), rgb[:, :4].reshape(-1, 3), rgb[:, -4:].reshape(-1, 3)])
    med = np.median(ring, axis=0)
    if (np.abs(ring - med) <= tol).all(axis=1).mean() < 0.5:
        return None
    return med


def _photo_like(px, a):
    """A placed photograph, not designed colour: no single exact colour covers more than frame_top_max of its pixels
    (default 0.05; a flat panel, rule, mark or letter is mostly one colour)."""
    code = (px[:, 0].astype(np.int64) << 16) | (px[:, 1].astype(np.int64) << 8) | px[:, 2].astype(np.int64)
    _, counts = np.unique(code, return_counts=True)
    return counts.max() / len(code) <= a.get('frame_top_max', 0.05)


def _photo_frames(path: Path, a, rgb, tol):
    """Whole placed photo frames, on lossless images (PNG) only: the pieces of non-ground pixels (more than ground_tol
    from the page ground, default twice tol) that are photo-like (see _photo_like) and cover frame_min of the image or
    more (default 0.01): (1) filled, when the piece fills frame_fill of its box or more (default 0.9; a photo with its
    own backdrop): the whole box; (2) a cut-out: the piece itself, grown by 3 px; (3) a thin keyline drawn round
    a photo-like piece (the keyline covers 95% or more of its box edge and 10% or less of the box): the inside of
    the keyline, the keyline itself left in. Returns (mask, boxes)."""
    cv2 = _cv2()
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), bool)
    boxes = []
    g = _ground(rgb, tol)
    if g is None or r3._lossy(path):
        return mask, boxes
    nong = (np.abs(rgb - g) > a.get('ground_tol', 2 * tol)).any(axis=2)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(nong.astype(np.uint8), connectivity=8)
    photos, keylines = [], []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if bw * bh < a.get('frame_min', 0.01) * h * w or bw * bh >= 0.9 * h * w:
            continue
        sl = (slice(y, y + bh), slice(x, x + bw))
        comp = labels[sl] == i
        fill = area / float(bw * bh)
        if area >= a.get('frame_min', 0.01) * h * w and _photo_like(rgb[sl][comp], a):
            photos.append((i, x, y, bw, bh, fill))
            continue
        ring = np.zeros_like(comp)
        ring[0, :] = ring[-1, :] = ring[:, 0] = ring[:, -1] = True
        if fill <= 0.1 and comp[ring].mean() >= 0.95:
            keylines.append((x, y, bw, bh))
    for i, x, y, bw, bh, fill in photos:
        if fill >= a.get('frame_fill', 0.9):
            mask[max(0, y - 1):y + bh + 1, max(0, x - 1):x + bw + 1] = True
            boxes.append({'box': [int(x), int(y), int(x + bw), int(y + bh)], 'kind': 'filled'})
        else:
            mask |= cv2.dilate((labels == i).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
            boxes.append({'box': [int(x), int(y), int(x + bw), int(y + bh)], 'kind': 'cut-out'})
    for x, y, bw, bh in keylines:
        inside = [p for p in photos if p[1] >= x and p[2] >= y and p[1] + p[3] <= x + bw and p[2] + p[4] <= y + bh]
        if inside:
            mask[y + 3:y + bh - 3, x + 3:x + bw - 3] = True
            boxes.append({'box': [int(x), int(y), int(x + bw), int(y + bh)], 'kind': 'keyline'})
    return mask, boxes


def op_palette_frames(path, a):
    """Every flat colour outside the photographs is a palette colour (hexes, within tol), with every placed photo
    left out as a whole frame (see _photo_frames and _photo_like: frame_min, frame_fill, frame_top_max, ground_tol),
    not only its textured part, so a photo's own smooth backdrop or a cut-out's tyres are not read as designed
    colour (anything set over a photo inside its frame is left out with it). Lossless images only frame photos;
    on a JPEG only texture and found supplied files are left out. A piece of an odd colour must cover min_px flat
    pixels (default 30). An odd
    piece within 20 px of photograph texture that no frame or supplied file accounts for goes to a person; when
    photograph texture of 1% of the image or more lies outside every frame and found supplied file, every odd piece
    goes to a person."""
    cv2 = _cv2()
    tol = r3._tol(path, a)
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    photo = r3._photo_mask(path, a)                       # texture blocks and the boxes of found supplied files
    frames, boxes = _photo_frames(path, a, rgb, tol)
    tex_only = r3._photo_mask(path, {'photos': [], '_asset_dirs': a.get('_asset_dirs')})
    found = np.zeros((h, w), bool)
    import objective_ops_r2 as r2
    for name in a.get('photos', []):
        try:
            page, box, state = r2._asset_box(path, a, name, 0)
        except FileNotFoundError:
            box = None
        if box is not None:
            x0, y0, x1, y1 = (int(round(v)) for v in box)
            found[max(0, y0 - 8):y1 + 8, max(0, x0 - 8):x1 + 8] = True
    covered = photo | frames
    outside = ~covered
    flat = r3._flat(rgb, 2 if not r3._lossy(path) else 6) & outside
    if flat.sum() < 200:
        return PERSON, {'reason': 'almost no flat designed area found'}
    off = flat & ~r3._near_mask(rgb, a['hexes'], tol)
    loose = tex_only & ~found & ~frames
    near_photo = cv2.dilate((tex_only & ~frames).astype(np.uint8), np.ones((41, 41), np.uint8)) > 0
    everything_unsure = loose.sum() >= 0.01 * loose.size
    bad, unsure = {}, {}
    for comp, st in r3._components(off, a.get('min_px', r3.MIN_COMPONENT)):
        colour = r3._to_hex(np.median(rgb[comp], axis=0))
        target = unsure if everything_unsure or (comp & near_photo).any() else bad
        target[colour] = target.get(colour, 0) + int(st[4])
    top = lambda d: [f'{c} ({n} px)' for c, n in sorted(d.items(), key=lambda kv: -kv[1])[:5]]
    ev = {'frames': boxes[:6]}
    if bad:
        return 'fail', dict(ev, outside_palette=top(bad))
    if unsure:
        return PERSON, dict(ev, reason='colours outside the palette only next to a photograph no frame accounts for', colours=top(unsure))
    return 'pass', dict(ev, palette=a['hexes'])


# ---------------------------------------------------------------- a placed photo against its supplied file


def _placements(path, a):
    """Every placement of the named supplied files found (photo, or photos), warped back onto the file (as in
    v2_vs_source), that shows min_shown of the file or more (default 0.3): [(name, where, src, back, valid)]."""
    names = [a['photo']] if a.get('photo') else a['photos']
    out = []
    for name in names:
        try:
            regs = pa._register(path, a, name, False)
        except FileNotFoundError:
            continue
        for where, src, back, valid, inside, scale, covers in regs:
            if valid.mean() >= a.get('min_shown', 0.3):
                out.append((name, where, src, back, valid))
    return out


def _worst(res, path, a):
    if not res:
        return PERSON, {'reason': 'supplied photo not found'}
    for want in ('fail', PERSON):
        for st, ev in res:
            if st == want:
                return st, ev
    if a.get('every') and pa._unmatched_photos(path, a, a.get('all_photos') or ([a['photo']] if a.get('photo') else a['photos'])):
        return PERSON, {'reason': 'a photograph shown is not matched to a supplied file, so not every one was checked'}
    return 'pass', res[0][1] if len(res) == 1 else {'placements': len(res), 'first': res[0][1]}


def op_shadow_detail(path, a):
    """Shadows of a placed photo keep their detail against the supplied file (not blocked up to solid black).
    Shadows: 16 px tiles of the supplied file whose mean lightness is shadow_L or less (Lab L, default 30) and whose
    lightness varies (std 1.5 or more). In the placement: crushed pixels are those at black_L or less (default 4)
    where the supplied file is lighter than black_L + 6. Pass when crushed pixels are crushed_pass or less of the
    shadow area (default 0.02) and the median shadow tile keeps detail_pass of its lightness variation or more
    (default 0.6); fail when crushed pixels are crushed_fail of the shadow area or more (default 0.25); a person
    otherwise (or when shadows cover under min_shadow_tiles tiles, default 4). Placements as in _placements
    (min_shown); every placement found is judged and the worst answer stands; none found: a person."""
    res = []
    for name, where, src, back, valid in _placements(path, a):
        ls, lb = pa._lab(src)[..., 0], pa._lab(back)[..., 0]
        tiles = []
        for sl in pa._tiles(valid, 16, 0.95):
            if ls[sl].mean() <= a.get('shadow_L', 30) and ls[sl].std() >= 1.5:
                tiles.append(sl)
        if len(tiles) < a.get('min_shadow_tiles', 4):
            res.append((PERSON, {'photo': name, 'reason': 'too few shadow areas to judge', 'tiles': len(tiles)}))
            continue
        sh = np.zeros(valid.shape, bool)
        for sl in tiles:
            sh[sl] = True
        bl = a.get('black_L', 4)
        crushed = float(((lb <= bl) & (ls > bl + 6) & sh).sum() / sh.sum())
        kept = float(np.median([lb[sl].std() / max(ls[sl].std(), 1e-3) for sl in tiles]))
        ev = {'photo': name, 'where': where, 'shadow_tiles': len(tiles), 'crushed_share': round(crushed, 4), 'detail_kept': round(kept, 2)}
        if crushed <= a.get('crushed_pass', 0.02) and kept >= a.get('detail_pass', 0.6):
            res.append(('pass', ev))
        elif crushed >= a.get('crushed_fail', 0.25):
            res.append(('fail', dict(ev, reason='shadow detail blocked up to solid black')))
        else:
            res.append((PERSON, dict(ev, reason='shadows darker or flatter in places; a person judges')))
    return _worst(res, path, a)


def op_clip_white(path, a):
    """No part of a placed photo is clipped to featureless white. Clipped: pixels of the placement with every channel
    clip_level or more (default 250) in one piece of clip_px or more (default 0.0002 of the photo's area, at least
    30 px). Pass when no such piece exists anywhere in the photo; a clipped piece goes to a person (the code does
    not place the dial itself, so it never fails). Placements as in _placements (min_shown); with
    every, a photograph shown that no named file accounts for sends a pass to a person. No placement found: a
    person."""
    cv2 = _cv2()
    res = []
    for name, where, src, back, valid in _placements(path, a):
        clip = (back >= a.get('clip_level', 250)).all(axis=2) & valid
        n, labels, stats, _ = cv2.connectedComponentsWithStats(clip.astype(np.uint8), connectivity=8)
        min_px = max(30, int(a.get('clip_px', 0.0002) * valid.sum()))
        pieces = [int(stats[i][4]) for i in range(1, n) if stats[i][4] >= min_px]
        ev = {'photo': name, 'where': where, 'clipped_pieces': len(pieces), 'largest_px': max(pieces, default=0), 'min_px': min_px}
        res.append(('pass', ev) if not pieces else (PERSON, dict(ev, reason='clipped white areas found; a person checks whether they are on the dial')))
    return _worst(res, path, a)


# ---------------------------------------------------------------- the white border of a restored print


def _border_band(lab, filled, a, min_width, base=(3, 8)):
    cv2 = _cv2()
    dist = cv2.distanceTransform(filled, cv2.DIST_L2, 5)
    L = lab[..., 0]
    grad = np.abs(L - cv2.GaussianBlur(L, (0, 0), 1.5))
    grad = cv2.GaussianBlur(grad, (0, 0), 1.0)
    stat = []
    for t in range(1, 120):
        r = (dist >= t) & (dist < t + 1)
        stat.append(float(np.median(grad[r])) if r.sum() >= 200 else np.nan)
    stat = np.array(stat)
    base_c = np.nanmedian(stat[base[0]:base[1]])
    for t in range(base[1], len(stat)):
        if np.isfinite(stat[t]) and stat[t] >= a.get('border_jump', 2.5) * max(base_c, 0.05):
            width = t + 1
            if width < min_width:
                return None, width
            border = (dist >= 3) & (dist <= width - 3)
            if np.median(L[border]) < a.get('border_min_L', 60):
                return None, width
            return border, width
    return None, None


def _border_mask(src, a=None):
    """The white border of a scanned print, on the supplied scan: the print is the largest piece away from the
    backdrop colour of the scan's outer ring (Lab distance 6 or more), filled, or the whole scan when the print
    fills it; the border is the band of the print from its edge inwards up to the picture, found as the first
    distance from the edge (1 px steps) at which the median local contrast of that ring rises to border_jump times
    (default 2.5) the contrast of the outermost rings. The band is kept 3 px clear of both edges, must be 12 px wide
    or more (8 px for a print filling the scan, and then no wider than edge_border_max of the scan's short side,
    default 0.04) and light (median lightness border_min_L or more, default 60). Returns (mask, width in px) or
    (None, reason)."""
    cv2 = _cv2()
    a = a or {}
    lab = pa._lab(src)
    h, w = lab.shape[:2]
    ring = np.concatenate([lab[:6].reshape(-1, 3), lab[-6:].reshape(-1, 3), lab[:, :6].reshape(-1, 3), lab[:, -6:].reshape(-1, 3)])
    bg = np.median(ring, axis=0)
    away = (np.sqrt(((lab - bg) ** 2).sum(axis=2)) >= 6).astype(np.uint8)
    away = cv2.morphologyEx(away, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(away, connectivity=8)
    if n >= 2:
        k = 1 + int(np.argmax(stats[1:, 4]))
        if stats[k][4] >= 0.3 * h * w:
            cnts, _ = cv2.findContours((labels == k).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            filled = np.zeros((h, w), np.uint8)
            cv2.drawContours(filled, cnts, -1, 1, -1)
            border, width = _border_band(lab, filled, a, 12)
            if border is not None:
                return border, width
    whole = np.zeros((h, w), np.uint8)                   # the print fills the scan: its border is the scan's edge band
    whole[1:-1, 1:-1] = 1
    border, width = _border_band(lab, whole, a, 8, (2, 7))
    if border is not None and width <= a.get('edge_border_max', 0.04) * min(h, w):
        return border, width
    return None, 'no white border found'


def op_border_cast(path, a):
    """The white border of a restored print, measured on the deliverable where the supplied scan's border lies (the
    scan found and its placement warped back). Mean Lab a* and b* of the border (at least min_border_px pixels) and
    its cast hue (degrees, a* towards b*). cast 'red': pass when a* is red_pass or less (default 2: no red or magenta
    in it); fail when a* is red_fail or more (default 6) and the hue lies from -90 to 40 degrees (magenta to red); a
    person otherwise. cast 'green': pass when a* is -green_pass or more (default 2); fail when a* is -green_fail or
    less (default 6) and the hue lies from 120 to 250 degrees (green to cyan); a person otherwise. cast 'yellow'
    (whites still yellow-orange): fail when b* is yellow_fail or more (default 12) and the hue lies from 40 to 100
    degrees; never a pass (skin is not read); a person otherwise."""
    res = []
    for name, where, src, back, valid in _placements(path, a):
        border, width = _border_mask(src, a)
        if border is None:
            res.append((PERSON, {'photo': name, 'reason': f'the print border could not be found on the supplied scan ({width})'}))
            continue
        m = border & valid
        if m.sum() < a.get('min_border_px', 2000):
            res.append((PERSON, {'photo': name, 'reason': 'too little of the border shown', 'border_px': int(m.sum())}))
            continue
        lb = pa._lab(back)
        A, B, L = float(lb[..., 1][m].mean()), float(lb[..., 2][m].mean()), float(lb[..., 0][m].mean())
        hue = float(np.degrees(np.arctan2(B, A)))
        ev = {'photo': name, 'where': where, 'border_px': int(m.sum()), 'border_width': width, 'L': round(L, 1), 'a': round(A, 1), 'b': round(B, 1), 'hue': round(hue, 0)}
        cast = a['cast']
        if cast == 'red':
            if A <= a.get('red_pass', 2):
                st = 'pass'
            elif A >= a.get('red_fail', 6) and -90 <= hue <= 40:
                st = 'fail'
            else:
                st = PERSON
        elif cast == 'green':
            if A >= -a.get('green_pass', 2):
                st = 'pass'
            elif A <= -a.get('green_fail', 6) and (120 <= hue <= 250 or -240 <= hue <= -110):
                st = 'fail'
            else:
                st = PERSON
        else:
            st = 'fail' if B >= a.get('yellow_fail', 12) and 40 <= hue <= 100 else PERSON
        res.append((st, ev))
    return _worst(res, path, a)


# ---------------------------------------------------------------- visible grain


def _photos_in(path, a):
    """The photographs to read: in a PDF every embedded picture that is photo-like (min_photo_share of the page or
    more, 64 grey levels or more, no transparency; a transparent picture with 64 grey levels or more might be a
    cut-out photograph, so the read is then not complete); on an image, every area of photograph blocks
    (_busy_blocks on lossless images, texture on JPEG) of 2% of the image or more (its box, shrunk by 6 px).
    Returns [(where, rgb array)] and whether the read is complete (only a PDF can be)."""
    cv2 = _cv2()
    out = []
    if path.suffix.lower() == '.pdf':
        import pymupdf
        doc = pymupdf.open(path)
        complete = True
        for page in doc:
            area = page.rect.width * page.rect.height
            for info in page.get_image_info(xrefs=True):
                b = info['bbox']
                if not info.get('xref') or (b[2] - b[0]) * (b[3] - b[1]) < a.get('min_photo_share', 0.02) * area:
                    continue
                pix = pymupdf.Pixmap(doc, info['xref'])
                see_through = pix.alpha or doc.xref_get_key(info['xref'], 'SMask')[0] != 'null'
                if pix.n - pix.alpha < 3:
                    pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
                y = arr @ np.array([0.299, 0.587, 0.114])
                if len(np.unique(np.round(y))) < 64:
                    continue
                if see_through:
                    complete = False
                    continue
                out.append((f'page {page.number + 1} image {info["xref"]}', np.ascontiguousarray(arr)))
        return out, complete
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    if r3._lossy(path):
        tex = r3._textured(rgb)
        tex = np.pad(tex, ((0, h - tex.shape[0]), (0, w - tex.shape[1])))
    else:
        tex = _busy_blocks(rgb, a)
    tex = cv2.morphologyEx(tex.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((33, 33), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(tex, connectivity=8)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 0.02 * h * w:
            continue
        out.append((f'area {x},{y},{x + bw},{y + bh}', rgb[y + 6:y + bh - 6, x + 6:x + bw - 6].astype(np.uint8)))
    return out, False


def _busy_blocks(rgb, a, block=16):
    """Photograph blocks of a lossless image (a two-colour photo too): 16 px blocks with block_colours or more
    distinct exact colours (default 40) and no colour covering more than block_top of the block (default 0.3); flat
    grounds, panels and anti-aliased type are mostly one or two exact colours."""
    h, w = rgb.shape[:2]
    by, bx = h // block, w // block
    q = rgb[:by * block, :bx * block].astype(np.int64)
    code = (q[..., 0] << 16) | (q[..., 1] << 8) | q[..., 2]
    blocks = code.reshape(by, block, bx, block).transpose(0, 2, 1, 3).reshape(by, bx, -1)
    out = np.zeros((by, bx), bool)
    for yy in range(by):
        for xx in range(bx):
            u, c = np.unique(blocks[yy, xx], return_counts=True)
            out[yy, xx] = len(u) >= a.get('block_colours', 40) and c.max() <= a.get('block_top', 0.3) * c.sum()
    full = np.kron(out, np.ones((block, block), bool)).astype(bool)
    return np.pad(full, ((0, h - full.shape[0]), (0, w - full.shape[1])))


def _grain(rgb):
    """Grain of a photograph: the robust spread (1.4826 x median absolute deviation) of its fine detail (lightness
    less a 1.5 px Gaussian blur) over its smoothest 40% (by the gradient of a 3 px blur), as a share of its tonal
    span (1st to 99th percentile of lightness)."""
    cv2 = _cv2()
    y = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    span = float(np.percentile(y, 99) - np.percentile(y, 1))
    if span < 20:
        return None, span
    fine = y - cv2.GaussianBlur(y, (0, 0), 1.5)
    sm = cv2.GaussianBlur(y, (0, 0), 3)
    gx, gy = cv2.Sobel(sm, cv2.CV_32F, 1, 0), cv2.Sobel(sm, cv2.CV_32F, 0, 1)
    grad = np.hypot(gx, gy)
    calm = grad <= np.percentile(grad, 40)
    calm[:4, :] = calm[-4:, :] = calm[:, :4] = calm[:, -4:] = False
    r = fine[calm]
    if r.size < 2000:
        return None, span
    spread = 1.4826 * float(np.median(np.abs(r - np.median(r))))
    return spread / span, span


def op_grain(path, a):
    """Visible grain in every photograph shown (see _photos_in): grain as measured by _grain (fine-detail spread over
    the photo's smoothest parts, as a share of its tonal span). Pass when every photograph's grain is grain_pass or
    more (default 0.02); fail when one is grain_fail or less (default 0.006); a person otherwise. No photograph:
    a person on an image; on a PDF (every embedded picture read) a fail when expect_photo, else a pass when
    none_ok. On a PDF holding a transparent picture with many tones (not read), a pass goes to a person."""
    photos, complete = _photos_in(path, a)
    if not photos:
        if complete and a.get('none_ok'):
            return 'pass', {'reason': 'no photograph in the file'}
        if complete and a.get('expect_photo'):
            return 'fail', {'reason': 'no photograph in the file'}
        return PERSON, {'reason': 'no photograph found'}
    vals, st = [], 'pass'
    for where, rgb in photos:
        g, span = _grain(rgb)
        if g is None:
            vals.append({'where': where, 'reason': 'too small or too flat to measure', 'span': round(span, 1)})
            st = PERSON if st == 'pass' else st
            continue
        vals.append({'where': where, 'grain': round(g, 4)})
        if g <= a.get('grain_fail', 0.006):
            st = 'fail'
        elif g < a.get('grain_pass', 0.02) and st == 'pass':
            st = PERSON
    ev = {'photos': vals[:8]}
    if st == PERSON:
        ev['reason'] = 'grain too faint to call; a person judges'
    if st == 'pass' and path.suffix.lower() == '.pdf' and not complete:
        st, ev['reason'] = PERSON, 'a transparent picture with many tones (perhaps a cut-out photograph) was not read'
    return st, ev


# ---------------------------------------------------------------- counters of a wordmark


def op_counters_open(path, a):
    """Every enclosed counter of a wordmark is open to the ground. The wordmark: every OCR line (confidence min_conf
    or more, default 60) whose whole text matches word (a pattern, such as NORTHGROVE), after at most one stray
    mark of one or two characters (a symbol read as a letter); a line with other words (a running header or footer)
    is text, not the mark. In its box, padded by 15% of its height: the ground is the
    median colour of the padded box's outer 2 px ring; ink is every pixel whose largest channel difference from the
    ground is ink_cut (default 0.5) of the ink contrast (the 98th percentile difference) or more; holes are the
    non-ink regions not connected to the box edge of hole_min of the box area or more (default 0.0015). Pass when a
    line shows counters holes or more (the number of enclosed counters the word has) and every hole's median colour
    is within hole_pass (default 12) of the ground; fail when a hole differs from the ground by hole_fail or more
    (default 40: a counter filled in); a person otherwise (fewer holes found, a hole between the bands, or no
    wordmark read: an absence on an image)."""
    import re
    from objective_ops import canon, merged, text_layers
    cv2 = _cv2()
    rgb = r3._pixels(str(path))
    H, W = rgb.shape[:2]
    layer = merged(text_layers(path))
    marks = [l for l in layer.lines if l.conf >= a.get('min_conf', 60) and re.fullmatch(r'\W*(?:\w{1,2}\W+)?(?:' + a['word'] + r')\W*', canon(l.text), re.I)]
    if not marks:
        return PERSON, {'reason': 'no wordmark read (the mark may be absent or drawn differently)'}
    res = []
    for l in marks:
        x0, y0, x1, y1 = l.bbox
        pad = 0.15 * (y1 - y0) + 2
        X0, Y0, X1, Y1 = int(max(0, x0 - pad)), int(max(0, y0 - pad)), int(min(W, x1 + pad)), int(min(H, y1 + pad))
        crop = rgb[Y0:Y1, X0:X1].astype(float)
        ring = np.concatenate([crop[:2].reshape(-1, 3), crop[-2:].reshape(-1, 3), crop[:, :2].reshape(-1, 3), crop[:, -2:].reshape(-1, 3)])
        ground = np.median(ring, axis=0)
        diff = np.abs(crop - ground).max(axis=2)
        contrast = float(np.percentile(diff, 98))
        item = {'text': l.text, 'box': [X0, Y0, X1, Y1], 'ground': r3._to_hex(ground)}
        if contrast < 40:
            res.append((PERSON, dict(item, reason='the wordmark barely stands out from its ground')))
            continue
        ink = diff >= a.get('ink_cut', 0.5) * contrast
        bg = (~ink).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(bg, connectivity=4)
        edge = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])))
        holes = []
        for i in range(1, n):
            if i in edge or stats[i][4] < a.get('hole_min', 0.0015) * bg.size:
                continue
            c = np.median(crop[labels == i], axis=0)
            holes.append(float(np.abs(c - ground).max()))
        item.update(holes=len(holes), worst_hole_diff=round(max(holes, default=0.0), 1))
        if any(d >= a.get('hole_fail', 40) for d in holes):
            res.append(('fail', dict(item, reason='a counter is filled, not open to the ground')))
        elif len(holes) >= a['counters'] and all(d <= a.get('hole_pass', 12) for d in holes):
            res.append(('pass', item))
        else:
            res.append((PERSON, dict(item, reason='not every counter found clearly open; a person checks')))
    for want in ('fail', PERSON):
        for st, ev in res:
            if st == want:
                return st, ev
    return 'pass', {'marks': [ev for _, ev in res][:4]}


def _word_part(ink):
    """The word of a symbol-and-word mark: the band of rows holding the most ink (a rule or line of text above or
    below, apart from it by empty rows, is left out), then the ink right of the widest empty column gap (the gap
    between symbol and word, when 2% of the width or more), cropped to its ink. Returns the mask, or None."""
    rows = ink.any(axis=1)
    runs, start = [], None
    for i, v in enumerate(list(rows) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if not runs:
        return None
    r0, r1 = max(runs, key=lambda r: ink[r[0]:r[1]].sum())
    ink = ink[r0:r1]
    cols = np.nonzero(ink.any(axis=0))[0]
    if len(cols) < 10:
        return None
    gaps = np.diff(cols)
    k = int(np.argmax(gaps))
    x0 = cols[k + 1] if gaps[k] >= max(4, 0.02 * ink.shape[1]) else cols[0]
    part = ink[:, x0:cols[-1] + 1]
    rr = np.nonzero(part.any(axis=1))[0]
    return part[rr[0]:rr[-1] + 1] if len(rr) else None


def op_lettering_kept(path, a):
    """The lettering of a supplied word-and-symbol mark is kept: not retyped, stretched or closed up. The supplied
    mark (mark, an SVG) is drawn at 1600 px wide and its word taken as the ink right of the gap after the symbol; on
    the deliverable every wordmark line read as in v2_counters_open_r4p gives its word the same way (ink against the
    ground round it, kept to the colour of the word's letters within word_colour_tol, default 40, so a symbol in
    another colour is left out). The two words' ink boxes are compared: aspect (width over height) and, after scaling the
    deliverable's word to the supplied word's box, the correlation of the two ink masks (both softened by a 1 px
    blur). Pass when the aspect differs by aspect_pass or less (default 0.03) and the correlation is min_ncc or more
    (default 0.9); fail when the correlation is fail_ncc or more (default 0.85: the same letters) and the aspect
    differs by aspect_fail or more (default 0.1: stretched or closed up); a person otherwise (or when no wordmark
    is read: an absence on an image)."""
    import re
    from objective_ops import canon, merged, text_layers
    cv2 = _cv2()
    im = np.asarray(base.svg_render(base.asset_path(a, a['mark']), 1600).convert('L'))
    tw = _word_part(im < 128)
    if tw is None:
        return PERSON, {'reason': 'the supplied mark could not be read'}
    t_ar = tw.shape[1] / tw.shape[0]
    rgb = r3._pixels(str(path))
    H, W = rgb.shape[:2]
    layer = merged(text_layers(path))
    marks = [l for l in layer.lines if l.conf >= a.get('min_conf', 60) and re.fullmatch(r'\W*(?:\w{1,2}\W+)?(?:' + a['word'] + r')\W*', canon(l.text), re.I)]
    if not marks:
        return PERSON, {'reason': 'no wordmark read (the mark may be absent or drawn differently)'}
    soft = lambda m: cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.0)
    res = []
    for l in marks:
        x0, y0, x1, y1 = l.bbox
        pad = 0.15 * (y1 - y0) + 2
        X0, Y0, X1, Y1 = int(max(0, x0 - pad)), int(max(0, y0 - pad)), int(min(W, x1 + pad)), int(min(H, y1 + pad))
        crop = rgb[Y0:Y1, X0:X1].astype(float)
        ring = np.concatenate([crop[:2].reshape(-1, 3), crop[-2:].reshape(-1, 3), crop[:, :2].reshape(-1, 3), crop[:, -2:].reshape(-1, 3)])
        diff = np.abs(crop - np.median(ring, axis=0)).max(axis=2)
        contrast = float(np.percentile(diff, 98))
        ink = diff >= 0.5 * contrast
        dw = None
        if contrast >= 40 and ink.any():
            cols = np.nonzero(ink.any(axis=0))[0]
            right = ink.copy()
            right[:, :cols[0] + int(0.7 * (cols[-1] - cols[0]))] = False       # the last 30% of the ink: word letters
            word_c = np.median(crop[right], axis=0) if right.any() else None
            if word_c is not None:
                dw = _word_part(ink & (np.abs(crop - word_c).max(axis=2) <= a.get('word_colour_tol', 40)))
        if dw is None or dw.shape[0] < 12:
            res.append((PERSON, {'text': l.text, 'reason': 'the word of the mark could not be read clearly'}))
            continue
        d_ar = dw.shape[1] / dw.shape[0]
        scaled = cv2.resize(dw.astype(np.uint8) * 255, (tw.shape[1], tw.shape[0]), interpolation=cv2.INTER_AREA) / 255.0
        ncc = pa._ncc(soft(scaled), soft(tw))
        dev = abs(d_ar / t_ar - 1)
        ev = {'text': l.text, 'box': [X0, Y0, X1, Y1], 'aspect_change': round(dev, 3), 'ncc': round(ncc, 3)}
        if dev <= a.get('aspect_pass', 0.03) and ncc >= a.get('min_ncc', 0.9):
            res.append(('pass', ev))
        elif ncc >= a.get('fail_ncc', 0.85) and dev >= a.get('aspect_fail', 0.1):
            res.append(('fail', dict(ev, reason='the lettering is stretched or closed up')))
        else:
            res.append((PERSON, dict(ev, reason='the lettering differs from the supplied mark; a person judges')))
    for want in ('fail', PERSON):
        for st, ev in res:
            if st == want:
                return st, ev
    return 'pass', {'marks': [ev for _, ev in res][:4]}


# ---------------------------------------------------------------- no photo texture in a placed wordmark (PDF)


def op_pdf_flat_marks(path, a):
    """No photo texture (such as a knit weave) shows round or between the letters of a placed wordmark, read from
    every picture placed in the PDF (all are read, so the read is complete). A picture with transparency is a mark
    when its visible pixels (alpha 128 or more) are one ink: the spread of their colour is ink_std or less (default
    6); a picture with transparency and more spread than that goes to a person. A picture without transparency of
    min_share of the page or more (default 0.001) must be one of the allowed supplied photos (allowed, found by its
    features); one found to be a named textured file (textured, such as the knit sweater photo) fails; any other
    goes to a person. Not a PDF: a person."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'only a PDF is read picture by picture'}
    import pymupdf
    cv2 = _cv2()
    doc = pymupdf.open(path)
    gray = lambda arr: cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    def load(name):
        im = np.asarray(base._load_gray(base.asset_path(a, name)))
        return im
    try:
        textured = {n: load(n) for n in a.get('textured', [])}
        allowed = {n: load(n) for n in a.get('allowed', [])}
    except FileNotFoundError as e:
        return PERSON, {'reason': f'supplied file not found: {e}'}
    marks, photos, unsure, bad = 0, [], [], []
    for page in doc:
        area = page.rect.width * page.rect.height
        for info in page.get_image_info(xrefs=True):
            xref = info.get('xref')
            b = info['bbox']
            if not xref or (b[2] - b[0]) * (b[3] - b[1]) < a.get('min_share', 0.001) * area:
                continue
            pix = pymupdf.Pixmap(doc, xref)
            smask = doc.xref_get_key(xref, 'SMask')
            alpha = None
            if pix.alpha:
                alpha = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., -1]
            elif smask[0] == 'xref':
                mp = pymupdf.Pixmap(doc, int(smask[1].split()[0]))
                if (mp.width, mp.height) == (pix.width, pix.height):
                    alpha = np.frombuffer(mp.samples, np.uint8).reshape(mp.height, mp.width, mp.n)[..., 0]
            if pix.n - pix.alpha < 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            rgb = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
            where = f'page {page.number + 1} image {xref}'
            if alpha is not None:
                vis = rgb[alpha >= 128].astype(float)
                spread = float(vis.std(axis=0).max()) if len(vis) else 0.0
                if spread <= a.get('ink_std', 6):
                    marks += 1
                else:
                    unsure.append({'where': where, 'reason': 'a transparent picture with more than one ink', 'spread': round(spread, 1)})
                continue
            g = gray(np.ascontiguousarray(rgb))
            hit = next((n for n, t in textured.items() if base.find_asset(g, t)[2] == 'found'), None)
            if hit:
                bad.append({'where': where, 'photo': hit})
                continue
            ok = next((n for n, t in allowed.items() if base.find_asset(g, t)[2] == 'found'), None)
            (photos.append({'where': where, 'photo': ok}) if ok else unsure.append({'where': where, 'reason': 'a placed picture not matched to an allowed photo'}))
    if bad:
        return 'fail', {'textured_photo_placed': bad[:3]}
    if unsure:
        return PERSON, {'reason': 'a placed picture could not be cleared', 'pictures': unsure[:3]}
    return 'pass', {'flat_marks': marks, 'photos': photos[:4]}


OPS = {
    'v2_palette_frames_r4p': op_palette_frames,
    'v2_shadow_detail_r4p': op_shadow_detail,
    'v2_clip_white_r4p': op_clip_white,
    'v2_border_cast_r4p': op_border_cast,
    'v2_grain_r4p': op_grain,
    'v2_counters_open_r4p': op_counters_open,
    'v2_lettering_kept_r4p': op_lettering_kept,
    'v2_pdf_flat_marks_r4p': op_pdf_flat_marks,
}
