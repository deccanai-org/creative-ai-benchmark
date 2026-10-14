#!/usr/bin/env python3
"""Apply the reviewed pilot input-pack refresh; never modify execution artifacts."""
import copy
import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from prepare_pilot13_assets import ROOT, WORK, IDS

REV = 'pilot13_inputs_2026_10_14'
TASKS = ROOT/'docs/gatsby-v7/tasks'
PUBLIC = 'https://annotationprod.s3.ap-south-1.amazonaws.com/'
PREFIX = 'creative-ai-benchmark/v3.1/pilot-refresh-2026-10-14/'
STAGE = WORK/'upload'
GEN = Path('/Users/dhiren/.codex/generated_images/01a08a66-45d7-7b33-b5d9-a89a015c01c1')
LOGOS = {
 'PHOTO-04': [('verranza_monogram_transparent.png','exec-a24c56dc-8026-483e-99fd-dcb79a9e4762.png','gate_plate.jpg')],
 'PHOTO-20': [('vellacourt_av_transparent.png','exec-f06dc734-c3a0-4ca6-887c-dbcde91e796a.png','vellacourt_deboss_card.jpg')],
 'PHOTO-28': [('verda_wordmark_transparent.png','exec-f3c59365-1ffd-44e2-8ab9-0a2a20f96df1.png','verda_logo_web.png')],
 'LAYOUT-12': [('umbra_sable_wordmark_transparent.png','exec-8d1594d5-4f89-45af-8d49-c3155e587359.png','umbra_wordmark_sable.jpg'),('umbra_meridian_wordmark_transparent.png','exec-32a0dbc3-4653-47d5-820b-b1a506defb01.png','umbra_wordmark_meridian.jpg')],
 'MOTION-11': [('staticfox_scrap_transparent.png','exec-a883b250-0f71-48c7-a98e-1d9500523ac7.png','staticfox_scrap_render.png')]
}
FONT_MAP = {
 'PHOTO-04': [('Canela Deck Light','Cormorant Garamond Light'),('Canela Deck','Cormorant Garamond'),('Untitled Sans','Source Sans 3')],
 'PHOTO-06': [('Financier Display','Cormorant Garamond'),('Freight Text Pro Book','Source Serif 4 Regular'),('Freight Text Pro','Source Serif 4'),('Untitled Sans','Source Sans 3')],
 'PHOTO-08': [('Publico Banner','Source Serif 4')],
 'PHOTO-10': [('GT Super Display','Source Serif 4'),('Freight Sans Pro Book','Libre Franklin Regular'),('Freight Sans Pro','Libre Franklin')],
 'PHOTO-19': [("Suisse Int'l Regular / Mono Regular",'Inter Regular / IBM Plex Mono Regular'),("Suisse Int'l Mono",'IBM Plex Mono'),("Suisse Int'l",'Inter')],
 'PHOTO-20': [('Neue Haas Grotesk Text Roman','Inter Regular'),('Neue Haas Grotesk Text Medium','Inter Medium'),('Neue Haas Grotesk Text','Inter')],
 'PHOTO-24': [('Boska Medium small caps','Cormorant Garamond Medium capitals'),('Boska Medium','Cormorant Garamond Medium'),('Boska','Cormorant Garamond'),("Suisse Int'l",'Inter'),('small caps','capitals')],
 'PHOTO-26': [('Druk Medium','Barlow Condensed Medium'),('Druk','Barlow Condensed'),('Publico Text Roman','Source Serif 4 Regular'),('Publico Text','Source Serif 4'),('Graphik','Inter')],
 'PHOTO-28': [('Monument Extended Regular','Archivo Regular'),('Monument Extended','Archivo'),('Basis Grotesque','Inter')],
 'LAYOUT-15': [('Miller Text Roman','Source Serif 4 Regular'),('Miller Text','Source Serif 4')],
 'LAYOUT-12': [],
 'VECTOR-04': [('Cirka Bold','DM Serif Display Regular'),('Cirka','DM Serif Display'),('Brandon Text Regular','Libre Franklin Regular'),('Brandon Text Bold','Libre Franklin Bold'),('Brandon Text','Libre Franklin')],
 'MOTION-11': [('Univers 59 Ultra Condensed','Anton Regular'),('Univers 83 Extra Black Extended','Archivo Black Regular'),('Univers','Anton / Archivo Black'),('inside one family','between two supplied faces')]
}
SLUGS = {'Cormorant Garamond':'cormorantgaramond','Source Sans 3':'sourcesans3','Source Serif 4':'sourceserif4','Libre Franklin':'librefranklin','Piazzolla':'piazzolla','Instrument Serif':'instrumentserif','Inter':'inter','Barlow Condensed':'barlowcondensed','Lexend':'lexend','Sora':'sora','Archivo Narrow':'archivonarrow','DM Serif Display':'dmserifdisplay','Archivo Black':'archivoblack','Archivo':'archivo','Anton':'anton','IBM Plex Mono':'ibmplexmono'}
SLUGS['IBM Plex Sans'] = 'ibmplexsans'

def save(path,value,indent=2):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=indent)+'\n')

def replace_text(value,pairs):
    if isinstance(value,str):
        for old,new in sorted(pairs,key=lambda p:-len(p[0])):
            value=value.replace(old,new)
        return value
    if isinstance(value,list): return [replace_text(v,pairs) for v in value]
    if isinstance(value,dict): return {k:replace_text(v,pairs) for k,v in value.items()}
    return value

def asset(tid,src,name,role,description,extra=None):
    target=STAGE/tid/name
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(src,target)
    key=PREFIX+tid+'/'+name
    a={'asset_id':tid+'-REFRESH-'+hashlib.sha256(name.encode()).hexdigest()[:10], 'filename':name,'bytes':target.stat().st_size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'role':role,'description':description,'state':'supplied','s3_key':key,'s3_uri':'s3://annotationprod/'+key,'public_url':PUBLIC+quote(key,safe='/'),'revision':REV}
    if extra: a.update(extra)
    if name.endswith('.png'):
        from PIL import Image
        im=Image.open(target)
        a.update(width=im.width,height=im.height,mode=im.mode)
        assert im.mode=='RGBA' and im.getchannel('A').getextrema()[0]==0, name
    return a

def font_assets(tid,brand):
    from fontTools.ttLib import TTFont
    faces=[]
    for row in brand['type_system']['scale']:
        matches=[name for name in sorted(SLUGS,key=len,reverse=True) if name in row['family']]
        # Avoid interpreting Archivo as a second font inside Archivo Narrow/Black.
        if any(n.startswith('Archivo ') for n in matches): matches=[n for n in matches if n!='Archivo']
        assert matches, row
        row['font_family']=matches[0]
        for face in matches:
            if face not in faces: faces.append(face)
        weight=row['weight'].lower()
        row['font_weight']=next((v for k,v in [('extrabold',800),('semibold',600),('bold',700),('medium',500),('light',300)] if k in weight),400)
        if row['font_family'] in ['DM Serif Display','Anton','Archivo Black','Instrument Serif']: row['font_weight']=400;row['weight']='Regular 400'
        if row['weight'] in ['Book','Roman']: row['weight']='Regular 400'
    assets=[]
    metadata=[]
    for family in SLUGS:
        if family in json.dumps(brand['type_system']) and family not in faces:
            if family == 'Archivo' and any(n.startswith('Archivo ') for n in faces):
                continue
            faces.append(family)
    for family in faces:
        folder=WORK/'fonts'/SLUGS[family]
        files=[p for p in folder.glob('*.ttf') if 'Italic' not in p.name]
        weights={r['font_weight'] for r in brand['type_system']['scale'] if r['font_family']==family} or {400}
        files=[p for p in files if 'fvar' in TTFont(p) or TTFont(p)['OS/2'].usWeightClass in weights]
        assert files, (family, weights)
        for file in files:
            name='fonts/'+file.name
            a=asset(tid,file,name,'font',family+' font file. See the matching OFL licence.',{'font_family':family,'licence':'SIL Open Font License 1.1','source_url':'https://github.com/google/fonts/tree/main/ofl/'+SLUGS[family]})
            font=TTFont(file)
            axes={x.axisTag:[x.minValue,x.defaultValue,x.maxValue] for x in font['fvar'].axes} if 'fvar' in font else {}
            assets.append(a)
            metadata.append({'family':family,'filename':name,'url':a['public_url'],'axes':axes,'weight_range':axes.get('wght',[font['OS/2'].usWeightClass]*3)})
        assets.append(asset(tid,folder/'OFL.txt','fonts/'+SLUGS[family]+'-OFL.txt','font licence','Licence and copyright notice for '+family))
    brand['font_files']=metadata
    ts=brand['type_system']
    ts['specimen_note']='The samples load the supplied font files. Their display size is reduced for this guide; use the stated deliverable settings, not the on-screen sample size. Fonts and their OFL licences are downloadable in Source assets.'
    ts['measurement_notes']=ts.get('measurement_notes','Tracking in units means thousandths of an em; 1 pt is 1/72 inch. Pixel settings apply at final exported size. Font size is not cap height.').replace('fallback','supplied')
    ts['application']=ts.get('application','Apply these roles to newly set text in the requested deliverables. Preserve supplied logo artwork rather than retyping it. Recovered artwork retains its photographed lettering.')
    ts['font_access']='Use the attached OFL font files at the named weights. These files replace unavailable commercial fonts for this commission. Do not substitute another family or simulate a missing weight.'
    return assets

def cfs_vector():
    from fontTools.ttLib import TTFont
    from fontTools.pens.svgPathPen import SVGPathPen
    from fontTools.varLib.instancer import instantiateVariableFont
    font=TTFont(next(p for p in (WORK/'fonts/sourcesans3').glob('*.ttf') if 'Italic' not in p.name))
    if 'fvar' in font: font=instantiateVariableFont(font,{'wght':600},inplace=False)
    glyphs=font.getGlyphSet(); cmap=font.getBestCmap(); x=0; paths=[]
    for char in 'CFS':
        name=cmap[ord(char)]; pen=SVGPathPen(glyphs);glyphs[name].draw(pen)
        paths.append(f'<path transform="translate({x},0)" d="{pen.getCommands()}"/>')
        x+=glyphs[name].width+300
    file=WORK/'cfs_mark_transparent.svg'
    file.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x} 1000"><title>CFS summit mark</title><g fill="#23303A" transform="translate(0,800) scale(1,-1)">{"".join(paths)}</g></svg>')
    return file

def export_settings(tid,o):
    fmt=o['spec']['format']
    if fmt=='mp4':
        audio=o['spec']['audio']
        return ['H.264 MP4; 24 fps; yuv420p; Rec.709 colour; exact dimensions and duration shown above.', 'No audio track.' if audio=='silent' else 'Use staticfox_bed.wav only; AAC stereo at 48 kHz, no speech or capture audio; avoid clipping.']
    if fmt=='svg': return ['SVG with editable vector paths and an explicit viewBox; no embedded raster image; transparent uninked areas.','Set physical units in millimetres; artwork long edge is 55 mm. Cut-contour dimensions include the 2.5 mm outward offset.']
    if fmt=='pdf':
        if tid in ['LAYOUT-15','VECTOR-04']:
            return ['Production PDF/X-4 with embedded fonts or outlined lettering, CMYK artwork and the supplied PSO Coated v3 output intent. Convert palette colours from sRGB using this profile; preserve named spot cut lines separately.', 'Premium coated A5 counter card; A5 TrimBox; 3 mm bleed outside trim; photographs at least 300 ppi at placed size; keep disclosure inside trim.' if tid=='LAYOUT-15' else '305 x 457 mm page, 55 mm artwork scale, 10 mm sheet clearance and 6 mm contour gutters; CutContour remains a separate named layer and spot colour. PSO Coated v3 is the agreed CMYK exchange space, not a solvent/vinyl device profile: the printer handles the final RIP conversion and physical proof for white gloss vinyl.']
        return ['Digital PDF in sRGB with embedded fonts, searchable text where practical, no crop marks and no added bleed; retain the exact page size and page count.','This file is for screen review/distribution, not a CMYK press master.']
    return [('PNG with genuine alpha transparency; sRGB; exact pixel dimensions.' if o['spec'].get('transparent') else 'Lossless PNG; sRGB; exact pixel dimensions.') if fmt=='png' else 'High-quality JPEG; sRGB; final long edge includes the caption margin.']

def add_check(tid,o,key,text,refs=()):
    filename=Path(o['path']).name
    sentence=f'{filename}: {text}'
    return {'task_id':tid,'output_id':o['output_id'],'check_id':tid+'/'+o['output_id']+'/R13-'+key,'type':'human','output_reference':o['path'],'artifact_name':o['name'],'artifact_file':filename,'check':sentence,'source_statement':sentence,'requirement':sentence,'pass_condition':sentence,'answer_type':'yes_no','allowed_answers':['Yes','No'],'pass_answer':'Yes','answer':None,'status':'not_assessed','reference_assets':list(refs),'revision':REV,'origin':REV,'k_id':'K1_Q2' if 'profile' in key or 'pdf-' in key else 'K2_Q3','k_label':'Export specification' if 'profile' in key or 'pdf-' in key else 'Brand-system compliance','evidence_reference':'Current brief and supplied assets. Exact font settings require authored-source or embedded-font evidence; do not infer them from a raster preview.','platform_priority':True}

def main():
    config=json.loads((ROOT/'scripts/pilot13_refresh_config.json').read_text())
    changes=[]
    for tid in IDS:
        before=json.loads((WORK/'before'/tid/'TASK_SPEC.json').read_text())
        t=copy.deepcopy(before); cfg=config[tid]
        pairs=FONT_MAP[tid]
        for key in ['brand_identity','client_brief','deliverable_groups','production_requirements']:
            if key in t: t[key]=replace_text(t[key],pairs)
        b=t['brand_identity']; ts=b['type_system']
        if tid=='MOTION-11':
            ts['scale'][0].update(family='Anton',weight='Regular 400')
            ts['scale'][1].update(family='Archivo Black',weight='Regular 400')
            ts['display_face']='Anton Regular / Archivo Black Regular'
        if tid=='PHOTO-19':
            ts['scale'][3]['family']='Inter Regular / IBM Plex Mono Regular'
        if tid=='LAYOUT-12':
            ts['scale'][0].update(role='Series title / headline',size='180 pt',leading='148 pt',note='A2 series title only, not every act in the schedule. Use 96 px on a release post; act names are 48 pt on posters and 76 px on posts. Act names may occupy one or two lines; keep the one-word name KOA on one line.')
            ts['scale'][1].update(role='Date line',size='18 pt',leading='22 pt',note='A2 poster date line above its act. On release posts use 30 px / 36 px.')
            ts['scale'][2].update(size='14 pt',leading='19 pt',note='A2 supporting billing uses 14 pt / 19 pt. Release-post supporting copy uses 28 px / 38 px. Deck body uses 18 pt / 25 pt.')
            ts['scale'][3]['note']='9 pt / 13 pt for poster licence and access lines. Release posts use at least 22 px / 30 px. SemiBold is reserved for door-time information; other fine print is Regular.'
            ts['rules']=[r for r in ts['rules'] if not any(x in r.lower() for x in ['one line','two lines','0.82'])]
            ts['rules'].insert(0,'Act names use one or two lines as needed; KOA stays on one line. Do not apply the 180 pt series-title size to the full billing list.')
            ts['signature_move']='A compact series-title stack in Sora ExtraBold; Bone White act blocks on Pitch with the date immediately above in Sodium. Billing sizes follow the placement-specific notes.'
        if tid=='VECTOR-04':
            ts['scale'][0]['weight']=ts['scale'][1]['weight']='Regular 400'
        b['signature_type_move']=ts['signature_move']
        # Current supplied production assets take precedence; originals remain downloadable references.
        new_assets=[]
        logo_pairs=[]
        for name,generated,old in LOGOS.get(tid,[]):
            new_assets.append(asset(tid,GEN/generated,name,'production identity','Current supplied transparent artwork; use instead of '+old,{'generation_tool':'built-in GPT image generation','model_version':'not exposed by tool','reference_filename':old}))
            logo_pairs.append((old,name))
            for a in t['assets']:
                if a['filename']==old: a.update(role='historical identity reference',description='Historical reference only; use '+name+' for production placement.')
        if tid=='PHOTO-19':
            new_assets.append(asset(tid,cfs_vector(),'cfs_mark_transparent.svg','production identity','CFS lettering supplied as outlined vector artwork; no font installation required for this mark.',{'derivation':'CFS lettermark recreated as outlined Source Sans 3 SemiBold glyphs; not image generated.'}))
        b['brand_assets_status']=cfg['logo_note']
        b['creative_scope']={'fixed':cfg['fixed'],'designer_choices':cfg['choices']}
        font_list=font_assets(tid,b)
        t['assets']+=new_assets+font_list
        if tid in ['LAYOUT-15','VECTOR-04']:
            for filename in ['PSOcoated_v3.icc','PSOcoated_v3_info.pdf']:
                t['assets'].append(asset(tid,WORK/'print-profile'/filename,filename,'print colour profile' if filename.endswith('.icc') else 'print profile documentation','ECI PSO Coated v3 profile for the commissioned print PDF.',{'source_url':'https://eci.org/lib/exe/pso-coated_v3.zip'}))
            b['palette_rules']['distribution']+=' Palette hex values define sRGB source colours. In the print PDF, convert them with PSOcoated_v3.icc; evaluate the colour-managed proof, not literal RGB hex values inside the CMYK file.'
        for a in t['assets']:
            a.pop('upload_pending',None)
        # Keep legacy references separately named; replace references used to judge current outputs.
        for key in ['verifiers_auto','verifiers_human']:
            updated=[]
            for old in t[key]:
                if tid=='LAYOUT-12' and re.search(r'Sora|Archivo|two lines|two-line|0\.82|180 pt|150 px',old['check'],re.I):
                    continue
                c=replace_text(old,pairs+logo_pairs)
                if tid=='MOTION-11':
                    c=replace_text(c,[('is cut from staticfox_scrap_transparent.png','uses staticfox_scrap_transparent.png'),('he is cut from staticfox_scrap_transparent.png','he uses staticfox_scrap_transparent.png')])
                if c!=old:
                    c.update(revision=REV,answer=None,status='not_assessed')
                updated.append(c)
            t[key]=updated
        if tid=='PHOTO-20':
            for c in t['verifiers_human']:
                if 'AV monogram and her name' in c['check'] and 'Instrument Serif' in c['check']:
                    o=next(x for x in t['deliverables'] if x['output_id']==c['output_id'])
                    c.update({k:f"{Path(o['path']).name}: Astrid's name beneath the supplied AV artwork uses Instrument Serif Regular." for k in ['check','source_statement','requirement','pass_condition']})
                    c.update(status='not_assessed',answer=None,revision=REV)
        if tid=='PHOTO-04':
            for c in t['verifiers_human']:
                if 'monogram' in c['check'] and 'reversed out' in c['check']:
                    msg='villa-collection.pdf: the supplied monogram is Blue on Lime Wash, or its ink is recoloured Lime Wash on a Blue panel.'
                    c.update({k:msg for k in ['check','source_statement','requirement','pass_condition']});c.update(status='not_assessed',answer=None,revision=REV)
            b['palette_rules']['distribution']+=' The supplied monogram may also appear in Blue on Lime Wash.'
        if tid=='LAYOUT-12':
            # Recovery is no longer a hidden dependency for the two supplied band marks.
            for c in t['verifiers_human']:
                if 'wordmark' in c['check'].lower() and 'Night Ferry' not in c['check'] and ('recovered' in c['check'] or 'lettering photographed' in c['check'] or 'traced' in c['check']):
                    filename=c['artifact_file']
                    msg=f'{filename}: Sable Quartet and Meridian Brass use their supplied transparent production wordmarks wherever their wordmarks are required.'
                    # Separate each band into its own check below; remove the old combined reconstruction check.
                    c['_retire']=True
            t['verifiers_human']=[c for c in t['verifiers_human'] if not c.get('_retire')]
            b['palette_rules']['distribution']+=' Supplied production act wordmarks are recoloured to Bone White on Pitch; their letter shapes remain unchanged.'
        # Do not assert exact source-ink hexes on generated logos; require palette-colour placement.
        if new_assets:
            b['palette_rules']['opacity']+=' Supplied raster identity artwork retains its edge anti-aliasing. Place it at 100% layer opacity; colour rules apply to any intentional recolouring.'
        t['client_brief']=replace_text(t['client_brief'],logo_pairs)
        if tid=='PHOTO-19': t['client_brief']=t['client_brief'].replace('Use the CFS mark shown on summit_badge_2025_PRINTER.pdf.','Use cfs_mark_transparent.svg for the CFS mark.')
        if tid=='PHOTO-28': t['client_brief']=t['client_brief'].replace('Keep it on one line, no larger than 34 px on screen;','Keep it on one line, at most 34 px tall measured on the visible letterforms;')
        if tid in ['LAYOUT-12','VECTOR-04','MOTION-11']:
            t['client_brief']=re.sub(r'\n\nUse the supplied approved copy and factual records\..*', '',t['client_brief'],flags=re.S)
            t['client_brief']=t['client_brief'].replace('named exports','files').replace('named export','file')
        if tid=='LAYOUT-12':
            t['client_brief']=t['client_brief'].replace('a recovered wordmark, where an act has one','a supplied production wordmark, for Sable Quartet or Meridian Brass').replace('a recovered wordmark, where the act has one','a supplied production wordmark, for Sable Quartet or Meridian Brass')
            t['client_brief']+='\n\nTreat the nine dates and prices in umbra_nights_autumn.csv as current. Decode 8:00&nbsp;PM as 8:00 PM. The old seasoncard_img_01.jpg through seasoncard_img_08.jpg identifiers are not supplied source photographs: choose from umbra_archive_night_01.jpg through umbra_archive_night_06.jpg, without implying that a pictured performer is a named act. The three poster files are A2 approval proofs, not press masters. Use the billing file\'s accessibility and licence lines on these poster proofs.'
        if tid=='VECTOR-04':
            t['client_brief']+='\n\nThis commission includes reconstruction of the four photographed originals. The two companion illustrations are new designs. Set every artwork SVG to 55 mm on its long edge; the cut contour adds its 2.5 mm outward offset. The PNG proofs use a 1600 x 1600 px viewing canvas and are not a substitute for the physical-scale SVGs.'
        if tid=='MOTION-11':
            t['client_brief']=t['client_brief'].replace('Scrap comes off the supplied render, not redrawn, and not stretched.','Use staticfox_scrap_transparent.png as the supplied mascot artwork, without redesigning or stretching it.')
            t['client_brief']+='\n\nUse staticfox_bed.wav for both teasers, with no speech or capture audio. The upright teaser uses at least three of the captures used in the wide teaser. Title 1 belongs to capture 01, title 2 to capture 02, and so on through title 6 and capture 06. For capture 04, keep the webcam window whole, cover it fully, or crop it out; do not leave a partly cut face. Use the exact members line and all three end-card lines from staticfox_titles.txt.'
        t['client_brief']+='\n\nSupplied identity artwork\n'+cfg['logo_note']+'\n\nWhat stays fixed\n'+cfg['fixed']+'\n\nYour design decisions\n'+cfg['choices']+'\n\nDelivery and fonts\nUse the placement and export instructions listed with each requested file below. The downloadable OFL fonts in Source assets are the current typefaces for this commission; the typography card gives their roles and weights.'
        for o in t['deliverables']:
            o['required_content']=replace_text(o.get('required_content',[]),pairs+logo_pairs)
            o['acceptance_requirements']=replace_text(o.get('acceptance_requirements',[]),pairs+logo_pairs)
            purpose,channel,audience,content=copy.deepcopy(cfg['groups'][o['group_id']])
            if tid=='MOTION-11' and o['group_id']=='channel-animation':
                if o['output_id']=='channel-animation':
                    purpose='Introduce the channel with authored identity animation and a reusable end card.'
                    content=['Animate the supplied mascot and channel typography, not a gameplay montage.','Hold a final end card containing the full members line and all three END CARD COPY lines from staticfox_titles.txt.']
                elif o['output_id']=='channel-teaser':
                    purpose='Invite viewers into the channel through a fast gameplay preview.'
                    content=['Use at least four of captures 01-06; no invented footage or looping to fill duration.','Show the exact tagline and NEW ONE EVERY OTHER DAY line from staticfox_titles.txt.']
                else:
                    purpose='Adapt the wide teaser for a vertical feed without losing the key action.'
                    channel='YouTube Shorts / vertical social feed'
                    content=['Use at least three captures also used in channel-teaser.mp4.','Reframe the action and type for the vertical canvas; keep the exact tagline and upload line.']
            o['commission']={'purpose':purpose,'channel':channel,'audience':audience,'content':content,'export_settings':export_settings(tid,o)}
            # All new requirements remain unassessed; existing run results are historical.
            if o['spec']['format'] in ['png','jpg','jpeg']:
                t['verifiers_human'].append(add_check(tid,o,'colour-profile','uses an sRGB colour profile.'))
            if o['spec']['format']=='pdf':
                production=tid in ['LAYOUT-15','VECTOR-04']
                t['verifiers_human'].append(add_check(tid,o,'pdf-profile','contains the supplied PSO Coated v3 output intent.' if production else 'is exported for sRGB screen viewing, not as a CMYK press master.'))
                t['verifiers_human'].append(add_check(tid,o,'pdf-fonts','has no unembedded font dependency.'))
            if tid=='LAYOUT-12':
                for role,family,weight in [('act-name text','Sora',800),('supporting billing','Archivo Narrow',400),('door-time information','Archivo Narrow',600)]:
                    for prop,val in [('family',family),('weight',str(weight))]:
                        t['verifiers_human'].append(add_check(tid,o,re.sub(r'\W+','-',role)+'-'+prop,f'the {role} uses font {prop} {val} wherever that text appears.'))
                t['verifiers_human'].append(add_check(tid,o,'koa-line','keeps the name KOA on one line when that act is included.'))
            if tid=='LAYOUT-12' and o['group_id'] in ['poster-direction','release-post']:
                acts=['Sable Quartet','Meridian Brass'] if o['group_id']=='poster-direction' else [(o.get('source_record') or {}).get('values',{}).get('headline')]
                for act in acts:
                    if act in ['Sable Quartet','Meridian Brass']:
                        file='umbra_sable_wordmark_transparent.png' if act=='Sable Quartet' else 'umbra_meridian_wordmark_transparent.png'
                        a=next(x for x in new_assets if x['filename']==file)
                        t['verifiers_human'].append(add_check(tid,o,'logo-'+act.lower().split()[0],f'the {act} wordmark uses the shapes in {file}.',[{'filename':file,'url':a['public_url']}]))
        t['revision_date']='2026-10-14'
        t['input_revision']={'id':REV,'previous_run_results':'Historical runs are preserved and have not been re-evaluated against these revised inputs.','changes':['Deliverable purposes and export settings','Downloadable licensed fonts','Explicit logo scope','Fixed requirements and creative choices','Task-level Decision Quality evaluation']}
        # Font reference links on font checks point to the actual supplied font files.
        font_refs=[{'filename':a['filename'],'url':a['public_url']} for a in font_list if a['role']=='font']
        for c in t['verifiers_human']:
            if c.get('typography_key') or re.search(r'font|typeface|Sora|Archivo|Inter|Cormorant|Source Serif|Source Sans|Libre Franklin|DM Serif|Anton|Lexend|Piazzolla|Instrument Serif|Barlow',c['check']):
                refs={r['filename']:r for r in c.get('reference_assets',[])}
                refs.update({r['filename']:r for r in font_refs})
                c['reference_assets']=list(refs.values())
        current_urls={a['filename']:a['public_url'] for a in t['assets']}
        for c in t['verifiers_auto']+t['verifiers_human']:
            for ref in c.get('reference_assets',[]):
                if ref.get('filename') in current_urls:
                    ref['url']=current_urls[ref['filename']]
            if c.get('status') != 'not_assessed' or c.get('answer'):
                c['historical_result']={k:c[k] for k in ['status','answer','verified_at','evidence_reference','artifact_url'] if k in c}
                c.update(status='not_assessed',answer=None,evidence_reference='Revised input pack: not run. Previous evidence is retained in historical_result and the original run files.')
                c.pop('verified_at',None)
                c.pop('artifact_url',None)
        for o in t['deliverables']:
            if o.get('artifact_url'):
                o['verification_scope']='historical_before_input_refresh'
        # Avoid bare parenthetical faces surviving a family substitution.
        b['typography']=replace_text(b.get('typography',''),pairs)
        save(TASKS/tid/'TASK_SPEC.json',t,1)
        save(TASKS/tid/'ASSET_MANIFEST.json',t['assets'])
        save(TASKS/tid/'OUTPUT_REGISTER.json',t['deliverables'])
        changes.append({'task_id':tid,'assets_before':len(before['assets']),'assets_after':len(t['assets']),'outputs':len(t['deliverables']),'font_families':[f['family'] for f in b['font_files']],'new_identity_assets':[a['filename'] for a in new_assets],'checks':len(t['verifiers_auto'])+len(t['verifiers_human'])})
    save(WORK/'change-summary.json',changes)
    print(json.dumps(changes,indent=2))

if __name__=='__main__': main()
