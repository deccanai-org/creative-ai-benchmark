#!/usr/bin/env python3
"""Decide which converted rules move to code, from the test results, and write moved_rules.json.

A converted rule moves when, across its test rows (the 2026-09-28 outputs, or made files for the three tasks no run
produced), the code gave no wrong answer and decided at least half of the rows itself. A wrong answer is a fail on a
row where the deliverable is right; known_true_fails lists every fail that was checked by hand and is a real defect.
Rules the code mostly sends back to a person stay with people for now: the automatic check exists, but on these
outputs it would not save review time.

Usage: python decide_moves.py <real results.json> <made good results.json> <made bad results.json> [<made bad2 results.json>
       [<made bad3 results.json> [<made bad4 results.json>]]] [--bad5 <made bad5 results.json>]
       [--planted <results.json>=<planted list.json> ...]
(bad2, bad3, bad4, bad5: the further broken sets, with the defects of PLANTED2, PLANTED3, PLANTED4 and PLANTED5;
--planted, repeatable: round 5's planted copies of real deliverables, one folder per helper, each with its own list
{"TASK/deliverable": {"rules": [...], "defect": "...", optional "checks": [...]}}; they test the round-5 rules only,
since earlier rounds never ran on them)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
MADE_TASKS = {'LAYOUT-12', 'VECTOR-04', 'MOTION-11'}
# fails confirmed by hand as real defects in the 2026-09-28 outputs (check ID -> what is wrong)
KNOWN_TRUE_FAILS = {
    'PHOTO-20/speaker-onepager/H040': 'talk titles are set in Times-Roman, not Inter Medium (read from the PDF fonts)',
    'PHOTO-24/dealer-launch/H052': 'reference names are set in Georgia; the PDF has no Cormorant Garamond at all',
    # round 2 (2026-10-28)
    'PHOTO-04/villa-collection/H035': 'house names are set in Georgia, not Cormorant Garamond Light',
    'PHOTO-04/villa-collection/H037': 'no oversized initial: the C of "Casa Verranza" is 26 pt, like the V',
    'PHOTO-04/villa-collection/H086': 'no oversized initial: the C of "Casa Oliveto" is 26 pt, like the O',
    'PHOTO-04/villa-collection/H087': 'no oversized initial: the C of "Casa Scogliera" is 26 pt, like the S',
    'PHOTO-20/talk-card-r007/H031': 'her name is repeated in Studio Slate #4C5560 on the Bone panel',
    **{f'PHOTO-20/talk-card-r00{n}/H050': 'the AV monogram is drawn 17.1 mm wide, under 18 mm' for n in range(2, 10)},
    'PHOTO-24/dealer-launch/H037': 'the timing line is set in Helvetica, not Inter Regular',
    'PHOTO-24/dealer-launch/H071': 'the wordmark is set in Georgia, not Cormorant Garamond Medium',
    'PHOTO-24/watch-keyvisual/H013': 'the stacked wordmark (36 px capitals) is smaller than MERIDIAN (44 px)',
    'PHOTO-24/watch-feature-r002/H062': 'the wordmark (21 px capitals) is smaller than the reference name (48 px)',
    'PHOTO-24/watch-feature-r003/H061': 'the wordmark (21 px capitals) is smaller than the reference name (48 px)',
    'PHOTO-24/watch-feature-r004/H061': 'the wordmark (21 px capitals) is smaller than the reference name (48 px)',
    'PHOTO-24/watch-feature-r005/H061': 'the wordmark (21 px capitals) is smaller than the reference name (48 px)',
    'PHOTO-24/watch-feature-r006/H060': 'the wordmark (21 px capitals) is smaller than the reference name (48 px)',
    'PHOTO-26/wholesale-presentation/H052': 'SKU lines are Soft Clay type on Warm Paper Ground, not a running foot',
    'PHOTO-26/wholesale-presentation/H028': 'prices, dimensions and care lines are set in Helvetica and Helvetica-Bold',
    'PHOTO-26/wholesale-presentation/H049': 'prices are 17 pt and dimensions 11 pt, not 8.5 pt',
    'PHOTO-26/wholesale-presentation/H011': 'every price (17 pt) is set larger than its product name (13 pt)',
}
# round 3 (2026-10-28): the fails checked by hand, kept in a file of their own (check ID -> what is wrong)
for _name in ('known_true_fails_r3.json', 'known_true_fails_r4.json', 'known_true_fails_r5.json'):   # rounds 3 to 5, a file each
    if (HERE / _name).is_file():
        KNOWN_TRUE_FAILS.update(json.loads((HERE / _name).read_text()))
# defects planted in the made "bad" files: (deliverable, rule) pairs where a fail is the expected answer
PLANTED = {
    'LAYOUT-12': {('poster-direction-type-led', 'R003'), ('poster-direction-type-led', 'R004'),   # SAT 16 OCT for Koa
                  ('release-post-r009', 'R003'), ('release-post-r009', 'R015'),
                  ('poster-direction-image-led', 'R132'),                                       # licence line not in capitals
                  ('poster-direction-image-led', 'R067'),                                       # merchandise photo placed
                  ('poster-direction-graphic-led', 'R001'),                                     # acts out of billing order
                  ('release-post-r002', 'R014'),                                                # $99 advance price
                  ('release-post-r007', 'R060'),                                                # &nbsp; in the door time
                  ('promoter-deck', 'R018')},                                                   # 300 standing (round-2 rule, same defect)
    'VECTOR-04': {('recovered-sticker-window-mark', 'R054'),                                     # red set through a CSS class
                  ('recovered-sticker-bag-design-1', 'R079'),                                    # Ink Black over 5%
                  ('new-sticker-companion-1', 'R031'), ('sticker-proof-companion-1', 'R031'), ('gang-sheet', 'R031')},
    'MOTION-11': {('thumbnail-everyone-off-the-platform', 'R002'), ('thumbnail-everyone-off-the-platform', 'R019'),
                  ('thumbnail-everyone-off-the-platform', 'R118'),                              # title cut off at the edge
                  ('thumbnail-we-broke-the-map', 'R002'), ('thumbnail-we-broke-the-map', 'R118'),   # misspelt title
                  ('thumbnail-kitchen-gone', 'R118'),                                           # a caption larger than the title
                  ('channel-teaser', 'R009'), ('channel-teaser-vertical', 'R014'),              # changed upload line
                  ('channel-animation', 'R032')},                                               # STATIC FAX
}

# round 2: defects planted in the made "bad2" files (one per file, from the generators' defect lists): (deliverable,
# rule) pairs, or a check ID where the rule has a row per act and only one act's row is broken
PLANTED2 = {
    'LAYOUT-12': {'LAYOUT-12/poster-direction-type-led/H009',                                  # The Blue Hour billed FRI 2 OCT
                  'LAYOUT-12/poster-direction-image-led/H011',                                 # Coral Sound set as a headline,
                  ('poster-direction-image-led', 'R026'), ('poster-direction-image-led', 'R176'),  # no "with", at the act's size
                  ('poster-direction-graphic-led', 'R147'),                                    # date lines tracked tighter
                  ('promoter-deck', 'R020'), ('promoter-deck', 'R027'), ('promoter-deck', 'R028'),  # earlier drafts shown
                  ('release-post-r002', 'R032'), ('release-post-r002', 'R175'),                # wordmark in place of the name
                  ('release-post-r003', 'R033'),                                               # the Sable wordmark on Meridian's post
                  ('release-post-r004', 'R015'),                                               # SAT 2 OCT (a Friday)
                  ('release-post-r005', 'R059'), ('release-post-r005', 'R015'),                # SUN 4 OCT, the other night
                  ('release-post-r006', 'R161'),                                               # date line below the act
                  ('release-post-r007', 'R039'), ('release-post-r009', 'R039'),                # advance price cut off
                  ('release-post-r010', 'R015')},                                              # FRI 17 OCT (a Saturday)
    'VECTOR-04': {('recovered-sticker-window-mark', 'R016'),                                   # 70 mm
                  ('recovered-sticker-bag-design-1', 'R040'), ('recovered-sticker-bag-design-1', 'R068'),  # traced from other bags
                  ('recovered-sticker-bag-design-2', 'R033'), ('recovered-sticker-bag-design-2', 'R055'),
                  ('recovered-sticker-bag-design-3', 'R034'), ('recovered-sticker-bag-design-3', 'R056'),
                  ('sticker-proof-bag-design-3', 'R043'),                                      # halftone dots
                  ('new-sticker-companion-1', 'R090'),                                         # ampersand at cap height
                  ('new-sticker-companion-2', 'R019')},                                        # cut line drawn into the art
    'MOTION-11': {('thumbnail-do-not-open-that-door', 'R018'),                                 # title cut off
                  ('thumbnail-kitchen-gone', 'R033'),                                          # frame from the wrong capture
                  ('thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi', 'R033'),
                  ('channel-animation', 'R119')},                                              # a larger line on the end card
}


# round 3: defects planted in the made "bad3" files (one per file, from the generators' defects3 list): (deliverable, rule)
# pairs; a planted defect may also break a round-1 or round-2 rule, listed with it
PLANTED3 = {
    'LAYOUT-12': {
        ('poster-direction-graphic-led', 'R108'), ('poster-direction-graphic-led', 'R109'),   # both wordmarks sit straight on the Ash panel, with no Pitch ground under them
        ('poster-direction-image-led', 'R166'), ('poster-direction-image-led', 'R148'),   # a Pitch scrim at 45% opacity is laid over the lower half of the photograph
        ('poster-direction-type-led', 'R177'),   # Sable Quartet, Meridian Brass and Night Ferry are set at 48 pt like the remaining acts, no
        ('promoter-deck', 'R114'),   # the identity page sets its body copy in three lines of 86 to 103 characters
        ('release-post-r002', 'R082'),   # the act name SABLE QUARTET is set in Sodium, not Bone White
        ('release-post-r003', 'R095'),   # the Meridian Brass wordmark is inked in Sodium, not Bone White
        ('release-post-r004', 'R081'), ('release-post-r004', 'R104'),   # the archive photograph is left in full colour, not in the Pitch and Sodium pair of the oth
        ('release-post-r005', 'R166'), ('release-post-r005', 'R084'),   # a Pitch gradient scrim (clear to 70%) darkens the lower half of the photograph
        ('release-post-r006', 'R107'),   # the date line and act name sit on an Ash panel, not on Pitch
        ('release-post-r007', 'R156'),   # the series title runs on one line, UMBRA / LOFT, not as a stack
        ('release-post-r008', 'R102'),   # the date line is Bone White, not Sodium
        ('release-post-r009', 'R079'), ('release-post-r009', 'R080'), ('release-post-r009', 'R093'),   # a Blood panel (about 12% of the designed area) sits behind the door and price lines
        ('release-post-r010', 'R131'),   # the body line runs to 74 characters on one line
    },
    'VECTOR-04': {
        ('gang-sheet', 'R080'),   # the Bag design 1 sticker is left in RGB; everything else is CMYK
        ('new-sticker-companion-1', 'R089'),   # MERIDIAN & ASH is set flat on one straight baseline, not arched on the 40 degree curve
        ('new-sticker-companion-2', 'R070'),   # the price lines are set in Brick Red on the Warm Cream tile
        ('recovered-sticker-bag-design-1', 'R100'), ('recovered-sticker-bag-design-1', 'R045'), ('recovered-sticker-bag-design-1', 'R054'),   # a soft drop shadow (the moth again in Roast Brown at 40% opacity through a Gaussian blur f
        ('recovered-sticker-bag-design-2', 'R071'), ('recovered-sticker-bag-design-2', 'R100'), ('recovered-sticker-bag-design-2', 'R079'),   # an Ink Black copy of the cone sits 0.2 mm behind it as a hard offset shadow, a main shape 
        ('recovered-sticker-bag-design-3', 'R100'),   # the ridge line ink is set to the Multiply blend mode
        ('recovered-sticker-window-mark', 'R051'),   # the hairline ring is filled in as a solid Warm Cream disc behind the roundel, with no open
        ('sticker-cut-bag-design-1', 'R008'),   # the cut path is offset 2.5 mm with its corners left unrounded (inner corners sharp, outer 
        ('sticker-cut-bag-design-2', 'R009'),   # a second closed path cuts round an island inside the artwork
        ('sticker-cut-bag-design-3', 'R020'),   # the cut path's layer is named Layer 1, not CutContour
        ('sticker-cut-companion-1', 'R021'), ('sticker-cut-companion-1', 'R009'),   # the sticker artwork is copied into the CutContour layer beside the cut path
        ('sticker-cut-companion-2', 'R017'),   # the SVG declares no viewBox
        ('sticker-cut-window-mark', 'R007'),   # the cut path is offset 1.5 mm from the artwork, not 2.5 mm
        ('sticker-proof-bag-design-1', 'R018'), ('sticker-proof-bag-design-1', 'R057'), ('sticker-proof-bag-design-1', 'R001'),   # an opaque white rectangle fills the whole proof behind the sticker
        ('sticker-proof-bag-design-2', 'R101'), ('sticker-proof-bag-design-2', 'R001'),   # a soft, semi-transparent drop shadow is painted under the sticker
        ('sticker-proof-bag-design-3', 'R022'), ('sticker-proof-bag-design-3', 'R057'), ('sticker-proof-bag-design-3', 'R001'),   # the magenta cut line is drawn round the artwork
        ('sticker-proof-companion-1', 'R097'), ('sticker-proof-companion-1', 'R001'),   # the wordmark is set at 13 pt, its capitals about 88 px tall
        ('sticker-proof-companion-2', 'R074'), ('sticker-proof-companion-2', 'R062'), ('sticker-proof-companion-2', 'R001'),   # the price lines are set in Ink Black
        ('sticker-proof-window-mark', 'R076'), ('sticker-proof-window-mark', 'R001'),   # the ash leaf is Kraft, not Warm Cream, so the proof no longer matches the SVG
    },
    'MOTION-11': {
        ('channel-animation', 'R066'),   # STATIC and FOX carry no Jet Black outline on the end card
        ('channel-teaser', 'R028'),   # capture 02's shot is played twice and capture 06's dropped
        ('channel-teaser-vertical', 'R037'),   # the music is a synthesised loop, not staticfox_bed.wav
        ('thumbnail-do-not-open-that-door', 'R048'),   # Scrap stands over half of capture 04's webcam window
        ('thumbnail-everyone-off-the-platform', 'R078'), ('thumbnail-everyone-off-the-platform', 'R058'),   # a 45% Jet Black scrim darkens the capture below the title panel
        ('thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi', 'R086'), ('thumbnail-i-gave-my-team-one-simple-job-and-they-set-the-entire-base-on-fi', 'R098'),   # the payoff word FIRE is set in Anton at the setup size, not in Archivo Black
        ('thumbnail-kitchen-gone', 'R064'), ('thumbnail-kitchen-gone', 'R065'),   # the title panel is Acid Signal, not Static Purple
        ('thumbnail-we-broke-the-map', 'R055'),   # the payoff word MAP has no Jet Black outline
        ('thumbnail-we-spent-six-hours-building-a-bridge-and-then-drove-straight-pas', 'R082'), ('thumbnail-we-spent-six-hours-building-a-bridge-and-then-drove-straight-pas', 'R120'),   # the long title stack is set at 64 px, its setup capitals about 55 px tall
    },
}


# round 3: rules a planted defect also breaks, found in the final run and confirmed against the rule's wording and the
# generators (the correct file passes; the broken file differs only by its planted defect)
ALSO_BROKEN = {
    'made_bad': {'LAYOUT-12': {('release-post-r007', 'R145')},          # the &nbsp; shows lowercase "nbsp" in the door line
                 'MOTION-11': {('channel-animation', 'R107')},          # STATIC FAX: FOX is not on the last row
                 'VECTOR-04': {('gang-sheet', 'R063'),                  # the window mark's off-palette red, placed on the sheet
                               ('sticker-proof-window-mark', 'R057'),   # and shown on its proof
                               # "Ink Black over 5%" is drawn as a heavy Ink Black drop shadow behind the moth: a shadow and a
                               # backing shape (round 4)
                               ('recovered-sticker-bag-design-1', 'R100'), ('sticker-proof-bag-design-1', 'R101'),
                               ('sticker-proof-bag-design-1', 'R074')}},
    'made_bad2': {'LAYOUT-12': {('poster-direction-image-led', 'R116')},  # Coral Sound set as a headline in Sora ExtraBold
                  'MOTION-11': {('channel-animation', 'R089'),          # STATIC shrunk to 64 px to put SUBSCRIBE above it
                                ('channel-animation', 'R090')},         # SUBSCRIBE OR DAVE WINS set in Anton
                  'VECTOR-04': {('sticker-proof-bag-design-1', 'R001'), ('sticker-proof-bag-design-2', 'R001'),
                                ('sticker-proof-bag-design-3', 'R001'),  # proofs keep the original artwork (by design)
                                ('sticker-cut-bag-design-1', 'R009'), ('sticker-cut-bag-design-2', 'R009'),
                                ('sticker-cut-bag-design-3', 'R009'), ('sticker-cut-window-mark', 'R009'),  # cut paths too
                                ('sticker-cut-window-mark', 'R007'), ('sticker-cut-bag-design-1', 'R007'),  # (round 4)
                                ('sticker-proof-companion-1', 'R001'),   # the SVG's badge arc changed, the proof did not
                                ('new-sticker-companion-1', 'R086'),     # ampersand at cap height sits on the baseline
                                # round 5: a sticker traced from the wrong bag lacks the parts its own design names
                                ('recovered-sticker-bag-design-1', 'R046'),   # ridge line traced: no moth antennae or eye spots
                                ('recovered-sticker-bag-design-2', 'R042')}},  # moth traced: no cone, carafe or steam curl
    'made_bad3': {'VECTOR-04': {('sticker-proof-bag-design-2', 'R018'),  # the painted shadow shows through the open space
                                ('recovered-sticker-window-mark', 'R053')}},  # round 5: ring filled solid, so no thin ring shows
    # round 5's bad5 (vision-model plants, defects5.json): earlier rules a plant breaks when the rule is read literally
    'made_bad5': {'LAYOUT-12': {('poster-direction-image-led', 'R105'), ('poster-direction-image-led', 'R115'),
                                ('poster-direction-image-led', 'R135'),  # caption "Pictured: Sable Quartet ..." on the
                                ('promoter-deck', 'R106'), ('promoter-deck', 'R118'),  # photograph: an act name on a photo,
                                ('promoter-deck', 'R140'),               # in Archivo Narrow and not in capitals
                                ('promoter-deck', 'R126')},              # page 2 also gains a date line FRI 2 OCT in Archivo Narrow
                  'MOTION-11': {('channel-teaser-vertical', 'R012')},    # cut before its end card: no handle shown
                  'VECTOR-04': {('sticker-proof-window-mark', 'R001'), ('sticker-proof-bag-design-1', 'R001'),
                                ('sticker-proof-bag-design-2', 'R001'), ('sticker-proof-bag-design-3', 'R001'),  # proofs changed
                                ('sticker-cut-bag-design-1', 'R007'), ('sticker-cut-bag-design-2', 'R007'),
                                ('sticker-cut-bag-design-3', 'R007'), ('sticker-cut-window-mark', 'R007'),  # artwork grown or
                                ('recovered-sticker-bag-design-2', 'R016'), ('recovered-sticker-bag-design-2', 'R054'),  # cut
                                ('sticker-proof-bag-design-2', 'R018'), ('sticker-proof-bag-design-3', 'R018'),  # photo behind
                                ('sticker-proof-bag-design-3', 'R060'),  # the pour-over drawing in place of the ridge line
                                ('sticker-proof-window-mark', 'R101'), ('sticker-proof-bag-design-1', 'R101'),
                                ('sticker-proof-bag-design-2', 'R101')}},  # photographs on the proof: not flat ink
}

# settings that are limits chosen in code (tolerances, thresholds, definitions), as opposed to values the rule states
CHOSEN = {'tol', 'min_conf', 'min_cover', 'min_chars', 'max_de', 'max_scale', 'tol_pt', 'pass_em', 'fail_em', 'min_share',
          'min_tiles', 'max_rows', 'max_words', 'max_other_words', 'min_words', 'min_ncc', 'thickness', 'min_gap', 'thin_px',
          'small_px'} | {'fail_mm', 'px_mm', 'sigma_mm', 'turn_sigma_mm', 'turn_window_mm', 'max_turn_deg', 'max_shift_mm', 'min_iou', 'fail_iou', 'max_aspect', 'max_changed_share', 'max_opacity_share', 'max_share', 'cover', 'min_drop', 'max_iou', 'min_differ', 'tol_deg', 'fail_deg', 'pass_share', 'min_rise', 'ink_tol', 'ground_tol', 'fail_short', 'fail_drop', 'even_tol', 'min_run', 'rule_tol', 'max_gap', 'max_px', 'fail_px', 'pic_tol', 'aspect_tol', 'edge_tol', 'name_conf', 'pass_ratio', 'fail_ratio', 'photo_digit_max', 'ground_share', 'photo_area', 'ring_px', 'flat_ring', 'ink_min', 'min_px', 'flat_tol', 'max_text', 'max_rms', 'min_letters', 'touch_spread', 'frame_min', 'frame_fill', 'frame_top_max', 'min_shown', 'shadow_L', 'black_L', 'crushed_pass', 'crushed_fail', 'detail_pass', 'min_shadow_tiles', 'clip_level', 'clip_px', 'border_jump', 'border_min_L', 'edge_border_max', 'min_border_px', 'red_pass', 'red_fail', 'green_pass', 'green_fail', 'grain_pass', 'grain_fail', 'min_photo_share', 'block_colours', 'block_top', 'ink_cut', 'hole_min', 'hole_pass', 'hole_fail', 'aspect_pass', 'aspect_fail', 'fail_ncc', 'word_colour_tol', 'ink_std', 'win_s', 'quiet_db', 'pass_ncc', 'fail_share', 'match_tol', 'person_tol', 'min_change', 'span_ratio', 'move_px', 'grow', 'still_px', 'still_grow', 'still_levels', 'still_share', 'min_frames', 'pass_scale', 'fail_scale', 'min_inliers', 'pass_gain', 'max_offset', 'max_shift_share', 'fail_gain', 'fail_shift_share', 'fade_s', 'fail_hue_deg'}   # round 4


CHOSEN |= {'pass_tol', 'inset', 'min_piece', 'fail_piece', 'edge_ncc', 'absent_tol', 'stack_overlap', 'small', 'other_tol',
           'near'}   # round 5
# round 5: limits some round-5 code operations apply by default, without the setting written into each check
OP_DEFAULT_LIMITS = {
    'v2_keyline_only_r5c': {'inset': 2, 'min_piece': 12, 'fail_piece': 30, 'edge_ncc': 0.5},
    'v2_ground_absent_r5c': {'absent_tol': 12},
    'v2_cap_ratio_r5c': {'stack_overlap': 0.5, 'pass_tol': 0.15},
    'v2_small_labels_r5c': {'small': 0.025},
    'v2_named_colour_r5c': {'other_tol': 3},
}


def limits(a, found) -> set:
    """The limits a check decides by: its chosen settings and every pass_if / fail_if condition, as (name, cmp, value)."""
    if isinstance(a, dict):
        for k, v in OP_DEFAULT_LIMITS.get(a.get('op'), {}).items():
            if k not in a:
                found.add((k, '=', v))
        for k, v in a.items():
            if k.startswith('_') or isinstance(v, bool):
                continue
            if k in CHOSEN and isinstance(v, (int, float)):
                found.add((k, '=', v))
            elif k in ('pass_if', 'fail_if') and isinstance(v, list):
                for c in v:
                    if isinstance(c, list) and len(c) == 3 and isinstance(c[2], (int, float)):
                        found.add((f'{k[:-3]}:{c[0]}', c[1], c[2]))
            else:
                limits(v, found)
    elif isinstance(a, list):
        for v in a:
            limits(v, found)
    return found


# round 4: defects planted in the made "bad4" files (one per file), read from the generators' defects4 lists when they
# are written (tools/pilot13_v2_automation/defects4.json: {"TASK/deliverable": {"rules": [...], "defect": "..."}}); an
# entry with "checks" plants only those rows (a rule with a row per capture, where one capture carries the defect)
PLANTED4 = defaultdict(set)
if (HERE / 'defects4.json').is_file():
    for _key, _d in json.loads((HERE / 'defects4.json').read_text()).items():
        _task, _out = _key.split('/')
        PLANTED4[_task] |= set(_d['checks']) if _d.get('checks') else {(_out, _r) for _r in _d['rules']}


# round 5: defects planted in the made "bad5" files (defects5.json) and in planted copies of real deliverables (one
# list per helper, passed with --planted), both {"TASK/deliverable": {"rules": [...], "defect": "...", optional "checks"}}
def _planted_from(name):
    out = defaultdict(set)
    path = Path(name) if Path(name).is_absolute() else HERE / name
    if path.is_file():
        for _key, _d in json.loads(path.read_text()).items():
            _task, _out = _key.split('/')
            out[_task] |= set(_d['checks']) if _d.get('checks') else {(_out, _r) for _r in _d['rules']}
    return out


PLANTED5 = _planted_from('defects5.json')


def method_of(a) -> str:
    """'vision model' when any part of a check asks the vision model (round 5), else 'code'."""
    if isinstance(a, dict):
        op = str(a.get('op', ''))
        if op.startswith('vlm_') or op.endswith(('_r5v', '_r5va', '_r5vb', '_r5vc')):
            return 'vision model'
        return 'vision model' if any(method_of(v) == 'vision model' for v in a.values() if isinstance(v, (dict, list))) else 'code'
    if isinstance(a, list):
        return 'vision model' if any(method_of(v) == 'vision model' for v in a) else 'code'
    return 'code'


def is_planted(planted, task, output, rule, check_id) -> bool:
    entries = planted.get(task, set())
    return (output, rule) in entries or check_id in entries


def note(r) -> str:
    """A short plain reason for a fail or a person answer, from the operation's evidence."""
    ev = r.get('evidence') or {}
    if r['status'] == 'person':
        return str(ev.get('reason') or 'the code could not decide')
    if r['status'] != 'fail':
        return ''
    if str(r.get('op', '')).startswith('vlm_'):   # round 5: the vision model's answer, as code compared it
        for key, label in (('read', 'read'), ('not_allowed', 'read'), ('counted', 'counted'), ('found', 'found'),
                           ('forbidden_found', 'found'), ('required_missing', 'not found')):
            if key in ev:
                value = ev[key]
                value = '; '.join(map(str, value[:3])) if isinstance(value, list) else value
                return f'{label}: {value}'[:160]
        first = (ev.get('answers') or [{}])[0]
        return ('vision model: ' + str(first.get('evidence') or first.get('answer') or 'see the check log'))[:160]
    for key, label in (('missing', 'not found'), ('forbidden_found', 'found'), ('found', 'found'), ('wrong', 'wrong weekday'),
                       ('not_allowed', 'price not allowed'), ('outside_palette', 'colour outside the palette'),
                       ('rendered_outside_palette', 'colour outside the palette'), ('not_matching', 'set differently'),
                       ('larger', 'larger text'), ('below', 'resolution below the minimum'), ('line', 'line too long'),
                       ('not_larger', 'not set larger'), ('width_mm', 'measured width in mm'), ('ratio', 'size ratio'),
                       ('contradicting', 'contradicting term'), ('cut_off', 'cut off at the edge'), ('not_directly_above', 'not directly above'),
                       ('not_more_open', 'not letterspaced more openly'), ('graphics_state', 'drawn with'), ('wrong_name', 'another name beside the photo'),
                       ('not_in_full', 'name not given in full'), ('blank_pages', 'blank page'), ('cut_lines', 'cut line drawn into the artwork'),
                       ('main_ink', 'main ink'), ('artwork_mm', 'artwork size in mm'), ('one_line', 'set on one line'), ('different', 'different size'),
                       ('fonts', 'set in'), ('advance_widths_em', 'uneven figure widths'), ('problems', 'section layout'),
                       ('placements', 'placement'), ('pages', 'pages'), ('overlap', 'silhouette overlap'), ('inliers', 'frame matches'),
                       ('ratios', 'size ratios'), ('tiny_dots', 'tiny dots')):
        if key in ev:
            value = ev[key]
            if isinstance(value, list):
                value = '; '.join(' '.join(map(str, v)) if isinstance(v, list) else str(v) for v in value[:3])
            return f'{label}: {value}'[:160]
    if 'share_pct' in ev:
        return f'covers {ev["share_pct"]}%'
    if 'a' in ev and 'b' in ev:
        return f'sizes {ev["a"]} and {ev["b"]}'
    return 'see the automatic check log'


def main():
    real, good, bad = (json.loads(Path(p).read_text()) for p in sys.argv[1:4])
    bad2 = json.loads(Path(sys.argv[4]).read_text()) if len(sys.argv) > 4 else []
    bad3 = json.loads(Path(sys.argv[5]).read_text()) if len(sys.argv) > 5 else []
    args = sys.argv[1:]
    bad5, planted_sets = [], []
    while '--bad5' in args:
        i = args.index('--bad5')
        bad5 = json.loads(Path(args[i + 1]).read_text())
        del args[i:i + 2]
    while '--planted' in args:
        i = args.index('--planted')
        res, lst = args[i + 1].split('=')
        planted_sets.append((json.loads(Path(res).read_text()), _planted_from(lst)))
        del args[i:i + 2]
    sys.argv[1:] = args
    bad4 = json.loads(Path(sys.argv[6]).read_text()) if len(sys.argv) > 6 else []
    pilot = {r['check_id']: {'status': r['status'], 'note': note(r)} for r in real
             if r['task'] not in MADE_TASKS and r['status'] in ('pass', 'fail', 'person')}
    (HERE / 'pilot_results_2026-09-28.json').write_text(json.dumps(pilot, ensure_ascii=False, indent=1) + '\n')
    moved = {f.stem: json.loads(f.read_text())['moved'] for f in sorted((HERE / 'moved').glob('*.json'))}
    stats = defaultdict(lambda: {'real': Counter(), 'made_good': Counter(), 'made_bad': Counter(), 'made_bad2': Counter(),
                                 'made_bad3': Counter(), 'made_bad4': Counter(), 'made_bad5': Counter(), 'planted': Counter(),
                                 'wrong': []})
    sys.path.insert(0, str(HERE.parent / 'auto_verifier'))
    import objective_ops  # noqa: F401  (loads every round's operations first, so round 5's modules can import them)
    import round5
    sets = [('real', real, None), ('made_good', good, None), ('made_bad', bad, None), ('made_bad2', bad2, None),
            ('made_bad3', bad3, None), ('made_bad4', bad4, None), ('made_bad5', bad5, None)]
    sets += [('planted', res, lst) for res, lst in planted_sets]
    for name, results, own in sets:
        planted = own if own is not None else {'made_bad2': PLANTED2, 'made_bad3': PLANTED3, 'made_bad4': PLANTED4,
                                               'made_bad5': PLANTED5}.get(name, PLANTED)
        also = ALSO_BROKEN.get(name, {})
        planted = {t: planted.get(t, set()) | also.get(t, set()) for t in set(planted) | set(also)}
        for r in results:
            if name == 'real' and r['task'] in MADE_TASKS:
                continue
            if name == 'planted' and (r['task'], r['rule_id']) not in round5.R5:
                continue
            key = (r['task'], r['rule_id'])
            s = stats[key]
            s[name][r['status']] += 1
            output = r['check_id'].split('/')[1]
            hit = is_planted(planted, r['task'], output, r['rule_id'], r['check_id'])
            # a planted copy is the real file plus one defect, so it keeps the real file's confirmed defects
            carried = name == 'planted' and r['check_id'] in KNOWN_TRUE_FAILS
            if (name.startswith('made_bad') or name == 'planted') and r['status'] == 'pass' and hit:
                s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'passed a planted defect'})
            if r['status'] in ('error',):
                s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'operation error'})
            if r['status'] == 'fail':
                if name == 'real' and r['check_id'] not in KNOWN_TRUE_FAILS:
                    s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'fail not confirmed as a real defect'})
                if name == 'made_good':
                    s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'fail on a correct made file'})
                if (name.startswith('made_bad') or name == 'planted') and not hit and not carried:
                    s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'fail where no defect was planted'})
    decisions = {}
    for tid, rows in moved.items():
        rules = defaultdict(list)
        for m in rows:
            rules[m['rule_id']].append(m)
        out = {}
        for rid, members in sorted(rules.items()):
            s = stats[(tid, rid)]
            test = s['made_good'] if tid in MADE_TASKS else s['real']
            tested = sum(v for k, v in test.items() if k != 'no_output')
            decided = test['pass'] + test['fail']
            if s['wrong']:
                verdict, why = 'stays', 'a wrong answer in testing'
            elif not tested:
                verdict, why = 'stays', 'no test output for its deliverables'
            elif decided * 2 < tested:
                verdict, why = 'stays', f'the code decided only {decided} of {tested} test rows; the rest came back to a person'
            else:
                verdict, why = 'moves', f'the code decided {decided} of {tested} test rows with no wrong answer'
            out[rid] = {'verdict': verdict, 'why': why, 'checks': [m['check_id'] for m in members], 'k_id': members[0]['k_id'],
                        'method': 'vision model' if any(method_of(m['assertion']) == 'vision model' for m in members) else 'code',
                        'critical': members[0]['critical'], 'how': sorted({m['how'] for m in members}),
                        'limits': sorted(set().union(*(limits(m['assertion'], set()) for m in members)), key=str),
                        'test': {k: dict(s[k]) for k in ('real', 'made_good', 'made_bad', 'made_bad2', 'made_bad3', 'made_bad4',
                                                         'made_bad5', 'planted') if s[k]},
                        'wrong': s['wrong']}
        decisions[tid] = out
    (HERE / 'moved_rules.json').write_text(json.dumps(decisions, ensure_ascii=False, indent=1) + '\n')
    total = Counter()
    for tid, out in decisions.items():
        c = Counter(v['verdict'] for v in out.values())
        n = Counter()
        for v in out.values():
            n[v['verdict']] += len(v['checks'])
        total.update({f'{k}_rules': c[k] for k in c})
        total.update({f'{k}_checks': n[k] for k in n})
        print(f"{tid:10s} moves {c['moves']:3d} rules / {n['moves']:4d} checks; stays {c['stays']:3d} rules / {n['stays']:4d} checks")
    print('TOTAL', dict(total))


if __name__ == '__main__':
    main()
