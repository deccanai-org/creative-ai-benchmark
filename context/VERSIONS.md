# Versions of the StudioBench review site

All live under `https://deccanai-org.github.io/creative-ai-benchmark/<folder>/` (GitHub Pages from `main:/docs`).

## gatsby, gatsby-v2, gatsby-v4 (frozen)
Earlier review pages for the V3 corpus. Kept for history. Not edited since.

## gatsby-v5 (frozen, 2026-09-19 onward)
- First objective-only verifier set. Human checks grouped under the orange (objective) rubric questions from
  `Creative_AI_Benchmark refined (12).docx`: K1 Q1 to Q5, K2 Q1 to Q4, K5 Q1 to Q2. K3/K4 removed from the page.
  Trajectory tab = K6 Q3 to Q7 (Pass/Minor/Major).
- At release: 100 tasks, **18,118 checks = 12,309 auto + 5,809 human**. Every check: one deliverable, one fact,
  artifact named, exact value quoted, no em/en dashes.
- Later additions (Sep 21): type-system cards on all 100 tasks (each brand keeps its own faces), "Revised contracts.
  Release held." banner removed, PHOTO-04 and PHOTO-13 **completed runs + trajectories** published
  (`tools/publish_completed_runs.py`, deliverables under `docs/gatsby-v5/runs/<ID>/`).

## gatsby-v6 (NOT ours; never write here)
Committed 2026-09-27 by a separate effort (commit `d5acf70`, "Add separate Gatsby V6 task-contract review and
validation"; tooling in `tools/gatsby_v6/` with `task-decisions.json`). Live title "Gatsby V6 | Deccan AI".
Our V7 build was briefly written into this folder by mistake on 2026-09-28 and restored with `git checkout` before push.
Its PHOTO-04 decision pins the heroes to High Summer (EUR 680/740/780); V7 pins "that house's lowest 2027 nightly rate,
shown as a from price with its season named". Use one version per study, not both.

## gatsby-v7 (current, built 2026-09-28)
V5 + the 2026-09-25 reviewer feedback applied to all 100 tasks. The five feedback points:
1. Briefs specific enough to avoid ambiguity (e.g. which season/rate on the hero).
2. Palette: each colour marked mandatory or optional, distribution rules, opacity rules, forbidden treatments.
3. Typography rules (e.g. "no gold") checked consistently on every deliverable, headings, subheadings and fine print.
4. Verifier consistency across all relevant deliverables.
5. Asset checks name the specific asset AND the deliverable (e.g. `verranza_pool.jpg`, not "Verranza").

Decisions taken with Dhiren:
- **Volume, option B:** one check per rule per deliverable. Templated runs with more than 6 outputs keep K2_Q3 rule
  checks only on the first, last and trap-carrying outputs. Content/record/asset checks are never sampled.
- **Register leak: stripped.** Output registers no longer expose trap answers (`values := raw_values`).

How it was produced: one patch per task authored by agents, two independent reviews, a repair pass, then a finalize
pass (consolidation + duplicate-id resolution), applied by a deterministic tool to every copy. Tooling snapshot in
`tools/gatsby_v7_feedback/`; workflow scripts and per-task results in `context/workflows/feedback_v7/`.

Commits: `4fe816a` (V7 added), `b150088` (289 deliverable images/PDFs force-added; they had been dropped by
`.gitignore` and the page showed 404s), `9290297` + `7a8a137` (ops-review fixes, then JSON formatting restored).

Counts now (`RELEASE_STATUS.json`): 100 tasks, 1,436 exports, **44,527 checks = 11,217 auto + 33,310 human**.

Known limits of V7 (also in `OPEN_WORK.md`):
- LAYOUT-24..35 and all MOTION tasks did not get the "one check per rule per deliverable" consolidation.
- No final whole-corpus audit ran. PHOTO-02, PHOTO-07, MOTION-15..19 were never independently reviewed.
- PHOTO-02: auto A009 on dish-card-r004/r009 expects takeaway prices 20/21, human H004 requires dine-in 18/19.
- 68 MOTION register-only still/print outputs kept (MOTION-05's brief says those items are unchanged).
- One em dash remains inside PHOTO-04's recorded run trajectory text (`run.trajectory_steps[18].reasoning`), same in V5;
  it is a recorded log, left as is.

## gatsby-v7/annotation-pilot (2026-09-29/30)
Standalone, client-facing briefs for the 10 pilot tasks plus an answer-free verifier bank
(`verifier-bank/<ID>.json`) and PDF previews. Built by `scripts/build_v7_annotation_pilot.py` and friends
(commits `27897e9` through `fb96bb6`). Notable choices made there: checklist bullets removed from deliverable cards,
briefs rewritten as client prose, source-of-truth note hidden, typography cards rendered in full and synchronized
across the ten briefs (and back into the V7 task files).
