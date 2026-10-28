"""Round 3 operations written with the PHOTO-04, 06, 08 and 10 handlers (pilot-13 v2, 2026-10-28).

Same contract as objective_ops: every operation returns (status, evidence), status "pass", "fail" or "person";
nothing passes on a failed read, and a person decides wherever the code is not sure. Loaded by objective_ops_r3.
Definitions used here (kept the same on every file):
- body size, heading, fine: the text roles of objective_ops_r3._roles.
- running text: a line with lowercase letters; a label: a line with no lowercase letters.
- a rule: a drawn shape 2 pt or less across (PDF), or a piece of one colour 0.4% of the image's short side or less
  across (images).
- a ground or panel: an opaque filled area of 2% of the page or more that shows outside placed pictures (PDF), or a
  flat area of one colour outside photographs (images).
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

import objective_ops as base
import objective_ops_r3 as r3
from objective_ops import PERSON, OCR_GOOD_CONF, canon, contains, merged, text_layers

LOWER = re.compile(r'[a-z]')


def _hexes_near(c, hexes, tol):
    return base._near_hex(r3._to_hex(c), hexes, tol)


def _sub(a, spec):
    return dict(spec, **{k: v for k, v in a.items() if k.startswith('_')})


# ---------------------------------------------------------------- combining two readings of a definition


def op_agree(path, a):
    """Two readings of a definition (a narrow and a broad one) must agree: both pass is a pass, both fail is a fail,
    anything else goes to a person (the answer would depend on which reading a reviewer takes)."""
    results = [base.run(path, _sub(a, c)) for c in a['checks']]
    states = [st for st, _ in results]
    if all(st == 'pass' for st in states):
        return 'pass', results[0][1]
    if all(st == 'fail' for st in states):
        return 'fail', results[0][1]
    return PERSON, {'reason': 'the narrow and the broad reading of the definition disagree', 'parts': states,
                    'evidence': [ev for _, ev in results][:2]}


# ---------------------------------------------------------------- PDF: where a colour is used, grounds, type colour


def _pdf_body(key):
    layer = base.pdf_layer(key)
    body, roles = r3._roles(layer)
    return layer, body, roles


def op_pdf_colour_roles(path, a):
    """PDF: shapes drawn in the colours are thin rules (2 pt or less across), and type in them is allowed only as
    small labels (text='labels': a line with no lowercase letters, no larger than the body size) or not at all
    (text='none'). A colour not used passes."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    bad = []
    for page in pymupdf.open(key):
        for d in page.get_drawings():
            for k in ('fill', 'color'):
                c = d.get(k)
                if c is None or not base._near_hex(base._hex(c), a['hexes'], 3):
                    continue
                r = d['rect']
                w = (d.get('width') or 0) if k == 'color' else 0
                if min(r.width + w, r.height + w) > 2.0:
                    bad.append({'page': page.number + 1, 'shape': [round(v) for v in r], 'colour': base._hex(c)})
    layer, body, roles = _pdf_body(key)
    import objective_ops_r2 as r2
    for sp in r2._pdf_spans(key):
        if not base._near_hex(sp['color'], a['hexes'], 3):
            continue
        if a.get('text', 'none') == 'none':
            bad.append({'page': sp['page'] + 1, 'type': sp['text'][:30], 'colour': sp['color']})
            continue
        line = next((l for l in layer.lines if l.page == sp['page'] and base._overlap(l.bbox, sp['bbox']) > 0.5), None)
        text = line.text if line else sp['text']
        if body is None:
            return PERSON, {'reason': 'no running text found to set the body size'}
        if LOWER.search(text) or sp['size'] > body + 0.3:
            bad.append({'page': sp['page'] + 1, 'type': text[:30], 'size': round(sp['size'], 1), 'colour': sp['color']})
    return ('fail', {'not_allowed': bad[:5]}) if bad else ('pass', {'hexes': a['hexes']})


def _page_ground(key, pno):
    """The commonest colour of the rendered page outside placed pictures: the page's ground."""
    arr, mask, _ = base._flat_pixels(Path(key), pno)
    px = arr[mask].reshape(-1, 3)
    if not len(px):
        return None
    values, counts = np.unique(px, axis=0, return_counts=True)
    return '#%02X%02X%02X' % tuple(values[counts.argmax()]), counts.max() / len(px)


def op_pdf_grounds(path, a):
    """PDF: every page ground (the rendered page's commonest colour outside placed pictures) and every panel (an
    opaque filled shape of 2% of the page or more, with both sides over 6 pt, of which 2% of the page shows outside
    placed pictures) is one of the allowed colours. See-through shapes are overlays, not panels."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    bad, seen = [], 0
    for page in pymupdf.open(key):
        W, H = page.rect.width, page.rect.height
        images = [tuple(i['bbox']) for i in page.get_image_info()]
        g = _page_ground(key, page.number)
        if g is not None:
            seen += 1
            if not base._near_hex(g[0], a['hexes'], 3):
                bad.append({'page': page.number + 1, 'ground': g[0]})
        for d in page.get_drawings():
            c = d.get('fill')
            if c is None or (d.get('fill_opacity') is not None and d['fill_opacity'] < 0.999):
                continue
            r = d['rect']
            area = r.width * r.height
            if min(r.width, r.height) <= 6 or area < 0.02 * W * H:
                continue
            covered = sum(max(0, min(r.x1, i[2]) - max(r.x0, i[0])) * max(0, min(r.y1, i[3]) - max(r.y0, i[1])) for i in images)
            if area - covered < 0.02 * W * H:
                continue
            seen += 1
            if not base._near_hex(base._hex(c), a['hexes'], 3):
                bad.append({'page': page.number + 1, 'panel': [round(v) for v in r], 'colour': base._hex(c)})
    if bad:
        return 'fail', {'not_allowed': bad[:5]}
    return ('pass', {'grounds_and_panels': seen}) if seen else (PERSON, {'reason': 'no ground found'})


def _select_pdf_lines(layer, body, roles, a):
    """Lines a PDF type check is about. select: 'running_below_heading' (lines with lowercase letters set under 1.3
    times the body size, of min_words words or more), 'above_body' (lines set 1 pt or more over the body size), or a
    list of roles; plus lines matching patterns; minus lines matching except."""
    picks = []
    sel = a.get('select')
    for l in layer.lines:
        t = canon(l.text)
        if sel == 'running_below_heading' and LOWER.search(t) and l.size < 1.3 * body - 0.01 and len(t.split()) >= a.get('min_words', 1):
            picks.append(l)
        elif sel == 'above_body' and l.size >= body + 1:
            picks.append(l)
        elif isinstance(sel, list) and any(l in roles.get(r, []) for r in sel):
            picks.append(l)
        elif any(re.search(p, t, re.I) or re.search(p, base.squash(t), re.I) for p in a.get('patterns', [])):
            picks.append(l)
    return [l for l in dict.fromkeys(picks) if not any(re.search(p, canon(l.text), re.I) for p in a.get('except', []))]


def op_pdf_text_colour(path, a):
    """PDF type of the selected lines (see _select_pdf_lines), where it sits on one of the grounds (the colour behind
    it read from the rendered page), is one of the colours."""
    import objective_ops_r2 as r2
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    key = str(path)
    layer, body, roles = _pdf_body(key)
    if body is None:
        return PERSON, {'reason': 'no running text found to set the body size'}
    chosen = _select_pdf_lines(layer, body, roles, a)
    bad, checked = [], 0
    spans = r2._pdf_spans(key)
    for l in chosen:
        for sp in spans:
            if sp['page'] != l.page or base._overlap(sp['bbox'], l.bbox) < 0.5:
                continue
            if a.get('grounds'):
                g = r2._ground(key, sp['page'], sp['bbox'], sp['color'])
                if g in ('photo', 'mixed') or not base._near_hex(g, a['grounds'], 6):
                    continue
            checked += 1
            if not base._near_hex(sp['color'], a['colors'], 2):
                bad.append((sp['text'][:30], sp['color']))
    return ('fail', {'not_matching': bad[:6]}) if bad else ('pass', {'spans_checked': checked})


def op_pdf_area_share(path, a):
    """PDF: the colours together cover no more than max_pct of the area outside placed pictures. Read per page and
    over the whole file: every page within passes; the whole file over fails; otherwise a person decides."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    hit_all = area_all = 0
    worst = 0.0
    for p in range(len(pymupdf.open(path))):
        arr, mask, _ = base._flat_pixels(path, p)
        px = arr[mask].reshape(-1, 3).astype(int)
        if not len(px):
            continue
        hit = np.zeros(len(px), bool)
        for h in a['hexes']:
            hit |= (np.abs(px - r3._hex_rgb(h)) <= 3).all(axis=1)
        hit_all += int(hit.sum())
        area_all += len(px)
        worst = max(worst, 100 * hit.mean())
    if not area_all:
        return PERSON, {'reason': 'no area outside the pictures'}
    total = 100 * hit_all / area_all
    ev = {'worst_page_pct': round(worst, 2), 'whole_file_pct': round(total, 2)}
    if worst <= a['max_pct']:
        return 'pass', ev
    if total > a['max_pct']:
        return 'fail', ev
    return PERSON, dict(ev, reason='over on one page, within over the whole file')


def op_pdf_no_overlay(path, a):
    """PDF: nothing see-through, shaded or blended is laid over a placed photograph: no fill with opacity under 1,
    no shading and no blend mode drawn over a picture, and no soft-masked picture over another one. An opaque
    shape partly covering a photo is a solid panel beside or over it, not an overlay. A see-through or masked
    picture over a photo, or a graphics state that cannot be tied to a shape, goes to a person."""
    import pymupdf
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(path)
    bad, unsure = [], []
    for page in doc:
        infos = page.get_image_info(xrefs=True)
        photos = [i for i in infos if (i['bbox'][2] - i['bbox'][0]) * (i['bbox'][3] - i['bbox'][1]) > 0.02 * page.rect.width * page.rect.height]
        boxes = [tuple(i['bbox']) for i in photos]
        def over(r):
            return [b for b in boxes if min(r[2], b[2]) - max(r[0], b[0]) > 1 and min(r[3], b[3]) - max(r[1], b[1]) > 1]
        for d in page.get_drawings():
            r = tuple(d['rect'])
            if not over(r):
                continue
            op = d.get('fill_opacity') if d.get('fill') is not None else d.get('stroke_opacity')
            if d.get('type') == 'sh' or (op is not None and op < 0.999):
                bad.append({'page': page.number + 1, 'shape': [round(v) for v in r], 'opacity': op})
        for i in infos:
            b = tuple(i['bbox'])
            under = [p for p in boxes if p != b and base._overlap(p, b) > 0.02]
            if under and i.get('xref'):
                smask = doc.xref_get_key(i['xref'], 'SMask')[0] != 'null'
                if smask:
                    unsure.append({'page': page.number + 1, 'masked_picture_over_photo': [round(v) for v in b]})
        gs = page.get_contents()
        stream = b''.join(doc.xref_stream(x) or b'' for x in gs).decode('latin-1')
        if re.search(r'(?<![\w/])sh\b', stream) and boxes:
            unsure.append({'page': page.number + 1, 'shading_on_page': True})
        for name in re.findall(r'/(\S+)\s+gs\b', stream):
            kind, val = doc.xref_get_key(page.xref, f'Resources/ExtGState/{name}')
            if kind == 'xref':
                val = doc.xref_object(int(val.split()[0]))
            m = re.search(r'/BM\s*/(\w+)', val or '')
            if m and m.group(1) not in ('Normal', 'Compatible') and boxes:
                unsure.append({'page': page.number + 1, 'blend': m.group(1)})
    if bad:
        return 'fail', {'overlays': bad[:4]}
    if unsure:
        return PERSON, {'reason': 'a see-through, shaded or blended element on a page with photos', 'found': unsure[:4]}
    return 'pass', {'pages': len(doc)}


def op_pdf_role_vs_lines(path, a):
    """PDF: every line of a role (heading by default), other than the lines matching names, is set smaller (rel
    'smaller') than the smallest line matching names."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer, body, roles = _pdf_body(str(path))
    if body is None:
        return PERSON, {'reason': 'no running text found to set the body size'}
    named = [l for l in layer.lines if any(re.search(p, canon(l.text), re.I) for p in a['names'])]
    if not named:
        return PERSON, {'reason': 'named lines not found'}
    sel = [l for l in roles.get(a.get('role', 'heading'), []) if l not in named]
    if not sel:
        return 'pass', {'reason': f'no {a.get("role", "heading")} other than the named lines'}
    ref = min(l.size for l in named)
    bad = [(l.text[:30], round(l.size, 1)) for l in sel if not l.size < ref - 0.01]
    return ('fail', {'not_smaller': bad[:5], 'names_size': round(ref, 1)}) if bad else ('pass', {'largest': round(max(l.size for l in sel), 1), 'names_size': round(ref, 1)})


# ---------------------------------------------------------------- lines on images


def _outside_lines(path, a):
    """Real OCR lines whose centre lies outside the photographs, and whether every wording line there was read
    confidently (so an absence or a length can be trusted)."""
    layer = merged(text_layers(path))
    mask = r3._photo_mask(path, a) if a.get('photos') is not None else None
    keep, sure = [], True
    layer.outside = []
    for l in layer.lines:
        cx, cy = int((l.bbox[0] + l.bbox[2]) / 2), int((l.bbox[1] + l.bbox[3]) / 2)
        if mask is not None and 0 <= cy < mask.shape[0] and 0 <= cx < mask.shape[1] and mask[cy, cx]:
            continue
        layer.outside.append(l)
        wording = len(re.findall(r'[A-Za-z0-9]', l.text)) >= 3 or re.search(r'[\d$€£@]', l.text)
        if wording and l.conf < OCR_GOOD_CONF:
            sure = False
        if base._real(l):
            keep.append(l)
    return layer, keep, sure


def op_max_line_chars(path, a):
    """No line runs longer than max_chars characters, spaces included. PDF: the lines of the named role or patterns
    (all lines without either); a longer line fails. Images: every line read outside the photographs; all within
    and read confidently passes (whatever counts as body text, none is longer); anything else goes to a person,
    since OCR may join two columns into one line."""
    if path.suffix.lower() == '.pdf':
        layer, body, roles = _pdf_body(str(path))
        lines = layer.lines
        if a.get('role') or a.get('select'):
            if body is None:
                return PERSON, {'reason': 'no running text found to set the body size'}
            lines = roles.get(a['role'], []) if a.get('role') else _select_pdf_lines(layer, body, roles, a)
        if a.get('patterns'):
            lines = [l for l in lines if any(re.search(p, canon(l.text), re.I) for p in a['patterns'])]
        long_ = [(l.text, len(canon(l.text))) for l in lines if len(canon(l.text)) > a['max_chars']]
        return ('fail', {'too_long': long_[:3]}) if long_ else ('pass', {'lines': len(lines)})
    layer, lines, sure = _outside_lines(path, a)
    if not lines:
        return PERSON, {'reason': 'no text read'}
    if a.get('patterns'):
        lines = [l for l in lines if any(re.search(p, canon(l.text), re.I) for p in a['patterns'])]
        if not lines:
            return ('pass', {'reason': 'no such line shown'}) if a.get('optional') and sure else (PERSON, {'reason': 'lines not found'})
    long_ = [(l.text, len(canon(l.text))) for l in lines if len(canon(l.text)) > a['max_chars']]
    if long_:
        return PERSON, {'reason': 'a line read longer than the limit (OCR may join columns)', 'lines': long_[:3]}
    if not sure:
        return PERSON, {'reason': 'some text outside the photographs not read clearly'}
    return 'pass', {'lines': len(lines), 'longest': max(len(canon(l.text)) for l in lines)}


def _line_hit(l, a):
    t = canon(l.text)
    if any(re.search(p, t) for p in a.get('except', [])):
        return False
    if a.get('all_text'):
        return True
    if any(contains(t, x, False) for x in a.get('texts', [])):
        return True
    return any(re.search(p, t, re.I) or re.search(p, base.squash(t), re.I) for p in a.get('patterns', []))


def _chunks(rgb, l, gap_k=1.5):
    """A line's box cut where the ground runs clear for more than gap_k line heights: pieces set apart on one row
    (a label and a value, two words in different colours) are measured on their own."""
    h, w = rgb.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in l.bbox)
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return [l.bbox]
    crop = rgb[y0:y1, x0:x1].astype(int)
    vals, cnt = np.unique(crop.reshape(-1, 3) // 4, axis=0, return_counts=True)
    g = vals[cnt.argmax()] * 4 + 2
    ink = (np.abs(crop - g).sum(axis=2) > 60).any(axis=0)
    gap = gap_k * (y1 - y0)
    out, start, last = [], None, None
    for i, on in enumerate(ink):
        if on:
            if start is None:
                start = i
            elif i - last > gap:
                out.append((x0 + start, y0, x0 + last + 1, y1))
                start = i
            last = i
    if start is not None:
        out.append((x0 + start, y0, x0 + last + 1, y1))
    return out or [l.bbox]


def op_line_colour_raster(path, a):
    """Ink (letter cores) and ground of selected text lines on an image. Lines are picked by texts, patterns
    (re.I; a pattern may switch case back on with (?-i:...)) or all_text, minus except; min_conf lowers the reading
    confidence needed to pick a line (a colour does not depend on every letter being read). split_gaps: pieces of
    a line set apart on its row are measured on their own. grounds: only lines on these grounds count; colors:
    allowed inks; pairs: allowed (ink, ground) combinations; ground_must: the ground must be one of these;
    allow_label_colors: a label (no lowercase letters) in one of these is allowed too. Within tol passes, 30 or more
    off fails (on a line read at 80 or more), between goes to a person; soft: a fail goes to a person instead.
    each: every text listed must be picked. Nothing picked: a pass only where optional and every line outside the
    photographs was read confidently."""
    tol = r3._tol(path, a) + 3
    rgb = r3._pixels(str(path))
    layer, lines, sure = _outside_lines(path, dict(a, photos=a.get('photos', [])))
    min_conf = a.get('min_conf', OCR_GOOD_CONF)
    pool = [l for l in layer.outside if l.conf >= min_conf and len(re.findall(r'[A-Za-z0-9]', l.text)) >= 2]
    picks = [l for l in pool if _line_hit(l, a)]
    if a.get('each'):
        missing = [t for t in a.get('texts', []) if not any(contains(canon(l.text), t, False) for l in picks)]
        if missing:
            return PERSON, {'reason': 'not every listed text was read', 'missing': missing[:3]}
    if a.get('largest_only') and picks:
        top = max(l.size for l in picks)
        picks = [l for l in picks if l.size >= 0.92 * top]
    checked, bad, unsure = 0, [], []
    for l in picks:
        for box in (_chunks(rgb, l) if a.get('split_gaps') else [l.bbox]):
            got = r3._ink_and_ground(rgb, box)
            if got is None:
                unsure.append(l.text)
                continue
            ink, ground, share = got
            g_hex, i_hex = r3._to_hex(ground), r3._to_hex(ink)
            if a.get('ground_must'):
                checked += 1
                if share < 0.5:
                    unsure.append(l.text)
                elif not base._near_hex(g_hex, a['ground_must'], tol + 3):
                    (bad if l.conf >= OCR_GOOD_CONF else unsure).append({'line': l.text, 'ground': g_hex})
                continue
            if a.get('grounds') and (share < 0.5 or not base._near_hex(g_hex, a['grounds'], tol + 3)):
                continue
            checked += 1
            if a.get('pairs'):
                dist = min(max(np.abs(ink - r3._hex_rgb(i)).max(), np.abs(ground - r3._hex_rgb(g)).max()) for i, g in a['pairs'])
            else:
                dist = min(np.abs(ink - r3._hex_rgb(c)).max() for c in a['colors'])
            if dist <= tol:
                continue
            if a.get('allow_label_colors') and not LOWER.search(l.text) and \
                    min(np.abs(ink - r3._hex_rgb(c)).max() for c in a['allow_label_colors']) <= tol:
                continue
            item = {'line': l.text, 'ink': i_hex, 'ground': g_hex}
            (bad if dist >= 30 and l.conf >= OCR_GOOD_CONF and not a.get('soft') else unsure).append(item)
    if bad:
        return 'fail', {'not_matching': bad[:5]}
    if unsure:
        return PERSON, {'reason': 'some line colours not clear enough to call', 'lines': unsure[:4]}
    if not checked:
        if a.get('optional') and sure:
            return 'pass', {'reason': 'no such text (the check applies only where it appears)'}
        return PERSON, {'reason': 'text not found' if not picks else 'not on those grounds; nothing to check'}
    return 'pass', {'lines_checked': checked}


# ---------------------------------------------------------------- where a colour may appear on an image


def op_colour_roles_raster(path, a):
    """Every piece of the colours outside photographs (and outside the supplied marks named in marks) is in an
    allowed role. Roles: thin (a rule, divider or keyline: one side 0.4% of the short side or less, at least 3 px),
    label (inside a text line with no lowercase letters whose letters are no taller than small_px, default 2.5% of
    the image height), text (inside any other text line), area (a filled panel or ground), mark (the symbol set
    just left of a wordmark line matching mark_word, as in v2_leaf_mark_raster), other. A piece outside
    the allowed roles fails when it is an area, or text in a line read confidently; anything else unclear goes to a
    person. With marks: a large piece where a named mark was not found goes to a person (a redrawn mark)."""
    import cv2
    tol = r3._tol(path, a)
    rgb, flat, outside = r3._designed(path, a)
    h, w = rgb.shape[:2]
    excl = np.zeros((h, w), bool)
    import objective_ops_r2 as r2
    missing_mark = False
    for name in a.get('marks', []):
        try:
            page, box, state = r2._asset_box(path, a, name, 0)
        except FileNotFoundError:
            box = None
        if box is None:
            missing_mark = True
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        excl[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = True
    thin = a.get('thin_px', max(3, round(0.004 * min(h, w))))
    small = a.get('small_px', 0.025 * h)
    hit = r3._near_mask(rgb, a['hexes'], tol) & outside & ~excl
    layer = merged(text_layers(path))
    lines = [l for l in layer.lines if len(re.findall(r'[A-Za-z0-9]', l.text)) >= 2]
    symbols = []
    for l in layer.lines:
        if a.get('mark_word') and l.conf >= 60 and _wordmark(l, a['mark_word']):
            symbols.append(_symbol_box(l, a['mark_word']))
            symbols.append(tuple(l.bbox))
    roles = {'mark': 0, 'thin': 0, 'thin_elsewhere': 0, 'label': 0, 'text': 0, 'area': 0, 'other': 0}
    bad, unsure = [], []
    import cv2
    n, labels, stats, _ = cv2.connectedComponentsWithStats(hit.astype(np.uint8), connectivity=8)
    near, inks = None, {}
    if a.get('thin_near_photo'):
        band = ~outside
        near = cv2.dilate(band.astype(np.uint8), np.ones((25, 25), np.uint8)) > 0 if band.any() else None
    for i in range(1, n):
        x, y, bw, bh, area = (int(v) for v in stats[i])
        if area < 12:
            continue
        cx, cy = x + bw / 2, y + bh / 2
        line = next((l for l in lines if l.bbox[0] - 3 <= cx <= l.bbox[2] + 3 and l.bbox[1] - 3 <= cy <= l.bbox[3] + 3), None)
        if any(b[0] <= cx <= b[2] and b[1] <= cy <= b[3] for b in symbols):
            role = 'mark'
        elif line is not None and bh <= 1.6 * max(1, line.bbox[3] - line.bbox[1]):
            key = id(line)
            if key not in inks:
                got = r3._ink_and_ground(rgb, line.bbox)
                inks[key] = got is not None and min(np.abs(got[0] - r3._hex_rgb(c)).max() for c in a['hexes']) <= tol + 3
            if not inks[key]:
                continue                                  # the edge of letters inked in another colour
            role = 'text' if LOWER.search(line.text) or bh > small else 'label'
        elif min(bw, bh) <= thin:
            role = 'thin'
            if a.get('thin_near_photo'):
                # a keyline round a photograph: the piece runs along the photographs' edge, within 12 px of it
                if near is None or near[y:y + bh, x:x + bw][labels[y:y + bh, x:x + bw] == i].mean() <= 0.9:
                    role = 'thin_elsewhere'
        elif bw * bh >= 0.004 * h * w and area / max(1, bw * bh) > 0.6 and min(bw, bh) > 4 * thin:
            role = 'area'
        else:
            role = 'other'
        roles[role] += 1
        if role in a['allowed']:
            continue
        item = {'role': role, 'box': [x, y, bw, bh], 'line': line.text[:30] if line is not None else None}
        if role == 'area' and not (a.get('marks') and missing_mark):
            bad.append(item)
        elif role == 'thin_elsewhere' and max(bw, bh) >= 0.05 * w:
            bad.append(item)
        elif role == 'text' and line.conf >= OCR_GOOD_CONF and area >= 30:
            bad.append(item)
        elif area >= 30:
            unsure.append(item)
    ev = {'pieces': roles}
    if bad:
        return 'fail', dict(ev, not_allowed=bad[:4])
    if unsure:
        return PERSON, dict(ev, reason='pieces in the colour whose role is unclear', pieces_unclear=unsure[:4])
    return 'pass', ev


def op_colour_absent_raster(path, a):
    """None of the colours appears outside photographs (and outside the text lines matching except_lines, where it
    is allowed): no flat piece of it (MIN_COMPONENT pixels in one piece) and no text line inked in it (letter cores
    within tol)."""
    tol = r3._tol(path, a)
    rgb, flat, outside = r3._designed(path, a)
    layer, lines, sure = _outside_lines(path, a)
    allowed = [l for l in layer.lines if any(re.search(p, canon(l.text), re.I) for p in a.get('except_lines', []))]
    hit = flat & r3._near_mask(rgb, a['hexes'], tol) & outside
    for l in allowed:
        x0, y0, x1, y1 = (int(round(v)) for v in l.bbox)
        hit[max(0, y0 - 4):y1 + 4, max(0, x0 - 4):x1 + 4] = False
    comps = r3._components(hit)
    if comps:
        return 'fail', {'pieces_px': sorted((int(st[4]) for _, st in comps), reverse=True)[:5]}
    for l in lines:
        if l in allowed:
            continue
        got = r3._ink_and_ground(rgb, l.bbox)
        if got is not None and min(np.abs(got[0] - r3._hex_rgb(c)).max() for c in a['hexes']) <= tol + 3:
            return 'fail', {'line_in_colour': l.text, 'ink': r3._to_hex(got[0])}
    return 'pass', {'hexes': a['hexes']}


def op_colour_only_by_raster(path, a):
    """Every flat area of the colour outside photographs sits behind or around the named things: it overlaps (or
    touches, within 1% of the image) the box of a named supplied file or text line. Not used passes."""
    import objective_ops_r2 as r2
    tol = r3._tol(path, a)
    rgb, flat, outside = r3._designed(path, a)
    h, w = rgb.shape[:2]
    hit = flat & r3._near_mask(rgb, a['hexes'], tol)
    comps = [(m, st) for m, st in r3._components(hit, max(r3.MIN_COMPONENT, int(0.002 * h * w)))]
    if not comps:
        return 'pass', {'reason': 'colour not used as an area'}
    boxes = []
    for name in a.get('assets', []):
        try:
            page, box, state = r2._asset_box(path, a, name, 0)
        except FileNotFoundError:
            box = None
        if box is not None:
            boxes.append(box)
    layer = merged(text_layers(path))
    for t in a.get('texts', []):
        boxes += [l.bbox for l in layer.lines if contains(l.text, t, False)]
    if not boxes:
        return PERSON, {'reason': 'the colour is used, and what it may stand behind was not found'}
    m = 0.01 * max(h, w)
    bad = []
    for comp, st in comps:
        x, y, bw, bh = (int(v) for v in st[:4])
        near = any(min(x + bw, b[2] + m) - max(x, b[0] - m) > 0 and min(y + bh, b[3] + m) - max(y, b[1] - m) > 0 for b in boxes)
        if not near:
            bad.append([x, y, bw, bh])
    return ('fail', {'areas_elsewhere': bad[:4]}) if bad else ('pass', {'areas': len(comps)})


def _regions(rgb, flat, outside, min_share, tol):
    """Flat one-colour areas of min_share of the image or more (not long thin rules): (hex, pixels, box)."""
    import cv2
    h, w = rgb.shape[:2]
    q = rgb // 4
    code = (q[..., 0].astype(np.int32) << 12) | (q[..., 1].astype(np.int32) << 6) | q[..., 2].astype(np.int32)
    sel = flat & outside
    values, counts = np.unique(code[sel], return_counts=True)
    out = []
    for v, c in sorted(zip(values, counts), key=lambda t: -t[1])[:16]:
        if c < min_share * h * w:
            break
        m = sel & (code == v)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
        for comp, st in r3._components(m, int(min_share * h * w)):
            if min(st[2], st[3]) >= 0.03 * min(h, w):
                out.append((r3._to_hex(np.median(rgb[comp & flat], axis=0)), int(st[4]), tuple(int(x) for x in st[:4])))
    return sorted(out, key=lambda r: -r[1])


def op_grounds_raster(path, a):
    """Every ground, band, panel and button (a flat area of one colour outside photographs covering min_share of the
    image or more, default 0.3%, both sides at least 3% of the short side) is one of the allowed colours."""
    tol = r3._tol(path, a)
    rgb, flat, outside = r3._designed(path, a)
    regions = _regions(rgb, flat, outside, a.get('min_share', 0.003), tol)
    if not regions:
        return PERSON, {'reason': 'no ground or panel found outside the photographs'}
    bad = sorted({c for c, _, _ in regions if not base._near_hex(c, a['hexes'], tol + 2)})
    return ('fail', {'grounds_outside': bad, 'regions': len(regions)}) if bad else ('pass', {'grounds': sorted({c for c, _, _ in regions})})


def op_main_ground_raster(path, a):
    """The ground (the largest flat area outside photographs, areas in the ignored colours left out) is main."""
    tol = r3._tol(path, a)
    rgb, flat, outside = r3._designed(path, a)
    regions = [r for r in _regions(rgb, flat, outside, 0.01, tol) if not base._near_hex(r[0], a.get('ignore', []), tol + 2)]
    if not regions:
        return PERSON, {'reason': 'no ground found outside the photographs'}
    top = regions[0][0]
    return ('pass' if base._near_hex(top, [a['main']], tol + 2) else 'fail'), {'ground': top}


def op_palette_raster_x(path, a):
    """As v2_palette_raster, with the ground (the largest flat area outside photographs) left out when skip_ground:
    a check about type, rules and keylines does not judge the margin's own colour. photo_touch: an off-palette
    piece touching a photograph goes to a person (it may be part of a photograph not matched to its file)."""
    tol = r3._tol(path, a)
    rgb, flat, outside = r3._designed(path, a)
    if flat.sum() < 200:
        return PERSON, {'reason': 'almost no flat designed area found'}
    keep = flat.copy()
    if a.get('skip_ground'):
        regions = _regions(rgb, flat, outside, 0.01, tol)
        if not regions:
            return PERSON, {'reason': 'no ground found'}
        keep &= ~r3._near_mask(rgb, [regions[0][0]], tol + 2)
    off = keep & ~r3._near_mask(rgb, a['hexes'], tol)
    bad, unsure = {}, {}
    import cv2
    photo = cv2.dilate((~outside).astype(np.uint8), np.ones((41, 41), np.uint8)) > 0     # within 20 px of a photograph
    if a.get('photo_touch'):
        # photographs present but not matched to a supplied file: their smooth parts (a backdrop, a tyre) are not
        # left out by texture alone, so no off-palette piece can be called designed colour with certainty
        import objective_ops_r2 as r2
        found = np.zeros(outside.shape, bool)
        for name in a.get('photos', []):
            try:
                page, box, state = r2._asset_box(path, a, name, 0)
            except FileNotFoundError:
                box = None
            if box is not None:
                x0, y0, x1, y1 = (int(round(v)) for v in box)
                found[max(0, y0 - 8):y1 + 8, max(0, x0 - 8):x1 + 8] = True
        tex = r3._photo_mask(path, {'photos': [], '_asset_dirs': a.get('_asset_dirs')})
        if (tex & ~found).sum() >= 0.01 * tex.size:
            photo[:] = True
    for comp, st in r3._components(off):
        colour = r3._to_hex(np.median(rgb[comp], axis=0))
        # a piece touching a photograph may be the photograph's own (a cut-out's tyre, a seamless backdrop the
        # supplied file was not matched over): a person decides; a piece standing apart is designed colour
        target = unsure if a.get('photo_touch') and (comp & photo).any() else bad
        target[colour] = target.get(colour, 0) + int(st[4])
    top = lambda d: [f'{c} ({n} px)' for c, n in sorted(d.items(), key=lambda kv: -kv[1])[:5]]
    if bad:
        return 'fail', {'outside_palette': top(bad)}
    if unsure:
        return PERSON, {'reason': 'colours outside the palette only where they touch a photograph', 'colours': top(unsure)}
    return 'pass', {'palette': a['hexes']}


# ---------------------------------------------------------------- thin rules on images


def _blend_identity(c, g, cands):
    """Which candidate colour a thin line's measured colour c is, on ground g: a thin line blends with its ground,
    so its colour lies on the segment from the ground to its own ink. Returns (hex, t) when one candidate fits
    clearly (residual 14 or less, at least 35% ink, and the next candidate fits at least twice as badly), else
    (None, fits)."""
    fits = []
    for h in cands:
        p = r3._hex_rgb(h).astype(float)
        d = p - g
        if (d @ d) < 1:
            continue
        t = float(((c - g) @ d) / (d @ d))
        resid = float(np.linalg.norm(c - (g + max(0.0, min(1.2, t)) * d)))
        fits.append((resid, t, h))
    fits.sort()
    if fits and fits[0][0] <= 14 and fits[0][1] >= 0.35 and (len(fits) == 1 or fits[1][0] >= 2 * max(fits[0][0], 4)):
        return fits[0][2], fits[0][1]
    return None, [(h, round(r, 1), round(t, 2)) for r, t, h in fits[:3]]


def _rules(rgb, outside, min_len, thin):
    """Horizontal rules: runs of pixels unlike the row's own ground, min_len long, thin rows thick at most.
    Returns [(y0, y1, x0, x1, colour, ground)], colour the median of the run's most contrasting pixels."""
    h, w = rgb.shape[:2]
    rowinfo = []
    for yy in range(h):
        row = rgb[yy].astype(int)
        if outside[yy].sum() < 0.2 * w:
            rowinfo.append(((0, 0, 0), np.zeros(3)))     # a row taken up by photographs: no rule is read there
            continue
        vals, cnt = np.unique(row[outside[yy]] // 4, axis=0, return_counts=True)
        g = vals[cnt.argmax()] * 4 + 2
        diff = (np.abs(row - g).sum(axis=1) > 24) & outside[yy]
        if not diff.any():
            rowinfo.append(((0, 0, 0), g))
            continue
        d = np.diff(np.concatenate([[0], diff.astype(np.int8), [0]]))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        i = int((ends - starts).argmax())
        rowinfo.append(((int(ends[i] - starts[i]), int(starts[i]), int(ends[i])), g))
    out = []
    yy = 0
    while yy < h:
        (n, x0, x1), g = rowinfo[yy]
        if n >= min_len:
            y1 = yy
            while y1 + 1 < h and rowinfo[y1 + 1][0][0] >= min_len and abs(rowinfo[y1 + 1][0][1] - x0) < 0.05 * w:
                y1 += 1
            if y1 - yy + 1 <= thin:
                band = rgb[yy:y1 + 1, x0:x1].reshape(-1, 3).astype(float)
                ground = g.astype(float)
                d = np.abs(band - ground).sum(axis=1)
                core = band[d >= 0.9 * d.max()]
                out.append((yy, y1, x0, x1, np.median(core, axis=0), ground))
            yy = y1 + 1
        else:
            yy += 1
    return out


def op_rule_colour_raster(path, a):
    """The colour of horizontal rules (one colour, at least min_len of the image width long, thin): the rule
    directly below a text line (below: pattern; within 3 line heights, nothing between), or every rule. A thin rule
    blends with its ground, so its colour is told by the direction it takes from the ground (see _blend_identity)
    among the candidate palette colours. colors: the allowed identity; on: {ground hex: allowed colours} where it
    depends on the ground. A rule clearly another palette colour fails; an unclear one goes to a person."""
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    outside = ~r3._photo_mask(path, a)
    thin = a.get('thin_px', max(4, round(0.006 * min(h, w))))
    rules = _rules(rgb, outside, int(a.get('min_len', 0.25) * w), thin if a.get('max_rows') is None else max(thin, 3 * a['max_rows']))
    if a.get('below'):
        layer = merged(text_layers(path))
        hits = [l for l in layer.lines if base._real(l) and (re.search(a['below'], canon(l.text), re.I) or re.search(a['below'], base.squash(canon(l.text)), re.I))]
        if not hits:
            if a.get('optional') and getattr(layer, 'confident_all', layer.confident):
                return 'pass', {'reason': 'no such text shown'}
            return PERSON, {'reason': 'text not found'}
        picked = []
        for l in hits:
            lh = l.bbox[3] - l.bbox[1]
            cands = [r for r in rules if l.bbox[3] - 0.4 * lh <= r[0] <= l.bbox[3] + 3 * lh and r[2] < l.bbox[2] and r[3] > l.bbox[0]]
            others = [k for k in layer.lines if k is not l and base._real(k)]
            cands = [r for r in cands if not any(k.bbox[1] > l.bbox[3] - 1 and k.bbox[3] < r[0] and k.bbox[0] < r[3] and k.bbox[2] > r[2] for k in others)]
            if not cands:
                return PERSON, {'reason': 'no rule found directly below', 'line': l.text}
            picked.append(min(cands, key=lambda r: r[0]))
        rules = picked
    # a "rule" in the colour of the image's own main ground is a gap between pictures, not a drawn rule
    vals, cnt = np.unique(rgb[outside] // 4, axis=0, return_counts=True) if outside.any() else (np.zeros((1, 3)), [1])
    main = vals[int(np.argmax(cnt))] * 4 + 2
    rules = [r for r in rules if np.abs(r[4] - main).max() > 12]
    if not rules:
        return PERSON, {'reason': 'no rule found'}
    if a.get('max_rows') is not None:
        thick = [r[1] - r[0] + 1 for r in rules]
        return ('pass' if max(thick) <= a['max_rows'] else 'fail'), {'rows': thick}
    if a.get('full_width'):
        spans = [(r[2], r[3]) for r in rules]
        ok = all(x0 <= 2 and x1 >= w - 2 for x0, x1 in spans)
        return ('pass', {'spans': spans}) if ok else (PERSON, {'reason': 'the rule does not run edge to edge', 'spans': spans})
    bad, unsure, seen = [], [], []
    for y0, y1, x0, x1, c, g in rules:
        ghex = r3._to_hex(g)
        allowed = a.get('colors', [])
        for gh, cols in a.get('on', {}).items():
            if base._near_hex(ghex, [gh], 10):
                allowed = cols
        ident, info = _blend_identity(c, g, a['candidates'])
        seen.append({'y': y0, 'colour': r3._to_hex(c), 'ground': ghex, 'is': ident})
        if ident is None:
            unsure.append({'y': y0, 'colour': r3._to_hex(c), 'ground': ghex, 'fits': info})
        elif ident not in allowed:
            bad.append({'y': y0, 'is': ident, 'colour': r3._to_hex(c), 'ground': ghex})
    if bad:
        return 'fail', {'rules': bad[:4]}
    if unsure:
        return PERSON, {'reason': 'a rule colour not clear enough to call', 'rules': unsure[:3]}
    return 'pass', {'rules': seen[:6]}


# ---------------------------------------------------------------- what sits behind a subject, and marks' parts


def op_behind_subject_raster(path, a):
    """The ground directly round each located supplied photo (a band 4 to 14 px outside where it shows) is not one
    of the forbidden colours: half or more of the band in one fails, a tenth to a half goes to a person. A photo
    not found goes to a person."""
    import objective_ops_r2 as r2
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    tol = r3._tol(path, a) + 3
    out, unsure = [], []
    for name in ([a['photo']] if a.get('photo') else a['photos']):
        page, box, state = r2._asset_box(path, a, name, 0)
        if box is None:
            return PERSON, {'reason': f'{name} not found'}
        x0, y0, x1, y1 = (int(round(v)) for v in box)
        ring = np.zeros((h, w), bool)
        ring[max(0, y0 - 14):min(h, y1 + 14), max(0, x0 - 14):min(w, x1 + 14)] = True
        ring[max(0, y0 - 4):min(h, y1 + 4), max(0, x0 - 4):min(w, x1 + 4)] = False
        px = rgb[ring]
        if not len(px):
            unsure.append(name)
            continue
        share = float(r3._near_mask(px[None], a['forbidden'], tol)[0].mean())
        out.append({'photo': name, 'forbidden_share': round(share, 2)})
        if share >= 0.5:
            return 'fail', {'behind': out[-1]}
        if share >= 0.1:
            unsure.append(name)
    if unsure:
        return PERSON, {'reason': 'part of the ground round a subject is in the colour', 'photos': out}
    return 'pass', {'photos': out}


def _wordmark(l, word):
    """A text line that is the wordmark: the word alone, or with one stray token of one or two characters before it
    (OCR sometimes reads the symbol beside the word as a letter)."""
    return re.fullmatch(rf'\W*(?:\S{{1,2}}\s+)?(?:{word})\W*', canon(l.text).strip(' .'), re.I) is not None


def _symbol_box(l, word):
    """Where the symbol set left of a wordmark line sits: up to 1.6 line heights left of the line, from 0.8 heights
    above to 0.2 below; when a stray token was read from the symbol, the line's own first half height too."""
    x0, y0, x1, y1 = l.bbox
    lh = y1 - y0
    stray = re.fullmatch(rf'\W*(?:{word})\W*', canon(l.text).strip(' .'), re.I) is None
    return (x0 - 1.6 * lh, y0 - 0.8 * lh, x0 + (0.5 * lh if stray else -2), y1 + 0.2 * lh)


def _dominant(px):
    """The commonest colour among the pixels (8-level bins), as the median of its bin: a symbol's own fill, not a
    thin outline or the anti-aliased edge round it."""
    q = (px // 8).astype(int)
    vals, cnt = np.unique(q, axis=0, return_counts=True)
    top = vals[cnt.argmax()]
    return np.median(px[(q == top).all(axis=1)], axis=0)


def op_leaf_mark_raster(path, a):
    """A word-and-symbol mark found by its wordmark line (word: a pattern the whole line must match, such as
    NORTHGROVE): the wordmark's ink (word_colors) and the symbol set just left of it (the ink within 1.6 wordmark
    heights to its left, from 0.8 heights above to 0.2 below; leaf_colors) are checked where the ground round the
    wordmark is one of on (another ground passes). pass_if_no_colour: no flat area of these colours outside
    photographs passes (no mark can sit on them). A wordmark not read, or no symbol beside it, goes to a person."""
    tol = r3._tol(path, a) + 3
    rgb = r3._pixels(str(path))
    h, w = rgb.shape[:2]
    if a.get('pass_if_no_colour'):
        rgb0, flat0, outside0 = r3._designed(path, a)
        if not r3._components(flat0 & outside0 & r3._near_mask(rgb0, a['pass_if_no_colour'], r3._tol(path, a)),
                              max(r3.MIN_COMPONENT, int(0.002 * h * w))):
            return 'pass', {'reason': 'no ground of that colour, so no mark on it'}
    layer = merged(text_layers(path))
    marks = [l for l in layer.lines if l.conf >= a.get('min_conf', 60) and _wordmark(l, a['word'])]
    if not marks:
        return PERSON, {'reason': 'wordmark not read (the mark may be absent or drawn differently)'}
    checked, bad, unsure, ev = 0, [], [], []
    for l in marks:
        got = r3._ink_and_ground(rgb, l.bbox)
        if got is None:
            unsure.append(l.text)
            continue
        ink, ground, share = got
        g_hex = r3._to_hex(ground)
        if a.get('on') and not base._near_hex(g_hex, a['on'], tol + 3):
            continue
        checked += 1
        item = {'ground': g_hex, 'wordmark': r3._to_hex(ink)}
        if a.get('word_colors'):
            dist = min(np.abs(ink - r3._hex_rgb(c)).max() for c in a['word_colors'])
            if dist > tol:
                (bad if dist >= 30 else unsure).append(dict(item, part='wordmark'))
        if a.get('leaf_colors'):
            sx0, sy0, sx1, sy1 = _symbol_box(l, a['word'])
            box = rgb[max(0, int(sy0)):min(h, int(sy1)), max(0, int(sx0)):max(0, int(sx1))].reshape(-1, 3).astype(float)
            d = np.abs(box - ground).sum(axis=1) if len(box) else np.zeros(0)
            if len(box) == 0 or (d > 60).sum() < max(40, 0.05 * len(box)):
                unsure.append(dict(item, part='symbol not found beside the wordmark'))
            else:
                c = _dominant(box[d > 0.5 * d.max()])
                item['symbol'] = r3._to_hex(c)
                dist = min(np.abs(c - r3._hex_rgb(x)).max() for x in a['leaf_colors'])
                if dist > tol:
                    (bad if dist >= 30 else unsure).append(dict(item, part='symbol'))
        ev.append(item)
    if bad:
        return 'fail', {'wrong': bad[:3]}
    if unsure:
        return PERSON, {'reason': 'a part of the mark not clear enough to call', 'parts': unsure[:3]}
    if not checked:
        return 'pass', {'reason': 'no mark on that ground', 'marks': len(marks)}
    return 'pass', {'marks': ev[:3]}


# ---------------------------------------------------------------- copied wording


def op_verbatim_if_any(path, a):
    """Any line that carries one of the approved texts' key words (a colourway name with a description, say) holds
    the approved text word for word. An exact copy passes; a near copy, or a description that differs, goes to a
    person (OCR may misread; PDFs fail on a clear difference). Nothing of the kind shown passes when the text was
    read reliably."""
    layer = merged(text_layers(path))
    if not layer.readable:
        return PERSON, {'reason': 'no readable text'}
    lines = [l for l in layer.lines if base._real(l)]
    hay = ' '.join(l.text for l in lines)
    found, odd = [], []
    for key, text in a['texts'].items():
        if contains(hay, text, False):
            found.append(key)
            continue
        cands = [l.text for l in lines if re.search(rf'(?<![\w]){re.escape(key)}(?![\w])', l.text, re.I) and len(l.text.split()) >= 4]
        if base.near_miss(hay, text) >= 0.75 or cands:
            odd.append({'key': key, 'lines': cands[:2]})
    if odd:
        return ('fail' if layer.source == 'pdf' else PERSON), {'reason': 'a text close to, or describing, an approved one without matching it', 'found': odd[:3]}
    if not (layer.source == 'pdf' or getattr(layer, 'confident_all', layer.confident)):
        return PERSON, {'reason': 'text not read clearly enough to rule out an altered copy'}
    return 'pass', {'exact': found}


# ---------------------------------------------------------------- conditions, sizes, each photo, PDF type style


def op_if_then(path, a):
    """The check (then) applies only where the text pattern (if) is shown. Not shown: a pass when the text was read
    reliably (live PDF text, or OCR confident on every wording line outside the photographs), else a person."""
    layer, lines, sure = _outside_lines(path, dict(a, photos=a.get('photos', [])))
    shown = [l for l in layer.lines if base._real(l) and (re.search(a['if'], canon(l.text), re.I) or re.search(a['if'], base.squash(canon(l.text)), re.I))]
    if not shown:
        if layer.source == 'pdf' or sure:
            return 'pass', {'reason': 'not shown (the check applies only where it appears)'}
        return PERSON, {'reason': 'could not rule out that it appears'}
    return base.run(path, _sub(a, a['then']))


def _pattern_lines(layer, patterns, min_conf=OCR_GOOD_CONF):
    out = []
    for l in layer.lines:
        if l.source != 'pdf' and (l.conf < min_conf or len(re.findall(r'[A-Za-z0-9]', l.text)) < 2):
            continue
        t = canon(l.text)
        if any(re.search(p, t, re.I) or re.search(p, base.squash(t), re.I) for p in patterns):
            out.append(l)
    return out


def op_sizes_vs(path, a):
    """Every line matching a (patterns) is set smaller (rel 'smaller') or larger than every line matching b, lines
    matching both left out. Sizes are font sizes in PDFs and letter heights on images (8% too close to call there).
    a not shown: a pass when optional and read reliably; b not shown: a pass (nothing to compare)."""
    layer = merged(text_layers(path))
    la = _pattern_lines(layer, a['a'])
    lb = [l for l in _pattern_lines(layer, a['b']) if l not in la]
    reliable = layer.source == 'pdf' or getattr(layer, 'confident_all', layer.confident)
    if not la:
        return ('pass', {'reason': 'not shown'}) if a.get('optional') and reliable else (PERSON, {'reason': 'text not found'})
    if not lb:
        return ('pass', {'reason': 'nothing to compare shown'}) if reliable else (PERSON, {'reason': 'compared text not found'})
    if not all(l.size_ok for l in la + lb):
        return PERSON, {'reason': 'letter height could not be measured on every line compared'}
    margin = base.SIZE_MARGIN if layer.source == 'ocr' else 0.01
    worst = None
    for x in la:
        for y in lb:
            r = x.size / y.size if y.size else 99
            ok = r < 1 - margin if a['rel'] == 'smaller' else r > 1 + margin
            if not ok:
                close = abs(r - 1) <= margin and layer.source == 'ocr'
                item = ('person' if close else 'fail', {'a': x.text[:30], 'a_size': round(x.size, 1), 'b': y.text[:30], 'b_size': round(y.size, 1)})
                if worst is None or item[0] == 'fail':
                    worst = item
    if worst:
        st, ev = worst
        if st == 'fail' and layer.source == 'ocr' and not all(l.conf >= OCR_GOOD_CONF for l in la + lb):
            st = PERSON
        return (PERSON if st == 'person' else 'fail'), ev
    return 'pass', {'a': [round(l.size, 1) for l in la][:4], 'b': [round(l.size, 1) for l in lb][:4]}


def op_for_each_photo(path, a):
    """Runs the check (then, given photo=<file>) for every supplied photo found in the deliverable; photos not shown
    are left out. Any fail fails; any unclear part goes to a person; none found goes to a person."""
    results = []
    for name in a['photos']:
        try:
            pair = r3._photo_pair(path, dict(a, photo=name, photos=None))
        except FileNotFoundError:
            pair = None
        if pair is None:
            continue
        results.append((name, base.run(path, _sub(a, dict(a['then'], photo=name, asset=name, assets=[name])))))
    if not results:
        return PERSON, {'reason': 'no supplied photo found'}
    for want in ('fail', PERSON):
        for name, (st, ev) in results:
            if st == want:
                return st, dict(ev, photo=name)
    if _unmatched_photos(path, a, a['photos']):
        return PERSON, {'reason': 'a photograph shown is not matched to a supplied file, so not every one was checked', 'checked': [n for n, _ in results]}
    return 'pass', {'photos': [n for n, _ in results]}


def op_pdf_lines_style(path, a):
    """PDF type style of lines picked by _select_pdf_lines: family and weight (except_digits: figures may differ),
    size, or leading (baseline gap between consecutive lines of one block)."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer, body, roles = _pdf_body(str(path))
    if body is None:
        return PERSON, {'reason': 'no running text found to set the body size'}
    sel = _select_pdf_lines(layer, body, roles, a)
    if not sel:
        return 'pass', {'reason': 'no such text'}
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
        return ('fail', {'sizes': bad}) if bad else ('pass', {'lines': len(sel)})
    if 'leading' in a:
        gaps = []
        ordered = sorted(sel, key=lambda l: (l.page, l.bbox[1]))
        for x, y in zip(ordered, ordered[1:]):
            if x.page == y.page and abs(x.bbox[0] - y.bbox[0]) < 2 and abs(x.size - y.size) < 0.3 and 0 < y.bbox[3] - x.bbox[3] < 2.2 * x.size:
                gaps.append(round(y.bbox[3] - x.bbox[3], 2))
        if not gaps:
            return 'pass', {'reason': 'no wrapped block'}
        bad = [g for g in gaps if abs(g - a['leading']) > a.get('tolerance', 0.5)]
        return ('fail', {'baseline_gaps': bad[:6]}) if bad else ('pass', {'baseline_gaps': sorted(set(gaps))})
    return PERSON, {'reason': 'nothing to check'}


# ---------------------------------------------------------------- a placed photograph against its supplied file

WORK = 900          # supplied files are compared at this long side


def _scenes_rgb(path: Path):
    """What a photo may be placed in: the image itself, or every picture embedded in a PDF (its own pixels)."""
    from PIL import Image
    if path.suffix.lower() != '.pdf':
        return [('image', r3._pixels(str(path)).astype(np.uint8))]
    import pymupdf
    doc = pymupdf.open(path)
    out = []
    for page in doc:
        for info in page.get_image_info(xrefs=True):
            if not info.get('xref'):
                continue
            pix = pymupdf.Pixmap(doc, info['xref'])
            if pix.n - pix.alpha < 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            arr = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]
            out.append((f'page {page.number + 1} image {info["xref"]}', np.ascontiguousarray(arr)))
    return out


_REG: dict = {}


def _register(path: Path, a, name, full=False):
    """The supplied file (scaled to WORK, or at its own size when full: fine grain is compared at 100%) and every
    placement of it found, warped back onto it: [(where, src, back, valid, inside)], inside True when the whole
    file lies within the scene."""
    import cv2
    from PIL import Image
    key = (str(path), name, full)
    if key in _REG:
        return _REG[key]
    big = np.asarray(Image.open(base.asset_path(a, name)).convert('RGB'))
    k = min(1.0, WORK / max(big.shape[:2]))
    src = big if k >= 1 else cv2.resize(big, (round(big.shape[1] * k), round(big.shape[0] * k)), interpolation=cv2.INTER_AREA)
    gsrc = cv2.cvtColor(src, cv2.COLOR_RGB2GRAY)
    found = []
    for where, scene in _scenes_rgb(path):
        gs = cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY)
        f = min(1.0, 2000 / max(gs.shape))           # large scenes are matched on a reduced copy, then scaled back
        small = gs if f >= 1 else cv2.resize(gs, (round(gs.shape[1] * f), round(gs.shape[0] * f)), interpolation=cv2.INTER_AREA)
        n, corners, state = base.find_asset(small, gsrc)
        if state != 'found':
            continue
        corners = np.float32(corners) / f
        h, w = gsrc.shape
        H = cv2.getPerspectiveTransform(np.float32([[0, 0], [w, 0], [w, h], [0, h]]), np.float32(corners))
        ref = src
        if full and k < 1:
            H = H @ np.diag([k, k, 1.0])
            ref = big
            h, w = big.shape[:2]
        inv = np.linalg.inv(H)
        back = cv2.warpPerspective(scene, inv, (w, h), flags=cv2.INTER_LINEAR if full else cv2.INTER_AREA)
        valid = cv2.warpPerspective(np.full(gs.shape, 255, np.uint8), inv, (w, h), flags=cv2.INTER_NEAREST) > 0
        valid = cv2.erode(valid.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        inside = bool((corners[:, 0] >= -2).all() and (corners[:, 1] >= -2).all() and (corners[:, 0] <= gs.shape[1] + 2).all() and (corners[:, 1] <= gs.shape[0] + 2).all())
        scale = float(np.sqrt(abs(np.linalg.det(H[:2, :2]))))
        # how much of the scene's photograph the supplied file accounts for: an embedded picture is all photograph;
        # on an image, the photograph is the textured area round the placement
        quad = np.zeros(gs.shape, np.uint8)
        cv2.fillConvexPoly(quad, np.int32(np.clip(corners, -1e4, 1e4)), 1)
        if where == 'image':
            photo = r3._photo_mask(path, {'photos': []})
            near = cv2.dilate(quad, np.ones((41, 41), np.uint8)) > 0
            region = photo & near
            covers = float((region & (quad > 0)).sum() / max(1, region.sum()))
        else:
            covers = float(quad.mean())
        found.append((where, ref.astype(np.float32), back.astype(np.float32), valid, inside, scale, covers))
    _REG[key] = found
    return found


def _lab(rgb):
    import cv2
    lab = cv2.cvtColor(np.clip(rgb, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    return np.dstack([lab[..., 0] * 100 / 255, lab[..., 1] - 128, lab[..., 2] - 128])


def _fit(src, back, m):
    """The supplied file put through one global tone and colour curve (per channel gain and offset) that best
    matches the placement: what is left over is local change."""
    out = np.empty_like(src)
    for c in range(3):
        x, y = src[..., c][m], back[..., c][m]
        g, o = np.polyfit(x, y, 1) if len(x) > 100 and x.std() > 1 else (1.0, float((y - x).mean()) if len(x) else 0.0)
        out[..., c] = src[..., c] * g + o
    return out


def _tiles(m, size=32, cover=0.8):
    h, w = m.shape
    for y in range(0, h - size + 1, size):
        for x in range(0, w - size + 1, size):
            sl = (slice(y, y + size), slice(x, x + size))
            if m[sl].mean() >= cover:
                yield sl


def _ncc(x, y):
    x, y = x - x.mean(), y - y.mean()
    d = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / d) if d > 1e-6 else 1.0


def _test(t, src, back, m, inside, a):
    import cv2
    gray = lambda im: im @ np.array([0.299, 0.587, 0.114], np.float32)
    if t in ('tiles', 'whole', 'changed', 'tile_de'):
        fit = _fit(src, back, m)
        gf, gb = gray(fit), gray(back)
        worst, resid = 1.0, 0.0
        for sl in _tiles(m):
            r = float(np.abs(gb[sl] - gf[sl]).mean())
            resid = max(resid, r)
            if gf[sl].std() < 4 and gb[sl].std() < 4:
                c = 1.0 if r < 8 else 0.0
            else:
                c = _ncc(gf[sl], gb[sl])
            worst = min(worst, c)
        ev = {'worst_tile_ncc': round(worst, 3), 'largest_tile_change': round(resid, 1), 'whole_file_inside': inside}
        if t == 'changed':
            return ('fail', dict(ev, reason='no local change from the supplied file')) if resid <= 4 else (PERSON, dict(ev, reason='changed in places; a person judges the repair'))
        if t == 'tile_de':
            la, lb = _lab(fit), _lab(back)
            de = max((float(np.sqrt(((la[sl] - lb[sl]) ** 2).sum(axis=2)).mean()) for sl in _tiles(m)), default=0.0)
            ev['largest_tile_delta_e'] = round(de, 1)
            return ('pass', ev) if de <= a.get('max_de', 4) else (PERSON, dict(ev, reason='a local colour change'))
        ok = worst >= a.get('min_ncc', 0.9) and (inside or t == 'tiles')
        return ('pass', ev) if ok else (PERSON, dict(ev, reason='differs from the supplied file in places' if inside else 'the supplied file is not shown whole'))
    if t == 'detail':
        hp = lambda im: im - cv2.GaussianBlur(im, (0, 0), 2)
        hs, hb = hp(gray(src)), hp(gray(back))
        worst_c, worst_e, n = 1.0, 9.0, 0
        for sl in _tiles(m):
            es = float((hs[sl] ** 2).mean())
            if es < 4:
                continue
            n += 1
            worst_c = min(worst_c, _ncc(hs[sl], hb[sl]))
            worst_e = min(worst_e, float((hb[sl] ** 2).mean()) / es)
        ev = {'worst_detail_ncc': round(worst_c, 3), 'least_detail_kept': round(worst_e, 2), 'tiles': n}
        if not n:
            return PERSON, dict(ev, reason='no textured area to compare')
        return ('pass', ev) if worst_c >= 0.8 and worst_e >= 0.8 else (PERSON, dict(ev, reason='detail weaker or different in places'))
    ls, lb = _lab(src), _lab(back)
    cs, cb = np.hypot(ls[..., 1], ls[..., 2]), np.hypot(lb[..., 1], lb[..., 2])
    if t == 'mono':
        rise = (cb - cs)[m]
        hs = np.degrees(np.arctan2(ls[..., 2], ls[..., 1]))[m]
        hb = np.degrees(np.arctan2(lb[..., 2], lb[..., 1]))[m]
        tone = float(np.degrees(np.arctan2(np.median(ls[..., 2][m]), np.median(ls[..., 1][m]))))
        far = np.abs((hb - tone + 180) % 360 - 180) > 40
        p99 = float(np.percentile(rise, 99))
        coloured = float(((rise > 12) & far).mean())
        ev = {'chroma_rise_p99': round(p99, 1), 'share_colourised': round(coloured, 3)}
        if p99 <= 4:
            return 'pass', ev
        return ('fail' if coloured >= 0.02 else PERSON), ev
    hue = np.degrees(np.arctan2(lb[..., 2], lb[..., 1]))
    hue_s = np.degrees(np.arctan2(ls[..., 2], ls[..., 1]))
    warm = lambda c, h: float(np.where((h >= 40) & (h <= 90), c, 0)[m].mean())
    db = float(lb[..., 2][m].mean() - ls[..., 2][m].mean())
    da = float(lb[..., 1][m].mean() - ls[..., 1][m].mean())
    if t == 'sepia':
        rise = warm(cb, hue) - warm(cs, hue_s)
        ev = {'warm_chroma_rise': round(rise, 1), 'scan_chroma': round(float(cs[m].mean()), 1)}
        if rise < 2:
            return 'pass', ev
        return ('fail' if cs[m].mean() < 3 and rise >= 6 else PERSON), ev
    if t == 'b_drop':
        ev = {'b_change': round(db, 1)}
        return (PERSON, ev) if db <= -5 else ('fail', dict(ev, reason='the yellow cast is not reduced'))
    if t == 'no_warmer':
        rise = warm(cb, hue) - warm(cs, hue_s)
        ev = {'b_change': round(db, 1), 'warm_chroma_rise': round(rise, 1)}
        return ('fail', ev) if db > 0 or rise > 0 else (PERSON, dict(ev, reason='not warmer than the faded scan; a person judges'))
    if t == 'range':
        rng = lambda L: float(np.percentile(L[m], 99) - np.percentile(L[m], 1))
        rs, rb = rng(ls[..., 0]), rng(lb[..., 0])
        ev = {'range_scan': round(rs, 1), 'range_now': round(rb, 1)}
        return (PERSON, ev) if rb >= 1.1 * rs else ('fail', dict(ev, reason='tonal range not widened'))
    de = float(np.sqrt(((ls - lb) ** 2).sum(axis=2))[m].mean())
    if t == 'mean_de':
        ev = {'mean_delta_e': round(de, 1)}
        return ('pass', ev) if de < a.get('max_de', 3) else (PERSON, dict(ev, reason='colours differ from the supplied file'))
    if t == 'cast_left':
        ev = {'mean_delta_e': round(de, 1)}
        return ('fail', dict(ev, reason='colours as in the supplied file, cast left in')) if de <= 3 else (PERSON, dict(ev, reason='colours changed; a person judges the cast'))
    if t in ('warm_shift', 'glow'):
        dbs, das = [], []
        for sl in _tiles(m):
            dbs.append(float(lb[..., 2][sl].mean() - ls[..., 2][sl].mean()))
            das.append(float(lb[..., 1][sl].mean() - ls[..., 1][sl].mean()))
        if not dbs:
            return PERSON, {'reason': 'too little of the photo to compare'}
        ev = {'max_tile_b_rise': round(max(dbs), 1), 'max_tile_a_rise': round(max(das), 1), 'min_tile_a_change': round(min(das), 1)}
        if t == 'glow':
            return ('pass', ev) if max(dbs) < 2 and max(das) < 2 else (PERSON, dict(ev, reason='warmer in places'))
        if max(dbs) < 3 and min(das) > -3:
            return 'pass', ev
        return ('fail' if db >= 6 or da <= -6 else PERSON), dict(ev, mean_b_change=round(db, 1), mean_a_change=round(da, 1))
    if t == 'crush':
        dark = lambda im: float(((im <= 8).all(axis=2))[m].mean())
        ds, dbk = dark(src), dark(back)
        gs, gb = gray(src), gray(back)
        shadows = [sl for sl in _tiles(m) if gs[sl].mean() <= np.percentile(gs[m], 20)]
        kept = min((float(gb[sl].std() / max(gs[sl].std(), 1e-3)) for sl in shadows if gs[sl].std() >= 2), default=1.0)
        ev = {'black_share_scan': round(ds, 4), 'black_share_now': round(dbk, 4), 'shadow_contrast_kept': round(kept, 2)}
        if dbk <= ds + 0.005 and kept >= 0.9:
            return 'pass', ev
        return ('fail' if dbk >= ds + 0.05 else PERSON), ev
    raise ValueError(f'unknown test {t}')


def _unmatched_photos(path, a, names):
    """Whether photographs are shown that none of the named supplied files accounts for (so a check about every
    photograph cannot pass on the ones found): on an image, textured area of 1% or more outside the found files'
    boxes; in a PDF, a placed picture of 2% of the page or more that matches none of them."""
    import objective_ops_r2 as r2
    if path.suffix.lower() == '.pdf':
        scenes = [w for w, _ in _scenes_rgb(path)]
        hit = {w for name in names for w, *_ in _register(path, a, name)}
        import pymupdf
        doc = pymupdf.open(path)
        big = set()
        for page in doc:
            for info in page.get_image_info(xrefs=True):
                b = info['bbox']
                if info.get('xref') and (b[2] - b[0]) * (b[3] - b[1]) >= 0.02 * page.rect.width * page.rect.height:
                    big.add(f'page {page.number + 1} image {info["xref"]}')
        return bool(big - hit)
    found = None
    for name in names:
        try:
            page, box, state = r2._asset_box(path, a, name, 0)
        except FileNotFoundError:
            box = None
        if box is not None:
            if found is None:
                found = np.zeros(r3._pixels(str(path)).shape[:2], bool)
            x0, y0, x1, y1 = (int(round(v)) for v in box)
            found[max(0, y0 - 8):y1 + 8, max(0, x0 - 8):x1 + 8] = True
    tex = r3._photo_mask(path, {'photos': [], '_asset_dirs': a.get('_asset_dirs')})
    if found is None:
        return bool(tex.sum() >= 0.01 * tex.size)
    return bool((tex & ~found).sum() >= 0.01 * tex.size)


def op_vs_source(path, a):
    """A placed photograph against its supplied file (photo; or every one of photos that is found). The file is
    found by its features, the placement warped back onto it, and test applied (see _test): tiles (every 32 px tile
    correlates min_ncc after one global tone curve: nothing added or reshaped), whole (also the whole file shown),
    changed (no local change at all fails: damage left), tile_de, detail (fine texture kept), mono, sepia, b_drop,
    no_warmer, range, mean_de, cast_left, warm_shift, glow, crush. A file not found goes to a person."""
    names = [a['photo']] if a.get('photo') else a['photos']
    results = []
    for name in names:
        for where, src, back, valid, inside, scale, covers in _register(path, a, name, bool(a.get('full'))):
            if valid.mean() < 0.15:
                results.append((PERSON, {'photo': name, 'where': where, 'reason': 'only a small part of the photo is shown'}))
                continue
            st, ev = _test(a['test'], src, back, valid, inside, a)
            ev = dict(ev, photo=name, where=where, scale=round(scale, 2))
            if st == 'pass' and a.get('max_scale') and scale > a['max_scale']:
                st, ev = PERSON, dict(ev, reason='shown larger than the supplied pixels')
            if st == 'pass' and a.get('min_cover') and covers < a['min_cover']:
                st, ev = PERSON, dict(ev, reason='part of the photograph lies beyond the supplied file (extended or another picture)', covers=round(covers, 3))
            results.append((st, ev))
    if not results:
        return PERSON, {'reason': 'supplied photo not found'}
    for want in ('fail', PERSON):
        for st, ev in results:
            if st == want:
                return st, ev
    if a.get('every') and _unmatched_photos(path, a, names):
        return PERSON, {'reason': 'a photograph shown is not matched to a supplied file, so not every one was checked'}
    return 'pass', results[0][1] if len(results) == 1 else {'placements': len(results), 'first': results[0][1]}


def op_made_from(path, a):
    """The deliverable is made from the expected supplied file and no other: of the listed files, the expected one
    is found and no other is (fail when another is found; a person when none is, or the match is unclear)."""
    import objective_ops_r2 as r2
    import cv2
    found, unsure = [], []
    shrink = lambda g: g if max(g.shape) <= 1200 else cv2.resize(g, (round(g.shape[1] * 1200 / max(g.shape)), round(g.shape[0] * 1200 / max(g.shape))), interpolation=cv2.INTER_AREA)
    scenes = [shrink(sc) for sc in base._scenes(path)]
    for name in a['photos']:
        asset = shrink(base._load_gray(base.asset_path(a, name)))
        for scene in scenes:
            n, corners, state = base.find_asset(scene, asset)
            if state == 'found':
                found.append(name)
                break
            if state == 'unsure':
                unsure.append(name)
    others = [n for n in found if n != a['expected']]
    if others:
        return 'fail', {'also_made_from': others[:3]}
    if a['expected'] in found and not [u for u in unsure if u != a['expected']]:
        return 'pass', {'found': a['expected']}
    return PERSON, {'reason': 'the expected file not found clearly', 'unsure': unsure[:3]}


def op_section_photos(path, a):
    """PDF: on the pages carrying the section's heading and no other section's, every placed photograph is one of
    the section's own supplied files (others: every supplied file of the other sections). A photo of another
    section fails; a picture matching no supplied file goes to a person (the brand mark, given in ignore, aside)."""
    import pymupdf
    import cv2
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    doc = pymupdf.open(path)
    layer = base.pdf_layer(str(path))
    pages = [p for p in range(len(doc)) if any(contains(l.text, a['heading'], False) for l in layer.lines if l.page == p)
             and not any(contains(l.text, o, False) for o in a['other_headings'] for l in layer.lines if l.page == p)]
    if not pages:
        return PERSON, {'reason': 'section not found'}
    seen, bad, unknown = [], [], []
    for p in pages:
        for info in doc[p].get_image_info(xrefs=True):
            if not info.get('xref'):
                continue
            pix = pymupdf.Pixmap(doc, info['xref'])
            if pix.n - pix.alpha < 3:
                pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
            img = cv2.cvtColor(np.ascontiguousarray(np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[..., :3]), cv2.COLOR_RGB2GRAY)
            hit = None
            for name in a['own'] + a['others'] + a.get('ignore', []):
                n, corners, state = base.find_asset(img, base._load_gray(base.asset_path(a, name)))
                if state == 'found':
                    hit = name
                    break
            if hit in a.get('ignore', []):
                continue
            if hit is None:
                unknown.append(p + 1)
            elif hit in a['own']:
                seen.append(hit)
            else:
                bad.append({'page': p + 1, 'photo': hit})
    if bad:
        return 'fail', {'other_section_photos': bad[:3]}
    if unknown:
        return PERSON, {'reason': 'a picture matching no supplied photo', 'pages': unknown[:3]}
    return ('pass', {'photos': seen}) if seen else (PERSON, {'reason': 'no photograph found in the section'})


def op_limit(path, a):
    """Runs the check and caps what it may decide: fail_as / pass_as turn a fail or a pass into another answer (a
    check that is only sure in one direction: a forbidden word read clearly is a sure fail, its absence is not a
    sure pass)."""
    st, ev = base.run(path, _sub(a, a['check']))
    if st == 'fail' and a.get('fail_as'):
        return a['fail_as'], dict(ev, capped='fail')
    if st == 'pass' and a.get('pass_as'):
        return a['pass_as'], dict(ev, capped='pass')
    return st, ev


def op_section_text(path, a):
    """PDF: the pages carrying the section's heading and no other section's heading contain the pattern (a pass);
    otherwise a person decides whether other wording says the same."""
    if path.suffix.lower() != '.pdf':
        return PERSON, {'reason': 'read from a PDF'}
    layer = base.pdf_layer(str(path))
    pages = {l.page for l in layer.lines if contains(l.text, a['heading'], False)}
    pages = [p for p in pages if not any(contains(l.text, o, False) for o in a['other_headings'] for l in layer.lines if l.page == p)]
    if not pages:
        return PERSON, {'reason': 'section not found'}
    text = ' '.join(l.text for l in layer.lines if l.page in pages)
    m = re.search(a['pattern'], canon(text), re.I)
    return ('pass', {'found': m.group(0), 'pages': [p + 1 for p in pages]}) if m else (PERSON, {'reason': 'no such word in the section', 'pages': [p + 1 for p in pages]})


OPS = {
    'v2_agree': op_agree,
    'v2_pdf_colour_roles': op_pdf_colour_roles,
    'v2_pdf_grounds': op_pdf_grounds,
    'v2_pdf_text_on_grounds': op_pdf_text_colour,
    'v2_pdf_area_share_pages': op_pdf_area_share,
    'v2_pdf_no_overlay': op_pdf_no_overlay,
    'v2_pdf_role_vs_lines': op_pdf_role_vs_lines,
    'v2_max_line_chars': op_max_line_chars,
    'v2_line_colour_raster': op_line_colour_raster,
    'v2_colour_roles_raster': op_colour_roles_raster,
    'v2_colour_absent_raster': op_colour_absent_raster,
    'v2_colour_only_by_raster': op_colour_only_by_raster,
    'v2_grounds_raster': op_grounds_raster,
    'v2_main_ground_raster': op_main_ground_raster,
    'v2_palette_raster_x': op_palette_raster_x,
    'v2_rule_colour_raster': op_rule_colour_raster,
    'v2_behind_subject_raster': op_behind_subject_raster,
    'v2_leaf_mark_raster': op_leaf_mark_raster,
    'v2_verbatim_if_any': op_verbatim_if_any,
    'v2_if_then': op_if_then,
    'v2_sizes_vs': op_sizes_vs,
    'v2_for_each_photo': op_for_each_photo,
    'v2_pdf_lines_style': op_pdf_lines_style,
    'v2_vs_source': op_vs_source,
    'v2_made_from': op_made_from,
    'v2_section_photos': op_section_photos,
    'v2_limit': op_limit,
    'v2_section_text': op_section_text,
}
