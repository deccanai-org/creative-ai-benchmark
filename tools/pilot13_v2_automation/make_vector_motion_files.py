#!/usr/bin/env python3
"""Make VECTOR-04 and MOTION-11 test deliverables (no run produced any): a correct set and a set with known defects.

VECTOR-04: palette-only SVG stickers with a little Ink Black, companion stickers priced $3 single / $9 four-pack,
transparent PNG proofs and an imposed PDF sheet. Defects: an off-palette red set through a CSS class (invisible to
an attribute scan), Ink Black over 5% of the ink, a $14 price on a sticker, a proof and the sheet.
MOTION-11: thumbnails whose title is the largest text and sits inside the frame, teasers carrying the tagline and
upload line, and the channel animation with STATIC FOX, the members line and the supplied Scrap cutout. Defects: a
title cut off at the edge, a misspelt title, a larger caption beating the title, a changed upload line, a wrong
channel name.

Usage: python make_vector_motion_files.py <out dir>     (writes <out>/good/<TASK>/... and <out>/bad/<TASK>/...)
Run with the benchmark_v4 venv (PyMuPDF, cairosvg) with ffmpeg on PATH.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault('DYLD_FALLBACK_LIBRARY_PATH', '/opt/homebrew/lib:/usr/local/lib:/usr/lib')  # Homebrew Cairo
import cairosvg  # noqa: E402
import pymupdf  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
ROAST, KRAFT, ASH, CREAM, BRICK, INK = '#3E2A20', '#C8A97E', '#5B6B54', '#F3E7D3', '#A8442E', '#201914'
TITLE_FONT = REFRESH / 'fonts/anton/Anton-Regular.ttf'
BODY_FONT = '/System/Library/Fonts/Supplemental/Arial.ttf'


def sticker_svg(kind: str, defect: str | None, price: str | None = None) -> str:
    """A die-cut sticker drawn only with palette fills; the defect variants break one rule."""
    style, extra = '', ''
    if defect == 'css_red':
        style = '<style>.accent{fill:#FF0000}</style>'
        extra = '<circle class="accent" cx="300" cy="120" r="40"/>'
    ink = (f'<rect x="60" y="60" width="480" height="160" fill="{INK}"/>' if defect == 'ink_heavy'
           else f'<rect x="270" y="420" width="60" height="12" fill="{INK}"/>')
    label = (f'<text x="300" y="380" font-family="Arial" font-size="44" text-anchor="middle" fill="{ROAST}">{price}</text>'
             if price else '')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="600" height="600" viewBox="0 0 600 600">{style}'
            f'<circle cx="300" cy="300" r="280" fill="{CREAM}"/>'
            f'<circle cx="300" cy="300" r="250" fill="{KRAFT}"/>'
            f'<path d="M150 330 L300 150 L450 330 Z" fill="{ROAST}"/>'
            f'<rect x="200" y="330" width="200" height="40" fill="{ASH}"/>'
            f'<circle cx="300" cy="250" r="30" fill="{BRICK}"/>{ink}{label}{extra}</svg>')


def vector04(out: Path, bad: bool):
    d = out / 'VECTOR-04' / 'deliverables'
    d.mkdir(parents=True, exist_ok=True)
    good_price = '$3 SINGLE / $9 FOUR-PACK'
    files = {
        'recovered-sticker-window-mark.svg': sticker_svg('mark', 'css_red' if bad else None),
        'recovered-sticker-bag-design-1.svg': sticker_svg('moth', 'ink_heavy' if bad else None),
        'recovered-sticker-bag-design-2.svg': sticker_svg('cone', None),
        'recovered-sticker-bag-design-3.svg': sticker_svg('ridge', None),
        'new-sticker-companion-1.svg': sticker_svg('c1', None, '$14 SINGLE' if bad else good_price),
        'new-sticker-companion-2.svg': sticker_svg('c2', None, good_price),
    }
    for name, svg in files.items():
        (d / name).write_text(svg)
    # transparent proofs: the companion artwork rendered with its transparent surround
    for n, price in (('1', '$14 SINGLE' if bad else good_price), ('2', good_price)):
        png = cairosvg.svg2png(bytestring=sticker_svg(f'c{n}', None, price).encode(), output_width=1200)
        (d / f'sticker-proof-companion-{n}.png').write_bytes(png)
    png = cairosvg.svg2png(bytestring=sticker_svg('ridge', None).encode(), output_width=1200)
    (d / 'sticker-proof-bag-design-3.png').write_bytes(png)
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    for i, svg in enumerate(list(files.values())[:4]):
        img = cairosvg.svg2png(bytestring=svg.encode(), output_width=600)
        page.insert_image(pymupdf.Rect(40 + i * 195, 120, 220 + i * 195, 300), stream=img)
    page.insert_text((40, 520), f'Companion stickers: {"$12" if bad else "$3"} single, $9 four-pack', fontsize=14)
    doc.save(d / 'gang-sheet.pdf')


def frame(size, lines, ground=(16, 16, 20)):
    """lines: (text, x, y, px, colour, font); x may be 'c' to centre."""
    img = Image.new('RGB', size, ground)
    dr = ImageDraw.Draw(img)
    for text, x, y, px, colour, font in lines:
        f = ImageFont.truetype(str(font), px)
        if x == 'c':
            x = (size[0] - dr.textlength(text, font=f)) / 2
        dr.text((x, y), text, fill=colour, font=f)
    return img


def wrap_title(title, size, px, font, margin=60, right=None):
    f = ImageFont.truetype(str(font), px)
    dr = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    width = (right or size[0]) - 2 * margin
    rows, line = [], ''
    for word in title.split():
        trial = (line + ' ' + word).strip()
        if dr.textlength(trial, font=f) > width and line:
            rows.append(line)
            line = word
        else:
            line = trial
    rows.append(line)
    return rows


def video(path: Path, frames, fps=2):
    with tempfile.TemporaryDirectory() as tmp:
        for i, img in enumerate(frames):
            img.save(Path(tmp) / f'f{i:04d}.png')
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-framerate', str(fps), '-i', str(Path(tmp) / 'f%04d.png'),
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', str(path)], check=True)


def motion11(out: Path, bad: bool):
    spec = json.loads((ROOT / 'docs/gatsby-v7/tasks/MOTION-11/TASK_SPEC.json').read_text())
    d = out / 'MOTION-11'
    (d / 'deliverables').mkdir(parents=True, exist_ok=True)
    size = (1280, 720)
    orange, white, acid = (255, 90, 31), (255, 255, 255), (182, 255, 46)
    for o in spec['deliverables']:
        if not o['path'].endswith('.png') or 'thumbnail' not in o['path']:
            continue
        title = o['name'].split(' - ', 1)[1]
        defect = None
        if bad:
            defect = {'thumbnail-everyone-off-the-platform.png': 'cut', 'thumbnail-we-broke-the-map.png': 'spelling',
                      'thumbnail-kitchen-gone.png': 'caption'}.get(Path(o['path']).name)
        shown = 'WE BROKE THE MAPS' if defect == 'spelling' else title
        px = 96 if len(title) < 30 else 64
        rows = wrap_title(shown, size, px, TITLE_FONT)
        lines = [(r, 60, 80 + i * (px + 18), px, white, TITLE_FONT) for i, r in enumerate(rows)]
        if defect == 'cut':
            lines = [(r, 760, 80 + i * (px + 18), px, white, TITLE_FONT) for i, r in enumerate(rows)]
        caption_px = 130 if defect == 'caption' else 30
        lines.append(('NEW ONE EVERY OTHER DAY', 60, 600 if defect != 'caption' else 470, caption_px, acid, TITLE_FONT))
        frame(size, lines).save(d / o['path'])
    tagline, upload = 'Co op disasters and bad decisions.', 'NEW ONE EVERY OTHER DAY'
    shown_upload = 'NEW ONE EVERY DAY' if bad else upload
    for name, vsize in (('channel-teaser.mp4', (1280, 720)), ('channel-teaser-vertical.mp4', (720, 1280))):
        frames = [frame(vsize, [('STATIC FOX', 'c', vsize[1] // 3, 110, orange, TITLE_FONT)])] * 2
        frames += [frame(vsize, [(tagline, 'c', vsize[1] // 2, 40, white, BODY_FONT)])] * 3
        frames += [frame(vsize, [(shown_upload, 'c', vsize[1] // 2, 60, acid, TITLE_FONT)])] * 3
        video(d / 'deliverables' / name, frames)
    scrap = Image.open(REFRESH / 'upload/MOTION-11/staticfox_scrap_transparent.png').convert('RGBA')
    scrap = scrap.resize((360, round(360 * scrap.height / scrap.width)))
    name_shown = 'STATIC FAX' if bad else 'STATIC FOX'
    title_card = frame(size, [(name_shown, 'c', 250, 150, orange, TITLE_FONT)])
    title_card.paste(scrap, (880, 330), scrap)
    members = 'Members get the Sunday chaos stream and the bloopers nobody should see. Link in the description.'
    rows = wrap_title(members, size, 38, BODY_FONT, margin=80)
    end_card = frame(size, [(r, 80, 380 + i * 52, 38, white, BODY_FONT) for i, r in enumerate(rows)]
                     + [('STATIC FOX', 80, 140, 120, orange, TITLE_FONT)])
    video(d / 'deliverables' / 'channel-animation.mp4', [title_card] * 3 + [end_card] * 4)


def main():
    out = Path(sys.argv[1])
    for kind in ('good', 'bad'):
        vector04(out / kind, kind == 'bad')
        motion11(out / kind, kind == 'bad')
    print('made', out)


if __name__ == '__main__':
    main()
