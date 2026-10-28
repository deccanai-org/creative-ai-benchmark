#!/usr/bin/env python3
"""Pass, fail and person fixtures for objective_ops. Every fixture is drawn here (PDFs with PyMuPDF, images with
Pillow), so the tests need no binary files. Run with the benchmark_v4 venv and Tesseract on PATH:

    python tools/auto_verifier/test_objective_ops.py      (or python -m pytest on the same file)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import objective_ops as o  # noqa: E402

FONT = next((p for p in ('/System/Library/Fonts/Supplemental/Arial.ttf', '/Library/Fonts/Arial.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
                         '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf') if Path(p).is_file()), None)
OCR_READY = bool(shutil.which('tesseract') and FONT)


def needs_ocr(test):
    test.needs_ocr = True
    return test


def pdf(tmp_path, name, lines, images=(), rects=()):
    """lines: (text, x, y, size, hex); images: (png path, rect in pt); rects: (rect, hex)."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=595)
    for rect, hexcol in rects:
        page.draw_rect(pymupdf.Rect(*rect), color=None, fill=tuple(int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5)))
    for text, x, y, size, hexcol in lines:
        page.insert_text((x, y), text, fontsize=size, fontname='helv',
                         color=tuple(int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5)))
    for png, rect in images:
        page.insert_image(pymupdf.Rect(*rect), filename=str(png))
    path = tmp_path / name
    doc.save(path)
    return path


def card(tmp_path, name, lines, size=(1080, 1350), ground=(238, 238, 238)):
    """lines: (text, x, y, px size)."""
    img = Image.new('RGB', size, ground)
    d = ImageDraw.Draw(img)
    for text, x, y, px in lines:
        d.text((x, y), text, fill=(30, 30, 30), font=ImageFont.truetype(FONT, px))
    path = tmp_path / name
    img.save(path)
    return path


def photo(seed, size=(600, 450)):
    """A textured stand-in photograph: random blobs are rich in features, like a real picture."""
    rng = np.random.default_rng(seed)
    img = Image.new('RGB', size, tuple(int(v) for v in rng.integers(0, 255, 3)))
    d = ImageDraw.Draw(img)
    for _ in range(260):
        x, y = rng.integers(0, size[0]), rng.integers(0, size[1])
        r = int(rng.integers(4, 40))
        d.ellipse((x - r, y - r, x + r, y + r), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    return img


# ------------------------------------------------------------------ text read from PDFs

def test_pdf_text_present_pass_fail_and_case(tmp_path):
    f = pdf(tmp_path, 'a.pdf', [('Casa Verranza', 40, 80, 24, '#24425A'), ('SPRING', 40, 120, 10, '#24425A')])
    assert o.run(f, {'op': 'v2_text_present', 'expected': ['Casa Verranza']})[0] == 'pass'
    assert o.run(f, {'op': 'v2_text_present', 'expected': ['Casa Oliveto']})[0] == 'fail'
    # same words in capitals: a person judges, never a fail
    assert o.run(f, {'op': 'v2_text_present', 'expected': ['Spring']})[0] == o.PERSON


def test_forbidden_inside_expected_counts_only_on_its_own(tmp_path):
    plus = pdf(tmp_path, 'plus.pdf', [('Meridian Certified Plus', 40, 80, 12, '#000000')])
    plain = pdf(tmp_path, 'plain.pdf', [('Meridian Certified', 40, 80, 12, '#000000')])
    a = {'op': 'v2_text_present', 'expected': ['Meridian Certified Plus'],
         'forbidden': [{'text': 'Meridian Certified', 'outside': ['Meridian Certified Plus']}]}
    assert o.run(plus, a)[0] == 'pass'
    assert o.run(plain, a)[0] == 'fail'


def test_pdf_text_absent_and_mention_for_a_person(tmp_path):
    f = pdf(tmp_path, 'b.pdf', [('Casa Fienile is no longer in the collection.', 40, 80, 10, '#000000')])
    assert o.run(f, {'op': 'v2_text_absent', 'texts': ['Fienile']})[0] == 'fail'
    assert o.run(f, {'op': 'v2_text_absent', 'texts': ['Fienile'], 'found_is': 'person'})[0] == o.PERSON
    assert o.run(f, {'op': 'v2_text_absent', 'texts': ['Scogliera']})[0] == 'pass'


def test_placeholder_values_keep_thousands_commas(tmp_path):
    f = pdf(tmp_path, 'c.pdf', [('$26,900   48,200 mi', 40, 80, 12, '#000000')])
    a = {'op': 'v2_text_absent', 'texts': ['M2290'], 'patterns': {'$22,900': r'\$\s?(?<![\d,.])22,?900(?![\d,.]|\d)',
                                                                   '71,300 mi': r'(?<![\d,.])71,?300(?![\d,.]|\d)'}}
    assert o.run(f, a)[0] == 'pass'
    g = pdf(tmp_path, 'd.pdf', [('$22,900', 40, 80, 12, '#000000')])
    assert o.run(g, a)[0] == 'fail'


def test_prices_in_range(tmp_path):
    ok = pdf(tmp_path, 'e.pdf', [('Passes from $650 to $1,150', 40, 80, 12, '#000000')])
    bad = pdf(tmp_path, 'f.pdf', [('Passes from $450', 40, 80, 12, '#000000')])
    a = {'op': 'v2_prices', 'mode': 'range', 'min': 600.0, 'max': 1200.0}
    assert o.run(ok, a)[0] == 'pass'
    assert o.run(bad, a)[0] == 'fail'


def test_line_lengths(tmp_path):
    office = 'Concord Branch, 212 North Main St, Concord NH 03301'
    long_office = office + ', Suite 400, second floor, rear entrance'
    ok = pdf(tmp_path, 'g.pdf', [(office, 30, 80, 8, '#4A5560')])
    bad = pdf(tmp_path, 'h.pdf', [(long_office, 30, 80, 6, '#4A5560')])
    assert o.run(ok, {'op': 'v2_line_lengths', 'texts': [office], 'max_chars': 65})[0] == 'pass'
    assert o.run(bad, {'op': 'v2_line_lengths', 'texts': [long_office], 'max_chars': 65})[0] == 'fail'


def test_palette_only(tmp_path):
    ok = pdf(tmp_path, 'i.pdf', [('Ink', 40, 80, 12, '#24425A')], rects=[((0, 0, 420, 595), '#EFE9DC')])
    bad = pdf(tmp_path, 'j.pdf', [('Ink', 40, 80, 12, '#FF0000')], rects=[((0, 0, 420, 595), '#EFE9DC')])
    a = {'op': 'v2_palette_only', 'hexes': ['#24425A', '#EFE9DC']}
    assert o.run(ok, a)[0] == 'pass'
    assert o.run(bad, a)[0] == 'fail'


# ------------------------------------------------------------------ OCR on images

@needs_ocr
def test_ocr_presence_absence_and_sizes(tmp_path):
    if not OCR_READY:
        return
    f = card(tmp_path, 'card.png', [('Marguerite Halloran', 70, 900, 64), ('Founder & CEO', 70, 1000, 36),
                                     ('Aldermoor Robotics', 70, 1100, 26)])
    assert o.run(f, {'op': 'v2_text_present', 'expected': ['Marguerite Halloran']})[0] == 'pass'
    assert o.run(f, {'op': 'v2_text_present', 'expected': ['Peter Vance']})[0] == 'fail'
    # a near miss may be a misreading, so a person decides
    assert o.run(f, {'op': 'v2_text_present', 'expected': ['Marguerite Halleran']})[0] == o.PERSON
    assert o.run(f, {'op': 'v2_text_absent', 'texts': ['Now confirmed.']})[0] == 'pass'
    assert o.run(f, {'op': 'v2_largest_text', 'text': 'Marguerite Halloran'})[0] == 'pass'
    assert o.run(f, {'op': 'v2_largest_text', 'text': 'Founder & CEO'})[0] == 'fail'
    assert o.run(f, {'op': 'v2_relation', 'a': 'Founder & CEO', 'b': ['Aldermoor Robotics'], 'rel': 'larger'})[0] == 'pass'
    assert o.run(f, {'op': 'v2_relation', 'a': 'Aldermoor Robotics', 'b': ['Founder & CEO'], 'rel': 'larger'})[0] == 'fail'


@needs_ocr
def test_heading_over_several_lines_counts_as_one_text(tmp_path):
    if not OCR_READY:
        return
    f = card(tmp_path, 'poster.png', [('Cascadia', 90, 200, 110), ('Founders', 90, 340, 110), ('Summit', 90, 480, 110),
                                       ('12-13 March 2026', 90, 700, 40)], size=(1920, 1080))
    assert o.run(f, {'op': 'v2_text_present', 'expected': ['Cascadia Founders Summit']})[0] == 'pass'
    assert o.run(f, {'op': 'v2_largest_text', 'text': 'Cascadia Founders Summit'})[0] == 'pass'


# ------------------------------------------------------------------ supplied files found in deliverables

def test_photo_found_kept_in_shape_and_absent(tmp_path):
    src = photo(1)
    src.save(tmp_path / 'portrait.jpg', quality=95)
    photo(2).save(tmp_path / 'other.jpg', quality=95)
    scene = Image.new('RGB', (1080, 1350), (230, 230, 230))
    scene.paste(src.resize((540, 405)), (270, 200))
    scene.save(tmp_path / 'kept.png')
    stretched = Image.new('RGB', (1080, 1350), (230, 230, 230))
    stretched.paste(src.resize((700, 405)), (190, 200))
    stretched.save(tmp_path / 'stretched.png')
    dirs = {'_asset_dirs': [str(tmp_path)]}
    assert o.run(tmp_path / 'kept.png', dict(dirs, op='v2_contains_asset', assets=['portrait.jpg'], shape=True))[0] == 'pass'
    assert o.run(tmp_path / 'stretched.png', dict(dirs, op='v2_contains_asset', assets=['portrait.jpg'], shape=True))[0] == 'fail'
    assert o.run(tmp_path / 'kept.png', dict(dirs, op='v2_lacks_asset', assets=['other.jpg']))[0] == 'pass'
    assert o.run(tmp_path / 'kept.png', dict(dirs, op='v2_lacks_asset', assets=['portrait.jpg']))[0] == 'fail'


def test_flat_mark_matched_as_template(tmp_path):
    mark = Image.new('RGBA', (900, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(mark)
    d.rectangle((40, 40, 160, 260), fill=(35, 48, 58, 255))
    d.polygon([(260, 260), (380, 40), (500, 260)], fill=(35, 48, 58, 255))
    d.ellipse((600, 40, 820, 260), fill=(35, 48, 58, 255))
    d.ellipse((660, 100, 760, 200), fill=(0, 0, 0, 0))
    mark.save(tmp_path / 'brand_mark.png')
    gray = o._load_gray(tmp_path / 'brand_mark.png')
    ink = o._ink_crop(gray)
    for stretch, expect_found in ((1.0, True), (1.15, False)):
        scene = np.full((700, 1000), 60, np.uint8)
        w = int(240 * stretch)
        h = round(240 * ink.shape[0] / ink.shape[1])
        placed = np.asarray(Image.fromarray(255 - ink).resize((w, h), Image.LANCZOS))
        scene[100:100 + h, 300:300 + w] = placed
        score, _ = o.find_flat(scene, gray)
        assert (score >= o.FLAT_MIN_SCORE) == expect_found, (stretch, score)


def test_image_ppi(tmp_path):
    src = photo(3, (1200, 900))
    src.save(tmp_path / 'headshot.png')
    sharp = pdf(tmp_path, 'k.pdf', [], images=[(tmp_path / 'headshot.png', (20, 20, 236, 182))])     # 3 in wide: 400 ppi
    soft = pdf(tmp_path, 'l.pdf', [], images=[(tmp_path / 'headshot.png', (20, 20, 400, 305))])      # 5.3 in wide: 227 ppi
    a = {'op': 'v2_image_ppi', 'asset': 'headshot.png', 'min_ppi': 300, '_asset_dirs': [str(tmp_path)]}
    status, ev = o.run(sharp, a)
    assert status == 'pass' and abs(ev['placements'][0]['ppi'] - 400) < 2
    assert o.run(soft, a)[0] == 'fail'


def test_any_of_disagreement_goes_to_a_person(tmp_path):
    f = pdf(tmp_path, 'm.pdf', [('CFS', 40, 80, 20, '#000000')])
    passes = {'op': 'v2_text_present', 'expected': ['CFS']}
    fails = {'op': 'v2_text_present', 'expected': ['XYZ']}
    assert o.run(f, {'op': 'v2_any_of', 'checks': [passes, passes]})[0] == 'pass'
    assert o.run(f, {'op': 'v2_any_of', 'checks': [passes, fails]})[0] == o.PERSON
    assert o.run(f, {'op': 'v2_any_of', 'checks': [fails, fails]})[0] == 'fail'


def main():
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith('test_') and callable(fn)]
    failed = 0
    for name, fn in tests:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                fn(Path(tmp))
                print('ok  ', name, '(skipped: no Tesseract)' if getattr(fn, 'needs_ocr', False) and not OCR_READY else '')
            except Exception:
                failed += 1
                print('FAIL', name)
                traceback.print_exc()
    print(f'{len(tests) - failed}/{len(tests)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
