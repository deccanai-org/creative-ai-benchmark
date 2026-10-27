# Pilot-13 v2: grouped human verifiers (2026-10-27)

Live: https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot-v2/

## Why

Annotators and Ops said the human verifiers were too many to read. Teammates proposed grouping (a sheet
`New Verifers.xlsx` covering PHOTO-19 and PHOTO-04, with 10 grouping rules). Their mapping was complete, but merging
by hand changed meaning in places: "must have" checks merged with "if it appears" checks (a card without the CFS mark
would pass), cards lost the link to their person, critical traps (PHOTO-04 Scogliera sleeps 10; Casa Fienile) were
merged with ordinary checks, and method notes (tolerances) were dropped. v2 does the grouping so that none of that
can happen.

## What changed

Only how human checks are shown. `TASK_SPEC.json`, the v1 pilot folder, the auto checks, the coverage tables and the
live Google Sheet are unchanged.

- A **rule** is one sentence template. Each **row** is one original human check, with its own check ID and its own
  Yes / No answer. The row's deliverable and values fill the template back to the check's exact wording.
- What may differ between rows: the deliverable reference, and value tokens (quoted text, hex codes, file names,
  numbers, names from the deliverables' source records and capitalised names mid-sentence, such as people, houses,
  acts and seasons).
- What must match for checks to share a rule: all other wording, the checking method, the method-note wording, the
  scoring dimension (`k_id`) and the answer fields. Consequences:
  - required and "if it appears" checks never share a rule (their wording differs);
  - critical-failure checks (K1_Q5) never share a rule with other dimensions;
  - Look and Measure never mix, and measurements with different instructions stay apart.
- Capitalised logic words ("If", "No", "Only", "Every" and so on) are never values, so a condition or negation is
  always in the rule text, never hidden in a row.
- If one varying value decides all the others (MOTION-11: text colour by ground colour), the rule is split so each
  part reads as a plain sentence.
- Verifier pages use the V7 Human verifiers layout: K1 · Instruction adherence, K2 · Asset utilization and fidelity,
  K5 · Communication effectiveness, each K question with its label, question text and rules, or the V7 note when
  automatic checks answer it (same AUTO2K mapping as the V7 page; the K catalog is read from `docs/gatsby-v7/index.html`).
  Inside K2 Q3 · Brand-system compliance, rules are split by what they name: a palette colour or hex, else a typeface
  or type setting, else other brand rules. Badges: K question, Look / Measure, Critical, Only if present.
- Each verifier page opens with "How to read a rule": three steps and two worked examples from that task (a rule, one
  of its rows, and the sentence they make).
- PHOTO-28 and VECTOR-04 have no K5 Q1 (primary-message recovery) human check in their specs; the page says so, as V7 does.
- Row layout (after Dhiren's review of PHOTO-06): every row shows its full sentence ("Reads as", on by default), a
  deliverable-type tag when a rule spans more than one deliverable group, and a **Source** column: a thumbnail of the
  supplied image the deliverable is made from (or that the row names) plus the row's own reference note, which is where
  catalogue captions such as "Ada with baby Ruth" live. Reference files and note sentences shared by every row are
  shown once under the rule. Every value column has a name (source-record field, approved field, file kind, the noun
  before it, or the value kind). Captions come only from the checks' own reference notes, never from raw data files,
  which can hold planted traps (PHOTO-04's sheet says sleeps 9).
- Thumbnails: `docs/gatsby-v7/annotation-pilot-v2/thumbs/<ID>/` (157 files, 1.5 MB, 192 px long edge, made with `sips`
  from the local asset copies the v1 builder reads; only images a page shows). The repo ignores images, so they are
  added with `git add -f`.

## Numbers

| Task | Human checks | Rules |
|---|---:|---:|
| PHOTO-04 | 233 | 122 |
| PHOTO-06 | 595 | 84 |
| PHOTO-08 | 517 | 162 |
| PHOTO-10 | 630 | 107 |
| PHOTO-19 | 885 | 114 |
| PHOTO-20 | 719 | 121 |
| PHOTO-24 | 355 | 116 |
| PHOTO-26 | 114 | 73 |
| PHOTO-28 | 227 | 106 |
| LAYOUT-15 | 593 | 60 |
| LAYOUT-12 | 784 | 178 |
| VECTOR-04 | 291 | 123 |
| MOTION-11 | 369 | 134 |
| **Total** | **6,312** | **1,500** |

Words to read (checks plus method notes): 256,258 before, 49,849 as rules (81% less). 616 rules hold a single check:
checks unique to one deliverable, or worded differently from their nearest sibling. The teammates' hand grouping had
63 rules for PHOTO-19 and 59 for PHOTO-04; v2 has more because it keeps the cases above apart.

## Files

- Builder: `scripts/build_v7_annotation_pilot_v2.py` (reuses the v1 brief renderer; reads only task files).
- Tests: `scripts/test_pilot13_v2_groups.py` (every check exactly once; every row rebuilds its check and method note
  exactly; one method, dimension and answer per rule; no logic words in values; published JSON equals a fresh build;
  pages and CSVs list every check once; each row's "Reads as" line equals its check; shared plus per-row references
  equal each check's full reference; every value column has a name; thumbnails exist and are supplied assets; K layout
  and AUTO2K match the V7 page; no em or en dashes in generated text).
- Output: `docs/gatsby-v7/annotation-pilot-v2/`: `index.html`, `<ID>.html` (brief, same as v1, previews read from
  `../annotation-pilot/previews/`), `<ID>-verifiers.html` (grouped rules, deliverable filter, search, toggle for each
  row's full original wording), `groups/<ID>.json`, `export/grouped_human_rules.csv`,
  `export/grouped_human_rule_rows.csv`.

## Rebuild order

After the existing pilot rebuild (`repair_pilot13_review.py`, `finalize_pilot13_verifiers.py`,
`sync_v7_pilot_content.py`, `tools/pilot13_ab_fixes/build_coverage_pages.py`, `build_v7_annotation_pilot.py`), run
`scripts/build_v7_annotation_pilot_v2.py`, then `python3 -m unittest test_pilot13_v2_groups` from `scripts/`.

## Open

- The platform / Sheet import still uses the v1 rows (one question per check per deliverable). A grouped import
  (rule shown once, every row passing by default, annotator ticks failures) needs Ops to agree the platform layout.
- Timing trial: same annotators, same outputs, v1 versus v2, to measure minutes saved and agreement.
