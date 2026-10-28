#!/usr/bin/env python3
"""Pass, fail and person fixtures for objective_ops_r2 (round 2). Every fixture is drawn here (PDFs with PyMuPDF,
SVGs as text), so the tests need no binary files. Run with the benchmark_v4 venv:

    python tools/auto_verifier/test_objective_ops_r2.py      (or python -m pytest on the same file)
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault('DYLD_FALLBACK_LIBRARY_PATH', '/opt/homebrew/lib:/usr/local/lib:/usr/lib')  # Homebrew Cairo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import objective_ops as o  # noqa: E402
import objective_ops_r2 as r2  # noqa: E402

o.OPS.update(r2.OPS_R2)


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def pdf(tmp_path, name, lines, rects=(), size=(420, 595), spacing=None):
    """lines: (text, x, y, pt, hex); rects: (rect, hex). spacing: {text: Tc}, letter spacing written into the page."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=size[0], height=size[1])
    for rect, hexcol in rects:
        page.draw_rect(pymupdf.Rect(*rect), color=None, fill=rgb(hexcol))
    extra = b''
    for text, x, y, pt, hexcol in lines:
        if spacing and text in spacing:
            r, g, b = rgb(hexcol)
            extra += f'\nBT /{{font}} {pt} Tf {spacing[text]} Tc {r} {g} {b} rg 1 0 0 1 {x} {size[1] - y} Tm ({text}) Tj ET'.encode()
        else:
            page.insert_text((x, y), text, fontsize=pt, fontname='helv', color=rgb(hexcol))
    if extra:
        # letter spacing is the PDF Tc operator, which insert_text cannot write: append a text object to the page
        page.clean_contents()
        ref = page.get_fonts()[0][4]
        xref = page.get_contents()[0]
        doc.update_stream(xref, doc.xref_stream(xref) + extra.replace(b'{font}', ref.encode()))
    path = tmp_path / name
    doc.save(path)
    return path


def test_paired_rate_by_house_and_season(tmp_path):
    lines = [('Casa Alba', 40, 60, 24, '#222222'), ('SPRING', 40, 120, 9, '#222222'), ('AUTUMN', 200, 120, 9, '#222222'),
             ('EUR 520 / night', 40, 145, 12, '#222222'), ('EUR 560 / night', 200, 145, 12, '#222222'),
             ('Casa Bruna', 40, 300, 24, '#222222'), ('SPRING', 40, 360, 9, '#222222'), ('EUR 610 / night', 40, 385, 12, '#222222')]
    f = pdf(tmp_path, 'villas.pdf', lines)
    base = {'op': 'v2_paired', 'anchor': ['Casa Alba'], 'rivals': ['Casa Bruna'], 'label': ['Spring'], 'label_rivals': ['Autumn'],
            'kind': r'EUR\s?\d', 'where': 'section'}
    assert o.run(f, dict(base, value={'regex': r'(?<!\d)520(?!\d)'}))[0] == 'pass'
    assert o.run(f, dict(base, value={'regex': r'(?<!\d)560(?!\d)'}))[0] == 'fail'          # Autumn's rate, not Spring's
    assert o.run(f, dict(base, anchor=['Casa Bruna'], rivals=['Casa Alba'], value={'regex': r'(?<!\d)520(?!\d)'}))[0] == 'fail'
    assert o.run(f, dict(base, anchor=['Casa Nera'], value={'regex': '520'}))[0] == o.PERSON


def test_paired_beside_takes_the_value_in_its_own_column(tmp_path):
    lines = [('Foundations', 40, 100, 14, '#222222'), ('$34', 160, 100, 12, '#222222'),
             ('Flow', 230, 100, 14, '#222222'), ('$36', 340, 100, 12, '#222222')]
    f = pdf(tmp_path, 'prices.pdf', lines)
    a = {'op': 'v2_paired', 'anchor': ['Flow'], 'whole_line': False, 'kind': r'\$\s?\d', 'where': 'beside', 'empty_ok': True}
    assert o.run(f, dict(a, value={'regex': r'\$36'}))[0] == 'pass'
    assert o.run(f, dict(a, value={'regex': r'\$34'}))[0] == 'fail'


def test_text_on_ground(tmp_path):
    f = pdf(tmp_path, 'ground.pdf', [('On blue', 40, 80, 20, '#EFE9DC'), ('Dark line', 40, 200, 20, '#222222'),
                                     ('On paper', 40, 400, 20, '#222222')],
            rects=[((20, 50, 400, 230), '#24425A')])
    a = {'op': 'v2_text_on_ground', 'texts': ['On blue'], 'grounds': ['#24425A'], 'colors': ['#EFE9DC']}
    assert o.run(f, a)[0] == 'pass'
    assert o.run(f, dict(a, texts=['Dark line']))[0] == 'fail'
    assert o.run(f, dict(a, texts=['On paper']))[0] == 'pass'                  # not on blue: the check does not apply
    assert o.run(f, {'op': 'v2_text_on_ground', 'texts': ['On paper'], 'ground_must': ['#24425A']})[0] == 'fail'


def test_page_size_and_blank_page(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    doc.new_page(width=595.28, height=841.89).insert_text((40, 40), 'A4 page')
    doc.new_page(width=595.28, height=841.89)
    f = tmp_path / 'pages.pdf'
    doc.save(f)
    assert o.run(f, {'op': 'v2_page_size', 'width_mm': 210, 'height_mm': 297, 'no_bleed': True})[0] == 'pass'
    assert o.run(f, {'op': 'v2_page_size', 'width_mm': 216, 'height_mm': 279})[0] == 'fail'
    assert o.run(f, {'op': 'v2_no_blank_page'})[0] == 'fail'


def test_letter_spacing(tmp_path):
    f = pdf(tmp_path, 'track.pdf', [('FRI 25 SEP', 40, 100, 20, '#222222'), ('SABLE QUARTET', 40, 140, 30, '#222222')],
            spacing={'FRI 25 SEP': 4})
    a = {'op': 'v2_tracking', 'a': {'patterns': [r'\d{1,2}\s*SEP']}, 'b': {'texts': ['Sable Quartet']}}
    assert o.run(f, a)[0] == 'pass'
    g = pdf(tmp_path, 'tight.pdf', [('FRI 25 SEP', 40, 100, 20, '#222222'), ('SABLE QUARTET', 40, 140, 30, '#222222')])
    assert o.run(g, a)[0] == 'fail'


def test_size_pairs_never_pass_unpaired(tmp_path):
    f = pdf(tmp_path, 'product.pdf', [('OATMEAL MUG', 40, 60, 13, '#222222'), ('$45', 300, 400, 17, '#222222')])
    assert o.run(f, {'op': 'v2_size_pairs', 'names': ['Oatmeal Mug'], 'kind': r'\$\s?\d'})[0] == 'fail'
    g = pdf(tmp_path, 'two.pdf', [('OATMEAL MUG', 40, 60, 13, '#222222'), ('INDIGO BOWL', 220, 60, 13, '#222222')])
    assert o.run(g, {'op': 'v2_size_pairs', 'names': ['Oatmeal Mug', 'Indigo Bowl'], 'kind': r'\$\s?\d'})[0] == o.PERSON


def svg(tmp_path, name, body, mm=55):
    f = tmp_path / name
    f.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{mm}mm" height="{mm}mm" viewBox="0 0 100 100">{body}</svg>')
    return f


def test_svg_size_cut_line_and_main_ink(tmp_path):
    art = '<rect x="0" y="0" width="100" height="100" fill="#C8A97E"/><circle cx="50" cy="50" r="30" fill="#5B6B54"/>'
    f = svg(tmp_path, 'ok.svg', art + '<g id="CutContour"><circle cx="50" cy="50" r="49" fill="none" stroke="#FF00FF"/></g>')
    assert o.run(f, {'op': 'v2_svg_size', 'long_mm': 55})[0] == 'pass'
    assert o.run(svg(tmp_path, 'big.svg', art, mm=70), {'op': 'v2_svg_size', 'long_mm': 55})[0] == 'fail'
    assert o.run(f, {'op': 'v2_svg_no_cutline'})[0] == 'pass'
    drawn = svg(tmp_path, 'drawn.svg', art + '<circle cx="50" cy="50" r="49" fill="none" stroke="#000000" stroke-width="1"/>')
    assert o.run(drawn, {'op': 'v2_svg_no_cutline'})[0] == 'fail'
    assert o.run(f, {'op': 'v2_main_ink', 'hexes': ['#5B6B54'], 'grounds': ['#C8A97E']})[0] == 'pass'
    assert o.run(f, {'op': 'v2_main_ink', 'hexes': ['#A8442E'], 'grounds': ['#C8A97E']})[0] == 'fail'


def test_ampersand_ratio(tmp_path):
    good = svg(tmp_path, 'amp.svg', '<text font-family="DM Serif Display" font-size="10" x="5" y="50">MERIDIAN'
                                    '<tspan font-size="16">&amp;</tspan>ASH</text>')
    flat = svg(tmp_path, 'flat.svg', '<text font-family="DM Serif Display" font-size="10" x="5" y="50">MERIDIAN &amp; ASH</text>')
    a = {'op': 'v2_svg_glyph_ratio', 'glyph': '&', 'family': 'DM Serif Display', 'ratio': 1.6}
    assert o.run(good, a)[0] == 'pass'
    assert o.run(flat, a)[0] == 'fail'


def test_directly_above_and_stacked(tmp_path):
    f = pdf(tmp_path, 'bill.pdf', [('FRI 25 SEP', 40, 100, 14, '#222222'), ('SABLE QUARTET', 40, 130, 24, '#222222'),
                                   ('MERIDIAN BRASS', 40, 200, 24, '#222222'), ('LUNARA', 40, 300, 20, '#222222'),
                                   ('CHRONOMETRY', 40, 322, 12, '#222222')])
    a = {'op': 'v2_directly_above', 'pattern': r'\d{1,2}\s*SEP'}
    assert o.run(f, dict(a, texts=['Sable Quartet']))[0] == 'pass'
    assert o.run(f, dict(a, texts=['Meridian Brass']))[0] == 'fail'
    assert o.run(f, {'op': 'v2_stacked', 'top': 'Lunara', 'bottom': 'Chronometry', 'stack': True})[0] == 'pass'


def main():
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith('test_') and callable(fn)]
    failed = 0
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(Path(tmp))
                print('ok  ', name)
            except Exception:
                failed += 1
                print('FAIL', name)
                traceback.print_exc()
    print(f'{len(tests) - failed}/{len(tests)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
