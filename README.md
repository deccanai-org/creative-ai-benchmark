# Creative AI Benchmark (StudioBench)

> **Picking this up in a new session? Read [`CLAUDE.md`](CLAUDE.md) first**, then `context/` (current state, versions,
> the 10-task pilot, expert feedback and plan, open work). The sections below date from 2026-09-17.

A benchmark for **professional creative work done by AI agents** — 100 real freelance
design tasks, sourced verbatim from Upwork & Freelancer.com briefs, executed with real
professional tools (Adobe connectors) across long, multi-step workflows. Unlike
generation-quality benchmarks, StudioBench measures whether an agent can *do the job a
client would pay for*, and compares it against a **human-professional baseline**.

- **100 tasks**, median **20 tool calls** each, 99/100 long-horizon (≥16 calls, ≥6 distinct tools).
- **8 operation families** across Photo/Image, Vector/Print, Layout/Data, and Motion/Audio.
- Fictional brands throughout (no real trademarks / no memorization leakage).
- Multi-layer QC: per-asset acceptance panels, realism audit, cross-asset **brand-kit consistency**.

## Repository layout

| Path | What's in it |
|------|--------------|
| `complex_benchmark/adobe_only/specs/` | the 100 task specs (`AO-*.json`): brief, inputs, deliverables, full connector workflow, difficulty rationale |
| `asset_pipeline/` | asset **generation + QC** pipeline — model adapters, best-of-N generation, verify/realism/consistency audits, brand-kit conditioning, dashboards |
| `input_assets/` | per-task **manifests**, prompts, and the HTML dashboards (`index_studiobench.html`, `all_assets.html`, per-task `contact_sheet.html`) |
| `pipeline/` | task ingestion / scraping (Upwork & Freelancer harvest → normalized specs) |
| `*.html`, `*.md` | benchmark design docs, taxonomy, QA reports, and prior Adobe experiments |

## Assets live on GCS, not in git

The ~1.6 GB of **generated media** (images, video, audio) is hosted on GCS buckets, not
committed here — this repo holds the **specs, code, manifests, dashboards, and docs**.
The dashboards reference media by relative path, so their image/video tiles render only
when the `input_assets/**/assets/` media is present locally (pull it from GCS).

## Running the pipeline

```bash
cd asset_pipeline
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt   # if present
cp .env.example .env    # then add your own GEMINI/OPENAI/ANTHROPIC/FAL keys
./.venv/bin/python build_dashboard.py     # rebuild the HTML dashboards from on-disk assets
```

## Live reports (GitHub Pages)

The self-contained ops reports live in **`docs/`** and are served by GitHub Pages, so the
team always sees the latest pushed version at a stable URL — no re-sharing files.

- `docs/index.html` — landing page linking the reports
- `docs/Task_Tags_v3_Table.html` — per-task tags + price table
- `docs/Taxonomy_Distribution.html` — distribution by family / modality / vertical / difficulty
- `docs/Quality_QA_Report.html` — per-task QA report

**To refresh the live site:** run `./publish_docs.sh` (syncs the reports into `docs/`) then
`git push`. Pages redeploys automatically.

**One-time enable** (repo owner, in the GitHub UI): **Settings → Pages → Source: “Deploy from
a branch” → `main` / `/docs` → Save.** Site publishes at
`https://deccanai-org.github.io/creative-ai-benchmark/`.

> Note: this repo is **private**. GitHub Pages on a private repo requires **GitHub Pro/Team/
> Enterprise** (Pages is unavailable on Free private repos). Pages serves only the `docs/`
> folder — the clean reports, no secrets or raw scraped data — so on Pro the site is public
> but exposes only those reports. Alternatives: mirror `docs/` to a separate **public**
> repo's Pages (keeps this repo private), or host `docs/` on GCS/Netlify.

## Secrets

No credentials are committed. `asset_pipeline/.env` and `pipeline/.env` are gitignored —
supply your own API keys locally.
