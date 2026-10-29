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
opacity is made solid (alpha the files hold at 1% or less is dropped). The three poster directions are distinct
(type-led title stack; image-led archive photograph in a Pitch and Sodium two-colour and grain treatment; graphic-led
Ash panel with Sodium leader rules), each with the compact UMBRA / LOFT stack (baselines 148/180 of the size apart).
The six-page deck shows renders of the three delivered posters, names the Image-led direction as the one the posts
adapt, and charts last season's draw by month, every value labelled. Each release post adapts the Image-led
direction: an archive night (01, 03 or 04, never the smeared 06 or the clipped 02 and 05) cropped, never extended,
across the top in the same Pitch and Sodium pair with grain, then the stack, the act block on solid Pitch, the door
and set times on one line, a body line and the licence wrapped under 65 characters a line. The poster licence and
access lines stay one line each: the round-1 checks read each as one line of fine print (not body or billing).

The bad set breaks one round-1 rule per deliverable (defects.json). The bad2 set starts from the correct set and
plants round-2 defects, at most one per file, listed with every round-2 rule they break in defects2.json. The bad3 set
does the same with round-3 defects (colour roles, grounds, scrims, photo treatment, stacks, sizes, line lengths), every
rule each breaks listed in defects3.json (merged with the other generator's keys).

Usage: python make_layout12_files.py <out dir>
       (writes <out>/{good,bad,bad2,bad3}/LAYOUT-12/..., defects.json, defects2.json, defects3.json)
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
LEAD = 148 / 180                                    # the series-title stack: 180 pt on 148 pt
BODY = 'Nine nights, one series, downstairs under the mill.'     # type system step 03 sample, release-post body
# each post's archive night, cropped from the supplied frame: (file, crop top, crop left, crop width as a share)
POST_PHOTOS = {'release-post-r002': ('umbra_archive_night_01.jpg', 0.12, 0.0, 1.0),
               'release-post-r003': ('umbra_archive_night_03.jpg', 0.30, 0.0, 1.0),
               'release-post-r004': ('umbra_archive_night_04.jpg', 0.30, 0.0, 1.0),
               'release-post-r005': ('umbra_archive_night_01.jpg', 0.20, 0.55, 0.62),
               'release-post-r006': ('umbra_archive_night_03.jpg', 0.45, 0.45, 0.62),
               'release-post-r007': ('umbra_archive_night_04.jpg', 0.25, 0.0, 0.62),
               'release-post-r008': ('umbra_archive_night_01.jpg', 0.05, 0.25, 0.8),
               'release-post-r009': ('umbra_archive_night_03.jpg', 0.35, 0.25, 0.8),
               'release-post-r010': ('umbra_archive_night_04.jpg', 0.45, 1.0, 0.62)}
POST_PHOTO = (1080, 400)                            # the photograph across the top of each post, in px

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
# round-3 defects: deliverable -> (defect, every rule it breaks, description), one per file
BAD3 = {
    'poster-direction-type-led': ('flat_headliners', ['R177'],
                                  'Sable Quartet, Meridian Brass and Night Ferry are set at 48 pt like the remaining '
                                  'acts, not larger'),
    'poster-direction-image-led': ('scrim', ['R166', 'R148'],
                                   'a Pitch scrim at 45% opacity is laid over the lower half of the photograph'),
    'poster-direction-graphic-led': ('marks_on_ash', ['R108', 'R109'],
                                     'both wordmarks sit straight on the Ash panel, with no Pitch ground under them'),
    'promoter-deck': ('long_lines', ['R114'],
                      'the identity page sets its body copy in three lines of 86 to 103 characters'),
    'release-post-r002': ('act_sodium', ['R082'], 'the act name SABLE QUARTET is set in Sodium, not Bone White'),
    'release-post-r003': ('mark_sodium', ['R095'], 'the Meridian Brass wordmark is inked in Sodium, not Bone White'),
    'release-post-r004': ('full_colour', ['R081', 'R104'],
                          'the archive photograph is left in full colour, not in the Pitch and Sodium pair of the '
                          'other posts'),
    'release-post-r005': ('gradient_scrim', ['R166', 'R084'],
                          'a Pitch gradient scrim (clear to 70%) darkens the lower half of the photograph'),
    'release-post-r006': ('ash_block', ['R107'], 'the date line and act name sit on an Ash panel, not on Pitch'),
    'release-post-r007': ('one_line_title', ['R156'], 'the series title runs on one line, UMBRA / LOFT, not as a stack'),
    'release-post-r008': ('date_bone', ['R102'], 'the date line is Bone White, not Sodium'),
    'release-post-r009': ('blood_panel', ['R079', 'R080', 'R093'],
                          'a Blood panel (about 12% of the designed area) sits behind the door and price lines'),
    'release-post-r010': ('long_body', ['R131'], 'the body line runs to 74 characters on one line'),
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


def bone_wordmark(name: str, out: Path, colour=BONE) -> Path:
    """A supplied production wordmark recoloured for Pitch grounds and cropped to its ink: every pixel takes Bone
    White, the alpha channel (letter shapes, edge anti-aliasing) is kept, ink held at 94-99% opacity is made solid and
    the faint specks the files hold at 1% or less (no visible ink) are dropped."""
    a = np.asarray(Image.open(UPLOAD / name).convert('RGBA'))
    alpha = a[..., 3].copy()
    alpha[alpha <= 3] = 0
    ys, xs = np.nonzero(alpha)
    alpha[alpha >= 240] = 255
    ink = np.zeros_like(a)
    ink[..., :3] = rgb255(colour)
    ink[..., 3] = alpha
    Image.fromarray(ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]).save(out)
    return out


def treated(src: Path, out: Path, size, top: float, pair=(PITCH, SODIUM), seed=1, left=0.0, share=1.0) -> Path:
    """An archive photograph in the series two-colour and grain treatment: cropped (never stretched, never past the
    frame's edges) to the placement's proportions from a share of the frame's width, luminance mapped from the dark
    palette colour to the light one, with fine grain. pair=None keeps the crop in full colour (a defect)."""
    im = Image.open(src)
    cw = round(im.width * share)
    crop = round(cw * size[1] / size[0])
    x0, y0 = round((im.width - cw) * left), round((im.height - crop) * top)
    box = (x0, y0, x0 + cw, y0 + crop)
    if pair is None:
        im.convert('RGB').crop(box).resize(size, Image.LANCZOS).save(out, quality=90)
        return out
    a = np.asarray(im.convert('L').crop(box).resize(size, Image.LANCZOS), float)
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

    def wrap(self, x, y, text, font, size, width, colour=BONE, leading=1.3, track=0, max_chars=65):
        line = ''
        for word in text.split():
            trial = (line + ' ' + word).strip()
            if (self.width(trial, font, size, track) > width or len(trial) > max_chars) and line:
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

    def stack(self, x, y, size, track=ACT_TRACK, first='UMBRA /'):
        """The compact series-title stack, UMBRA / over LOFT, baselines 148/180 of the size apart. Returns the
        second baseline."""
        self.text(x, y, first, 'SoraEB', size, track=track)
        self.text(x, y + LEAD * size, 'LOFT', 'SoraEB', size, track=track)
        return y + LEAD * size


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
        # round 4 (bad4): the door lines set tighter than the untracked support acts
        p.text(x, y, f'DOORS {door} / SETS {set_}', 'ArchivoNarrowSB', 12, track=-30 if defect == 'tight_doors' else FINE_TRACK)
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
            p.stack(80, 220, 180)
            # round 3: the headliners left at the remaining acts' 48 pt
            boxes, _ = billing(p, 80, 440, order, 48 if defect == 'flat_headliners' else 72, defect, gap=40)
            for act, box in boxes.items():
                if act in marks:
                    p.mark(marks[act], 800, (box.y0 + box.y1) / 2, 100)
    elif direction == 'image-led':
        photo = (treated(SOURCES / 'umbra_archive_night_03.jpg', work / 'draft_photo.jpg', (2480, 958), 0.4, (PITCH, COLD))
                 if draft else treated(SOURCES / 'umbra_archive_night_01.jpg', work / 'photo.jpg', (2480, 958), 0.27))
        p.page.insert_image(pymupdf.Rect(0, 0, w, 460), filename=str(photo))
        if merch:
            p.page.insert_image(pymupdf.Rect(760, 40, 1150, 333), filename=str(merch))
        if defect == 'scrim':   # round 3: a translucent Pitch scrim over the lower half of the photograph
            p.page.draw_rect(pymupdf.Rect(0, 230, w, 460), color=None, fill=rgb(PITCH), fill_opacity=0.45)
        if draft:   # the title on one line
            p.text(80, 570, SERIES, 'SoraEB', 104, track=ACT_TRACK)
            boxes, _ = billing(p, 80, 615, order, 60, defect, gap=20)
        else:
            boxes, _ = billing(p, 80, p.stack(80, 556, 104) + 30, order, 60, defect, gap=14)
        for act, box in boxes.items():
            if act in marks:
                p.mark(marks[act], 720, (box.y0 + box.y1) / 2, 84)
    else:
        left = draft   # the earlier round had the panel on the left and the title on one line
        x = 470 if left else 80
        if left:
            p.text(80, 200, SERIES, 'SoraEB', 130, track=ACT_TRACK)
        rule = 236 if left else p.stack(80, 178, 130) + 27
        p.page.draw_line((80, rule), (w - 80, rule), color=rgb(SODIUM), width=1.5)
        panel = pymupdf.Rect(0, rule + 26, 410, 1560) if left else pymupdf.Rect(700, rule + 26, w, 1560)
        p.page.draw_rect(panel, color=None, fill=rgb(ASH))
        boxes, _ = billing(p, x, rule + 64, order, 64, defect, gap=40)
        for act, box in boxes.items():
            mid = (box.y0 + box.y1) / 2
            if not left:
                p.page.draw_line((box.x1 + 24, mid), (panel.x0, mid), color=rgb(SODIUM), width=1.5)
            if act in marks:
                window = pymupdf.Rect(panel.x0 + 30, mid - 62, min(panel.x1, w) - 30, mid + 62)
                if defect != 'marks_on_ash':   # round 3: no Pitch ground under the wordmarks
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
    lines = ['Nine nights, one series, made downstairs in the room.',
             'Act names Bone White on Pitch, the date above them in Sodium.',
             'Sora ExtraBold sets names and dates; Archivo Narrow the billing.',
             'Supplied wordmarks sit beside the typeset name, not in its place:',
             'ink recoloured to Bone White, letter shapes unchanged.']
    if defect == 'long_lines':   # round 3: the same copy run on in three long lines
        lines = ['Nine nights, one series, made downstairs in the room, act names Bone White on Pitch with',
                 'the date above them in Sodium; Sora ExtraBold sets names and dates, Archivo Narrow the billing.',
                 'Supplied wordmarks sit beside the typeset name, not in its place, their ink recoloured to Bone.']
    for i, line in enumerate(lines):
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
        # round 4 (bad4): the door lines set tighter than the untracked body text
        p.text(x, y + 42, f'DOORS {door} / SETS {set_}', 'ArchivoNarrowSB', 11, track=-30 if defect == 'tight_doors' else FINE_TRACK)

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
    p.text(60, 110, 'The nine release posts adapt the Image-led direction.', 'ArchivoNarrowR', 18)
    for i, line in enumerate(['One archive night runs across the top, in Pitch and Sodium.',
                              'One pair on all nine, so six lighting rigs read as one series.',
                              'Below it the act block reads first on a phone late at night.',
                              'Every post keeps its date in Sodium directly above the act.']):
        p.text(60, 160 + i * 25, line, 'ArchivoNarrowR', 18)
    frame = pymupdf.Rect(600, 50, 600 + 440 / 2 ** 0.5, 490)
    p.page.draw_rect(frame + (-6, -6, 6, 6), color=None, fill=rgb(ASH))
    p.page.insert_image(frame, filename=str(shown['image-led']))

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


def release_post(path: Path, fonts, act, date, support, door, set_, price, defect: str | None = None,
                 mark: Path | None = None, photo=None, work: Path | None = None, seed=1):
    """Drawn as a 1080 x 1350 px page and rasterised, as an image deliverable would be. The Image-led direction
    adapted: the archive night across the top (photo: its file and crop, in POST_PHOTOS), the title stack, the
    wordmark where the act has one, then the act block on solid Pitch. The wordmark stays smaller than the act name,
    so the act name is still the largest text after the series title. Two OCR allowances (the checks read posts with
    Tesseract): the title is set untracked, and the date line has open word spaces, since a tracked title or a tight
    "FRI 25" or "4 OCT" in Sora ExtraBold reads below the confident-read threshold."""
    doc = pymupdf.open()
    p = Page(doc, fonts, POST)
    file, top, left, share = photo
    img = treated(SOURCES / file, work / f'{path.stem}-{defect or "good"}.png', POST_PHOTO, top,
                  None if defect == 'full_colour' else (PITCH, SODIUM), seed, left, share)
    if defect == 'gradient_scrim':   # round 3: a Pitch scrim, clear at mid-height, 70% at the photo's foot
        a = np.asarray(Image.open(img).convert('RGB'), float)
        k = np.clip((np.arange(a.shape[0]) / a.shape[0] - 0.5) / 0.5, 0, 1)[:, None, None] * 0.7
        Image.fromarray((a * (1 - k) + np.array(rgb255(PITCH)) * k).round().astype(np.uint8)).save(img)
    p.page.insert_image(pymupdf.Rect(0, 0, POST[0], POST_PHOTO[1] * POST[0] / POST_PHOTO[0]), filename=str(img))
    if defect == 'one_line_title':   # round 3: no stack
        p.text(70, 520, SERIES, 'SoraEB', 96)
    else:
        p.stack(70, 520, 96, track=0, first='UMBRA')     # the stack itself marks the break the slash stands for
    weekday, day, month = day_line('2026-10-04' if defect == 'other_night' else date,
                                   {'weekday': 'SAT', 'weekday_fri': 'FRI'}.get(defect)).split()
    days = f'{weekday}   {day}  {month}'
    date_y, act_y, shift = 808, 880, 0
    date_ink = BONE if defect == 'date_bone' else SODIUM
    if defect == 'ash_block':   # round 3: the act block on an Ash panel
        p.page.draw_rect(pymupdf.Rect(40, 750, 1040, 912), color=None, fill=rgb(ASH))
    if mark and defect != 'wordmark_for_name':
        mw, mh = Image.open(mark).size
        p.mark(mark, 70, 740 - 95 * mh / mw, 190 * mh / mw)
    if defect == 'date_below':
        p.text(70, 850, act.upper(), 'SoraEB', 76, track=ACT_TRACK)
        p.text(70, 908, days, 'SoraEB', 44, date_ink, DATE_TRACK)
        shift = 28
    elif defect == 'wordmark_for_name':
        p.text(70, 700, days, 'SoraEB', 44, date_ink, DATE_TRACK)
        mw, mh = Image.open(mark).size
        shift = p.mark(mark, 70, 716 + 160 * mh / mw, 320 * mh / mw).y1 - act_y + 16
    else:
        p.text(70, date_y, days, 'SoraEB', 44, date_ink, DATE_TRACK)
        p.text(70, act_y, act.upper(), 'SoraEB', 76, SODIUM if defect == 'act_sodium' else BONE, ACT_TRACK)
    if defect == 'blood_panel':   # round 3: an accent used as a panel
        p.page.draw_rect(pymupdf.Rect(40, 960 + shift, 1040, 1080 + shift), color=None, fill=rgb(BLOOD))
    p.text(70, 938 + shift, f'with {support}', 'ArchivoNarrowR', 34)
    door_text = door.replace(' ', '&nbsp;') if defect == 'nbsp' else door
    # round 4 (bad4): 'door_track<n>' sets the door line at n thousandths of an em, no more open than the support line
    door_track = int(defect[len('door_track'):]) if defect and defect.startswith('door_track') else FINE_TRACK
    p.text(70, 1000 + shift, f'DOORS {door_text}, SETS {set_}', 'ArchivoNarrowSB', 34, track=door_track)
    advance = f'ADVANCE {"$99" if defect == "price" else price}'
    x, y = 70, 1054 + shift
    if defect == 'price_cut_right':   # the last figure half outside the frame
        x = POST[0] + p.width(advance[-1], 'ArchivoNarrowR', 34) / 2 - p.width(advance, 'ArchivoNarrowR', 34, FINE_TRACK)
    elif defect == 'price_cut_bottom':
        y = POST[1] + 9
    p.text(x, y, advance, 'ArchivoNarrowR', 34, track=FINE_TRACK)
    body = BODY[:-1] + ', all of them after dark.' if defect == 'long_body' else BODY   # round 3: 74 characters
    p.text(70, 1114 + shift, body, 'ArchivoNarrowR', 28)
    p.wrap(70, 1210 + shift, LICENCE.upper(), 'ArchivoNarrowR', 22, 940, leading=30 / 22, track=FINE_TRACK,
           max_chars=60)
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
    sodium = bone_wordmark(WORDMARKS['Meridian Brass'], work / 'umbra_meridian_wordmark_sodium.png', SODIUM)
    spec = json.loads((ROOT / 'docs/gatsby-v7/tasks/LAYOUT-12/TASK_SPEC.json').read_text())
    for kind in ('good', 'bad', 'bad2', 'bad3'):
        root = out / kind / 'LAYOUT-12'
        d = root / 'deliverables'
        d.mkdir(parents=True, exist_ok=True)
        planted = (BAD if kind == 'bad' else {k: v[0] for k, v in BAD2.items()} if kind == 'bad2'
                   else {k: v[0] for k, v in BAD3.items()} if kind == 'bad3' else {})
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
            elif kind == 'bad' and direction == 'image-led':   # the deck keeps its own defect only: no merch shot
                src = work / 'bad-image-led-nomerch.pdf'
                poster(src, fonts, direction, marks, work, planted.get(f'poster-direction-{direction}'))
            shown[direction] = render(src, work / f'{kind}-{direction}.jpg')
        deck(d / 'promoter-deck.pdf', fonts, shown, marks, planted.get('promoter-deck'))
        for n, o in enumerate(spec['deliverables']):
            v = (o.get('source_record') or {}).get('values')
            if not v:
                continue
            defect = planted.get(o['output_id'])
            mark = (marks['Sable Quartet'] if defect == 'other_mark' else sodium if defect == 'mark_sodium'
                    else marks.get(v['headline']))
            release_post(root / o['path'], fonts, v['headline'], v['date'], v['support'],
                         v['door'].replace('&nbsp;', ' '), v['set'], v['price'], defect, mark,
                         POST_PHOTOS[o['output_id']], work, seed=10 + n)
    defects = {k: v for k, v in BAD.items() if k.startswith('release-post')}
    defects.update({'poster-direction-type-led': 'weekday', 'poster-direction-image-led': 'licence_case+merch',
                    'poster-direction-graphic-led': 'order', 'promoter-deck': 'capacity'})
    (out / 'defects.json').write_text(json.dumps(defects, indent=1) + '\n')
    (out / 'defects2.json').write_text(json.dumps({k: {'rules': v[1], 'defect': v[2]} for k, v in BAD2.items()},
                                                  indent=1, ensure_ascii=False) + '\n')
    # defects3.json is shared with make_vector_motion_files.py: replace this task's keys, keep the others
    path3 = out / 'defects3.json'
    defects3 = {k: v for k, v in (json.loads(path3.read_text()) if path3.is_file() else {}).items()
                if not k.startswith('LAYOUT-12/')}
    defects3.update({f'LAYOUT-12/{k}': {'rules': v[1], 'defect': v[2]} for k, v in BAD3.items()})
    path3.write_text(json.dumps(dict(sorted(defects3.items())), indent=1, ensure_ascii=False) + '\n')
    print('made', out)


if __name__ == '__main__':
    main()
