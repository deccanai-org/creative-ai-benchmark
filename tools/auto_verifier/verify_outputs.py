"""Run file-bound objective checks. A missing artifact never becomes a process-based pass."""
import argparse
import ctypes.util
import io
import json
import math
import re
import subprocess
import tempfile
import zipfile
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image
from pypdf import PdfReader

_find_library=ctypes.util.find_library
_homebrew_cairo=Path('/opt/homebrew/lib/libcairo.2.dylib')
if _homebrew_cairo.exists() and not _find_library('cairo'):
    ctypes.util.find_library=lambda name: str(_homebrew_cairo) if 'cairo' in name else _find_library(name)


class VerifierUnavailable(RuntimeError):
    pass


def command(args):
    result = subprocess.run(args, capture_output=True, timeout=180)
    if result.returncode:
        raise ValueError(result.stderr.decode(errors='replace')[-600:])
    return result.stdout


def svg_tree(file):
    text = file.read_text()
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
        raise ValueError('External XML declarations are not permitted')
    root = ET.fromstring(text)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('Not an SVG root')
    for element in root.iter():
        if element.tag.split('}')[-1] in ('script', 'foreignObject'):
            raise ValueError('Active SVG content is not permitted')
        for name, value in element.attrib.items():
            if name.split('}')[-1] == 'href' and not value.startswith('#'):
                raise ValueError('External or embedded linked media requires manual review')
            remaining = re.sub(r'url\(\s*[\"\x27]?#[-\w]+[\"\x27]?\s*\)', '', value, flags=re.I)
            if 'url(' in remaining.lower():
                raise ValueError('External CSS resource is not permitted')
        if element.tag.split('}')[-1]=='style' and ('@import' in (element.text or '').lower() or 'url(' in (element.text or '').lower()):
            raise ValueError('CSS resource loading is not permitted')
    return root


def closed_svg_contours(root):
    contours=0
    for element in root.iter():
        name=element.tag.split('}')[-1]
        if name in ('line','polyline'):
            return False, contours
        if name in ('circle','ellipse','rect','polygon'):
            contours+=1
        if name!='path':
            continue
        subpaths=[part for part in re.split(r'(?=[Mm])',element.get('d','')) if part.strip()]
        if not subpaths or any(not re.search(r'[Zz]\s*$',part) for part in subpaths):
            return False, contours
        contours+=len(subpaths)
    return contours>0, contours


def probe(file):
    return json.loads(command(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(file)]))


def image_size(file):
    if file.suffix.lower() == '.mp4':
        stream = next(s for s in probe(file)['streams'] if s['codec_type'] == 'video')
        return stream['width'], stream['height']
    with Image.open(file) as image:
        return image.size


def render_pdf_page(file, page):
    with tempfile.TemporaryDirectory() as directory:
        prefix=Path(directory)/'page'
        command(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-r','150','-png',str(file),str(prefix)])
        with Image.open(prefix.with_suffix('.png')) as image:
            return np.asarray(image.convert('RGB'),dtype=np.int16)


def verify(file, assertion, artifact_root=None):
    op = assertion['op']
    if op == 'file_exists':
        return file.is_file() and file.stat().st_size > 0, {'bytes': file.stat().st_size if file.exists() else 0}
    if op == 'decodable':
        fmt = assertion['format']
        if fmt in ('png', 'jpg'):
            with Image.open(file) as im:
                expected = 'PNG' if fmt == 'png' else 'JPEG'
                if im.format != expected:
                    return False, {'detected_format': im.format}
                im.load()
        elif fmt == 'pdf':
            pdf = PdfReader(file)
            if not pdf.pages:
                return False, {'pages': 0}
            for page in pdf.pages:
                page.get_contents()
        elif fmt == 'svg':
            svg_tree(file)
        elif fmt == 'zip':
            with zipfile.ZipFile(file) as archive:
                if archive.testzip():
                    return False, {'crc_error': True}
        elif fmt == 'mp4':
            info=probe(file)
            if not any(s['codec_type']=='video' for s in info['streams']):
                return False, {'video_stream': False}
            command(['ffmpeg','-v','error','-xerror','-i',str(file),'-f','null','-'])
        else:
            raise NotImplementedError(fmt)
        return True, {'format': fmt}
    if op in ('width','height','long_edge'):
        width,height=image_size(file)
        value = width if op=='width' else height if op=='height' else max(width,height)
        return value==assertion['equals'], {'measured':value}
    if op in ('pages','trim_width_mm','trim_height_mm'):
        pdf=PdfReader(file)
        if op=='pages':
            return len(pdf.pages)==assertion['equals'], {'measured':len(pdf.pages)}
        selected=pdf.pages
        if 'page' in assertion:
            page=assertion['page']
            if not isinstance(page,int) or page<1 or page>len(pdf.pages):
                return False, {'reason':'The referenced PDF page is absent.'}
            selected=[pdf.pages[page-1]]
        values=[float(p.trimbox.width if op=='trim_width_mm' else p.trimbox.height)*25.4/72 for p in selected]
        return all(abs(x-assertion['equals'])<=assertion['tolerance'] for x in values), {'measured_mm':values}
    if op == 'pdf_text_contains':
        text='\n'.join((page.extract_text() or '') for page in PdfReader(file).pages)
        normalize=lambda value: re.sub(r'\s+',' ',value).strip()
        expected=normalize(assertion['expected'])
        actual=normalize(text)
        return expected in actual, {'expected':expected,'extracted_text_length':len(actual)}
    if op == 'pdf_page_matches_output':
        if artifact_root is None:
            raise VerifierUnavailable('Artifact root is required for page comparison')
        source=(artifact_root/assertion['source_path']).resolve()
        if not source.is_relative_to(artifact_root) or not source.is_file():
            return False, {'reason':'Referenced source output is missing'}
        left=render_pdf_page(file,assertion['page'])
        right=render_pdf_page(source,assertion['source_page'])
        if left.shape!=right.shape:
            return False, {'combined_shape':list(left.shape),'source_shape':list(right.shape)}
        difference=float(np.mean(np.abs(left-right)))
        return difference<=0.5, {'mean_absolute_pixel_difference':difference,'render_dpi':150}
    if op == 'no_raster_image':
        elements=[e.tag.split('}')[-1] for e in svg_tree(file).iter()]
        return 'image' not in elements, {'image_elements':elements.count('image')}
    if op == 'transparent_background':
        if file.suffix.lower()=='.svg':
            try:
                import cairosvg
            except (ImportError,OSError) as error:
                raise VerifierUnavailable('SVG renderer is unavailable: '+str(error)[:150]) from error
            svg_tree(file)
            im=Image.open(io.BytesIO(cairosvg.svg2png(url=str(file),output_width=256,output_height=256))).convert('RGBA')
        else:
            im=Image.open(file).convert('RGBA')
        alpha=np.asarray(im.getchannel('A'))
        outer=np.concatenate([alpha[0],alpha[-1],alpha[:,0],alpha[:,-1]])
        fraction=float((outer==0).mean())
        return fraction>=0.95 and int(alpha.max())>0, {'transparent_border_fraction':fraction,'alpha_range':[int(alpha.min()),int(alpha.max())]}
    if op == 'closed_paths':
        root=svg_tree(file)
        if any(e.tag.split('}')[-1]=='use' for e in root.iter()):
            raise VerifierUnavailable('Referenced cutting geometry requires expanded-path validation')
        closed,count=closed_svg_contours(root)
        return closed, {'contour_count':count}
    if op == 'duration_range':
        info=probe(file)
        video=next((s for s in info['streams'] if s['codec_type']=='video'),None)
        if not video:return False, {'reason':'No video stream'}
        if 'duration' not in video:
            raise VerifierUnavailable('Video-stream duration is unavailable; container or audio duration cannot substitute for it')
        duration=float(video['duration'])
        return assertion['min']-0.05<=duration<=assertion['max']+0.05, {'video_seconds':duration,'container_seconds':float(info['format']['duration'])}
    if op == 'audio_stream':
        found=any(s['codec_type']=='audio' for s in probe(file)['streams'])
        return found==assertion['required'], {'audio_stream':found}
    if op in ('video_codec','pixel_format','frame_rate'):
        video=next((s for s in probe(file)['streams'] if s['codec_type']=='video'),None)
        if not video:return False, {'reason':'No video stream'}
        field={'video_codec':'codec_name','pixel_format':'pix_fmt','frame_rate':'avg_frame_rate'}[op]
        if field not in video:raise VerifierUnavailable('Stream property unavailable: '+field)
        value=video[field]
        if op=='frame_rate':
            value=float(Fraction(value))
            return abs(value-assertion['equals'])<0.001, {'measured':value}
        return value==assertion['equals'], {'measured':value}
    if op == 'non_silent_audio':
        raw=command(['ffmpeg','-v','error','-i',str(file),'-vn','-ac','1','-ar','8000','-f','f32le','-'])
        samples=np.frombuffer(raw,dtype='<f4')
        peak=float(np.max(np.abs(samples))) if len(samples) else 0
        return peak>0.0001, {'peak_amplitude':peak}
    if op == 'moving_picture':
        raw=command(['ffmpeg','-v','error','-i',str(file),'-vf','fps=2,scale=32:32','-pix_fmt','gray','-f','rawvideo','-'])
        frames=np.frombuffer(raw,dtype=np.uint8)
        if frames.size<2048:
            return False, {'sampled_frames':frames.size//1024}
        frames=frames.reshape(-1,1024).astype(float)
        difference=float(np.max(np.mean(np.abs(np.diff(frames,axis=0)),axis=1)))
        return difference>1, {'largest_mean_frame_difference':difference,'note':'This detects changing pictures, not meaningful motion or good editing.'}
    if op == 'editable_source_present':
        with zipfile.ZipFile(file) as archive:
            infos=archive.infolist()
            natives=[x.filename for x in infos if x.file_size>0 and Path(x.filename).suffix.lower() in ('.indd','.idml','.ai','.psd','.svg','.pptx')]
            refs=[]
            for name in archive.namelist():
                if Path(name).name=='document.json':
                    data=json.loads(archive.read(name))
                    url=data.get('editable_url','')
                    host=(urlparse(url).hostname or '').lower()
                    if url.startswith('https://') and (host=='adobe.com' or host.endswith('.adobe.com')):
                        refs.append(name)
        return bool(natives or refs), {'native_files':natives,'document_references':refs,'note':'Opening and editability are independently assessed by a human.'}
    if op == 'icc_profile':
        expected=assertion.get('expects','sRGB').lower().replace(' ','')
        with Image.open(file) as image:
            if image.mode in ('CMYK','LAB'):
                return False, {'mode':image.mode}
            icc=image.info.get('icc_profile')
            if icc:
                from PIL import ImageCms
                description=ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc))).strip()
                return expected in description.lower().replace(' ',''), {'profile':description}
            if 'srgb' in image.info:
                return True, {'profile':'PNG sRGB chunk'}
            return bool(assertion.get('allow_untagged',True)), {'profile':None,'note':'Untagged image; browsers and web channels treat it as sRGB.'}
    if op == 'pdf_fonts_embedded':
        fonts=pdf_font_inventory(PdfReader(file))
        missing=sorted({name for name,embedded in fonts if not embedded})
        return not missing, {'fonts':sorted({name for name,_ in fonts}),'not_embedded':missing}
    if op == 'pdf_output_intent':
        wanted=normalize_name(assertion['contains'])
        found=pdf_output_intents(PdfReader(file))
        return any(wanted in normalize_name(value) for value in found), {'output_intents':found}
    if op == 'pdf_no_cmyk':
        reader=PdfReader(file)
        evidence=pdf_cmyk_usage(reader)
        evidence['output_intents']=pdf_output_intents(reader)
        cmyk_intent=any('cmyk' in value.lower() or 'coated' in value.lower() or 'fogra' in value.lower() or 'swop' in value.lower() for value in evidence['output_intents'])
        return not (evidence['colour_spaces'] or evidence['operators'] or cmyk_intent), evidence
    if op == 'pdf_text_style':
        return pdf_text_style(PdfReader(file), assertion)
    raise NotImplementedError(op)


def normalize_name(value):
    return re.sub(r'[^a-z0-9]', '', str(value).lower())


def _resolved(value):
    return value.get_object() if hasattr(value, 'get_object') else value


def _walk_resources(resources, seen=None):
    """Yield every resource dictionary reachable through Form XObjects."""
    seen=set() if seen is None else seen
    resources=_resolved(resources)
    if not resources or id(resources) in seen:
        return
    seen.add(id(resources))
    yield resources
    for xobject in (_resolved(resources.get('/XObject')) or {}).values():
        xobject=_resolved(xobject)
        if xobject.get('/Subtype')=='/Form' and '/Resources' in xobject:
            yield from _walk_resources(xobject['/Resources'], seen)


def pdf_font_inventory(reader):
    fonts=[]
    for page in reader.pages:
        for resources in _walk_resources(page.get('/Resources')):
            for font in (_resolved(resources.get('/Font')) or {}).values():
                font=_resolved(font)
                name=str(font.get('/BaseFont','(unnamed)')).lstrip('/')
                subtype=font.get('/Subtype')
                if subtype=='/Type3':
                    fonts.append((name,True));continue
                if subtype=='/Type0':
                    descendants=_resolved(font.get('/DescendantFonts')) or []
                    font=_resolved(descendants[0]) if descendants else font
                descriptor=_resolved(font.get('/FontDescriptor')) or {}
                fonts.append((name,any(key in descriptor for key in ('/FontFile','/FontFile2','/FontFile3'))))
    return fonts


def pdf_output_intents(reader):
    values=[]
    for intent in _resolved(reader.trailer['/Root'].get('/OutputIntents')) or []:
        intent=_resolved(intent)
        for key in ('/OutputConditionIdentifier','/OutputCondition','/Info','/RegistryName'):
            if key in intent:
                values.append(str(intent[key]))
        profile=_resolved(intent.get('/DestOutputProfile'))
        if profile is not None:
            try:
                from PIL import ImageCms
                values.append(ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(profile.get_data()))).strip())
            except Exception:
                values.append('(unreadable ICC profile)')
    return values


def _is_cmyk(space):
    space=_resolved(space)
    if space is None:
        return False
    if isinstance(space,str) or not hasattr(space,'__getitem__'):
        return str(space) in ('/DeviceCMYK','/CMYK')
    if len(space) and str(space[0])=='/ICCBased':
        return int(_resolved(space[1]).get('/N',0))==4
    if len(space) and str(space[0]) in ('/Indexed','/I'):
        return _is_cmyk(space[1])
    if len(space) and str(space[0]) in ('/Separation','/DeviceN'):
        return _is_cmyk(space[2])
    return False


def pdf_cmyk_usage(reader):
    from pypdf.generic import ContentStream
    spaces=set();operators=set()
    for number,page in enumerate(reader.pages,1):
        for resources in _walk_resources(page.get('/Resources')):
            for name,space in (_resolved(resources.get('/ColorSpace')) or {}).items():
                if _is_cmyk(space): spaces.add(f'page {number}: {name}')
            for name,xobject in (_resolved(resources.get('/XObject')) or {}).items():
                xobject=_resolved(xobject)
                if xobject.get('/Subtype')=='/Image' and _is_cmyk(xobject.get('/ColorSpace')):
                    spaces.add(f'page {number}: image {name}')
        contents=page.get_contents()
        if contents is not None:
            for _,operator in ContentStream(contents,reader).operations:
                if operator in (b'k',b'K'):
                    operators.add(f'page {number}: {operator.decode()}')
    return {'colour_spaces':sorted(spaces),'operators':sorted(operators)}


WEIGHT_WORDS=('extralight','ultralight','thin','light','book','regular','roman','normal','medium','semibold','demibold','extrabold','ultrabold','bold','black','heavy')


WEIGHT_ALIASES={'demibold':'semibold','ultrabold':'extrabold','ultralight':'extralight'}


def _weight_of(style):
    for word in sorted(WEIGHT_WORDS,key=len,reverse=True):
        if word in style:
            return WEIGHT_ALIASES.get(word,word)
    return ''


def _style_of(font_name):
    name=re.sub(r'^[A-Z]{6}\+','',font_name.lstrip('/'))
    return name, normalize_name(name.split('-',1)[1] if '-' in name else '')


def pdf_text_style(reader, assertion):
    """Find live text and confirm its font family, optional weight and optional effective size.

    Every occurrence on the selected pages is examined; the check passes when at least one occurrence is set as
    stated (the same words may also appear elsewhere in another role). Matching ignores case unless
    "case_sensitive" is true, because typed case and displayed capitals can differ.
    """
    wanted=re.sub(r'\s+',' ',assertion['text']).strip()
    fold=(lambda s:s) if assertion.get('case_sensitive') else str.lower
    wanted=fold(wanted)
    family=normalize_name(assertion['family'])
    weight=normalize_name(assertion.get('weight','')) or None
    size=assertion.get('size_pt');tolerance=float(assertion.get('tolerance_pt',0.3))
    pages=[assertion['page']] if 'page' in assertion else range(1,len(reader.pages)+1)
    any_text=False
    failures=[]
    for number in pages:
        chars=[]
        def visitor(text,cm,tm,font_dict,font_size):
            if not text:return
            name=str(font_dict.get('/BaseFont','')) if font_dict else ''
            y=(tm[2]*cm[0]+tm[3]*cm[2], tm[2]*cm[1]+tm[3]*cm[3])
            effective=float(font_size)*math.hypot(*y)
            chars.extend((ch,name,effective) for ch in text)
        reader.pages[number-1].extract_text(visitor_text=visitor)
        if any(ch.strip() for ch,_,_ in chars):any_text=True
        normal=[];index=[]
        for position,(ch,_,_) in enumerate(chars):
            if ch.isspace():
                if normal and normal[-1]!=' ':normal.append(' ');index.append(position)
            else:
                normal.append(ch);index.append(position)
        haystack=fold(''.join(normal))
        if len(haystack)!=len(normal):
            haystack=''.join(normal)  # lower() changed the length; fall back to exact case
        start=haystack.find(wanted)
        while start>=0:
            matched=[chars[index[i]] for i in range(start,start+len(wanted)) if not chars[index[i]][0].isspace()]
            ok,evidence=_judge_style(matched,number,family,weight,size,tolerance)
            if ok:
                return True, evidence
            failures.append(evidence)
            start=haystack.find(wanted,start+1)
    if failures:
        return False, {'occurrences':len(failures),'first':failures[0]}
    if not any_text:
        raise VerifierUnavailable('The PDF has no live text; outlined lettering needs the matching human check')
    raise VerifierUnavailable('The exact text was not found as live text; the matching content check covers its presence')


def _judge_style(matched,number,family,weight,size,tolerance):
    problems=[]
    for ch,name,effective in matched:
        full,style=_style_of(name)
        if family not in normalize_name(full):
            problems.append(f'{ch!r} in {full or "unknown font"}');continue
        if weight:
            actual=_weight_of(style) or _weight_of(normalize_name(full).replace(family,'',1))
            regular=('','regular','roman','book','normal')
            if (weight in regular and actual not in regular) or (weight not in regular and actual!=WEIGHT_ALIASES.get(weight,weight)):
                problems.append(f'{ch!r} weight {actual or "unstated"}')
        if size is not None and abs(effective-float(size))>tolerance:
            problems.append(f'{ch!r} at {effective:.2f} pt')
    evidence={'page':number,'fonts':sorted({_style_of(n)[0] for _,n,_ in matched}),'sizes_pt':sorted({round(e,2) for _,_,e in matched})}
    if problems:evidence['problems']=problems[:12]
    return not problems, evidence


def evaluate(spec, artifact_root):
    artifact_root=artifact_root.resolve()
    outputs={o['output_id']:o for o in spec['deliverables']}
    results=[]
    for check in spec['verifiers_auto']+spec['verifiers_human']:
        output=outputs[check['output_id']]
        file=(artifact_root/output['path']).resolve()
        result={'check_id':check['check_id'],'output_id':check['output_id'],'output_reference':check['output_reference'],'type':check['type']}
        if not file.is_relative_to(artifact_root):
            result.update(status='evaluation_error',reason='Output path escapes artifact root')
        elif not file.is_file():
            result.update(status='fail' if check.get('assertion',{}).get('op')=='file_exists' else 'not_assessable',reason='Required output is missing')
        elif check['type']=='human':
            result.update(status='pending_expert_review')
        else:
            try:
                passed,evidence=verify(file,check['assertion'],artifact_root)
                result.update(status='pass' if passed else 'fail',evidence=evidence)
            except (ImportError,FileNotFoundError,NotImplementedError,VerifierUnavailable) as error:
                result.update(status='evaluation_error',reason=str(error)[:300])
            except Exception as error:
                result.update(status='fail',reason=str(error)[:300])
        results.append(result)
    return {'task_id':spec['new_id'],'overall_status':'pending_expert_review' if all(r['status'] in ('pass','pending_expert_review') for r in results) else 'incomplete_or_failed','results':results}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--spec',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    report=evaluate(json.loads(args.spec.read_text()),args.artifacts)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'task_id':report['task_id'],'status':report['overall_status'],'checks':len(report['results'])}))
