# Auto verifier runner (copy)

`verify_outputs.py` runs every automatic check (`verifiers_auto[].assertion`) of a task against a folder of
delivered files: `python3 verify_outputs.py --spec TASK_SPEC.json --artifacts <run folder> --out report.json`.
Human checks are reported as `pending_expert_review`; a missing file is never a pass.

The working copy lives outside this repo at `~/Documents/ChatGPT/Adobe_Gpt/benchmark_v4/` (no git history there);
this folder is a published copy so the operations are not lost. Keep the two in sync.

Operations added 2026-10-21 so machine facts are no longer asked of annotators:
`icc_profile` (sRGB colour; untagged counts as sRGB), `pdf_fonts_embedded`, `pdf_output_intent` (e.g. PSO Coated v3),
`pdf_no_cmyk` (screen PDFs), `pdf_text_style` (exact live text set in a family, optional weight and size in pt;
raises "not assessable" when the text is outlined or absent; any occurrence counts, case-insensitive by default). Tests: `python3 -m unittest test_verifiers` (22 pass)
using a Python with Pillow, pypdf, numpy, CairoSVG (see requirements.txt).
