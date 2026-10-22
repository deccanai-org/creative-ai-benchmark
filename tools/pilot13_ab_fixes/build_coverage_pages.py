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
.cov td.nv{background:#fff4dc;color:#7a5200}
.method{display:inline-block;font-size:10.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;border-radius:3px;padding:1px 5px;margin-right:4px;background:#e8eef9;color:#2a4f8a}
.method.estimate{background:#f3e8f9;color:#6b2a8a}
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
    nv = sum(1 for c in cells if 'not_verified' in c)
    missing = len(cells) - covered - na - nv
    mapped = {cid for cell in cells for cid in cell.get('checks', [])}
    if mapped != set(checks):
        raise ValueError(f'{tid}: coverage and live checks differ: {sorted(mapped ^ set(checks))}')
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
            elif 'not_verified' in cell:
                tds.append(f'<td class="nv" title="{html.escape(cell["not_verified"] + " Excluded from scoring.")}">Not scored</td>')
            else:
                tds.append('<td class="missing">missing</td>')
        rows.append(f'<tr><th class="rule" scope="row"><span class="kind">{html.escape(KIND.get(r["kind"], r["kind"]))}</span>{html.escape(r["rule"])}</th>{"".join(tds)}</tr>')
    per = []
    for o in outputs:
        items = {'auto': [], 'human': []}
        excluded = []
        seen = set()
        for r in rules:
            cell = r['cells'][o['output_id']]
            if cell.get('checks'):
                for c in cell['checks']:
                    if c in checks and c not in seen:
                        seen.add(c)
                        kind = 'auto' if checks[c]['type'] == 'auto' else 'human'
                        m = checks[c].get('method', 'look')
                        note=checks[c].get('method_note','')
                        tag = '' if kind == 'auto' else f'<span class="method {m}">{m.capitalize()}</span><span class="muted">{html.escape(note)}</span><br>'
                        items[kind].append(f'<li><code>{html.escape(c)} · {kind}</code><br>{html.escape(checks[c]["check"])}<br>{tag}</li>')
            elif 'not_verified' in cell:
                excluded.append(f'<li>{html.escape(r["rule"])}<br><strong>Not scored:</strong> {html.escape(cell["not_verified"])}</li>')
        lists = ''.join(f'<h3>{kind.capitalize()} verifiers ({len(items[kind])})</h3><ul>{"".join(items[kind])}</ul>' for kind in ('auto', 'human'))
        if excluded:
            lists += f'<h3>Unscored design targets ({len(excluded)})</h3><p>These are not verifiers and are excluded from the score denominator.</p><ul>{"".join(excluded)}</ul>'
        per.append(f'<details class="deliv" id="{html.escape(o["output_id"])}"><summary>{html.escape(o["name"])} <code>{html.escape(Path(o["path"]).name)}</code> · {len(seen)} unique checks · {len(excluded)} unscored targets</summary>{lists}</details>')
    doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(tid)} verifier coverage</title><style>{CSS}{EXTRA_CSS}</style></head><body><main class="page">
<p class="eyebrow"><a href="index.html">Verifier coverage</a> · <a href="../{tid}.html">Task brief</a></p>
<h1>{html.escape(spec["task_name"])}</h1>
<p class="muted">A cell names the verifier for that rule and file. “n/a” means the rule does not apply. “Not scored” means it applies but the requested finished file lacks the evidence needed to verify it. It is not counted as covered. Hover for the reason; full details are also listed below.</p>
<p>{html.escape(cov['scoring_policy'])}</p><p><a href="../measurement-guide.html">Measurement guide and calculators</a></p>
<div class="stats"><div><strong>{len(rules)}</strong>rules</div><div><strong>{len(outputs)}</strong>deliverables</div><div><strong>{covered}</strong>cells with checks</div><div><strong>{na}</strong>not applicable</div><div><strong>{nv}</strong>not scored</div><div><strong>{missing}</strong>missing</div></div>
<div class="cov-wrap"><table class="cov"><thead><tr><th class="rule">Rule</th>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>
<h2>Checklist by deliverable</h2>{"".join(per)}
</main></body></html>'''
    (COV / f'{tid}.html').write_text(doc, encoding='utf-8')
    return {'task': tid, 'name': spec['task_name'], 'rules': len(rules), 'outputs': len(outputs), 'covered': covered, 'na': na, 'not_verified': nv, 'missing': missing}


def main():
    stats = [page(tid) for tid in TASK_IDS if (COV / f'{tid}.json').is_file()]
    rows = ''.join(f'<tr><td><a href="{s["task"]}.html">{s["task"]}</a></td><td>{html.escape(s["name"])}</td><td>{s["rules"]}</td><td>{s["outputs"]}</td><td>{s["covered"]}</td><td>{s["na"]}</td><td>{s["not_verified"]}</td><td>{s["missing"]}</td></tr>' for s in stats)
    index = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Verifier coverage</title><style>{CSS}{EXTRA_CSS}</style></head><body><main class="page">
<p class="eyebrow"><a href="../index.html">Pilot task briefs</a></p><h1>Verifier coverage</h1>
<p class="muted">Each pilot's rules against its deliverables. Unverifiable design targets are marked “Not scored”, with reasons, and excluded from the score denominator. They are not counted as covered. Auto and Human lists below each table contain each check once per file, even when it supports several rules.</p>
<p><a href="../measurement-guide.html">Measurement guide and calculators</a></p>
<div class="cov-wrap"><table class="cov"><thead><tr><th>Task</th><th class="rule">Name</th><th>Rules</th><th>Deliverables</th><th>Cells with checks</th><th>Not applicable</th><th>Not scored</th><th>Missing</th></tr></thead><tbody>{rows}</tbody></table></div>
</main></body></html>'''
    (COV / 'index.html').write_text(index, encoding='utf-8')
    print(json.dumps(stats, indent=1))


if __name__ == '__main__':
    main()
