#!/usr/bin/env python3
"""Build annotation-pilot-v2: the 13 pilot tasks with their human checks grouped into shared rules.

A rule is one sentence template. Each of its rows is one original human check: the row's deliverable and values
fill the template back to that check's exact wording, and the row keeps the check's ID and its own Yes / No answer.
Checks share a rule only when their wording outside the varying names and values, checking method, method-note
wording, scoring dimension and answer format all match. So a required check never merges with an "if it appears"
one, a critical-failure check never merges with an ordinary one, and different measurements stay apart.
TASK_SPEC.json is read, never written; scoring, coverage and the auto checker are unaffected.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from build_v7_annotation_pilot import (CSS, DOWNLOAD_SCRIPT, ROOT, TASK_IDS, TASKS, esc, font_css, render_assets,
                                       render_brand, render_outputs)

OUT = ROOT / 'docs/gatsby-v7/annotation-pilot-v2'
REVISION = 'pilot13_v2_grouping_2026_10_27'
EXT = r'(?:jpe?g|png|svg|pdf|mp4|mov|webm|csv|txt|icc|wav|mp3|m4a|ttf|otf|json|zip)'
# Capitalised words that carry a check's logic. They always stay literal, so a rule can never hide
# "If", "No" or "Only" inside a per-row value.
LOGIC_WORDS = {
    'If', 'Any', 'All', 'Every', 'Each', 'No', 'None', 'Not', 'Never', 'Only', 'The', 'A', 'An', 'Where', 'When',
    'Whenever', 'Wherever', 'Yes', 'Both', 'Neither', 'Either', 'This', 'That', 'These', 'Those', 'It', 'Its',
    'There', 'At', 'In', 'On', 'With', 'Without', 'Compared', 'Apart', 'Except', 'For', 'From', 'To', 'And', 'Or',
    'Of', 'Use', 'Answer',
}
VALUE_KINDS = {'Q', 'HEX', 'FILE', 'ENT', 'NUM', 'CAP'}
HEX = re.compile(r'#[0-9A-Fa-f]{6}\b')
CONDITIONAL = re.compile(r'(If|Any|Where|Wherever|When|Whenever)\b')
TYPE_WORDS = re.compile(r'(?i)\b(?:set in|typefaces?|fonts?|tracking|leading|baselines?|kerning|cap height|characters|'
                        r'small caps|caps|italic|lining|tabular|figures|numerals|line length|point size|'
                        r'\d+(?:\.\d+)?\s?(?:pt|px))\b')
K_ORDER = ['K1_Q1', 'K1_Q2', 'K1_Q3', 'K1_Q5', 'K2_Q1', 'K2_Q2', 'K2_Q3', 'K2_Q4', 'K5_Q1', 'K5_Q2']
BRAND_PARTS = {'colour': 'colour', 'type': 'typography', 'other': 'other brand rules'}
# Which K question each automatic assertion answers: the AUTO2K map of the V7 page (docs/gatsby-v7/index.html).
AUTO2K = {
    'file_exists': 'K1_Q4', 'decodable': 'K1_Q2', 'width': 'K1_Q2', 'height': 'K1_Q2', 'long_edge': 'K1_Q2', 'pages': 'K1_Q2',
    'trim_width_mm': 'K1_Q2', 'trim_height_mm': 'K1_Q2', 'duration_range': 'K1_Q2', 'video_codec': 'K1_Q2',
    'pixel_format': 'K1_Q2', 'frame_rate': 'K1_Q2', 'pdf_text_contains': 'K1_Q1', 'pdf_page_matches_output': 'K1_Q1',
    'no_raster_image': 'K1_Q3', 'closed_paths': 'K1_Q3', 'transparent_background': 'K1_Q3', 'audio_stream': 'K1_Q3',
    'non_silent_audio': 'K1_Q3', 'moving_picture': 'K1_Q3', 'icc_profile': 'K1_Q2', 'pdf_fonts_embedded': 'K1_Q2',
    'pdf_output_intent': 'K1_Q2', 'pdf_no_cmyk': 'K1_Q2', 'pdf_text_style': 'K2_Q3',
}


def k_catalog() -> list[dict]:
    """K1, K2 and K5 with their questions, read from the V7 page so both sites use the same wording."""
    page = (ROOT / 'docs/gatsby-v7/index.html').read_text(encoding='utf-8')
    catalog, _ = json.JSONDecoder().raw_decode(page, page.index('"kCatalog":') + len('"kCatalog":'))
    capabilities = {c['id']: c for c in catalog['capabilities']}
    chosen = [capabilities[k] for k in ('K1', 'K2', 'K5')]
    missing = set(K_ORDER) - {q['id'] for c in chosen for q in c['questions']}
    if missing:
        raise ValueError(f'K questions missing from the V7 catalog: {sorted(missing)}')
    return chosen


def k_short(k_id: str) -> str:
    """K1_Q1 -> K1 Q1, as the V7 page writes it."""
    head, *rest = k_id.split('_')
    return f"{head} {'.'.join(rest)}" if rest else k_id


def task_entities(spec: dict) -> list[str]:
    """Names that vary by deliverable: the part after ' - ' in each deliverable name, and its source-record values."""
    found = set()
    for output in spec['deliverables']:
        name = output.get('name') or ''
        if ' - ' in name:
            found.add(name.rsplit(' - ', 1)[1].strip())
        for value in ((output.get('source_record') or {}).get('values') or {}).values():
            if isinstance(value, str):
                value = value.strip()
                if (3 <= len(value) <= 60 and value[:1].isupper() and value not in LOGIC_WORDS
                        and not re.search(r'[“”#]', value)):
                    found.add(value)
    return sorted(found, key=lambda e: (-len(e), e))


def task_pattern(entities: list[str]) -> re.Pattern:
    parts = [('Q', r'“[^”]*”'), ('HEX', r'#[0-9A-Fa-f]{6}\b'), ('FILE', rf'[\w-]+(?:\.[\w-]+)*\.{EXT}\b')]
    if entities:
        parts.append(('ENT', r'(?<![\w-])(?:' + '|'.join(map(re.escape, entities)) + r')(?![\w-])'))
    parts += [('NUM', r'[$€£]?\d+(?:[.,:]\d+)*'), ('CAP', r"[A-Z][\w&'’-]*(?: (?:[A-Z][\w&'’-]*|&))*"),
              ('WORD', r"[A-Za-z]+(?:['’][A-Za-z]+)*"), ('WS', r'\s+'), ('P', r'.')]
    return re.compile('|'.join(f'(?P<{kind}>{rx})' for kind, rx in parts), re.S)


def own_reference(check: dict) -> str | None:
    """How a check names its own deliverable: “name” (file), or the file alone."""
    full = f"“{check['artifact_name']}” ({check['artifact_file']})"
    if full in check['check']:
        return full
    return check['artifact_file'] if check['artifact_file'] in check['check'] else None


def tokenize(text: str, own: str | None, pattern: re.Pattern) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    for index, piece in enumerate(text.split(own) if own else [text]):
        if index:
            tokens.append(('D', own))
        for match in pattern.finditer(piece):
            kind, value = match.lastgroup, match.group()
            if kind == 'CAP':
                before = ''.join(v for _, v in tokens).rstrip()
                first = value.split(' ')[0]
                # Sentence openers and logic words are wording, not values. Mid-sentence, a capitalised
                # "The" opening a longer run starts a name ("The Blue Hour").
                if not before or before[-1] in '.;:!?' or (
                        first in LOGIC_WORDS and not (first in ('The', 'A', 'An') and ' ' in value)):
                    tokens += [('WS' if part.isspace() else 'WORD', part) for part in re.findall(r'\s+|\S+', value)]
                    continue
            tokens.append((kind, value))
    merged: list[tuple[str, str]] = []
    for kind, value in tokens:
        # A varying a / an belongs to the value it introduces: "a Spring", "an Autumn".
        if kind in ('ENT', 'CAP', 'NUM') and len(merged) >= 2 and merged[-1][0] == 'WS' \
                and merged[-2] in (('WORD', 'a'), ('WORD', 'an')):
            value = merged[-2][1] + merged[-1][1] + value
            del merged[-2:]
        merged.append((kind, value))
    if ''.join(v for _, v in merged) != text:
        raise ValueError(f'Tokenizer lost text: {text}')
    return merged


def skeleton(tokens: list[tuple[str, str]]) -> tuple:
    return tuple(kind if kind in VALUE_KINDS or kind == 'D' else (kind, value) for kind, value in tokens)


def varying(members: list[dict], field: str) -> list[int]:
    first = members[0][field]
    return [p for p, (kind, _) in enumerate(first)
            if kind in VALUE_KINDS and len({m[field][p][1] for m in members}) > 1]


def split_rule(members: list[dict]) -> list[list[dict]]:
    """If one value decides every other varying value (two palette rules sharing a sentence shape), give each its own rule."""
    positions = varying(members, 'tokens')
    if len(positions) >= 2:
        for p in positions:
            parts = defaultdict(list)
            for m in members:
                parts[m['tokens'][p][1]].append(m)
            if 2 <= len(parts) <= 4 and min(map(len, parts.values())) >= 2 and all(
                    len({m['tokens'][q][1] for m in part}) == 1 for part in parts.values() for q in positions if q != p):
                return [rule for part in parts.values() for rule in split_rule(part)]
    return [members]


def template(members: list[dict], field: str, start: int) -> tuple[list[dict], dict[int, int], int]:
    """Constant text stays text; the deliverable and each varying value become numbered placeholders."""
    segments: list[dict] = []
    slots: dict[int, int] = {}
    number = start
    for p, (kind, value) in enumerate(members[0][field]):
        if kind == 'D':
            segments.append({'deliverable': True})
        elif kind in VALUE_KINDS and len({m[field][p][1] for m in members}) > 1:
            number += 1
            slots[p] = number
            segments.append({'slot': number})
        elif segments and 'text' in segments[-1]:
            segments[-1]['text'] += value
        else:
            segments.append({'text': value})
    return segments, slots, number


def fill(segments: list[dict], values: dict, reference: str | None) -> str:
    return ''.join(s['text'] if 'text' in s else reference if 'deliverable' in s else values[str(s['slot'])]
                   for s in segments)


def unquote(value: str) -> str:
    return value[1:-1] if value.startswith('“') and value.endswith('”') else value


def slot_label(rows: list[dict], number: int, segments: list[dict], outputs: dict) -> str:
    """A column name when the data says what the value is; otherwise just the number."""
    key = str(number)
    record_keys = None
    for row in rows:
        record = (outputs[row['output_id']].get('source_record') or {}).get('values') or {}
        keys = {k for k, v in record.items() if isinstance(v, (str, int, float)) and str(v) == unquote(row['values'][key])}
        record_keys = keys if record_keys is None else record_keys & keys
    if record_keys:
        return sorted(record_keys)[0].replace('_', ' ')
    fields = {row.get('expected_field') for row in rows
              if row.get('expected_value') is not None and str(row['expected_value']) == unquote(row['values'][key])}
    if len(fields) == 1 and None not in fields and all(row.get('expected_field') for row in rows):
        return fields.pop().replace('_', ' ')
    for i, segment in enumerate(segments):
        if segment.get('slot') == number and i and 'text' in segments[i - 1]:
            word = re.search(r'(\w+)\s$', segments[i - 1]['text'])
            if word and word.group(1).lower() in ('row', 'rows', 'page', 'pages', 'caliber', 'stock'):
                return word.group(1).lower()
    return ''


def references_view(check: dict) -> dict:
    """What the V7 page shows under Reference: the source-file links and the evidence note."""
    refs = [{'filename': a['filename'], 'url': a['url']} for a in check.get('reference_assets') or []]
    note = str(check.get('evidence_reference') or '').split('; approved ')[0]
    if note == '; '.join(a['filename'] for a in refs):
        note = ''
    return {'assets': refs, 'note': note}


def brand_part(texts: list[str], brand: dict) -> str:
    """Brand rules split by what they name: a palette colour, else a typeface or type setting, else neither."""
    blob = ' '.join(texts)
    palette = [p['name'] for p in brand['palette']]
    if HEX.search(blob) or re.search(r'(?i)\bcolou?rs?\b', blob) or any(
            re.search(rf'(?<![\w-]){re.escape(name)}(?![\w-])', blob) for name in palette):
        return 'colour'
    families = {f['family'] for f in brand.get('font_files', [])}
    families |= {row.get('family', '') for row in brand.get('type_system', {}).get('scale', [])}
    if TYPE_WORDS.search(blob) or any(f and re.search(rf'(?<![\w-]){re.escape(f)}(?![\w-])', blob) for f in families):
        return 'type'
    return 'other'


def scope_text(output_ids: set, spec: dict) -> str:
    names = {o['output_id']: o['name'] for o in spec['deliverables']}
    parts, placed = [], set()
    for group in spec['deliverable_groups']:
        members = group['outputs']
        covered = [o for o in members if o in output_ids]
        placed.update(members)
        if not covered:
            continue
        short = lambda o: names[o].rsplit(' - ', 1)[1] if names[o].startswith(group['name'] + ' - ') else names[o]
        if len(members) == 1:
            parts.append(group['name'])
        elif len(covered) == len(members):
            parts.append(f"{group['name']}: all {len(members)}")
        elif len(covered) <= 3:
            parts.append(f"{group['name']}: {len(covered)} of {len(members)} ({', '.join(map(short, covered))})")
        else:
            missing = [o for o in members if o not in output_ids]
            note = f" (all except {', '.join(map(short, missing))})" if len(missing) <= 3 else ''
            parts.append(f"{group['name']}: {len(covered)} of {len(members)}{note}")
    if output_ids - placed:
        raise ValueError(f"Deliverables outside every deliverable group: {sorted(output_ids - placed)}")
    return ' · '.join(parts)


def build_rules(spec: dict) -> list[dict]:
    pattern = task_pattern(task_entities(spec))
    outputs = {o['output_id']: o for o in spec['deliverables']}
    order = {o['output_id']: i for i, o in enumerate(spec['deliverables'])}
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for position, check in enumerate(spec['verifiers_human']):
        if check['k_id'] not in K_ORDER:
            raise ValueError(f"Unknown scoring dimension {check['k_id']}: {check['check_id']}")
        own = own_reference(check)
        member = {'check': check, 'own': own, 'position': position,
                  'tokens': tokenize(check['check'], own, pattern), 'note': tokenize(check['method_note'], own, pattern)}
        key = (skeleton(member['tokens']), check['method'], skeleton(member['note']), check['k_id'],
               check['answer_type'], check['pass_answer'], tuple(check['allowed_answers']))
        grouped[key].append(member)
    rules = []
    for members in grouped.values():
        for part in split_rule(members):
            part.sort(key=lambda m: (order[m['check']['output_id']], m['position']))
            segments, check_slots, last = template(part, 'tokens', 0)
            note_segments, note_slots, _ = template(part, 'note', last)
            rows = []
            for m in part:
                c = m['check']
                values = {str(n): m['tokens'][p][1] for p, n in check_slots.items()}
                values.update({str(n): m['note'][p][1] for p, n in note_slots.items()})
                rows.append({'check_id': c['check_id'], 'output_id': c['output_id'],
                             'deliverable': outputs[c['output_id']]['name'], 'file': c['artifact_file'],
                             'deliverable_ref': m['own'], 'values': values, 'reference': references_view(c),
                             'check': c['check'], 'expected_value': c.get('expected_value'),
                             'expected_field': c.get('expected_field')})
            for row, m in zip(rows, part):
                if fill(segments, row['values'], row['deliverable_ref']) != m['check']['check'] or \
                        fill(note_segments, row['values'], row['deliverable_ref']) != m['check']['method_note']:
                    raise ValueError(f"Rule does not rebuild {m['check']['check_id']}")
            first = part[0]['check']
            labels = {str(n): slot_label(rows, n, segments if n in check_slots.values() else note_segments, outputs)
                      for n in sorted([*check_slots.values(), *note_slots.values()])}
            shared = all(r['reference'] == rows[0]['reference'] for r in rows)
            k_part = brand_part([r['check'] for r in rows], spec['brand_identity']) if first['k_id'] == 'K2_Q3' else ''
            rules.append({
                'k_id': first['k_id'], 'k_label': first['k_label'], 'brand_part': k_part, 'method': first['method'],
                'critical': first['k_id'] == 'K1_Q5', 'template': segments, 'note_template': note_segments,
                'slot_labels': labels, 'conditional': bool(CONDITIONAL.match(fill(segments, rows[0]['values'], 'X'))),
                'scope': scope_text({r['output_id'] for r in rows}, spec),
                'shared_reference': rows[0]['reference'] if shared else None, 'rows': rows,
                '_first': min(m['position'] for m in part),
            })
    section_key = lambda r: (K_ORDER.index(r['k_id']), list(BRAND_PARTS).index(r['brand_part']) if r['brand_part'] else 0)
    rules.sort(key=lambda r: (section_key(r), r['_first']))
    for number, rule in enumerate(rules, 1):
        rule['rule_id'] = f'R{number:03d}'
        rule['section'] = (f"{k_short(rule['k_id'])} · {rule['k_label']}"
                           + (f": {BRAND_PARTS[rule['brand_part']]}" if rule['brand_part'] else ''))
        del rule['_first']
    return rules


def template_text(segments: list[dict], labels: dict) -> str:
    """Plain-text form for exports: [deliverable] and [n] (or [n: label]) placeholders."""
    out = []
    for s in segments:
        if 'text' in s:
            out.append(s['text'])
        elif 'deliverable' in s:
            out.append('[deliverable]')
        else:
            label = labels.get(str(s['slot']))
            out.append(f"[{s['slot']}: {label}]" if label else f"[{s['slot']}]")
    return ''.join(out)


def template_html(segments: list[dict], labels: dict) -> str:
    out = []
    for s in segments:
        if 'text' in s:
            out.append(esc(s['text']))
        elif 'deliverable' in s:
            out.append('<span class="ph ph-d">deliverable</span>')
        else:
            label = labels.get(str(s['slot']))
            out.append(f'<span class="ph ph-n" title="{esc(label or "Value")} for each row">{s["slot"]}</span>')
    return ''.join(out)


def filled_html(segments: list[dict], row: dict) -> str:
    """One row's sentence, with the parts that came from the row highlighted."""
    out = []
    for s in segments:
        if 'text' in s:
            out.append(esc(s['text']))
        elif 'deliverable' in s:
            out.append(f'<mark class="mk-d">{esc(row["deliverable_ref"])}</mark>')
        else:
            out.append(f'<mark class="mk-n">{esc(row["values"][str(s["slot"])])}</mark>')
    return ''.join(out)


def example_html(rules: list[dict], task_id: str, link: bool = False) -> str:
    """A worked example from the task's own rules: the rule, one of its rows, and the sentence they make."""
    with_values = [r for r in rules if len(r['rows']) > 1 and any('slot' in s for s in r['template'])]
    plain = [r for r in rules if len(r['rows']) > 1 and not any('slot' in s for s in r['template'])]
    parts = []
    for rule, intro in ((with_values[0] if with_values else None, 'A rule with numbered boxes'),
                        (plain[0] if plain else None, 'A rule without numbered boxes: each row is the same sentence about a different file')):
        if not rule:
            continue
        row = rule['rows'][0]
        values = ' · '.join(f'<span class="ph ph-n">{n}</span> {esc(v)}' for n, v in sorted(row['values'].items(), key=lambda kv: int(kv[0])))
        name = row['deliverable'].rsplit(' - ', 1)[1] if ' - ' in row['deliverable'] else row['deliverable']
        rid = f'<a href="{task_id}-verifiers.html#{rule["rule_id"]}">{rule["rule_id"]}</a>' if link else rule['rule_id']
        parts.append(
            f'<div class="example"><p class="ex-h">{esc(intro)} ({esc(task_id)} {rid}, first of its {len(rule["rows"])} rows)</p>'
            f'<p><span>Rule</span><span>{template_html(rule["template"], rule["slot_labels"])}</span></p>'
            f'<p><span>Row</span><span><strong>{esc(name)}</strong> <code>{esc(row["file"])}</code>'
            f'{" · " + values if values else ""}</span></p>'
            f'<p><span>Reads as</span><span>{filled_html(rule["template"], row)}</span></p>'
            f'<p><span>Answer</span><span>Yes or No for this row. The next row is the same rule for the next file.</span></p></div>')
    return ''.join(parts)


HOW_TO_READ = (
    '<ol><li><strong>Read the rule once.</strong> It is the same check for every row in its table.</li>'
    '<li><strong>Each row is one original check on one deliverable.</strong> Read the rule with that row\'s file in place of '
    '<span class="ph ph-d">deliverable</span>, and that row\'s values in place of the numbered boxes '
    '<span class="ph ph-n">1</span> <span class="ph ph-n">2</span>.</li>'
    '<li><strong>Answer Yes or No for each row</strong>, as before. Every row keeps its own check ID.</li></ol>')


def reference_html(ref: dict) -> str:
    links = '<br>'.join(f'<a href="{esc(a["url"])}" target="_blank" rel="noopener">{esc(a["filename"])}</a>' for a in ref['assets'])
    if len(ref['assets']) > 2:
        links = f'<details><summary>Source files ({len(ref["assets"])})</summary>{links}</details>'
    note = f'<small>{esc(ref["note"])}</small>' if ref['note'] else ''
    return links + note


V2_CSS = """
[hidden]{display:none!important}
.v2nav{font-size:13px;color:#5b6760;margin:0 0 6px}.v2nav a{color:#176348}
.intro{max-width:92ch;color:#303b35}.intro p{margin:0 0 10px}
.tools{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid #dce3df;padding:10px 0;margin:18px 0 6px;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;font-size:13px}
.tools label{display:flex;gap:6px;align-items:center}.tools select,.tools input[type=search]{font:inherit;padding:5px 8px;border:1px solid #c9d3cd;border-radius:5px;max-width:100%}
.tools input[type=search]{width:min(260px,100%)}#shown{color:#5b6760}
.kcap{margin:26px 0;border:1px solid #dce3df;border-radius:8px;padding:18px 20px}.kcap>h2{margin:0 0 4px;font-size:19px}
.k-measures{color:#5b6760;font-size:13px;margin:0 0 10px}.k-coverage{color:#5b6760;font-size:13px;margin:6px 0 0}
.kq{margin:16px 0;padding:12px 14px;border-left:3px solid #1e7059;background:#fafbfa;scroll-margin-top:96px}
.kq h3{margin:0 0 2px;font-size:15px}.k-qtext{margin:0 0 10px;color:#333}
.k-count{float:right;color:#5b6760;font-weight:400;font-size:12px}
.objective{display:inline-block;margin-left:8px;padding:1px 8px;border-radius:10px;background:#f6b26b;color:#4a2c00;font-size:11px;font-weight:700;vertical-align:middle}
.k-empty{color:#5b6760;font-style:italic;font-size:13px;margin:0}.k-auto{font-size:13px;color:#3f4b45;background:#eef4f0;border-radius:6px;padding:8px 10px}
.kpart>h4{font-size:13.5px;margin:16px 0 8px;color:#3f4b45}
.howto{border:1px solid #cfe0d6;background:#f6faf7;border-radius:8px;padding:14px 18px;margin:16px 0 8px;max-width:118ch}
.howto>h2{font-size:17px;margin:0 0 8px}.howto ol{margin:0 0 6px;padding-left:20px}.howto li{margin:0 0 5px}
.example{border-top:1px solid #dce3df;padding-top:10px;margin-top:10px;font-size:14px}
.example p{margin:0 0 6px;display:grid;grid-template-columns:78px minmax(0,1fr);gap:10px}.example p.ex-h{display:block;font-weight:600;color:#3f4b45}
.example p>span:first-child{font-weight:700;color:#5b6760;font-size:11.5px;text-transform:uppercase;padding-top:3px}
.example code{font-size:12px;color:#5b6760}
mark.mk-d{background:#e3efe8;color:#1d5a42;padding:0 2px;border-radius:3px}mark.mk-n{background:#fff0c7;color:#5f4300;padding:0 2px;border-radius:3px}
.b-k{background:#e3efe8;color:#1d5a42;font-weight:600}
.rule{border:1px solid #dce3df;border-radius:6px;padding:13px 15px 6px;margin:0 0 12px;background:#fff;scroll-margin-top:96px}
.rule-head{display:flex;flex-wrap:wrap;gap:6px 8px;align-items:center;font-size:12px;margin-bottom:8px}
.rid{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-weight:700;color:#202724}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;background:#eef1ef;color:#4f5c56}
.b-measure{background:#e6eef8;color:#1f4a7a}.b-crit{background:#fbe3e1;color:#8a1f17;font-weight:700}.b-cond{background:#fff3d6;color:#6b4a00}
.rule-text{font-size:15px;line-height:1.55;margin:0 0 6px;max-width:100ch}
.ph{display:inline-block;border-radius:4px;padding:0 6px;font-size:.86em;line-height:1.5;vertical-align:baseline;font-weight:600}
.ph-d{background:#e3efe8;color:#1d5a42}.ph-n{background:#fff0c7;color:#5f4300;font-variant-numeric:tabular-nums;min-width:1.6em;text-align:center}
.rule-note{font-size:13px;color:#46534c;margin:0 0 6px;max-width:110ch}.rule-scope{font-size:12.5px;color:#5b6760;margin:0 0 6px}
.rule-ref{font-size:12.5px;margin:0 0 6px}.rule-ref small{display:block;color:#5b6760}
.rows-wrap{overflow-x:auto;margin:6px 0 8px}.rows{border-collapse:collapse;width:100%;font-size:13px}
.rows th{background:#f4f7f5;text-align:left;font-weight:600;color:#3f4b45;padding:6px 8px;border-bottom:1px solid #dce3df;white-space:nowrap}
.rows td{padding:6px 8px;border-bottom:1px solid #edf0ed;vertical-align:top;overflow-wrap:anywhere}
.rows td.d{min-width:160px}.rows td.v{overflow-wrap:normal;word-break:normal;min-width:5ch}.rows td.d strong{font-weight:600}.rows td.d code{display:block;font-size:11.5px;color:#5b6760}
.rows td.id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;color:#5b6760;white-space:nowrap}
.rows td.ans{white-space:nowrap;color:#3f4b45}.rows td small{display:block;color:#5b6760;font-size:12px;margin-top:2px}.rows th .ph{margin-right:4px}.full{display:none;font-size:12px;color:#46534c;margin-top:4px}
body.show-full .full{display:block}
.summary{border-collapse:collapse;font-size:14px;margin:8px 0 18px}.summary th,.summary td{padding:6px 12px;border-bottom:1px solid #e3e8e4;text-align:left}
.summary td.n,.summary th.n{text-align:right;font-variant-numeric:tabular-nums}
.page ul.rules-list li{margin:0 0 6px}.scroll-x{overflow-x:auto}
.tools label{min-width:0;max-width:100%}.tools select{min-width:0;max-width:min(440px,100%)}
@media(max-width:720px){.rule{padding:12px 12px 4px}.rule-text{font-size:14.5px}
.tools{position:static}.tools label{width:100%}.tools select,.tools input[type=search]{flex:1;min-width:0;width:auto;max-width:none}
.rows-wrap{overflow-x:visible}.rows thead{display:none}.rows,.rows tbody,.rows tr,.rows td{display:block;width:100%}
.rows tr{border-bottom:1px solid #dce3df;padding:8px 0}.rows td{border:0;padding:2px 0;min-width:0}.rows td.d{min-width:0}
.rows td[data-label]::before{content:attr(data-label) ": ";font-weight:600;color:#3f4b45}
.rows td.id,.rows td.ans{display:inline-block;width:auto;margin-right:14px}}
"""

FILTER_SCRIPT = """
<script>
(() => {
  const pick = document.getElementById('deliverable'), query = document.getElementById('query'),
        full = document.getElementById('full'), shown = document.getElementById('shown');
  function apply() {
    const output = pick.value, text = query.value.trim().toLowerCase();
    let rules = 0, rows = 0;
    document.querySelectorAll('.rule').forEach(rule => {
      let visible = 0;
      rule.querySelectorAll('tbody tr').forEach(tr => {
        const keep = !output || tr.dataset.output === output;
        tr.hidden = !keep;
        if (keep) visible++;
      });
      const show = visible > 0 && (!text || rule.textContent.toLowerCase().includes(text));
      rule.hidden = !show;
      if (show) { rules++; rows += visible; }
    });
    const filtering = Boolean(output || text);
    document.querySelectorAll('.kpart').forEach(part => { part.hidden = !part.querySelector('.rule:not([hidden])'); });
    document.querySelectorAll('.kq').forEach(q => {
      q.hidden = q.querySelector('.rule') ? !q.querySelector('.rule:not([hidden])') : filtering;
    });
    document.querySelectorAll('.kcap').forEach(cap => { cap.hidden = !cap.querySelector('.kq:not([hidden])'); });
    shown.textContent = `Showing ${rules} rules and ${rows} checks`;
  }
  pick.addEventListener('change', apply);
  query.addEventListener('input', apply);
  full.addEventListener('change', () => document.body.classList.toggle('show-full', full.checked));
  apply();
})();
</script>
"""


def rule_html(rule: dict) -> str:
    labels = rule['slot_labels']
    badges = [f'<span class="badge b-k" title="{esc(rule["k_label"])}">{esc(k_short(rule["k_id"]))}</span>',
              f'<span class="badge {"b-measure" if rule["method"] == "measure" else ""}">{esc(rule["method"].capitalize())}</span>']
    if rule['critical']:
        badges.append('<span class="badge b-crit">Critical</span>')
    if rule['conditional']:
        badges.append('<span class="badge b-cond">Only if present</span>')
    rows = rule['rows']
    outputs = len({r['output_id'] for r in rows})
    badges.append(f'<span class="badge">{len(rows)} check{"s" if len(rows) != 1 else ""} · '
                  f'{outputs} deliverable{"s" if outputs != 1 else ""}</span>')
    numbers = sorted(labels, key=int)
    column = lambda n: f'{n} {labels[n][:1].upper() + labels[n][1:]}'.strip()
    head = ['Deliverable'] + [f'<span class="ph ph-n">{n}</span>{esc(labels[n][:1].upper() + labels[n][1:])}' for n in numbers]
    if rule['shared_reference'] is None:
        head.append('Reference')
    head += ['Check', 'Answer']
    body = []
    for r in rows:
        name = r['deliverable']
        short = name.rsplit(' - ', 1)[1] if ' - ' in name else name
        cells = [f'<td class="d"><strong>{esc(short)}</strong><code>{esc(r["file"])}</code>'
                 f'<div class="full">{esc(r["check"])}</div></td>']
        cells += [f'<td class="v" data-label="{esc(column(n))}">{esc(r["values"][n])}</td>' for n in numbers]
        if rule['shared_reference'] is None:
            cells.append(f'<td data-label="Reference">{reference_html(r["reference"])}</td>')
        cells.append(f'<td class="id" data-label="Check" data-check="{esc(r["check_id"])}" title="{esc(r["check_id"])}">'
                     f'{esc(r["check_id"].split("/")[-1])}</td>')
        cells.append('<td class="ans" data-label="Answer">Yes / No</td>')
        body.append(f'<tr data-output="{esc(r["output_id"])}">{"".join(cells)}</tr>')
    shared = rule['shared_reference']
    ref = ''
    if shared and (shared['assets'] or shared['note']):
        ref = f'<div class="rule-ref"><strong>Reference:</strong> {reference_html(shared)}</div>'
    return (f'<article class="rule" id="{rule["rule_id"]}"><div class="rule-head"><span class="rid">{rule["rule_id"]}</span>'
            f'{"".join(badges)}</div>'
            f'<p class="rule-text">{template_html(rule["template"], labels)}</p>'
            f'<p class="rule-note"><strong>{esc(rule["method"].capitalize())}:</strong> {template_html(rule["note_template"], labels)}</p>'
            f'{ref}<p class="rule-scope"><strong>Applies to:</strong> {esc(rule["scope"])}</p>'
            f'<div class="rows-wrap"><table class="rows"><thead><tr>{"".join(f"<th>{h}</th>" for h in head)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></article>')


def nav(task_id: str, here: str) -> str:
    links = [('index.html', 'All pilot tasks'), (f'{task_id}.html', 'Brief'), (f'{task_id}-verifiers.html', 'Human verifiers')]
    parts = [esc(label) if href == here else f'<a href="{href}">{esc(label)}</a>' for href, label in links]
    return f'<p class="v2nav">{" · ".join(parts)} · <a href="../index.html#{task_id}/auto">Auto verifiers</a> · ' \
           f'<a href="../index.html#{task_id}/trajectory">Trajectory verifiers</a></p>'


def k_sections(task_id: str, spec: dict, rules: list[dict], catalog: list[dict]) -> tuple[str, str]:
    """The V7 Human verifiers layout: K1, K2, K5, each question with its rules, or a note when code answers it."""
    by_question = defaultdict(list)
    for rule in rules:
        by_question[rule['k_id']].append(rule)
    covered = auto_covered = total = 0
    blocks = []
    for cap in catalog:
        parts = [f'<section class="kcap"><h2>{esc(cap["id"])} · {esc(cap["name"])}</h2>'
                 f'<p class="k-measures">{esc(cap["measures"])} <em>Scored by {esc(cap["scored_by"])}.</em></p>']
        for q in cap['questions']:
            total += 1
            members = by_question.get(q['id'], [])
            checks = sum(len(r['rows']) for r in members)
            count = (f'{len(members)} rule{"s" if len(members) != 1 else ""} · {checks} check{"s" if checks != 1 else ""}'
                     if members else '')
            badge = '<span class="objective" title="Objective question">Objective</span>' if q.get('objective') else ''
            parts.append(f'<div class="kq" id="{esc(q["id"])}"><h3>{esc(k_short(q["id"]))} · {esc(q["label"])}{badge}'
                         f'<span class="k-count">{count}</span></h3><p class="k-qtext">{esc(q["question"])}</p>')
            if members:
                covered += 1
                if q['id'] == 'K2_Q3':
                    for part, title in BRAND_PARTS.items():
                        chosen = [r for r in members if r['brand_part'] == part]
                        if chosen:
                            n = sum(len(r['rows']) for r in chosen)
                            parts.append(f'<div class="kpart"><h4>Brand-system rules: {esc(title)} '
                                         f'({len(chosen)} rule{"s" if len(chosen) != 1 else ""} · {n} check{"s" if n != 1 else ""})</h4>'
                                         + ''.join(rule_html(r) for r in chosen) + '</div>')
                else:
                    parts.extend(rule_html(r) for r in members)
            else:
                auto = [c for c in spec['verifiers_auto'] if AUTO2K.get((c.get('assertion') or {}).get('op')) == q['id']]
                if auto:
                    auto_covered += 1
                    parts.append(f'<div class="k-auto"><strong>Answered by automatic checks.</strong> {len(auto)} automatic '
                                 f'check{"s" if len(auto) != 1 else ""} on this task answer this question, so annotators do not '
                                 f'rate it here. They are listed on the <a href="../index.html#{task_id}/auto">Auto verifiers</a> tab.</div>')
                else:
                    parts.append('<p class="k-empty">No task-specific verifier for this question on this task.</p>')
            parts.append('</div>')
        parts.append('</section>')
        blocks.append(''.join(parts))
    coverage = (f'<p class="k-coverage">{covered + auto_covered} of {total} objective rubric questions are answered for this '
                f'task: {covered} by task-specific human verifiers and {auto_covered} by the automatic layer.</p>')
    return coverage, ''.join(blocks)


def write_verifier_page(task_id: str, spec: dict, rules: list[dict], catalog: list[dict]) -> None:
    checks = sum(len(r['rows']) for r in rules)
    coverage, blocks = k_sections(task_id, spec, rules, catalog)
    options = ''.join(f'<option value="{esc(o["output_id"])}">{esc(o["name"])}</option>' for o in spec['deliverables'])
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(task_id)} · Human verifiers</title><style>{CSS}{V2_CSS}</style></head><body>
<main class="page">
{nav(task_id, f'{task_id}-verifiers.html')}
<header><h1>{esc(spec["task_name"])}: human verifiers</h1></header>
<div class="intro">
<p><strong>{checks} human checks, written as {len(rules)} rules.</strong> The checks and their K questions are the same as on the V7 site; only the layout changed. Checks that say the same thing about different deliverables are written once, as a rule, with one row per check.</p>
</div>
<section class="howto" aria-labelledby="howto-title"><h2 id="howto-title">How to read a rule</h2>{HOW_TO_READ}{example_html(rules, task_id)}
<p class="k-coverage"><span class="badge b-k">K1 Q1</span> is the K question a rule scores. <span class="badge b-cond">Only if present</span>: the rule applies only when that element appears. <span class="badge b-crit">Critical</span>: a critical-failure check. Look or Measure is the checking method, explained under each rule.</p></section>
{coverage}
<div class="tools" role="group" aria-label="Filter rules">
<label>Deliverable <select id="deliverable"><option value="">All {len(spec["deliverables"])} deliverables</option>{options}</select></label>
<label>Search <input id="query" type="search" placeholder="Words in a rule"></label>
<label><input id="full" type="checkbox"> Show the full sentence in every row</label>
<span id="shown" aria-live="polite"></span>
</div>
{blocks}
</main>{FILTER_SCRIPT}<script src="https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5"></script></body></html>
"""
    (OUT / f'{task_id}-verifiers.html').write_text(page, encoding='utf-8')


def write_brief_page(task_id: str, spec: dict, assets: list[dict], outputs: list[dict]) -> None:
    """The v1 brief page, with links to the grouped verifiers. Previews are read from the v1 folder."""
    brand = spec['brand_identity']
    assets_html = render_assets(task_id, assets).replace('src="previews/', 'src="../annotation-pilot/previews/')
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(task_id)} · {esc(spec["task_name"])}</title><style>{CSS}{V2_CSS}\n{font_css(brand)}</style></head><body>
<main class="page">
{nav(task_id, f'{task_id}.html')}
<header><h1>{esc(spec["task_name"])}</h1></header>
<section class="section" aria-labelledby="brief-title"><h2 id="brief-title">Client brief</h2><div class="brief-text">{esc(spec["client_brief"])}</div></section>
<section class="section" aria-labelledby="brand-title"><h2 id="brand-title">Brand identity</h2>{render_brand(brand)}</section>
<section class="section" aria-labelledby="assets-title"><h2 id="assets-title">Source assets ({len(assets)})</h2>{assets_html}</section>
<section class="section" aria-labelledby="outputs-title"><h2 id="outputs-title">Requested deliverables ({len(outputs)})</h2>{render_outputs(outputs, spec["deliverable_groups"])}</section>
</main>{DOWNLOAD_SCRIPT}<script src="https://cdn.jsdelivr.net/npm/@iframe-resizer/child@5"></script></body></html>
"""
    (OUT / f'{task_id}.html').write_text(page, encoding='utf-8')


def export_rule(task_id: str, rule: dict) -> dict:
    return {'rule_id': rule['rule_id'], 'section': rule['section'], 'k_id': rule['k_id'], 'k_label': rule['k_label'],
            'method': rule['method'], 'critical': rule['critical'], 'only_if_present': rule['conditional'],
            'scope': rule['scope'], 'template': rule['template'], 'note_template': rule['note_template'],
            'slot_labels': rule['slot_labels'], 'shared_reference': rule['shared_reference'],
            'rows': [{k: v for k, v in r.items() if v is not None or k == 'deliverable_ref'} for r in rule['rows']]}


def write_index(summary: list[tuple[str, dict, list[dict]]]) -> None:
    example_task, _, example_rules = next(item for item in summary if item[0] == 'PHOTO-19')
    total_checks = sum(len(s['verifiers_human']) for _, s, _ in summary)
    total_rules = sum(len(r) for _, _, r in summary)
    rows = ''.join(
        f'<tr><td><a href="{tid}-verifiers.html">{tid}</a></td><td>{esc(s["task_name"])}</td>'
        f'<td class="n">{len(s["deliverables"])}</td><td class="n">{len(s["verifiers_human"])}</td><td class="n">{len(r)}</td></tr>'
        for tid, s, r in summary)
    items = ''.join(
        f'<li><a href="{tid}.html">{tid} - {esc(s["task_name"])}</a><br><span class="vlinks">'
        f'<a href="{tid}-verifiers.html">Human verifiers ({len(s["verifiers_human"])} checks in {len(r)} rules)</a> · '
        f'<a href="../index.html#{tid}/human">Same checks, one per row (V7 site)</a> · '
        f'<a href="../index.html#{tid}/auto">Auto ({len(s["verifiers_auto"])})</a> · '
        f'<a href="../index.html#{tid}/trajectory">Trajectory</a> · '
        f'<a href="../annotation-pilot/coverage/{tid}.html">Checks per deliverable</a> · '
        f'<a href="groups/{tid}.json">Rules as JSON</a></span></li>'
        for tid, s, r in summary)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pilot task briefs v2</title><style>{CSS}{V2_CSS}.vlinks{{font-size:14px;color:#5b6760}}.page li{{margin:0 0 12px}}</style></head><body>
<main class="page">
<h1>Pilot task briefs, v2: grouped human verifiers</h1>
<div class="intro">
<p>The same 13 pilot tasks and the same {total_checks} human checks as <a href="../annotation-pilot/index.html">v1</a>. What changed is how the checks are shown: checks that say the same thing about different deliverables are written once, as a rule, with one row per check. {total_checks} checks now read as {total_rules} rules.</p>
<p>Each task's verifier page keeps the V7 structure: K1 · Instruction adherence, K2 · Asset utilization and fidelity and K5 · Communication effectiveness, each question with its rules under it.</p>
</div>
<section class="howto" aria-labelledby="howto-title"><h2 id="howto-title">How to read a rule</h2>{HOW_TO_READ}{example_html(example_rules, example_task, link=True)}</section>
<div class="intro">
<p>Nothing was reworded, dropped or merged away:</p>
<ul>
<li>Every row keeps its original check ID and is answered Yes or No on its own, so scoring and coverage do not change.</li>
<li>Names and values that differ between rows (a person, a house, a price, a CSV row) are shown in that row, so each row still says exactly which deliverable gets which value.</li>
<li>Filled in, every row reads word for word as its original check. A test confirms this for all {total_checks} checks and that each check appears exactly once.</li>
<li>Checks share a rule only when they match on wording, checking method (Look or Measure), method instructions, scoring dimension and answer. So "must have" checks never merge with "if it appears" checks, critical-failure checks never merge with ordinary ones, and different measurements stay apart.</li>
</ul>
<p>Under K2 Q3 · Brand-system compliance, rules are split by what they name: a palette colour, a typeface or type setting, or neither. Auto checks are unchanged and still run by code. <a href="../annotation-pilot/measurement-guide.html">Measurement guide and scoring policy</a>.</p>
</div>
<div class="scroll-x"><table class="summary"><thead><tr><th>Task</th><th>Name</th><th class="n">Deliverables</th><th class="n">Human checks</th><th class="n">Rules</th></tr></thead>
<tbody>{rows}<tr><td><strong>Total</strong></td><td></td><td class="n">{sum(len(s["deliverables"]) for _, s, _ in summary)}</td><td class="n"><strong>{total_checks}</strong></td><td class="n"><strong>{total_rules}</strong></td></tr></tbody></table></div>
<h2>Tasks</h2><ul class="rules-list">{items}</ul>
<h2>Downloads</h2>
<ul class="rules-list">
<li><a href="export/grouped_human_rules.csv">grouped_human_rules.csv</a>: one row per rule, with its scope and every check ID it covers.</li>
<li><a href="export/grouped_human_rule_rows.csv">grouped_human_rule_rows.csv</a>: one row per check, with its rule, its values and its original wording.</li>
</ul>
</main></body></html>
"""
    (OUT / 'index.html').write_text(page, encoding='utf-8')


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'groups').mkdir(exist_ok=True)
    (OUT / 'export').mkdir(exist_ok=True)
    summary = []
    catalog = k_catalog()
    rule_rows = [['task_id', 'rule_id', 'section', 'k_id', 'method', 'critical', 'only_if_present', 'scope', 'rule',
                  'method_note', 'check_count', 'deliverable_count', 'check_ids']]
    check_rows = [['task_id', 'rule_id', 'check_id', 'output_id', 'deliverable', 'file', 'values', 'check']]
    for task_id in TASK_IDS:
        folder = TASKS / task_id
        spec = json.loads((folder / 'TASK_SPEC.json').read_text(encoding='utf-8'))
        assets = json.loads((folder / 'ASSET_MANIFEST.json').read_text(encoding='utf-8'))
        outputs = json.loads((folder / 'OUTPUT_REGISTER.json').read_text(encoding='utf-8'))
        bank = {v['check_id']: v['check'] for v in json.loads((folder / 'VERIFIERS.json').read_text(encoding='utf-8'))
                if v['type'] == 'human'}
        if bank != {c['check_id']: c['check'] for c in spec['verifiers_human']}:
            raise ValueError(f'VERIFIERS.json and TASK_SPEC.json disagree on human checks for {task_id}')
        rules = build_rules(spec)
        kept = Counter(r['check_id'] for rule in rules for r in rule['rows'])
        if set(kept) != set(bank) or max(kept.values()) != 1:
            raise ValueError(f'{task_id}: grouping lost or repeated a check')
        write_brief_page(task_id, spec, assets, outputs)
        write_verifier_page(task_id, spec, rules, catalog)
        payload = {'task_id': task_id, 'revision': REVISION, 'source': f'docs/gatsby-v7/tasks/{task_id}/TASK_SPEC.json verifiers_human',
                   'check_count': len(kept), 'rule_count': len(rules), 'rules': [export_rule(task_id, r) for r in rules]}
        (OUT / 'groups' / f'{task_id}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
        for rule in rules:
            labels = rule['slot_labels']
            rule_rows.append([task_id, rule['rule_id'], rule['section'], rule['k_id'], rule['method'],
                              'yes' if rule['critical'] else '', 'yes' if rule['conditional'] else '', rule['scope'],
                              template_text(rule['template'], labels), template_text(rule['note_template'], labels),
                              len(rule['rows']), len({r['output_id'] for r in rule['rows']}),
                              ' '.join(r['check_id'] for r in rule['rows'])])
            for r in rule['rows']:
                values = '; '.join(f"{n}={v}" for n, v in sorted(r['values'].items(), key=lambda kv: int(kv[0])))
                check_rows.append([task_id, rule['rule_id'], r['check_id'], r['output_id'], r['deliverable'], r['file'],
                                   values, r['check']])
        summary.append((task_id, spec, rules))
        singles = sum(1 for r in rules if len(r['rows']) == 1)
        print(f'{task_id}: {len(kept)} human checks -> {len(rules)} rules ({singles} single-check rules)')
    for name, data in (('grouped_human_rules.csv', rule_rows), ('grouped_human_rule_rows.csv', check_rows)):
        with (OUT / 'export' / name).open('w', newline='', encoding='utf-8') as f:
            csv.writer(f, lineterminator='\n').writerows(data)
    write_index(summary)
    print(f'Total: {sum(len(s["verifiers_human"]) for _, s, _ in summary)} checks -> {sum(len(r) for _, _, r in summary)} rules')


if __name__ == '__main__':
    main()
