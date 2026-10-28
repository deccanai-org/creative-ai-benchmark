# Pilot-13 v2: moving objective human checks to automatic checks

Plan agreed with Dhiren on 2026-10-27. Only checks whose answer is a fact code can read exactly from the delivered
file move; nothing needing judgement does. Code never passes a check it cannot read or find: that row stays with a
person. Converted checks keep their check IDs, K question and critical flag.

## Steps

1. **List** (done 2026-10-27): every v2 rule sorted. `automation_plan_step1.html` (review page),
   `automation_plan_step1.csv` and `.json` (one row per rule with its check IDs). Built by `plan_step1.py`
   (patterns plus per-rule overrides from reading every rule) and `build_review.py`.
2. **Tools** (installed 2026-10-27): Tesseract 5.5.3 (Homebrew, `eng`), opencv-python-headless 5.0.0.93 and
   PyMuPDF 2.0 (MuPDF 1.28.5) in `~/Documents/ChatGPT/Adobe_Gpt/benchmark_v4/.venv`, cairosvg (Homebrew Cairo).
3. **Operations** (done 2026-10-27): `tools/auto_verifier/objective_ops.py`, with pass, fail and person fixtures in
   `tools/auto_verifier/test_objective_ops.py` (13 tests, all drawn in code, no binary fixtures).
4. **Convert and test** (done 2026-10-27): `convert.py` turns each automatic rule into one assertion per check
   (`moved/<TASK>.json`; rules it cannot convert exactly are listed in `not_converted.json`). `run_checks.py` runs
   them on a folder of deliverables. Tested on the 102 deliverables of the 2026-09-28 run (10 tasks) and on made
   files for LAYOUT-12, VECTOR-04 and MOTION-11 (`make_layout12_files.py`, `make_vector_motion_files.py`): a
   correct set and a set with one planted defect per file. Every fail was checked by hand.
5. **Decide** (done 2026-10-27): `decide_moves.py` writes `moved_rules.json`. A converted rule moves when testing
   gave no wrong answer and the code decided at least half of its test rows itself; otherwise it stays with people.
6. **Move in v2** (done 2026-10-27): `scripts/build_v7_annotation_pilot_v2.py` reads `moved_rules.json`. Moved
   rules stay under their K question, marked Code, with how the code checks them; `answered_by` is in the rule JSON
   and both CSVs. `build_results_page.py` writes `docs/gatsby-v7/annotation-pilot-v2/automation.html`.
7. Only with approval: move them in TASK_SPEC.json, the V7 site, coverage and the Sheet, all copies together, and
   dispatch the `v2_*` operations from `tools/auto_verifier/verify_outputs.py` (a person answer maps to
   `pending_expert_review`).

## Round 2 (2026-10-28)

Round 1 converted 913 of the 1,385 automatic checks. Round 2 builds the other 472 (140 rules), each with a handler of
its own in `round2.py`, keyed by task and rule so round-1 conversions never change (`convert.py` reports any
difference). Their operations are in `tools/auto_verifier/objective_ops_r2.py`, with fixtures in
`tools/auto_verifier/test_objective_ops_r2.py`: which value belongs to which name (a rate to its house and season, a
date to its act), the colour behind type, mark size and position against the photo, page and artwork size, letter
spacing, figure style, which supplied photo is shown and which capture a thumbnail comes from. The made-file
generators also write a second broken set (`bad2`, one round-2 defect per file, listed in `PLANTED2` of
`decide_moves.py`). The same decision rule applies: a rule moves when testing gave no wrong answer and the code
decided at least half of its rows.

Result: 124 of the 140 rules (418 checks) moved; 16 rules (54 checks) stay with people because the code mostly
answered "person" on the test files (OCR read too unclearly to rule text out, a mark absent so not provable, plate
labels a person must judge as accession codes or not). One round-1 rule (LAYOUT-12 R060, "&nbsp;") also moved once a
matching fix let it decide. In all: 1,167 checks (299 rules) run as code; 218 checks (50 rules) have code but stay
with people. Tests: the 2026-09-28 outputs (1,002 rows: 751 pass, 224 person, 27 fail, every fail a confirmed defect
listed in `KNOWN_TRUE_FAILS`) and the made files (correct set: 374 pass, 9 person, 0 fail; both broken sets: every
planted defect failed or sent to a person, none passed, and nothing else failed).

## Outcomes and safety rules

Every operation answers `pass`, `fail` or `person` (the code could not decide, so a person answers that row).

- Nothing passes on a failed read. OCR absence checks need every line that could carry wording read at 80
  confidence or more.
- A near miss (similarity 0.8 or more) may be a misreading, so it goes to a person, never to a fail.
- A difference only in letter case goes to a person, unless the check is about letter case.
- A supplied photo or logo counts as found only when its matched area also correlates with the file (0.8 or more);
  flat logos are matched as templates at their own proportions (0.93 or more).
- Text size on images is the height of capitals and tall letters; a line with none has no measurable size.
- Images are read by OCR at 2x, 1x and 0.5x; for each area the reading recovering most letters is kept.
- SVG colours are checked as declared and as rendered; SVG text is read live and by OCR of the render.

## Rerun

From this folder:

```
PY=~/Documents/ChatGPT/Adobe_Gpt/benchmark_v4/.venv/bin/python
python3 convert.py
$PY -W ignore ../auto_verifier/test_objective_ops.py
$PY -W ignore run_checks.py --out real.json                         # 2026-09-28 outputs
$PY -W ignore ../auto_verifier/test_objective_ops_r2.py
$PY -W ignore make_layout12_files.py <made> && $PY -W ignore make_vector_motion_files.py <made>
$PY -W ignore run_checks.py --run <made>/good --tasks LAYOUT-12 VECTOR-04 MOTION-11 --out good.json
$PY -W ignore run_checks.py --run <made>/bad --tasks LAYOUT-12 VECTOR-04 MOTION-11 --out bad.json
$PY -W ignore run_checks.py --run <made>/bad2 --tasks LAYOUT-12 VECTOR-04 MOTION-11 --out bad2.json
python3 decide_moves.py real.json good.json bad.json bad2.json
python3 ../../scripts/build_v7_annotation_pilot_v2.py && $PY build_results_page.py
```

## Step 1 result

| Decision | Rules | Checks |
|---|---:|---:|
| Code answers it | 349 | 1,385 |
| Needs a definition first | 100 | 271 |
| Colour sampled on an image (later) | 214 | 1,319 |
| Stays with people | 837 | 3,337 |
| **Total** | **1,500** | **6,312** |

Automatic by method: OCR 152 rules / 738 checks, read from the file 141 / 386, image matching 43 / 203,
file plus matching 8 / 37, OCR plus matching 5 / 21.

Rerun: `python3 plan_step1.py <repo root> automation_plan_step1.json` then
`python3 build_review.py <repo root> automation_plan_step1.json automation_plan_step1.html`.
