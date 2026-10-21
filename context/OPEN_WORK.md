# Open work (priority order; 2026-10-21 update at the top)

0. **2026-10-21:** pilot-13 fixes A+B done (`PILOT13_AB_FIXES_2026-10-21.md`). Next: confirm its judgement calls; share a
   Brand Identity question set and move Decision Quality there; re-import the annotation sheet; check the 12 other marks
   produced by `benchmark_v4/clean_adobe_vectors.py` for dropped coloured elements; roll the same fixes to the other 87 tasks.


1. ~~Expert-feedback plan for the pilot~~ DONE: implemented in place by the 2026-10-14 refresh (OFL font swap, supplied
   clean logos, purpose/export per deliverable, fixed vs open decisions) and the 2026-10-21 fixes. Remaining: roll out to
   the other 87 tasks as Gatsby V8.
2. **MOTION fixes** (all 20 MOTION tasks):
   - consolidation to "one check per rule per deliverable" was never run on MOTION (or LAYOUT-24..35);
   - MOTION-15..19 never independently reviewed;
   - 68 register-only still/print outputs in MOTION registers (MOTION-01..10, 15, 16, 19) are not in the task specs;
     MOTION-05's brief says those items are "unchanged", so decide keep vs remove deliberately;
   - MOTION footage IP marks (MOTION-03, 08, 15, 19) from the IP sweep.
3. **Final whole-corpus audit of V7** (never ran). Include PHOTO-02 and PHOTO-07 (never independently reviewed).
4. **PHOTO-02 conflict:** auto A009 on dish-card-r004/r009 expects takeaway prices 20/21; human H004 requires dine-in
   18/19. Auto checks cannot be edited (runs keyed to them) unless a new version deliberately re-keys them. Needs a decision.
5. **IP-mark remediation** (`memory/project_adobe_ip_sweep.md`): 77 leaks across 27 tasks; only masked local inpaint
   works (whole-frame regeneration destroys engineered defects). Only LAYOUT-02 counter_shot_01/06/10 published so far.
   PHOTO tasks affected: 01, 11, 16, 29, 30. Inventory: `workflows/v5_ip_audit/wf_790cbe01-e38.json` (locate-ip-marks)
   and `wf_919e7b6a-270.json` (comprehensive image IP audit). Also add a no-brand guardrail to every generation prompt.
6. **Source-asset authoring flaws** found while vetting (not planned traps): PHOTO-03, 05, 12, 14, 15, 18, 21, 22, 23,
   25, 27 and VECTOR-02 (details in `PILOT_10.md`). Fixing needs input-asset or CSV edits (masked inpaint or re-binding).
7. **Release status bookkeeping:** `docs/gatsby-v7/RELEASE_STATUS.json` says `completed_creative_runs: 0` although
   PHOTO-04 and PHOTO-13 runs are published under `runs/`.
8. **Page weight:** V7 `index.html` and `TASKS_V5_ALL100.json` are ~85 MB (GitHub limit 100 MB). A V8 with more checks
   will need the data split per task or loaded lazily.
