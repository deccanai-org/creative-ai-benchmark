"""Round 4 conversions for MOTION-11 (STATIC FOX), 2026-10-28: the films' music, repeated shots, the captures a film
uses, the mascot's movement, capture footage enlarged past its recorded
pixels, and washes or recolouring over the footage. Operations in tools/auto_verifier/ops_r4_video.py (names end in _r4m).

One handler per (task, rule), taking (row, ctx) and returning an assertion, or None when the row cannot be checked
exactly; a rule moves only when every row converts. Every limit is a setting in the assertion and is described in
its op's docstring.
"""
from __future__ import annotations

TASK = 'MOTION-11'
SCRAP = 'staticfox_scrap_transparent.png'
BED = 'staticfox_bed.wav'


def const(a):
    return lambda row, ctx: dict(a)


def capture_number(row, ctx):
    v = (row.get('values') or {}).get('1', '')
    digits = ''.join(ch for ch in str(v) if ch.isdigit())
    return int(digits) if digits and 1 <= int(digits) <= 6 else None


def per_capture(a):
    def h(row, ctx):
        n = capture_number(row, ctx)
        return dict(a, capture=n) if n else None
    return h


SCALE = {'op': 'capture_scale_r4m', 'pass_scale': 1.05, 'fail_scale': 2.0, 'min_inliers': 30}


def title_of(row, ctx):
    """A thumbnail's own upload title (its deliverable name after 'Channel thumbnail - ')."""
    name = ctx.outputs[row['output_id']]['name']
    return name.split(' - ', 1)[1] if ' - ' in name and 'thumbnail' in row['output_id'] else None


def stack(row, ctx, mode):
    t = title_of(row, ctx)
    return {'op': 'title_stack_r4m', 'title': t, 'mode': mode, 'max_rows': 6, 'min_conf': 60} if t else None

R4 = {
    (TASK, 'R017'): const({'op': 'scrap_moves_r4m', 'asset': SCRAP, 'move_px': 8, 'grow': 0.03, 'still_px': 2,
                           'still_grow': 0.01, 'still_share': 0.9, 'still_levels': 3}),
    (TASK, 'R028'): const({'op': 'no_repeat_r4m', 'min_gap': 12, 'min_run': 8, 'match_tol': 3.0, 'person_tol': 6.0, 'min_change': 4.0,
                           'span_ratio': 0.25}),
    (TASK, 'R030'): const({'op': 'shared_captures_r4m', 'deliverable': 'deliverables/channel-teaser.mp4', 'count': 3,
                           'min_frames': 6}),
    (TASK, 'R037'): const({'op': 'music_from_bed_r4m', 'asset': BED, 'win_s': 0.5, 'quiet_db': -45, 'pass_ncc': 0.9,
                           'fail_ncc': 0.5, 'fail_share': 0.25}),
    (TASK, 'R053'): const(SCALE),
    (TASK, 'R054'): per_capture(SCALE),
    (TASK, 'R079'): const({'op': 'shot_wash_r4m', 'pass_gain': [0.92, 1.10], 'max_offset': 16, 'max_shift_share': 0.03,
                           'fail_gain': 0.75, 'fail_shift_share': 0.2, 'fade_s': 0.5}),
    (TASK, 'R052'): const({'op': 'shot_colour_r4m', 'tol': 8, 'fail_hue_deg': 30, 'fade_s': 0.5}),
    # round-2 title rules, read as a stack of rows (the correct thumbnails set the title over two or more rows)
    (TASK, 'R001'): lambda row, ctx: stack(row, ctx, 'reads'),
    (TASK, 'R018'): lambda row, ctx: stack(row, ctx, 'inside'),
    (TASK, 'R019'): lambda row, ctx: stack(row, ctx, 'inside'),
    (TASK, 'R117'): lambda row, ctx: stack(row, ctx, 'largest'),
    (TASK, 'R004'): const({'op': 'end_card_line_r4m', 'min_conf': 60, 'max_rows': 6,
                           'text': 'Members get the Sunday chaos stream and the bloopers nobody should see. Link in the description.'}),
}

HOW = {
    'music_from_bed_r4m': 'Decodes the whole sound track and searches for every half second of it in the supplied music file by cross-correlation.',
    'no_repeat_r4m': 'Compares every frame of the film with every frame half a second or more away and looks for a run of changing frames shown twice.',
    'scrap_moves_r4m': 'Finds the supplied mascot in the frames by feature matching and compares where he stands and how large he is from frame to frame.',
    'shared_captures_r4m': 'Matches every footage frame of both films to the supplied captures and compares the captures each film uses.',
    'capture_scale_r4m': 'Finds the capture frame behind each image or film frame by feature matching and measures its size against the recorded frame.',
    'shot_wash_r4m': 'Aligns every footage frame with its source capture frame and compares their tones channel by channel, allowing plain fades at the cuts.',
    'shot_colour_r4m': 'Aligns every footage frame with its source capture frame and compares their colours and hues.',
    'title_stack_r4m': 'Reads the image by OCR and finds the run of rows, top to bottom, that together read the title; then checks the reading, the rows\' boxes against the image edges, or their letter height against every other line.',
    'end_card_line_r4m': 'Reads the held end card by OCR and finds the rows that read the line; a final full stop lost in the reading is measured from the pixels after the last letter.',
}
