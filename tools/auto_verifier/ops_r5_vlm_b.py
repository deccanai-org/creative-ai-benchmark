"""Round 5 vision-model ops, helper b (2026-10-29): two thin ops built on ops_r5_vlm.answers(), with the same safety
rules (a check passes or fails only when every answer agrees; cannot_tell, a disagreement or an unreadable reply goes
to a person; nothing found passes only where planted copies proved the model finds such a thing when it is there).

  vlm_text_rx_r5vb  every text on the file copied once with the shared transcription question of ops_r5_vlm (one
                    saved answer per file or PDF page serves every rule on it); the copied lines of each answer are
                    joined (pages in order) and code checks them with regular expressions:
                      forbid_rx  [regex]: a match fails the rule; no match passes only with none_found 'pass'
                      require_rx [regex]: every one must match, else the rule fails
                      values_rx  {'rx': regex whose first non-empty group is the value, 'allowed': [strings]}: every
                                 value found must be allowed (case-folded, spaces and dashes normalised; a value
                                 differing only in spacing goes to a person); none found passes only with
                                 none_found 'pass'
                      distinct_rx {'rx': regex, 'count': n}: the number of different matches (case-folded) must be n
                      by_name    {name: [regex]}: exactly one of the names must be read (else a person looks); its
                                 regexes are then forbidden as with forbid_rx
                      person_rx  [regex]: wording these patterns do not settle (looked for once the forbidden and
                                 value matches are taken out); any match goes to a person
                    `pages` lists the PDF pages to copy (default: the whole image, or page 1 of a PDF).
  vlm_items_r5vb    one list question; code sorts every listed item: `ok` (allowed strings, case-folded) or `ok_rx`
                    (allowed patterns) are allowed; `bad_rx` (patterns) are breaches; an item that is neither goes to
                    a person (when `bad_rx` is not given, every item not allowed is a breach). `near`: an item word
                    this similar to a word of an allowed string, but not equal to one, is a possible misreading and
                    goes to a person (`near_item`: compare whole items instead, for sentences). Every answer
                    listing a breach fails the rule. `need_rx` (patterns): the
                    items are the parts of one thing; every pattern must match a listed part, else that answer
                    finds a part missing (a breach).
                    Every answer listing nothing (answer no) passes only with none_found 'pass'.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import ops_r5_vlm as V
from objective_ops import PERSON


def _fold(s):
    return V._norm(s, 'fold', 'fold')


def _ev(ans, n=40):
    return [{'model': x['model'], 'seed': x['seed'], **({'answer': x['parsed']['answer'], 'values': x['parsed']['values'][:n],
             'evidence': x['parsed']['evidence'][:160]} if x['parsed'] else {'unreadable': True, 'error': x.get('error'),
                                                                              'missing': x.get('missing')})} for x in ans]


def _transcripts(file, a):
    """{(model, seed): joined text} over the listed pages, or (None, evidence) when a person must look."""
    pages = a.get('pages') or [None]
    texts, ev = {}, []
    for p in pages:
        spec = {'src': 'deliverable'}
        if p is not None:
            spec['page'] = p
        for k in ('dpi', 'max_side'):
            if a.get(k):
                spec[k] = a[k]
        q = {'question': V.TRANSCRIBE, 'images': [spec], '_asset_dirs': a.get('_asset_dirs'), '_artifacts': a.get('_artifacts')}
        ans, err = V.answers(file, q)
        if err:
            return None, {'reason': err}
        ev.append({'page': p, 'answers': _ev(ans)})
        for x in ans:
            if x['parsed'] is None:
                return None, {'answers': ev, 'reason': 'an answer is missing or unreadable'}
            if x['parsed']['answer'] == 'cannot_tell':
                return None, {'answers': ev, 'reason': 'the model cannot tell'}
            texts.setdefault((x['model'], x['seed']), []).extend(v for v in x['parsed']['values'] if v.strip())
    return {k: '\n'.join(_fold(l) for l in v) for k, v in texts.items()}, {'answers': ev}


def _joined(t):
    return re.sub(r'\s+', ' ', t)


def vlm_text_rx(file, a):
    texts, ev = _transcripts(file, a)
    if texts is None:
        return PERSON, ev
    keys = sorted(texts)
    flat = {k: _joined(texts[k]) for k in keys}
    verdicts, notes = [], {}
    forbid = list(a.get('forbid_rx') or [])
    if a.get('by_name'):   # the rule depends on which one of several names the file shows
        named = [sorted(n for n in a['by_name'] if re.search(rf'\b{re.escape(n)}\b', flat[k], re.I)) for k in keys]
        notes['named'] = named[0]
        if any(x != named[0] for x in named) or len(named[0]) != 1:
            return PERSON, dict(ev, named=named[0], reason='not exactly one of the names is read, or the answers differ')
        forbid += a['by_name'][named[0][0]]
    for rx in forbid:
        r = re.compile(rx, re.I)
        hits = [r.search(flat[k]) for k in keys]
        if all(hits):
            verdicts.append('fail')
            notes.setdefault('forbidden_found', []).append(hits[0].group(0))
        elif any(hits):
            verdicts.append(PERSON)
            notes.setdefault('answers_disagree_on', []).append(rx)
        elif a.get('none_found') == 'pass':
            verdicts.append('pass')
        else:
            verdicts.append(PERSON)
            notes.setdefault('absent_needs_person', []).append(rx)
    for rx in a.get('require_rx') or []:
        r = re.compile(rx, re.I)
        hits = [r.search(flat[k]) for k in keys]
        if all(hits):
            verdicts.append('pass')
        elif any(hits):
            verdicts.append(PERSON)
            notes.setdefault('answers_disagree_on', []).append(rx)
        else:
            verdicts.append('fail')
            notes.setdefault('required_missing', []).append(rx)
    if a.get('values_rx'):
        vr = a['values_rx']
        r = re.compile(vr['rx'], re.I)
        allowed = {_fold(s) for s in vr['allowed']}
        found = []
        for k in keys:
            vals = set()
            for m in r.finditer(flat[k]):
                g = next((x for x in m.groups() if x), m.group(0)) if m.groups() else m.group(0)
                vals.add(re.sub(r'\s+', ' ', g).strip())
            found.append(sorted(vals))
        notes['values'] = found[0][:20]
        if any(f != found[0] for f in found):
            verdicts.append(PERSON)
            notes['reason'] = 'the answers read different values'
        elif not found[0]:
            verdicts.append('pass' if a.get('none_found') == 'pass' else PERSON)
        elif all(v in allowed for v in found[0]):
            verdicts.append('pass')
        elif all(v in allowed or re.sub(r'\s+', '', v) in {re.sub(r'\s+', '', x) for x in allowed} for v in found[0]):
            verdicts.append(PERSON)   # only the spacing differs: a possible misreading
            notes['reason'] = 'a value differs from the allowed one only in spacing'
        else:
            verdicts.append('fail')
            notes['not_allowed'] = [v for v in found[0] if v not in allowed]
    if a.get('person_rx'):   # similar wording the patterns above do not settle: a person reads it
        rest = dict(flat)
        for rx in forbid + ([a['values_rx']['rx']] if a.get('values_rx') else []):
            rest = {k: re.sub(rx, ' ', v, flags=re.I) for k, v in rest.items()}
        hit = sorted({m.group(0) for rx in a['person_rx'] for k in keys for m in re.finditer(rx, rest[k], re.I)})
        if hit:
            verdicts.append(PERSON)
            notes['for_a_person'] = hit[:10]
    if a.get('distinct_rx'):
        dr = a['distinct_rx']
        r = re.compile(dr['rx'], re.I)
        sets = [sorted({m.group(0) for m in r.finditer(flat[k])}) for k in keys]
        notes['distinct'] = sets[0]
        if any(s != sets[0] for s in sets):
            verdicts.append(PERSON)
            notes['reason'] = 'the answers read different names'
        else:
            verdicts.append('pass' if len(sets[0]) == dr['count'] else 'fail')
    ev.update(notes)
    if not verdicts:
        return PERSON, dict(ev, reason='nothing to check')
    if PERSON in verdicts:
        return PERSON, dict(ev, reason=ev.get('reason') or 'part of the check needs a person')
    return ('fail' if 'fail' in verdicts else 'pass'), ev


def _near(items, ok, near):
    """An item word that is not an allowed word but is this similar to one (a misread letter), word by word, so a
    shared surname does not make two different names look alike."""
    words = {w for o in ok for w in re.findall(r'[\w@.$%-]+', o)}
    for v in items:
        for w in re.findall(r'[\w@.$%-]+', v):
            if w not in words and any(SequenceMatcher(None, w, o).ratio() >= near for o in words):
                return True
    return False


def _near_item(items, ok, near):
    """An item this similar to a whole allowed string, but not equal to it (a sentence with a misread letter)."""
    return any(SequenceMatcher(None, v, o).ratio() >= near for v in items for o in ok)


def vlm_items(file, a):
    ans, err = V.answers(file, a)
    if err:
        return PERSON, {'reason': err}
    ev = {'answers': _ev(ans)}
    if not ans or any(x['parsed'] is None for x in ans):
        return PERSON, dict(ev, reason='an answer is missing or unreadable')
    ok = {_fold(s) for s in a.get('ok') or []}
    ok_rx = [re.compile(r, re.I) for r in a.get('ok_rx') or []]
    bad_rx = [re.compile(r, re.I) for r in a['bad_rx']] if a.get('bad_rx') is not None else None
    near = a.get('near')
    need = [re.compile(r, re.I) for r in a.get('need_rx') or []]
    per = []
    for x in ans:
        p = x['parsed']
        if p['answer'] == 'cannot_tell':
            return PERSON, dict(ev, reason='the model cannot tell')
        vals = sorted({_fold(v) for v in p['values'] if v.strip()})
        if not vals:
            if p['answer'] != 'no':
                return PERSON, dict(ev, reason='the answer says yes but lists nothing')
            per.append(('none', ()))
            continue
        if need:   # the listed parts of one thing: every required part must be among them
            missing = tuple(r.pattern for r in need if not any(r.search(v) for v in vals))
            per.append(('bad', missing) if missing else ('ok', tuple(vals)))
            continue
        good = [v for v in vals if v in ok or any(r.search(v) for r in ok_rx)]
        rest = [v for v in vals if v not in good]
        if near and (_near_item(rest, ok, near) if a.get('near_item') else _near(rest, ok, near)):
            return PERSON, dict(ev, reason='an item is close to an allowed one: a possible misreading', items=rest)
        bad = [v for v in rest if bad_rx is None or any(r.search(v) for r in bad_rx)]
        if bad:
            per.append(('bad', tuple(bad)))
        elif rest:
            per.append(('unsure', tuple(rest)))
        else:
            per.append(('ok', tuple(vals)))
    kinds = {k for k, _ in per}
    if kinds == {'none'}:
        if a.get('none_found') == 'pass':
            return 'pass', dict(ev, note='none found')
        return PERSON, dict(ev, reason='none found; a person confirms it is absent')
    if kinds == {'ok'}:
        return 'pass', dict(ev, items=list(per[0][1]))
    if kinds == {'bad'}:   # every answer lists a breach (in its own words): the rule is broken
        return 'fail', dict(ev, breach=list(per[0][1]))
    return PERSON, dict(ev, reason='the answers do not agree or an item needs a person', items=[list(v) for _, v in per])


OPS = {'vlm_text_rx_r5vb': vlm_text_rx, 'vlm_items_r5vb': vlm_items}
