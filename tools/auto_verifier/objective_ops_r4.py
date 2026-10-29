"""Round 4 (2026-10-28): the remaining human checks that code can measure exactly: sticker and cut-file geometry,
type measurements (figures, signs, cap heights, letter spacing, size relations), photographs against their supplied
files, and video and audio. Operations live in one module per family (ops_r4_vector.py, ops_r4_type.py,
ops_r4_photo.py, ops_r4_video.py), each with OPS; an op name may be defined once only, across every round.
"""
import sys

OPS_R4: dict = {}
_owner = {}
if 'objective_ops' in sys.modules:   # rounds 1 to 3, registered before this module is loaded
    _owner.update(dict.fromkeys(sys.modules['objective_ops'].OPS, 'objective_ops (rounds 1-3)'))
for _name in ('ops_r4_vector', 'ops_r4_type', 'ops_r4_photo', 'ops_r4_video'):
    try:
        _ops = __import__(_name).OPS
    except ModuleNotFoundError as _e:
        if _e.name != _name:
            raise
        continue
    for _op in _ops:
        if _op in _owner:
            raise ValueError(f'{_name} defines {_op}, already defined in {_owner[_op]}; op names must be unique')
        _owner[_op] = _name
    OPS_R4.update(_ops)
