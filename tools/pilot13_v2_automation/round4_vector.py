"""Round 4 conversions for VECTOR-04 (Meridian & Ash stickers), 2026-10-28: cut-path geometry, cut lines drawn into
proofs and the sheet, live SVG type and the wordmark's arch, the window mark's part colours and layout, and corrected
round-3 checks (R100, R101, R018, R001, R089). R027 (weeding notes) is not converted: the made correct sheet carries
none, so there is no correct file to test a pass on (ops_r4_vector.op_sheet_notes is kept for later).

One handler per (task, rule), taking (row, ctx) and returning an assertion for tools/auto_verifier/ops_r4_vector.py
(or None where the row cannot be checked exactly: the proof rows of the type rules, whose fonts a raster does not
carry and whose SVG's embedded fonts the renderer does not load). Settings named in each op's docstring.
"""
from __future__ import annotations

from round3_layout import ASHG, CREAM, ROAST, by_format, const, v04_path, v04_proof_master

OFFSET = {'offset_mm': 2.5, 'tol': 0.15, 'fail_mm': 0.5, 'min_share': 0.9}
CORNER = {'radius_mm': 3.0, 'tol': 0.15, 'fail_mm': 2.2, 'max_turn_deg': 25, 'sigma_mm': 0.5, 'turn_window_mm': 0.3,
          'turn_sigma_mm': 0.1}


def with_file(op, key='1', **kw):
    def h(row, ctx):
        p = v04_path(ctx, (row.get('values') or {}).get(key))
        return dict({'op': op, 'deliverable': p}, **kw) if p else None
    return h


def with_master(op, **kw):
    def h(row, ctx):
        p = v04_proof_master(ctx, row)
        return dict({'op': op, 'deliverable': p}, **kw) if p else None
    return h


def svg_type(what):
    return by_format(svg=lambda row, ctx: {'op': 'svg_type_r4v', 'what': what, 'title_pt': 9.0, 'min_drop': 0.05})


R4 = {
    ('VECTOR-04', 'R007'): with_file('cut_offset_r4v', **OFFSET),
    ('VECTOR-04', 'R014'): const(dict({'op': 'cut_offset_r4v'}, **OFFSET)),
    ('VECTOR-04', 'R008'): const(dict({'op': 'cut_corners_r4v'}, **CORNER)),
    ('VECTOR-04', 'R015'): const(dict({'op': 'cut_corners_r4v'}, **CORNER)),
    ('VECTOR-04', 'R022'): with_master('proof_no_cutline_r4v', thin_px=12, cover=0.85),
    ('VECTOR-04', 'R026'): const({'op': 'sheet_no_cutline_r4v', 'cover': 0.85}),
    ('VECTOR-04', 'R100'): const({'op': 'svg_solid_ink_r4v', 'max_shift_mm': 5}),
    ('VECTOR-04', 'R101'): with_master('proof_flat_r4v'),
    ('VECTOR-04', 'R018'): with_master('proof_open_r4v', thin_px=12, max_share=0.02),
    ('VECTOR-04', 'R001'): with_file('proof_same_r4v', min_iou=0.97, fail_iou=0.9, max_aspect=0.02, min_px=150, far=30,
                                     max_changed_share=0.001, max_opacity_share=0.01),
    ('VECTOR-04', 'R003'): lambda row, ctx: ({'op': 'svg_other_drawing_r4v', 'deliverable': v04_path(ctx, 'new-sticker-companion-1.svg'),
                                              'max_iou': 0.8, 'min_differ': 0.2} if v04_path(ctx, 'new-sticker-companion-1.svg') else None),
    ('VECTOR-04', 'R083'): svg_type('wordmark_font'),
    ('VECTOR-04', 'R091'): svg_type('title_font'),
    ('VECTOR-04', 'R092'): svg_type('copy_font'),
    ('VECTOR-04', 'R098'): svg_type('wordmark_caps'),
    ('VECTOR-04', 'R106'): svg_type('title_caps'),
    ('VECTOR-04', 'R086'): svg_type('amp_hangs'),
    ('VECTOR-04', 'R089'): const({'op': 'svg_arch_angle_r4v', 'deg': 40, 'tol_deg': 2, 'fail_deg': 5}),
    # window mark parts (proofs read through their SVG)
    ('VECTOR-04', 'R067'): const({'op': 'window_part_r4v', 'part': 'wordmark', 'hex': ROAST, 'tol': 5, 'pass_share': 0.95, 'far': 30}),
    ('VECTOR-04', 'R072'): const({'op': 'window_part_r4v', 'part': 'roundel', 'hex': ASHG, 'tol': 5, 'pass_share': 0.95, 'far': 30}),
    ('VECTOR-04', 'R073'): const({'op': 'window_part_r4v', 'part': 'leaf', 'hex': CREAM, 'tol': 5, 'pass_share': 0.95, 'far': 30}),
    ('VECTOR-04', 'R077'): const({'op': 'window_part_r4v', 'part': 'ring', 'hex': CREAM, 'tol': 5, 'pass_share': 0.95, 'far': 30}),
    ('VECTOR-04', 'R066'): with_master('window_part_r4v', part='wordmark', hex=ROAST, tol=5, pass_share=0.95, far=30),
    ('VECTOR-04', 'R075'): with_master('window_part_r4v', part='roundel', hex=ASHG, tol=5, pass_share=0.95, far=30),
    ('VECTOR-04', 'R076'): with_master('window_part_r4v', part='leaf', hex=CREAM, tol=5, pass_share=0.95, far=30),
    ('VECTOR-04', 'R078'): with_master('window_part_r4v', part='ring', hex=CREAM, tol=5, pass_share=0.95, far=30),
    ('VECTOR-04', 'R123'): by_format(svg=lambda row, ctx: {'op': 'window_arch_r4v', 'min_rise': 0.02},
                                     png=lambda row, ctx: ({'op': 'window_arch_r4v', 'min_rise': 0.02, 'deliverable': v04_proof_master(ctx, row)}
                                                           if v04_proof_master(ctx, row) else None)),
}

HOW = {
    'cut_offset_r4v': 'The cut path is read point by point and its distance to the artwork edge measured in millimetres; it must sit at the offset all the way round, never closer.',
    'cut_corners_r4v': 'The cut path is read from its geometry and the tightest bend along it measured as a radius in millimetres.',
    'svg_solid_ink_r4v': 'The SVG is read for opacity under 100%, gradients, filters, masks, blend modes, embedded pictures and shapes repeated at a small offset behind themselves (a hard shadow).',
    'proof_same_r4v': 'The SVG is rendered at the proof size and compared region by region: the same outline and, in every flat area, the same colour.',
    'proof_open_r4v': 'Where the SVG has no ink, the proof must be transparent; filled areas are counted, thin lines are left to the cut line check.',
    'proof_flat_r4v': 'The proof is searched for soft or see-through ink, and its SVG for hard shadows the proof shows.',
    'proof_no_cutline_r4v': 'The proof is searched for a thin line running round the artwork or thin ink in the cut-line magenta, and compared with its SVG.',
    'sheet_no_cutline_r4v': 'The sheet\'s drawings inside each cut path are read for an unfilled stroke running round the sticker or a cut colour off the cut layer.',
    'svg_type_r4v': 'The SVG\'s live type is read: font family, weight, style, capitals and the ampersand\'s drop from the baseline.',
    'svg_other_drawing_r4v': 'Both SVGs are rendered to the same size and compared: outline overlap and colour.',
    'window_part_r4v': 'The window mark\'s parts are found by their shape (the roundel an ellipse, the ring a thin ellipse round it, the leaf inside the roundel, the lettering outside the ring) and each part\'s fill read from the SVG, or from the proof where the part shows.',
    'svg_arch_angle_r4v': 'The arc the wordmark runs on is read from the SVG and the letters\' widths from its embedded font; the angle the inked letters span is measured in degrees.',
    'window_arch_r4v': 'The lettering and the roundel are found by their shape and their positions compared: the lettering above the roundel, its letters rising to the middle.',
}
