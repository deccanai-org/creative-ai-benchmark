#!/usr/bin/env python3
"""Build annotation-pilot-v3: the v2 pilot pages with every human check now answered by code moved to the task's
Auto verifiers page.

Each task gets a Human verifiers page with only the rules people still answer, and an Auto verifiers page with the
task's own automatic checks (unchanged from V7) followed by the human checks code now answers, rule by rule under their
K question, with how the code checks each one, the limits it decides by and its answer on the 2026-09-28 run. Briefs,
check IDs, K questions, critical flags and scoring are the same as in v2; v1 and v2 are not touched (v3 links v2's
thumbnails and v1's previews). Run after decide_moves.py, so moved_rules.json is current.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import build_v7_annotation_pilot_v2 as v2
from build_v7_annotation_pilot import CSS, DOWNLOAD_SCRIPT, ROOT, TASK_IDS, TASKS, esc, font_css, render_assets, render_brand, render_outputs

sys.path.insert(0, str(ROOT / 'tools/pilot13_v2_automation'))
from build_results_page import limit_text  # noqa: E402

OUT = ROOT / 'docs/gatsby-v7/annotation-pilot-v3'
REVISION = 'pilot13_v3_code_moved_to_auto_2026_10_29'
RUNS = ROOT / 'docs/gatsby-v7/pilot-2026-09-28/runs'
V2_DIR = '../annotation-pilot-v2'
V3_CSS = """
.k-moved{margin:8px 0 14px;padding:9px 12px;border:1px solid #cfe0d6;border-radius:6px;background:#f3f8f5;font-size:14px}
.rule-limits{font-size:14px;color:#3f4b45;margin:6px 0 8px;overflow-wrap:anywhere}
.auto-intro{border-left:4px solid #3c7a5a;padding:2px 0 2px 12px;margin:14px 0}
.part-head{margin:34px 0 6px;padding-top:18px;border-top:2px solid #dce3df}
.ans.auto-pass{color:#2f6a4c}.ans.auto-fail{color:#a3402b}.ans.auto-none{color:#6b7570}
"""


class Thumbs(v2.Thumbnails):
    """v2's thumbnails, linked from the v2 folder (v3 shows the same rules); one v2 lacks is made in v3's own folder,
    never in v2's."""

    def __getitem__(self, name: str) -> str:
        suffix = Path(name).suffix.lower()
        if suffix == '.svg':
            return self.assets[name]['public_url']
        file = name if suffix in ('.jpg', '.jpeg', '.png') else name + '.jpg'
        if (v2.THUMBS / self.task_id / file).is_file():
            return f'{V2_DIR}/thumbs/{self.task_id}/{file}'
        kept, v2.THUMBS = v2.THUMBS, OUT / 'thumbs'
        try:
            return super().__getitem__(name)
        finally:
            v2.THUMBS = kept


def run_results(task_id: str) -> dict:
    """The automatic checks' answers on the 2026-09-28 pilot run (check ID -> status), for the ten tasks it covered."""
    path = RUNS / task_id / 'verifier-results.json'
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    rows = data.get('results') or data.get('auto_verifiers') or []
    return {r['verifier_id']: r.get('status') for r in rows if r.get('verifier_id')}


def nav(task_id: str, here: str) -> str:
    links = [('index.html', 'All pilot tasks'), (f'{task_id}.html', 'Brief'), (f'{task_id}-verifiers.html', 'Human verifiers'),
             (f'{task_id}-auto.html', 'Auto verifiers')]
    parts = [esc(label) if href == here else f'<a href="{href}">{esc(label)}</a>' for href, label in links]
    return f'<p class="v2nav">{" · ".join(parts)} · <a href="../index.html#{task_id}/trajectory">Trajectory verifiers</a></p>'


def count(n: int, word: str) -> str:
    return f'{n} {word}{"s" if n != 1 else ""}'


def coded_rule_html(rule: dict, ctx: dict, limits: list) -> str:
    """v2's rendering of a rule answered by code, with the limits it decides by."""
    html = v2.rule_html(rule, ctx)
    if limits:
        tail = 'A row comes back to a person when the code cannot read or find what it needs.</p>'
        html = html.replace(tail, tail + f'<p class="rule-limits"><strong>Limits chosen in code:</strong> {esc(limit_text(limits))}.</p>', 1)
    return html


def k_blocks(task_id: str, spec: dict, rules: list[dict], catalog: list[dict], ctx: dict, page: str, limits: dict) -> tuple[str, str]:
    """The V7 K layout for one side: page 'human' shows the rules people answer, page 'auto' the rules code answers.
    Each question also says where its other checks are."""
    by_question = defaultdict(list)
    for rule in rules:
        by_question[rule['k_id']].append(rule)
    answered = Counter()
    total = 0
    blocks = []
    mine = (lambda r: r.get('answered_by') != 'code') if page == 'human' else (lambda r: r.get('answered_by') == 'code')
    render = (lambda r: v2.rule_html(r, ctx)) if page == 'human' else (lambda r: coded_rule_html(r, ctx, limits.get(r['rule_id'], [])))
    for cap in catalog:
        parts = []
        for q in cap['questions']:
            total += 1
            members = by_question.get(q['id'], [])
            here = [r for r in members if mine(r)]
            there = [r for r in members if not mine(r)]
            n_here, n_there = sum(len(r['rows']) for r in here), sum(len(r['rows']) for r in there)
            if page == 'auto' and not here:
                continue
            if here:
                answered['task'] += 1
            elif there:
                answered['other'] += 1
            label = f'{count(len(here), "rule")} · {count(n_here, "check")}' if here else ''
            badge = '<span class="objective" title="Objective question">Objective</span>' if q.get('objective') else ''
            parts.append(f'<div class="kq" id="{esc(q["id"])}"><h3>{esc(v2.k_short(q["id"]))} · {esc(q["label"])}{badge}'
                         f'<span class="k-count">{label}</span></h3><p class="k-qtext">{esc(q["question"])}</p>')
            if here:
                if q['id'] == 'K2_Q3':
                    for part, title in v2.BRAND_PARTS.items():
                        chosen = [r for r in here if r['brand_part'] == part]
                        if chosen:
                            n = sum(len(r['rows']) for r in chosen)
                            parts.append(f'<div class="kpart"><h4>Brand-system rules: {esc(title)} ({count(len(chosen), "rule")} · '
                                         f'{count(n, "check")})</h4>' + ''.join(render(r) for r in chosen) + '</div>')
                else:
                    parts.extend(render(r) for r in here)
            if there and page == 'human':
                parts.append(f'<p class="k-moved">{count(n_there, "further check")} for this question ({count(len(there), "rule")}) '
                             f'{"are" if n_there != 1 else "is"} answered by code: see <a href="{task_id}-auto.html#{esc(q["id"])}">Auto verifiers</a>.</p>')
            if not members and page == 'human':
                auto = [c for c in spec['verifiers_auto'] if v2.AUTO2K.get((c.get('assertion') or {}).get('op')) == q['id']]
                if auto:
                    answered['auto'] += 1
                    parts.append(f'<div class="k-auto"><strong>Answered by automatic checks.</strong> {count(len(auto), "automatic check")} '
                                 f'on this task answer this question, so annotators do not rate it here. They are listed on the '
                                 f'<a href="{task_id}-auto.html#own-auto">Auto verifiers</a> page.</div>')
                else:
                    parts.append('<p class="k-empty">No task-specific verifier for this question on this task.</p>')
            parts.append('</div>')
        if parts:
            blocks.append(f'<section class="kcap"><h2>{esc(cap["id"])} · {esc(cap["name"])}</h2>'
                          f'<p class="k-measures">{esc(cap["measures"])} <em>Scored by {esc(cap["scored_by"])}.</em></p>' + ''.join(parts) + '</section>')
    if page == 'human':
        coverage = (f'<p class="k-coverage">{answered["task"] + answered["other"] + answered["auto"]} of {total} objective rubric questions are '
                    f'answered for this task: {answered["task"]} with rules for people on this page, {answered["other"]} only by human checks '
                    f'now answered by code, and {answered["auto"]} by the automatic layer.</p>')
    else:
        coverage = ''
    return coverage, ''.join(blocks)


TOOLS = """<div class="tools" role="group" aria-label="Filter rules">
<label>Deliverable <select id="deliverable"><option value="">All {n} deliverables</option>{options}</select></label>
<label>Search <input id="query" type="search" placeholder="Words in a rule or check"></label>
<label><input id="hide-full" type="checkbox"> Hide the full sentence under each row</label>
<span id="shown" aria-live="polite"></span>
</div>"""


def write_human_page(task_id: str, spec: dict, rules: list[dict], catalog: list[dict], ctx: dict) -> None:
    people = [r for r in rules if r.get('answered_by') != 'code']
    coded = [r for r in rules if r.get('answered_by') == 'code']
    checks, code_checks = sum(len(r['rows']) for r in people), sum(len(r['rows']) for r in coded)
    coverage, blocks = k_blocks(task_id, spec, rules, catalog, ctx, 'human', {})
    moved = (f' The other {code_checks} human checks of this task ({count(len(coded), "rule")}) are now answered by code and are listed on '
             f'the <a href="{task_id}-auto.html">Auto verifiers</a> page; each K question below says how many of its checks moved.') if coded else ''
    options = ''.join(f'<option value="{esc(o["output_id"])}">{esc(o["name"])}</option>' for o in spec['deliverables'])
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(task_id)} · Human verifiers</title><style>{CSS}{v2.V2_CSS}{V3_CSS}</style></head><body>
<main class="page">
{nav(task_id, f'{task_id}-verifiers.html')}
<header><h1>{esc(spec["task_name"])}: human verifiers</h1></header>
<div class="intro">
<p><strong>{count(checks, "human check")} for people, written as {count(len(people), "rule")}.</strong>{moved} The checks and their K questions are the same as on the V7 site; checks that say the same thing about different deliverables are written once, as a rule, with one row per check.</p>
</div>
<section class="howto" aria-labelledby="howto-title"><h2 id="howto-title">How to read a rule</h2>{v2.HOW_TO_READ}{v2.example_html(people or rules, task_id)}
<p class="k-coverage"><span class="badge b-k">K1 Q1</span> is the K question a rule scores. <span class="badge b-cond">Only if present</span>: the rule applies only when that element appears. <span class="badge b-crit">Critical</span>: a critical-failure check. Look or Measure is the checking method, explained under each rule.</p></section>
{coverage}
{TOOLS.format(n=len(spec["deliverables"]), options=options)}
{blocks}
</main>{v2.FILTER_SCRIPT}<script src="https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5"></script></body></html>
"""
    (OUT / f'{task_id}-verifiers.html').write_text(page, encoding='utf-8')


def own_auto_html(task_id: str, spec: dict, results: dict) -> tuple[str, int]:
    """The task's own automatic checks (TASK_SPEC verifiers_auto, as on the V7 Auto tab), one table per deliverable."""
    by_output = defaultdict(list)
    for c in spec['verifiers_auto']:
        by_output[c['output_id']].append(c)
    run = bool(results)
    blocks = []
    for o in spec['deliverables']:
        checks = by_output.get(o['output_id'], [])
        if not checks:
            continue
        body = []
        for c in checks:
            status = results.get(c['check_id'])
            if status == 'pass':
                ans = '<td class="ans auto-pass" data-label="Answer">Code: Yes</td>'
            elif status == 'fail':
                ans = '<td class="ans auto-fail" data-label="Answer">Code: No</td>'
            else:
                ans = ('<td class="ans auto-none" data-label="Answer">Code<small>not assessed on the 2026-09-28 run</small></td>' if run else
                       '<td class="ans auto-none" data-label="Answer">Code<small>no output on the 2026-09-28 run</small></td>')
            k = v2.AUTO2K.get((c.get('assertion') or {}).get('op'))
            kq = f'<span class="badge b-k">{esc(v2.k_short(k))}</span> ' if k else ''
            body.append(f'<tbody class="ck" data-output="{esc(o["output_id"])}" data-row="{esc(c["check_id"])}"><tr>'
                        f'<td class="id" data-label="Check" title="{esc(c["check_id"])}">{esc(c["check_id"].split("/")[-1])}</td>'
                        f'<td data-label="Automatic check">{kq}{esc(c["check"])}</td>{ans}</tr></tbody>')
        blocks.append(f'<article class="rule" id="auto-{esc(o["output_id"])}"><div class="rule-head"><span class="rid">{esc(o["name"])}</span>'
                      f'<span class="badge">{count(len(checks), "automatic check")}</span></div>'
                      f'<p class="rule-scope"><code>{esc(Path(o["path"]).name)}</code></p>'
                      f'<div class="rows-wrap"><table class="rows"><thead><tr><th>Check</th><th>Automatic check</th>'
                      f'<th>{"Answer on the 2026-09-28 run" if run else "Answer"}</th></tr></thead>{"".join(body)}</table></div></article>')
    return ''.join(blocks), len(spec['verifiers_auto'])


def write_auto_page(task_id: str, spec: dict, rules: list[dict], catalog: list[dict], ctx: dict, limits: dict, results: dict) -> None:
    coded = [r for r in rules if r.get('answered_by') == 'code']
    code_checks = sum(len(r['rows']) for r in coded)
    _, blocks = k_blocks(task_id, spec, rules, catalog, ctx, 'auto', limits)
    own, n_own = own_auto_html(task_id, spec, results)
    back = sum(1 for r in coded for row in r['rows'] if (v2.PILOT.get(row['check_id']) or {}).get('status') == 'person')
    run_note = (f' On the 2026-09-28 run, {count(back, "row")} of the moved checks came back to a person because the code could not '
                f'read or find what the check needs; a person answers those rows.') if back else ''
    options = ''.join(f'<option value="{esc(o["output_id"])}">{esc(o["name"])}</option>' for o in spec['deliverables'])
    moved_part = (f'<h2 class="part-head" id="moved">Human checks now answered by code ({count(code_checks, "check")}, {count(len(coded), "rule")})</h2>'
                  f'<p class="auto-intro">These were human checks in v1 and v2. Each keeps its check ID, K question and critical flag, so scoring '
                  f'does not change. Under each rule: how the code checks it, the limits it decides by, and its answer on every row.{run_note}</p>'
                  + blocks) if coded else '<p class="k-empty">No human check of this task is answered by code yet.</p>'
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(task_id)} · Auto verifiers</title><style>{CSS}{v2.V2_CSS}{V3_CSS}</style></head><body>
<main class="page">
{nav(task_id, f'{task_id}-auto.html')}
<header><h1>{esc(spec["task_name"])}: auto verifiers</h1></header>
<div class="intro">
<p><strong>{count(n_own + code_checks, "check")} answered by code:</strong> the task's {count(n_own, "automatic check")}, unchanged from the V7 site, and {count(code_checks, "human check")} now answered by code. The code reads the delivered file directly (PDF and SVG text, fonts, sizes and colours), reads images and video frames by OCR, and measures pictures against the supplied files. Every check answers pass, fail or person: person means the code could not decide, so a person answers that row. No AI model is used.</p>
<p><a href="{task_id}-verifiers.html">Human verifiers</a> lists the checks people still answer. <a href="{V2_DIR}/automation.html">How every moved rule was tested</a>.</p>
</div>
{TOOLS.format(n=len(spec["deliverables"]), options=options)}
{moved_part}
<h2 class="part-head" id="own-auto">The task's automatic checks ({count(n_own, "check")})</h2>
<p class="auto-intro">File, format, size and content checks written as automatic checks from the start; the same as the V7 Auto verifiers tab.</p>
{own}
</main>{v2.FILTER_SCRIPT}<script src="https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5"></script></body></html>
"""
    (OUT / f'{task_id}-auto.html').write_text(page, encoding='utf-8')


def write_brief_page(task_id: str, spec: dict, assets: list[dict], outputs: list[dict]) -> None:
    """The v1 brief page, unchanged, with the v3 links. Previews are read from the v1 folder."""
    brand = spec['brand_identity']
    assets_html = render_assets(task_id, assets).replace('src="previews/', 'src="../annotation-pilot/previews/')
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(task_id)} · {esc(spec["task_name"])}</title><style>{CSS}{v2.V2_CSS}\n{font_css(brand)}</style></head><body>
<main class="page">
{nav(task_id, f'{task_id}.html')}
<header><h1>{esc(spec["task_name"])}</h1></header>
<section class="section" aria-labelledby="brief-title"><h2 id="brief-title">Client brief</h2><div class="brief-text">{esc(spec["client_brief"])}</div></section>
<section class="section" aria-labelledby="brand-title"><h2 id="brand-title">Brand identity</h2>{render_brand(brand)}</section>
<section class="section" aria-labelledby="assets-title"><h2 id="assets-title">Source assets ({len(assets)})</h2>{assets_html}</section>
<section class="section" aria-labelledby="outputs-title"><h2 id="outputs-title">Requested deliverables ({len(outputs)})</h2>{render_outputs(outputs, spec["deliverable_groups"])}</section>
</main>{DOWNLOAD_SCRIPT}<script src="https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5"></script></body></html>
"""
    (OUT / f'{task_id}.html').write_text(page, encoding='utf-8')


def write_index(summary: list[tuple[str, dict, list[dict]]]) -> None:
    people = lambda rules: [x for x in rules if x.get('answered_by') != 'code']
    coded = lambda rules: [x for x in rules if x.get('answered_by') == 'code']
    n = lambda rules: sum(len(x['rows']) for x in rules)
    tot = Counter()
    rows = []
    for tid, s, r in summary:
        hp, hc, own = n(people(r)), n(coded(r)), len(s['verifiers_auto'])
        tot.update(deliv=len(s['deliverables']), human=len(s['verifiers_human']), people=hp, coded=hc, own=own, rules=len(people(r)))
        rows.append(f'<tr><td><a href="{tid}-verifiers.html">{tid}</a></td><td>{esc(s["task_name"])}</td><td class="n">{len(s["deliverables"])}</td>'
                    f'<td class="n">{len(s["verifiers_human"]):,}</td><td class="n">{hp:,}</td><td class="n">{len(people(r))}</td>'
                    f'<td class="n">{own:,}</td><td class="n">{hc:,}</td><td class="n">{own + hc:,}</td></tr>')
    rows.append(f'<tr><td><strong>Total</strong></td><td></td><td class="n">{tot["deliv"]}</td><td class="n">{tot["human"]:,}</td>'
                f'<td class="n"><strong>{tot["people"]:,}</strong></td><td class="n">{tot["rules"]}</td><td class="n">{tot["own"]:,}</td>'
                f'<td class="n">{tot["coded"]:,}</td><td class="n"><strong>{tot["own"] + tot["coded"]:,}</strong></td></tr>')
    items = ''.join(
        f'<li><a href="{tid}.html">{tid} - {esc(s["task_name"])}</a><br><span class="vlinks">'
        f'<a href="{tid}-verifiers.html">Human verifiers ({n(people(r)):,} checks in {len(people(r))} rules)</a> · '
        f'<a href="{tid}-auto.html">Auto verifiers ({len(s["verifiers_auto"]) + n(coded(r)):,} checks: {len(s["verifiers_auto"])} automatic, '
        f'{n(coded(r)):,} moved from human)</a> · '
        f'<a href="../index.html#{tid}/trajectory">Trajectory</a> · <a href="groups/{tid}.json">Rules as JSON</a></span></li>'
        for tid, s, r in summary)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pilot task briefs v3</title><style>{CSS}{v2.V2_CSS}{V3_CSS}.vlinks{{font-size:14px;color:#5b6760}}.page li{{margin:0 0 12px}}</style></head><body>
<main class="page">
<h1>Pilot task briefs, v3: human checks now answered by code moved to Auto verifiers</h1>
<div class="scroll-x"><table class="summary"><thead><tr><th>Task</th><th>Name</th><th class="n">Deliverables</th><th class="n">Human checks (v2)</th><th class="n">For people now</th><th class="n">Rules for people</th><th class="n">Automatic checks</th><th class="n">Moved from human</th><th class="n">All by code</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table></div>
<h2>How to read a rule</h2>{v2.HOW_TO_READ}
<h2>Tasks</h2><ul class="rules-list">{items}</ul>
<h2>Downloads</h2>
<ul class="rules-list">
<li><a href="export/grouped_human_rules.csv">grouped_human_rules.csv</a>: one row per rule, with who answers it (person or code), its scope and every check ID it covers.</li>
<li><a href="export/grouped_human_rule_rows.csv">grouped_human_rule_rows.csv</a>: one row per check, with its rule, its values, its original wording and who answers it.</li>
</ul>
</main></body></html>
"""
    (OUT / 'index.html').write_text(page, encoding='utf-8')


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'groups').mkdir(exist_ok=True)
    (OUT / 'export').mkdir(exist_ok=True)
    catalog = v2.k_catalog()
    moves = v2.load_moves()
    rule_rows = [['task_id', 'rule_id', 'section', 'k_id', 'method', 'critical', 'only_if_present', 'scope', 'rule',
                  'method_note', 'check_count', 'deliverable_count', 'check_ids', 'answered_by', 'code_check']]
    check_rows = [['task_id', 'rule_id', 'check_id', 'output_id', 'deliverable', 'file', 'values', 'check', 'answered_by']]
    summary = []
    for task_id in TASK_IDS:
        folder = TASKS / task_id
        spec = json.loads((folder / 'TASK_SPEC.json').read_text(encoding='utf-8'))
        assets = json.loads((folder / 'ASSET_MANIFEST.json').read_text(encoding='utf-8'))
        outputs = json.loads((folder / 'OUTPUT_REGISTER.json').read_text(encoding='utf-8'))
        rules = v2.apply_moves(task_id, v2.build_rules(spec), moves)
        ids = Counter(r['check_id'] for rule in rules for r in rule['rows'])
        if set(ids) != {c['check_id'] for c in spec['verifiers_human']} or max(ids.values()) != 1:
            raise ValueError(f'{task_id}: a human check is lost or repeated')
        manifest = {a['filename']: a for a in assets}
        ctx = {'assets': manifest, 'thumbs': Thumbs(task_id, manifest), 'outputs': {o['output_id']: o for o in spec['deliverables']},
               'groups': {o: g['name'] for g in spec['deliverable_groups'] for o in g['outputs']}}
        limits = {rid: v.get('limits', []) for rid, v in (moves.get(task_id) or {}).items() if v['verdict'] == 'moves'}
        write_brief_page(task_id, spec, assets, outputs)
        write_human_page(task_id, spec, rules, catalog, ctx)
        write_auto_page(task_id, spec, rules, catalog, ctx, limits, run_results(task_id))
        payload = {'task_id': task_id, 'revision': REVISION, 'source': f'docs/gatsby-v7/tasks/{task_id}/TASK_SPEC.json verifiers_human',
                   'check_count': len(ids), 'rule_count': len(rules),
                   'checks_for_people': sum(len(r['rows']) for r in rules if r['answered_by'] != 'code'),
                   'checks_by_code': sum(len(r['rows']) for r in rules if r['answered_by'] == 'code'),
                   'rules': [v2.export_rule(task_id, r) for r in rules]}
        (OUT / 'groups' / f'{task_id}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        for rule in rules:
            labels = rule['slot_labels']
            rule_rows.append([task_id, rule['rule_id'], rule['section'], rule['k_id'], rule['method'], 'yes' if rule['critical'] else '',
                              'yes' if rule['conditional'] else '', rule['scope'], v2.template_text(rule['template'], labels),
                              v2.template_text(rule['note_template'], labels), len(rule['rows']), len({r['output_id'] for r in rule['rows']}),
                              ' '.join(r['check_id'] for r in rule['rows']), rule['answered_by'], ' '.join(rule['code_how'])])
            for r in rule['rows']:
                values = '; '.join(f'{k}={v}' for k, v in sorted(r['values'].items(), key=lambda kv: int(kv[0])))
                check_rows.append([task_id, rule['rule_id'], r['check_id'], r['output_id'], r['deliverable'], r['file'], values,
                                   r['check'], rule['answered_by']])
        summary.append((task_id, spec, rules))
        people = sum(len(r['rows']) for r in rules if r['answered_by'] != 'code')
        print(f'{task_id}: {len(ids)} human checks -> {people} for people, {len(ids) - people} by code; {len(spec["verifiers_auto"])} automatic')
    for name, data in (('grouped_human_rules.csv', rule_rows), ('grouped_human_rule_rows.csv', check_rows)):
        with (OUT / 'export' / name).open('w', newline='', encoding='utf-8') as f:
            csv.writer(f, lineterminator='\n').writerows(data)
    write_index(summary)
    total = sum(len(s['verifiers_human']) for _, s, _ in summary)
    coded = sum(len(r['rows']) for _, _, rules in summary for r in rules if r['answered_by'] == 'code')
    print(f'Total: {total} human checks -> {total - coded} for people, {coded} by code; '
          f'{sum(len(s["verifiers_auto"]) for _, s, _ in summary)} automatic checks')


if __name__ == '__main__':
    main()
