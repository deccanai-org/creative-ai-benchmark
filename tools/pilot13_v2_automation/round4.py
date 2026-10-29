"""Round 4 conversions (2026-10-28): the remaining human checks code can measure exactly. One module per family:
round4_vector.py (VECTOR-04 sticker, cut-file and proof geometry), round4_type.py (type measurements and size
relations), round4_photo.py (photographs against their supplied files, marks, grain), round4_video.py (MOTION-11 video,
audio and stacked titles), each with R4 = {(task, rule): handler(row, ctx) -> assertion or None} and HOW = {op: text}.
A round-4 handler replaces the round-2 or round-3 conversion of the same rule; convert.py lists every replacement.
"""
from __future__ import annotations

import importlib

HOW: dict = {}
R4: dict = {}
for _name in ('round4_vector', 'round4_type', 'round4_photo', 'round4_video'):
    try:
        _m = importlib.import_module(_name)
    except ModuleNotFoundError as _e:
        if _e.name != _name:
            raise
        continue
    if set(R4) & set(_m.R4):   # a rule converted twice: one handler would silently replace the other
        raise ValueError(f'{_name} converts rules another module already converts: {sorted(set(R4) & set(_m.R4))[:10]}')
    R4.update(_m.R4)
    HOW.update(getattr(_m, 'HOW', {}))


def convert(tid, rid, row, ctx):
    h = R4.get((tid, rid))
    return h(row, ctx) if h else None
