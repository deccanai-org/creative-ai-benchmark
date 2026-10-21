#!/usr/bin/env python3
"""Renderer edits to docs/gatsby-v7/index.html (item B10, 2026-10-21). Idempotent.

1. Human verifiers tab: when only automatic checks answer a rubric question, show a one-line pointer to the
   Auto verifiers tab instead of embedding the auto-check list (reviewers said the sections looked merged).
2. Map the new automatic operations to rubric questions.
"""
from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / 'docs/gatsby-v7/index.html'
OLD_BLOCK = ("if(ac.length){autoCovered++;body+=`<div class=\"k-auto\"><strong>Answered by the automatic layer.</strong> ${ac.length} automatic check${ac.length>1?'s':''} on this task answer this question, so no separate human judgement is required here. The exact checks are listed below.</div>`+`<details class=\"k-autolist\"${ac.length<=6?' open':''}><summary>${ac.length} automatic check${ac.length>1?'s':''} answering ${esc(kShort(q.id))}</summary><div class=\"verifier-table\">${checkRows(ac)}</div></details>`;")
NEW_BLOCK = ("if(ac.length){autoCovered++;body+=`<div class=\"k-auto\"><strong>Answered by automatic checks.</strong> ${ac.length} automatic check${ac.length>1?'s':''} on this task answer this question, so annotators do not rate it here. They are listed on the Auto verifiers tab.</div>`;")
OLD_MAP = "non_silent_audio:'K1_Q3',moving_picture:'K1_Q3'};"
NEW_MAP = "non_silent_audio:'K1_Q3',moving_picture:'K1_Q3',icc_profile:'K1_Q2',pdf_fonts_embedded:'K1_Q2',pdf_output_intent:'K1_Q2',pdf_no_cmyk:'K1_Q2',pdf_text_style:'K2_Q3'};"


def main():
    html = PAGE.read_text()
    for old, new in ((OLD_BLOCK, NEW_BLOCK), (OLD_MAP, NEW_MAP)):
        if new in html:
            continue
        assert html.count(old) == 1, old[:60]
        html = html.replace(old, new)
    PAGE.write_text(html)
    print('index.html renderer edits applied')


if __name__ == '__main__':
    main()
