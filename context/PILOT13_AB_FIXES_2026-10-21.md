# Pilot-13 fixes A + B (2026-10-21)

Current follow-up and corrected claims: [2026-10-22 review fixes](PILOT13_REVIEW_FIXES_2026-10-22.md).
The rounds below are historical; use the round3 export named in that follow-up for current imports.

What was fixed after the audit of the 13 refreshed pilot tasks (original 10 + LAYOUT-12, VECTOR-04, MOTION-11)
against every stakeholder request: client (every constraint on every deliverable; verifier count manageable),
design call (simple, atomic, exact output reference), in-house creative expert (deliverable details, fonts, logos).

Live: https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot/ and the new coverage tables at
https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot/coverage/
Git tag before the change: `pilot13-before-AB-fixes-2026-10-21`.

## A. Visible errors
- **PHOTO-10 logo:** the four Northgrove mark files had lost the olive leaf and carried a traced fragment of the photo's
  dark edge. Root cause: `benchmark_v4/clean_adobe_vectors.py` kept only near-black trace shapes (RGB <= 100), so the
  olive leaf (rgb 114,114,65) was dropped and edge shadow kept. Rebuilt from the Adobe trace (leaf + 10 letters only),
  Olive #6B7248 leaf and Charcoal #2E2E2C wordmark, reversed wholly Off White #F5F2EC
  (`tools/pilot13_ab_fixes/rebuild_photo10_mark.py`). Uploaded to the same S3 keys (versioning keeps the old files);
  links carry `?v=<sha12>` because the objects are cached "immutable" for a year.
  NOTE: the same cleanup script produced 12 other marks in the corpus (LAYOUT-03, MOTION-01, PHOTO-07, PHOTO-08,
  PHOTO-15, PHOTO-28, LAYOUT-17, LAYOUT-19, MOTION-02, MOTION-03, MOTION-08, MOTION-09); any coloured element in those
  could have been dropped the same way. PHOTO-08's roundel was checked and is fine.
- **Coverage holes filled** (old first/last sampling), e.g. PHOTO-06 restoration masters and share images, LAYOUT-12
  release posts r003/r008/r009. Proof: a rule-by-deliverable table per task (`docs/gatsby-v7/annotation-pilot/coverage/`):
  4,517 cells checked, 1,766 not applicable (each with a reason), 0 missing.
- **Delivery-of-all checks removed:** LAYOUT-12 release-post-r002/H009, poster-direction-type-led/H003, MOTION-11
  thumbnail-we-broke-the-map/H004, LAYOUT-15 producer-card-combined/H001 (auto `file_exists`/`pages` cover them).
- **Leftover "If a named font is unavailable, ask us before substituting it."** removed (fonts are supplied).
  Duplicate "Export:" labels merged into one line per deliverable.

## B. Simpler, atomic, fewer unjudgeable checks
- **Machine facts moved to auto (161 checks):** sRGB colour (`icc_profile`), embedded fonts (`pdf_fonts_embedded`),
  screen PDF has no CMYK (`pdf_no_cmyk`), PSO Coated v3 output intent (`pdf_output_intent`).
- **Exact type measurements on images retired (1,351):** sizes, leading, tracking on PNG/JPG/MP4 cannot be judged by eye.
  Replaced where it matters by visible relative checks (largest text, smaller than body). On screen PDFs with live
  text, sizes became auto `pdf_text_style` checks (exact text, family, weight, size). Not on outline-allowed press PDFs
  (LAYOUT-15, VECTOR-04).
- **Duplicates merged (347)**, compound checks split, "(when present)" removed everywhere (0 left), checks over 30 words shortened.
- **Comparisons with "the other cards" (10 + templated families) rewritten** against a stated value or the output's own
  source file. Where the brand requires sameness across a run and no value exists, ONE fixed named reference is used:
  PHOTO-19 cards vs speaker-card-r005.png (head scale, ground tone); LAYOUT-12 posts vs release-post-r002.png (colour pair).
- **Auto vs human separated:** the V7 Human verifiers tab no longer embeds auto-check lists; the annotation sheet's
  verifier list no longer includes auto checks.
- Net per task (human before -> after): PHOTO-04 198->191, PHOTO-06 462->570, PHOTO-08 409->450, PHOTO-10 649->562,
  PHOTO-19 783->750, PHOTO-20 766->630, PHOTO-24 370->305, PHOTO-26 100->97, PHOTO-28 164->169, LAYOUT-15 585->492,
  LAYOUT-12 428->617, VECTOR-04 220->260, MOTION-11 283->338. Total 5,417 -> 5,431 human (5,581 before machine facts moved),
  755 -> 992 auto. The count is flat because removals (1,866) were offset by coverage fills and splits; every remaining
  human check is now judgeable by eye and every constraint is covered per deliverable.

## How it was done
`tools/pilot13_ab_fixes/`: `pre_edits.py` (deterministic A1/A3/A4/B5), `GUIDE_AB.md` (agent rules), `apply_patch.py`,
`validate_patch.py` (rule enforcement + coverage completeness), `show_patched.py`, `page_edits.py`,
`build_coverage_pages.py`, `patches/` (13 final patches), `reviews/` (reviewer findings, repair and final-check records).
52 + 15 agents: author -> two independent reviewers (fidelity, language) -> repair -> final verifier -> fix.
Frozen base specs for re-runs live outside the repo in `~/Documents/ChatGPT/Adobe_Gpt/reviews/pilot13-ab-fixes-2026-10-21/base/`.
Auto runner copy with new ops: `tools/auto_verifier/` (22 tests). Tests: `scripts/test_pilot13_ab.py` (new) plus updated
`test_v7_pilot_typography.py` and `test_v7_main_attachments.mjs`.

Rebuild order: `apply_patch.py --write <IDs>` -> `pre_edits.py` -> `scripts/sync_v7_pilot_content.py` -> `page_edits.py`
-> `build_coverage_pages.py` -> `scripts/build_v7_annotation_pilot.py` -> tests.

## Judgement calls to confirm with the team
- PHOTO-19 / LAYOUT-12 single-reference sameness checks (above). Alternative: drop the sameness rule.
- 5% accent-area caps (PHOTO-06/08/19) are estimates by eye.
- A few px rules that the brief fixes stay as "measure in an editor" checks (PHOTO-28 wordmark 34 px and safe area,
  MOTION-11 cap-height ranges guarding the title-length trap).
- Tracking/leading and some PNG-only type details (PHOTO-20, PHOTO-24 tabular spacing) are no longer checked at all.
- LAYOUT-15 now has no human K1_Q4 check (auto file checks answer it); the lapsed producer's exclusion is guarded on the
  combined run only.
- The annotation platform still shows only a sample of each output's human checks (first 2-4 + priority ones); the
  full bank and the coverage tables are linked. Re-import the sheet from `reviews/pilot13-refresh-2026-10-14/sheet_rows.json`.

## Round 2 (2026-10-22): response to the external review
An external (ChatGPT) review of round 1 found five gaps; all were verified and fixed.
1. **Repo moved to `deccanai-org`.** Old `dhigdec.github.io` links 404. Current release links, Sheet export, QA scripts,
   docs and the git remote now use `https://deccanai-org.github.io/creative-ai-benchmark/`. Frozen V4/V5/V6 folders untouched.
2. **Sheet sampled 807 of 5,431 checks.** The export is now 13 task rows (input-asset rubric) + 143 deliverable rows that
   carry EVERY human check (6,177; about 17 h at 10 s each), auto checks excluded. Import file:
   `tools/pilot13_ab_fixes/round2/sheet_rows_2026-10-22.json` (also `reviews/pilot13-refresh-2026-10-14/sheet_rows.json`).
   The live Google Sheet is NOT updated; the team must import it and decide how to assign the 143 deliverable rows.
3. **"0 missing" overstated coverage.** Rules are now split into single requirements (type: one property per role).
   Each cell is checked, n/a, or **not verified** with a reason (exact values that cannot be measured in a delivered
   image, designer-worded text that code cannot target). Totals: 6,029 checked, 3,090 n/a, 1,190 not verified, 0 missing.
   Decision (Dhiren): code where possible, otherwise design target marked not verified.
4. **Auto false passes fixed.** `pdf_no_cmyk` now follows nested Form XObjects, patterns, shadings, inline images,
   transparency groups and annotations; `pdf_output_intent` requires a /GTS_PDFX intent with an embedded valid CMYK ICC
   profile. New: `pdf_text_style` measures `leading_pt` and `tracking` (pdfminer.six). Regression tests: 24 pass.
5. **Atomic + measured vs visual.** Bundled checks split (e.g. LAYOUT-12 dates per act). Every human check carries
   `method` = look / measure / estimate (857 measure, 103 estimate) with a plain `method_note`; the Sheet shows
   "[Measure: ...]" / "[Estimate: ...]" before the question.
Totals after round 2: 6,177 human + 1,111 auto checks on the 13 tasks. Records: `tools/pilot13_ab_fixes/round2/`.
Open owner decisions: LAYOUT-12 act-name size (48 pt for all vs larger headliners) and its prose typography paragraph
that contradicts the type scale. TASKS_V5_ALL100.json is 92.1 MB (limit 100 MB).
