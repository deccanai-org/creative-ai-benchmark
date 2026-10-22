import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter

import verify_outputs as v


class AtomicVerifierTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_dimensions_independent(self):
        p=self.root/'frame.png'
        Image.new('RGB',(1080,900),'white').save(p)
        self.assertTrue(v.verify(p,{'op':'width','equals':1080})[0])
        self.assertFalse(v.verify(p,{'op':'height','equals':1350})[0])

    def test_opaque_png_rejected(self):
        p=self.root/'logo.png'
        Image.new('RGBA',(20,20),(255,255,255,255)).save(p)
        self.assertFalse(v.verify(p,{'op':'transparent_background'})[0])

    def test_transparent_png_accepted(self):
        p=self.root/'logo.png'
        image=Image.new('RGBA',(20,20),(0,0,0,0))
        image.putpixel((10,10),(0,0,0,255));image.save(p)
        self.assertTrue(v.verify(p,{'op':'transparent_background'})[0])

    def test_empty_transparent_png_rejected(self):
        p=self.root/'empty.png'
        Image.new('RGBA',(20,20),(0,0,0,0)).save(p)
        self.assertFalse(v.verify(p,{'op':'transparent_background'})[0])

    def test_pdf_page_count(self):
        p=self.root/'book.pdf'
        writer=PdfWriter();writer.add_blank_page(width=595.276,height=841.89)
        with p.open('wb') as stream:writer.write(stream)
        self.assertTrue(v.verify(p,{'op':'pages','equals':1})[0])
        self.assertFalse(v.verify(p,{'op':'pages','equals':2})[0])
        self.assertTrue(v.verify(p,{'op':'trim_width_mm','equals':210,'tolerance':0.2})[0])

    def test_missing_video_fails_delivery(self):
        spec={'new_id':'TEST','deliverables':[{'output_id':'film','path':'film.mp4'}],
              'verifiers_auto':[{'check_id':'A1','output_id':'film','output_reference':'film.mp4','type':'auto','assertion':{'op':'file_exists'}},
                                {'check_id':'A2','output_id':'film','output_reference':'film.mp4','type':'auto','assertion':{'op':'audio_stream','required':True}}],
              'verifiers_human':[{'check_id':'H1','output_id':'film','output_reference':'film.mp4','type':'human'}]}
        report=v.evaluate(spec,self.root)
        self.assertEqual([r['status'] for r in report['results']],['fail','not_assessable','not_assessable'])
        self.assertEqual(report['overall_status'],'incomplete_or_failed')

    def test_pdf_page_reference_is_atomic(self):
        p=self.root/'mixed.pdf'
        writer=PdfWriter();writer.add_blank_page(width=595.276,height=841.89)
        writer.add_blank_page(width=420,height=595)
        with p.open('wb') as stream:writer.write(stream)
        self.assertTrue(v.verify(p,{'op':'trim_width_mm','equals':210,'tolerance':0.2,'page':1})[0])
        self.assertFalse(v.verify(p,{'op':'trim_width_mm','equals':210,'tolerance':0.2,'page':2})[0])
        self.assertFalse(v.verify(p,{'op':'trim_width_mm','equals':210,'tolerance':0.2,'page':3})[0])

    def test_source_archive_cannot_be_just_png(self):
        p=self.root/'source.zip'
        with zipfile.ZipFile(p,'w') as archive:archive.writestr('flat.png',b'not a native source')
        self.assertFalse(v.verify(p,{'op':'editable_source_present'})[0])

    def test_svg_background_and_path(self):
        p=self.root/'mark.svg'
        p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><path d="M20 20 L80 20 L80 80 Z"/></svg>')
        self.assertTrue(v.verify(p,{'op':'closed_paths'})[0])
        self.assertTrue(v.verify(p,{'op':'transparent_background'})[0])
        p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><path d="M20 20 L80 20 L80 80"/></svg>')
        self.assertFalse(v.verify(p,{'op':'closed_paths'})[0])

    def test_external_svg_resources_rejected(self):
        p=self.root/'external.svg'
        p.write_text('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.invalid/private.png"/></svg>')
        with self.assertRaises(ValueError):v.svg_tree(p)

    def test_real_silent_source_does_not_pass_audio_requirement(self):
        sources=Path('/Users/dhiren/Downloads/Deccan/Adobe-Freelance-Leads/input_assets_v3/MOTION-02/assets')
        file=next(sources.glob('*.mp4'))
        self.assertFalse(v.verify(file,{'op':'audio_stream','required':True})[0])
        self.assertTrue(v.verify(file,{'op':'audio_stream','required':False})[0])
        self.assertFalse(v.verify(file,{'op':'duration_range','min':20,'max':30})[0])

    def test_long_audio_cannot_inflate_video_runtime(self):
        metadata={'format':{'duration':'30'},'streams':[{'codec_type':'video','duration':'5'},{'codec_type':'audio','duration':'30'}]}
        with patch.object(v,'probe',return_value=metadata):
            self.assertFalse(v.verify(self.root/'film.mp4',{'op':'duration_range','min':20,'max':30})[0])

    def test_unknown_video_runtime_is_not_a_pass(self):
        metadata={'format':{'duration':'30'},'streams':[{'codec_type':'video'}]}
        with patch.object(v,'probe',return_value=metadata), self.assertRaises(v.VerifierUnavailable):
            v.verify(self.root/'film.mp4',{'op':'duration_range','min':20,'max':30})

    def test_video_delivery_properties_are_independent(self):
        metadata={'streams':[{'codec_type':'video','codec_name':'h264','pix_fmt':'yuv420p','avg_frame_rate':'30000/1001'}]}
        with patch.object(v,'probe',return_value=metadata):
            self.assertTrue(v.verify(self.root/'film.mp4',{'op':'video_codec','equals':'h264'})[0])
            self.assertTrue(v.verify(self.root/'film.mp4',{'op':'pixel_format','equals':'yuv420p'})[0])
            self.assertFalse(v.verify(self.root/'film.mp4',{'op':'frame_rate','equals':24})[0])

    def test_svg_validity_does_not_approve_identity(self):
        p=self.root/'wrong-crest.svg'
        p.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="30"/></svg>')
        spec={'new_id':'TEST','deliverables':[{'output_id':'crest','path':p.name}],
              'verifiers_auto':[{'check_id':'A1','output_id':'crest','output_reference':p.name,'type':'auto','assertion':{'op':'decodable','format':'svg'}}],
              'verifiers_human':[{'check_id':'H1','output_id':'crest','output_reference':p.name,'type':'human','check':'The shield matches the approved crest.'}]}
        report=v.evaluate(spec,self.root)
        self.assertEqual(report['results'][0]['status'],'pass')
        self.assertEqual(report['results'][1]['status'],'pending_expert_review')
        self.assertNotEqual(report['overall_status'],'pass')


def _cairo_pdf(path, svg):
    import ctypes.util
    finder=ctypes.util.find_library
    ctypes.util.find_library=lambda name: '/opt/homebrew/lib/libcairo.2.dylib' if 'cairo' in name else finder(name)
    import cairosvg
    path.write_bytes(cairosvg.svg2pdf(bytestring=svg.encode()))
    return path


class PilotThirteenOperationTests(unittest.TestCase):
    """Operations added 2026-10-21 so machine facts are not asked of human annotators."""
    SVG=('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
         '<text x="10" y="50" font-family="Helvetica" font-size="20">Paul Devoe</text>'
         '<text x="10" y="120" font-family="Courier" font-weight="bold" font-size="12">Licence 12345</text></svg>')

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.pdf=_cairo_pdf(self.root/'card.pdf',self.SVG)

    def tearDown(self):
        self.temp.cleanup()

    def test_text_style_family_size_and_weight(self):
        self.assertTrue(v.verify(self.pdf,{'op':'pdf_text_style','text':'Paul Devoe','family':'Helvetica','size_pt':15})[0])
        self.assertTrue(v.verify(self.pdf,{'op':'pdf_text_style','text':'Licence 12345','family':'Courier','weight':'Bold'})[0])

    def test_text_style_rejects_wrong_family_size_or_weight(self):
        self.assertFalse(v.verify(self.pdf,{'op':'pdf_text_style','text':'Paul Devoe','family':'Lexend'})[0])
        self.assertFalse(v.verify(self.pdf,{'op':'pdf_text_style','text':'Paul Devoe','family':'Helvetica','size_pt':20})[0])
        self.assertFalse(v.verify(self.pdf,{'op':'pdf_text_style','text':'Licence 12345','family':'Courier','weight':'Regular'})[0])
        self.assertFalse(v.verify(self.pdf,{'op':'pdf_text_style','text':'Paul Devoe','family':'Helvetica','weight':'SemiBold'})[0])

    def test_text_style_any_occurrence_and_case(self):
        pdf=_cairo_pdf(self.root/'rates.pdf','<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200">'
            '<text x="10" y="40" font-family="Helvetica" font-size="16">From 520 a night</text>'
            '<text x="10" y="120" font-family="Courier" font-size="12">520</text>'
            '<text x="10" y="170" font-family="Helvetica" font-size="12">Sable Quartet</text></svg>')
        # first "520" is 12 pt Helvetica body copy, the second is the 9 pt Courier rate: any matching occurrence passes
        self.assertTrue(v.verify(pdf,{'op':'pdf_text_style','text':'520','family':'Courier','size_pt':9})[0])
        self.assertFalse(v.verify(pdf,{'op':'pdf_text_style','text':'520','family':'Courier','size_pt':20})[0])
        self.assertTrue(v.verify(pdf,{'op':'pdf_text_style','text':'SABLE QUARTET','family':'Helvetica'})[0])
        with self.assertRaises(v.VerifierUnavailable):
            v.verify(pdf,{'op':'pdf_text_style','text':'SABLE QUARTET','family':'Helvetica','case_sensitive':True})

    def test_text_leading_and_tracking(self):
        # 20 px (15 pt) Helvetica, letter-spacing 0.6 px = 0.45 pt = +30 units; lines 40 px apart = 30 pt leading
        pdf=_cairo_pdf(self.root/'block.pdf','<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200"><text font-family="Helvetica" font-size="20" letter-spacing="0.6">'
            '<tspan x="10" y="40">Astrid Vellacourt</tspan><tspan x="10" y="80">Design lead</tspan></text></svg>')
        ok,evidence=v.verify(pdf,{'op':'pdf_text_style','text':'Astrid Vellacourt Design lead','family':'Helvetica','size_pt':15,'leading_pt':30,'tracking':30})
        self.assertTrue(ok,evidence)
        self.assertFalse(v.verify(pdf,{'op':'pdf_text_style','text':'Astrid Vellacourt','family':'Helvetica','tracking':0})[0])
        self.assertFalse(v.verify(pdf,{'op':'pdf_text_style','text':'Astrid Vellacourt Design lead','family':'Helvetica','leading_pt':38})[0])
        with self.assertRaises(v.VerifierUnavailable):
            v.verify(pdf,{'op':'pdf_text_style','text':'Astrid Vellacourt','family':'Helvetica','leading_pt':30})
        plain=_cairo_pdf(self.root/'plain.pdf','<svg xmlns="http://www.w3.org/2000/svg" width="400" height="100"><text x="10" y="40" font-family="Helvetica" font-size="20">Astrid Vellacourt</text></svg>')
        self.assertTrue(v.verify(plain,{'op':'pdf_text_style','text':'Astrid Vellacourt','family':'Helvetica','tracking':0})[0])

    def test_text_style_missing_text_is_not_a_pass_or_fail(self):
        with self.assertRaises(v.VerifierUnavailable):
            v.verify(self.pdf,{'op':'pdf_text_style','text':'Priya Nandakumar','family':'Helvetica'})

    def _text_operator_pdf(self, name, operators):
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        writer=PdfWriter();page=writer.add_blank_page(600,600)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        content=DecodedStreamObject();content.set_data(operators)
        page[NameObject('/Contents')]=writer._add_object(content)
        path=self.root/name
        with path.open('wb') as handle:writer.write(handle)
        return path

    def test_metrics_with_tf_tm_horizontal_scaling_and_rotation(self):
        variants=[
            b'/F1 15 Tf 0.45 Tc 30 TL 1 0 0 1 20 250 Tm',
            b'/F1 1 Tf 0.03 Tc 2 TL 15 0 0 15 20 250 Tm',
            b'/F1 15 Tf 0.45 Tc 30 TL 80 Tz 1 0 0 1 20 250 Tm',
            b'/F1 15 Tf 0.45 Tc 30 TL 0 1 -1 0 250 20 Tm',
        ]
        for i,operators in enumerate(variants):
            with self.subTest(operators=operators):
                pdf=self._text_operator_pdf(f'operators-{i}.pdf',b'BT '+operators+b' (Astrid Vellacourt) Tj T* (Design lead) Tj ET')
                assertion={'op':'pdf_text_style','text':'Astrid Vellacourt Design lead','family':'Helvetica','size_pt':15,'tracking':30,'leading_pt':30}
                ok,evidence=v.verify(pdf,assertion)
                self.assertTrue(ok,evidence)
                self.assertEqual(evidence['sizes_pt'],[15])
                self.assertAlmostEqual(evidence['tracking_units'],30,delta=1)
                self.assertFalse(v.verify(pdf,{**assertion,'size_pt':1})[0])
                self.assertFalse(v.verify(pdf,{**assertion,'tracking':450})[0])
                self.assertFalse(v.verify(pdf,{**assertion,'leading_pt':20})[0])

    def test_metrics_negative_tracking_and_later_measurable_occurrence(self):
        pdf=self._text_operator_pdf('negative.pdf',b'BT /F1 48 Tf -0.48 Tc 1 0 0 1 20 250 Tm (THE BLUE HOUR) Tj ET')
        self.assertTrue(v.verify(pdf,{'op':'pdf_text_style','text':'THE BLUE HOUR','family':'Helvetica','size_pt':48,'tracking':-10})[0])
        pdf=self._text_operator_pdf('occurrences.pdf',b'BT /F1 15 Tf 30 TL 20 400 Td (Design lead) Tj 0 -100 Td (Design) Tj T* (lead) Tj ET')
        ok,evidence=v.verify(pdf,{'op':'pdf_text_style','text':'Design lead','family':'Helvetica','leading_pt':30})
        self.assertTrue(ok,evidence)

    def test_fonts_embedded(self):
        self.assertTrue(v.verify(self.pdf,{'op':'pdf_fonts_embedded'})[0])
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter();page=writer.add_blank_page(200,200)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 10 Td (Hi) Tj ET');page[NameObject('/Contents')]=writer._add_object(stream)
        bare=self.root/'bare.pdf'
        with open(bare,'wb') as handle:writer.write(handle)
        ok,evidence=v.verify(bare,{'op':'pdf_fonts_embedded'})
        self.assertFalse(ok);self.assertEqual(evidence['not_embedded'],['Helvetica'])

    PSO_ICC=Path('/Users/dhiren/Documents/ChatGPT/Adobe_Gpt/reviews/pilot13-refresh-2026-10-14/print-profile/PSOcoated_v3.icc')

    def _with_intent(self, name, profile_bytes):
        from pypdf import PdfReader
        from pypdf.generic import ArrayObject,DictionaryObject,NameObject,TextStringObject,DecodedStreamObject,NumberObject
        writer=PdfWriter(clone_from=PdfReader(self.pdf))
        intent=DictionaryObject({NameObject('/Type'):NameObject('/OutputIntent'),NameObject('/S'):NameObject('/GTS_PDFX'),NameObject('/OutputConditionIdentifier'):TextStringObject('PSO Coated v3')})
        if profile_bytes is not None:
            icc=DecodedStreamObject();icc.set_data(profile_bytes);icc[NameObject('/N')]=NumberObject(4)
            intent[NameObject('/DestOutputProfile')]=writer._add_object(icc)
        writer._root_object[NameObject('/OutputIntents')]=ArrayObject([writer._add_object(intent)])
        path=self.root/name
        with open(path,'wb') as handle:writer.write(handle)
        return path

    def test_output_intent_needs_embedded_cmyk_profile(self):
        self.assertFalse(v.verify(self.pdf,{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
        label_only=self._with_intent('label.pdf',None)
        self.assertFalse(v.verify(label_only,{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
        from PIL import ImageCms
        srgb=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
        self.assertFalse(v.verify(self._with_intent('wrongprofile.pdf',srgb),{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
        if self.PSO_ICC.is_file():
            press=self._with_intent('press.pdf',self.PSO_ICC.read_bytes())
            self.assertTrue(v.verify(press,{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
            import hashlib
            digest=hashlib.sha256(self.PSO_ICC.read_bytes()).hexdigest()
            self.assertTrue(v.verify(press,{'op':'pdf_output_intent','contains':'PSO Coated v3','profile_sha256':digest})[0])
            self.assertFalse(v.verify(press,{'op':'pdf_output_intent','contains':'PSO Coated v3','profile_sha256':'0'*64})[0])
            self.assertFalse(v.verify(press,{'op':'pdf_no_cmyk'})[0])
        self.assertFalse(v.verify(label_only,{'op':'pdf_no_cmyk'})[0])

    def test_output_intent_rejects_fake_icc_and_wrong_cmyk_identity(self):
        fake=bytearray(132);fake[:4]=(132).to_bytes(4,'big');fake[16:20]=b'CMYK';fake[36:40]=b'acsp'
        ok,evidence=v.verify(self._with_intent('fake.pdf',bytes(fake)),{'op':'pdf_output_intent','contains':'PSO Coated v3'})
        self.assertFalse(ok,evidence)
        self.assertFalse(evidence['output_intents'][0]['profile_valid'])
        profile=Path('/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc')
        if not profile.exists():self.skipTest('System Generic CMYK fixture unavailable')
        wrong=self._with_intent('wrong-cmyk.pdf',profile.read_bytes())
        self.assertFalse(v.verify(wrong,{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
        self.assertTrue(v.verify(wrong,{'op':'pdf_output_intent','contains':'Generic CMYK Profile'})[0])

    def test_output_intent_rejects_bad_length_and_channel_count(self):
        if not self.PSO_ICC.exists():self.skipTest('PSO Coated v3 fixture unavailable')
        data=self.PSO_ICC.read_bytes()
        self.assertFalse(v.verify(self._with_intent('truncated.pdf',data[:-10]),{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
        from pypdf import PdfReader
        from pypdf.generic import NameObject, NumberObject
        writer=PdfWriter(clone_from=PdfReader(self._with_intent('channels.pdf',data)))
        writer._root_object['/OutputIntents'][0].get_object()['/DestOutputProfile'][NameObject('/N')]=NumberObject(3)
        target=self.root/'bad-channels.pdf'
        with target.open('wb') as handle:writer.write(handle)
        self.assertFalse(v.verify(target,{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])

    def test_no_cmyk_finds_cmyk_anywhere(self):
        self.assertTrue(v.verify(self.pdf,{'op':'pdf_no_cmyk'})[0])
        cmyk=self.root/'cmyk.pdf'
        Image.new('CMYK',(40,40),(0,80,80,0)).save(cmyk)
        ok,evidence=v.verify(cmyk,{'op':'pdf_no_cmyk'})
        self.assertFalse(ok);self.assertTrue(evidence['colour_spaces'])
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject,ArrayObject,NumberObject
        def form_pdf(name,inner,outer_name='/Fm1'):
            writer=PdfWriter();page=writer.add_blank_page(200,200)
            leaf=DecodedStreamObject();leaf.set_data(inner)
            leaf.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(200),NumberObject(200)]),NameObject('/Resources'):DictionaryObject()})
            outer=DecodedStreamObject();outer.set_data(b'q /Fm2 Do Q')
            outer.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/BBox'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(200),NumberObject(200)]),
                          NameObject('/Resources'):DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Fm2'):writer._add_object(leaf)})})})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject(outer_name):writer._add_object(outer)})})
            contents=DecodedStreamObject();contents.set_data(b'q /Fm1 Do Q');page[NameObject('/Contents')]=writer._add_object(contents)
            path=self.root/name
            with open(path,'wb') as handle:writer.write(handle)
            return path
        nested=form_pdf('nested.pdf',b'0 0.8 0.8 0 k 10 10 50 50 re f')
        ok,evidence=v.verify(nested,{'op':'pdf_no_cmyk'})
        self.assertFalse(ok);self.assertTrue(any('form' in o for o in evidence['operators']))
        rgb=form_pdf('nested_rgb.pdf',b'0.2 0.4 0.6 rg 10 10 50 50 re f')
        self.assertTrue(v.verify(rgb,{'op':'pdf_no_cmyk'})[0])
        inline=form_pdf('inline.pdf',b'q 10 0 0 10 0 0 cm BI /W 1 /H 1 /CS /CMYK /BPC 8 ID \x00\x80\x80\x00 EI Q')
        self.assertFalse(v.verify(inline,{'op':'pdf_no_cmyk'})[0])

    def test_icc_profile(self):
        from PIL import ImageCms
        tagged=self.root/'tagged.png'
        Image.new('RGB',(8,8),'white').save(tagged,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes())
        self.assertTrue(v.verify(tagged,{'op':'icc_profile','expects':'sRGB'})[0])
        plain=self.root/'plain.png';Image.new('RGB',(8,8),'white').save(plain)
        self.assertTrue(v.verify(plain,{'op':'icc_profile','expects':'sRGB'})[0])
        self.assertFalse(v.verify(plain,{'op':'icc_profile','expects':'sRGB','allow_untagged':False})[0])
        lab=self.root/'lab.png'
        Image.new('RGB',(8,8),'white').save(lab,icc_profile=ImageCms.ImageCmsProfile(ImageCms.createProfile('LAB')).tobytes())
        self.assertFalse(v.verify(lab,{'op':'icc_profile','expects':'sRGB'})[0])
        cmyk=self.root/'cmyk.jpg';Image.new('CMYK',(8,8)).save(cmyk)
        self.assertFalse(v.verify(cmyk,{'op':'icc_profile','expects':'sRGB'})[0])


if __name__=='__main__':unittest.main(verbosity=2)
