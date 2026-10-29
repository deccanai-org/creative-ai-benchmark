"""Round 4 operations for MOTION-11 (STATIC FOX): the films' sound, their shots against the supplied captures, the
mascot's movement and the scale of capture footage, 2026-10-28. Op names end in _r4m.

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person";
nothing passes on a failed read, and a "person" answer carries a reason. Films are read completely: every frame is
decoded (at 640 px wide), and the sound track is decoded whole, so an absence over the whole film is decisive.

Shared reading of capture footage (_footage): a frame is footage where textured 16 px blocks (24 or more colours,
grey spread 6 levels or more) cover a tenth of it or more; the textured area is cut out and compared, as a small
grey picture, with every frame of the six supplied captures; its capture is the one correlating best at min_ncc
(0.6) or more, margin (0.15) ahead of any other (the numbers op_footage uses). The matched source frame and its two
neighbours are then aligned to the film frame by SIFT features and a RANSAC similarity transform (uniform scale,
rotation, shift), which gives the footage's scale against its recorded pixels; the source frames within 8 of the
match are warped the same way and the closest (median difference) is the one the colour checks compare. Consecutive footage frames of one capture whose source frames run on are a shot.
"""
from __future__ import annotations

OPS: dict = {}

import functools
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

import objective_ops as base
from objective_ops import PERSON

DECODE_W = 640            # films and capture frames are compared at 640 px wide
MIN_NCC, MARGIN = 0.6, 0.15
SR = 8000                 # sound is compared at 8 kHz, mono
NEAR = 8                  # source frames within 8 of the correlation match are tried for the exact one


# ================================================================ decoding

def _probe(key: str, stream='v:0', entries='stream=width,height,r_frame_rate'):
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', stream, '-show_entries', entries, '-of', 'csv=p=0',
                          key], capture_output=True, text=True, timeout=120).stdout.strip()
    return out


def _decode(key: str, width: int = DECODE_W):
    """Every frame of a film at width px (area-averaged), as an (n, h, w, 3) uint8 array; its fps and full size."""
    w, h, rate = _probe(key).split('\n')[0].split(',')[:3]
    w, h = int(w), int(h)
    num, den = rate.split('/')
    fps = float(num) / float(den or 1)
    hh = max(2, int(round(h * width / w / 2)) * 2)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', key, '-vf', f'scale={width}:{hh}:flags=area', '-f', 'rawvideo',
                          '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True, timeout=900).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, hh, width, 3), fps, (w, h)


@functools.lru_cache(maxsize=3)
def _film(key: str):
    return _decode(key)


@functools.lru_cache(maxsize=2)
def _bank(dirs: tuple):
    """The six supplied captures: their frames at 640 px, full size, and small grey signatures of every frame."""
    out = {}
    for i in range(1, 7):
        try:
            p = base.asset_path({'_asset_dirs': list(dirs)}, f'staticfox_captures/staticfox_capture_0{i}.mp4')
        except FileNotFoundError:
            continue
        frames, fps, size = _decode(str(p))
        out[i] = (frames, size, np.stack([_sig(f) for f in frames]))
    return out


def _gray(rgb):
    import cv2
    return cv2.cvtColor(np.ascontiguousarray(rgb, np.uint8), cv2.COLOR_RGB2GRAY)


def _sig(rgb):
    """A frame as a zero-mean, unit-length 160 x 90 grey picture (for correlation)."""
    import cv2
    g = cv2.resize(_gray(rgb), (160, 90), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
    g -= g.mean()
    return g / (np.linalg.norm(g) + 1e-6)


def _textured(rgb, b: int = 16):
    """Textured 16 px blocks: 24 or more colours (5 bits a channel) and a grey spread of 6 levels or more."""
    h, w = rgb.shape[:2]
    by, bx = h // b, w // b
    q = (rgb[:by * b, :bx * b] >> 3).astype(np.int32)
    code = (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]
    blocks = np.sort(code.reshape(by, b, bx, b).transpose(0, 2, 1, 3).reshape(by, bx, -1), axis=2)
    uniq = 1 + (np.diff(blocks, axis=2) != 0).sum(axis=2)
    g = rgb[:by * b, :bx * b].astype(np.float32).mean(axis=2).reshape(by, b, bx, b).transpose(0, 2, 1, 3).reshape(by, bx, -1)
    return (uniq >= 24) & (g.std(axis=2) >= 6)


# ================================================================ capture footage

def _match_sig(sig, bank):
    """(capture, source frame, score, second best capture's score) for one signature."""
    best = {}
    for n, (_, _, sigs) in bank.items():
        sc = sigs @ sig
        j = int(np.argmax(sc))
        best[n] = (float(sc[j]), j)
    order = sorted(best.items(), key=lambda kv: -kv[1][0])
    top = order[0]
    second = order[1][1][0] if len(order) > 1 else -1.0
    return top[0], top[1][1], top[1][0], second


@functools.lru_cache(maxsize=3)
def _footage(key: str, dirs: tuple):
    """Per frame: textured share and, for footage frames, the matched capture and source frame (see the module
    docstring); and the shots, as lists of frame numbers."""
    frames, fps, size = _film(key)
    bank = _bank(dirs)
    recs = []
    for f, rgb in enumerate(frames):
        tex = _textured(rgb)
        rec = {'f': f, 'tex': float(tex.mean())}
        if rec['tex'] >= 0.10 and bank:
            ys, xs = np.nonzero(tex)
            crop = rgb[ys.min() * 16:(ys.max() + 1) * 16, xs.min() * 16:(xs.max() + 1) * 16]
            n, j, score, second = _match_sig(_sig(crop), bank)
            rec.update(score=round(score, 3), second=round(second, 3))
            if score >= MIN_NCC and score - second >= MARGIN:
                rec.update(capture=n, src=j)
            else:
                left = _without_mascot(rgb, tex, dirs)
                if left is not None and left < 0.10:   # the texture is the supplied mascot, not footage
                    rec.update(tex=round(left, 3), mascot=True)
        recs.append(rec)
    _features_fallback(frames, recs, bank)
    shots, cur = [], []
    for rec in recs:   # consecutive frames of one capture are one shot
        if 'capture' in rec and cur and recs[cur[-1]].get('capture') == rec['capture'] and rec['f'] == cur[-1] + 1:
            cur.append(rec['f'])
            continue
        if cur:
            shots.append(cur)
        cur = [rec['f']] if 'capture' in rec else []
    if cur:
        shots.append(cur)
    return recs, shots, fps, size


SCRAP = 'staticfox_scrap_transparent.png'
STRIDE = 8                # footage the correlation misses (cropped or enlarged) is searched for every 8th source frame


def _search(img, bank, cands):
    """The capture frame among cands [(capture, frame)] that SIFT aligns with the most inliers: (capture, frame,
    inliers, second capture's best inliers), refined over the 4 frames either side."""
    per = {}
    for n, j in cands:
        sim = _similarity(bank[n][0][j], img)
        if sim and sim[1] > per.get(n, (0, -1))[0]:
            per[n] = (sim[1], j)
    if not per:
        return None
    order = sorted(per.items(), key=lambda kv: -kv[1][0])
    n, (inl, j) = order[0]
    second = order[1][1][0] if len(order) > 1 else 0
    for i in range(max(0, j - 4), min(len(bank[n][0]), j + 5)):
        sim = _similarity(bank[n][0][i], img)
        if sim and sim[1] > inl:
            inl, j = sim[1], i
    return n, j, inl, second


def _features_fallback(frames, recs, bank):
    """Footage frames the correlation did not match (a crop or an enlargement of the capture): the first of each
    run is searched by SIFT against every STRIDE-th frame of every capture; a capture is taken with 40 or more
    inliers and three times the next capture's; the run's next frames follow on from the source frame found. After
    a failed search the next one is made 8 frames on (frames between stay unmatched, so they go to a person)."""
    prev, failed = None, None
    for rec in recs:
        if rec['tex'] < 0.10 or 'capture' in rec or rec.get('mascot'):
            prev = None
            continue
        img = frames[rec['f']]
        if prev is not None:
            n, j = prev
            got = _search(img, bank, [(n, i) for i in range(j, min(len(bank[n][0]), j + 3))])
            if got and got[2] >= 40:
                rec.update(capture=n, src=got[1], by='features')
                prev = (n, got[1])
                continue
        if failed is not None and rec['f'] - failed < STRIDE:   # a search just failed: try again 8 frames on
            prev = None
            continue
        cands = [(n, i) for n in bank for i in range(0, len(bank[n][0]), STRIDE)]
        got = _search(img, bank, cands)
        if got and got[2] >= 40 and got[2] >= 3 * got[3]:
            rec.update(capture=got[0], src=got[1], by='features')
            prev, failed = (got[0], got[1]), None
        else:
            prev, failed = None, rec['f']


def _without_mascot(rgb, tex, dirs):
    """The textured share left once the supplied mascot cut-out, where found (SIFT, as v2_asset_found), and a 16 px
    margin round it are taken out; None when it is not found."""
    import cv2
    try:
        asset = base._load_gray(base.asset_path({'_asset_dirs': list(dirs)}, SCRAP))
    except FileNotFoundError:
        return None
    n, corners, state = base.find_asset(_gray(rgb), asset)
    if state != 'found':
        return None
    m = np.zeros(rgb.shape[:2], np.uint8)
    cv2.fillConvexPoly(m, np.asarray(corners, np.float32).reshape(-1, 2).astype(np.int32), 1)
    m = cv2.dilate(m, np.ones((33, 33), np.uint8))
    by, bx = tex.shape
    cover = m[:by * 16, :bx * 16].reshape(by, 16, bx, 16).mean(axis=(1, 3)) > 0
    return float((tex & ~cover).mean())


def _similarity(src_rgb, dst_rgb):
    """SIFT features and a RANSAC similarity transform from a source frame onto a film frame (both at 640 px):
    (2 x 3 matrix, inliers, scale), or None under 20 inliers."""
    import cv2
    cv2.setRNGSeed(0)
    sift = cv2.SIFT_create(nfeatures=3000)
    k1, d1 = sift.detectAndCompute(_gray(src_rgb), None)
    k2, d2 = sift.detectAndCompute(_gray(dst_rgb), None)
    if d1 is None or d2 is None or len(k1) < 20 or len(k2) < 20:
        return None
    pairs = cv2.BFMatcher().knnMatch(d1, d2, k=2)
    good = [p[0] for p in pairs if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < 20:
        return None
    p1 = np.float32([k1[g.queryIdx].pt for g in good])
    p2 = np.float32([k2[g.trainIdx].pt for g in good])
    A, inl = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=3.0, maxIters=4000)
    if A is None or int(inl.sum()) < 20:
        return None
    return A, int(inl.sum()), float(np.sqrt(abs(np.linalg.det(A[:, :2]))))


def _local_stats(a, b, k=15):
    import cv2
    a, b = a.astype(np.float32), b.astype(np.float32)
    ma, mb = cv2.blur(a, (k, k)), cv2.blur(b, (k, k))
    va = np.maximum(cv2.blur(a * a, (k, k)) - ma * ma, 0)
    vb = np.maximum(cv2.blur(b * b, (k, k)) - mb * mb, 0)
    cov = cv2.blur(a * b, (k, k)) - ma * mb
    return np.sqrt(vb), cov / (np.sqrt(va * vb) + 1e-6)


def _compare(src_rgb, dst_rgb, A):
    """The source frame warped onto the film frame: where both show the same detail (15 px windows correlating at
    0.8 or more where the source has texture), each channel's gain and offset (robust straight-line fit), the share
    shifted by 12 levels or more after the fit (smoothed), the share shifted one way by 25 or more, the mean
    difference per channel and the mean hue shift on saturated pixels (tones read after a 2 px blur)."""
    import cv2
    h, w = dst_rgb.shape[:2]
    src = src_rgb.astype(np.float32)
    dst = dst_rgb.astype(np.float32)
    warped = cv2.warpAffine(src, A, (w, h), flags=cv2.INTER_LINEAR)
    valid = cv2.warpAffine(np.full(src.shape[:2], 255, np.uint8), A, (w, h), flags=cv2.INTER_NEAREST) > 0
    valid = cv2.erode(valid.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    sf, ncc = _local_stats(_gray(dst_rgb), _gray(np.clip(warped, 0, 255)))
    vis = valid & (sf >= 8) & (ncc >= 0.8)
    vis = cv2.erode(vis.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    # tones are compared after a 2 px blur, so sub-pixel shifts of fine detail do not read as colour changes
    dst, warped = cv2.GaussianBlur(dst, (0, 0), 2), cv2.GaussianBlur(warped, (0, 0), 2)
    out = {'visible_share': round(float(vis.mean()), 3), 'covered': round(float(valid.mean()), 3)}
    if vis.sum() < 2000:
        return out
    gains, offs = [], []
    for ch in range(3):
        x, y = warped[..., ch][vis], dst[..., ch][vis]
        keep = np.ones(len(x), bool)
        g, o = 1.0, 0.0
        for _ in range(4):
            if keep.sum() < 100:
                break
            g, o = np.polyfit(x[keep], y[keep], 1)
            keep = np.abs(y - (g * x + o)) < 20
        gains.append(float(g))
        offs.append(float(o))
    resid = (dst - (warped * np.array(gains, np.float32) + np.array(offs, np.float32))).mean(axis=2)
    smooth = cv2.blur(np.where(vis, resid, 0).astype(np.float32), (15, 15)) / np.maximum(cv2.blur(vis.astype(np.float32), (15, 15)), 1e-3)
    shifted = float((vis & (np.abs(smooth) >= 12)).sum() / vis.sum())
    strong = vis & (np.abs(smooth) >= 25)
    sign = float(np.sign(np.median(smooth[strong]))) if strong.any() else 0.0
    one_way = float((vis & (smooth * sign >= 25)).sum() / vis.sum()) if sign else 0.0
    diff = np.abs(dst[vis] - warped[vis]).mean(axis=0)
    hsv_d = cv2.cvtColor(np.clip(dst, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    hsv_s = cv2.cvtColor(np.clip(warped, 0, 255).astype(np.uint8), cv2.COLOR_RGB2HSV)
    sat = vis & (hsv_s[..., 1] > 60) & (hsv_s[..., 2] > 40)
    dh = np.abs((hsv_d[..., 0][sat].astype(float) - hsv_s[..., 0][sat].astype(float)) * 2 + 180) % 360 - 180
    out.update(gain=[round(g, 3) for g in gains], offset=[round(o, 1) for o in offs], shifted_share=round(shifted, 3),
               one_way_share=round(one_way, 3), mean_difference=[round(float(d), 1) for d in diff],
               hue_shift_deg=round(float(np.abs(dh).mean()), 1) if sat.sum() > 500 else 0.0)
    return out


@functools.lru_cache(maxsize=2048)
def _aligned(key: str, dirs: tuple, f: int):
    """A footage frame against its source: the best of the matched source frame and its two neighbours (smallest
    mean difference where aligned): scale against the recorded pixels, inliers and the colour comparison."""
    recs, shots, fps, (W, H) = _footage(key, dirs)
    rec = recs[f]
    if 'capture' not in rec:
        return None
    import cv2
    frames = _film(key)[0]
    src_frames, (sw, sh), _ = _bank(dirs)[rec['capture']]
    sim = None
    for i in (rec['src'], rec['src'] - 1, rec['src'] + 1):
        if 0 <= i < len(src_frames):
            sim = _similarity(src_frames[i], frames[f])
            if sim is not None:
                break
    if sim is None:
        return {'aligned': False}
    A, inl, s = sim
    # the source frame itself: of the frames within NEAR of the match, the one closest to the film frame once aligned;
    # the alignment is then made again on that frame (twice, so a camera move between frames does not mislead it)
    dst = frames[f].astype(np.float32)
    h, w = dst.shape[:2]
    best_i = rec['src']
    for _ in range(2):
        valid = cv2.warpAffine(np.full(src_frames[0].shape[:2], 255, np.uint8), A, (w, h), flags=cv2.INTER_NEAREST) > 0
        best_d = None
        for i in range(max(0, best_i - NEAR), min(len(src_frames), best_i + NEAR + 1)):
            warped = cv2.warpAffine(src_frames[i].astype(np.float32), A, (w, h), flags=cv2.INTER_LINEAR)
            d = float(np.median(np.abs(dst[valid] - warped[valid])))
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        again = _similarity(src_frames[best_i], frames[f])
        if again is None:
            break
        A, inl, s = again
    return dict(_compare(src_frames[best_i], frames[f], A), src=best_i, inliers=inl, scale=round(s * W / sw, 3))


def _dirs(a):
    return tuple(a.get('_asset_dirs') or [])


def _is_film(path):
    return Path(path).suffix.lower() in ('.mp4', '.mov', '.webm', '.m4v')


# ================================================================ operations

def op_music_from_bed_r4m(path, a):
    """The film's music is taken from the supplied music file with no other track: the sound is decoded whole (8 kHz,
    mono) and cut into windows of win_s seconds (0.5) overlapping by half; each window louder than quiet_db (-45 dB
    full scale) is searched for along the whole supplied file by normalised cross-correlation. Pass: every loud
    window matches somewhere at pass_ncc (0.9) or more. Fail: no sound track or no loud window (no music), or
    fail_share (a quarter) or more of the loud windows match nowhere above fail_ncc (0.5) (another track). Anything
    else goes to a person."""
    if not _probe(str(path), 'a', 'stream=index'):
        return 'fail', {'reason': 'the film has no sound track'}
    try:
        bed = base.asset_path(a, a['asset'])
    except FileNotFoundError:
        return PERSON, {'reason': 'supplied music file not available'}

    def pcm(p):
        r = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(p), '-vn', '-ac', '1', '-ar', str(SR), '-f', 'f32le', '-'],
                           capture_output=True, timeout=300)
        return np.frombuffer(r.stdout, np.float32).astype(np.float64) if r.returncode == 0 else None
    x, y = pcm(path), pcm(bed)
    if x is None or y is None or len(y) < SR:
        return PERSON, {'reason': 'the sound could not be decoded'}
    win = int(round(a.get('win_s', 0.5) * SR))
    hop = max(1, win // 2)
    quiet = 10 ** (a.get('quiet_db', -45) / 20)
    nfft = 1 << int(np.ceil(np.log2(len(y) + win)))
    Y = np.fft.rfft(y, nfft)
    csum = np.concatenate([[0.0], np.cumsum(y * y)])
    energy = np.sqrt(np.maximum(csum[win:] - csum[:-win], 1e-12))
    scores, quiet_n = [], 0
    for s in range(0, len(x) - win + 1, hop):
        w = x[s:s + win]
        if np.sqrt(np.mean(w * w)) < quiet:
            quiet_n += 1
            continue
        c = np.fft.irfft(Y * np.conj(np.fft.rfft(w, nfft)), nfft)[:len(y) - win + 1]
        scores.append(float(np.max(c / (energy * np.linalg.norm(w) + 1e-12))))
    ev = {'loud_windows': len(scores), 'quiet_windows': quiet_n}
    if not scores:
        return 'fail', dict(ev, reason='no music heard on the sound track')
    sc = np.array(scores)
    ev.update(lowest_match=round(float(sc.min()), 3), median_match=round(float(np.median(sc)), 3),
              share_unmatched=round(float((sc < a.get('fail_ncc', 0.5)).mean()), 3))
    if sc.min() >= a.get('pass_ncc', 0.9):
        return 'pass', ev
    if (sc < a.get('fail_ncc', 0.5)).mean() >= a.get('fail_share', 0.25):
        return 'fail', dict(ev, reason='much of the sound is not found in the supplied music file')
    return PERSON, dict(ev, reason='parts of the sound match the supplied music only loosely')


def _small(key):
    import cv2
    frames = _film(key)[0]
    return np.stack([cv2.resize(_gray(f), (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32).ravel()
                     for f in frames])


def op_no_repeat_r4m(path, a):
    """No shot is repeated or looped: every frame is read (64 x 36 grey) and every pair of frames at least min_gap
    frames apart (12, half a second at 24 fps) compared (root mean square difference in grey levels). A repeat is a
    run of min_run (8) or more consecutive frames that match frames later in the film in the same order (or in
    reverse order, a ping-pong loop), while the content changes over the run: the run's frames differ from its first
    frame by min_change (4 levels) or more at most, and the match is under match_tol (3 levels) and under span_ratio
    (0.25) of that change. A still card held for a time is not a repeat (nothing changes). Pass: no run found; fail: a run found; a run matching only under person_tol
    (6 levels) goes to a person."""
    if not _is_film(path):
        return PERSON, {'reason': 'not a film'}
    v = _small(str(path))
    n = len(v)
    sq = (v * v).sum(axis=1)
    D = np.sqrt(np.maximum(sq[:, None] + sq[None, :] - 2 * v @ v.T, 0) / v.shape[1])
    gap, run_min = int(a.get('min_gap', 12)), int(a.get('min_run', 8))
    tol, ptol, ratio = a.get('match_tol', 3.0), a.get('person_tol', 6.0), a.get('span_ratio', 0.25)
    change = a.get('min_change', 4.0)
    found, near = [], []

    def scan(pairs):
        """pairs: list of (i, j) along one diagonal; record runs of matches."""
        run = []
        for i, j in pairs + [(None, None)]:
            ok = i is not None and D[i, j] < ptol
            if ok:
                run.append((i, j))
                continue
            if len(run) >= run_min:
                (i0, j0), (i1, j1) = run[0], run[-1]
                span = float(max(D[i0, p] for p, _ in run))
                d = float(np.mean([D[p, q] for p, q in run]))
                if span >= change and d < ratio * span:
                    item = {'frames': [int(i0), int(i1)], 'again_at': [int(j0), int(j1)], 'difference': round(d, 2),
                            'change_over_run': round(float(span), 2)}
                    (found if d < tol else near).append(item)
            run = []
    for d in range(gap, n):
        scan([(i, i + d) for i in range(n - d)])
    for s in range(gap, 2 * n - 2):
        scan([(i, s - i) for i in range(max(0, s - n + 1), n) if s - i - i >= gap])
    ev = {'frames': n, 'repeats': found[:4], 'near_repeats': near[:4]}
    if found:
        return 'fail', ev
    if near:
        return PERSON, dict(ev, reason='a run of frames nearly matches a later one')
    return 'pass', ev


def op_scrap_moves_r4m(path, a):
    """The supplied mascot moves or animates: it is found (SIFT feature matching, as v2_asset_found) in the film's
    frames at 4 a second. Pass: two found placements differ by move_px (8 px) or more in position, or by grow (3%)
    or more in size. Fail: found in still_share (0.9) or more of the frames, every placement within still_px (2 px)
    and still_grow (1%) in size, and its pixels unchanged (mean difference under still_levels, 3 grey levels, across
    frames). Anything else goes to a person (it may move where it was not found)."""
    import ops_r3_layout as l3
    try:
        hits, asset = l3._find_asset_frames(path, a, 'all')
    except FileNotFoundError:
        return PERSON, {'reason': 'supplied file not available'}
    total = len(l3._frames_of(path, 'all'))
    if not hits:
        return PERSON, {'reason': 'the mascot was not found'}
    pos = np.array([np.asarray(c, float).reshape(-1, 2).mean(axis=0) for _, c in hits])
    quads = [np.asarray(c, float).reshape(-1, 2) for _, c in hits]
    size = np.array([np.linalg.norm(np.roll(q, -1, axis=0) - q, axis=1).mean() for q in quads])
    move = float(np.max(np.linalg.norm(pos[:, None] - pos[None, :], axis=2)))
    grow = float(size.max() / max(size.min(), 1e-6) - 1)
    ev = {'found_in': len(hits), 'frames': total, 'largest_move_px': round(move, 1), 'size_change': round(grow, 3)}
    if move >= a.get('move_px', 8) or grow >= a.get('grow', 0.03):
        return 'pass', ev
    if len(hits) >= a.get('still_share', 0.9) * total and move <= a.get('still_px', 2) and grow <= a.get('still_grow', 0.01):
        c = np.asarray(hits[0][1], float).reshape(-1, 2)
        x0, y0 = np.floor(c.min(axis=0)).astype(int)
        x1, y1 = np.ceil(c.max(axis=0)).astype(int)
        crops = []
        for f, _ in hits:
            rgb = l3._frame_rgb(path, f)
            crops.append(rgb[max(0, y0):max(0, y1), max(0, x0):max(0, x1)].astype(float))
        change = max(float(np.abs(cr - crops[0]).mean()) for cr in crops)
        ev['pixel_change'] = round(change, 2)
        if change < a.get('still_levels', 3):
            return 'fail', dict(ev, reason='the mascot stays in one place, unchanged, through the film')
    return PERSON, dict(ev, reason='the mascot was found only in some frames, in one place')


def _used(key, dirs, min_frames):
    """Captures a film uses: {capture: frames}, frames of footage not matched, and captures seen in under
    min_frames frames (unsure)."""
    recs, shots, fps, size = _footage(key, dirs)
    used = {}
    for r in recs:
        if 'capture' in r:
            used[r['capture']] = used.get(r['capture'], 0) + 1
    unmatched = [r['f'] for r in recs if r['tex'] >= 0.10 and 'capture' not in r]
    return used, unmatched, [c for c, k in used.items() if k < min_frames]


def op_shared_captures_r4m(path, a):
    """The film uses shots from at least count (3) captures, all of them also used in the other film (deliverable).
    Every frame of both films is matched to the captures (module docstring); a capture counts where min_frames (6)
    or more frames show it. Pass: count or more captures, every one used in the other film too. Fail: fewer, or one
    not in the other film. Footage not matched to a capture, or a capture seen in only a few frames, goes to a
    person."""
    other = Path(a['_artifacts']) / a['deliverable']
    if not other.is_file():
        return PERSON, {'reason': f'{a["deliverable"]} not found'}
    dirs = _dirs(a)
    if not _bank(dirs):
        return PERSON, {'reason': 'supplied captures not available'}
    k = a.get('min_frames', 6)
    mine, un1, few1 = _used(str(path), dirs, k)
    theirs, un2, few2 = _used(str(other), dirs, k)
    ev = {'captures': {str(c): n for c, n in sorted(mine.items())}, 'other_captures': {str(c): n for c, n in sorted(theirs.items())},
          'unmatched_frames': len(un1), 'other_unmatched_frames': len(un2)}
    if un1 or un2 or few1 or few2:
        return PERSON, dict(ev, reason='footage not matched to a capture, or a capture seen in only a few frames')
    if len(mine) < a.get('count', 3):
        return 'fail', dict(ev, reason=f'shots from {len(mine)} captures')
    if set(mine) - set(theirs):
        return 'fail', dict(ev, reason=f'capture {sorted(set(mine) - set(theirs))} not used in the other film')
    return 'pass', ev


def op_capture_scale_r4m(path, a):
    """Capture footage is not enlarged past its recorded pixels. Image: the capture frame is found (whole-image
    correlation with every frame of the six captures, the best three and every 8th frame aligned by SIFT and a
    similarity transform, the most inliers wins, min_inliers 30 or more). Film: every frame showing capture (the capture named, or any) is aligned to its source
    frame. The scale is the aligned size over the recorded size. Pass: every scale at pass_scale (1.05) or less.
    (Footage the correlation misses is searched by SIFT against every 8th frame of every capture.)
    Fail: a scale of fail_scale (2.0) or more (each recorded pixel spread over two or more pixels each way, which
    shows as blocks or blur at full size). Between, or footage not aligned, goes to a person. A film where the named
    capture is not used (all its footage matched to other captures) passes."""
    dirs = _dirs(a)
    bank = _bank(dirs)
    if not bank:
        return PERSON, {'reason': 'supplied captures not available'}
    lo, hi = a.get('pass_scale', 1.05), a.get('fail_scale', 2.0)
    if not _is_film(path):
        import cv2
        img = np.asarray(Image.open(path).convert('RGB'))
        W = img.shape[1]
        small = cv2.resize(img, (DECODE_W, round(img.shape[0] * DECODE_W / W)), interpolation=cv2.INTER_AREA)
        sig = _sig(small)
        top = sorted(((float(s), n, j) for n, (_, _, sigs) in bank.items() for j, s in enumerate(sigs @ sig)), reverse=True)[:3]
        cands = [(n, j) for _, n, j in top] + [(n, i) for n in bank for i in range(0, len(bank[n][0]), STRIDE)]
        got = _search(small, bank, cands)
        if got is None or got[2] < a.get('min_inliers', 30):
            return PERSON, {'reason': 'the capture frame was not found'}
        n, j, inl, second = got
        A, inl, sc = _similarity(bank[n][0][j], small)
        best = (n, inl, round(sc * W / bank[n][1][0], 3), j)
        ev = {'capture': best[0], 'frame': best[3], 'inliers': best[1], 'scale': best[2]}
        return ('pass' if best[2] <= lo else 'fail' if best[2] >= hi else PERSON), ev
    recs, shots, fps, size = _footage(str(path), dirs)
    want = a.get('capture')
    unmatched = [r['f'] for r in recs if r['tex'] >= 0.10 and 'capture' not in r]
    mine = [r['f'] for r in recs if 'capture' in r and (want is None or r['capture'] == want)]
    ev = {'capture': want, 'frames': len(mine), 'unmatched_frames': len(unmatched)}
    if not mine:
        if unmatched:
            return PERSON, dict(ev, reason='footage not matched to a capture')
        return 'pass', dict(ev, reason='the capture is not used')
    scales, lost = [], 0
    for f in mine:
        r = _aligned(str(path), dirs, f)
        if not r or 'scale' not in r:
            lost += 1
            continue
        scales.append(r['scale'])
    ev.update(aligned=len(scales), largest_scale=max(scales) if scales else None, smallest_scale=min(scales) if scales else None)
    if scales and max(scales) >= hi:
        return 'fail', ev
    if lost or not scales:
        return PERSON, dict(ev, reason='some footage frames were not aligned to their source')
    if max(scales) <= lo:
        return 'pass', ev
    return PERSON, dict(ev, reason='the footage is enlarged a little')


def _shot_frames(key, dirs, fade_s):
    """Footage frames by shot, each with whether it lies within fade_s of the shot's start or end."""
    recs, shots, fps, size = _footage(key, dirs)
    k0 = int(round(fade_s * fps))
    out = []
    for s in shots:
        k = min(k0, len(s) // 3)   # the fade allowance never covers more than a third of a shot at each end
        out.append([(f, i < k or i >= len(s) - k) for i, f in enumerate(s)])
    k = k0
    unmatched = [r['f'] for r in recs if r['tex'] >= 0.10 and 'capture' not in r]
    # footage frames not matched next to a cut (a dissolve between two shots) are left to the fade allowance
    edges = {f for s in shots for f in (s[0], s[-1])}
    loose = [f for f in unmatched if not any(abs(f - e) <= k for e in edges)]
    return out, loose


def op_shot_wash_r4m(path, a):
    """No shot carries a scrim or colour wash over the footage; plain fades between shots are allowed. Every footage
    frame is compared with its aligned source frame (module docstring). A frame is clean with each channel's gain
    within pass_gain (0.92 to 1.10), offsets under max_offset (16 levels) and under max_shift_share (3%) of the
    visible footage shifted by 12 levels or more; within fade_s (0.5 s, at most a third of the shot) of a shot's start
    or end the same darkening or lightening on every channel (gains within 0.05 of each other, offsets within
    max_offset of each other) is a plain fade and allowed. Pass: every
    frame clean. Fail: outside the fade allowance, an even darkening or lightening of everything (a gain under
    fail_gain, 0.75, or over 1/0.75) or fail_shift_share (a fifth) or more of the footage shifted one way by 25
    levels or more. Anything else (a frame not aligned, too little visible) goes to a person."""
    dirs = _dirs(a)
    if not _is_film(path) or not _bank(dirs):
        return PERSON, {'reason': 'not a film, or supplied captures not available'}
    lo, hi = a.get('pass_gain', [0.92, 1.10])
    off, share = a.get('max_offset', 16), a.get('max_shift_share', 0.03)
    fg, fshare = a.get('fail_gain', 0.75), a.get('fail_shift_share', 0.2)
    shots, loose = _shot_frames(str(path), dirs, a.get('fade_s', 0.5))
    if not shots and not loose:
        return PERSON, {'reason': 'no capture footage found in the film'}
    bad, unsure, frames = [], [], 0
    for shot in shots:
        for f, edge in shot:
            r = _aligned(str(path), dirs, f)
            frames += 1
            if not r or 'gain' not in r:
                unsure.append({'frame': f, 'reason': 'not aligned or too little visible'})
                continue
            g, o, sh = r['gain'], r['offset'], r['shifted_share']
            within = max(abs(x) for x in o) < off and sh < share
            if within and lo <= min(g) and max(g) <= hi:
                continue
            # a plain fade: the same change on every channel (gains within 0.05, offsets within max_offset of each other)
            if edge and sh < share and max(g) - min(g) <= 0.05 and max(o) - min(o) < off:
                continue
            item = {'frame': f, 'gain': g, 'offset': o, 'shifted_share': sh, 'one_way_share': r['one_way_share']}
            if not edge and ((min(g) < fg or max(g) > 1 / fg) and sh < share or r['one_way_share'] >= fshare):
                bad.append(item)
            else:
                unsure.append(item)
    ev = {'footage_frames': frames, 'shots': len(shots), 'unmatched_frames': len(loose)}
    if bad:
        return 'fail', dict(ev, washed=bad[:4])
    if unsure or loose:
        return PERSON, dict(ev, unsure=unsure[:4], reason='footage tones differ from the source (a grade, a wash, or not read)')
    return 'pass', ev


def op_shot_colour_r4m(path, a):
    """No shot is recoloured toward the palette; each keeps its source capture's game colours. Every footage frame
    outside the fade allowance (fade_s, 0.5 s from a shot's start or end, at most a third of the shot) is compared
    with its aligned source frame.
    Pass: every frame within tol (8 levels) of its source on average in each channel. Fail: a frame whose saturated
    colours are turned by fail_hue_deg (30 degrees) or more on average. Anything else goes to a person."""
    dirs = _dirs(a)
    if not _is_film(path) or not _bank(dirs):
        return PERSON, {'reason': 'not a film, or supplied captures not available'}
    shots, loose = _shot_frames(str(path), dirs, a.get('fade_s', 0.5))
    if not shots and not loose:
        return PERSON, {'reason': 'no capture footage found in the film'}
    bad, unsure, frames = [], [], 0
    for shot in shots:
        inner = [f for f, edge in shot if not edge] or [f for f, _ in shot]
        for f in inner:
            r = _aligned(str(path), dirs, f)
            frames += 1
            if not r or 'mean_difference' not in r:
                unsure.append({'frame': f, 'reason': 'not aligned or too little visible'})
                continue
            if max(r['mean_difference']) <= a.get('tol', 8):
                continue
            item = {'frame': f, 'mean_difference': r['mean_difference'], 'hue_shift_deg': r['hue_shift_deg']}
            (bad if r['hue_shift_deg'] >= a.get('fail_hue_deg', 30) else unsure).append(item)
    ev = {'frames_compared': frames, 'shots': len(shots), 'unmatched_frames': len(loose)}
    if bad:
        return 'fail', dict(ev, recoloured=bad[:4])
    if unsure or loose:
        return PERSON, dict(ev, unsure=unsure[:4], reason='footage colours differ from the source')
    return 'pass', ev


def _capture_behind(path, dirs, loose=40):
    """The capture frame a thumbnail is built on, found as in capture_scale_r4m (SIFT over every capture), its exact
    source frame chosen among the 8 either side (median difference once aligned), and warped onto the thumbnail at
    full size: a mask of the pixels it explains (within loose, 40 levels, of it after a 9 px blur), or None."""
    import cv2
    bank = _bank(dirs)
    if not bank:
        return None
    img = np.asarray(Image.open(path).convert('RGB'))
    H, W = img.shape[:2]
    small = cv2.resize(img, (DECODE_W, round(H * DECODE_W / W)), interpolation=cv2.INTER_AREA)
    sig = _sig(small)
    top = sorted(((float(s), n, j) for n, (_, _, sigs) in bank.items() for j, s in enumerate(sigs @ sig)), reverse=True)[:3]
    got = _search(small, bank, [(n, j) for _, n, j in top] + [(n, i) for n in bank for i in range(0, len(bank[n][0]), STRIDE)])
    if got is None or got[2] < 30:
        return None
    n, j = got[0], got[1]
    frames, (sw, sh), _ = bank[n]
    A, inl, sc = _similarity(frames[j], small)
    best = (None, j)
    for i in range(max(0, j - NEAR), min(len(frames), j + NEAR + 1)):
        w_ = cv2.warpAffine(frames[i].astype(np.float32), A, (small.shape[1], small.shape[0]))
        v_ = cv2.warpAffine(np.full(frames[i].shape[:2], 255, np.uint8), A, (small.shape[1], small.shape[0]), flags=cv2.INTER_NEAREST) > 0
        d = float(np.median(np.abs(small.astype(np.float32)[v_] - w_[v_])))
        if best[0] is None or d < best[0]:
            best = (d, i)
    j = best[1]
    import ops_r3_layout as l3
    try:
        cap_path = base.asset_path({'_asset_dirs': list(dirs)}, f'staticfox_captures/staticfox_capture_0{n}.mp4')
    except FileNotFoundError:
        return None
    full = l3._video_frame(str(cap_path), j)
    if full is None:
        return None
    sim = _similarity(frames[j], small)
    if sim is None:
        return None
    A = sim[0].astype(np.float64)
    Af = np.zeros((2, 3))
    Af[:, :2] = A[:, :2] * (W / DECODE_W) * (frames[j].shape[1] / full.shape[1])
    Af[:, 2] = A[:, 2] * (W / DECODE_W)
    warped = cv2.warpAffine(full.astype(np.float32), Af, (W, H), flags=cv2.INTER_LINEAR)
    valid = cv2.warpAffine(np.full(full.shape[:2], 255, np.uint8), Af, (W, H), flags=cv2.INTER_NEAREST) > 0
    diff = cv2.blur(np.abs(img.astype(np.float32) - warped).mean(axis=2), (9, 9))
    return {'loose': valid & (diff < loose), 'capture': valid & (diff < 24), 'valid': valid, 'frame': warped,
            'share': float((valid & (diff < 24)).mean()), 'index': j, 'number': n}


def op_palette_over_capture_r4m(path, a):
    """Type, outline, panel, shape and icon colours come only from the palette, on a thumbnail built on a capture
    frame: the whole capture frame is masked out (the exact source frame found by SIFT over every capture and
    aligned at full size, _capture_behind; pixels within loose, 40 levels, of it after a 9 px blur), the supplied
    cut-outs found (photos) too, and the rest is read by v2_raster_palette's own rules (flat pieces of 30 pixels or
    more, tol per channel; 30 or more from every colour and not a blend of two fails; a blend or a near miss goes to a
    person). The capture not found goes to a person."""
    import ops_r3_layout as l3
    cap = _capture_behind(path, _dirs(a), a.get('loose', 40))
    if cap is None:
        return PERSON, {'reason': 'the capture frame the design is built on was not found'}
    real = l3._capture_match
    try:   # v2_raster_palette, given this capture frame in place of its own match
        l3._capture_match = lambda key, capture, dirs: cap
        st, ev = l3.op_raster_palette(path, dict(a, capture=f'staticfox_captures/staticfox_capture_0{cap["number"]}.mp4'))
    finally:
        l3._capture_match = real
    return st, dict(ev, capture=cap['number'], frame=cap['index'])


def _stack_rows(layer, title, max_rows=6, min_conf=60):
    """The consecutive OCR lines (top to bottom) that together read the title, a stacked title set over up to
    max_rows rows: (rows, exact), exact when the rows read the title and nothing else; ([], False) when not found.
    Lines read under min_conf (60) are left out, but short rows (a payoff word of two letters) are kept."""
    from objective_ops import canon
    lines = sorted([l for l in layer.lines if l.conf >= min_conf and l.text.strip()], key=lambda l: (l.bbox[1], l.bbox[0]))
    want = ' '.join(canon(title, False).split())
    best = ([], False)
    for n in range(1, max_rows + 1):
        for i in range(len(lines) - n + 1):
            rows = lines[i:i + n]
            got = ' '.join(canon(' '.join(l.text for l in rows), False).split())
            if got == want:
                return rows, True
            if want in got and not best[0]:
                best = (rows, False)
    return best


def op_title_stack_r4m(path, a):
    """The title read as a stack: the consecutive OCR lines (top to bottom, read at min_conf 60 or more) that
    together read the title (_stack_rows). mode "reads": rows reading exactly the title pass; anything else goes to a
    person (a misreading cannot be told from a misspelling). mode "inside": rows reading exactly the title with every
    row's box inside the image pass, such a row's box reaching the image edge fails (as v2_text_inside); not read
    exactly goes to a person. mode "largest": the title's largest row (letter height) is larger than every other confidently read line
    by SIZE_MARGIN (8%) passes; another line larger by that margin fails; closer, or a size not measured, goes to a
    person."""
    from objective_ops import SIZE_MARGIN, OCR_GOOD_CONF, merged, text_layers
    layer = merged(text_layers(path))
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    rows, exact = _stack_rows(layer, a['title'], a.get('max_rows', 6), a.get('min_conf', 60))
    ev = {'rows': [l.text for l in rows]}
    if not rows:
        return PERSON, dict(ev, reason='the title was not read as a stack of rows')
    mode = a['mode']
    if mode == 'reads':
        return ('pass', ev) if exact else (PERSON, dict(ev, reason='the rows hold other text as well'))
    if mode == 'inside':
        if not exact:
            return PERSON, dict(ev, reason='the rows hold other text as well')
        for l in rows:
            x0, y0, x1, y1 = l.bbox
            if x0 < 0.5 or y0 < 0.5 or x1 > layer.width - 0.5 or y1 > layer.height - 0.5:
                return 'fail', dict(ev, row=l.text, bbox=l.bbox)
        return 'pass', ev
    if mode == 'largest':
        if not exact or not all(l.size_ok for l in rows):
            return PERSON, dict(ev, reason='the title rows were not read cleanly enough to measure')
        size = max(l.size for l in rows)
        others = [l for l in layer.lines if l not in rows and l.conf >= OCR_GOOD_CONF and len(re.sub(r'[^A-Za-z0-9]', '', l.text)) >= 3]
        biggest = max(others, key=lambda l: l.size, default=None)
        ev.update(size=round(size, 1), next_largest=round(biggest.size, 1) if biggest else None,
                  next_text=biggest.text if biggest else None)
        if biggest is None or size >= biggest.size * (1 + SIZE_MARGIN):
            return 'pass', ev
        if biggest.size >= size * (1 + SIZE_MARGIN) and biggest.size_ok:
            return 'fail', ev
        return PERSON, dict(ev, reason='sizes too close to call from pixels')
    return PERSON, ev


def _full_stop_after(rgb, bbox):
    """Whether the last mark of a row of type is a full stop: the row's ink (pixels 80 grey levels or more from the
    row's ground) is split into pieces; the rightmost piece is a full stop when it is no more than 0.3 of the row's
    height either way, roughly square (sides within 1.7 of each other), mostly filled (60% or more) and sits on the
    row's baseline (its foot within 0.15 of the row's height of the letters' feet)."""
    import cv2
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    h = max(1, y1 - y0)
    X1 = min(rgb.shape[1], x1 + int(0.6 * h))
    crop = rgb[max(0, y0 - 2):min(rgb.shape[0], y1 + 3), max(0, x0):X1].astype(np.float32)
    if crop.size == 0:
        return None
    g = crop.mean(axis=2)
    ink = np.abs(g - np.median(g)) >= 80
    n, lab, stats, cent = cv2.connectedComponentsWithStats(ink.astype(np.uint8), 8)
    pieces = [stats[i] for i in range(1, n) if stats[i][4] >= 4]
    if len(pieces) < 2:
        return None
    feet = np.median([p[1] + p[3] for p in pieces if p[3] >= 0.5 * h] or [crop.shape[0]])
    last = max(pieces, key=lambda p: p[0] + p[2])
    w, hh, area = last[2], last[3], last[4]
    return bool(w <= 0.3 * h and hh <= 0.3 * h and max(w, hh) <= 1.7 * max(1, min(w, hh))
                and area >= 0.6 * w * hh and abs(last[1] + hh - feet) <= 0.15 * h)


def op_end_card_line_r4m(path, a):
    """The held end card carries the line word for word: the last held frame (4 a second, as v2_end_hold) is read
    by OCR and the consecutive rows reading the line are found, case and punctuation kept (_stack_rows, min_conf 60).
    Pass: the rows read the line exactly; or they read it exactly but for its final full stop, which OCR often loses
    on a compressed frame, and the row's last mark is measured as a full stop (_full_stop_after). Anything else goes
    to a person."""
    import ops_r3_layout as l3
    from objective_ops import canon, ocr_image
    if not _is_film(path):
        return PERSON, {'reason': 'not a film'}
    f = l3._frames_of(path, 'last')[0]
    rgb = l3._frame_rgb(path, f).astype(np.uint8)
    layer = ocr_image(Image.fromarray(rgb))
    want = a['text']
    lines = sorted([l for l in layer.lines if l.conf >= a.get('min_conf', 60) and l.text.strip()], key=lambda l: (l.bbox[1], l.bbox[0]))
    target = ' '.join(canon(want).split())
    short = target[:-1] if target.endswith('.') else None
    for n in range(1, a.get('max_rows', 6) + 1):
        for i in range(len(lines) - n + 1):
            rows = lines[i:i + n]
            got = ' '.join(canon(' '.join(l.text for l in rows)).split())
            if got == target:
                return 'pass', {'frame': f, 'rows': [l.text for l in rows]}
            if short and got == short:
                stop = _full_stop_after(rgb, rows[-1].bbox)
                ev = {'frame': f, 'rows': [l.text for l in rows], 'full_stop_measured': stop}
                return ('pass', ev) if stop else (PERSON, dict(ev, reason='the final full stop was not read or measured'))
    return PERSON, {'frame': f, 'reason': 'the line was not read word for word', 'lines': [l.text for l in lines][:8]}


OPS.update({
    'end_card_line_r4m': op_end_card_line_r4m,
    'title_stack_r4m': op_title_stack_r4m,
    'music_from_bed_r4m': op_music_from_bed_r4m,
    'no_repeat_r4m': op_no_repeat_r4m,
    'scrap_moves_r4m': op_scrap_moves_r4m,
    'shared_captures_r4m': op_shared_captures_r4m,
    'capture_scale_r4m': op_capture_scale_r4m,
    'shot_wash_r4m': op_shot_wash_r4m,
    'shot_colour_r4m': op_shot_colour_r4m,
})
