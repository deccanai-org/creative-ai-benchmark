"""Run file-bound objective checks. A missing artifact never becomes a process-based pass."""
import argparse
import ctypes.util
import hashlib
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
        subtype=assertion.get('subtype','/GTS_PDFX')
        intents=pdf_output_intent_records(PdfReader(file))
        matched=[i for i in intents if i['subtype']==subtype and i['profile_space']=='CMYK' and i['profile_valid']
                 and wanted == normalize_name(i['profile_description'])
                 and (not assertion.get('profile_sha256') or i.get('profile_sha256')==assertion['profile_sha256'])]
        return bool(matched), {'output_intents':intents,'required':f'{subtype} intent with a valid embedded CMYK ICC profile whose description is {assertion["contains"]}'}
    if op == 'pdf_no_cmyk':
        reader=PdfReader(file)
        evidence=pdf_cmyk_usage(reader)
        intents=pdf_output_intent_records(reader)
        evidence['output_intents']=intents
        cmyk_intent=any(i['profile_space']=='CMYK' or any(re.search(r'cmyk|coated|fogra|swop|gracol|pso',v,re.I) for v in i['names']) for i in intents)
        return not (evidence['colour_spaces'] or evidence['operators'] or cmyk_intent), evidence
    if op == 'pdf_text_style':
        if any(key in assertion for key in ('leading_pt','tracking')):
            return pdf_text_metrics(file, assertion)
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


def pdf_output_intent_records(reader):
    """Every OutputIntent with its names and what its embedded DestOutputProfile really is."""
    records=[]
    for intent in _resolved(reader.trailer['/Root'].get('/OutputIntents')) or []:
        intent=_resolved(intent)
        record={'subtype':str(intent.get('/S','')),'names':[str(intent[k]) for k in ('/OutputConditionIdentifier','/OutputCondition','/Info','/RegistryName') if k in intent],
                'profile_valid':False,'profile_space':None,'profile_description':''}
        profile=_resolved(intent.get('/DestOutputProfile'))
        if profile is not None:
            try:
                data=profile.get_data()
                record['profile_sha256']=hashlib.sha256(data).hexdigest()
                record['profile_space']=data[16:20].decode('latin-1').strip()
                if len(data)<132 or data[36:40]!=b'acsp' or int.from_bytes(data[:4], 'big')!=len(data):
                    raise ValueError('Invalid ICC header or declared profile length')
                from PIL import ImageCms
                parsed=ImageCms.ImageCmsProfile(io.BytesIO(data))
                record['profile_description']=ImageCms.getProfileDescription(parsed).strip()
                channels={'GRAY':1,'RGB':3,'CMYK':4}.get(record['profile_space'])
                if channels is None or int(profile.get('/N',0))!=channels:
                    raise ValueError('PDF profile channel count does not match the embedded ICC profile')
                mode={'GRAY':'L','RGB':'RGB','CMYK':'CMYK'}[record['profile_space']]
                ImageCms.buildTransformFromOpenProfiles(parsed,ImageCms.createProfile('LAB'),mode,'LAB')
                record['profile_valid']=True
            except Exception as error:
                record['profile_valid']=False
                record['profile_error']=str(error)[:120]
        records.append(record)
    return records


def pdf_output_intents(reader):
    return [v for r in pdf_output_intent_records(reader) for v in r['names']+([r['profile_description']] if r['profile_description'] else [])]


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
    if len(space) and str(space[0])=='/Pattern' and len(space)>1:
        return _is_cmyk(space[1])
    return False


def _named_space(name, resources):
    if str(name) in ('/DeviceCMYK','/CMYK','/DeviceRGB','/RGB','/DeviceGray','/G','/Pattern'):
        return name
    return (_resolved(resources.get('/ColorSpace')) or {}).get(name) if resources else None


def pdf_cmyk_usage(reader):
    """Find CMYK anywhere it can paint: page and nested Form XObject streams, tiling patterns, shadings,
    images (XObject and inline), transparency groups and annotation appearances."""
    from pypdf.generic import ContentStream
    spaces=set();operators=set();seen=set()

    def note_space(space,label):
        if _is_cmyk(space): spaces.add(label)

    def scan(stream,resources,label,depth=0):
        key=id(stream)
        if key in seen or depth>12:
            return
        seen.add(key)
        resources=_resolved(resources) or {}
        for name,space in (_resolved(resources.get('/ColorSpace')) or {}).items():
            note_space(space,f'{label}: colour space {name}')
        group=_resolved(stream.get('/Group')) if hasattr(stream,'get') else None
        if group and group.get('/CS') is not None:
            note_space(group.get('/CS'),f'{label}: transparency group')
        try:
            operations=ContentStream(stream,reader).operations
        except Exception:
            return
        for operands,operator in operations:
            if operator in (b'k',b'K'):
                operators.add(f'{label}: {operator.decode()}')
            elif operator in (b'cs',b'CS') and operands:
                note_space(_named_space(operands[0],resources),f'{label}: {operator.decode()} {operands[0]}')
            elif operator==b'sh' and operands:
                shading=_resolved((_resolved(resources.get('/Shading')) or {}).get(operands[0]))
                if shading is not None: note_space(shading.get('/ColorSpace'),f'{label}: shading {operands[0]}')
            elif operator in (b'scn',b'SCN') and operands and str(operands[-1]).startswith('/'):
                pattern=_resolved((_resolved(resources.get('/Pattern')) or {}).get(operands[-1]))
                if pattern is not None:
                    if pattern.get('/PatternType')==1:
                        scan(pattern,pattern.get('/Resources') or resources,f'{label} > pattern {operands[-1]}',depth+1)
                    else:
                        shading=_resolved(pattern.get('/Shading'))
                        if shading is not None: note_space(shading.get('/ColorSpace'),f'{label}: pattern {operands[-1]}')
            elif operator==b'INLINE IMAGE':
                settings=operands.get('settings',{}) if isinstance(operands,dict) else {}
                space=settings.get('/CS',settings.get('/ColorSpace'))
                if space is not None: note_space(_named_space(space,resources),f'{label}: inline image')
            elif operator==b'Do' and operands:
                xobject=_resolved((_resolved(resources.get('/XObject')) or {}).get(operands[0]))
                if xobject is None: continue
                if xobject.get('/Subtype')=='/Image':
                    note_space(xobject.get('/ColorSpace'),f'{label}: image {operands[0]}')
                elif xobject.get('/Subtype')=='/Form':
                    scan(xobject,xobject.get('/Resources') or resources,f'{label} > form {operands[0]}',depth+1)

    for number,page in enumerate(reader.pages,1):
        resources=page.get('/Resources')
        group=_resolved(page.get('/Group'))
        if group and group.get('/CS') is not None:
            note_space(group.get('/CS'),f'page {number}: page group')
        contents=page.get_contents()
        if contents is not None:
            scan(contents,resources,f'page {number}')
        for resource_dict in _walk_resources(resources):
            for name,xobject in (_resolved(resource_dict.get('/XObject')) or {}).items():
                xobject=_resolved(xobject)
                if xobject.get('/Subtype')=='/Image':
                    note_space(xobject.get('/ColorSpace'),f'page {number}: image {name}')
        for annot in _resolved(page.get('/Annots')) or []:
            appearance=_resolved((_resolved(_resolved(annot).get('/AP')) or {}).get('/N'))
            if appearance is not None and hasattr(appearance,'get_data'):
                scan(appearance,appearance.get('/Resources'),f'page {number}: annotation')
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


def _median(values):
    values=sorted(values)
    return values[len(values)//2] if len(values)%2 else (values[len(values)//2-1]+values[len(values)//2])/2


def pdf_text_metrics(file, assertion):
    """pdf_text_style plus measured leading (pt, baseline to baseline) and tracking (thousandths of an em).

    Uses pdfminer.six glyph positions: tracking is the median extra advance between neighbouring glyphs of the
    matched text on one baseline (kerning pairs vary, so the median is used); leading is the median distance between
    the matched text's baselines, so it needs text that runs over at least two lines.
    """
    try:
        from pdfminer.converter import PDFPageAggregator
        from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
        from pdfminer.pdfpage import PDFPage
        from pdfminer.layout import LTChar
    except ImportError as error:
        raise VerifierUnavailable('pdfminer.six is required for leading and tracking checks') from error
    fold=(lambda t:t) if assertion.get('case_sensitive') else str.lower
    needle=fold(re.sub(r'\s+','',assertion['text']))
    family=normalize_name(assertion['family'])
    weight=normalize_name(assertion.get('weight','')) or None
    size=assertion.get('size_pt');tolerance=float(assertion.get('tolerance_pt',0.3))
    leading=assertion.get('leading_pt');leading_tol=float(assertion.get('leading_tolerance_pt',0.5))
    tracking=assertion.get('tracking');tracking_tol=float(assertion.get('tracking_tolerance',8))
    wanted_pages=None if 'page' not in assertion else {assertion['page']}

    class MetricsAggregator(PDFPageAggregator):
        def render_char(self, matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate):
            advance=super().render_char(matrix,font,fontsize,scaling,rise,cid,ncs,graphicstate)
            glyph=self.cur_item._objs[-1]
            # Tf and Tz are separate from Tm; retain both instead of assuming a 1 pt font.
            glyph.em_pt=abs(fontsize)*math.hypot(matrix[2],matrix[3])
            glyph.advance_em=abs(fontsize*scaling)*math.hypot(matrix[0],matrix[1])
            return advance

    def pages():
        manager=PDFResourceManager()
        device=MetricsAggregator(manager)
        interpreter=PDFPageInterpreter(manager,device)
        try:
            with open(file,'rb') as stream:
                for page in PDFPage.get_pages(stream):
                    interpreter.process_page(page)
                    yield device.get_result()
        finally:
            device.close()

    def walk(item):
        if isinstance(item,LTChar) or not hasattr(item,'__iter__'):
            yield item
        else:
            for child in item:
                yield from walk(child)

    any_text=False;failures=[];unmeasurable=[]
    for number,page in enumerate(pages(),1):
        if wanted_pages and number not in wanted_pages:continue
        items=list(walk(page))
        glyphs=[(i,o) for i,o in enumerate(items) if isinstance(o,LTChar) and o.get_text().strip()]
        if glyphs:any_text=True
        hay='';owner=[]
        for position,(_,glyph) in enumerate(glyphs):
            text=fold(glyph.get_text())
            hay+=text;owner.extend([position]*len(text))
        start=hay.find(needle)
        while start>=0:
            positions=sorted(set(owner[start:start+len(needle)]))
            matched=[glyphs[p] for p in positions]
            rows=[(o.get_text(),o.fontname,o.em_pt) for _,o in matched]
            ok,evidence=_judge_style(rows,number,family,weight,size,tolerance)
            problems=list(evidence.get('problems',[]))
            unavailable=[]
            first=matched[0][1]
            axis_length=math.hypot(first.matrix[0],first.matrix[1])
            if not axis_length or not first.em_pt:
                raise VerifierUnavailable('Degenerate text transform cannot be measured')
            ux,uy=first.matrix[0]/axis_length,first.matrix[1]/axis_length
            if any(abs(o.matrix[0]*uy-o.matrix[1]*ux)>0.001 for _,o in matched):
                raise VerifierUnavailable('Matched text changes baseline direction')
            if tracking is not None:
                gaps=[]
                for (i,a),(j,b) in zip(matched,matched[1:]):
                    dx,dy=b.matrix[4]-a.matrix[4],b.matrix[5]-a.matrix[5]
                    if j==i+1 and a.fontname==b.fontname and a.advance_em and abs(-dx*uy+dy*ux)<0.2*a.em_pt:
                        advance=a.adv*math.hypot(a.matrix[0],a.matrix[1])
                        gaps.append((dx*ux+dy*uy-advance)/a.advance_em*1000)
                if gaps:
                    measured=_median(gaps);evidence['tracking_units']=round(measured,1)
                    if abs(measured-float(tracking))>tracking_tol:problems.append(f'tracking {measured:+.0f} units, expected {float(tracking):+.0f}')
                else:
                    unavailable.append('tracking needs two neighbouring glyphs on one line')
            if leading is not None:
                baselines=[]
                for y in sorted({round(-o.matrix[4]*uy+o.matrix[5]*ux,1) for _,o in matched},reverse=True):
                    if not baselines or baselines[-1]-y>0.5:baselines.append(y)
                if len(baselines)>=2:
                    measured=_median([a-b for a,b in zip(baselines,baselines[1:])]);evidence['leading_pt']=round(measured,2)
                    if abs(measured-float(leading))>leading_tol:problems.append(f'leading {measured:.2f} pt, expected {float(leading)} pt')
                else:
                    unavailable.append('leading needs the text to run over at least two lines')
            if problems:
                evidence['problems']=problems[:12];failures.append(evidence)
            elif not unavailable:
                return True,evidence
            unmeasurable.extend(unavailable)
            start=hay.find(needle,start+1)
    if failures:
        return False,{'occurrences':len(failures),'first':failures[0]}
    if unmeasurable:
        raise VerifierUnavailable('; '.join(sorted(set(unmeasurable))))
    if not any_text:
        raise VerifierUnavailable('The PDF has no live text; outlined lettering needs the matching human check')
    raise VerifierUnavailable('The exact text was not found as live text; the matching content check covers its presence')


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
