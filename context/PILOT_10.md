# The 10-task annotation pilot (V7)

Pages: `https://deccanai-org.github.io/creative-ai-benchmark/gatsby-v7/annotation-pilot/<ID>.html`

| Task | Brand | Pilot page |
|---|---|---|
| PHOTO-04 | Verranza Coastal Retreats | annotation-pilot/PHOTO-04.html |
| PHOTO-06 | Hollis Family Archive | annotation-pilot/PHOTO-06.html |
| PHOTO-08 | Meridian Motors | annotation-pilot/PHOTO-08.html |
| PHOTO-10 | Northgrove | annotation-pilot/PHOTO-10.html |
| PHOTO-19 | Cascadia Founders Summit | annotation-pilot/PHOTO-19.html |
| PHOTO-20 | Vellacourt | annotation-pilot/PHOTO-20.html |
| PHOTO-24 | Lunara Chronometry | annotation-pilot/PHOTO-24.html |
| PHOTO-26 | Thornmere Home | annotation-pilot/PHOTO-26.html |
| PHOTO-28 | Verda Reformer Studio | annotation-pilot/PHOTO-28.html |
| LAYOUT-15 | Aldervale Mutual | annotation-pilot/LAYOUT-15.html |

## How the set was chosen (2026-09-28)

1. **First pick (mostly PHOTO, cleanest after the feedback pass):** PHOTO-04, 06, 08, 12, 19, 22, 24, 25, 26, 27.
   Criteria: two independent reviews + repair, consolidated, 0 or 1 benign not-fixed review items, no real-world
   brand marks in inputs. Excluded up front: PHOTO-01, 11, 16, 29, 30 (real brand marks from the IP sweep),
   PHOTO-02 and 07 (never independently reviewed), PHOTO-13 (register still certifies swapped provenance lines).
2. **Ops review** of that set (Dhiren's reviewer) said: keep 04, 24, 26; keep with cleanup 06, 08, 19;
   replace 12, 22, 25, 27. Verified true:
   - PHOTO-22: room cards are bound to detail shots (Warehouse Loft to `property_shoot_14.jpg`, a stair-rail detail;
     Reef to a staircase; Hull to a breakfast counter). Not an engineered trap.
   - PHOTO-12: one A4 page must carry 14 photographed products plus full shelf-card fields. Not credible.
   - PHOTO-25: a car photo cannot prove an almost invisible protective film was applied.
   - PHOTO-27: confusing source set for an ops reviewer (packshots disagree, lifestyle refs unusable by design).
3. **Replacement vetting** (one agent per two candidates, read-only, looked at every bound image). Six lenses:
   1. record-to-image mismatch (or "same subject" images showing different subjects);
   2. feasibility (content fits the format);
   3. verifiability (claims the assets can show; nothing requested that was not supplied);
   4. verifier hygiene (no human check on one output that judges all files or other outputs);
   5. unplanned contradictions an ops reviewer would read as authoring errors (`defect_engineered` items are fine);
   6. real-world brand marks in inputs.

   Results:
   | Candidate | Verdict | Reason |
   |---|---|---|
   | PHOTO-03 | Reject | Listing hero photo shows house number 27; listing is 14 Ridgeway Lane. Not a planned trap. |
   | PHOTO-05 | Reject | "Street elevation" and "canal frontage" are visibly different buildings; Providence brand with UK scenery. |
   | PHOTO-14 | Reject | Two finish records contradict their photos (needs input CSV edits). |
   | PHOTO-15 | Reject | CSV colourways contradict 3 of 9 packshots. |
   | PHOTO-18 | Reject | "One couple" story shows several different couples. |
   | PHOTO-21 | Reject | Two CSV-bound photos do not show the named piece; pound prices on a photographed card vs dollar drop. |
   | PHOTO-23 | Reject | 11 of 12 CSV image bindings wrong; dollar prices for a Sheffield works. |
   | VECTOR-02 | Reject | The two "same mark" sources show two different monograms. |
   | PHOTO-10 | **Keep after fix** | Size pin added (placements note said 1600x2000 JPEG; register says 1440x1800 PNG). |
   | PHOTO-20 | **Keep after fix** | Size pin (copy said square; register 4:5) + one cross-output check retired. |
   | PHOTO-28 | **Keep after fix** | Removed a request for "licensed movement imagery" that nobody supplied. |
   | LAYOUT-15 | **Keep after fix** | r015/H008 tightened (no stock photo may stand in for a real producer). The missing headshot is an engineered trap ("she cannot ship until raised with the client"); left unannounced on purpose. |

   **Lesson:** most PHOTO tasks have source-asset authoring flaws that are NOT planned traps. Vet with these lenses
   before choosing tasks for any study.

## Fixes applied for the pilot (commits `9290297`, `7a8a137`)

- Retired human checks that judged delivery of every file from one output: PHOTO-06 (2), PHOTO-08, PHOTO-19, PHOTO-20.
  Auto checks already confirm file presence, so K1_Q4 now shows "Answered by the automatic layer".
- PHOTO-04: brochure rates pinned to `rates_2027.csv` (the hero line already was).
- PHOTO-19: the four host rows (Session = Host) relabelled "Summit host card - <name>" (filenames unchanged).
- PHOTO-24: last season's certificate stated as a visual reference only; current type rules govern. (Its planned
  trap is a text-conversion defect, so this does not give anything away.)
- PHOTO-20, PHOTO-10: register sizes pinned in the brief.
- PHOTO-28: "prepared alongside suitable licensed movement imagery" became "prepared"; evidence quotes updated.
- LAYOUT-15: r015/H008 rewritten to match `compliance_note.txt`.

Afterwards (2026-09-29/30, separate commits) the pilot pages were built and the ten briefs made client-facing, with
typography synchronized; see `VERSIONS.md`.

## Completed runs

Only PHOTO-04 and PHOTO-13 have executed runs with real output files (`docs/gatsby-v7/runs/<ID>/`). The other 98 tasks
are definitions plus verifiers only. PHOTO-04's run predates the V7 brief pins and has no files for any deliverable
added later.
