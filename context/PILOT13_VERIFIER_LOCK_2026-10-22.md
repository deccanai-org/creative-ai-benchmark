# Pilot 13 verifier follow-up

Scope: the verifier findings in the latest audit. No new benchmark execution, regenerated assets, historical output repairs, or changes to the other 87 task specifications.

## Changes

- PHOTO-06: replaced 27 relative "nearer" colour decisions with a bounded RGB match.
- PHOTO-19: replaced 19 subjective neutral-background decisions with an explicit range between Fog Grey and Warm Paper, including a three-sample measurement procedure. The brand instructions now state the same range.
- PHOTO-28: reconciled the supplied wordmark's original ink with the palette rules, typography reference and coverage. Original #222724 ink is explicitly permitted only for that supplied wordmark on the specified grounds. Recolouring restrictions remain in force for other graphics.
- Split 99 compound checks into 234 single-requirement checks, adding 135 checks. Existing IDs retain the first requirement; new IDs identify the remaining requirements and record `split_from`. The conditional PHOTO-20 portrait case remains conditional.
- Added the missing mappings for 80 human checks and 681 automatic checks. Every current check is now represented in coverage against its own output.
- Converted all 103 Estimate checks: six chart values are read from exact labels, and 97 area checks now have measurement procedures. LAYOUT-12's requested deck explicitly requires the numeric labels; its output register, brief HTML and coverage agree.
- Coverage now separates Auto, Human and unscored design targets. A check supporting several rules appears only once in each deliverable's checklist.
- All 1,190 unverifiable rule/output targets are explicitly excluded from the score denominator, not counted as covered and not treated as passes or failures. They remain design instructions. A missing measurement for a scored check is unanswered, not a guessed Yes/No.
- Removed the unsupported ten-seconds-per-check timing estimate. Timing must be calibrated with reviewers.
- Added a browser-local measurement guide, a neutral-range calculator and a masked-area calculator. These do not upload files. Area masks require reviewer validation; this is measurement assistance, not an automated design judgement.

## Current inventory

- 13 tasks, 143 deliverables.
- 6,312 human checks: 4,784 Look and 1,528 Measure. No Estimate checks remain.
- 1,111 automatic checks, unchanged by this follow-up.
- 6,791 rule/output cells with checks; 4,520 not applicable; 1,190 not scored; no empty coverage cells.
- All existing benchmark runs and their results remain historical and unchanged. Nothing here constitutes rerating the outputs.

## Synchronisation

The canonical task specifications, per-task verifier JSON/Markdown, V7 task aggregates, review site, 13 brief HTMLs, coverage pages, verifier bank and round-four Sheet export are rebuilt together.

Live Google Sheet: `Gatsby Sample Inventory`, tab `Verifiers_sample_inventory` (sheet ID 775360614). The prior tab was copied to hidden `Verifiers_before_lock_2026-10-22` (sheet ID 639085228) before editing. The current table has 157 rows including its header and 26 columns. Only C, M:N and T:Z were changed; unrelated cells and formatting were preserved. All 4,082 cells were read back and compared, including unchanged columns. Four appended fields carry scoring policy, coverage URL, unscored-target count and measurement-guide URL. Raw JSON and URLs intentionally retain the import table's clipped cell presentation.

The Sheet update does not reload assignments in the separate annotation platform. Its importer must consume the current rows and honour the scoring-policy fields before the next rating round. No claim is made that existing assignments have refreshed.

Export: `tools/pilot13_ab_fixes/round4/sheet_rows_2026-10-22.json` and matching CSV. Previous round exports are preserved.

## Rebuild

```sh
python3 scripts/repair_pilot13_review.py
python3 scripts/finalize_pilot13_verifiers.py
python3 scripts/sync_v7_pilot_content.py
python3 tools/pilot13_ab_fixes/build_coverage_pages.py
python3 scripts/build_v7_annotation_pilot.py
python3 scripts/sync_v7_pilot_content.py --check
```

## Verification

64 automated regression tests pass: 28 automatic-checker tests, 27 Python pilot/synchronisation/follow-up tests, eight measurement-function tests and one historical attachment test. Browser checks cover all 13 coverage pages, the main Human tab, desktop/mobile guide layout and calculator interactions. The follow-up tests cover complete check mapping, scoring exclusions, compound splits, wordmark consistency, export completeness, idempotence and preservation of the other 87 tasks.

Passing these tests establishes structural consistency and the tested decision rules. It does not prove that all creative judgements are objective or that the full checklist can be rated quickly. Reviewer calibration remains necessary, particularly for the 1,528 Measure checks.
