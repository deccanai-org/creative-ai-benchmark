#!/usr/bin/env python3
"""Write docs/gatsby-v7/annotation-pilot-v2/automation.html: which human rules now run as code, how each is checked,
and what testing showed. Reads moved_rules.json (decide_moves.py), the v2 rule groups and the step-1 plan.

Usage: python build_results_page.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_v7_annotation_pilot import CSS, TASK_IDS, esc  # noqa: E402
from build_v7_annotation_pilot_v2 import OUT, V2_CSS, k_short, template_text  # noqa: E402

FOUND_IN_TESTING = [
    ('Two headshots shot against the same backdrop were taken for each other.',
     'A match must now also look like the supplied photo where it was found (correlation 0.8 or more; true matches score 0.93 to 1.0, look-alikes under 0.45).'),
    ('"SPRING" was failed against "Spring".',
     'A difference in letter case alone goes to a person, unless the check is about letter case ("in sentence case, not in capitals").'),
    ('A note saying Casa Fienile is no longer offered was failed as an entry for it.',
     'Where a check forbids an entry or offer, a mention goes to a person; only a clean read with no mention passes.'),
    ('"Meridian Certified Plus" was failed for containing the forbidden "Meridian Certified".',
     'A forbidden phrase inside the expected one only counts where it stands on its own.'),
    ('"$22,900" was split at its comma, so the card\'s own "$26,900" matched "900".',
     'List items split only at a comma followed by a space; thousands commas stay.'),
    ('"SAT 3 OCT / SUN 4 OCT" was read as Sunday 3 October.',
     'A weekday pairs with the date right after it, or right before it, never across a slash or dash.'),
    ('Text sizes were measured from short letters, so two lines of one paragraph differed by 13%.',
     'Size is the height of capitals and tall letters; a line with none is "size unknown" and goes to a person.'),
    ('Very large display type was read only in part ("LOFT" for "UMBRA / LOFT").',
     'Images are read at three scales, and for each area the reading that recovers the most letters is kept.'),
    ('A check that the ridge line is drawn, "not from the halftone dots" of a photo, was turned into "the photo is present".',
     'Every converted rule with "not", "no" or "never" was re-read. Round 2 checks such rules for what the file shows: tiny dot shapes are counted in the SVG, and a traced drawing is matched against each photo.'),
    ('An SVG colour set through a CSS class, a named colour or the default black fill was invisible to the code.',
     'SVG colours are checked twice: the declared fills and strokes, and every solid area of the rendered artwork.'),
    ('A portrait cropped from the supplied photo was located by the whole photo\'s outline, which ran over the monogram above it.',
     'A supplied photo is located by the part of it that actually shows, compared pixel by pixel.'),
    ('Talk cards printing the date as "2026-03-03" were not found by a pattern for "3 Mar".',
     'A date is matched in any clear form, including exactly as the source record writes it.'),
    ('A cropped headshot was compared with the whole supplied photo, so correlation fell below 0.6 for an unaltered face.',
     'Only the part of the photo inside the placed picture\'s frame is compared.'),
    ('"PRIYA ANAND" in capitals was sent to a person for a check that the name is "spelled exactly".',
     'Letter case is not spelling: spelling checks compare without case. Checks that a line "reads exactly" still send a case difference to a person.'),
    ('On a product page with the price in a separate column, no product name was paired with its price, and the check passed.',
     'A page showing one product pairs it with that page\'s prices, and a name with no value found now goes to a person, never a pass.'),
    ('Dark type on a dark panel was read as part of the letters, so the panel colour was missed.',
     'The colour behind type leaves out only pixels close to the type\'s own colour, so low-contrast type is still checked.'),
    ('Clear paper below a heading was measured from the line box, about 1 mm short of the letters\' real bottom.',
     'Depth is measured from the bottom of the heading\'s letters, and a reading within 1 mm of the limit goes to a person.'),
    ('Tracked type extracts from PDFs with spaces between its letters ("F R I 2 5 S E P"), so dates and spacing went unread.',
     'Patterns are also matched with spaces removed, and letter spacing is measured glyph to glyph.'),
    ('A check that "&nbsp;" does not appear missed "8:00&nbsp;PM", because the text touched the figures.',
     'A word boundary applies only where the searched text starts or ends with a letter or digit (fixed for round 1 too).'),
    ('A deck showing earlier drafts of the posters passed the check that it shows the delivered designs.',
     'A design shown in a deck must match the delivered file in every cell of a 4 x 4 grid; any difference goes to a person.'),
    ('A cut line drawn inside the sticker artwork passed, because its path was named "cut-line".',
     'Only a group, or an object standing directly in the document, named as the cut contour counts as the separate cut layer.'),
    ('One-colour wordmarks were found but marked unclear: correlation has little to compare inside a solid shape.',
     'An unclear feature match is confirmed by template matching at the place it points to before it counts.'),
    ('Stickers traced from a bag photo were compared by outline with the whole bag, so every row went to a person.',
     'The drawing is feature-matched against each bag photo; its own photo must match clearly more points than the others.'),
    ('Thumbnails built on game footage with little texture were never matched to their capture.',
     'Whole-frame correlation is used where feature matching finds nothing.'),
]


def main():
    decisions = json.loads((HERE / 'moved_rules.json').read_text())
    plan = json.loads((HERE / 'automation_plan_step1.json').read_text())
    plan_c = Counter(p['status'] for p in plan)
    plan_n = Counter()
    for p in plan:
        plan_n[p['status']] += p['checks']
    groups = {tid: {r['rule_id']: r for r in json.loads((OUT / 'groups' / f'{tid}.json').read_text())['rules']} for tid in TASK_IDS}
    totals = Counter()
    task_rows, sections = [], []
    for tid in TASK_IDS:
        out = decisions.get(tid, {})
        moves = {k: v for k, v in out.items() if v['verdict'] == 'moves'}
        stays = {k: v for k, v in out.items() if v['verdict'] != 'moves'}
        mc = sum(len(v['checks']) for v in moves.values())
        sc = sum(len(v['checks']) for v in stays.values())
        test = Counter()
        for v in moves.values():
            t = v['test'].get('made_good') if tid in ('LAYOUT-12', 'VECTOR-04', 'MOTION-11') else v['test'].get('real')
            test.update(t or {})
        totals.update(moves=len(moves), move_checks=mc, stays=len(stays), stay_checks=sc,
                      passed=test['pass'], person=test['person'], failed=test['fail'])
        source = 'made files' if tid in ('LAYOUT-12', 'VECTOR-04', 'MOTION-11') else 'Sept 28 outputs'
        task_rows.append(f'<tr><td><a href="#{tid}">{tid}</a></td><td class="n">{len(moves)}</td><td class="n">{mc}</td>'
                         f'<td class="n">{test["pass"]}</td><td class="n">{test["person"]}</td><td class="n">{test["fail"]}</td>'
                         f'<td>{source}</td><td class="n">{len(stays)}</td></tr>')
        items = []
        for rid, v in sorted(moves.items()) + sorted(stays.items()):
            rule = groups[tid][rid]
            t = v['test'].get('made_good') if tid in ('LAYOUT-12', 'VECTOR-04', 'MOTION-11') else v['test'].get('real')
            t = t or {}
            bad = Counter(v['test'].get('made_bad') or {}) + Counter(v['test'].get('made_bad2') or {})
            result = f'pass {t.get("pass", 0)} · person {t.get("person", 0)} · fail {t.get("fail", 0)}'
            if bad:
                result += f' (broken files: pass {bad.get("pass", 0)} · person {bad.get("person", 0)} · fail {bad.get("fail", 0)})'
            verdict = ('<span class="badge b-code">Moves to code</span>' if v['verdict'] == 'moves'
                       else '<span class="badge">Stays with people</span>')
            crit = '<span class="badge b-crit">Critical</span>' if v['critical'] else ''
            items.append(f'<li><strong>{rid}</strong> <span class="badge b-k">{esc(k_short(v["k_id"]))}</span> {verdict} {crit}'
                         f'<br>{esc(template_text(rule["template"], rule["slot_labels"]))}'
                         f'<br><small><strong>Code:</strong> {esc(" ".join(v["how"]))} <strong>Test:</strong> {esc(result)} '
                         f'({len(v["checks"])} check{"s" if len(v["checks"]) != 1 else ""}). {esc(v["why"][:1].upper() + v["why"][1:])}.</small></li>')
        sections.append(f'<details class="task" id="{tid}"><summary>{tid}: {len(moves)} rules · {mc} checks move; '
                        f'{len(stays)} rules stay</summary><ol class="rules-list">{"".join(items)}</ol></details>')
    found = ''.join(f'<li><strong>{esc(a)}</strong> {esc(b)}</li>' for a, b in FOUND_IN_TESTING)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Checks Moved to Code</title><style>{CSS}{V2_CSS}
.task{{border:1px solid #dce3df;border-radius:8px;margin:10px 0;padding:6px 12px}}.task>summary{{cursor:pointer;font-weight:600;padding:4px 0}}
.task li{{margin:0 0 10px}}.task small{{color:#3f4b45}}table.summary td,table.summary th{{padding:5px 8px}}</style></head><body>
<main class="page">
<p class="v2nav"><a href="index.html">All pilot tasks</a></p>
<header><h1>Pilot-13 v2: human checks now answered by code</h1></header>
<div class="intro">
<p><strong>{totals["move_checks"]} checks ({totals["moves"]} rules) now run as code.</strong> They are facts code reads exactly from the delivered file. A PDF gives its text, fonts, sizes, colours and placed images directly. Images and video frames are read with OCR (Tesseract 5.5.3). Supplied photos and logos are found by feature matching, then confirmed by correlation (OpenCV 5.0). Nothing that needs judgement moved.</p>
<p>Every automatic check answers pass, fail or person. <strong>Person</strong> means the code could not decide, so that row goes back to a person. The code never passes what it cannot read. A near miss that could be a misreading (Lindqvist read as "Lindavist") goes to a person, not to a fail. A difference only in letter case goes to a person too. Each check keeps its ID, K question and critical flag, so scoring does not change.</p>
</div>
<h2>Where the 1,500 rules stand</h2>
<div class="scroll-x"><table class="summary"><thead><tr><th>Decision</th><th class="n">Rules</th><th class="n">Checks</th></tr></thead><tbody>
<tr><td>Moved to code (this page)</td><td class="n">{totals["moves"]}</td><td class="n">{totals["move_checks"]}</td></tr>
<tr><td>Automatic check built, but stays with people for now (a wrong answer in testing, or the code decided under half of the test rows)</td><td class="n">{totals["stays"]}</td><td class="n">{totals["stay_checks"]}</td></tr>
<tr><td>Could run as code, not converted yet</td><td class="n">{plan_c["auto"] - totals["moves"] - totals["stays"]}</td><td class="n">{plan_n["auto"] - totals["move_checks"] - totals["stay_checks"]}</td></tr>
<tr><td>Needs a definition first (open questions for Dhiren)</td><td class="n">{plan_c["needs_definition"]}</td><td class="n">{plan_n["needs_definition"]}</td></tr>
<tr><td>Colour sampled on a photograph or render (later)</td><td class="n">{plan_c["later"]}</td><td class="n">{plan_n["later"]}</td></tr>
<tr><td>Stays with people (judgement)</td><td class="n">{plan_c["human"]}</td><td class="n">{plan_n["human"]}</td></tr>
</tbody></table></div>
<h2>Test results for the moved rules</h2>
<p>The ten tasks with outputs were tested on the 102 deliverables of the 2026-09-28 run. LAYOUT-12, VECTOR-04 and MOTION-11 have no run output, so test files were made from each task's own data in three sets: a correct set, and two sets with one planted defect per file (a wrong weekday, acts out of order, an off-palette colour hidden in CSS, a title cut off at the edge, an act billed with the wrong date, a sticker traced from the wrong bag photo, a thumbnail built on another video's frame). Every planted defect was failed or sent to a person; none passed, and no correct file failed. Every fail on the real outputs was checked by hand.</p>
<div class="scroll-x"><table class="summary"><thead><tr><th>Task</th><th class="n">Rules moved</th><th class="n">Checks moved</th><th class="n">Pass</th><th class="n">Person</th><th class="n">Fail</th><th>Tested on</th><th class="n">Rules staying</th></tr></thead>
<tbody>{"".join(task_rows)}<tr><td><strong>Total</strong></td><td class="n"><strong>{totals["moves"]}</strong></td><td class="n"><strong>{totals["move_checks"]}</strong></td><td class="n">{totals["passed"]}</td><td class="n">{totals["person"]}</td><td class="n">{totals["failed"]}</td><td></td><td class="n">{totals["stays"]}</td></tr></tbody></table></div>
<p>Pass, Person and Fail count test rows: the 2026-09-28 outputs for the ten tasks with a run, the correct made files for LAYOUT-12, VECTOR-04 and MOTION-11.</p>
<h2>What testing found, and what changed</h2>
<p>Each of these gave a wrong answer, or no answer where the file allowed one, on a test output before it was fixed; after the fixes, all outputs were run again.</p>
<ul class="rules-list">{found}</ul>
<h2>Questions for Dhiren</h2>
<ul class="rules-list">
<li><strong>Letter case.</strong> When a check says a line "reads exactly" a value and the design sets it in capitals ("OPENING KEYNOTE" for "Opening Keynote", "SPRING" for "Spring"), should that count as matching? Today those rows go to a person. If case should not matter, they would pass automatically.</li>
<li><strong>Nine definitions.</strong> {plan_n["needs_definition"]} checks ({plan_c["needs_definition"]} rules) need a definition before code can answer them, such as which lines count as body text, which text is the main heading, or whether an opaque shape partly covering a photo counts as an overlay. They are listed on the <a href="automation-plan.html">step-1 plan</a>.</li>
</ul>
<h2>Every converted rule</h2>
{"".join(sections)}
</main></body></html>
"""
    (OUT / 'automation.html').write_text(page, encoding='utf-8')
    # the step-1 plan it links to, published beside it
    (OUT / 'automation-plan.html').write_text((HERE / 'automation_plan_step1.html').read_text(encoding='utf-8'), encoding='utf-8')
    print('wrote', OUT / 'automation.html', dict(totals))


if __name__ == '__main__':
    main()
