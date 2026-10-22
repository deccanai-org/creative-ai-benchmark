# StudioBench / Creative AI Benchmark — Working Context & Pilot Plan

> Pull this file up at the start of a new chat to restore context. Last updated: 2026-07-15.
> This is a living doc — keep appending decisions and state as work continues.

---

## 0. What this project is

**Creative AI Benchmark ("StudioBench")** — a benchmark measuring whether an AI agent
(currently **Claude driven through the Adobe Creative Cloud connectors**) can do professional
creative work end-to-end: take a real client brief + brand assets, use pro design tools across
many steps, and produce a client-acceptable deliverable. It also produces licensing-clean
training data.

- **100 tasks**, sourced verbatim from real Upwork/Freelancer briefs, each given a **fictional
  brand** (no real trademarks / no memorization leakage).
- Median ~20 tool calls/task, 99/100 long-horizon.
- Primary outcomes: **commission pass rate** (would a client accept with no rework) and
  **human-parity rate** (agent vs human expert).

### Locations (IMPORTANT — two dirs exist)
- **ACTIVE repo:** `/Users/dhiren/Downloads/Deccan/Adobe-Freelance-Leads/` — git repo
  `dhigdec/creative-ai-benchmark` (private), GitHub Pages at
  `https://deccanai-org.github.io/creative-ai-benchmark/`. **Work here.**
- **STALE snapshot (ignore):** `/Users/dhiren/Downloads/Adobe-Freelance-Leads/` (no "Deccan") —
  a frozen June-11 copy; do not use.

### Key files / dirs
| Path | What |
|---|---|
| `complex_benchmark/adobe_only/specs/AO-*.json` | the 100 task specs (brief, inputs, outputs, connector_workflow, difficulty, reverify) |
| `input_assets/AO-*/` | per-task generated input assets (manifests + `assets/` media, ~1.4GB local; masters on GCS) |
| `input_assets/index_studiobench.html` + `all_assets.html` + per-task `contact_sheet.html` | asset gallery/dashboards |
| `authored_verifiers.json` | Layer-3 task-specific verifiers, keyed by AO-ID (see §4) — **only 55/100 current tasks covered** |
| `tasks_supply_sheet.csv` (root) + `docs/tasks_supply_sheet.csv` (Pages) | per-task tool-calls, outputs, difficulty, price |
| `asset_pipeline/` | generation + multi-layer QC pipeline (build_supply_sheet.py, build_dashboard.py, judge.py, vlm_qa.py, etc.) |
| `docs/` | GitHub Pages ops site (index, Task_Tags_v3_Table, Taxonomy_Distribution, Quality_QA_Report, CSVs) |
| `publish_docs.sh` | syncs reports into `docs/` before push |
| `Creative_AI_Benchmark refined (4).docx` (in `~/Downloads/`) | **the rubrics/pipeline design doc** — source of §3 below |

### Env
- macOS, zsh. Venv: `asset_pipeline/.venv/bin/python` (PIL, google-genai, openai, etc.).
- API keys in `asset_pipeline/.env`: GEMINI/OPENAI/ANTHROPIC/OPENROUTER set; **FAL_KEY blank**
  (FAL = Seedance video gen; only matters for video-asset regen).
- Media gitignored (`input_assets/**/assets/`), lives on GCS; `sync_to_gcs.sh` configured.

---

## 1. Current dataset shape (as of 2026-07-15)
- **100 tasks**, **539 total declared outputs** (was 554 before the 2026-07-15 output-clubbing pass).
- Families: **Photo & Image 49 · Layout & Data 18 · Video & Motion 17 · Vector & Print 16.**
- Difficulty (composite band): **T1_simple 25 · T2_moderate 30 · T3_complex 25 · T4_expert 20.**
- Audio was fully de-scoped earlier (removed as a modality from 19 tasks).

---

## 2. The 4-phase evaluation pipeline (from the rubrics doc)

One rule throughout: **human experts make every judgment; code only checks objective facts.
No AI judge.**

- **Phase 0 — Task validation (expert, Yes/No × 7):** one specific deliverable? doable with
  supported tools only? no leaked answer? startable without client clarification? fictional
  brand, no real data? right difficulty (not trivial)? reads like a real professional task?
- **Phase 1 — Input-asset validation (expert + code), 8 dims, each Pass/Fix/Reject:**
  completeness · feasibility integrity · realism/difficulty · brand coherence · no-answer
  leakage · provenance/licensing (code: source log + SHA-256 + commercial-safe flag) ·
  decision quality · hallucination/contradiction. Task enters only when every dim = Pass.
- **Phase 2 — Golden trajectory (expert):** the expert *does the task themselves* using the
  same connector tool vocabulary; logs each step as (action from a growing dropdown +
  one-line reason) AND screen-records (no audio). Produces the golden output + golden path.
- **Phase 3 — Output scoring (5 layers):**
  1. **Capabilities K1–K7** (roll-up, computed from layers below): K1 instruction adherence,
     K2 asset utilization/fidelity, K3 compositional craft, K4 creative quality, K5
     communication, K6 agentic competence, K7 honesty/calibration.
  2. **Operation craft** — per-family anchored Pass/Minor/Major checklists (Photo&Image,
     Vector&Print, Layout&Data, Motion&Audio) → K3.
  3. **Verifier checks** — the task-specific rubric (§4) → mostly K1/K2.
  4. **Process & honesty** — from the step-log; code counts, expert marks Pass/Minor/Major → K6/K7.
  5. **Professional review** — the call (accept/send-back/scrap), punch-list, pin-the-flaw,
     blind face-off, confidence.
- **Comparison tracks:** A = human vs 1 agent run (output quality); B = 3 agent runs vs golden
  trajectory (process/path match); C = best-of-3 agent vs human.

---

## 3. Verifiers (Layer 3) — the "verifier mapping"

`authored_verifiers.json` — dict keyed by AO-ID → list of verifier objects. Each verifier:
```json
{ "check": "...", "type": "auto|expert", "pass_condition": "...",
  "feeds": "K1..K7", "weight": "mandatory|quality", "source": "output|..." }
```
This is exactly the "verifier mapping" the ops team wants in CSV form.
**Coverage gap:** only 55 of the current 100 tasks have verifiers (the original AO-00..AO-73
set). The newest tasks (AO-74..AO-123), including the hardest T4 image tasks, have **none yet**.

---

## 4. THE PILOT (in progress)

**Goal:** a trial run of the whole 4-phase pipeline on **2 of the 100 tasks**. Give creative
experts everything (task brief, input assets, wanted deliverables) so they run Phases 0–3 on
their end; we also run Claude via the Adobe connectors. Tasks must be **best-quality, realistic,
HARD, and image-related**.

**Ops team ask:** "Share the task list along with the verifier mapping in CSV format."
→ Deliverable: a CSV = the pilot task list + each task's verifiers (check/type/pass/feeds/weight).

### Candidate analysis (image family, hard, fully headless [C], assets present locally)
| Task | Diff | Tools | Outputs | Verifiers? | Craft tested |
|---|---|---|---|---|---|
| **AO-104** Northwind headshots — batch retouch+grade, color+B&W, 3 crops | T4 | 40 | 18 img | none | portrait retouch, grade consistency, B&W |
| **AO-115** Rukmini 925 jewelry — isolate on pure white, 6 SKUs | T4 | 45 | 2 (×6 img) | none | hard masking/edges, metal grade |
| AO-113 Loomhearth apparel flat-lay cutouts, 6 garments | T4 | 48 | 3 (×6) | none | masking, color-true, consistent bg |
| AO-110 Summit&Sable product grade + masked recolor | T3 | 32 | 3 | none | grade consistency, masked recolor |
| AO-116 Umbra Loft noir duotone posters, 3 shots | T3 | 34 | 2 (×3) | none | stylized/duotone FX |
| AO-11 Sterling ruby pendant retouch+cutout+vectorize | T3 | 21 | 7 (mixed) | **18** | retouch, cutout (mixed deliverables) |
| AO-32 Modern house listing photo grade | T3 | 27 | 6 img | **16** | perspective/verticals, color, web+TIFF |

### DECISION (2026-07-15, FINAL): pilot tasks = **AO-13 + AO-115** (both Photo & Image, both fully headless)
History (many swaps): AO-104+AO-32 → AO-32→AO-116 (duotone) → →AO-78 (café menu) → user wanted BOTH tasks
Photo & Image + fully-headless → AO-78→AO-115 (jewelry) & AO-104 kept → **user then wanted an AD/FLYER task
→ tried AO-72 (store graphics) but it has the same template-trap as the menu (proxy .indd/.ai) → swapped
AO-104→AO-13** (Meta ad photo-asset prep), the strongest *genuinely* fully-headless ad task. Superseded
tasks' verifiers/pro-briefs stay in the repo (`pilot_briefs/AO-78.md`,`AO-104`… ; verifiers in json).
- **AO-13** El Vecino Cocina Meta ad photo-asset prep — T3_complex, 19 calls, 10 deliverables. **Fully `[C]`
  headless, NO template trap.** Ad/marketing flavor: warm/bold food grade, color-splash + Subject-Pop
  scroll-stop variants, dish cut-out, 3 Meta ratios (1:1/4:5/9:16 by crop-reframe), stock backdrop, logo SVG.
  **17 verifiers** (reconciled: restored the deliverables-present check, fixed a stale "outpaint the ratios" verifier → reframe-crop; dropped a stale
  Firefly-board verifier; added a K7 no-generative dealbreaker). Pixels viewed: realistic tacos-al-pastor hero.
- **AO-115** Rukmini Silverworks 925 jewelry — T4_expert, 45 calls, 12 deliverables (6 SKUs × transparent
  PNG + 3000² white-bg JPEG). **Fully `[C]` headless.** Tests **elite product-retouch / isolation** — open
  filigree + chain-link gaps cut to transparent, cast-free silver grade, pure #FFFFFF. **18 verifiers.**
  Pixels viewed: filigree pendant (open scrollwork) + curb chain = genuinely brutal masking.
- **Professional briefs authored:** `pilot_briefs/AO-13.md` (ad-agency creative brief — deliverables table,
  1080² ratios, art direction, no-generative constraint) + `pilot_briefs/AO-115.md` (product-retouch spec).
  Handoff builder auto-uses `pilot_briefs/<id>.md` as that task's `BRIEF.md`.
- **Why this pair:** both fully agent-runnable Photo & Image → clean human-vs-agent compare on both.
  AO-13 = marketing/ad asset prep (grade/cut-out/reframe — agent competitive); AO-115 = product isolation
  (agent likely hits a ceiling on fine filigree — honest finding). Different flavors (ad vs catalog).
- **Template-trap rule learned:** any task whose inputs include a `.indd`/`.ai` that exists only as a
  `.proxy.txt` stub (menu AO-78, store-graphics AO-72, flyer AO-24, etc.) is NOT agent-doable end-to-end —
  the `document_render_layout`/`render_vector` step can't export a template that doesn't really exist.
- **Ruled out:** AO-78/menu (layout not headless — agent can't build it); AO-113 apparel (easier masking than
  jewelry); AO-18 dark-food (T3, fewer inputs); AO-32 (routine); AO-110 (not headless).

### OPS SYNC (2026-07-14) — authoritative operational model
- **4-stage pipeline** (maps onto the doc's Phase 0–3): **Stage 1** Metadata verification (tags) =
  doc Phase 0 + tag check · **Stage 2** Asset validation + **verifier WRITING by the freelancer** =
  doc Phase 1 + author verifiers · **Stage 3** Human SFT (creative execution) = doc Phase 2
  trajectory · **Stage 4** Agent-vs-human comparison = binary Pass/Fail verifiers + "would people
  actually buy this?" + craft/process/review.
- **Trajectory capture:** screen-recording (no audio) vs before/after screenshots at each tool call —
  one freelancer does each in the dry run to compare.
- **Pricing:** per-OUTPUT payment (not hourly); 3 buckets by weighted task score (<6 / 6.5–10 / >10);
  copies per task 3→1; prefer industry-experienced freelancers over students.
- **Dry run:** 2 warm-contact freelancers, kickoff by Fri/Sat; Sumadhura circulates a Google Form;
  assets move from Dhiren's GCS → annotation-admin S3; Adhiraj drafting annotator instruction docs.
- **Ops note said "image AND video modalities"; USER OVERRODE 2026-07-15 → image-only pilot.** So
  the pilot stays **AO-104 + AO-32** (both image). (On record; revisit if ops pushes back.)
- **Dhiren action item "flag/recount format-variant outputs" = the output-clubbing done this
  session** (554→**539**, avg outputs 5.54→**5.39** ≈ the ~5.4 ops cited). Share 539 back to ops.

### Rubrics/verifiers source of truth
There is **no separate "rubrics CSV."** Canonical = `authored_verifiers.json`. BOTH the master
`StudioBench_Task_Mapping.html` (via `build_task_mapping.py`) and the pilot CSV (via
`build_pilot_verifiers.py`) derive from it. (Old `rubrics.json` under executed_jobs/mega_executions/
flagship_executions are a different per-execution format from the earlier experiments — not these.)

### STALE: `StudioBench_Task_Mapping.html` (the 100-task verifier/mapping HTML)
Built Jul 13 (commit-time), **internal doc, NOT on GitHub Pages.** Stale in 3 ways: (1) verifiers
cover only **66 of 100 tasks** ("1,077 checks across the 66 tasks") — missing AO-104 + 33 newest;
(2) predates today's changes (no AO-104 verifiers; still shows AO-32's pre-fix set); (3) its builder
reads the old 66-row `task_tags.json`, not the 100-row `task_tags_v3_core.json`. For the pilot, the
current/correct verifier source is `pilot_verifier_mapping.csv`. Refreshing the master HTML to all
100 = a separate job (needs verifiers authored for the 33 uncovered tasks + builder pointed at v3 tags).

### Pilot deliverables — BUILT this session (not yet committed)
1. **`pilot_verifier_mapping.csv`** (repo root) — the ops deliverable = task list + full verifier
   mapping for both tasks, **23 rows (AO-13 11 + AO-115 12)** — tightened; `source` column dropped, cols: task_id, task_title, family, difficulty, tool_calls, num_deliverables, verifier_no, check, type, pass_condition, feeds_capability, weight. (source dropped 2026-07-15 — internal metadata, not needed by ops.) Pro briefs live in `pilot_briefs/` (AO-115 active; AO-78 kept).
2. **`pilot_handoff/`** (repo root) — expert handoff package, **rebuilt to the OPS 4-STAGE model**:
   - `README.md` (2 tasks + 4-stage instructions + who-does-what), `pilot_verifier_mapping.csv` (golden ref for ops).
   - per task `<id>_<slug>/`: `BRIEF.md` (verbatim brief + inputs + deliverables + suggested workflow),
     `assets/` (real input files), and the 4 stage sheets: `stage1_metadata_verification.csv`
     (metadata tags to confirm + 7 task-validity Y/N), `stage2_asset_validation.csv` (8 dims Pass/Fix/Reject),
     `stage2_write_verifiers_TEMPLATE.csv` (BLANK — freelancer authors verifiers), `stage3_trajectory_steplog.csv`
     (step + reason + before/after screenshot cols), `stage4_comparison_scoring.csv` (binary verifiers +
     craft + process/honesty + pro-review incl. "would people buy this?" + A/B human-vs-agent).
   - `authored_verifiers.json` updated in place (AO-104/AO-115/AO-78/AO-116 authored, AO-13/AO-32 reconciled) → covers 70 tasks; pilot = AO-13 + AO-115.
   - Pro briefs: `pilot_briefs/AO-13.md` + `AO-115.md` (active); `AO-78.md` (kept) (handoff builder auto-uses any `pilot_briefs/<id>.md` as that task's BRIEF.md).
3. **TODO (Claude side):** run both tasks via the Adobe connectors (element ops + local compose)
   to produce the agent runs (T1/T2/T3) for the human-vs-agent comparison tracks.

### Builder scripts (in session scratchpad, re-runnable)
`pilot_verifiers.py` (authors AO-104 + reconciles AO-32 + emits the CSV) and `build_handoff.py`
(assembles `pilot_handoff/`). Both idempotent; re-run from repo root.

---

## 5. Work done this session (2026-07-15)
- **Output-clubbing pass (COMMITTED + PUSHED, commit `5c5ab78`):** 14 groups across 13 tasks
  where the same deliverable shipped in multiple file formats (e.g. vector logo also as PNG/JPEG,
  print PDF + JPEG copy) were merged into one `spec.outputs[]` entry with a `formats` list; the
  secondary format's description is folded into `spec` (no info lost). `build_supply_sheet.py`
  patched so `output_breakdown` shows e.g. `PDF+image×1`. Total outputs **554 → 539**.
  Tasks changed: AO-14, 22 (2 groups), 29, 52, 76, 78, 80, 81, 83, 90, 105, 106, 107.
  `tasks_supply_sheet.csv` regenerated + synced to `docs/` (live on Pages). Verified: JSON valid,
  CSV recompute idempotent (0 diff), no orphan/dupe output names.
  - Other pages (Taxonomy_Distribution, Task_Tags_v3, Quality_QA_Report) don't carry a live
    output-count number → left unchanged, correctly.

## 6. Open / pending items
- **AO-96 broken working tree (NOT committed):** an earlier interrupted VLM-QA/regen session
  left AO-96's manifest with wiped video entries (`path:null`, "FAL_KEY not set"), a bad logo
  regen (photorealism prompt applied to a flat-vector logo → "photo of a sticker"), and a
  non-standard `contact_sheet.html`. The `.mp4` files on disk are fine; only metadata corrupt.
  Fix plan: restore 3 video manifest entries from HEAD, revert/redo the logo regen with the
  correct flat-vector prompt, keep the (good) endcard regen, rebuild the contact sheet, recompute
  ready/QC, and fix the regen script to skip video when FAL_KEY absent + not apply the
  photorealism suffix to logo/vector kinds. **Was paused mid-fix; nothing changed yet.**
- **7 untracked files** from that interrupted VLM QA pass: `asset_pipeline/vlm_qa.py`,
  `asset_pipeline/regen_fix.py`, `asset_pipeline/.vlm_models.json`, `vlm_qa_report.json`,
  `vlm_qa_report_v2.json`, `vlm_qa_run.err`, `vlm_qa_run2.err`. (VLM QA flagged defects in 8
  tasks — AO-117/74/34/80/46/84/96/112 — but only AO-117 was run through the fixer, and it failed.)
- **Verifier coverage:** 45/100 tasks (AO-74+) still need verifiers authored.

## 7. People / preferences
- Suma (ops/pricing lead): asked for difficulty as a range/composite band (done) — the
  T1..T4 composite band exists because of her feedback.
- Prefs: honest, evidence-backed claims; realistic (non-AI-looking) assets; asset generation
  uses non-Claude models (Claude may judge); confirm before pushing/publishing.
