# Pilot-13 verifier rewrite, 2026-10-21: how to patch ONE task

You are rewriting the **human verifiers** of one benchmark task so they meet what the client, the design team
and the in-house creative expert asked for. You do not edit repository files. You write two files (a patch and a
coverage table); a deterministic tool applies the patch to every copy later.

Paths (absolute):
- Repo (READ ONLY): `/Users/dhiren/Documents/ChatGPT/Adobe_Gpt/publish/creative-ai-benchmark`
- Your task spec (READ ONLY): `<repo>/docs/gatsby-v7/tasks/<ID>/TASK_SPEC.json`
  (`client_brief`, `brand_identity`, `deliverables`, `verifiers_human`, `verifiers_auto`, `assets`)
- Tools: `<repo>/tools/pilot13_ab_fixes/` (`apply_patch.py` for the schema, `validate_patch.py` to validate)
- Supplied input files: `/Users/dhiren/Documents/ChatGPT/Adobe_Gpt/reviews/pilot13-refresh-2026-10-14/sources/<ID>/`
  and `.../upload/<ID>/` (new fonts and logos)
- Planned traps: `/Users/dhiren/Downloads/Deccan/Adobe-Freelance-Leads/input_assets_v3/<ID>/asset_plan.json`
  (`defect_engineered` on each asset). These contradictions are deliberate test traps.
- WRITE ONLY HERE: `/Users/dhiren/Documents/ChatGPT/Adobe_Gpt/reviews/pilot13-ab-fixes-2026-10-21/`
  `patches/<ID>.json`, `coverage/<ID>.json`, scratch in `work/<ID>/`.

## What people asked for (the acceptance bar)

1. **Every constraint on every deliverable.** For every constraint in the brief or brand identity (a required font,
   "no gold or silver", a colour rule, an opacity rule, a logo rule...), each individual deliverable it applies to has
   its own check. No sampling of long runs (an earlier tool kept some rules only on the first and last file of a run;
   fill those holes). Otherwise annotators add their own verifiers per deliverable and the count explodes.
2. **Simple, direct language.** Plain words a designer understands at a glance. One observable fact per check.
3. **Atomic.** A check looks at ONE output file. Never "the same as on the other cards", never "all six files are
   delivered", never "the rest of the posts".
4. **Exact output reference.** Every check names its output as “Name” (file.ext), using the deliverable's name and file.
5. **Manageable volume.** No duplicates, and no checks a person cannot answer by looking at the file.

## Ground rules (do not break)

- Do not weaken or drop a check that guards a planned trap (`defect_engineered`), a record value, a truth or permission
  constraint, or a K1_Q5 critical check. You may reword it, keeping the same fact.
- Do not invent requirements. Every check must follow from the brief, the brand identity, a deliverable's commission,
  or a supplied file. Quote values exactly (names, prices, dates, hexes, filenames).
- Do not touch auto checks (`A###`). They are code checks. The only auto checks you may ADD are `pdf_text_style` (below).
- Do not reveal a trap's answer in check wording beyond what the existing check already states.
- Human check text: at most 40 words (aim for 25), no em or en dashes, names the output file, a valid `k_id`
  (K1_Q1..K1_Q5, K2_Q1..K2_Q4, K5_Q1, K5_Q2; brand rules are K2_Q3), no "(when present)".

## The changes to make

### A. Fill coverage holes (and prove coverage with the table)
Build the coverage table first (schema below), then add a check wherever an applicable cell is empty.
Typical holes: a palette or effect rule present on some files of a run but missing on others; a type-role rule
missing on a file that carries that text.

### B. Typography
- Keep ONE check per text role per output for **family and weight**, e.g.
  `The speaker name on “Summit speaker card - Peter Vance” (speaker-card-r003.png) is set in Inter Medium.`
  Annotators compare with the supplied font files.
- **Exact sizes, leading and tracking on raster outputs (PNG, JPG, MP4) cannot be judged by eye: retire them.**
  Where the type scale implies a visible relationship that matters, keep or add ONE relative check, e.g.
  `The speaker name is the largest text on “…” (speaker-card-r003.png).` or
  `The fine print on “…” (vehicle-card-r002.png) is smaller than the mileage text.`
- **PDF outputs with live text:** where the role's exact text is known (a name or value from the output's
  `source_record`, a fixed line in the brief or a supplied copy file), add an auto check:
  `{"type":"auto","assertion":{"op":"pdf_text_style","text":"Paul Devoe","family":"Lexend","weight":"SemiBold","size_pt":20},
  "check":"“District insurance counter card - Paul Devoe” (producer-card-r005.pdf) sets “Paul Devoe” in Lexend SemiBold at 20 pt."}`
  Use the size the type scale states for that placement (pt). Omit `size_pt` if no size is stated. Never guess text.
  Then retire the human exact-size checks for that role (`covered_by` the auto check).
  Do NOT add `pdf_text_style` where the export settings allow outlined lettering (LAYOUT-15 production cards,
  VECTOR-04): keep human family/weight checks and retire exact-size ones (keep relative checks if they matter).
- Remove "(when present)". If the element is required on that output, state it plainly. If it is genuinely optional,
  write `If a standfirst appears on “…” (booking-hero-oliveto.png), it is set in Cormorant Garamond Light.`
- Duplicates: older checks (`H###` written 2026-09) and typography checks (from 2026-09-30, e.g.
  `speaker-card-r003.png: speaker/host name uses Inter Medium (when present).`) often test the same role. Keep one
  (prefer clear full wording that names the output as “Name” (file)), modify it if needed, retire the other with
  `covered_by`.

### C. Atomicity and simplicity
- Cross-output comparisons: rewrite against a stated value or a supplied source file, e.g. "the ground behind the
  sitter is plain warm grey, with no colour cast" instead of "the same tone as the other speaker cards".
  If consistency truly cannot be stated without a reference, name ONE fixed reference that is not "the others"
  (a supplied file, or a value the brief or another single named deliverable fixes, e.g. "the two colours named in
  promoter-deck.pdf"). Allowed exceptions that already name exactly one file: a combined PDF page versus its own single
  file; a cut contour versus its own artwork file.
- Delivery-of-several-files checks: retire; auto `file_exists` and `pages` checks already cover them.
- Compound checks (two or more independent facts): keep the main fact in the existing id (modify), add the other facts
  as new checks. A list that forms one rule ("colours come only from #A, #B, #C") is one fact.
- Shorten anything over 30 words where you can without losing the fact.

## Patch schema (`patches/<ID>.json`)
```json
{"task_id": "PHOTO-19",
 "retire": [{"check_id": "PHOTO-19/speaker-card-r003/H031", "why": "exact size not judgeable on a PNG", "covered_by": ["PHOTO-19/speaker-card-r003/H019"]}],
 "modify": [{"check_id": "PHOTO-19/speaker-card-r003/H014", "check": "The ground behind the sitter on “Summit speaker card - Peter Vance” (speaker-card-r003.png) is plain warm grey with no colour cast.", "why": "was a comparison with other cards"}],
 "add":    [{"key": "r003-no-metallic", "output_id": "speaker-card-r003", "type": "human", "k_id": "K2_Q3",
             "check": "No metallic, gloss or glow effect is used on any type, panel or mark on “Summit speaker card - Peter Vance” (speaker-card-r003.png).",
             "evidence_reference": "Brand identity, palette rules, forbidden: ...", "reference_assets": [], "why": "rule missing on this card"}]}
```
`covered_by` may list existing ids or `new:<key>`. Every item needs a short `why`. `reference_assets` are filenames
from the task's `assets`.

## Coverage schema (`coverage/<ID>.json`)
```json
{"task_id": "PHOTO-19",
 "rules": [
  {"rule_id": "B01", "kind": "brand", "rule": "No gloss, glow, drop shadow, outline, gradient, metallic or busy texture on any type, panel, rule or mark.",
   "source": "brand_identity.palette_rules.forbidden",
   "cells": {"speaker-card-r002": {"checks": ["PHOTO-19/speaker-card-r002/H021"]},
             "summit-announcement": {"checks": ["new:announce-no-effects"]}}},
  {"rule_id": "D01", "kind": "deliverable", "rule": "<exact text of a commission.content bullet>", "source": "deliverables[].commission.content",
   "cells": {"speaker-card-r002": {"checks": ["..."]}, "summit-announcement": {"na": "This requirement belongs to the speaker cards, not the announcement."}}}
 ]}
```
- `kind`: `brand` (palette, distribution, opacity, forbidden, photography, logo use), `type` (one rule per type-scale role,
  plus checkable type rules and the signature move), `brief` (cross-cutting brief constraints, e.g. "What stays
  fixed"), `deliverable` (one rule per distinct `commission.content` bullet, text copied exactly).
- `cells` must list EVERY output of the task. A cell has `checks` (ids that exist after your patch and belong to that
  output) or `na` with a specific reason of at least six words (e.g. "Restoration masters carry no added typography,
  per the brief.").
- A combined/run file that repeats single files may mark brand/type rules `na` only if an existing check confirms its
  pages match the single files; cite it in the reason.

## How to work
1. Load the spec with Python. Print every human check grouped by output. Read the brief, brand identity, each
   deliverable's commission, and the asset plan's `defect_engineered` notes.
2. Work programmatically for templated families (the same check on every file of a run), then read every resulting
   check for your task and fix wording by hand.
3. Run `python3 <repo>/tools/pilot13_ab_fixes/validate_patch.py <ID>` until it reports 0 errors. Read the warnings and
   fix the ones that matter (long checks, pixel values a person cannot judge).
4. Your final answer is a short summary (counts before/after, holes filled, conversions, anything you could not resolve).
