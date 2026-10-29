"""Round 5 (2026-10-29): objective look, count and read checks answered by a vision model.

How a check is answered:
- The deliverable (and any supplied file the rule compares it with) is prepared the same way every time: a PDF page
  rendered at a fixed resolution, an SVG rendered by CairoSVG, a video frame taken at an exact time, an optional crop,
  then scaled so its longest side is at most `max_side` pixels, sent as PNG.
- The model gets one narrow question and replies in a fixed JSON form: answer (yes, no or cannot_tell), values (text
  copied exactly as printed, or the items found), count and evidence. Questions never contain the expected text or
  number, so a model cannot copy it back: it reads blind and code compares what it read with what the rule expects.
- Every question is asked twice at temperature 0 with two fixed seeds, of each model in `MODELS`. A check passes or
  fails only when every answer agrees; any disagreement, cannot_tell, unreadable reply or missing answer goes to a
  person. Answers are saved (key: model, settings, question and the SHA-256 of each source file with how it was
  prepared), so a later run replays exactly the same answers without asking again.

Ops (every setting is in the assertion):
  vlm_yesno_r5v  question with a yes or no answer; pass_on 'yes' or 'no' says which answer meets the rule.
  vlm_read_r5v   copy every matching text; `expected` (string or list of allowed strings) is compared by code after
                 whitespace and quote normalising (`case` 'exact' or 'fold'; `dashes` 'fold' treats a hyphen and an
                 en or em dash as one, 'exact' keeps them apart); `mode` 'all' (every text read must be
                 allowed) or 'any' (at least one); nothing found goes to a person unless `none_found` says 'pass'
                 (only for rules proven on planted copies that the model finds such text when it is there).
  vlm_count_r5v  count things; `expected` an integer or [low, high].
  vlm_list_r5v   list every item of a kind (a phone number, a second person, a cut letter); pass when every answer
                 lists none (only for rules proven on planted copies), fail when every answer lists the same items.
  vlm_text_r5v   every text on the file copied once (one saved answer serves every rule on the file), then code
                 checks the lines: `select` + `expected`, `forbid`, `require` (see the function).
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

PERSON = 'person'   # as objective_ops.PERSON; not imported, so this module can load before objective_ops

# models asked; a check is decided only when every model agrees (set after the 2026-10-29 bake-off)
MODELS = [m for m in os.environ.get('VLM_MODELS', 'google/gemini-3.8-flash').split(',') if m]
SEEDS = (11, 23)
PARAMS = {'temperature': 0, 'max_tokens': 1500}
API = 'https://openrouter.ai/api/v1/chat/completions'
HERE = Path(__file__).resolve().parent
# saved answers: the repo copy (published) first, then the work folder where new answers are written on the VM
ANSWER_DIRS = [HERE.parent / 'pilot13_v2_automation' / 'vlm_answers']
_WORK = HERE.parents[1].parents[1] / 'reviews/pilot13-automation-2026-10-28/vlm5/answers'   # the work folder beside publish/
if os.environ.get('VLM_ANSWERS'):
    _WORK = Path(os.environ['VLM_ANSWERS'])
ANSWER_DIRS.append(_WORK)
OFFLINE = os.environ.get('VLM_OFFLINE') == '1'   # replay only: a missing answer goes to a person

SYSTEM = (
    'You check one finished design file against one precise question. Look only at the image or images given. '
    'Answer the question literally and objectively; do not judge taste, style or quality. '
    'When asked for text, copy it exactly as printed, character for character: keep its spelling, capitals, '
    'punctuation, spacing and any mistakes; never correct, complete, translate or guess text. '
    'If what is asked about is too small, blurred, covered or otherwise not clearly visible, or you are not sure, '
    'answer cannot_tell. Reply with JSON only, in the given form.')
SCHEMA = {
    'type': 'object',
    'properties': {
        'answer': {'type': 'string', 'enum': ['yes', 'no', 'cannot_tell']},
        'values': {'type': 'array', 'items': {'type': 'string'}},
        'count': {'type': 'integer'},
        'evidence': {'type': 'string'},
    },
    'required': ['answer', 'values', 'count', 'evidence'],
    'additionalProperties': False,
}
FORM = ('Reply as JSON: {"answer": "yes" | "no" | "cannot_tell", "values": [strings], "count": integer, '
        '"evidence": "where you looked and what you saw, in a few words"}. ')


def _key():
    k = os.environ.get('OPENROUTER_API_KEY')
    if not k:
        f = Path.home() / '.config/pilot13/openrouter.env'
        if f.is_file():
            for line in f.read_text().splitlines():
                if line.startswith('OPENROUTER_API_KEY='):
                    k = line.split('=', 1)[1].strip()
    return k


def _sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for b in iter(lambda: fh.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


# ------------------------------------------------------------------ image preparation (deterministic)
def _find_asset(name, a):
    for d in a.get('_asset_dirs') or []:
        for p in Path(d).rglob(name):
            if p.is_file():
                return p
    return None


def _render(path: Path, spec: dict):
    """PIL image of the prepared view of `path` per `spec` (page, time, crop, max_side)."""
    from PIL import Image
    suf = path.suffix.lower()
    if suf == '.pdf':
        import fitz
        doc = fitz.open(path)
        page = doc[int(spec.get('page', 1)) - 1]
        zoom = float(spec.get('dpi', 144)) / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    elif suf == '.svg':
        import cairosvg
        png = cairosvg.svg2png(url=str(path), output_width=int(spec.get('svg_width', 1600)))
        img = Image.open(io.BytesIO(png))
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGBA', img.size, spec.get('svg_ground', '#FFFFFF'))
            img = Image.alpha_composite(bg, img.convert('RGBA')).convert('RGB')
    elif suf in ('.mp4', '.mov', '.webm', '.m4v'):
        t = float(spec.get('time', 0))
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / 'f.png'
            subprocess.run(['ffmpeg', '-v', 'error', '-ss', f'{t:.3f}', '-i', str(path), '-frames:v', '1', str(out)],
                           check=True, timeout=120)
            img = Image.open(out).convert('RGB')
    else:
        img = Image.open(path)
        if img.mode in ('RGBA', 'LA', 'P'):
            bg = Image.new('RGBA', img.size, spec.get('ground', '#FFFFFF'))
            img = Image.alpha_composite(bg, img.convert('RGBA')).convert('RGB')
        else:
            img = img.convert('RGB')
    if spec.get('crop'):
        x0, y0, x1, y1 = spec['crop']   # fractions of the width and height
        W, H = img.size
        img = img.crop((round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H)))
    ms = int(spec.get('max_side', 2048))
    if max(img.size) > ms:
        s = ms / max(img.size)
        img = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.LANCZOS)
    return img


def _png(img):
    b = io.BytesIO()
    img.save(b, format='PNG', optimize=False, compress_level=6)
    return b.getvalue()


def _images(file: Path, a: dict):
    """[(source sha256, spec, png bytes)] for the assertion's `images` list (default: the whole deliverable)."""
    out = []
    for spec in a.get('images') or [{'src': 'deliverable'}]:
        src = spec.get('src', 'deliverable')
        if src == 'deliverable':
            p = file
        elif src.startswith('asset:'):
            p = _find_asset(src[6:], a)
        elif src.startswith('artifact:'):
            p = Path(a.get('_artifacts', '')) / src[9:]
        else:
            p = None
        if p is None or not Path(p).is_file():
            return None, f'file not found: {src}'
        clean = {k: v for k, v in spec.items() if k != 'label'}
        out.append((_sha(p), clean, spec.get('label'), _png(_render(Path(p), spec))))
    return out, None


# ------------------------------------------------------------------ asking, with saved answers
_cache: dict | None = None


def _load():
    global _cache
    if _cache is None:
        _cache = {}
        for d in ANSWER_DIRS:
            if d.is_dir():
                for f in sorted(d.glob('*.jsonl')):
                    for line in f.read_text().splitlines():
                        try:
                            r = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        _cache.setdefault(r['key'], r)
    return _cache


def _save(rec):
    _WORK.mkdir(parents=True, exist_ok=True)
    f = _WORK / (re.sub(r'[^A-Za-z0-9.-]+', '_', rec['model']) + '.jsonl')
    with open(f, 'a') as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
        fcntl.flock(fh, fcntl.LOCK_UN)


def _parse(text):
    if not text:
        return None
    t = text.strip()
    m = re.search(r'\{.*\}', t, re.S)
    if not m:
        return None
    try:
        r = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if r.get('answer') not in ('yes', 'no', 'cannot_tell'):
        return None
    vals = r.get('values') or []
    if not isinstance(vals, list):
        return None
    try:
        cnt = int(r.get('count', -1))
    except (TypeError, ValueError):
        cnt = -1
    return {'answer': r['answer'], 'values': [str(v) for v in vals], 'count': cnt, 'evidence': str(r.get('evidence', ''))[:400]}


def ask(model, question, imgs, seed, extra=None):
    """One answer (parsed dict, or None for an unreadable reply), from the saved answers or the API."""
    extra = extra or {}
    params = dict(PARAMS, **extra)
    key = hashlib.sha256(json.dumps({'model': model, 'params': params, 'seed': seed, 'system': SYSTEM,
                                     'route': PROVIDERS.get(model), 'reasoning': REASONING.get(model),
                                     'question': question, 'images': [(s, sp, lb) for s, sp, lb, _ in imgs]},
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    c = _load()
    if os.environ.get('VLM_USED_LOG'):   # the final run lists every answer it uses, so only those are published
        with open(os.environ['VLM_USED_LOG'], 'a') as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(key + '\n')
            fcntl.flock(fh, fcntl.LOCK_UN)
    if key in c:
        return c[key].get('parsed'), c[key]
    if OFFLINE:
        return None, {'missing': True}
    api_key = _key()
    if not api_key:
        return None, {'missing': True, 'reason': 'no API key'}
    content = []
    for s, sp, lb, png in imgs:
        if lb:
            content.append({'type': 'text', 'text': lb})
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(png).decode()}})
    content.append({'type': 'text', 'text': question + '\n\n' + FORM})
    body = {'model': model, 'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': content}],
            'seed': seed, 'usage': {'include': True},
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'check', 'strict': True, 'schema': SCHEMA}}}
    body.update(params)
    if model in PROVIDERS:
        body['provider'] = {'order': PROVIDERS[model], 'allow_fallbacks': False}
    if model in REASONING:
        body['reasoning'] = REASONING[model]
    data = json.dumps(body).encode()
    last = None
    for attempt in range(5):
        req = urllib.request.Request(API, data=data, headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json',
                                                              'X-Title': 'pilot13-verifiers'})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                resp = json.loads(r.read())
            if 'choices' not in resp:
                raise RuntimeError(json.dumps(resp)[:300])
            break
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            last = e
            msg = e.read().decode()[:300] if isinstance(e, urllib.error.HTTPError) else str(e)[:300]
            last = msg
            time.sleep(3 * (attempt + 1))
    else:
        return None, {'error': str(last)}
    msg = resp['choices'][0]['message']
    text = msg.get('content') or ''
    rec = {'key': key, 'model': model, 'seed': seed, 'params': params, 'question': question,
           'images': [(s, sp, lb) for s, sp, lb, _ in imgs], 'provider': resp.get('provider'),
           'served_model': resp.get('model'), 'text': text, 'parsed': _parse(text),
           'usage': resp.get('usage'), 'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    _save(rec)
    c[key] = rec
    return rec['parsed'], rec


# model -> provider, pinned so the same deployment answers every time; model -> reasoning setting. Chosen 2026-10-29:
# Gemini 3.8 Flash on Google Vertex with low reasoning answered 23 of 23 known-answer calibration questions right
# (planted misspellings copied as printed, an added phone number and web address found, cut letters, people and
# shapes counted).
PROVIDERS: dict = {'google/gemini-3.8-flash': ['google-vertex']}
REASONING: dict = {'google/gemini-3.8-flash': {'effort': 'low'}}


def answers(file, a):
    """Every (model, seed) answer for the assertion; (list, None) or (None, reason)."""
    imgs, err = _images(Path(file), a)
    if err:
        return None, err
    out = []
    for m in a.get('models') or MODELS:
        for s in a.get('seeds') or SEEDS:
            p, rec = ask(m, a['question'], imgs, s, a.get('params'))
            out.append({'model': m, 'seed': s, 'parsed': p, 'missing': bool(rec.get('missing')), 'error': rec.get('error')})
    return out, None


def _norm(s, case, dashes='fold'):
    s = unicodedata.normalize('NFKC', s)
    s = s.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    if dashes == 'fold':   # a model does not reliably tell a hyphen from an en or em dash
        s = re.sub('[‐‑‒–—−]', '-', s)
    s = s.replace(' ', ' ').replace(' ', ' ').replace(' ', ' ')
    s = re.sub(r'\s+', ' ', s).strip()
    return s.casefold() if case == 'fold' else s


def _ev(ans):
    return [{'model': x['model'], 'seed': x['seed'], **({'answer': x['parsed']['answer'], 'values': x['parsed']['values'][:12],
             'count': x['parsed']['count'], 'evidence': x['parsed']['evidence'][:160]} if x['parsed'] else
            {'unreadable': True, 'error': x.get('error'), 'missing': x.get('missing')})} for x in ans]


def _all_parsed(ans):
    if not ans or any(x['parsed'] is None for x in ans):
        return False
    return True


def vlm_yesno(file, a):
    ans, err = answers(file, a)
    if err:
        return PERSON, {'reason': err}
    ev = {'answers': _ev(ans)}
    if not _all_parsed(ans):
        return PERSON, dict(ev, reason='an answer is missing or unreadable')
    got = {x['parsed']['answer'] for x in ans}
    if len(got) != 1 or 'cannot_tell' in got:
        return PERSON, dict(ev, reason='the answers do not agree' if len(got) > 1 else 'the model cannot tell')
    yes = got.pop()
    return ('pass' if yes == a.get('pass_on', 'yes') else 'fail'), ev


def vlm_read(file, a):
    ans, err = answers(file, a)
    if err:
        return PERSON, {'reason': err}
    ev = {'answers': _ev(ans)}
    if not _all_parsed(ans):
        return PERSON, dict(ev, reason='an answer is missing or unreadable')
    case = a.get('case', 'exact')
    exp = a['expected'] if isinstance(a['expected'], list) else [a['expected']]
    dashes = a.get('dashes', 'fold')
    allowed = {_norm(e, case, dashes) for e in exp}
    reads = []
    for x in ans:
        if x['parsed']['answer'] == 'cannot_tell':
            return PERSON, dict(ev, reason='the model cannot tell')
        reads.append(sorted({_norm(v, case, dashes) for v in x['parsed']['values'] if v.strip()}))
    if any(r != reads[0] for r in reads):
        return PERSON, dict(ev, reason='the answers read different text')
    r = reads[0]
    if not r:
        if a.get('none_found') == 'pass' and all(x['parsed']['answer'] == 'no' for x in ans):
            return 'pass', dict(ev, note='no such text on the file')
        return PERSON, dict(ev, reason='no such text found; a person confirms it is absent')
    ok = [v in allowed for v in r]
    good = all(ok) if a.get('mode', 'all') == 'all' else any(ok)
    if good:
        return 'pass', dict(ev, read=r)
    return 'fail', dict(ev, read=r, expected=sorted(allowed))


def vlm_count(file, a):
    ans, err = answers(file, a)
    if err:
        return PERSON, {'reason': err}
    ev = {'answers': _ev(ans)}
    if not _all_parsed(ans):
        return PERSON, dict(ev, reason='an answer is missing or unreadable')
    if any(x['parsed']['answer'] == 'cannot_tell' or x['parsed']['count'] < 0 for x in ans):
        return PERSON, dict(ev, reason='the model cannot tell')
    counts = {x['parsed']['count'] for x in ans}
    if len(counts) != 1:
        return PERSON, dict(ev, reason='the counts do not agree')
    n = counts.pop()
    e = a['expected']
    lo, hi = (e, e) if isinstance(e, int) else (e[0], e[1])
    return ('pass' if lo <= n <= hi else 'fail'), dict(ev, counted=n)


def vlm_list(file, a):
    ans, err = answers(file, a)
    if err:
        return PERSON, {'reason': err}
    ev = {'answers': _ev(ans)}
    if not _all_parsed(ans):
        return PERSON, dict(ev, reason='an answer is missing or unreadable')
    if any(x['parsed']['answer'] == 'cannot_tell' for x in ans):
        return PERSON, dict(ev, reason='the model cannot tell')
    lists = [x['parsed']['values'] for x in ans]
    empty = [not [v for v in l if v.strip()] and x['parsed']['answer'] == 'no' for l, x in zip(lists, ans)]
    if all(empty):
        if a.get('none_found', 'person') == 'pass':
            return 'pass', dict(ev, note='none found')
        return PERSON, dict(ev, reason='none found; a person confirms it is absent')
    if any(empty):
        return PERSON, dict(ev, reason='the answers do not agree')
    found = all(x['parsed']['answer'] == 'yes' for x in ans)
    if not found:
        return PERSON, dict(ev, reason='the answers do not agree')
    return 'fail', dict(ev, found=lists[0][:12])


TRANSCRIBE = ('Copy every piece of text visible in the image, exactly as printed, one entry per line of text, in reading '
              'order (top to bottom, then left to right). Include headings, small print, labels, numbers, prices, '
              'lettering in logos and any text on photographs. answer yes if there is any text, no if there is none.')


def _near(a, b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def vlm_text(file, a):
    """Every text on the file copied once (the same question for every rule on the file, so one saved answer serves
    them all), then code checks the lines. Settings: `select` (a regular expression a line must match to be checked;
    default every line), `expected` (allowed strings for the selected lines, `mode` 'all' or 'any'), `forbid` (strings
    no line may contain), `require` (strings some line must contain), `case` and `dashes` as for vlm_read_r5v,
    `near` (a line this similar to an expected or required string, but not equal, is a possible misreading: person;
    default 0.0, off), `none_found` ('pass' only for rules proven on planted copies; default person)."""
    a = dict(a, question=a.get('question') or TRANSCRIBE)
    ans, err = answers(file, a)
    if err:
        return PERSON, {'reason': err}
    ev = {'answers': [{'model': x['model'], 'seed': x['seed'], 'lines': (x['parsed'] or {}).get('values', [])[:60]} for x in ans]}
    if not _all_parsed(ans):
        return PERSON, dict(ev, reason='an answer is missing or unreadable')
    if any(x['parsed']['answer'] == 'cannot_tell' for x in ans):
        return PERSON, dict(ev, reason='the model cannot tell')
    case, dashes = a.get('case', 'exact'), a.get('dashes', 'fold')
    per = [[_norm(v, case, dashes) for v in x['parsed']['values'] if v.strip()] for x in ans]
    fold = [[l.casefold() for l in p] for p in per]
    verdicts, notes = [], {}
    for s in a.get('forbid') or []:
        s2 = _norm(s, 'fold', dashes)
        hits = [any(s2 in l for l in f) for f in fold]
        if all(hits):
            verdicts.append('fail'); notes.setdefault('forbidden_found', []).append(s)
        elif any(hits):
            verdicts.append(PERSON); notes.setdefault('answers_disagree_on', []).append(s)
        else:
            verdicts.append('pass' if a.get('none_found') == 'pass' else PERSON)
            if a.get('none_found') != 'pass':
                notes.setdefault('absent_needs_person', []).append(s)
    for s in a.get('require') or []:
        s2 = _norm(s, case, dashes)
        hits = [any(s2 in l for l in p) for p in per]
        if all(hits):
            verdicts.append('pass')
        elif any(hits):
            verdicts.append(PERSON); notes.setdefault('answers_disagree_on', []).append(s)
        elif a.get('near') and any(_near(s2, l) >= a['near'] for p in per for l in p):
            verdicts.append(PERSON); notes.setdefault('near_miss', []).append(s)
        else:
            verdicts.append('fail'); notes.setdefault('required_missing', []).append(s)
    if a.get('expected') is not None:
        exp = a['expected'] if isinstance(a['expected'], list) else [a['expected']]
        allowed = {_norm(e, case, dashes) for e in exp}
        rx = re.compile(a['select'], re.I) if a.get('select') else None
        sel = [sorted({l for l in p if (rx.search(l) if rx else True)}) for p in per]
        notes['selected'] = sel[0][:12]
        if any(s != sel[0] for s in sel):
            verdicts.append(PERSON); notes['reason'] = 'the answers read different text'
        elif not sel[0]:
            verdicts.append('pass' if a.get('none_found') == 'pass' else PERSON)
        else:
            ok = [l in allowed for l in sel[0]]
            if all(ok) if a.get('mode', 'all') == 'all' else any(ok):
                verdicts.append('pass')
            elif a.get('near') and any(_near(l, e) >= a['near'] for l, k in zip(sel[0], ok) if not k for e in allowed):
                verdicts.append(PERSON); notes['near_miss'] = [l for l, k in zip(sel[0], ok) if not k]
            else:
                verdicts.append('fail'); notes['not_allowed'] = [l for l, k in zip(sel[0], ok) if not k]
    ev.update(notes)
    if not verdicts:
        return PERSON, dict(ev, reason='nothing to check')
    if 'fail' in verdicts and PERSON not in verdicts:
        return 'fail', ev
    if PERSON in verdicts:
        return PERSON, dict(ev, reason=ev.get('reason') or 'part of the check needs a person')
    return 'pass', ev


def prefetch(items, workers=24):
    """Ask every question of [(file, assertion)] in parallel so the checks then replay from the saved answers.
    Identical questions on the same file are asked once."""
    from concurrent.futures import ThreadPoolExecutor
    seen, todo = set(), []
    for f, a in items:
        if a.get('op') not in ('vlm_yesno_r5v', 'vlm_read_r5v', 'vlm_count_r5v', 'vlm_list_r5v', 'vlm_text_r5v'):
            continue   # an op that builds its own questions asks them when it runs
        q = a.get('question') or (TRANSCRIBE if a.get('op') == 'vlm_text_r5v' else None)
        if not q:
            continue
        k = (str(f), q, json.dumps(a.get('images'), sort_keys=True), json.dumps(a.get('models')), json.dumps(a.get('params')))
        if k not in seen:
            seen.add(k)
            todo.append((f, dict(a, question=q)))
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(lambda it: answers(*it), todo))
    return len(todo)


OPS = {'vlm_yesno_r5v': vlm_yesno, 'vlm_read_r5v': vlm_read, 'vlm_count_r5v': vlm_count, 'vlm_list_r5v': vlm_list,
       'vlm_text_r5v': vlm_text}
