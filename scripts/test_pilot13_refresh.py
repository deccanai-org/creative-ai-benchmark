"""Input-pack regression checks; these do not grade benchmark execution outputs."""
import json
import re
import subprocess
import unittest
from pathlib import Path

from build_v7_annotation_pilot import ROOT, TASKS, TASK_IDS, OUT, SHEET_EXPORT
from prepare_pilot13_assets import WORK


class RefreshTests(unittest.TestCase):
    def test_contracts_and_references(self):
        for tid in TASK_IDS:
            with self.subTest(task=tid):
                t=json.loads((TASKS/tid/'TASK_SPEC.json').read_text())
                urls={a['filename']:a['public_url'] for a in t['assets']}
                self.assertEqual(len(urls),len(t['assets']))
                outputs={o['output_id']:o for o in t['deliverables']}
                for o in outputs.values():
                    self.assertTrue(all(o['commission'].get(k) for k in ['purpose','channel','audience','content','export_settings']))
                checks=t['verifiers_auto']+t['verifiers_human']
                self.assertEqual(len(checks),len({c['check_id'] for c in checks}))
                for c in checks:
                    self.assertIn(c['output_id'],outputs)
                    self.assertEqual(re.split(r', (?:source|page) ',c['output_reference'])[0],outputs[c['output_id']]['path'])
                    self.assertEqual(c['allowed_answers'],['Yes','No'])
                    self.assertEqual(c['status'],'not_assessed')
                    self.assertIsNone(c['answer'])
                    for ref in c.get('reference_assets',[]):
                        if ref.get('filename') in urls: self.assertEqual(ref['url'],urls[ref['filename']])
                self.assertEqual(t['deliverables'],json.loads((TASKS/tid/'OUTPUT_REGISTER.json').read_text()))
                self.assertEqual(t['assets'],json.loads((TASKS/tid/'ASSET_MANIFEST.json').read_text()))
                families={f['family'] for f in t['brand_identity']['font_files']}
                for row in t['brand_identity']['type_system']['scale']:
                    self.assertIn(row['font_family'],families)
                    fonts=[f for f in t['brand_identity']['font_files'] if f['family']==row['font_family']]
                    self.assertTrue(any(f['weight_range'][0]<=row['font_weight']<=f['weight_range'][-1] for f in fonts))
                self.assertNotRegex(json.dumps(t['brand_identity']),r'Canela|Financier|Freight|GT Super|Suisse|Neue Haas|Boska|Druk|Publico|Graphik|Monument Extended|Basis Grotesque|Miller Text|Cirka|Brandon Text|Univers')

    def test_original_runs_and_other_tasks_preserved(self):
        changed=subprocess.check_output(['git','diff','--name-only'],cwd=ROOT,text=True).splitlines()
        self.assertFalse(any('/runs/' in p for p in changed))
        old=json.loads(subprocess.check_output(['git','show','HEAD:docs/gatsby-v7/TASKS_V5_ALL100.json'],cwd=ROOT))
        now=json.loads((ROOT/'docs/gatsby-v7/TASKS_V5_ALL100.json').read_text())
        self.assertEqual(len(now),100)
        self.assertEqual([t for t in old if t['new_id'] not in TASK_IDS],[t for t in now if t['new_id'] not in TASK_IDS])

    def test_evaluation_scope(self):
        rows=json.loads(SHEET_EXPORT.read_text())
        self.assertEqual(len(rows),14)
        for row in rows[1:]:
            self.assertTrue(all(len(str(v))<49000 for v in row))
            rubrics=json.loads(row[1])
            decision=next(r for r in rubrics if r['side_headers'].startswith('7.'))
            self.assertEqual([r['asset_options'][0]['label'] for r in decision['AssestRepeater']],['Brief','Brand identity'])
            self.assertTrue(any('Typography:' in r['asset_options'][0]['label'] for r in rubrics[1]['AssestRepeater']))


if __name__=='__main__': unittest.main()
