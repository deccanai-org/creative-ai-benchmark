#!/usr/bin/env python3
"""Make LAYOUT-12 test deliverables (no run produced any): a correct set and a set with known defects.

The correct set follows the brief and billing exactly: Pitch ground, Sora ExtraBold act names and date lines in
capitals, Sodium date lines, Bone White for everything else, Archivo Narrow for door, licence and accessibility lines,
true 2026 weekdays (Koa is FRI 16 OCT, not the billing's Sat), acts in billing order, no merchandise photos.
The defect set breaks one thing per deliverable, so each moved check has a known answer.

Usage: python make_layout12_files.py <out dir>     (writes <out>/good/LAYOUT-12/... and <out>/bad/LAYOUT-12/...)
Run with the benchmark_v4 venv (PyMuPDF, fontTools).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pymupdf
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
FONTS = REFRESH / 'fonts'
SOURCES = REFRESH / 'sources/LAYOUT-12'

PITCH, ASH, SODIUM, COLD, BONE, BLOOD = '#0E0E10', '#2A2A2E', '#E4863B', '#3F7C8C', '#E9E4D8', '#8E2B24'
SERIES = 'UMBRA / LOFT'
LICENCE = ('Umbra Loft, 14 Foundry Court (basement), Providence RI. Licensed under City of Providence '
           'Entertainment Licence PVD-2021-0846.')
ACCESS = ('Step-free access to the main room is via the mill loading entrance on request; please contact the '
          'venue in advance.')
# billing order, with each night's support act (umbra_billing_autumn.txt, umbra_nights_autumn.csv)
NIGHTS = [('Sable Quartet', ['2026-09-25'], 'Odette Lang', '8:00 PM', '9:00 PM', '$28'),
          ('Meridian Brass', ['2026-09-26'], 'The Tin Ravens', '8:30 PM', '9:15 PM', '$32'),
          ('Night Ferry', ['2026-10-02'], 'Junior Vale', '8:00 PM', '9:00 PM', '$26'),
          ('The Blue Hour', ['2026-10-03', '2026-10-04'], 'Coral Sound', '8:00 PM', '9:00 PM', '$24'),
          ('Vespertine', ['2026-10-09'], 'Marlow Reyes', '8:00 PM', '9:00 PM', '$22'),
          ('The Eastons', ['2026-10-10'], 'Half Light', '8:30 PM', '9:30 PM', '$28'),
          ('Koa', ['2026-10-16'], 'The Undertow', '8:00 PM', '9:00 PM', '$24'),
          ('Laurel and the Dive', ['2026-10-17'], 'Ferro', '8:30 PM', '9:15 PM', '$26')]
A2 = (1190.55, 1683.78)


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def static_font(var_path: Path, family: str, style: str, wght: int, out: Path) -> Path:
    """A named static instance of a variable font, so the PDF records e.g. Sora-ExtraBold."""
    f = instancer.instantiateVariableFont(TTFont(var_path), {'wght': wght})
    ps = f'{family.replace(" ", "")}-{style}'
    for rec in f['name'].names:
        if rec.nameID in (1, 16):
            rec.string = family
        elif rec.nameID in (2, 17):
            rec.string = style
        elif rec.nameID == 4:
            rec.string = f'{family} {style}'
        elif rec.nameID == 6:
            rec.string = ps
    path = out / f'{ps}.ttf'
    f.save(path)
    return path


def day_line(date: str, weekday: str | None = None) -> str:
    d = dt.date.fromisoformat(date)
    return f'{weekday or d.strftime("%a").upper()} {d.day} {d.strftime("%b").upper()}'


class Page:
    def __init__(self, doc, fonts, size):
        self.page = doc.new_page(width=size[0], height=size[1])
        self.fonts = fonts
        self.page.draw_rect(self.page.rect, color=None, fill=rgb(PITCH))

    def text(self, x, y, text, font, size, colour=BONE):
        self.page.insert_text((x, y), text, fontsize=size, fontname=font, fontfile=str(self.fonts[font]), color=rgb(colour))

    def wrap(self, x, y, text, font, size, width, colour=BONE, leading=1.3):
        f = pymupdf.Font(fontfile=str(self.fonts[font]))
        line = ''
        for word in text.split():
            trial = (line + ' ' + word).strip()
            if f.text_length(trial, fontsize=size) > width and line:
                self.text(x, y, line, font, size, colour)
                y += size * leading
                line = word
            else:
                line = trial
        if line:
            self.text(x, y, line, font, size, colour)
            y += size * leading
        return y


def poster(path: Path, fonts, defect: str | None = None, photo: Path | None = None, merch: Path | None = None):
    doc = pymupdf.open()
    p = Page(doc, fonts, A2)
    p.text(80, 230, SERIES, 'SoraEB', 150)
    if photo:
        p.page.insert_image(pymupdf.Rect(700, 300, 1110, 560), filename=str(photo))
    if merch:
        p.page.insert_image(pymupdf.Rect(700, 300, 1110, 560), filename=str(merch))
    order = list(NIGHTS)
    if defect == 'order':
        order[0], order[1] = order[1], order[0]
    y = 360
    for act, dates, support, door, set_, _ in order:
        days = ' / '.join(day_line(d, 'SAT' if defect == 'weekday' and act == 'Koa' else None) for d in dates)
        p.text(80, y, days, 'SoraEB', 34, BONE if defect == 'date_colour' else SODIUM)
        p.text(80, y + 52, act.upper(), 'SoraEB', 46)
        p.text(80, y + 92, f'WITH {support.upper()}', 'SoraEB', 26)
        p.text(80, y + 124, f'DOORS {door} / SETS {set_}', 'ArchivoNarrowSB', 22)
        y += 158
    caps = (lambda s: s) if defect == 'licence_case' else str.upper
    y = p.wrap(80, 1600, caps(LICENCE), 'ArchivoNarrowR', 14, 1030)
    p.wrap(80, y + 4, ACCESS.upper(), 'ArchivoNarrowR', 14, 1030)
    doc.save(path)


def deck(path: Path, fonts, defect: str | None = None):
    doc = pymupdf.open()
    size = (960, 540)
    p = Page(doc, fonts, size)
    p.text(60, 120, SERIES, 'SoraEB', 64)
    p.text(60, 170, 'AUTUMN AFTER-DARK SERIES', 'ArchivoNarrowSB', 20)
    p = Page(doc, fonts, size)
    y = 70
    for act, dates, support, door, set_, _ in NIGHTS:
        p.text(60, y, ' / '.join(day_line(d) for d in dates), 'SoraEB', 14, SODIUM)
        p.text(250, y, act.upper(), 'SoraEB', 14)
        p.text(520, y, f'DOORS {door}', 'ArchivoNarrowSB', 13)
        y += 52
    p = Page(doc, fonts, size)
    p.text(60, 90, 'THE ROOM', 'SoraEB', 30)
    rows = ['Capacity: 250 standing', 'Seated cabaret capacity: 120', 'Season-average attendance: 183 of 250',
            'Season-average occupancy: 73%']
    if defect == 'capacity':
        rows[0] = 'Capacity: 300 standing'
    for i, row in enumerate(rows):
        p.text(60, 150 + i * 40, row, 'ArchivoNarrowR', 20)
    # a small Cold Signal chart bar: well under 5% of the page
    p.page.draw_rect(pymupdf.Rect(600, 400, 640, 480), color=None, fill=rgb(COLD))
    doc.save(path)


def release_post(path: Path, fonts, act, date, support, door, set_, price, defect: str | None = None):
    """Drawn as a 1080 x 1350 px page and rasterised, as an image deliverable would be."""
    doc = pymupdf.open()
    p = Page(doc, fonts, (1080, 1350))
    p.text(70, 150, SERIES, 'SoraEB', 96)
    weekday = 'SAT' if defect == 'weekday' else None
    p.text(70, 420, day_line(date, weekday), 'SoraEB', 44, SODIUM)
    p.text(70, 520, act.upper(), 'SoraEB', 72)
    p.text(70, 600, f'WITH {support.upper()}', 'SoraEB', 36)
    door_text = door.replace(' ', '&nbsp;') if defect == 'nbsp' else door
    p.text(70, 700, f'DOORS {door_text}', 'ArchivoNarrowSB', 34)
    p.text(70, 750, f'SETS {set_}', 'ArchivoNarrowSB', 34)
    p.text(70, 830, f'ADVANCE {"$99" if defect == "price" else price}', 'ArchivoNarrowSB', 34)
    p.wrap(70, 1230, LICENCE.upper(), 'ArchivoNarrowR', 16, 940)
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False)
    pix.save(path)


def main():
    out = Path(sys.argv[1])
    tmp = out / '_fonts'
    tmp.mkdir(parents=True, exist_ok=True)
    fonts = {'SoraEB': static_font(FONTS / 'sora/Sora[wght].ttf', 'Sora', 'ExtraBold', 800, tmp),
             'ArchivoNarrowSB': static_font(FONTS / 'archivonarrow/ArchivoNarrow[wght].ttf', 'Archivo Narrow', 'SemiBold', 600, tmp),
             'ArchivoNarrowR': static_font(FONTS / 'archivonarrow/ArchivoNarrow[wght].ttf', 'Archivo Narrow', 'Regular', 400, tmp)}
    spec = json.loads((ROOT / 'docs/gatsby-v7/tasks/LAYOUT-12/TASK_SPEC.json').read_text())
    defects = {}
    for kind in ('good', 'bad'):
        d = out / kind / 'LAYOUT-12' / 'deliverables'
        d.mkdir(parents=True, exist_ok=True)
        bad = kind == 'bad'
        poster(d / 'poster-direction-type-led.pdf', fonts, 'weekday' if bad else None)
        poster(d / 'poster-direction-image-led.pdf', fonts, 'licence_case' if bad else None, photo=SOURCES / 'umbra_archive_night_01.jpg',
               merch=SOURCES / 'umbra_wordmark_sable.jpg' if bad else None)
        poster(d / 'poster-direction-graphic-led.pdf', fonts, 'order' if bad else None)
        deck(d / 'promoter-deck.pdf', fonts, 'capacity' if bad else None)
        for o in spec['deliverables']:
            v = (o.get('source_record') or {}).get('values')
            if not v:
                continue
            defect = None
            if bad:
                defect = {'release-post-r002': 'price', 'release-post-r007': 'nbsp', 'release-post-r009': 'weekday'}.get(o['output_id'])
            release_post(out / kind / 'LAYOUT-12' / o['path'], fonts, v['headline'], v['date'], v['support'],
                         v['door'].replace('&nbsp;', ' '), v['set'], v['price'], defect)
            if defect:
                defects[o['output_id']] = defect
    defects.update({'poster-direction-type-led': 'weekday', 'poster-direction-image-led': 'licence_case+merch',
                    'poster-direction-graphic-led': 'order', 'promoter-deck': 'capacity'})
    (out / 'defects.json').write_text(json.dumps(defects, indent=1) + '\n')
    print('made', out)


if __name__ == '__main__':
    main()
