# Auto verifier runner (copy)

`verify_outputs.py` runs every automatic check (`verifiers_auto[].assertion`) of a task against a folder of
delivered files: `python3 verify_outputs.py --spec TASK_SPEC.json --artifacts <run folder> --out report.json`.
Human checks are reported as `pending_expert_review`; a missing file is never a pass.

The working copy lives outside this repo at `~/Documents/ChatGPT/Adobe_Gpt/benchmark_v4/` (no git history there);
this folder is a published copy so the operations are not lost. Keep the two in sync.

Operations added 2026-10-21 so machine facts are no longer asked of annotators:
`icc_profile` (sRGB colour; untagged counts as sRGB), `pdf_fonts_embedded`,
`pdf_output_intent` (requires a /GTS_PDFX intent naming the condition AND an embedded, valid CMYK ICC DestOutputProfile;
a bare label fails), `pdf_no_cmyk` (scans page and nested Form XObject streams, tiling patterns, shadings, XObject and
inline images, transparency groups, annotation appearances and output intents), `pdf_text_style` (exact live text set in a
family, optional weight and size in pt; any occurrence counts, case-insensitive by default; with `leading_pt` and/or
`tracking` it measures baseline-to-baseline leading and median extra glyph advance in thousandths of an em using
pdfminer.six; leading needs text running over two or more lines). Missing or outlined text is "not assessable", never a pass.

Tests: `python3 -m unittest test_verifiers` (24 pass) with Pillow, pypdf, numpy, CairoSVG and pdfminer.six (requirements.txt).
The PSO Coated v3 positive test uses the ECI profile if present on disk and is skipped otherwise.