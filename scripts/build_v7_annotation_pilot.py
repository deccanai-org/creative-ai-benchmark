#!/usr/bin/env python3
"""Build standalone pilot briefs and the matching annotation-sheet import rows."""

from __future__ import annotations

import csv
import html
import json
import re
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "docs/gatsby-v7/tasks"
OUT = ROOT / "docs/gatsby-v7/annotation-pilot"
RUN_SOURCES = ROOT.parents[1] / "benchmark_runs/pilot_v7_hybrid_2026-09-28"
REFRESH = ROOT.parents[1] / "reviews/pilot13-refresh-2026-10-14"
SHEET_EXPORT = REFRESH / "sheet_rows.json"
BASE_URL = "https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot/"
TASK_IDS = [
    "PHOTO-04", "PHOTO-06", "PHOTO-08", "PHOTO-10", "PHOTO-19",
    "PHOTO-20", "PHOTO-24", "PHOTO-26", "PHOTO-28", "LAYOUT-15",
    "LAYOUT-12", "VECTOR-04", "MOTION-11",
]
RUBRICS = [
    "1. Completeness", "2. Feasibility Integrity", "3. Realism / Difficulty",
    "4. Brand Coherence", "5. No-Answer Leakage", "6. Provenance / Licensing",
    "7. Decision Quality", "8. Hallucination / Contradiction",
]


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def label(key: str) -> str:
    special = {
        "founded_place_size": "Origin and scale",
        "brand_assets_status": "Brand assets",
        "price_positioning": "Price positioning",
        "type_system": "Type system",
        "palette_rules": "Palette rules",
        "signature_type_move": "Signature type move",
    }
    return special.get(key, key.replace("_", " ").capitalize())


def render_value(value: object) -> str:
    if isinstance(value, dict):
        return '<dl class="detail-list">' + "".join(
            f"<div><dt>{esc(label(key))}</dt><dd>{render_value(item)}</dd></div>"
            for key, item in value.items()
        ) + "</dl>"
    if isinstance(value, list):
        return '<ul class="data-list">' + "".join(
            f"<li>{render_value(item)}</li>" for item in value
        ) + "</ul>"
    return f"<span>{esc(value)}</span>"


def type_is_serif(face: str) -> bool:
    return bool(re.search(
        r"serif|didot|garamond|caslon|bodoni|playfair|freight|georgia|times|"
        r"minion|baskerville|clarendon|tiempos|canela|lyon|chronicle|publico|"
        r"financier|instrument|miller|piazzolla|boska|gt super",
        face, re.IGNORECASE,
    )) and not bool(re.search(r"sans", face, re.IGNORECASE))


def font_css(brand: dict) -> str:
    return "\n".join(
        '@font-face{font-family:"brand-' + font['family'] + '";src:url("' + font['url'] + '") format("truetype");font-weight:'
        + str(int(font['weight_range'][0])) + ' ' + str(int(font['weight_range'][-1])) + ';font-style:normal;font-display:swap;}'
        for font in brand.get('font_files', [])
    )


def font_style(row: dict) -> str:
    return esc('font-family:"brand-' + row.get('font_family', 'Inter') + '",sans-serif;font-weight:' + str(row.get('font_weight', 400)) + ';font-synthesis:none;')


def render_type_system(brand: dict) -> str:
    system = brand["type_system"]
    sizes = [float(match.group()) for row in system["scale"]
             if (match := re.search(r"\d+(?:\.\d+)?", str(row.get("size", ""))))]
    largest = max(sizes, default=1)
    faces = list(dict.fromkeys(f['family'] for f in brand.get('font_files', [])))
    parts = [
        '<div class="tsys"><p class="tsys-eyebrow">// Type system</p>',
        '<div class="tsys-head"><div>',
        f'<p class="tsys-name" style="{font_style(system["scale"][0])}">'
        f'{esc(system.get("brand_name") or brand["brand_name"])}</p>',
        f'<p class="tsys-tag">{esc(system.get("tagline", ""))}</p>',
        '</div><div class="tsys-faces">',
    ]
    for face in faces:
        serif = " serif" if type_is_serif(face) else ""
        parts.append(
            f'<div><div class="tsys-aa{serif}" style="{font_style({"font_family": face})}">Aa</div>'
            f'<div class="tsys-facename">{esc(face)}</div></div>'
        )
    parts.append('</div></div>')
    for key in ("specimen_note", "application", "measurement_notes", "font_access"):
        if system.get(key):
            parts.append(f'<p class="tsys-note">{esc(system[key])}</p>')
    for row in system["scale"]:
        match = re.search(r"\d+(?:\.\d+)?", str(row.get("size", "")))
        size = float(match.group()) if match else 0
        preview_size = max(12, min(34, 10 + 22 * size / largest)) if size else 14
        serif = " serif" if type_is_serif(row.get("family", "")) else ""
        tracking = f' · tracking {esc(row["tracking"])}' if row.get("tracking") else ""
        leading = f' / {esc(row["leading"])}' if row.get("leading") else ""
        parts.append(
            '<div class="tsys-row">'
            f'<div class="tsys-step">{esc(row.get("step", ""))}</div>'
            f'<div><p class="tsys-role">{esc(row.get("role", ""))}</p>'
            f'<div class="tsys-meta">{esc(row.get("family", ""))} · '
            f'{esc(row.get("size", ""))}{leading}<br>'
            f'{esc(row.get("weight", ""))}{tracking}</div></div>'
            f'<div><div class="tsys-sample{serif}" style="font-size:{preview_size:.1f}px;{font_style(row)}">'
            f'{esc(row.get("sample", ""))}</div>'
            f'<div class="tsys-note">{esc(row.get("note", ""))}</div></div></div>'
        )
    parts.append('<div class="tsys-foot"><ul>')
    parts.extend(f'<li>{esc(rule)}</li>' for rule in system.get("rules", []))
    parts.append('</ul></div></div>')
    return "".join(parts)


def render_brand(brand: dict) -> str:
    parts = [
        '<div class="brand-profile">',
        f'<h3 class="brand-profile-name">{esc(brand["brand_name"])}</h3>',
        f'<p class="brand-about">{esc(brand["about"])}</p>',
        '<div class="brand-overview">',
        f'<div><h3>Audience</h3><p>{esc(brand["audience"])}</p></div>',
        f'<div><h3>Positioning</h3><p>{esc(brand["price_positioning"])}</p></div>',
        '</div>',
        '<h3>Palette</h3><div class="swatches rich">',
    ]
    for colour in brand["palette"]:
        code = colour["hex"]
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", code):
            raise ValueError(f"Invalid brand hex: {code}")
        role = colour["role"]
        required = " req" if role.lower().startswith("mandatory") else ""
        parts.append(
            '<div class="swatch">'
            f'<i style="background:{code}" aria-hidden="true"></i>'
            f'<span><strong>{esc(colour["name"])}</strong><br><code>{esc(code)}</code> '
            f'<em class="pal-role{required}">{esc(role.lower())}</em>'
            f'<small class="pal-use">{esc(colour["usage"])}</small></span></div>'
        )
    parts.append("</div>")
    rules = brand["palette_rules"]
    parts.append('<div class="pal-rules"><p class="pal-rules-h">Colour rules</p><dl>')
    for key, title in (
        ("distribution", "Distribution"), ("opacity", "Opacity"),
        ("forbidden", "Not allowed"), ("photography", "Photography"),
    ):
        if rules.get(key):
            parts.append(f'<dt>{title}</dt><dd>{esc(rules[key])}</dd>')
    parts.append('</dl></div>')
    parts.append('<h3>Typography</h3>')
    parts.append(render_type_system(brand))
    parts.append(f'<h3>Voice</h3><p>{esc(brand["voice"])}</p>')
    parts.append(f'<h3>Existing brand materials</h3><p>{esc(brand["brand_assets_status"])}</p>')
    parts.append('</div>')
    return "".join(parts)


def source_preview(task_id: str, asset: dict) -> str:
    name = asset["filename"]
    suffix = Path(name).suffix.lower()
    url = esc(asset["public_url"])
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg"}:
        return f'<img loading="lazy" src="{url}" alt="Preview of {esc(name)}">'
    local_file = RUN_SOURCES / task_id / "source" / name
    for candidate in (REFRESH / 'upload' / task_id / name, REFRESH / 'sources' / task_id / name):
        if candidate.is_file():
            local_file = candidate
            break
    if suffix == ".pdf" and local_file.is_file():
        preview = OUT / "previews" / f"{task_id}-{Path(name).stem}.png"
        if not preview.exists():
            preview.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [shutil.which('pdftoppm') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/bin/override/pdftoppm'), "-f", "1", "-singlefile", "-scale-to", "480",
                 "-png", str(local_file), str(preview.with_suffix(""))],
                check=True, stdout=subprocess.DEVNULL,
            )
        return f'<img loading="lazy" src="previews/{esc(preview.name)}" alt="First page of {esc(name)}">'
    if suffix in {".csv", ".txt"} and local_file.is_file():
        sample = "\n".join(local_file.read_text(encoding="utf-8-sig", errors="replace").splitlines()[:6])
        return f'<pre class="file-excerpt">{esc(sample[:500])}</pre>'
    if suffix == '.ttf':
        return f'<span class="font-preview" style="{font_style(asset)}">Aa 0123</span>'
    if suffix in {'.mp4','.mov','.webm'}:
        return f'<video controls preload="metadata" src="{url}" aria-label="{esc(name)}"></video>'
    if suffix in {'.wav','.mp3','.m4a'}:
        return f'<audio controls preload="metadata" src="{url}" aria-label="{esc(name)}"></audio>'
    return f'<span class="file-icon">{esc(suffix.lstrip(".").upper())}</span>'


def render_assets(task_id: str, assets: list[dict]) -> str:
    parts = ['<div class="asset-grid">']
    for asset in assets:
        name = asset["filename"]
        is_pdf = Path(name).suffix.lower() == ".pdf"
        url = esc(asset["public_url"])
        size = (f'{asset["bytes"] / 1024:.1f} KB' if asset["bytes"] < 1024 * 1024
                else f'{asset["bytes"] / 1024 / 1024:.2f} MB')
        role = asset["role"].replace("_", " ").capitalize()
        details = f"PDF · {role} · {size}" if is_pdf else f"{role} · {size}"
        view_label = "View full PDF" if is_pdf else "Open"
        media = Path(name).suffix.lower() in {'.mp4','.mov','.webm','.wav','.mp3','.m4a'}
        preview = (f'<div class="asset-preview">{source_preview(task_id, asset)}</div>' if media else
                   f'<a class="asset-preview" href="{url}" target="_blank" rel="noopener noreferrer" aria-label="Open {esc(name)} in a new tab">{source_preview(task_id, asset)}</a>')
        parts.append(
            '<article class="asset-card">'
            + preview +
            '<div class="asset-info">'
            f'<strong title="{esc(name)}">{esc(name)}</strong>'
            f'<p>{esc(details)}</p>'
            f'<p>{esc(asset.get("description", ""))}</p>'
            '<div class="asset-actions">'
            f'<a href="{url}" target="_blank" rel="noopener noreferrer">{view_label}</a>'
            f'<a href="{url}" download="{esc(name)}" data-download>Download</a>'
            '</div></div></article>'
        )
    parts.append("</div>")
    return "".join(parts)


def output_spec_text(spec: dict) -> str:
    parts = [str(spec["format"]).upper()] if spec.get("format") else []
    if "width" in spec and "height" in spec:
        dimensions = f'{spec["width"]} x {spec["height"]} px'
        parts.append(dimensions + (" (original dimensions)" if spec.get("source_dimensions") else ""))
    if "width_mm" in spec and "height_mm" in spec:
        parts.append(f'{spec["width_mm"]} x {spec["height_mm"]} mm')
    if "pages" in spec:
        parts.append(f'{spec["pages"]} page' + ("s" if spec["pages"] != 1 else ""))
    if "long_edge" in spec:
        parts.append(f'Long edge: {spec["long_edge"]} px')
    if "safe_area" in spec:
        insets = ", ".join(f"{edge} {amount} px" for edge, amount in spec["safe_area"].items())
        parts.append(f"Keep the booking action inside these margins: {insets}")
    if "template_reference" in spec:
        parts.append(f'Template: {spec["template_reference"]}')
    extra = {'duration_seconds':'Duration (seconds)', 'ratio':'Aspect ratio', 'audio':'Audio',
             'frame_rate':'Frames per second', 'video_codec':'Video codec', 'pixel_format':'Pixel format',
             'transparent':'Transparent background', 'closed_paths':'Closed vector paths'}
    for key, title in extra.items():
        if key in spec:
            value = spec[key]
            if isinstance(value, dict): value = ' to '.join(str(v) for v in value.values())
            if isinstance(value, list): value = ' to '.join(str(v) for v in value)
            if isinstance(value, bool): value = 'Yes' if value else 'No'
            parts.append(f'{title}: {value}')
    handled = {"format", "width", "height", "width_mm", "height_mm", "pages",
               "long_edge", "source_dimensions", "safe_area", "template_reference", *extra}
    unknown = set(spec) - handled
    if unknown:
        raise ValueError(f"Unformatted output specifications: {sorted(unknown)}")
    return " · ".join(parts)


def render_outputs(outputs: list[dict], groups: list[dict]) -> str:
    group_names = {group["id"]: group["name"] for group in groups}
    parts = ['<div class="outputs">']
    last_group = None
    for output in outputs:
        group_id = output.get("group_id")
        if group_id != last_group:
            parts.append(f'<h3>{esc(group_names.get(group_id, "Requested files"))}</h3>')
            last_group = group_id
        spec = output.get("spec", {})
        spec_text = output_spec_text(spec)
        record = output.get("source_record") or {}
        source_parts = []
        if record.get("table"):
            row_label = f', row {record["row_number"]}' if record.get("row_number") else ""
            source_parts.append(record["table"] + row_label)
        if output.get("source_image"):
            source_parts.append(output["source_image"])
        parts.append(
            '<article class="output-row">'
            f'<div><strong>{esc(output["name"])}</strong><code>{esc(Path(output["path"]).name)}</code>'
            f'<small>{esc(spec_text)}</small></div>'
        )
        if source_parts:
            parts.append(f'<p class="output-source"><strong>Source:</strong> {esc(" · ".join(source_parts))}</p>')
        commission = output.get('commission', {})
        if commission:
            bullets = [f'<strong>Purpose:</strong> {esc(commission["purpose"])}',
                       f'<strong>Placement:</strong> {esc(commission["channel"])}',
                       f'<strong>Audience:</strong> {esc(commission["audience"])}']
            bullets += [esc(v) for v in commission['content']]
            # One export line per deliverable; settings are sentences, so join them.
            bullets.append('<strong>Export:</strong> ' + ' '.join(esc(v) for v in commission['export_settings']))
            parts.append('<ul class="output-requirements">' + ''.join(f'<li>{v}</li>' for v in bullets) + '</ul>')
        parts.append("</article>")
    parts.append("</div>")
    return "".join(parts)


CSS = """
:root{color-scheme:light;font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#202724;background:#fff;font-size:15px;line-height:1.52}
*{box-sizing:border-box}body{margin:0}.page{max-width:1050px;margin:auto;padding:28px 32px 56px}h1,h2,h3,p{margin-top:0}h1{font-size:27px;line-height:1.2;margin:8px 0 9px}h2{font-size:20px;line-height:1.3;margin-bottom:18px}h3{font-size:16px;line-height:1.35;margin:28px 0 12px}.eyebrow{color:#59645f;font-weight:700;font-size:12px;text-transform:uppercase;letter-spacing:.08em}.subline{color:#59645f;margin-bottom:28px}.section{border-top:1px solid #dce3df;padding-top:25px;margin-top:27px}.brief-text{white-space:pre-wrap;overflow-wrap:anywhere;max-width:83ch}.brand-name{font-size:20px;font-weight:700;margin-bottom:2px}.tagline{font-style:italic;color:#51605a}.brand-facts,.detail-list{margin:0}.brand-facts>div,.detail-list>div{display:grid;grid-template-columns:minmax(150px,23%) 1fr;gap:12px;padding:10px 0;border-bottom:1px solid #edf0ed}.brand-facts dt,.detail-list dt{font-weight:700;color:#52605a}.brand-facts dd,.detail-list dd{margin:0;min-width:0}.brand-facts dd p,.detail-list dd p{margin:0}.data-list{margin:0;padding-left:18px}.palette-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.palette-item{display:flex;gap:12px;border:1px solid #e0e6e1;border-radius:6px;padding:10px;min-width:0}.palette-item .swatch{width:55px;min-width:55px;height:55px;border-radius:3px;border:1px solid #0002}.palette-item strong{display:inline-block;margin-right:6px}.palette-item code{font-size:12px;color:#57645e}.palette-item small{display:block;text-transform:uppercase;color:#66726d;font-size:11px;font-weight:700;letter-spacing:.04em}.palette-item p{font-size:13px;margin:5px 0 0}.type-system>.detail-list>div{grid-template-columns:minmax(150px,23%) 1fr}.type-system .data-list li{margin-bottom:8px}.asset-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:13px}.asset-card{border:1px solid #dce3df;border-radius:6px;overflow:hidden;min-width:0;background:#fff}.asset-preview{display:flex;height:190px;align-items:center;justify-content:center;background:#f2f5f3;border-bottom:1px solid #e3e8e4;overflow:hidden;color:#386951}.asset-preview img{display:block;width:100%;height:100%;object-fit:contain}.asset-info{padding:11px 12px}.asset-info strong{display:block;font-size:13px;overflow-wrap:anywhere;line-height:1.35}.asset-info p{font-size:12px;color:#65716a;margin:4px 0 9px}.asset-actions{display:flex;gap:14px}.asset-actions a{font-size:12px;color:#176348;text-decoration:underline;text-underline-offset:2px}.file-excerpt{font-size:10px;line-height:1.35;white-space:pre-wrap;overflow-wrap:anywhere;margin:0;padding:12px;width:100%;height:100%;color:#364a3e}.file-icon{font-size:24px;font-weight:700;color:#6d8577}.output-row{border:1px solid #e0e6e1;border-radius:6px;padding:13px 15px;margin-bottom:9px}.output-row>div:first-child{display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 14px}.output-row strong{font-size:14px}.output-row code{font-size:12px;color:#375d4d;overflow-wrap:anywhere}.output-row small{display:block;width:100%;font-size:12px;color:#5b6760}.output-requirements{font-size:13px;padding-left:20px;margin:8px 0 0}.output-requirements li{margin:3px 0}a:focus-visible{outline:2px solid #146344;outline-offset:2px}@media(max-width:720px){.page{padding:20px 18px 40px}.asset-grid,.palette-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.brand-facts>div,.detail-list>div,.type-system>.detail-list>div{display:block}.brand-facts dt,.detail-list dt{margin-bottom:3px}.asset-preview{height:150px}}@media(max-width:470px){.asset-grid,.palette-grid{grid-template-columns:1fr}.asset-preview{height:220px}h1{font-size:23px}}
"""
CSS += ".output-source{font-size:12px;color:#5b6760;margin:7px 0 0}"
CSS += '.asset-preview video{width:100%;height:100%;object-fit:contain}.asset-preview audio{width:95%}.font-preview{font-size:38px}.asset-card{display:flex;flex-direction:column}.asset-info{flex:1}*{letter-spacing:0!important}'
CSS += """
.brief-text{line-height:1.68;color:#303b35}.brief-text::first-line{font-weight:700;font-size:17px;color:#202724}
.page{max-width:1500px}.asset-grid{grid-template-columns:repeat(auto-fill,minmax(240px,1fr))}
.brand-profile-name{font-size:20px;line-height:1.3;margin:0 0 15px}
.brand-about{max-width:100ch;margin:0 0 22px}
.brand-overview{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:24px}
.brand-overview h3{margin:12px 0}.brand-overview p{line-height:1.55}
.swatches.rich{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px}
.swatches.rich .swatch{display:flex;align-items:flex-start;gap:9px;min-width:0;border:1px solid #dce1de;border-radius:6px;padding:10px 12px;background:#fcfcfb;font-size:12px}
.swatches.rich .swatch i{flex:0 0 30px;width:30px;height:30px;border:1px solid #888;border-radius:50%}
.swatches.rich .swatch span{min-width:0}.swatches.rich strong{font-weight:500}.swatches.rich code{font-size:11.5px}
.pal-role{display:inline-block;margin-top:5px;padding:2px 8px;border-radius:999px;font-style:normal;font-size:10.5px;letter-spacing:.03em;background:#eef1ef;color:#59635f;overflow-wrap:anywhere}
.pal-role.req{background:#dcefe5;color:#235f43;font-weight:700}
.pal-use{display:block;margin-top:5px;color:#59635f;font-size:11.5px;line-height:1.45;overflow-wrap:anywhere}
.pal-rules{margin:14px 0 6px;border:1px solid #dce1de;border-left:3px solid #1e7059;border-radius:6px;padding:12px 14px;background:#fcfcfb}
.pal-rules-h{margin:0 0 6px;font-weight:700;font-size:13px}
.pal-rules dl{display:grid;grid-template-columns:120px minmax(0,1fr);gap:6px 14px;margin:0}
.pal-rules dt{color:#59635f;font-size:12px}.pal-rules dd{margin:0;font-size:12.5px;line-height:1.5;overflow-wrap:anywhere}
.tsys{border:1px solid #dce1de;border-left:3px solid #b13a36;border-radius:6px;padding:18px 20px 6px;margin:6px 0 14px;background:#fcfcfb}
.tsys-eyebrow{color:#b13a36;font-size:11px;letter-spacing:.14em;text-transform:uppercase;margin:0 0 6px}
.tsys-head{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;border-bottom:1px solid #dce1de;padding-bottom:14px;margin-bottom:2px;flex-wrap:wrap}
.tsys-name{font-size:30px;line-height:1.1;letter-spacing:.01em;margin:0;overflow-wrap:anywhere}
.tsys-name.serif,.tsys-aa.serif,.tsys-sample.serif{font-family:Georgia,"Times New Roman",serif}
.tsys-tag{color:#59635f;font-size:12.5px;margin:4px 0 0}
.tsys-faces{display:flex;gap:22px;text-align:center;flex-wrap:wrap}
.tsys-faces>div{min-width:64px;max-width:210px}.tsys-aa{font-size:26px;line-height:1.1}
.tsys-facename{color:#59635f;font-size:11px;margin-top:2px;overflow-wrap:anywhere}
.tsys-row{display:grid;grid-template-columns:28px minmax(150px,210px) minmax(0,1fr);gap:14px;align-items:baseline;padding:13px 0;border-bottom:1px solid #dce1de}
.tsys-step{color:#b13a36;font-size:12px;font-variant-numeric:tabular-nums}
.tsys-role{font-size:13.5px;margin:0 0 3px}.tsys-meta{color:#59635f;font-size:12px;line-height:1.5;font-variant-numeric:tabular-nums}
.tsys-sample{line-height:1.25;overflow-wrap:anywhere}.tsys-note{color:#59635f;font-size:11.5px;margin-top:4px}
.tsys-foot{border-top:1px solid #dce1de;margin-top:2px;padding:11px 0 12px}.tsys-foot ul{margin:5px 0 0;padding-left:18px}
.tsys-foot li{color:#59635f;font-size:12px;line-height:1.55}
@media(max-width:720px){.tsys{padding:16px 16px 5px}.tsys-row{grid-template-columns:24px minmax(0,1fr);gap:8px 12px}.tsys-row>div:last-child{grid-column:2}.tsys-head{align-items:flex-start}.tsys-name{font-size:27px}.tsys-faces{text-align:left;gap:10px 18px}}
@media(max-width:720px){.brand-overview{grid-template-columns:1fr;gap:4px}.pal-rules dl{grid-template-columns:1fr;gap:3px}.pal-rules dd{margin-bottom:8px}}
@media(max-width:470px){.tsys-row>div:last-child{grid-column:1/-1}.tsys-name{font-size:24px}.tsys-faces>div{max-width:140px}}
"""

DOWNLOAD_SCRIPT = """
<script>
document.addEventListener('click', async (event) => {
  const link = event.target.closest('a[data-download]');
  if (!link) return;
  event.preventDefault();
  const original = link.textContent;
  link.textContent = 'Downloading...';
  try {
    const response = await fetch(link.href, {mode: 'cors', cache: 'no-store'});
    if (!response.ok) throw new Error(`Asset returned ${response.status}`);
    const objectUrl = URL.createObjectURL(await response.blob());
    const saveLink = document.createElement('a');
    saveLink.href = objectUrl;
    saveLink.download = link.getAttribute('download');
    document.body.append(saveLink);
    saveLink.click();
    saveLink.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  } catch (error) {
    window.open(link.href, '_blank', 'noopener');
  } finally {
    link.textContent = original;
  }
});
</script>
"""


def write_page(task_id: str, spec: dict, assets: list[dict], outputs: list[dict]) -> None:
    title = spec["task_name"]
    brand = spec["brand_identity"]
    content = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(task_id)} · {esc(title)}</title><style>{CSS}\n{font_css(brand)}</style></head><body>
<main class="page">
<header><h1>{esc(title)}</h1></header>
<section class="section" aria-labelledby="brief-title"><h2 id="brief-title">Client brief</h2><div class="brief-text">{esc(spec["client_brief"])}</div></section>
<section class="section" aria-labelledby="brand-title"><h2 id="brand-title">Brand identity</h2>{render_brand(brand)}</section>
<section class="section" aria-labelledby="assets-title"><h2 id="assets-title">Source assets ({len(assets)})</h2>{render_assets(task_id, assets)}</section>
<section class="section" aria-labelledby="outputs-title"><h2 id="outputs-title">Requested deliverables ({len(outputs)})</h2>{render_outputs(outputs, spec["deliverable_groups"])}</section>
</main>{DOWNLOAD_SCRIPT}<script src="https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5"></script></body></html>
"""
    (OUT / f"{task_id}.html").write_text(content, encoding="utf-8")


def platform_verifiers(verifiers: list[dict], outputs: list[dict]) -> list[dict]:
    chosen = []
    for output in outputs:
        output_id = output["output_id"]
        output_checks = [v for v in verifiers if v["output_id"] == output_id]
        auto = [v for v in output_checks if v["type"] == "auto"]
        human = [v for v in output_checks if v["type"] == "human"]
        # The platform's Phase 2 review should stay usable, while the full bank
        # remains available through the canonical verifier JSON linked in the sheet.
        # Auto checks are run by code, never asked of annotators (2026-10-21).
        chosen.extend(human[:4 if len(outputs) <= 7 else 2])
        chosen.extend(v for v in human if v.get("platform_priority"))
        if output_id == "producer-card-r015":
            chosen.extend(v for v in human if "no photograph presented as Priya" in v["check"])
    seen = set()
    result = []
    for item in chosen:
        if item["check_id"] in seen:
            continue
        seen.add(item["check_id"])
        result.append({"verifier_question": f'{len(result) + 1}. {item["check"]}', "verifer_radio": "", "comment_box": ""})
    return result


def write_review_verifiers(task_id: str, verifiers: list[dict]) -> None:
    bank = OUT / "verifier-bank"
    bank.mkdir(parents=True, exist_ok=True)
    fields = ("check_id", "output_id", "type", "output_reference", "check", "method", "method_note", "reference_assets")
    review_only = [{key: item[key] for key in fields if key in item} for item in verifiers]
    (bank / f"{task_id}.json").write_text(
        json.dumps(review_only, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def sheet_row(index: int, task_id: str, assets: list[dict], verifiers: list[dict], outputs: list[dict]) -> list[object]:
    asset_names = ["Brief", "Brand identity", "Typography: supplied families, weights and access"] + [a["filename"] for a in assets]
    rubrics = []
    for heading in RUBRICS:
        scoped = ["Brief", "Brand identity"] if heading.startswith(('3.', '7.')) else asset_names
        rubrics.append({
            "side_headers": heading,
            "AcceptRejectRadio": "",
            "AssestRepeater": [{
                "placeholder_assest_comment": f"What is wrong with the {name}?",
                "asset_options": [{"label": name}],
                "Assest_comment": "",
            } for name in scoped],
        })
    review_checks = platform_verifiers(verifiers, outputs)
    row = [
        f"gatsby_v7_pilot_{task_id.lower().replace('-', '_')}",
        json.dumps(rubrics, ensure_ascii=False, separators=(",", ":")),
        json.dumps(review_checks, ensure_ascii=False, separators=(",", ":")),
        index, "", "NORMAL", "", BASE_URL + task_id + ".html",
        BASE_URL + "verifier-bank/" + task_id + ".json",
        f"https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/tasks/{task_id}/ASSET_MANIFEST.json",
        len(assets), len(outputs), len(review_checks), len(verifiers),
    ]
    if len(row[1]) > 49000 or len(row[2]) > 49000:
        raise ValueError(f"Sheet cell too large for {task_id}: {len(row[1])}, {len(row[2])}")
    return row


SECONDS_PER_CHECK = 10


def question_text(index: int, check: dict) -> str:
    """Annotator-facing question, with an explicit checking method."""
    method = check['method']
    if method not in ('look', 'measure', 'estimate') or not check.get('method_note'):
        raise ValueError(f"Missing checking guidance: {check['check_id']}")
    prefix = '[Look] ' if method == 'look' else f'[{method.capitalize()}: {check["method_note"]}] '
    return f"{index}. {prefix}{check['check']}"


def deliverable_rows(task_id: str, verifiers: list[dict], outputs: list[dict]) -> list[list[object]]:
    """One sheet row per deliverable carrying every human check for it (no sampling, no auto checks)."""
    rows = []
    for output in outputs:
        human = [v for v in verifiers if v["output_id"] == output["output_id"] and v["type"] == "human"]
        questions = [{"verifier_question": question_text(i, v), "verifer_radio": "", "comment_box": ""} for i, v in enumerate(human, 1)]
        cell = json.dumps(questions, ensure_ascii=False, separators=(",", ":"))
        if len(cell) > 49000:
            raise ValueError(f"Sheet cell too large for {task_id}/{output['output_id']}: {len(cell)}")
        rows.append([
            f"gatsby_v7_pilot_{task_id.lower().replace('-', '_')}__{output['output_id']}", "[]", cell, "", "", "NORMAL", "",
            BASE_URL + task_id + ".html", BASE_URL + "verifier-bank/" + task_id + ".json",
            f"https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/tasks/{task_id}/ASSET_MANIFEST.json",
            "", 1, len(questions), len(human),
            "deliverable_verifiers", task_id, output["output_id"], output["name"], Path(output["path"]).name,
            round(len(questions) * SECONDS_PER_CHECK / 60, 1),
            sum(1 for v in human if v.get("method") == "measure"), sum(1 for v in human if v.get("method") == "estimate"),
        ])
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [[
        "task_id", "MainSectionRepeater", "VerifiersRepeater", "uniqueId",
        "taskTags", "taskCategory", "CustomVerifiersRepeater", "url_link",
        "full_verifiers_url", "asset_manifest_url", "asset_count", "output_count",
        "platform_verifier_count", "full_verifier_count",
        "row_type", "task", "output_id", "deliverable", "deliverable_file", "estimated_minutes", "measure_checks", "estimate_checks",
    ]]
    verifier_rows = []
    for index, task_id in enumerate(TASK_IDS, 1):
        folder = TASKS / task_id
        spec = json.loads((folder / "TASK_SPEC.json").read_text(encoding="utf-8"))
        assets = json.loads((folder / "ASSET_MANIFEST.json").read_text(encoding="utf-8"))
        outputs = json.loads((folder / "OUTPUT_REGISTER.json").read_text(encoding="utf-8"))
        verifiers = json.loads((folder / "VERIFIERS.json").read_text(encoding="utf-8"))
        if len(outputs) != len(spec["deliverables"]):
            raise ValueError(f"Output mismatch for {task_id}")
        if any(not asset["public_url"].startswith("https://annotationprod.s3.ap-south-1.amazonaws.com/") for asset in assets):
            raise ValueError(f"Unexpected asset host for {task_id}")
        write_page(task_id, spec, assets, outputs)
        write_review_verifiers(task_id, verifiers)
        row = sheet_row(index, task_id, assets, verifiers, outputs)
        # 2026-10-22: the task row carries the input-asset rubric only; every human check is on a deliverable row.
        row[2] = "[]"
        row[12] = 0
        row += ["task_inputs", task_id, "", "", "", "", 0, 0]
        rows.append(row)
        drows = deliverable_rows(task_id, verifiers, outputs)
        verifier_rows += drows
        print(f"{task_id}: {len(assets)} assets, {len(outputs)} deliverable rows, {sum(r[12] for r in drows)} human checks (all), about {round(sum(r[19] for r in drows))} min at {SECONDS_PER_CHECK}s each")
    rows += verifier_rows
    for n, r in enumerate(rows[1:], 1):
        r[3] = n
    SHEET_EXPORT.parent.mkdir(parents=True, exist_ok=True)
    SHEET_EXPORT.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    current_export = ROOT / 'tools/pilot13_ab_fixes/round3/sheet_rows_2026-10-22.json'
    current_export.parent.mkdir(parents=True, exist_ok=True)
    current_export.write_bytes(SHEET_EXPORT.read_bytes())
    # Same rows for a manual Google Sheets import (File > Import > Replace current sheet, text kept as text).
    with current_export.with_suffix('.csv').open('w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerows(rows)
    links = ''.join(f'<li><a href="{tid}.html">{tid} - {esc(json.loads((TASKS/tid/"TASK_SPEC.json").read_text())["task_name"])}</a></li>' for tid in TASK_IDS)
    coverage = ''
    if (OUT/'coverage'/'index.html').is_file():
        coverage = '<h2>Verifier coverage</h2><p>For each task: every brief and brand-identity constraint against every deliverable, with the verifier that checks it. <a href="coverage/index.html">Open the coverage tables</a>.</p>'
    (OUT/'index.html').write_text(f'<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pilot task briefs</title><style>{CSS}</style><main class="page"><h1>Pilot task briefs</h1><ul>{links}</ul>{coverage}</main></html>')
    print(f"Sheet payload: {SHEET_EXPORT}")


if __name__ == "__main__":
    main()
