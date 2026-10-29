"""Round 5 (2026-10-29), vision helper c: four thin operations on top of ops_r5_vlm.answers(), with the same safety
rule (a check passes or fails only when every answer agrees; anything else goes to a person).

  vlm_frames_r5vc  frames picked by the film's own length, then one of the shared questions asked about them:
                   `from_end` (a list of seconds before the last frame; 0 is the last frame itself) or `every` (one
                   frame every so many seconds from the start, and the last frame); `then` names the shared op
                   (vlm_yesno_r5v or vlm_list_r5v) and the rest of the assertion is passed on.
  vlm_pages_r5vc   every page of a PDF (in order, each labelled with its page number), then one of the shared
                   questions asked about them (`then`, as above); `dpi` and `max_side` apply to every page.
  vlm_join_r5vc    the text copied, its pieces joined with single spaces, must equal `expected` (after the shared
                   whitespace, quote and dash normalising; `case` 'exact' or 'fold').
  vlm_part_r5vc    every text copied must be a run of whole words of `expected` (after normalising, letter case
                   folded; a run at least `near` (default 0.8) similar counts, so a misspelt title still reads as
                   the title): pass; every answer the same text that is not: fail.
  vlm_names_r5vc   a list question; fail only when every answer lists an item naming one of `names`; pass only when
                   every answer finds none (`none_found` 'pass'); any other answer goes to a person.
"""
from __future__ import annotations

import json
import re
import subprocess
from difflib import SequenceMatcher
from fractions import Fraction
from pathlib import Path

import ops_r5_vlm as V
from objective_ops import PERSON


def _video_frames(path: Path):
    """(frame count, frames per second) of the first video stream."""
    out = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                          'stream=nb_read_packets,r_frame_rate', '-of', 'json', str(path)],
                         capture_output=True, text=True, timeout=120, check=True)
    s = json.loads(out.stdout)['streams'][0]
    return int(s['nb_read_packets']), float(Fraction(s['r_frame_rate']))


def vlm_frames(file, a):
    n, fps = _video_frames(Path(file))
    last = (n - 1) / fps - 0.2 / fps          # just before the last frame's time: the frame decoded is the last one
    imgs = []
    for spec in a.get('images') or [{'src': 'deliverable'}]:
        spec = dict(spec)
        if 'from_end' in spec:
            ts = [max(0.0, last - float(x)) for x in spec.pop('from_end')]
        elif 'every' in spec:
            step = float(spec.pop('every'))
            ts = [k * step for k in range(int(last / step) + 1)] + [last]
        else:
            imgs.append(spec)
            continue
        for k, t in enumerate(sorted(set(round(t, 3) for t in ts))):
            imgs.append(dict(spec, time=t, label=f'Frame {k + 1} (at {t:.1f} s)'))
    b = {k: v for k, v in a.items() if k not in ('then', 'images')}
    st, ev = (V.OPS.get(a['then']) or OPS[a['then']])(file, dict(b, images=imgs, op=a['then']))
    return st, dict(ev or {}, frames=[i.get('time') for i in imgs if 'time' in i])


def pdf_pages(file, a):
    """The assertion with one image per page of the PDF (the page count read from the file)."""
    import fitz
    n = len(fitz.open(str(file)))
    base = {k: v for k, v in (a.get('page_spec') or {}).items()}
    imgs = [dict(base, src='deliverable', page=k, label=f'Page {k}') for k in range(1, n + 1)]
    return dict({k: v for k, v in a.items() if k not in ('then', 'images', 'page_spec')}, images=imgs, op=a['then'])


def vlm_pages(file, a):
    b = pdf_pages(file, a)
    st, ev = (V.OPS.get(b['op']) or OPS[b['op']])(file, b)
    return st, dict(ev or {}, pages=len(b['images']))


def _words(s):
    s = V._norm(s, 'fold')
    s = re.sub(r'[^\w$&%/\' -]', ' ', s)
    return ' '.join(s.split())


def _parsed_or_person(file, a):
    ans, err = V.answers(file, a)
    if err:
        return None, (PERSON, {'reason': err})
    ev = {'answers': V._ev(ans)}
    if not V._all_parsed(ans):
        return None, (PERSON, dict(ev, reason='an answer is missing or unreadable'))
    if any(x['parsed']['answer'] == 'cannot_tell' for x in ans):
        return None, (PERSON, dict(ev, reason='the model cannot tell'))
    return (ans, ev), None


def vlm_join(file, a):
    got, out = _parsed_or_person(file, a)
    if out:
        return out
    ans, ev = got
    case, dashes = a.get('case', 'exact'), a.get('dashes', 'fold')
    reads = [V._norm(' '.join(v for v in x['parsed']['values'] if v.strip()), case, dashes) for x in ans]
    if any(r != reads[0] for r in reads):
        return PERSON, dict(ev, reason='the answers read different text')
    if not reads[0]:
        return PERSON, dict(ev, reason='no text read')
    exp = V._norm(a['expected'], case, dashes)
    return ('pass' if reads[0] == exp else 'fail'), dict(ev, read=reads[0], expected=exp)


def vlm_part(file, a):
    got, out = _parsed_or_person(file, a)
    if out:
        return out
    ans, ev = got
    words = _words(a['expected']).split()
    whole = ' '.join(words)
    near = float(a.get('near', 0.8))

    def part(v):   # v is a run of the expected words, read as printed (a misspelt word still counts as that word)
        n = len(v.split())
        return any(SequenceMatcher(None, v, ' '.join(words[i:i + n])).ratio() >= near for i in range(max(1, len(words) - n + 1)))
    per = [sorted({_words(v) for v in x['parsed']['values'] if _words(v)}) for x in ans]
    if any(not p for p in per):
        return PERSON, dict(ev, reason='no text read')
    inside = [all(part(v) for v in p) for p in per]
    if all(inside):
        return 'pass', dict(ev, read=per[0])
    if any(inside) or any(p != per[0] for p in per):
        return PERSON, dict(ev, reason='the answers do not agree')
    return 'fail', dict(ev, read=per[0], expected=whole)


def vlm_names(file, a):
    got, out = _parsed_or_person(file, a)
    if out:
        return out
    ans, ev = got
    names = [_words(n) for n in a.get('names') or []]
    lists = [[v for v in x['parsed']['values'] if v.strip()] for x in ans]
    empty = [not l and x['parsed']['answer'] == 'no' for l, x in zip(lists, ans)]
    if all(empty):
        if a.get('none_found') == 'pass':
            return 'pass', dict(ev, note='none found')
        return PERSON, dict(ev, reason='none found; a person confirms it is absent')
    named = [any(n and re.search(r'(?<!\w)' + re.escape(n) + r'(?!\w)', _words(v)) for v in l for n in names) for l in lists]
    if all(named) and all(x['parsed']['answer'] == 'yes' for x in ans):
        return 'fail', dict(ev, found=lists[0][:12])
    return PERSON, dict(ev, reason='an item was listed that names no billed act, or the answers do not agree')


OPS = {'vlm_frames_r5vc': vlm_frames, 'vlm_pages_r5vc': vlm_pages, 'vlm_join_r5vc': vlm_join, 'vlm_part_r5vc': vlm_part, 'vlm_names_r5vc': vlm_names}
