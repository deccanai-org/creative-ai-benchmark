# CLAUDE.md: StudioBench (Creative AI Benchmark for Adobe)

Start here. This file is the entry point for any Claude session picking up this project.
Last full update: 2026-10-09. Detailed context lives in `context/` (index at the bottom).

## What this project is

StudioBench is a benchmark of **100 freelance-style creative commissions** used to evaluate creative AI
agents that work through the **Adobe connector** (the "Adobe for creativity" MCP: Photoshop/Lightroom
image ops, Express, InDesign data merge, Fonts, Stock, Acrobat, Premiere-style video). Owner: Dhiren
(Deccan AI). Client: Adobe.

- **Families and IDs:** PHOTO-01..30, VECTOR-01..15, LAYOUT-01..35, MOTION-01..20. Display codes look like
  `SB3-004-PHO`. Every brand is fictional.
- **Each task** = a client brief + brand identity (palette roles, colour rules, type system, voice) + supplied
  input assets (photos, PDFs, CSVs, notes) that carry **engineered defects** (planned traps) + an output
  register (exact filenames, sizes, pages, record bindings) + **verifiers**:
  - **Auto checks** (`A###`): code-checkable facts (file exists, size, pages, text present).
  - **Human checks** (`H###`): one observable Yes/No fact each, tagged with an objective rubric question
    `K1_Q1..Q5` (instruction adherence), `K2_Q1..Q4` (asset use and fidelity), `K5_Q1..Q2` (communication).
  - **Trajectory checks** (K6): scored from a run's step log.
- **Evaluation pipeline** (from the rubrics doc, see `PILOT_AND_SESSION_CONTEXT.md` section 2): Phase 0 task
  validation, Phase 1 input-asset validation (8 dims incl. "decision quality"), Phase 2 golden trajectory by
  an expert, Phase 3 output scoring (K1 to K7). Humans judge; code checks only objective facts; no AI judge.

## Update 2026-10-27 (read first)

- **annotation-pilot-v2** (`docs/gatsby-v7/annotation-pilot-v2/`): the same 13 tasks and 6,312 human checks, shown as
  1,500 rules with one row per original check (same ID, own answer; each row rebuilds its check word for word).
  Built by `scripts/build_v7_annotation_pilot_v2.py`, tested by `scripts/test_pilot13_v2_groups.py`; v1 and
  `TASK_SPEC.json` untouched. Record: `context/PILOT13_V2_GROUPED_VERIFIERS_2026-10-27.md`.
- **Checks moved to code in v2**: 748 of those 6,312 checks (174 rules) are now answered by code (PDF text, OCR,
  image matching), shown under their K question marked Code with the code's answer on the 2026-09-28 run; a row the
  code cannot decide comes back to a person. Operations: `tools/auto_verifier/objective_ops.py` (tests:
  `test_objective_ops.py`); convert, test and decide: `tools/pilot13_v2_automation/` (README). Results page:
  `docs/gatsby-v7/annotation-pilot-v2/automation.html`. Not yet in TASK_SPEC.json, the V7 site, the Sheet or
  `verify_outputs.py`: that step needs Dhiren's approval.
- **Round 2 (2026-10-28)**: the other 472 automatable checks were built (`tools/auto_verifier/objective_ops_r2.py`,
  one handler per rule in `tools/pilot13_v2_automation/round2.py`); 418 more moved, so 1,167 of the 6,312 checks
  (299 rules) are answered by code. 218 checks (50 rules) have code but stay with people. Round-1 conversions are
  unchanged; made-file generators now also write a second broken set (`bad2`).
- **Round 3 (2026-10-28)**: colour on images, the rules that needed a definition, and the measurable rules re-sorted
  out of judgement (no AI vision model; handlers `tools/pilot13_v2_automation/round3*.py`, ops
  `tools/auto_verifier/objective_ops_r3.py` + `ops_r3_*.py`, reference `OPS_REFERENCE.md`). 3,895 of the 6,312
  checks (872 rules) are now answered by code; 1,201 (313 rules) have code but stay with people; each moved rule lists
  the limits it decides by on `automation.html`. Made files gained a third broken set (`bad3`). Heavy runs go to a VM.
- **annotation-pilot-v3 (2026-10-29)**: `docs/gatsby-v7/annotation-pilot-v3/`, built by `scripts/build_v7_annotation_pilot_v3.py`
  on top of v2 (v1 and v2 untouched; v3 links v2's thumbnails). Human checks answered by code moved from Human verifiers
  to a new per-task Auto verifiers page (`<ID>-auto.html`: the task's own automatic checks, then the moved rules with how
  the code checks, limits and the 2026-09-28 answers). Rebuild after every decide_moves.py run.
- **Round 4 (2026-10-29)**: the remaining code-measurable checks (`round4_*.py`, `ops_r4_*.py`, bad4 made set):
  4,143 of 6,312 human checks (928 rules) now answered by code; v3 shows 2,169 for people.
- **Round 5 (2026-10-29)**: close calls in code (`round5_code.py`, `ops_r5_code.py`) and objective look, count and read
  checks by a vision model (`round5_vlm_{a,b,c}.py`, `ops_r5_vlm*.py`: Gemini 3.8 Flash via OpenRouter, pinned Google
  Vertex, temperature 0, two seeds must agree, blind reading, answers saved in `tools/pilot13_v2_automation/vlm_answers/`
  and replayed; `VLM_OFFLINE=1` needs no key). 4,631 of 6,312 human checks (1,041 rules) answered automatically: 4,186 by
  code, 445 by the vision model; v3 shows 1,681 for people. The OpenRouter key is NEVER in the repo (it lives in
  `~/.config/pilot13/openrouter.env` or `OPENROUTER_API_KEY`); vision rules carry a "Vision model" badge.

## Update 2026-10-22

- Colour tolerance + checker sync (after verifying ChatGPT's follow-up): every exact-colour Measure check states its rule
  (R, G, B within 5; video stills within 10; SVG exact; press PDFs via Relative Colorimetric + black point compensation).
  `benchmark_v4/verify_outputs.py` now equals `tools/auto_verifier/`; edit the repo copy first. Live Sheet not yet re-imported.
- Follow-up review fixes: see `context/PILOT13_REVIEW_FIXES_2026-10-22.md`. The current Sheet import is
  `tools/pilot13_ab_fixes/round3/sheet_rows_2026-10-22.json`, not the older round2 export.
- Repository visibility was verified PUBLIC on 2026-10-22. Older statements below that call it private are historical.
- LAYOUT-12 typography is reconciled: poster headline acts larger than the remaining 48 pt acts, designer-selected
  headline sizes. PDF measurement and ICC identity checks are hardened; all human methods are explicit and visible.
- Repo is now **deccanai-org/creative-ai-benchmark**; site https://deccanai-org.github.io/creative-ai-benchmark/ (old dhigdec links 404).
- Round 2 fixes (external review): full-coverage Sheet export (one row per deliverable, all human checks), honest coverage with
  "not verified" cells, hardened auto ops + leading/tracking, Look/Measure/Estimate labels. See `context/PILOT13_AB_FIXES_2026-10-21.md` (Round 2).

## Update 2026-10-21

- **Pilot is 13 tasks** (original 10 + LAYOUT-12, VECTOR-04, MOTION-11), refreshed 2026-10-14 (purpose/placement/audience/
  export per deliverable, OFL fonts in assets, clean transparent logos, fixed vs open decisions, Part A questions reworded).
- **2026-10-21 fixes A + B applied to those 13:** PHOTO-10 logo rebuilt (leaf restored, S3 same keys), every brief/brand
  constraint checked on every deliverable with published coverage tables
  (`docs/gatsby-v7/annotation-pilot/coverage/`, 0 missing cells), machine facts moved to new auto ops, unjudgeable
  measurements and duplicates retired, atomic plain-language checks, auto kept out of the Human tab and the sheet.
  Full record and judgement calls: `context/PILOT13_AB_FIXES_2026-10-21.md`. Tooling: `tools/pilot13_ab_fixes/`.
- Still open from the audit: Brand Identity question set + Decision Quality (platform), task variety, MOTION/other tasks.
- `TASKS_V5_ALL100.json` is 90.4 MB (GitHub limit 100 MB): split before adding much more data.

## Current state (2026-10-09)

1. **Gatsby V7 is the current full corpus**: https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/
   (100 tasks, 1,436 exports, 44,527 checks = 11,217 auto + 33,310 human, per `docs/gatsby-v7/RELEASE_STATUS.json`).
2. **A 10-task annotation pilot ran on V7**: PHOTO-04, 06, 08, 10, 19, 20, 24, 26, 28 and LAYOUT-15.
   Pages: `https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot/<ID>.html`.
   Why these 10, and what was rejected: `context/PILOT_10.md`.
3. **In-house creative expert feedback arrived 2026-10-07.** My assessment and a 5-part fix plan are in
   `context/EXPERT_FEEDBACK_2026-10-07.md`. **Waiting on Dhiren for 3 decisions** (fonts: swap vs fallback;
   logos: named deliverable vs supplied clean file; scope: pilot-v2 for 10 first vs all 100). Nothing from
   that plan has been implemented yet.
4. **MOTION tasks still need their fixes** (next after the expert-feedback work). Full queue: `context/OPEN_WORK.md`.

## Where things are

### Branches (one GitHub repo: `git@github.com:dhigdec/creative-ai-benchmark.git`, private; Pages public)

| Branch | What it holds |
|---|---|
| `main` | Published site (`docs/`, served by GitHub Pages from `/docs`), page tooling (`scripts/`, `tools/`), all context docs. |
| `codex/studiobench-v3-audit-rebalance` | **V3 corpus source**: `complex_benchmark/adobe_only/` (specs, rebuilt specs, rebuild guidance), `input_assets_v3/<ID>/asset_plan.json` + `manifest.json` (the `defect_engineered` field says which source contradictions are INTENDED traps), asset generators (`asset_pipeline/generate_v3*.py`, `render_v3_pdfs.py`), ChatGPT handoff docs, pilot handoff. |
| `remediation/audit-fixes-2026-08-24` | Old AO-* corpus (pre-V3). Historical. |

`main` and the `codex/...` branch have **unrelated histories** (a July history rewrite). Do not merge them.
Read V3 files with `git show origin/codex/studiobench-v3-audit-rebalance:<path>` or a separate worktree.

### Local checkouts on Dhiren's Mac

- `~/Documents/ChatGPT/Adobe_Gpt/publish/creative-ai-benchmark` → `main` (partial clone, `blob:none`). Site work happens here.
- `~/Downloads/Deccan/Adobe-Freelance-Leads` → `codex/studiobench-v3-audit-rebalance`. Input-asset media is on disk
  here under `input_assets_v3/<ID>/assets/` (gitignored).

### Input assets (media is NOT in git)

- Public S3 (used by the pilot pages):
  `https://annotationprod.s3.ap-south-1.amazonaws.com/creative-ai-benchmark/v3.1/tasks/<SB3-code>__<slug>/assets/<file>`
  (the exact key per file is in `docs/gatsby-v7/tasks/<ID>/ASSET_MANIFEST.json`, field `s3_key`, with `sha256`).
- Local copies: `Adobe-Freelance-Leads/input_assets_v3/<ID>/assets/`.
- Older AO-* assets: `s3://annotationprod/creativegym/`. Full storage and AWS access details: `context/STORAGE_AWS.md`.

## Versions

| Path | What it is | Status |
|---|---|---|
| `docs/gatsby/`, `gatsby-v2/`, `gatsby-v4/` | Earlier review pages | Frozen |
| `docs/gatsby-v5/` | First objective-only verifier set, K-sectioned (18,118 checks at release; later got PHOTO-04/13 completed runs + trajectories) | Frozen. Do not edit. |
| `docs/gatsby-v6/` | **A different team's build** ("task-contract review", commit `d5acf70`, tooling `tools/gatsby_v6/`) | **Never write here.** Its PHOTO-04 pin (High Summer EUR 680/740/780) differs from V7's (lowest 2027 rate, season named). |
| `docs/gatsby-v7/` | V5 + reviewer feedback applied to all 100 tasks + ops-review fixes + pilot | **Current.** |
| `docs/gatsby-v7/annotation-pilot/` | 10 client-facing pilot briefs + answer-free verifier bank | Used by annotators. Do not overwrite; build a v2 folder. |
| `docs/gatsby-v7/annotation-pilot-v2/` | The 13 pilot tasks with human checks grouped into rules (2026-10-27) | Generated by `scripts/build_v7_annotation_pilot_v2.py`; never hand-edit. |
| `docs/pilot/` | July AO-13 / AO-115 pilot handoff | Historical |

Detail and numbers per version: `context/VERSIONS.md`.

## How a Gatsby version folder works (read before editing anything)

`docs/gatsby-vN/index.html` (V7: ~84 MB) = CSS + app JS + one embedded blob
`<script type="application/json" id="data">{tasks:[{id,code,title,family,brief,brand,storage,outputs,groups,checks,readiness,assets,exclusions,run?}],repairImages,kCatalog}</script>`.

The same data is fanned out to: `TASKS_V5_ALL100.json`, `ATOMIC_VERIFIERS_ALL100.json`,
`OUTPUT_REGISTER_ALL100.json`, `RELEASE_STATUS.json`, `data/*.csv`, and per task
`tasks/<ID>/{TASK_SPEC.json, VERIFIERS.json, VERIFIERS.md, OUTPUT_REGISTER.json, BRIEF.md, BRAND_IDENTITY.json/.md,
DELIVERABLES.md, ASSET_MANIFEST.json, RELEASE_GATES.json, RUN_RESULT.json}`.

**Every edit must land in every copy.** After editing, verify: page blob == `tasks/<ID>/VERIFIERS.json` per
check_id, all JSON parses, no duplicate check ids, counts in `RELEASE_STATUS.json` updated.
Check id format: `<TASK>/<output_id>/<A###|H###>`.

Pilot pages are generated, not hand-edited: `scripts/build_v7_annotation_pilot.py` (+ `sync_v7_pilot_content.py`,
`fix_v7_pilot_typography.py`, `build_v7_pilot_site.py`, `build_v7_main_attachments.py`; tests `scripts/test_v7_*.py`).
They read the V7 task files, so V7 task edits flow into the pilot when rebuilt.

## Rules (non-negotiable, learned the hard way)

1. **New version = new folder.** Never modify `gatsby-v5`, `gatsby-v6` or pages annotators already used.
2. **Do not change briefs, brands or assets beyond what feedback requires.** Keep each task's own fonts and voice.
3. **Never remove or give away an engineered trap.** Check `asset_plan.json` `defect_engineered` first. Pin ambiguity
   by criterion (e.g. "that house's lowest 2027 nightly rate"), never by naming the trap or its answer.
4. **Never edit auto checks.** PHOTO-04 and PHOTO-13 completed-run answers are keyed to them.
5. **Check wording:** one observable fact, Yes/No, at most 40 words, names the deliverable as “Name” (file.ext) and
   the exact source asset file; **no em or en dashes in prose**.
6. **Never rename filenames or S3 keys.**
7. **Git:** commit only when Dhiren asks. Identity `Dhiren Gangishetty <dhiren.gangishetty@deccan.ai>`.
   `.gitignore` blocks `*.png/*.jpg/*.pdf/*.zip/...`: deliverables that a page shows must be `git add -f`'d or the
   live page 404s (this happened on V7). Run `git status` and a secret scan before every push; `.env` files never.
8. **JSON formatting:** the corpus JSON is `indent=1, ensure_ascii=False`. Re-dump with exactly that or the diff
   explodes into millions of lines (this happened once on V7).
9. **Size:** GitHub's hard limit is 100 MB per file; `index.html` and `TASKS_V5_ALL100.json` are ~85 MB.
10. **Verify against what the user sees:** reproduce in the live page/browser before reporting a defect or a fix.
11. **Illusion backend** (the separate API product Adobe also uses) is out of scope here and strictly read-only.

## Recipes

- **Serve locally:** `cd docs && python3 -m http.server 8806` → `http://localhost:8806/gatsby-v7/`.
- **Pages build status:** `gh api repos/dhigdec/creative-ai-benchmark/pages/builds/latest --jq .status`.
- **Edit one check everywhere:** exact-string replace of its full text across the files listed above (count
  occurrences first; they must match per copy), or prune by `check_id` from every JSON list + the `.md` table row +
  the csv row + the page blob. Then run the verification above.
- **Vet a task for an assessment set:** the 6 lenses in `context/PILOT_10.md` (record vs image match, feasibility,
  verifiability, cross-output checks, unplanned contradictions, real-world brand marks). Look at every bound image.
- **Feedback patch tooling** (how V7 was produced): `tools/gatsby_v7_feedback/` (recovered snapshot, see its README).
  The authoritative record of every V7 change is `git diff` between `docs/gatsby-v5/tasks/<ID>` and `docs/gatsby-v7/tasks/<ID>`.
- **Adobe connector** (fonts, previews, running tasks): needs authorisation via `/mcp` in Claude Code.

## Context index (`context/`)

| File | Contents |
|---|---|
| `context/STATE_AND_HISTORY.md` | Timeline June to October 2026, what happened and why |
| `context/VERSIONS.md` | Each Gatsby version, counts, commits, what changed |
| `context/PILOT_10.md` | The 10 pilot tasks, fixes applied, rejected candidates with reasons, the vetting lenses |
| `context/EXPERT_FEEDBACK_2026-10-07.md` | Expert feedback verbatim, my assessment with evidence, the 5-part plan, pending decisions |
| `context/OPEN_WORK.md` | Everything still open, in priority order |
| `context/PILOT13_AB_FIXES_2026-10-21.md` | Pilot-13 fixes A+B: what changed, numbers, tooling, rebuild order, open judgement calls |
| `context/PILOT13_V2_GROUPED_VERIFIERS_2026-10-27.md` | Pilot-13 v2: grouping rules, safeguards, numbers per task, files, rebuild order |
| `context/STORAGE_AWS.md` | AWS account, S3 bucket `annotationprod`, every asset prefix with sizes, SSO profile, local copies |
| `context/memory/` | Copies of Claude's project memory notes for this project (point-in-time; verify before relying) |
| `context/workflows/` | Multi-agent workflow scripts and their results (feedback pass on V7; V5 audits and the IP-mark sweep) |

Older but still useful: `PILOT_AND_SESSION_CONTEXT.md` (evaluation pipeline, rubric source), `PROJECT_FULL_CONTEXT.md`
and `PROJECT_CONTEXT_HANDOFF.md` (A to Z history up to mid-September: dataset, connector execution modes, asset
pipeline). Those three stop at 2026-09-17.
