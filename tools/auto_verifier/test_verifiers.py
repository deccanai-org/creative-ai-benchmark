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

    def test_text_style_missing_text_is_not_a_pass_or_fail(self):
        with self.assertRaises(v.VerifierUnavailable):
            v.verify(self.pdf,{'op':'pdf_text_style','text':'Priya Nandakumar','family':'Helvetica'})

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

    def test_output_intent_and_cmyk(self):
        self.assertFalse(v.verify(self.pdf,{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
        self.assertTrue(v.verify(self.pdf,{'op':'pdf_no_cmyk'})[0])
        from pypdf import PdfReader
        from pypdf.generic import ArrayObject,DictionaryObject,NameObject,TextStringObject
        writer=PdfWriter(clone_from=PdfReader(self.pdf))
        intent=DictionaryObject({NameObject('/Type'):NameObject('/OutputIntent'),NameObject('/S'):NameObject('/GTS_PDFX'),NameObject('/OutputConditionIdentifier'):TextStringObject('PSO Coated v3')})
        writer._root_object[NameObject('/OutputIntents')]=ArrayObject([writer._add_object(intent)])
        press=self.root/'press.pdf'
        with open(press,'wb') as handle:writer.write(handle)
        self.assertTrue(v.verify(press,{'op':'pdf_output_intent','contains':'PSO Coated v3'})[0])
        self.assertFalse(v.verify(press,{'op':'pdf_no_cmyk'})[0])
        cmyk=self.root/'cmyk.pdf'
        Image.new('CMYK',(40,40),(0,80,80,0)).save(cmyk)
        ok,evidence=v.verify(cmyk,{'op':'pdf_no_cmyk'})
        self.assertFalse(ok);self.assertTrue(evidence['colour_spaces'])

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
