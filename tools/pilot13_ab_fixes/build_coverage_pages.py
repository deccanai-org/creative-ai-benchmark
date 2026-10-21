#!/usr/bin/env python3
"""Render docs/gatsby-v7/annotation-pilot/coverage/<ID>.html and index.html from coverage/<ID>.json.

Each page answers: is every brief and brand-identity constraint checked on every deliverable? Rows are rules,
columns are deliverables, cells name the verifier (hover or the per-deliverable checklist below shows its text).
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_v7_annotation_pilot import CSS, TASK_IDS, TASKS, OUT  # noqa: E402

COV = OUT / 'coverage'
KIND = {'brand': 'Brand identity', 'type': 'Typography', 'brief': 'Brief', 'deliverable': 'Deliverable requirement'}
EXTRA_CSS = """
.cov-wrap{overflow-x:auto;border:1px solid #dce3df;border-radius:6px;margin:14px 0 26px}
table.cov{border-collapse:collapse;font-size:12px;min-width:100%}
.cov th,.cov td{border-bottom:1px solid #edf0ed;border-right:1px solid #edf0ed;padding:6px 8px;vertical-align:top;text-align:left}
.cov thead th{position:sticky;top:0;background:#f6f8f6;font-weight:700;white-space:nowrap}
.cov th.rule{position:sticky;left:0;background:#fff;min-width:300px;max-width:420px;font-weight:400;white-space:normal;z-index:1}
.cov thead th.rule{background:#f6f8f6;z-index:2}
.cov .kind{display:block;color:#59645f;font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px}
.cov td.ok{background:#eef7f1;color:#1f5c40;white-space:nowrap}.cov td.na{background:#f4f4f2;color:#7a837e}
.cov td.missing{background:#fde8e6;color:#9b2c22;font-weight:700}
.stats{display:flex;gap:22px;flex-wrap:wrap;margin:6px 0 4px}.stats div{font-size:13px}.stats strong{font-size:20px;display:block}
details.deliv{border:1px solid #e0e6e1;border-radius:6px;padding:10px 14px;margin-bottom:8px}
details.deliv summary{cursor:pointer;font-weight:700}details.deliv ul{margin:8px 0 0;padding-left:18px}
details.deliv li{margin:5px 0;font-size:13px}details.deliv code{font-size:11.5px;color:#375d4d}
.muted{color:#5b6760;font-size:13px}
"""


def page(tid):
    spec = json.loads((TASKS / tid / 'TASK_SPEC.json').read_text())
    cov = json.loads((COV / f'{tid}.json').read_text())
    checks = {c['check_id']: c for c in spec['verifiers_auto'] + spec['verifiers_human']}
    outputs = spec['deliverables']
    rules = cov['rules']
    cells = [r['cells'][o['output_id']] for r in rules for o in outputs]
    covered = sum(1 for c in cells if c.get('checks'))
    na = sum(1 for c in cells if 'na' in c)
    missing = len(cells) - covered - na
    head = ''.join(f'<th title="{html.escape(o["name"])}">{html.escape(Path(o["path"]).name)}</th>' for o in outputs)
    rows = []
    for r in rules:
        tds = []
        for o in outputs:
            cell = r['cells'][o['output_id']]
            if cell.get('checks'):
                label = ', '.join(c.split('/')[-1] for c in cell['checks'])
                tip = ' | '.join(checks[c]['check'] for c in cell['checks'] if c in checks)
                tds.append(f'<td class="ok" title="{html.escape(tip)}">{html.escape(label)}</td>')
            elif 'na' in cell:
                tds.append(f'<td class="na" title="{html.escape(cell["na"])}">n/a</td>')
            else:
                tds.append('<td class="missing">missing</td>')
        rows.append(f'<tr><th class="rule" scope="row"><span class="kind">{html.escape(KIND.get(r["kind"], r["kind"]))}</span>{html.escape(r["rule"])}</th>{"".join(tds)}</tr>')
    per = []
    for o in outputs:
        items = []
        for r in rules:
            cell = r['cells'][o['output_id']]
            if cell.get('checks'):
                for c in cell['checks']:
                    if c in checks:
                        kind = 'auto' if checks[c]['type'] == 'auto' else 'human'
                        items.append(f'<li>{html.escape(r["rule"])}<br><code>{html.escape(c.split("/")[-1])} · {kind}</code> {html.escape(checks[c]["check"])}</li>')
        per.append(f'<details class="deliv"><summary>{html.escape(o["name"])} <code>{html.escape(Path(o["path"]).name)}</code> · {len(items)} checks</summary><ul>{"".join(items)}</ul></details>')
    doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(tid)} verifier coverage</title><style>{CSS}{EXTRA_CSS}</style></head><body><main class="page">
<p class="eyebrow"><a href="index.html">Verifier coverage</a> · <a href="../{tid}.html">Task brief</a></p>
<h1>{html.escape(spec["task_name"])}</h1>
<p class="muted">Every brief and brand-identity constraint, and every requirement listed on a deliverable, against every deliverable. A cell names the verifier that checks that rule on that file (hover for its text); “n/a” means the rule does not apply to that file (hover for why).</p>
<div class="stats"><div><strong>{len(rules)}</strong>rules</div><div><strong>{len(outputs)}</strong>deliverables</div><div><strong>{covered}</strong>cells checked</div><div><strong>{na}</strong>not applicable</div><div><strong>{missing}</strong>missing</div></div>
<div class="cov-wrap"><table class="cov"><thead><tr><th class="rule">Rule</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<h2>Checklist by deliverable</h2>{"".join(per)}
</main></body></html>'''
    (COV / f'{tid}.html').write_text(doc, encoding='utf-8')
    return {'task': tid, 'name': spec['task_name'], 'rules': len(rules), 'outputs': len(outputs), 'covered': covered, 'na': na, 'missing': missing}


def main():
    stats = [page(tid) for tid in TASK_IDS if (COV / f'{tid}.json').is_file()]
    rows = ''.join(f'<tr><td><a href="{s["task"]}.html">{s["task"]}</a></td><td>{html.escape(s["name"])}</td><td>{s["rules"]}</td><td>{s["outputs"]}</td><td>{s["covered"]}</td><td>{s["na"]}</td><td>{s["missing"]}</td></tr>' for s in stats)
    index = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Verifier coverage</title><style>{CSS}{EXTRA_CSS}</style></head><body><main class="page">
<p class="eyebrow"><a href="../index.html">Pilot task briefs</a></p><h1>Verifier coverage</h1>
<p class="muted">For each pilot task: is every brief and brand-identity constraint checked on every individual deliverable? Rule-by-deliverable tables, generated from the published verifiers (2026-10-21).</p>
<div class="cov-wrap"><table class="cov"><thead><tr><th>Task</th><th class="rule">Name</th><th>Rules</th><th>Deliverables</th><th>Cells checked</th><th>Not applicable</th><th>Missing</th></tr></thead><tbody>{rows}</tbody></table></div>
</main></body></html>'''
    (COV / 'index.html').write_text(index, encoding='utf-8')
    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main()
