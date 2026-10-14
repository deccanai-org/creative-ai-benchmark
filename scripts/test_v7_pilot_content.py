#!/usr/bin/env python3
"""Check canonical copy, pilot embeds, file lists and annotation-only boundaries."""

import json
import unittest
from html.parser import HTMLParser

from build_v7_annotation_pilot import OUT, TASKS, TASK_IDS, output_spec_text
from sync_v7_pilot_content import sync


class PilotPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.brief = ""
        self.about = ""
        self.active = None
        self.sections = []
        self.scripts = []
        self.assets = []
        self.outputs = 0
        self.images = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if "brief-text" in classes:
            self.active = "brief"
        elif "brand-about" in classes:
            self.active = "about"
        if tag == "section":
            self.sections.append(attrs.get("aria-labelledby"))
        if tag == "script" and "src" in attrs:
            self.scripts.append(attrs["src"])
        if "asset-preview" in classes:
            self.assets.append(attrs)
        if "output-row" in classes:
            self.outputs += 1
        if tag == "img":
            self.images.append(attrs["src"])

    def handle_endtag(self, tag):
        if self.active == "brief" and tag == "div" or self.active == "about" and tag == "p":
            self.active = None

    def handle_data(self, text):
        if self.active:
            setattr(self, self.active, getattr(self, self.active) + text)


class PilotContentTests(unittest.TestCase):
    def test_mirrors_are_current(self):
        sync(check=True)

    def test_pilot_pages(self):
        totals = [0, 0]
        expected_counts = [4, 18, 7, 12, 19, 16, 7, 2, 3, 14, 13, 19, 9]
        for task_id, output_count in zip(TASK_IDS, expected_counts):
            with self.subTest(task=task_id):
                spec = json.loads((TASKS / task_id / "TASK_SPEC.json").read_text())
                assets = json.loads((TASKS / task_id / "ASSET_MANIFEST.json").read_text())
                outputs = json.loads((TASKS / task_id / "OUTPUT_REGISTER.json").read_text())
                html = (OUT / f"{task_id}.html").read_text()
                page = PilotPage()
                page.feed(html)
                self.assertEqual(page.brief, spec["client_brief"])
                self.assertEqual(page.about, spec["brand_identity"]["about"])
                self.assertEqual(page.sections, ["brief-title", "brand-title", "assets-title", "outputs-title"])
                self.assertEqual(page.outputs, output_count)
                self.assertEqual(page.scripts, ["https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5"])
                self.assertEqual(len(page.assets),len(assets))
                self.assertEqual([a["href"] for a in page.assets if 'href' in a], [a["public_url"] for a in assets if not a['filename'].endswith(('.mp4','.mov','.webm','.wav','.mp3','.m4a'))])
                self.assertTrue(all(a["target"] == "_blank" for a in page.assets if 'href' in a))
                for image in page.images:
                    if not image.startswith("https://"):
                        self.assertTrue((OUT / image).is_file(), image)
                for output in outputs:
                    self.assertIn(output["path"].split("/")[-1], html)
                    self.assertTrue(output_spec_text(output["spec"]))
                for forbidden in ("Production constraints", "Source of truth", "benchmark series",
                                  "canonical client", "record bindings", "named exports",
                                  "Source dimensions: True", "output-requirements\"><ul"):
                    self.assertNotIn(forbidden, html)
                totals[0] += len(assets)
                totals[1] += page.outputs
        self.assertEqual(totals, [288, 143])

    def test_file_count_clarifications(self):
        expected = {
            "PHOTO-19": "fourteen speaker cards and four host cards",
            "PHOTO-20": "eight individual talk-card PDFs and one combined eight-page PDF",
            "LAYOUT-15": "thirteen individual producer-card PDFs and one combined thirteen-page PDF",
            "PHOTO-04": "lowest 2027 nightly rate from rates_2027.csv",
            "PHOTO-10": 'line labelled "Tall post" in northgrove_copy.txt',
            "PHOTO-06": "where the family notes correct the catalogue, follow the notes",
        }
        for task_id, text in expected.items():
            spec = json.loads((TASKS / task_id / "TASK_SPEC.json").read_text())
            self.assertIn(text, spec["client_brief"])


if __name__ == "__main__":
    unittest.main()
