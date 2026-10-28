"""Round 3 conversions (2026-10-28): colour on images, rules that needed a definition, and the measurable rules
first sorted as judgement. Handlers live in one module per task family (round3_photo_a.py: PHOTO-04, 06, 08, 10;
round3_photo_b.py: PHOTO-19, 20, 24, 26, 28; round3_layout.py: LAYOUT-15, LAYOUT-12, VECTOR-04, MOTION-11;
round3_fonts.py: typeface, italics and letter spacing read from images, all tasks), each with
R3 = {(task, rule): handler(row, ctx) -> assertion or None} and HOW = {op: plain description}. Keyed by task and
rule, so round-1 and round-2 conversions never change.
"""
from __future__ import annotations

import importlib

HOW = {
    'v2_palette_raster': 'Reads every flat colour outside the photographs and checks each is a palette colour.',
    'v2_colour_present_raster': 'Looks for the colour as a flat area outside the photographs.',
    'v2_area_share_raster': 'Measures the share of the area outside the photographs in the named colours.',
    'v2_ground_raster': 'Finds every ground and panel (flat areas outside the photographs) and reads its colour.',
    'v2_colour_role_raster': 'Finds every piece in the colour outside the photographs and checks its shape (thin rule, small label, panel or type).',
    'v2_text_colour_raster': 'Reads each text line by OCR, then the colour of its letters and of the ground behind it.',
    'v2_mark_colour_raster': 'Finds the mark, then reads the colour of its ink and of the ground round it.',
    'v2_no_overlay': 'Compares the photo with the supplied file (images) or reads the shapes drawn over it (PDFs) for a scrim, gradient or tint.',
    'v2_chroma_kept': 'Compares the photo\'s colourfulness with the supplied file.',
    'v2_two_colour': 'Checks every pixel of the photograph lies on the blend between the two colours.',
    'v2_tone_between': 'Reads the tone of the ground behind the sitter and checks it lies between the two colours.',
    'v2_legible_at': 'Shrinks the image to the stated width and checks OCR still reads every word.',
    'v2_no_gold': 'Reads the designed colours and checks none is a gold or metallic yellow-brown.',
    'v2_pdf_shapes': 'Reads the shapes drawn in the PDF: their colours, sizes and thickness.',
    'v2_pdf_rule_by_text': 'Finds the text and the full-width rules in the PDF and checks one sits directly by it.',
    'v2_pdf_rules_match': 'Reads the rules\' heights in both PDFs and compares them.',
    'v2_colour_only_in_mark': 'Finds every use of the colour and checks it is only the mark.',
    'v2_solid_pdf': 'Reads the PDF for any transparency or gradient shading.',
    'v2_role_lines': 'Reads the text lines, sorts them into body, headings and fine print by size, and checks the named role.',
    'v2_role_colour_pdf': 'Sorts the PDF text into roles by size and reads the colour of the named role.',
    # PHOTO-19 sitter-ground variants (ops_r3_photo_b.py)
    'v2_palette_sitter_pb': 'Reads every flat colour outside the photographs, leaving out the ground round the cut-out sitter, and checks each is a palette colour.',
    'v2_grounds_sitter_pb': 'Finds every ground and panel outside the photographs, leaving out the ground round the cut-out sitter, and reads its colour.',
    'v2_tone_sitter_pb': 'Finds the cut-out sitter, reads the ground round it and checks each channel lies between the two colours.',
}
R3: dict = {}
for _name in ('round3_photo_a', 'round3_photo_b', 'round3_layout', 'round3_fonts'):
    try:
        _m = importlib.import_module(_name)
    except ModuleNotFoundError as _e:
        if _e.name != _name:
            raise
        continue
    if set(R3) & set(_m.R3):   # a rule converted twice: one handler would silently replace the other
        raise ValueError(f'{_name} converts rules another module already converts: {sorted(set(R3) & set(_m.R3))[:10]}')
    R3.update(_m.R3)
    HOW.update(getattr(_m, 'HOW', {}))


def convert(tid, rid, row, ctx):
    h = R3.get((tid, rid))
    return h(row, ctx) if h else None
