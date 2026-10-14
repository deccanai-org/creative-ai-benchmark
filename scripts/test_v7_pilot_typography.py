#!/usr/bin/env python3
"""Check typography coverage, source parity and the unchanged pilot scope."""

import json
import re
import unittest
from pathlib import Path

from build_v7_annotation_pilot import TASKS, TASK_IDS, OUT, SHEET_EXPORT, platform_verifiers
from fix_v7_pilot_typography import REVISION, roles_for


class TypographyTests(unittest.TestCase):
    def test_instructions_and_role_coverage(self):
        for tid in TASK_IDS[:10]:
            with self.subTest(task=tid):
                spec = json.loads((TASKS / tid / "TASK_SPEC.json").read_text())
                ts = spec["brand_identity"]["type_system"]
                text = json.dumps(ts)
                self.assertNotRegex(text, r"(?i)invented|size not stated|leading not stated")
                self.assertIn("thousandths of an em", ts["measurement_notes"])
                self.assertIn("supplied logo", ts["application"])
                self.assertEqual(spec["brand_identity"]["signature_type_move"], ts["signature_move"])
                checks = spec["verifiers_auto"] + spec["verifiers_human"]
                self.assertEqual(len(checks), len({c["check_id"] for c in checks}))
                by_output = {}
                for c in checks:
                    by_output.setdefault(c["output_id"], []).append(c)
                for output in spec["deliverables"]:
                    cs = by_output[output["output_id"]]
                    filename = Path(output["path"]).name
                    actual = {c.get("typography_key") for c in cs}
                    for role in roles_for(tid, output):
                        for prop, value in role.items():
                            if prop != "role" and value is not None:
                                self.assertIn(f'{role["role"]}:{prop}', actual)
                    for c in cs:
                        if c.get("typography_key"):
                            self.assertTrue(c["check"].startswith(filename + ":"))
                            self.assertEqual(c["status"], "not_assessed")
                            self.assertIsNone(c["answer"])
                            self.assertEqual(c["origin"], REVISION)
                    if output["output_id"].startswith("restoration-"):
                        self.assertFalse(any(c.get("typography_key") for c in cs))
                    if output["output_id"].endswith("-combined"):
                        self.assertTrue(any("individual" in c["check"].lower() or "identical" in c["check"].lower() for c in cs))

    def test_all_published_specifications_match(self):
        for tid in TASK_IDS:
            spec = json.loads((TASKS / tid / "TASK_SPEC.json").read_text())
            canonical = {c["check_id"]: c for c in spec["verifiers_auto"] + spec["verifiers_human"]}
            mirror = json.loads((TASKS / tid / "VERIFIERS.json").read_text())
            self.assertEqual(canonical, {c["check_id"]: c for c in mirror})
            bank = json.loads((OUT / "verifier-bank" / f"{tid}.json").read_text())
            self.assertEqual(len(bank), len(canonical))
            for c in bank:
                self.assertEqual(c["check"], canonical[c["check_id"]]["check"])
            page = (OUT / f"{tid}.html").read_text()
            self.assertIn("The samples load the supplied font files", page)
            self.assertIn("https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5", page)

    def test_sheet_export_and_priorities(self):
        rows = json.loads(SHEET_EXPORT.read_text())
        self.assertEqual(len(rows), 14)
        for tid, row in zip(TASK_IDS, rows[1:]):
            spec = json.loads((TASKS / tid / "TASK_SPEC.json").read_text())
            checks = json.loads((TASKS / tid / "VERIFIERS.json").read_text())
            selected = platform_verifiers(checks, spec["deliverables"])
            self.assertEqual(json.loads(row[2]), selected)
            self.assertLess(len(row[2]), 49000)
            self.assertEqual(row[13], len(checks))
            for c in checks:
                if c.get("platform_priority"):
                    self.assertTrue(any(c["check"] in p["verifier_question"] for p in selected))


if __name__ == "__main__":
    unittest.main()
