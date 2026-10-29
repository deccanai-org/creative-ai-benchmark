"""Round 5 (2026-10-29), vision-model helper a: three line checks built on the shared transcription of ops_r5_vlm.

Each op asks, unless the assertion gives a narrower question, the same fixed question as vlm_text_r5v (every text on
the file copied once, one entry per line), so one saved answer serves every rule on the file, and keeps the same
safety rule: a check passes or fails only when every
answer (two seeds) agrees; any disagreement, cannot_tell or unreadable reply goes to a person.

  vlm_joined_r5va   the lines joined into one text (a sentence may be set over two lines); `require` phrases must
                    appear in it.
  vlm_lines_ok_r5va every line must be one of the `allow` patterns (lines already judged to meet the rule); a line
                    matching a `deny` pattern fails; any other line goes to a person.
  vlm_once_r5va     each `values` pattern may match at most one line (lines matching `exempt` are not counted).
"""
from __future__ import annotations

import re

import ops_r5_vlm as V
from objective_ops import PERSON


def _clean(s):
    s = V._norm(s, 'fold', 'fold')
    s = re.sub('[•∙⋅‧・]', '·', s)
    s = re.sub(r'\s*([/·])\s*', r' \1 ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _lines(file, a):
    """[(per-answer list of cleaned lines)] or (None, (status, evidence)) when the answers cannot be used. The question
    is the shared transcription unless the assertion gives a narrower one that also asks for lines of text."""
    a = dict(a, question=a.get('question') or V.TRANSCRIBE)
    ans, err = V.answers(file, a)
    if err:
        return None, (PERSON, {'reason': err})
    ev = {'answers': [{'model': x['model'], 'seed': x['seed'], 'lines': (x['parsed'] or {}).get('values', [])[:60]} for x in ans]}
    if not V._all_parsed(ans):
        return None, (PERSON, dict(ev, reason='an answer is missing or unreadable'))
    if any(x['parsed']['answer'] == 'cannot_tell' for x in ans):
        return None, (PERSON, dict(ev, reason='the model cannot tell'))
    return ([[_clean(v) for v in x['parsed']['values'] if v.strip()] for x in ans], ev), None


def vlm_joined(file, a):
    got, bad = _lines(file, a)
    if bad:
        return bad
    per, ev = got
    joined = [' '.join(p) for p in per]
    verdicts = []
    for s in a['require']:
        s2 = _clean(s)
        hits = [s2 in j for j in joined]
        if all(hits):
            verdicts.append('pass')
        elif any(hits):
            verdicts.append(PERSON)
            ev.setdefault('answers_disagree_on', []).append(s)
        else:
            verdicts.append('fail')
            ev.setdefault('required_missing', []).append(s)
    if PERSON in verdicts:
        return PERSON, dict(ev, reason='the answers do not agree')
    return ('fail' if 'fail' in verdicts else 'pass'), ev


def vlm_lines_ok(file, a):
    got, bad = _lines(file, a)
    if bad:
        return bad
    per, ev = got
    allow = [re.compile(p) for p in a['allow']]
    deny = [re.compile(p) for p in a.get('deny') or []]
    denied = [sorted({l for l in p if any(d.search(l) for d in deny)}) for p in per]
    unknown = [sorted({l for l in p if not any(x.fullmatch(l) for x in allow)}) for p in per]
    if all(denied):
        return 'fail', dict(ev, denied=denied[0][:12])
    if any(denied):
        return PERSON, dict(ev, reason='the answers do not agree', denied=[d[:6] for d in denied])
    if any(unknown):
        return PERSON, dict(ev, reason='a line is not one already judged to meet the rule; a person reads it',
                            unknown=sorted({l for u in unknown for l in u})[:12])
    return 'pass', ev


def vlm_once(file, a):
    got, bad = _lines(file, a)
    if bad:
        return bad
    per, ev = got
    ex = re.compile(a['exempt']) if a.get('exempt') else None
    counts = []
    for p in per:
        lines = [l for l in p if not (ex and ex.search(l))]
        counts.append({v: sum(1 for l in lines if re.search(v, l)) for v in a['values']})
    twice = [sorted(v for v, n in c.items() if n >= 2) for c in counts]
    ev['counts'] = counts[0]
    if all(t == twice[0] for t in twice):
        if twice[0]:
            return 'fail', dict(ev, stated_twice=twice[0])
        return 'pass', ev
    return PERSON, dict(ev, reason='the answers do not agree')


OPS = {'vlm_joined_r5va': vlm_joined, 'vlm_lines_ok_r5va': vlm_lines_ok, 'vlm_once_r5va': vlm_once}
