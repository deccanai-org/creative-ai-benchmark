"""Offline tests of the round-5 vision-model decision rules (no API call: answers are given directly).
Run: python test_ops_r5_vlm.py (self-running, like test_objective_ops.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import objective_ops  # noqa: F401,E402  (loads every round)
import ops_r5_vlm as V  # noqa: E402


def fake(*parsed):
    """Make answers() return these parsed replies (one per model and seed)."""
    V.answers = lambda file, a: ([{'model': 'm', 'seed': i, 'parsed': p, 'missing': False, 'error': None}
                                  for i, p in enumerate(parsed)], None)


def reply(answer='yes', values=(), count=-1):
    return {'answer': answer, 'values': list(values), 'count': count, 'evidence': ''}


def test_read_agree_pass_and_fail():
    fake(reply(values=['Loopback Crew']), reply(values=['Loopback  Crew']))
    assert V.vlm_read('x.png', {'question': 'q', 'expected': 'Loopback Crew'})[0] == 'pass'
    fake(reply(values=['Loopbak Crew']), reply(values=['Loopbak Crew']))
    assert V.vlm_read('x.png', {'question': 'q', 'expected': 'Loopback Crew'})[0] == 'fail'


def test_read_disagreement_and_cannot_tell_go_to_a_person():
    fake(reply(values=['Loopback Crew']), reply(values=['Loopbak Crew']))
    assert V.vlm_read('x.png', {'question': 'q', 'expected': 'Loopback Crew'})[0] == 'person'
    fake(reply(values=['Loopback Crew']), reply(answer='cannot_tell'))
    assert V.vlm_read('x.png', {'question': 'q', 'expected': 'Loopback Crew'})[0] == 'person'


def test_read_dashes_fold_unless_exact():
    fake(reply(values=['12-13 MARCH 2026']), reply(values=['12–13 MARCH 2026']))
    assert V.vlm_read('x.png', {'question': 'q', 'expected': '12–13 MARCH 2026'})[0] == 'pass'
    fake(reply(values=['12-13 MARCH 2026']), reply(values=['12-13 MARCH 2026']))
    assert V.vlm_read('x.png', {'question': 'q', 'expected': '12–13 MARCH 2026', 'dashes': 'exact'})[0] == 'fail'


def test_nothing_found_is_a_person_unless_proven():
    fake(reply(answer='no'), reply(answer='no'))
    assert V.vlm_list('x.png', {'question': 'q'})[0] == 'person'
    assert V.vlm_list('x.png', {'question': 'q', 'none_found': 'pass'})[0] == 'pass'
    fake(reply(values=['(207) 555-0148']), reply(values=['(207) 555-0148']))
    assert V.vlm_list('x.png', {'question': 'q', 'none_found': 'pass'})[0] == 'fail'
    fake(reply(answer='no'), reply(values=['(207) 555-0148']))
    assert V.vlm_list('x.png', {'question': 'q', 'none_found': 'pass'})[0] == 'person'


def test_count_and_yesno():
    fake(reply(count=1), reply(count=1))
    assert V.vlm_count('x.png', {'question': 'q', 'expected': 1})[0] == 'pass'
    fake(reply(count=2), reply(count=2))
    assert V.vlm_count('x.png', {'question': 'q', 'expected': 1})[0] == 'fail'
    fake(reply(count=1), reply(count=2))
    assert V.vlm_count('x.png', {'question': 'q', 'expected': 1})[0] == 'person'
    fake(reply(answer='no'), reply(answer='no'))
    assert V.vlm_yesno('x.png', {'question': 'q', 'pass_on': 'no'})[0] == 'pass'
    fake(reply(answer='yes'), reply(answer='no'))
    assert V.vlm_yesno('x.png', {'question': 'q', 'pass_on': 'no'})[0] == 'person'


def test_unreadable_reply_goes_to_a_person():
    fake(reply(values=['A']), None)
    assert V.vlm_read('x.png', {'question': 'q', 'expected': 'A'})[0] == 'person'
    assert V._parse('not json') is None
    assert V._parse('{"answer": "maybe", "values": [], "count": 0, "evidence": ""}') is None


def test_the_expected_answer_is_never_in_a_published_question():
    """Blind reading: no round-5 read or count question contains the text or number the rule expects."""
    import json
    import round5  # noqa: E402
    import convert  # noqa: E402
    root = Path(__file__).resolve().parents[2]
    seen = 0
    for (tid, rid), h in round5.R5.items():
        spec = json.loads((root / 'docs/gatsby-v7/tasks' / tid / 'TASK_SPEC.json').read_text())
        groups = json.loads((root / 'docs/gatsby-v7/annotation-pilot-v2/groups' / f'{tid}.json').read_text())
        ctx = convert.Ctx(tid, spec, groups)
        for row in ctx.rules[rid]['rows']:
            a = h(row, ctx)
            if a and a.get('op') in ('vlm_read_r5v', 'vlm_count_r5v') and a.get('question'):
                exp = a['expected'] if isinstance(a['expected'], list) else [a['expected']]
                for e in exp:
                    if isinstance(e, str) and len(e) > 3:
                        assert e.casefold() not in a['question'].casefold(), (tid, rid, e)
                seen += 1
    assert seen > 0


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pilot13_v2_automation'))
    real_answers = V.answers
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    failed = 0
    for t in tests:
        V.answers = real_answers
        try:
            t()
            print('ok  ', t.__name__)
        except AssertionError as e:
            failed += 1
            print('FAIL', t.__name__, e)
    print(f'{len(tests) - failed}/{len(tests)} passed')
    sys.exit(1 if failed else 0)
