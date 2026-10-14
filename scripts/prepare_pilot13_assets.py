#!/usr/bin/env python3
"""Stage source assets and OFL font files without changing published task data."""
import concurrent.futures
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'
IDS = ['PHOTO-04','PHOTO-06','PHOTO-08','PHOTO-10','PHOTO-19','PHOTO-20','PHOTO-24','PHOTO-26','PHOTO-28','LAYOUT-15','LAYOUT-12','VECTOR-04','MOTION-11']
FONTS = ['cormorantgaramond','sourcesans3','sourceserif4','librefranklin','piazzolla','instrumentserif','inter','barlowcondensed','lexend','sora','archivonarrow','dmserifdisplay','archivo','anton','archivoblack','ibmplexmono']

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent':'Gatsby-pilot-assets/1.0'})
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read()

def source(item):
    task_id, a = item
    dest = WORK / 'sources' / task_id / a['filename']
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = ROOT.parents[1] / 'benchmark_runs/pilot_v7_hybrid_2026-09-28' / task_id / 'source' / a['filename']
    if not dest.exists():
        if old.exists():
            shutil.copy2(old, dest)
        else:
            dest.write_bytes(get(a['public_url']))
    try:
        req = urllib.request.Request(a['public_url'], method='HEAD')
        with urllib.request.urlopen(req, timeout=45) as r:
            status, remote_size = r.status, int(r.headers.get('Content-Length',0))
        return {'task':task_id,'filename':a['filename'],'status':status,'bytes':dest.stat().st_size,'remote_bytes':remote_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'url':a['public_url']}
    except Exception as e:
        return {'task':task_id,'filename':a['filename'],'error':str(e)}

def font(slug):
    listing = json.loads(get('https://api.github.com/repos/google/fonts/contents/ofl/' + slug))
    folder = WORK / 'fonts' / slug
    folder.mkdir(parents=True, exist_ok=True)
    rows=[]
    for file in listing:
        if file['name'].endswith('.ttf') or file['name'] in ['OFL.txt','METADATA.pb']:
            dest=folder/file['name']
            if not dest.exists(): dest.write_bytes(get(file['download_url']))
            rows.append({'filename':file['name'],'source':file['download_url'],'git_blob_sha':file['sha'],'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    return {'family_directory':slug,'files':rows}

def main():
    WORK.mkdir(parents=True,exist_ok=True)
    queue=[]
    for task_id in IDS:
        folder=ROOT/'docs/gatsby-v7/tasks'/task_id
        before=WORK/'before'/task_id
        if not before.exists(): shutil.copytree(folder,before)
        spec=json.loads((folder/'TASK_SPEC.json').read_text())
        queue.extend((task_id,a) for a in spec['assets'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(source,queue))
    (WORK/'asset-access-audit.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Source assets:',len(results),'errors:',[r for r in results if 'error' in r],flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(font,FONTS))
    (WORK/'font-provenance.json').write_text(json.dumps(results,indent=2)+'\n')
    print('OFL font families:',len(results),flush=True)

if __name__=='__main__': main()
