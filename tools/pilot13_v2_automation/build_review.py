"""Step-1 review page: which v2 human rules code can answer, how, and what needs a decision."""
import csv, html, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(sys.argv[1]); PLAN = Path(sys.argv[2]); OUT = Path(sys.argv[3])
sys.path.insert(0, str(ROOT / 'scripts'))
from build_v7_annotation_pilot_v2 import template_text  # noqa: E402

esc = lambda v: html.escape(str(v), quote=True)
IDS = ['PHOTO-04','PHOTO-06','PHOTO-08','PHOTO-10','PHOTO-19','PHOTO-20','PHOTO-24','PHOTO-26','PHOTO-28','LAYOUT-15','LAYOUT-12','VECTOR-04','MOTION-11']
LIVE = 'https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot-v2/'
METHOD = {'file': 'Read from the file', 'ocr': 'OCR', 'match': 'Image matching', 'file+match': 'File + image matching', 'ocr+match': 'OCR + image matching'}
QUESTIONS = [
    ('lines', r'which lines count', 'Which lines the 65-character limit covers',
     'Count every line of text on the deliverable except its largest text (titles and names).'),
    ('body', r'body|running text|caption|fine[- ]print|cloth note|biography|\bcopy\b', 'What counts as body text, captions and fine print',
     'Body text: any line that belongs to a paragraph of two or more lines. Caption: a line of three or more words directly under or beside a photograph. Fine print: text in the smallest size used on the deliverable.'),
    ('heading', r'headline|heading|standfirst|display|title line', 'What counts as a headline or heading',
     'Headline: the largest line of text that is not a name, price or wordmark. Main heading: the largest line in the heading typeface. Subheading: a heading-typeface line smaller than the main heading.'),
    ('accents', r'hairline|gold|metallic', 'Where accent colours may appear',
     'Hairline: a line 1 pt thick or less. Small label: text 9 pt or smaller. Gold or metallic: any colour outside the palette with a gold hue.'),
    ('roles', r'billing|table|product name|running foot|label', 'Other named text roles (billing, table, product name, running foot)',
     'Each role is found by the type style the brand assigns to it (for example product names are text in the product-name style).'),
    ('link', r'tied to', 'Linking a line to the item it describes',
     'A fabric line, care line, price or colourway belongs to the nearest product or style name above it, or beside it on the same row.'),
    ('shapes', r'ground|panel|band|tile', 'What counts as a ground, panel or band',
     'Any filled shape (not a photo) covering at least 5% of the page.'),
    ('overlay', r'overlay', 'What counts as an overlay on a photograph',
     'Any semi-transparent or gradient fill drawn over a placed photo. Opaque shapes partly covering a photo are left to a person.'),
    ('other', r'.', 'Other open points', 'Listed per rule below.'),
]


def question_of(note):
    for key, rx, *_ in QUESTIONS:
        if re.search(rx, note, re.I):
            return key


def main():
    plan = json.loads(PLAN.read_text())
    rules = {}
    for tid in IDS:
        for r in json.loads((ROOT / 'docs/gatsby-v7/annotation-pilot-v2/groups' / f'{tid}.json').read_text())['rules']:
            rules[(tid, r['rule_id'])] = r
    for p in plan:
        r = rules[(p['task'], p['rule'])]
        p['sentence'] = template_text(r['template'], r['slot_labels'])
        p['check_ids'] = [x['check_id'] for x in r['rows']]
    status_tot = defaultdict(Counter)
    per_task = defaultdict(Counter)
    for p in plan:
        status_tot[p['status']]['rules'] += 1; status_tot[p['status']]['checks'] += p['checks']
        per_task[p['task']][p['status']] += p['checks']
        if p['status'] == 'auto':
            per_task[p['task']]['m:' + p['method']] += p['checks']
    auto_checks = status_tot['auto']['checks']; nd = status_tot['needs_definition']['checks']

    def rule_row(p, extra=''):
        link = f'{LIVE}{p["task"]}-verifiers.html#{p["rule"]}'
        crit = ' <span class="badge b-crit">Critical</span>' if p['critical'] else ''
        return (f'<tr><td class="id"><a href="{link}" target="_blank" rel="noopener">{esc(p["task"])} {esc(p["rule"])}</a></td>'
                f'<td class="n">{p["checks"]}</td><td>{esc(p["sentence"])}{crit}</td><td>{extra}</td></tr>')

    def table(head, rows):
        return (f'<div class="scroll-x"><table class="list"><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead>'
                f'<tbody>{"".join(rows)}</tbody></table></div>')

    # summary
    order = [('auto', 'Code answers it'), ('needs_definition', 'Code can answer it once you define a term'),
             ('later', 'Colour sampled on an image (later)'), ('human', 'Stays with people')]
    summary = ''.join(f'<tr><td>{label}</td><td class="n">{status_tot[k]["rules"]}</td><td class="n">{status_tot[k]["checks"]}</td>'
                      f'<td class="n">{status_tot[k]["checks"] / 6312:.0%}</td></tr>' for k, label in order)
    methods = Counter()
    for p in plan:
        if p['status'] == 'auto':
            methods[p['method']] += p['checks']
    method_rows = ''.join(f'<tr><td>{METHOD[m]}</td><td class="n">{sum(1 for p in plan if p["status"]=="auto" and p["method"]==m)}</td>'
                          f'<td class="n">{n}</td></tr>' for m, n in methods.most_common())
    task_rows = ''.join(
        f'<tr><td>{t}</td><td class="n">{sum(per_task[t].values()) - sum(v for k, v in per_task[t].items() if k.startswith("m:"))}</td>'
        f'<td class="n">{per_task[t]["auto"]}</td><td class="n">{per_task[t]["m:file"] + per_task[t]["m:file+match"]}</td>'
        f'<td class="n">{per_task[t]["m:ocr"] + per_task[t]["m:ocr+match"]}</td><td class="n">{per_task[t]["m:match"]}</td>'
        f'<td class="n">{per_task[t]["needs_definition"]}</td><td class="n">{per_task[t]["later"]}</td><td class="n">{per_task[t]["human"]}</td></tr>'
        for t in IDS)

    # decisions needed
    qblocks = []
    for key, _, title, proposal in QUESTIONS:
        sel = [p for p in plan if p['status'] == 'needs_definition' and question_of(p['note']) == key]
        if not sel:
            continue
        n = sum(p['checks'] for p in sel)
        rows = [rule_row(p, esc(p['note'])) for p in sel]
        qblocks.append(f'<section class="q"><h3>{esc(title)} <small>{len(sel)} rules · {n} checks</small></h3>'
                       f'<p><strong>Proposed definition:</strong> {esc(proposal)}</p>'
                       f'<details><summary>Show the {len(sel)} rules</summary>{table(["Rule", "Checks", "Rule wording", "What must be defined"], rows)}</details></section>')

    # automatic, per task
    ablocks = []
    for t in IDS:
        sel = [p for p in plan if p['task'] == t and p['status'] == 'auto']
        if not sel:
            continue
        n = sum(p['checks'] for p in sel)
        rows = [rule_row(p, f'<span class="badge">{esc(METHOD[p["method"]])}</span> {esc(p["pass_rule"])}') for p in sel]
        ablocks.append(f'<details class="task"><summary><strong>{t}</strong> · {len(sel)} rules · {n} checks</summary>'
                       f'{table(["Rule", "Checks", "Rule wording", "How code answers it"], rows)}</details>')

    def simple(status, why_title):
        blocks = []
        for t in IDS:
            sel = [p for p in plan if p['task'] == t and p['status'] == status]
            if not sel:
                continue
            n = sum(p['checks'] for p in sel)
            rows = [rule_row(p, esc(p['note'])) for p in sel]
            blocks.append(f'<details class="task"><summary><strong>{t}</strong> · {len(sel)} rules · {n} checks</summary>'
                          f'{table(["Rule", "Checks", "Rule wording", why_title], rows)}</details>')
        return ''.join(blocks)

    reasons = Counter()
    for p in plan:
        if p['status'] == 'human':
            reasons[p['note']] += p['checks']
    reason_rows = ''.join(f'<tr><td>{esc(k)}</td><td class="n">{v}</td></tr>' for k, v in reasons.most_common())

    css = """
:root{color-scheme:light;--ink:#202724;--muted:#5b6760;--line:#dce3df;--soft:#f4f7f5;--green:#1e7059;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--ink);background:#fff;font-size:15px;line-height:1.52}
*{box-sizing:border-box}body{margin:0;background:#fff}.page{max-width:1180px;margin:auto;padding:28px 24px 64px}
h1{font-size:26px;line-height:1.2;margin:0 0 8px}h2{font-size:20px;margin:34px 0 10px;border-top:1px solid var(--line);padding-top:24px}h3{font-size:16px;margin:0 0 6px}h3 small{font-weight:400;color:var(--muted);font-size:13px}
p{margin:0 0 10px;max-width:96ch}.lede{color:#33403a}.muted{color:var(--muted)}
table{border-collapse:collapse}.sum td,.sum th{padding:6px 12px;border-bottom:1px solid var(--line);text-align:left}.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.sum th{background:var(--soft);font-weight:600}.scroll-x{overflow-x:auto}
.list{width:100%;font-size:13px;margin:8px 0}.list th{background:var(--soft);text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);font-weight:600}.list td{padding:6px 8px;border-bottom:1px solid #edf0ed;vertical-align:top}
.list td.id{white-space:nowrap;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.list a{color:#176348}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;background:#e3efe8;color:#1d5a42;font-size:11.5px;font-weight:600;margin-right:4px}.b-crit{background:#fbe3e1;color:#8a1f17}
.q{border:1px solid var(--line);border-left:3px solid var(--green);border-radius:6px;padding:12px 14px;margin:0 0 12px;background:#fafbfa}
details{margin:6px 0}summary{cursor:pointer;padding:6px 0}details.task{border-bottom:1px solid var(--line)}
.note{border:1px solid #cfe0d6;background:#f6faf7;border-radius:8px;padding:12px 16px;margin:14px 0}.note li{margin:0 0 4px}
a:focus-visible,summary:focus-visible{outline:2px solid #146344;outline-offset:2px}
@media(max-width:720px){.page{padding:20px 16px 48px}h1{font-size:23px}}
"""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Automation plan, step 1</title><style>{css}</style></head><body><main class="page">
<h1>Which v2 human checks can code answer?</h1>
<p class="lede">Step 1 of the plan: every one of the 1,500 v2 rules (6,312 human checks) read and sorted. A rule counts as automatic only when its answer is a fact code can read exactly from the delivered file, with no judgement. Nothing has been moved yet: this is the list to approve.</p>
<div class="scroll-x"><table class="sum"><thead><tr><th>Decision</th><th class="n">Rules</th><th class="n">Checks</th><th class="n">Share</th></tr></thead><tbody>{summary}</tbody></table></div>
<p>If every automatic rule passes the step-4 test, annotators answer <strong>{6312 - auto_checks:,}</strong> checks instead of 6,312. With your definitions approved as well, <strong>{6312 - auto_checks - nd:,}</strong>.</p>
<div class="note"><p><strong>How the automatic checks stay safe</strong></p><ul>
<li>Deterministic: fixed tool versions (Tesseract 5.5.3, OpenCV 5.0.0, PyMuPDF 2.0 on MuPDF 1.28.5) and fixed settings, so the same file always gets the same answer.</li>
<li>Never a false pass from a failed read: if code cannot find or read what it needs, that check is not answered automatically and a person answers it.</li>
<li>"Nothing of this kind appears" checks on images pass only when OCR has read every piece of text clearly.</li>
<li>Each pass rule comes from the check's own wording, including any allowance it states (for example "in any letter case", "in any clear form such as 25 SEP").</li>
<li>Every converted check keeps its check ID, K question and critical flag.</li></ul></div>
<h3>Automatic checks by method</h3>
<div class="scroll-x"><table class="sum"><thead><tr><th>Method</th><th class="n">Rules</th><th class="n">Checks</th></tr></thead><tbody>{method_rows}</tbody></table></div>
<h3 style="margin-top:18px">Per task (checks)</h3>
<div class="scroll-x"><table class="sum"><thead><tr><th>Task</th><th class="n">Human checks</th><th class="n">Automatic</th><th class="n">File</th><th class="n">OCR</th><th class="n">Matching</th><th class="n">Needs a definition</th><th class="n">Colour on images</th><th class="n">Stays human</th></tr></thead><tbody>{task_rows}</tbody></table></div>

<h2>1. Decisions needed from you</h2>
<p>These rules name a role ("body text", "headline", "panel") or link two items without saying how to find them. Each question below covers several rules; one answer settles all of them. The proposed definitions are suggestions to accept, change or reject.</p>
{''.join(qblocks)}

<h2>2. Automatic, by task</h2>
<p class="muted">Each rule links to its place on the live v2 page.</p>
{''.join(ablocks)}

<h2>3. Colour sampled on images (later)</h2>
<p>Flat colours of type, grounds or marks on PNG, JPG and video frames. Code must first find the element in the picture, so these start as a measurement shown to annotators and move only once that proves reliable.</p>
{simple('later', 'Why later')}

<h2>4. Stays with people</h2>
<div class="scroll-x"><table class="sum"><thead><tr><th>Why</th><th class="n">Checks</th></tr></thead><tbody>{reason_rows}</tbody></table></div>
{simple('human', 'Why it stays human')}
</main></body></html>"""
    OUT.write_text(page, encoding='utf-8')
    # machine-readable list
    with (OUT.with_suffix('.csv')).open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(['task', 'rule', 'k_id', 'critical', 'checks', 'formats', 'decision', 'method', 'operation', 'how_code_answers', 'open_point_or_reason', 'rule_wording', 'check_ids'])
        for p in plan:
            w.writerow([p['task'], p['rule'], p['k'], 'yes' if p['critical'] else '', p['checks'], ' '.join(p['formats']), p['status'],
                        p['method'], p['op'], p['pass_rule'], p['note'], p['sentence'], ' '.join(p['check_ids'])])
    print('written', OUT, OUT.with_suffix('.csv'))


main()
