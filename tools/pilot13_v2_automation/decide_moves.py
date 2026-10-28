#!/usr/bin/env python3
"""Decide which converted rules move to code, from the test results, and write moved_rules.json.

A converted rule moves when, across its test rows (the 2026-09-28 outputs, or made files for the three tasks no run
produced), the code gave no wrong answer and decided at least half of the rows itself. A wrong answer is a fail on a
row where the deliverable is right; known_true_fails lists every fail that was checked by hand and is a real defect.
Rules the code mostly sends back to a person stay with people for now: the automatic check exists, but on these
outputs it would not save review time.

Usage: python decide_moves.py <real results.json> <made good results.json> <made bad results.json> [<made bad2 results.json>]
(bad2: the second broken set, with the round-2 defects of PLANTED2)
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
    pilot = {r['check_id']: {'status': r['status'], 'note': note(r)} for r in real
             if r['task'] not in MADE_TASKS and r['status'] in ('pass', 'fail', 'person')}
    (HERE / 'pilot_results_2026-09-28.json').write_text(json.dumps(pilot, ensure_ascii=False, indent=1) + '\n')
    moved = {f.stem: json.loads(f.read_text())['moved'] for f in sorted((HERE / 'moved').glob('*.json'))}
    stats = defaultdict(lambda: {'real': Counter(), 'made_good': Counter(), 'made_bad': Counter(), 'made_bad2': Counter(), 'wrong': []})
    for name, results in (('real', real), ('made_good', good), ('made_bad', bad), ('made_bad2', bad2)):
        planted = PLANTED2 if name == 'made_bad2' else PLANTED
        for r in results:
            if name == 'real' and r['task'] in MADE_TASKS:
                continue
            key = (r['task'], r['rule_id'])
            s = stats[key]
            s[name][r['status']] += 1
            output = r['check_id'].split('/')[1]
            hit = is_planted(planted, r['task'], output, r['rule_id'], r['check_id'])
            if name in ('made_bad', 'made_bad2') and r['status'] == 'pass' and hit:
                s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'passed a planted defect'})
            if r['status'] in ('error',):
                s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'operation error'})
            if r['status'] == 'fail':
                if name == 'real' and r['check_id'] not in KNOWN_TRUE_FAILS:
                    s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'fail not confirmed as a real defect'})
                if name == 'made_good':
                    s['wrong'].append({'check': r['check_id'], 'run': name, 'why': 'fail on a correct made file'})
                if name in ('made_bad', 'made_bad2') and not hit:
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
                        'critical': members[0]['critical'], 'how': sorted({m['how'] for m in members}),
                        'test': {k: dict(s[k]) for k in ('real', 'made_good', 'made_bad', 'made_bad2') if s[k]}, 'wrong': s['wrong']}
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
