#!/usr/bin/env python
"""Publish the pilot handoff to GitHub Pages (docs/pilot/): render the 2 briefs (md->html),
the verifier mapping (csv->html table + raw csv), and a pilot index. Run from repo root."""
import csv, html, re, shutil
from pathlib import Path

ROOT = Path(".")
OUT = ROOT / "docs" / "pilot"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "https://deccanai-org.github.io/creative-ai-benchmark/pilot"

CSS = """
*{box-sizing:border-box} body{font:15px/1.6 -apple-system,Segoe UI,Inter,Helvetica,Arial,sans-serif;
color:#1c2230;background:#f6f7fb;margin:0;padding:0}
.wrap{max-width:940px;margin:0 auto;padding:28px 22px 80px}
a{color:#2456c7;text-decoration:none} a:hover{text-decoration:underline}
.top{background:#14233b;color:#fff;padding:18px 22px} .top .wrap{padding:0;max-width:940px}
.top a{color:#bcd0ff} .top h1{margin:0;font-size:18px;font-weight:700} .top .sub{color:#9fb3d6;font-size:13px;margin-top:2px}
h1{font-size:24px;letter-spacing:-.3px;margin:22px 0 6px} h2{font-size:18px;margin:26px 0 8px;border-bottom:1px solid #e3e7f0;padding-bottom:6px}
h3{font-size:15px;margin:18px 0 6px}
code{background:#eef1f7;border-radius:4px;padding:1px 6px;font-size:.9em;color:#2a3550}
blockquote{border-left:3px solid #c7d2e8;background:#eef2fa;margin:12px 0;padding:8px 14px;color:#41506b;border-radius:0 6px 6px 0}
hr{border:0;border-top:1px solid #e3e7f0;margin:22px 0}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px;background:#fff;border:1px solid #e3e7f0;border-radius:8px;overflow:hidden}
th,td{text-align:left;padding:8px 11px;border-bottom:1px solid #eef1f7;vertical-align:top}
th{background:#f0f3fa;font-weight:700;color:#2a3550} tr:last-child td{border-bottom:0}
ul,ol{margin:8px 0 8px 4px;padding-left:22px} li{margin:3px 0}
.card{background:#fff;border:1px solid #e3e7f0;border-radius:10px;padding:16px 18px;margin:14px 0}
.badge{display:inline-block;font-size:11px;font-weight:700;border-radius:20px;padding:2px 9px;margin-right:4px}
.b-deal{background:#fbe4e4;color:#b3261e} .b-mand{background:#fdf0da;color:#8a5a12} .b-qual{background:#e2f2e6;color:#1f7a3d}
.b-auto{background:#e6eefb;color:#2456c7} .b-exp{background:#efe9fb;color:#6a3fb0}
.k{font-weight:700;color:#2a3550;font-size:12px} .muted{color:#6b7488;font-size:13px}
.filelink{display:block;background:#fff;border:1px solid #e3e7f0;border-radius:8px;padding:12px 14px;margin:8px 0}
.filelink:hover{border-color:#2456c7} .filelink .n{font-weight:700} .filelink .d{color:#6b7488;font-size:13px}
"""

def esc(s): return html.escape(s, quote=False)

def inline(s):
    s = esc(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", s)
    return s

def md_to_html(md):
    lines = md.split("\n"); out = []; i = 0
    para = []; quote = []; li = []
    ctx = {"list": None}   # 'ul' | 'ol' | None
    def flush_para():
        if para: out.append(f"<p>{inline(' '.join(para))}</p>"); para.clear()
    def flush_quote():
        if quote: out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>"); quote.clear()
    def flush_li():
        if li: out.append(f"<li>{inline(' '.join(li))}</li>"); li.clear()
    def close_list():
        flush_li()
        if ctx["list"] == "ul": out.append("</ul>")
        elif ctx["list"] == "ol": out.append("</ol>")
        ctx["list"] = None
    def flush_all():
        flush_para(); flush_quote(); close_list()
    while i < len(lines):
        raw = lines[i]; ln = raw.rstrip(); stripped = ln.strip()
        if ln.startswith("|"):                      # table block
            flush_all()
            tbl = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                tbl.append(lines[i].strip()); i += 1
            rows = [[c.strip() for c in r.strip("|").split("|")] for r in tbl]
            rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]  # drop |---| sep
            if rows:
                out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in rows[0]) + "</tr></thead><tbody>")
                for r in rows[1:]:
                    out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
                out.append("</tbody></table>")
            continue
        if not stripped: flush_all(); i += 1; continue
        if stripped.startswith("> "): flush_para(); close_list(); quote.append(stripped[2:]); i += 1; continue
        flush_quote()
        is_ul = ln.startswith("- "); is_ol = bool(re.match(r"\d+\. ", ln))
        is_cont = raw.startswith(" ") and not is_ul and not is_ol   # wrapped continuation line
        if ln.startswith("### "): flush_all(); out.append(f"<h3>{inline(ln[4:])}</h3>")
        elif ln.startswith("## "): flush_all(); out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("# "): flush_all(); out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif stripped == "---": flush_all(); out.append("<hr>")
        elif is_ul:
            flush_para(); flush_li()
            if ctx["list"] != "ul": close_list(); out.append("<ul>"); ctx["list"] = "ul"
            li.append(ln[2:])
        elif is_ol:
            flush_para(); flush_li()
            if ctx["list"] != "ol": close_list(); out.append("<ol>"); ctx["list"] = "ol"
            li.append(re.sub(r"^\d+\. ", "", ln, count=1))
        elif is_cont and ctx["list"]:               # continuation of the current list item
            li.append(stripped)
        else:
            close_list(); para.append(stripped)     # accumulate wrapped paragraph lines
        i += 1
    flush_all()
    return "\n".join(out)

def page(title, body, back=True):
    nav = '<p class="muted"><a href="index.html">← Pilot handoff</a></p>' if back else ""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{esc(title)}</title>
<style>{CSS}</style></head><body>
<div class=top><div class=wrap><h1>StudioBench — Creative AI Benchmark</h1><div class=sub>Pilot handoff</div></div></div>
<div class=wrap>{nav}{body}</div></body></html>"""

# ---- render the two briefs ----
for tid in ["AO-13", "AO-115"]:
    md = (ROOT / "pilot_briefs" / f"{tid}.md").read_text(encoding="utf-8")
    (OUT / f"{tid}.html").write_text(page(f"{tid} — brief", md_to_html(md)), encoding="utf-8")

# ---- verifier mapping: raw csv + html table ----
shutil.copy2("pilot_verifier_mapping.csv", OUT / "pilot_verifier_mapping.csv")
rows = list(csv.DictReader(open("pilot_verifier_mapping.csv")))
WB = {"dealbreaker": "b-deal", "mandatory": "b-mand", "quality": "b-qual"}
body = ["<h1>Verifier mapping</h1>",
        f'<p class="muted">Task list + verifier mapping for the 2 pilot tasks — {len(rows)} checks. '
        '<a href="pilot_verifier_mapping.csv">Download CSV ↓</a></p>']
for tid in ["AO-13", "AO-115"]:
    sub = [r for r in rows if r["task_id"] == tid]
    h = sub[0]
    body.append(f'<h2>{tid} — {esc(h["task_title"])}</h2>')
    body.append(f'<p class="muted">{esc(h["family"])} · {esc(h["difficulty"])} · {h["tool_calls"]} tool-calls · '
                f'{h["num_deliverables"]} deliverables · {len(sub)} verifiers</p>')
    body.append("<table><thead><tr><th>#</th><th>Check</th><th>How</th><th>Pass condition</th><th>Feeds</th><th>Weight</th></tr></thead><tbody>")
    for r in sub:
        tb = "b-auto" if r["type"] == "auto" else "b-exp"
        wb = WB.get(r["weight"], "b-mand")
        body.append(f'<tr><td>{r["verifier_no"]}</td><td>{esc(r["check"])}</td>'
                    f'<td><span class="badge {tb}">{r["type"]}</span></td>'
                    f'<td class=muted>{esc(r["pass_condition"])}</td>'
                    f'<td class=k>{esc(r["feeds_capability"].split()[0])}</td>'
                    f'<td><span class="badge {wb}">{r["weight"]}</span></td></tr>')
    body.append("</tbody></table>")
(OUT / "verifiers.html").write_text(page("Verifier mapping", "\n".join(body)), encoding="utf-8")

# ---- pilot index ----
idx = f"""<h1>StudioBench Pilot — task handoff</h1>
<p class=muted>Two image tasks for the end-to-end pipeline dry run. Both are real freelance briefs
(fictional brands), both fully executable via the Adobe connectors.</p>
<div class=card>
<h3>The 2 tasks</h3>
<table><thead><tr><th>Task</th><th>What it is</th><th>Family</th><th>Difficulty</th></tr></thead><tbody>
<tr><td><a href="AO-13.html">AO-13</a></td><td>El Vecino Cocina — Meta ad photo-asset prep (grade, scroll-stop variants, cut-out, 3 ad ratios, logo vector)</td><td>Photo &amp; Image</td><td>T3</td></tr>
<tr><td><a href="AO-115.html">AO-115</a></td><td>Rukmini Silverworks — 925 jewelry catalog: isolate 6 SKUs on pure white + transparent PNG</td><td>Photo &amp; Image</td><td>T4</td></tr>
</tbody></table>
</div>
<h2>Files</h2>
<a class=filelink href="verifiers.html"><span class=n>Verifier mapping (task list + verifiers)</span><span class=d>The scoring checklist for both tasks — view as table, or download the CSV.</span></a>
<a class=filelink href="AO-13.html"><span class=n>AO-13 — Creative brief</span><span class=d>El Vecino Cocina Meta ad asset pack: brief, deliverables, specs.</span></a>
<a class=filelink href="AO-115.html"><span class=n>AO-115 — Creative brief</span><span class=d>Rukmini Silverworks jewelry catalog: brief, deliverables, specs.</span></a>
<a class=filelink href="pilot_verifier_mapping.csv"><span class=n>pilot_verifier_mapping.csv</span><span class=d>Raw CSV (task_id, check, type, pass_condition, capability, weight).</span></a>"""
(OUT / "index.html").write_text(page("StudioBench Pilot", idx, back=False), encoding="utf-8")

print("built docs/pilot/:", ", ".join(sorted(p.name for p in OUT.iterdir())))
print("live base:", BASE)
