# Pilot-13 round 2 (2026-10-22): honest coverage, atomic checks, measured vs visual

An external review of round 1 found three things this round fixes. Read `GUIDE_AB.md` first: every rule there still
holds (one fact, at most 40 words, names the output as “Name” (file.ext), no em or en dashes, valid k_id, never weaken a
planned trap or K1_Q5 check, never invent a requirement, never edit auto checks).

1. **Coverage overstated.** A rule counted as covered if any linked check existed, even when the rule bundled several
   requirements (font + 34 pt + 38 pt leading + 30 tracking) and the checks tested only some of them.
2. **Bundled checks.** Some checks still list several independent facts (five acts' dates in one check).
3. **Measured checks looked like visual checks.** "34 px wordmark", cap-height ranges and "about 5% of the area" need a
   ruler or an estimate, and annotators were not told.

Decisions taken by the project owner:
- Exact type values: **check by code where possible** (PDF outputs with live text); otherwise keep the brand value as a
  design target and mark it **not verified** in the coverage table with the reason. Never claim coverage you do not have.
- Every human check is labelled **look** (judge by eye), **measure** (needs a ruler or tool) or **estimate** (an approximate
  visual share). Measured and estimated checks say how.

## Paths
- Base spec (READ ONLY, what is published now): `/Users/dhiren/Documents/ChatGPT/Adobe_Gpt/reviews/pilot13-c-fixes-2026-10-22/base/<ID>/TASK_SPEC.json`
- Base coverage (READ ONLY): `.../pilot13-c-fixes-2026-10-22/base/<ID>/coverage.json`
- WRITE ONLY: `.../pilot13-c-fixes-2026-10-22/patches/<ID>.json` (patch against the base spec) and
  `.../pilot13-c-fixes-2026-10-22/coverage/<ID>.json` (the complete new coverage table), scratch in `work/<ID>/`.
- Tools (always set the work folder): `export PILOT_FIX_WORK=/Users/dhiren/Documents/ChatGPT/Adobe_Gpt/reviews/pilot13-c-fixes-2026-10-22`
  then `python3 <repo>/tools/pilot13_ab_fixes/validate_patch.py <ID>` and `python3 <repo>/tools/pilot13_ab_fixes/show_patched.py <ID> --retired --coverage`.
- Inputs, asset plans and trap notes: as in GUIDE_AB.md.

## What to do
1. **Split every coverage rule into single requirements.**
   - Type rules: one rule per property per role: font (family and weight), size, leading, tracking; case, position or
     other type rules separately. The validator rejects a type rule that names more than one of font, size, leading, tracking.
   - Brand rules: if a rule holds several separate requirements (grounds; type colours; accent limits; ...), make each one
     its own rule.
   - Deliverable rules keep the exact text of each `commission.content` bullet (the validator matches it). If a bullet
     bundles several facts, its cell lists every check needed to cover all of them.
2. **Fill every cell honestly.** `checks` must really test that requirement on that file. `na` = it does not apply to that
   file (say why). `not_verified` = it applies, but no check verifies it; say why (for example "Exact leading cannot be
   measured in a delivered PNG; the brand value is a design target"). Only type and brand rules may be `not_verified`.
   Do not use `not_verified` where a check is reasonable: add the check instead.
3. **Code where possible.** For PDF outputs with live text (not LAYOUT-15 or VECTOR-04, which may outline lettering), add
   `pdf_text_style` auto checks for the size, leading and tracking the type scale states for that placement, where you
   know an exact text string in that role on that output (a record value, a fixed line in the brief or a supplied copy
   file). The runner now supports:
   `{"op":"pdf_text_style","text":"...","family":"...","weight":"...","size_pt":10,"leading_pt":15,"tracking":0}`
   (tracking in thousandths of an em; leading = baseline to baseline in pt and needs text that runs over two or more
   lines, so add `leading_pt` only for text you know wraps, such as a paragraph; any occurrence counts; case-insensitive).
   You may add separate auto checks per property. The check text names the output file and the values.
4. **Split bundled human checks.** One check per item when a check lists several independent values (dates, prices,
   times, names with their own facts). The validator rejects three or more dates, prices or times in one check unless
   it states an order or sequence.
5. **Label methods.** In `modify` or `add`, set `"method": "measure"` or `"estimate"` with `"how"` (at most 25 words,
   plain, what to measure and with what), for example:
   - measure: "In an image editor at 100% zoom, measure the height of the wordmark's capital letters in pixels."
   - estimate: "Estimate the share of the designed, non-photographic area in the accent colours; answer No only if it is clearly over 5%."
   A `modify` item may carry only `method`/`how` (no text change). Everything else defaults to `look`. Use measure or
   estimate only where the brief's requirement truly needs it; a person judging by eye must never be asked for an exact number.
6. Keep coverage complete (no missing cells), keep volume sensible (no duplicates), and run the validator to 0 errors.

## Patch schema
As in GUIDE_AB.md, plus `method` and `how` on `modify` and `add`. Your patch is against the round-2 base spec.
Your coverage file is the complete new table (start from the base coverage and edit it). Every item needs a short `why`.
