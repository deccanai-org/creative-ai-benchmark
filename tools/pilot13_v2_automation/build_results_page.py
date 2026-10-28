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
    # round 3
    ('Two checks written separately shared a name, so one ran the other\'s code.',
     'Every check name is now verified unique when the code loads; a repeat stops the run.'),
    ('The soft, anti-aliased edges of letters were read as grey type.',
     'Type colour is read from the cores of the letters, never their edges.'),
    ('A leaf mark\'s colour was read from its dark outline.',
     'A mark\'s colour is the commonest colour of its own fill, never its outline or soft edge.'),
    ('The gap between two photographs was read as a drawn rule.',
     'No rule is read in a row taken up mostly by photographs.'),
    ('Tyres and warm grey studio backdrops inside photographs were read as off-palette designed colour.',
     'An off-palette piece within 20 px of a photograph now goes to a person. Where only part of a photograph is masked (PHOTO-08 R046, PHOTO-10 R052) a wrong fail remains, so those two rules stay with people.'),
    ('The ground behind a cut-out speaker was taken from the header band above her.',
     'The ground behind a sitter is the flat area running down both sides of the cut-out, not a band it only touches at the top.'),
    ('A dark jacket was read as leftover studio backdrop.',
     'Leftover backdrop must match the supplied photo\'s own pixels there as well as the backdrop colour.'),
    ('A check that every photograph keeps its colour passed when only some photographs were found.',
     'A check about every photograph answers only when every photograph on the file is matched to a supplied one.'),
    ('OCR skipped a small plate numeral entirely while reading the other lines with full confidence.',
     'Typeface checks never pass because a line was not found; a person confirms the absence.'),
]


# plain words for the limits a check decides by (decide_moves.limits); anything not listed shows its code name
LIMIT_WORDS = {
    'tol': 'colour tolerance per RGB channel', 'min_conf': 'OCR confidence at least', 'min_cover': 'share of the photo found at least',
    'min_chars': 'letters read at least', 'max_de': 'colour difference allowed (Delta E)', 'max_scale': 'enlargement allowed',
    'tol_pt': 'line spacing tolerance (pt)', 'pass_em': 'letter spacing passes up to (em)', 'fail_em': 'letter spacing fails from (em)',
    'min_share': 'smallest area counted (share of the page)', 'min_tiles': 'tiles compared at least', 'max_rows': 'text rows at most',
    'max_words': 'words at most', 'max_other_words': 'other words at most', 'min_words': 'words at least',
    'min_ncc': 'correlation with the supplied file at least', 'thickness': 'rule thickness (pt)', 'min_gap': 'gap at least',
    'thin_px': 'thin line up to (px)', 'small_px': 'small piece up to (px)',
    'ncc_min': 'lowest tile correlation with the supplied photo', 'rgb_max': 'largest tile colour change (RGB levels)',
    'rgb_median': 'typical colour change (RGB levels)', 'de_max': 'largest tile colour difference (Delta E)',
    'dc_max': 'largest tile shift in hue and saturation (Delta E, lightness left out)', 'drift': 'tone drift',
    'gain_min': 'lowest brightness gain', 'hf_min': 'fine detail kept, lowest tile (share of the source)',
    'hf_median': 'fine detail kept, typical tile (share of the source)', 'frame_share': 'share of the frame',
    'fills_image': 'share of the image filled', 'chroma_ratio': 'colourfulness against the source',
    'da': 'mean shift green to red', 'db': 'mean shift blue to yellow', 'dL': 'mean shift in lightness', 'scale': 'scale against the source',
    'noise_ratio': 'grain against the source', 'warm_single': 'single warm tone', 'src_warm_single': 'source in a single warm tone',
}


def limit_text(limits) -> str:
    parts = []
    for name, cmp, value in limits:
        verdict, _, key = name.rpartition(':')
        words = LIMIT_WORDS.get(key, key)
        cmp = {'>=': 'at least', '<=': 'at most', '>': 'over', '<': 'under', '=': ''}.get(cmp, cmp)
        parts.append(f'{verdict} when {words} {cmp} {value:g}'.replace('  ', ' ') if verdict else f'{words} {value:g}')
    return '; '.join(parts)


def main():
    decisions = json.loads((HERE / 'moved_rules.json').read_text())
    plan = json.loads((HERE / 'automation_plan_step1.json').read_text())
    plan_c = Counter(p['status'] for p in plan)
    plan_n = Counter()
    for p in plan:
        plan_n[p['status']] += p['checks']
    # where each first-sort group stands: moved, built but staying, or left with people
    status_of = {(p['task'], p['rule']): p['status'] for p in plan}
    group = {k: Counter() for k in plan_c}
    for tid, rules in decisions.items():
        for rid, v in rules.items():
            g = group[status_of[(tid, rid)]]
            key = 'moved' if v['verdict'] == 'moves' else 'built'
            g[key + '_rules'] += 1
            g[key + '_checks'] += len(v['checks'])
    labels = [('auto', 'Code reads it directly (text, type, sizes, positions, picture matching)'),
              ('later', 'Colour on images'), ('needs_definition', 'Needed a definition (now defined in code)'),
              ('human', 'Judgement (the measurable ones re-sorted in round 3)')]
    group_rows, all_ = [], Counter()
    for key, label in labels:
        g = group[key]
        left_r = plan_c[key] - g['moved_rules'] - g['built_rules']
        left_c = plan_n[key] - g['moved_checks'] - g['built_checks']
        all_.update(r=plan_c[key], c=plan_n[key], m=g['moved_checks'], b=g['built_checks'], l=left_c)
        group_rows.append(f'<tr><td>{label}</td><td class="n">{plan_c[key]:,}</td><td class="n">{plan_n[key]:,}</td>'
                          f'<td class="n">{g["moved_checks"]:,}</td><td class="n">{g["built_checks"]:,}</td><td class="n">{left_c:,}</td></tr>')
    group_rows.append(f'<tr><td><strong>Total</strong></td><td class="n"><strong>{all_["r"]:,}</strong></td><td class="n"><strong>{all_["c"]:,}</strong></td>'
                      f'<td class="n"><strong>{all_["m"]:,}</strong></td><td class="n"><strong>{all_["b"]:,}</strong></td><td class="n"><strong>{all_["l"]:,}</strong></td></tr>')
    group_rows = '\n'.join(group_rows)
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
            bad = sum((Counter(v['test'].get(k) or {}) for k in ('made_bad', 'made_bad2', 'made_bad3')), Counter())
            result = f'pass {t.get("pass", 0)} · person {t.get("person", 0)} · fail {t.get("fail", 0)}'
            if bad:
                result += f' (broken files: pass {bad.get("pass", 0)} · person {bad.get("person", 0)} · fail {bad.get("fail", 0)})'
            verdict = ('<span class="badge b-code">Moves to code</span>' if v['verdict'] == 'moves'
                       else '<span class="badge">Stays with people</span>')
            crit = '<span class="badge b-crit">Critical</span>' if v['critical'] else ''
            items.append(f'<li><strong>{rid}</strong> <span class="badge b-k">{esc(k_short(v["k_id"]))}</span> {verdict} {crit}'
                         f'<br>{esc(template_text(rule["template"], rule["slot_labels"]))}'
                         f'<br><small><strong>Code:</strong> {esc(" ".join(v["how"]))} <strong>Test:</strong> {esc(result)} '
                         f'({len(v["checks"])} check{"s" if len(v["checks"]) != 1 else ""}). {esc(v["why"][:1].upper() + v["why"][1:])}.'
                         + (f' <strong>Limits chosen in code:</strong> {esc(limit_text(v["limits"]))}.' if v.get('limits') else '')
                         + '</small></li>')
        sections.append(f'<details class="task" id="{tid}"><summary>{tid}: {len(moves)} rules · {mc} checks move; '
                        f'{len(stays)} rules stay</summary><ol class="rules-list">{"".join(items)}</ol></details>')
    found = ''.join(f'<li><strong>{esc(a)}</strong> {esc(b)}</li>' for a, b in FOUND_IN_TESTING)
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Checks Moved to Code</title><style>{CSS}{V2_CSS}
.task{{border:1px solid #dce3df;border-radius:8px;margin:10px 0;padding:6px 12px}}.task>summary{{cursor:pointer;font-weight:600;padding:4px 0}}
.task li{{margin:0 0 10px;overflow-wrap:anywhere}}.task small{{color:#3f4b45}}table.summary td,table.summary th{{padding:5px 8px}}</style></head><body>
<main class="page">
<p class="v2nav"><a href="index.html">All pilot tasks</a></p>
<header><h1>Pilot-13 v2: human checks now answered by code</h1></header>
<div class="intro">
<p><strong>{totals["move_checks"]:,} checks ({totals["moves"]:,} rules) now run as code.</strong> Each is a measurement with a fixed rule, so the same file always gets the same answer. A PDF gives its text, fonts, sizes, colours and placed images directly. Images and video frames are read with OCR (Tesseract 5.5). Supplied photos and logos are found by feature matching and compared pixel by pixel (OpenCV 5.0). A typeface on an image is identified by drawing the line's own words in each candidate font and comparing the letter shapes. No AI vision model is used, and nothing that needs judgement moved.</p>
<p>Round 3 (2026-10-28) added colour on images, photographs compared with their supplied files, typefaces on images, and the rules that needed a definition. Where a rule is worded as how something looks ("the water reads pale turquoise as in the source", "not visibly letterspaced"), the code measures it against limits: clearly within passes, clearly outside fails, anything between goes to a person. Every moved rule below lists the limits it decides by.</p>
<p>Every automatic check answers pass, fail or person. <strong>Person</strong> means the code could not decide, so that row goes back to a person. The code never passes what it cannot read. A near miss that could be a misreading (Lindqvist read as "Lindavist") goes to a person, not to a fail. A difference only in letter case goes to a person too. Each check keeps its ID, K question and critical flag, so scoring does not change.</p>
</div>
<h2>Where the 1,500 rules stand</h2>
<p>Each rule was first sorted by what answering it takes. The columns show where each group stands now.</p>
<div class="scroll-x"><table class="summary"><thead><tr><th>First sorted as</th><th class="n">Rules</th><th class="n">Checks</th><th class="n">Moved to code</th><th class="n">Code built, stays with people</th><th class="n">Left with people</th></tr></thead><tbody>
{group_rows}
</tbody></table></div>
<p>"Code built, stays with people" means the automatic check exists, but on the test files it gave a wrong answer or decided fewer than half of the rows, so a person keeps answering it for now.</p>
<h2>Test results for the moved rules</h2>
<p>The ten tasks with outputs were tested on the 102 deliverables of the 2026-09-28 run. LAYOUT-12, VECTOR-04 and MOTION-11 have no run output, so test files were made from each task's own data in four sets: a correct set, and three sets with one planted defect per file (a wrong weekday, acts out of order, an off-palette colour hidden in CSS, a title cut off at the edge, an act billed with the wrong date, a sticker traced from the wrong bag photo, a thumbnail built on another video's frame; in round 3 a scrim over the photograph, a wordmark inked in the wrong colour, a shadow behind a sticker, a title word with no outline, synthesised music in place of the supplied track). For every moved rule, each planted defect was failed or sent to a person, and no correct file failed. Every fail on the real outputs was checked by eye.</p>
<div class="scroll-x"><table class="summary"><thead><tr><th>Task</th><th class="n">Rules moved</th><th class="n">Checks moved</th><th class="n">Pass</th><th class="n">Person</th><th class="n">Fail</th><th>Tested on</th><th class="n">Rules staying</th></tr></thead>
<tbody>{"".join(task_rows)}<tr><td><strong>Total</strong></td><td class="n"><strong>{totals["moves"]:,}</strong></td><td class="n"><strong>{totals["move_checks"]:,}</strong></td><td class="n">{totals["passed"]:,}</td><td class="n">{totals["person"]:,}</td><td class="n">{totals["failed"]:,}</td><td></td><td class="n">{totals["stays"]:,}</td></tr></tbody></table></div>
<p>Pass, Person and Fail count test rows: the 2026-09-28 outputs for the ten tasks with a run, the correct made files for LAYOUT-12, VECTOR-04 and MOTION-11.</p>
<h2>What testing found, and what changed</h2>
<p>Each of these gave a wrong answer, or no answer where the file allowed one, on a test output before it was fixed; after the fixes, all outputs were run again.</p>
<ul class="rules-list">{found}</ul>
<h2>Questions for Dhiren</h2>
<ul class="rules-list">
<li><strong>Letter case.</strong> When a check says a line "reads exactly" a value and the design sets it in capitals ("OPENING KEYNOTE" for "Opening Keynote", "SPRING" for "Spring"), should that count as matching? Today those rows go to a person. If case should not matter, they would pass automatically.</li>
<li><strong>Definitions chosen in code.</strong> Rules about "body text", "headings", "fine print" or "captions" now use one definition, read the same way on every file: running text is sentence-case lines not repeated with only figures changed; body text is the running lines at the size carrying the most characters; headings are set at 1.3 times that size or more (the main heading at the largest size); fine print is under 0.85 times it, captions in sentence case and labels in capitals. A panel is a filled area of 2% of the page or more; an overlay is anything semi-transparent or shaded drawn over a placed photo. Please say if any of these should read differently. Rules where only a circular definition was possible stay with people.</li>
<li><strong>Limits chosen in code.</strong> Rules worded as how something looks are decided by the limits listed under each moved rule (for example letter spacing passes up to 0.002 em and fails from 0.025 em; a photograph passes as unchanged when every tile still correlates 0.95 or more with the supplied file). Please say if any limit should be tighter or looser.</li>
<li><strong>Text that is not there.</strong> An optional check ("if a price appears") passes on an image when OCR reads every line at 80% confidence or more and finds no such text. In round 3, OCR skipped a small plate numeral entirely while reading the rest with full confidence, so typeface checks now send an absence to a person. The other image checks still pass an absence, as published in rounds 1 and 2. Should they send it to a person too? That would be safer, and would lower the number of checks answered by code.</li>
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
