"""Round 5 (2026-10-29): the close calls code can now settle with full confidence (ops_r5_code.py), and the objective
look, count and read checks a vision model answers (ops_r5_vlm.py: asked twice, both answers must agree, replayed
from a saved answer file). Operations live in one module per family, each with OPS; an op name may be defined once
only, across every round.
"""
import sys

OPS_R5: dict = {}
_owner = {}
if 'objective_ops' in sys.modules:   # rounds 1 to 4, registered before this module is loaded
    _owner.update(dict.fromkeys(sys.modules['objective_ops'].OPS, 'objective_ops (rounds 1-4)'))
for _name in ('ops_r5_code', 'ops_r5_vlm', 'ops_r5_vlm_a', 'ops_r5_vlm_b', 'ops_r5_vlm_c'):
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
    OPS_R5.update(_ops)
