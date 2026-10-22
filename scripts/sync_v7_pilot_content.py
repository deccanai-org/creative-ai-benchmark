#!/usr/bin/env python3
"""Synchronize pilot brief, brand and verifier specifications from TASK_SPEC."""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

from build_v7_annotation_pilot import ROOT, TASKS, TASK_IDS, REFRESH, render_outputs, render_type_system, font_css


PAGE = ROOT / "docs/gatsby-v7"
DATA_SCRIPT = re.compile(r'(<script\b[^>]*\bid=[\"\']data[\"\'][^>]*>)(.*?)(</script>)', re.S)


def refreshed_assets_verified() -> bool:
    path = PAGE / 'annotation-pilot/asset-access-status.json'
    if not path.exists():
        return False
    audit = json.loads(path.read_text())
    return (audit.get('revision') == 'pilot13_inputs_2026_10_14'
            and audit.get('failures') == 0
            and audit.get('refreshed_assets_hash_verified') == 73)


def merge_checks(existing: list, canonical: list) -> list:
    """Keep mirror order/field order stable while updating the check specifications."""
    by_id = {c["check_id"]: c for c in canonical}
    result = []
    for old in existing:
        if old["check_id"] in by_id:
            new = by_id.pop(old["check_id"])
            result.append({**{k: new[k] for k in old if k in new}, **new})
    result.extend(by_id.values())
    return result


def reconcile(path: Path, content: str, check: bool) -> None:
    if path.exists() and path.read_bytes().decode("utf-8") == content:
        return
    if check:
        raise ValueError(f"Stale content: {path.relative_to(ROOT)}")
    path.write_text(content, encoding="utf-8")
    print(path.relative_to(ROOT))


def sync_csv(path: Path, specs: dict, check: bool) -> None:
    text = path.read_bytes().decode("utf-8")
    lines = text.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(text, newline=""))
    headers = next(reader)
    by_code = {spec["task_code"]: spec for spec in specs.values()}
    end = reader.line_num
    result = lines[:end]
    brand_fields = {
        "Founded / place / size": "founded_place_size", "About": "about",
        "Audience": "audience", "Price positioning": "price_positioning",
        "Brand assets status": "brand_assets_status",
        "Typography": "typography", "Signature type move": "signature_type_move",
    }
    for values in reader:
        start, end = end, reader.line_num
        row = dict(zip(headers, values))
        original = row.copy()
        spec = by_code.get(row.get("Task code"))
        if spec:
            if "Client brief" in row:
                row["Client brief"] = spec["client_brief"]
            if "Review page" in row:
                row["Review page"] = "https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/#" + spec["new_id"]
            if 'Assets' in row: row['Assets']=str(len(spec['assets']))
            if 'Deliverables' in row:
                row['Deliverables']='\n'.join(g['name']+': '+str(sum(o['group_id']==g['id'] for o in spec['deliverables']))+' files' for g in spec['deliverable_groups'])
            if 'Palette rules' in row: row['Palette rules']=json.dumps(spec['brand_identity']['palette_rules'],ensure_ascii=False)
            for column, field in brand_fields.items():
                if column in row:
                    row[column] = spec["brand_identity"][field]
            for column, field in (("Auto verifiers", "verifiers_auto"), ("Human verifiers", "verifiers_human")):
                if column in row:
                    row[column] = str(len(spec[field]))
        if row == original:
            result.extend(lines[start:end])
        else:
            stream = io.StringIO(newline="")
            newline = "\r\n" if lines[end - 1].endswith("\r\n") else "\n"
            writer = csv.writer(stream, lineterminator=newline)
            writer.writerow([row[column] for column in headers])
            result.append(stream.getvalue())
    reconcile(path, "".join(result), check)


def sync_detail_csv(path: Path, specs: dict, kind: str, check: bool) -> None:
    text=path.read_text(); reader=csv.DictReader(io.StringIO(text)); headers=reader.fieldnames
    by_code={s['task_code']:s for s in specs.values()}; emitted=set(); rows=[]
    for row in reader:
        spec=by_code.get(row['Task code'])
        if not spec: rows.append(row); continue
        code=spec['task_code']
        if code in emitted: continue
        emitted.add(code)
        common={'Task code':code,'Task name':spec['task_name'],'Family':spec['family']}
        if kind=='assets':
            for i,a in enumerate(spec['assets'],1):
                pending = a.get('revision') == 'pilot13_inputs_2026_10_14' and not refreshed_assets_verified()
                rows.append({**common,'Asset #':i,'Filename':a['filename'],'Role':a['role'],'Type':Path(a['filename']).suffix.lstrip('.'),'Bytes':a.get('bytes',''),'SHA-256':a.get('sha256',''),'State':a.get('state',''),'S3 URI':a.get('s3_uri',''),'HTTPS object':a['public_url'],'S3 console':'https://ap-south-1.console.aws.amazon.com/s3/object/annotationprod?region=ap-south-1&prefix='+quote(a.get('s3_key',''),safe=''),'Upload status':'uploaded; public access pending policy approval' if pending else 'verified public access 2026-10-14'})
        elif kind=='verifiers':
            for c in spec['verifiers_auto']+spec['verifiers_human']:
                rows.append({**common,'Verifier type':c['type'].capitalize(),'Verifier ID':c['check_id'],'Output ID':c['output_id'],'Deliverable':c.get('artifact_name',''),'Output file':c.get('artifact_file',c['output_reference']),'Pass condition':c['check'],'Evidence':c.get('evidence_reference',''),'K question':c.get('k_id',''),'Answer (Yes/No)':''})
        else:
            for i,o in enumerate(spec['deliverables'],1):
                rows.append({**common,'Sequence':i,'Output ID':o['output_id'],'Deliverable':o['name'],'Output file':o['path'],'Kind':o['kind'],'Specification':json.dumps({'spec':o['spec'],'commission':o['commission']},ensure_ascii=False),'Status':'revised inputs; earlier delivery is historical' if o.get('artifact_url') else 'not_produced'})
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,headers,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    reconcile(path,stream.getvalue(),check)


def typography_markdown(brand: dict) -> str:
    ts = brand["type_system"]
    lines = ["## Typography", f'Display face: {ts["display_face"]}. Text face: {ts["text_face"]}.', ""]
    for key in ("specimen_note", "application", "measurement_notes"):
        if ts.get(key):
            lines.extend([ts[key], ""])
    for r in ts["scale"]:
        lines.append(f'- {r["step"]} {r["role"]}: {r["family"]}, {r["size"]} / {r["leading"]}, {r["weight"]}, tracking {r["tracking"]}. {r["note"]}')
    lines.extend(["", "Signature move: " + ts["signature_move"], "", "Rules:"])
    lines.extend("- " + rule for rule in ts["rules"])
    return "\n".join(lines) + "\n\n"


def brand_markdown(brand: dict) -> str:
    lines=['# '+brand['brand_name'], '']
    for key,value in brand.items():
        if key == 'type_system':
            lines.append(typography_markdown(brand))
            continue
        lines += ['## '+key.replace('_',' ').capitalize(), '']
        if isinstance(value,str): lines.append(value)
        elif isinstance(value,list):
            lines.extend('- '+(json.dumps(v,ensure_ascii=False) if isinstance(v,dict) else str(v)) for v in value)
        elif isinstance(value,dict):
            lines.extend('- '+k.replace('_',' ').capitalize()+': '+str(v) for k,v in value.items())
        lines.append('')
    return '\n'.join(lines).rstrip()+'\n'


def sync(check: bool = False) -> None:
    specs = {task_id: json.loads((TASKS / task_id / "TASK_SPEC.json").read_text()) for task_id in TASK_IDS}
    for task_id, spec in specs.items():
        folder = TASKS / task_id
        brief = f'# {spec["task_code"]} | {spec["task_name"]}\n\n{spec["client_brief"]}\n'
        reconcile(folder / "BRIEF.md", brief, check)
        brand_path = folder / "BRAND_IDENTITY.json"
        output_path = folder / 'OUTPUT_REGISTER.json'
        output_text = output_path.read_text()
        if json.loads(output_text) != spec['deliverables']:
            indent = len(re.search(r'\n( +)\{', output_text)[1])
            reconcile(output_path, json.dumps(spec['deliverables'], ensure_ascii=False, indent=indent) + ('\n' if output_text.endswith('\n') else ''), check)
        brand = spec["brand_identity"]
        markdown = brand_markdown(brand)
        reconcile(folder / "BRAND_IDENTITY.md", markdown, check)
        reconcile(brand_path, json.dumps(brand, ensure_ascii=False, indent=2) + "\n", check)
        verifier_path = folder / "VERIFIERS.json"
        old_verifier_text = verifier_path.read_text()
        verifier_data = merge_checks(json.loads(old_verifier_text), spec["verifiers_auto"] + spec["verifiers_human"])
        reconcile(verifier_path, json.dumps(verifier_data, ensure_ascii=False, indent=1) + ("\n" if old_verifier_text.endswith("\n") else ""), check)
        verifier_md=['# '+spec['task_name']+' - current verifiers', '', 'Revised input pack. Previous execution results are historical, not current ratings.', '']
        if spec['evaluation'].get('objective_scoring_policy'):
            verifier_md += [spec['evaluation']['objective_scoring_policy'], '', '[Measurement guide](../../annotation-pilot/measurement-guide.html)', '']
        for kind in ['auto','human']:
            verifier_md+=['## '+kind.capitalize()+' verifiers','']
            for c in verifier_data:
                if c['type']==kind:
                    verifier_md += ['- `'+c['check_id']+'` '+c['check']]
                    if kind == 'human': verifier_md += ['  '+c['method'].capitalize()+': '+c['method_note']]
            verifier_md.append('')
        reconcile(folder/'VERIFIERS.md','\n'.join(verifier_md).rstrip()+'\n',check)
        lines=[f'# {spec["task_name"]}: requested deliverables', '', 'Current input revision: pilot13_inputs_2026_10_14. Prior outputs have not been reassessed against these revised inputs.', '']
        for output in spec['deliverables']:
            c=output['commission']
            lines += [f'## {output["name"]}', f'File: `{output["path"]}`', '', f'- Purpose: {c["purpose"]}', f'- Placement: {c["channel"]}', f'- Audience: {c["audience"]}', '- Specification: '+json.dumps(output['spec']), *['- '+s for s in c['content']], '- Export: '+' '.join(c['export_settings']), '']
        old=(REFRESH/'before'/task_id/'DELIVERABLES.md').read_text()
        if 'completed output register' in old:
            lines += ['## Historical delivery record', '', 'The following record belongs to the earlier input pack; it is not approval of the current requirements.', '', old]
        reconcile(folder/'DELIVERABLES.md','\n'.join(lines).rstrip()+'\n',check)

    aggregate_path = PAGE / "TASKS_V5_ALL100.json"
    tasks = json.loads(aggregate_path.read_text())
    for task in tasks:
        if task["new_id"] in specs:
            spec = specs[task["new_id"]]
            for key in ('client_brief','brand_identity','assets','deliverable_groups','deliverables','input_revision','revision_date','evaluation'):
                task[key]=deepcopy(spec[key])
            for key in ("verifiers_auto", "verifiers_human"):
                task[key] = merge_checks(task[key], spec[key])
    reconcile(aggregate_path, json.dumps(tasks, ensure_ascii=False, indent=1), check)

    index_path = PAGE / "index.html"
    document = index_path.read_text()
    # Add the pilot's clarification text without changing the renderer for the other 90 tasks.
    old_render = '</div>${rows}${foot}</div>`;}function paletteRules'
    new_render = '</div>${[ts.specimen_note,ts.application,ts.measurement_notes].filter(Boolean).map(n=>`<p class="tsys-note">${esc(n)}</p>`).join(\'\')}${rows}${foot}</div>`;}function paletteRules'
    if old_render in document:
        document = document.replace(old_render, new_render, 1)
    match = DATA_SCRIPT.search(document)
    if not match:
        raise ValueError("Cannot locate V7 task data")
    data = json.loads(match[2])
    for task in data["tasks"]:
        if task["id"] in specs:
            spec = specs[task["id"]]
            task["brief"] = spec["client_brief"]
            task["brand"] = deepcopy(spec["brand_identity"])
            task["checks"] = merge_checks(task["checks"], spec["verifiers_auto"] + spec["verifiers_human"])
            task['assets']=deepcopy(spec['assets'])
            task['groups']=deepcopy(spec['deliverable_groups'])
            by_id={o['output_id']:o for o in spec['deliverables']}
            for o in task['outputs']:
                if o['output_id'] in by_id:
                    current=by_id[o['output_id']]
                    for key in ('commission','spec','required_content','acceptance_requirements'):
                        o[key]=deepcopy(current[key])
                    o['verification_scope']='historical_before_input_refresh'
            task['input_revision']=spec['input_revision']
            task['scoring_policy']=spec['evaluation'].get('objective_scoring_policy', '')
            task['unscored_design_targets']=deepcopy(spec['evaluation'].get('unscored_design_targets', []))
            task['current_type_html']='<style>'+font_css(spec['brand_identity'])+'</style>'+render_type_system(spec['brand_identity'])
            task['current_deliverables_html']='<style>.output-row{padding:16px 0;border-bottom:1px solid #ddd}.output-row code,.output-row small{display:block}.output-requirements{padding-left:20px}.output-requirements li{margin:5px 0}</style>'+render_outputs(spec['deliverables'],spec['deliverable_groups'])
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    document=document[:match.start(2)] + serialized + document[match.end(2):]
    document=document.replace('${typeSystem(b)}','${t.current_type_html||typeSystem(b)}')
    document=document.replace('const summary=t.run?', 'const summary=t.input_revision?`${rows.length} current checks: not assessed` :t.run?')
    hook="document.getElementById('content').innerHTML=html;}"
    replacement="""if(t.input_revision){const note='<p class="verifier-note"><strong>Revised input pack:</strong> '+esc(t.input_revision.previous_run_results)+'</p>';if(section==='Outputs')html=note+'<h2>Current requested deliverables</h2>'+t.current_deliverables_html+'<h2>Historical pilot outputs</h2>'+html;if(section==='Auto verifiers'||section==='Human verifiers')html=note+html;}document.getElementById('content').innerHTML=html;}"""
    if 'Current requested deliverables</h2>' not in document:
        document=document.replace(hook,replacement)
    if 'id="current-scoring-policy"' not in document:
        scoring_hook = """if(t.scoring_policy&&(section==='Auto verifiers'||section==='Human verifiers'))html='<div id="current-scoring-policy"><p>'+esc(t.scoring_policy)+'</p><p>'+t.unscored_design_targets.length+' unscored design targets. <a href="annotation-pilot/coverage/'+encodeURIComponent(t.id)+'.html">Coverage and exclusions</a> · <a href="annotation-pilot/measurement-guide.html">Measurement guide</a></p></div>'+html;"""
        document=document.replace(hook,scoring_hook+hook)
    # Deep links to a tab, e.g. index.html#PHOTO-04/human; the address follows task and tab clicks.
    document=document.replace(
        "let current=data.tasks.find(t=>t.id===location.hash.slice(1))||data.tasks[0],section='Brief';",
        "const sectionLinks={brief:'Brief',brand:'Brand',outputs:'Outputs',auto:'Auto verifiers',human:'Human verifiers',trajectory:'Trajectory verifiers',assets:'Assets',gates:'Release gates'};"
        "const hashParts=decodeURIComponent(location.hash.slice(1)).split('/');"
        "let current=data.tasks.find(t=>t.id===hashParts[0])||data.tasks[0],section=sectionLinks[(hashParts[1]||'').toLowerCase()]||'Brief';"
        "const setHash=()=>history.replaceState(null,'','#'+current.id+(section==='Brief'?'':'/'+Object.keys(sectionLinks).find(k=>sectionLinks[k]===section)));")
    document=document.replace("outputFilter='';history.replaceState(null,'','#'+current.id);nav();render();",
                              "outputFilter='';setHash();nav();render();")
    document=document.replace("section=b.dataset.section;render();", "section=b.dataset.section;setHash();render();")
    reconcile(index_path,document,check)

    for name in ("photo-tasks.csv", "layout-tasks.csv", "vector-tasks.csv", "motion-tasks.csv", "task-register.csv", "brand-identity.csv"):
        sync_csv(PAGE / "data" / name, specs, check)
    for name in ['assets','verifiers','deliverables']:
        sync_detail_csv(PAGE/'data'/(name+'.csv'),specs,name,check)
    for filename,field in [('OUTPUT_REGISTER_ALL100.json','deliverables'),('ATOMIC_VERIFIERS_ALL100.json',None)]:
        path=PAGE/filename
        existing=json.loads(path.read_text())
        result=[]; emitted=set()
        for row in existing:
            tid=row['task_id']
            if tid not in specs: result.append(row); continue
            if tid in emitted: continue
            emitted.add(tid)
            items=specs[tid][field] if field else specs[tid]['verifiers_auto']+specs[tid]['verifiers_human']
            result.extend({'task_id':tid,**item} for item in items)
        reconcile(path,json.dumps(result,ensure_ascii=False,indent=1),check)
    path=PAGE/'PUBLIC_ASSET_INDEX.json'
    index=json.loads(path.read_text()); result=[]; emitted=set()
    for a in index['assets']:
        tid=a['task_id']
        if tid not in specs: result.append(a); continue
        if tid in emitted: continue
        emitted.add(tid); spec=specs[tid]
        result.extend({'task_id':tid,'task_code':spec['task_code'],'task_name':spec['task_name'],'family':spec['family'],**a} for a in spec['assets'])
    index.update(assets=result,asset_count=len(result),total_bytes=sum(a.get('bytes',0) for a in result),pilot_input_revision='pilot13_inputs_2026_10_14')
    reconcile(path,json.dumps(index,ensure_ascii=False,indent=2)+'\n',check)
    manifest_path = PAGE / 'PUBLICATION_MANIFEST.json'
    manifest = json.loads(manifest_path.read_text())
    manifest.update(
        generated_at='2026-10-14', title='Gatsby V7 task review',
        task_count=len(tasks), asset_count=len(result),
        public_asset_links=len(result), public_path='/creative-ai-benchmark/gatsby-v7/',
        pilot_input_revision='pilot13_inputs_2026_10_14',
        refreshed_pilot_tasks=TASK_IDS,
        refreshed_assets_uploaded=73,
        refreshed_assets_public_access=('verified anonymous access and browser CORS; 73 new files match local SHA-256 hashes'
                                       if refreshed_assets_verified() else 'pending bucket policy approval; public GET returns 403'),
    )
    reconcile(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', check)
    release_path = PAGE / 'RELEASE_STATUS.json'
    release = json.loads(release_path.read_text())
    release.update(
        asset_count=len(result), exports=sum(len(t['deliverables']) for t in tasks),
        auto=sum(len(t['verifiers_auto']) for t in tasks),
        human=sum(len(t['verifiers_human']) for t in tasks),
        pilot_input_revision='pilot13_inputs_2026_10_14',
        refreshed_asset_access_pending=0 if refreshed_assets_verified() else 73,
    )
    release['atomic_verifiers'] = release['auto'] + release['human']
    reconcile(release_path, json.dumps(release, ensure_ascii=False, indent=2) + '\n', check)
    print("All 13 pilot brief/brand/verifier specifications are synchronized.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail on stale mirrors without writing files")
    sync(parser.parse_args().check)
