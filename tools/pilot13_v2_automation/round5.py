"""Round 5 conversions (2026-10-29). round5_code.py: close calls (rules whose code already decided some rows with
no wrong answer) that code now settles with full confidence. round5_vlm_a.py, round5_vlm_b.py, round5_vlm_c.py:
objective look, count and read checks answered by a vision model through ops_r5_vlm.py. Each module has
R5 = {(task, rule): handler(row, ctx) -> assertion or None} and HOW = {op: text}. A round-5 handler replaces any
earlier conversion of the same rule; convert.py lists every replacement.
"""
from __future__ import annotations

import importlib

HOW: dict = {}
R5: dict = {}
for _name in ('round5_code', 'round5_vlm_a', 'round5_vlm_b', 'round5_vlm_c'):
    try:
        _m = importlib.import_module(_name)
    except ModuleNotFoundError as _e:
        if _e.name != _name:
            raise
        continue
    if set(R5) & set(_m.R5):   # a rule converted twice: one handler would silently replace the other
        raise ValueError(f'{_name} converts rules another module already converts: {sorted(set(R5) & set(_m.R5))[:10]}')
    R5.update(_m.R5)
    HOW.update(getattr(_m, 'HOW', {}))


def convert(tid, rid, row, ctx):
    h = R5.get((tid, rid))
    return h(row, ctx) if h else None
