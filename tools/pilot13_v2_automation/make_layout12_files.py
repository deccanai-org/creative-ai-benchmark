#!/usr/bin/env python3
"""Make LAYOUT-12 test deliverables (no run produced any): a correct set and two sets with known defects.

The correct set follows the brief and billing exactly: Pitch ground, Sora ExtraBold act names and date lines in
capitals, each Sodium date line directly above its Bone White act name, Bone White for everything else, Archivo Narrow
for support, door, licence and accessibility lines, true 2026 weekdays (Koa is FRI 16 OCT, not the billing's Sat),
acts in billing order, no merchandise photos. Type-system tracking is real PDF character spacing (the Tc operator):
act names -10, date lines +20, billing 0, door and fine print +30. The supplied production wordmarks
(upload/umbra_sable_wordmark_transparent.png, umbra_meridian_wordmark_transparent.png) sit beside the typeset act
names on the posters, in the deck and on their release posts: the ink is recoloured to Bone White for the Pitch
ground, the alpha channel (letter shapes and edge anti-aliasing) is kept as supplied, and ink the files hold at 94-99%
opacity is made solid. The three poster directions are distinct (type-led title stack; image-led archive photograph
in a Pitch and Sodium two-colour and grain treatment; graphic-led Ash panel with Sodium leader rules). The six-page
deck shows renders of the three delivered posters and charts last season's draw by month, every value labelled.

The bad set breaks one round-1 rule per deliverable (defects.json). The bad2 set starts from the correct set and
plants round-2 defects, at most one per file, listed with every round-2 rule they break in defects2.json.

Usage: python make_layout12_files.py <out dir>
       (writes <out>/good/LAYOUT-12/..., <out>/bad/LAYOUT-12/..., <out>/bad2/LAYOUT-12/..., defects.json, defects2.json)
Run with the benchmark_v4 venv (PyMuPDF, fontTools, Pillow, numpy).
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import sys
from pathlib import Path

import numpy as np
import pymupdf
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
FONTS = REFRESH / 'fonts'
SOURCES = REFRESH / 'sources/LAYOUT-12'
UPLOAD = REFRESH / 'upload/LAYOUT-12'

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
HEADLINERS = ('Sable Quartet', 'Meridian Brass', 'Night Ferry')     # larger than the 48 pt acts on posters
WORDMARKS = {'Sable Quartet': 'umbra_sable_wordmark_transparent.png',
             'Meridian Brass': 'umbra_meridian_wordmark_transparent.png'}
DRAW = [('Sep', 168), ('Oct', 201), ('Nov', 187), ('Dec', 224), ('Jan', 142), ('Feb', 176)]   # umbra_room_specs.txt
DIRECTIONS = ('type-led', 'image-led', 'graphic-led')
A2, DECK, POST = (1190.55, 1683.78), (960, 540), (1080, 1350)
ACT_TRACK, DATE_TRACK, FINE_TRACK = -10, 20, 30    # thousandths of an em: type system steps 01, 02 and 04
CAP = 0.73                                          # Sora cap height in em

# round-1 defects: one per deliverable (the image-led poster also carries a merchandise photo)
BAD = {'poster-direction-type-led': 'weekday', 'poster-direction-image-led': 'licence_case',
       'poster-direction-graphic-led': 'order', 'promoter-deck': 'capacity',
       'release-post-r002': 'price', 'release-post-r007': 'nbsp', 'release-post-r009': 'weekday'}
# round-2 defects: deliverable -> (defect, every round-2 rule it breaks, description); release-post-r008 stays correct
BAD2 = {
    'poster-direction-type-led': ('wrong_date', ['R002'],
                                  "The Blue Hour's first residency night is billed FRI 2 OCT (Night Ferry's date), "
                                  'not SAT 3 OCT; SUN 4 OCT is right'),
    'poster-direction-image-led': ('co_headliner', ['R005', 'R026', 'R176'],
                                   "The Blue Hour's support act is set as a second headline: CORAL SOUND in Sora "
                                   'ExtraBold at the act name\'s 48 pt, with no "with", so it is no longer billed as '
                                   'the support act (R005 fails on The Blue Hour\'s row only)'),
    'poster-direction-graphic-led': ('tight_dates', ['R147'],
                                     'every date line is set at -60 tracking, tighter than the act names at -10'),
    'promoter-deck': ('drafts', ['R020', 'R027', 'R028'],
                      'the deck shows earlier drafts of all three directions (type-led title on one line and no '
                      'wordmarks, image-led with another photograph in Pitch and Cold Signal, graphic-led with the '
                      'panel on the left), not the delivered posters'),
    'release-post-r002': ('wordmark_for_name', ['R032'],
                          'the Sable Quartet wordmark stands in place of the typeset act name, under the date line'),
    'release-post-r003': ('other_mark', ['R033'],
                          'the Sable Quartet wordmark is placed where the Meridian Brass wordmark belongs'),
    'release-post-r004': ('weekday', ['R015'], 'dated SAT 2 OCT; 2 Oct 2026 is a Friday'),
    'release-post-r005': ('other_night', ['R059', 'R015'], "dated SUN 4 OCT, the residency's other night"),
    'release-post-r006': ('date_below', ['R161'], 'the date line sits below the act name, not above it'),
    'release-post-r007': ('price_cut_right', ['R039'],
                          'the advance price runs off the right edge, its last figure cut in half'),
    'release-post-r009': ('price_cut_bottom', ['R039'],
                          'the advance price line sits on the bottom edge, the lower part of its letters cut off'),
    'release-post-r010': ('weekday_fri', ['R015'], 'dated FRI 17 OCT; 17 Oct 2026 is a Saturday'),
}


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def rgb255(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


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


@functools.lru_cache(maxsize=None)
def metrics(path: str) -> pymupdf.Font:
    return pymupdf.Font(fontfile=path)


def day_line(date: str, weekday: str | None = None) -> str:
    d = dt.date.fromisoformat(date)
    return f'{weekday or d.strftime("%a").upper()} {d.day} {d.strftime("%b").upper()}'


def bone_wordmark(name: str, out: Path) -> Path:
    """A supplied production wordmark recoloured for Pitch grounds and cropped to its ink: every pixel takes Bone
    White, the alpha channel (letter shapes, edge anti-aliasing) is kept, and ink held at 94-99% opacity is made solid."""
    a = np.asarray(Image.open(UPLOAD / name).convert('RGBA'))
    alpha = a[..., 3].copy()
    ys, xs = np.nonzero(alpha)
    alpha[alpha >= 240] = 255
    ink = np.zeros_like(a)
    ink[..., :3] = rgb255(BONE)
    ink[..., 3] = alpha
    Image.fromarray(ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]).save(out)
    return out


def treated(src: Path, out: Path, size, top: float, pair=(PITCH, SODIUM), seed=1) -> Path:
    """An archive photograph in the series two-colour and grain treatment: cropped (never stretched) to the
    placement's proportions, luminance mapped from the dark palette colour to the light one, with fine grain."""
    im = Image.open(src).convert('L')
    crop = round(im.width * size[1] / size[0])
    y0 = round((im.height - crop) * top)
    a = np.asarray(im.crop((0, y0, im.width, y0 + crop)).resize(size, Image.LANCZOS), float)
    lo, hi = np.percentile(a, (1, 99.5))
    a = np.clip((a - lo) / (hi - lo), 0, 1) ** 0.8
    a = np.clip(a + np.random.default_rng(seed).normal(0, 0.07, a.shape), 0, 1)
    dark, light = (np.array(rgb255(c), float) for c in pair)
    Image.fromarray((dark + a[..., None] * (light - dark)).round().astype(np.uint8)).save(out, quality=90)
    return out


def render(pdf: Path, out: Path, dpi=60) -> Path:
    """A page render, as placed in the deck to show a delivered poster (the part-covered last pixel row and column
    are dropped, so no light edge shows)."""
    page = pymupdf.open(pdf)[0]
    pix = page.get_pixmap(dpi=dpi)
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    im.crop((0, 0, int(page.rect.width * dpi / 72), int(page.rect.height * dpi / 72))).save(out, quality=90)
    return out


class Page:
    def __init__(self, doc, fonts, size):
        self.page = doc.new_page(width=size[0], height=size[1])
        self.fonts = fonts
        self.page.draw_rect(self.page.rect, color=None, fill=rgb(PITCH))

    def text(self, x, y, text, font, size, colour=BONE, track=0):
        """Live text; track (thousandths of an em) is written as the PDF Tc operator, which insert_text lacks."""
        shape = self.page.new_shape()
        shape.insert_text((x, y), text, fontsize=size, fontname=font, fontfile=str(self.fonts[font]), color=rgb(colour))
        if track:
            shape.text_cont = shape.text_cont.replace(' Tf ', f' Tf {track * size / 1000:.3f} Tc ', 1)
        shape.commit()

    def width(self, text, font, size, track=0):
        return metrics(str(self.fonts[font])).text_length(text, fontsize=size) + track * size / 1000 * (len(text) - 1)

    def wrap(self, x, y, text, font, size, width, colour=BONE, leading=1.3, track=0):
        line = ''
        for word in text.split():
            trial = (line + ' ' + word).strip()
            if self.width(trial, font, size, track) > width and line:
                self.text(x, y, line, font, size, colour, track)
                y += size * leading
                line = word
            else:
                line = trial
        if line:
            self.text(x, y, line, font, size, colour, track)
            y += size * leading
        return y

    def mark(self, path, x, mid, height):
        """A wordmark of the given height, its left edge at x and centred on mid, in its own proportions."""
        w, h = Image.open(path).size
        rect = pymupdf.Rect(x, mid - height / 2, x + height * w / h, mid + height / 2)
        self.page.insert_image(rect, filename=str(path))
        return rect


def billing(p, x, y, nights, head, defect=None, gap=24):
    """Act blocks top to bottom: the Sodium date line directly above the Bone White act name, then the support act
    prefixed "with" and the SemiBold door line. Returns each act line's box and the bottom of the list."""
    boxes = {}
    for act, dates, support, door, set_, _ in nights:
        size = head if act in HEADLINERS else 48
        days = ' / '.join(day_line(d, 'SAT' if defect == 'weekday' and act == 'Koa' else None) for d in dates)
        if defect == 'wrong_date' and act == 'The Blue Hour':
            days = f'{day_line("2026-10-02")} / {day_line(dates[1])}'
        y += CAP * 18
        p.text(x, y, days, 'SoraEB', 18, SODIUM, -60 if defect == 'tight_dates' else DATE_TRACK)
        top = y + 8
        y = top + CAP * size
        p.text(x, y, act.upper(), 'SoraEB', size, track=ACT_TRACK)
        boxes[act] = pymupdf.Rect(x, top, x + p.width(act.upper(), 'SoraEB', size, ACT_TRACK), y)
        if defect == 'co_headliner' and act == 'The Blue Hour':
            y += 10 + CAP * size
            p.text(x, y, support.upper(), 'SoraEB', size, track=ACT_TRACK)
        else:
            y += 22
            p.text(x, y, f'with {support}', 'ArchivoNarrowR', 14)
        y += 18
        p.text(x, y, f'DOORS {door} / SETS {set_}', 'ArchivoNarrowSB', 12, track=FINE_TRACK)
        y += gap
    return boxes, y


def poster(path: Path, fonts, direction, marks, work: Path, defect: str | None = None, draft=False, merch: Path | None = None):
    """One A2 direction. draft=True draws the earlier round of that direction (shown by the bad2 deck only)."""
    doc = pymupdf.open()
    p = Page(doc, fonts, A2)
    w = A2[0]
    order = list(NIGHTS)
    if defect == 'order':
        order[0], order[1] = order[1], order[0]
    if direction == 'type-led':
        if draft:   # the title on one line, no wordmarks yet
            p.text(80, 200, SERIES, 'SoraEB', 140, track=ACT_TRACK)
            billing(p, 80, 300, order, 56, defect, gap=46)
        else:
            p.text(80, 220, 'UMBRA /', 'SoraEB', 180, track=ACT_TRACK)
            p.text(80, 368, 'LOFT', 'SoraEB', 180, track=ACT_TRACK)
            boxes, _ = billing(p, 80, 440, order, 72, defect, gap=40)
            for act, box in boxes.items():
                if act in marks:
                    p.mark(marks[act], 800, (box.y0 + box.y1) / 2, 100)
    elif direction == 'image-led':
        photo = (treated(SOURCES / 'umbra_archive_night_03.jpg', work / 'draft_photo.jpg', (2480, 958), 0.4, (PITCH, COLD))
                 if draft else treated(SOURCES / 'umbra_archive_night_01.jpg', work / 'photo.jpg', (2480, 958), 0.27))
        p.page.insert_image(pymupdf.Rect(0, 0, w, 460), filename=str(photo))
        if merch:
            p.page.insert_image(pymupdf.Rect(760, 40, 1150, 333), filename=str(merch))
        p.text(80, 570, SERIES, 'SoraEB', 104, track=ACT_TRACK)
        boxes, _ = billing(p, 80, 615, order, 60, defect, gap=20)
        for act, box in boxes.items():
            if act in marks:
                p.mark(marks[act], 720, (box.y0 + box.y1) / 2, 84)
    else:
        left = draft   # the earlier round had the panel on the left
        x = 470 if left else 80
        p.text(80, 200, SERIES, 'SoraEB', 130, track=ACT_TRACK)
        p.page.draw_line((80, 236), (w - 80, 236), color=rgb(SODIUM), width=1.5)
        panel = pymupdf.Rect(0, 262, 410, 1560) if left else pymupdf.Rect(700, 262, w, 1560)
        p.page.draw_rect(panel, color=None, fill=rgb(ASH))
        boxes, _ = billing(p, x, 300, order, 64, defect, gap=40)
        for act, box in boxes.items():
            mid = (box.y0 + box.y1) / 2
            if not left:
                p.page.draw_line((box.x1 + 24, mid), (panel.x0, mid), color=rgb(SODIUM), width=1.5)
            if act in marks:
                window = pymupdf.Rect(panel.x0 + 30, mid - 62, min(panel.x1, w) - 30, mid + 62)
                p.page.draw_rect(window, color=None, fill=rgb(PITCH))
                mw, mh = Image.open(marks[act]).size
                p.mark(marks[act], (window.x0 + window.x1) / 2 - 46 * mw / mh, mid, 92)
    caps = (lambda s: s) if defect == 'licence_case' else str.upper
    p.text(80, 1626, caps(LICENCE), 'ArchivoNarrowR', 9, track=FINE_TRACK)
    p.text(80, 1639, ACCESS.upper(), 'ArchivoNarrowR', 9, track=FINE_TRACK)
    doc.save(path, garbage=3, deflate=True)


def deck(path: Path, fonts, shown, marks, defect: str | None = None):
    """Six 16:9 pages: cover, series identity, the nine nights, three directions, the release-post direction, the room."""
    doc = pymupdf.open()
    p = Page(doc, fonts, DECK)
    p.text(60, 250, SERIES, 'SoraEB', 96, track=ACT_TRACK)
    p.page.draw_line((60, 284), (440, 284), color=rgb(SODIUM), width=1.5)
    p.text(60, 322, 'AUTUMN AFTER-DARK SERIES', 'ArchivoNarrowR', 22, track=FINE_TRACK)
    p.text(60, 352, 'Downstairs, after dark.', 'ArchivoNarrowR', 18)
    p.text(60, 470, 'Three poster directions, nine release posts, one room.', 'ArchivoNarrowR', 18)

    p = Page(doc, fonts, DECK)
    p.text(60, 72, 'THE SERIES IDENTITY', 'SoraEB', 28, track=ACT_TRACK)
    for i, line in enumerate(['Nine nights, one series, made downstairs in the room.',
                              'Act names Bone White on Pitch, the date above them in Sodium.',
                              'Sora ExtraBold sets names and dates; Archivo Narrow the billing.',
                              'Supplied wordmarks sit beside the typeset name, not in its place:',
                              'ink recoloured to Bone White, letter shapes unchanged.']):
        p.text(60, 110 + i * 25, line, 'ArchivoNarrowR', 18)
    for i, (act, date) in enumerate([('Sable Quartet', '2026-09-25'), ('Meridian Brass', '2026-09-26')]):
        y = 280 + i * 130
        p.text(60, y, day_line(date), 'SoraEB', 16, SODIUM, DATE_TRACK)
        y += 8 + CAP * 36
        p.text(60, y, act.upper(), 'SoraEB', 36, track=ACT_TRACK)
        p.mark(marks[act], 440, y - CAP * 18, 104)

    p = Page(doc, fonts, DECK)
    p.text(60, 62, 'NINE NIGHTS', 'SoraEB', 28, track=ACT_TRACK)
    for i, (act, dates, support, door, set_, _) in enumerate(NIGHTS):
        x, y = (60, 500)[i // 4], 100 + (i % 4) * 108 + CAP * 14
        p.text(x, y, ' / '.join(day_line(d) for d in dates), 'SoraEB', 14, SODIUM, DATE_TRACK)
        y += 7 + CAP * 26
        p.text(x, y, act.upper(), 'SoraEB', 26, track=ACT_TRACK)
        p.text(x, y + 24, f'with {support}', 'ArchivoNarrowR', 18)
        p.text(x, y + 42, f'DOORS {door} / SETS {set_}', 'ArchivoNarrowSB', 11, track=FINE_TRACK)

    p = Page(doc, fonts, DECK)
    p.text(60, 58, 'THREE DIRECTIONS', 'SoraEB', 28, track=ACT_TRACK)
    for i, (direction, note) in enumerate(zip(DIRECTIONS, ['The title stack and the act names carry it.',
                                                           'One archive night in Pitch and Sodium, grained.',
                                                           'An Ash panel, Sodium rules leading into it.'])):
        x = 60 + i * 300
        frame = pymupdf.Rect(x, 80, x + 360 / 2 ** 0.5, 440)
        p.page.draw_rect(frame + (-6, -6, 6, 6), color=None, fill=rgb(ASH))
        p.page.insert_image(frame, filename=str(shown[direction]))
        p.text(x, 466, direction.upper(), 'SoraEB', 14, track=ACT_TRACK)
        p.text(x, 488, note, 'ArchivoNarrowR', 13)

    p = Page(doc, fonts, DECK)
    p.text(60, 72, 'RELEASE POSTS', 'SoraEB', 28, track=ACT_TRACK)
    p.text(60, 110, 'The nine release posts adapt the Type-led direction.', 'ArchivoNarrowR', 18)
    for i, line in enumerate(['On a phone late at night it reads first: the act, then the date.',
                              'Type carries the series where six lighting rigs never match.',
                              'Every post keeps its date in Sodium directly above the act.']):
        p.text(60, 160 + i * 25, line, 'ArchivoNarrowR', 18)
    frame = pymupdf.Rect(600, 50, 600 + 440 / 2 ** 0.5, 490)
    p.page.draw_rect(frame + (-6, -6, 6, 6), color=None, fill=rgb(ASH))
    p.page.insert_image(frame, filename=str(shown['type-led']))

    p = Page(doc, fonts, DECK)
    p.text(60, 72, 'THE ROOM', 'SoraEB', 28, track=ACT_TRACK)
    p.text(60, 110, 'What promoters ask before they will talk.', 'ArchivoNarrowR', 18)
    rows = ['Capacity: 250 standing', 'Seated cabaret capacity: 120', 'Season-average attendance: 183 of 250',
            'Season-average occupancy: 73%']
    if defect == 'capacity':
        rows[0] = 'Capacity: 300 standing'
    for i, row in enumerate(rows):
        p.text(60, 300 + i * 32, row, 'ArchivoNarrowR', 20)
    # the draw chart: Cold Signal bars from zero on an Ash panel, each month and value labelled (well under 5% of the page)
    p.page.draw_rect(pymupdf.Rect(470, 50, 900, 490), color=None, fill=rgb(ASH))
    p.text(492, 84, 'LAST SEASON: AVERAGE DRAW BY MONTH', 'ArchivoNarrowR', 14, track=FINE_TRACK)
    p.text(492, 104, 'Of 250 capacity; bars drawn from zero.', 'ArchivoNarrowR', 13)
    base = 440
    for i, (month, value) in enumerate(DRAW):
        cx = 520 + i * 66
        p.page.draw_rect(pymupdf.Rect(cx - 8, base - value, cx + 8, base), color=None, fill=rgb(COLD))
        for label, y in ((str(value), base - value - 8), (month, base + 20)):
            p.text(cx - p.width(label, 'ArchivoNarrowR', 14) / 2, y, label, 'ArchivoNarrowR', 14)
    p.page.draw_line((496, base), (874, base), color=rgb(COLD), width=0.75)
    doc.save(path, garbage=3, deflate=True)


def release_post(path: Path, fonts, act, date, support, door, set_, price, defect: str | None = None, mark: Path | None = None):
    """Drawn as a 1080 x 1350 px page and rasterised, as an image deliverable would be. The wordmark stays smaller
    than the act name, so the act name is still the largest text after the series title. Two OCR allowances (the
    checks read posts with Tesseract): the title is set untracked, and the date line has open word spaces, since a
    tracked title or a tight "FRI 25" or "4 OCT" in Sora ExtraBold reads below the confident-read threshold."""
    doc = pymupdf.open()
    p = Page(doc, fonts, POST)
    p.text(70, 150, SERIES, 'SoraEB', 96)
    weekday, day, month = day_line('2026-10-04' if defect == 'other_night' else date,
                                   {'weekday': 'SAT', 'weekday_fri': 'FRI'}.get(defect)).split()
    days = f'{weekday}   {day}  {month}'
    shift = 0
    if mark and defect != 'wordmark_for_name':
        mw, mh = Image.open(mark).size
        p.mark(mark, 70, 370 - 95 * mh / mw, 190 * mh / mw)
    if defect == 'date_below':
        p.text(70, 512, act.upper(), 'SoraEB', 76, track=ACT_TRACK)
        p.text(70, 570, days, 'SoraEB', 44, SODIUM, DATE_TRACK)
        shift = 56
    elif defect == 'wordmark_for_name':
        p.text(70, 440, days, 'SoraEB', 44, SODIUM, DATE_TRACK)
        mw, mh = Image.open(mark).size
        shift = p.mark(mark, 70, 456 + 160 * mh / mw, 320 * mh / mw).y1 - 512 + 16
    else:
        p.text(70, 440, days, 'SoraEB', 44, SODIUM, DATE_TRACK)
        p.text(70, 512, act.upper(), 'SoraEB', 76, track=ACT_TRACK)
    p.text(70, 584 + shift, f'with {support}', 'ArchivoNarrowR', 34)
    door_text = door.replace(' ', '&nbsp;') if defect == 'nbsp' else door
    p.text(70, 680 + shift, f'DOORS {door_text}', 'ArchivoNarrowSB', 34, track=FINE_TRACK)
    p.text(70, 730 + shift, f'SETS {set_}', 'ArchivoNarrowR', 34, track=FINE_TRACK)
    advance = f'ADVANCE {"$99" if defect == "price" else price}'
    x, y = 70, 810 + shift
    if defect == 'price_cut_right':   # the last figure half outside the frame
        x = POST[0] + p.width(advance[-1], 'ArchivoNarrowR', 34) / 2 - p.width(advance, 'ArchivoNarrowR', 34, FINE_TRACK)
    elif defect == 'price_cut_bottom':
        y = POST[1] + 9
    p.text(x, y, advance, 'ArchivoNarrowR', 34, track=FINE_TRACK)
    p.wrap(70, 1200, LICENCE.upper(), 'ArchivoNarrowR', 22, 940, leading=1.36, track=FINE_TRACK)
    pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(1, 1), alpha=False)
    pix.save(path)


def main():
    out = Path(sys.argv[1])
    tmp = out / '_fonts'
    tmp.mkdir(parents=True, exist_ok=True)
    work = out / '_work'
    work.mkdir(exist_ok=True)
    fonts = {'SoraEB': static_font(FONTS / 'sora/Sora[wght].ttf', 'Sora', 'ExtraBold', 800, tmp),
             'ArchivoNarrowSB': static_font(FONTS / 'archivonarrow/ArchivoNarrow[wght].ttf', 'Archivo Narrow', 'SemiBold', 600, tmp),
             'ArchivoNarrowR': static_font(FONTS / 'archivonarrow/ArchivoNarrow[wght].ttf', 'Archivo Narrow', 'Regular', 400, tmp)}
    marks = {act: bone_wordmark(name, work / name.replace('_transparent', '_bone')) for act, name in WORDMARKS.items()}
    spec = json.loads((ROOT / 'docs/gatsby-v7/tasks/LAYOUT-12/TASK_SPEC.json').read_text())
    for kind in ('good', 'bad', 'bad2'):
        root = out / kind / 'LAYOUT-12'
        d = root / 'deliverables'
        d.mkdir(parents=True, exist_ok=True)
        planted = BAD if kind == 'bad' else {k: v[0] for k, v in BAD2.items()} if kind == 'bad2' else {}
        for direction in DIRECTIONS:
            oid = f'poster-direction-{direction}'
            merch = SOURCES / 'umbra_wordmark_sable.jpg' if kind == 'bad' and direction == 'image-led' else None
            poster(d / f'{oid}.pdf', fonts, direction, marks, work, planted.get(oid), merch=merch)
        # the deck shows renders of this set's delivered posters (bad2: renders of earlier drafts)
        shown = {}
        for direction in DIRECTIONS:
            src = d / f'poster-direction-{direction}.pdf'
            if planted.get('promoter-deck') == 'drafts':
                src = work / f'draft-{direction}.pdf'
                poster(src, fonts, direction, {} if direction == 'type-led' else marks, work, draft=True)
            shown[direction] = render(src, work / f'{kind}-{direction}.jpg')
        deck(d / 'promoter-deck.pdf', fonts, shown, marks, planted.get('promoter-deck'))
        for o in spec['deliverables']:
            v = (o.get('source_record') or {}).get('values')
            if not v:
                continue
            defect = planted.get(o['output_id'])
            mark = marks['Sable Quartet'] if defect == 'other_mark' else marks.get(v['headline'])
            release_post(root / o['path'], fonts, v['headline'], v['date'], v['support'],
                         v['door'].replace('&nbsp;', ' '), v['set'], v['price'], defect, mark)
    defects = {k: v for k, v in BAD.items() if k.startswith('release-post')}
    defects.update({'poster-direction-type-led': 'weekday', 'poster-direction-image-led': 'licence_case+merch',
                    'poster-direction-graphic-led': 'order', 'promoter-deck': 'capacity'})
    (out / 'defects.json').write_text(json.dumps(defects, indent=1) + '\n')
    (out / 'defects2.json').write_text(json.dumps({k: {'rules': v[1], 'defect': v[2]} for k, v in BAD2.items()},
                                                  indent=1, ensure_ascii=False) + '\n')
    print('made', out)


if __name__ == '__main__':
    main()
