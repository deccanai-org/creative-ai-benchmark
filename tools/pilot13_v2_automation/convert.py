#!/usr/bin/env python3
"""Turn the automatic v2 rules into exact assertions, one per original check.

A rule converts only when every row yields an unambiguous assertion from the check's own wording (and, where the
check cites a CSV field, the deliverable's source record). Anything else stays with people. Output:
moved/<TASK>.json with each moved check's ID, rule, K question, critical flag, assertion and plain-language test.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import round2  # noqa: E402  (round 2: one handler per rule round 1 could not convert)
import round3  # noqa: E402  (round 3: colour on images, defined roles, measurable judgement rules)
import round4  # noqa: E402  (round 4: the remaining checks code can measure exactly)
import round5  # noqa: E402  (round 5: close calls settled by code; vision-model checks)
TASKS = ROOT / 'docs/gatsby-v7/tasks'
GROUPS = ROOT / 'docs/gatsby-v7/annotation-pilot-v2/groups'
HERE = Path(__file__).resolve().parent
PLAN = HERE / 'automation_plan_step1.json'
OUT = HERE / 'moved'
TASK_IDS = ['PHOTO-04', 'PHOTO-06', 'PHOTO-08', 'PHOTO-10', 'PHOTO-19', 'PHOTO-20', 'PHOTO-24', 'PHOTO-26', 'PHOTO-28',
            'LAYOUT-15', 'LAYOUT-12', 'VECTOR-04', 'MOTION-11']
MONTHS = {'Jan': 'JAN(?:UARY)?', 'Feb': 'FEB(?:RUARY)?', 'Mar': 'MAR(?:CH)?', 'Apr': 'APR(?:IL)?', 'May': 'MAY',
          'Jun': 'JUNE?', 'Jul': 'JULY?', 'Aug': 'AUG(?:UST)?', 'Sep': 'SEPT?(?:EMBER)?', 'Oct': 'OCT(?:OBER)?',
          'Nov': 'NOV(?:EMBER)?', 'Dec': 'DEC(?:EMBER)?'}
CONTACT = {
    'web address': r'\b(?:https?://\S+|www\.\S+|[a-z0-9-]+\.(?:com|org|net|io|co|us|uk|ca|app|studio|example)(?:/\S*)?)\b',
    'email': r'\b[\w.+-]+@[\w-]+\.[\w.]+\b',
    'phone number': r'(?<![\w$])\+?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b',
    'social handle': r'(?<![\w@])@[A-Za-z_][\w.]{1,}',
}
Q = r'“([^”]+)”'


def date_regex(day: str, mon: str) -> str:
    # the day may follow a weekday with no space, as OCR reads tight display type ("FRI16 OCT")
    m = MONTHS[mon[:3].title()]
    return rf'(?<!\d){int(day)}\s*{m}\b|\b{m}\.?\s*{int(day)}(?!\d)'


def num_regex(value: str) -> str:
    digits = value.replace(',', '')
    if len(digits) > 3:
        digits = digits[:-3] + ',?' + digits[-3:]
    return rf'(?<![\d,.]){digits}(?![\d,.]|\d)'


def expand_range(text: str) -> list[str]:
    """'lunara_campaign_01.jpg to lunara_campaign_09.jpg' -> every file in between."""
    m = re.search(r'([\w-]+?_)(\d+)(\.\w+) to \1(\d+)\3', text)
    if not m:
        return []
    prefix, a, ext, b = m.group(1), m.group(2), m.group(3), m.group(4)
    return [f'{prefix}{i:0{len(a)}d}{ext}' for i in range(int(a), int(b) + 1)]


def files_in(text: str) -> list[str]:
    return re.findall(r'[\w-]+(?:\.[\w-]+)*\.(?:png|svg|jpe?g)\b', text)


class Ctx:
    """Facts shared by a task's rules: act names, series title, other talk titles, record values."""

    def __init__(self, tid, spec, groups):
        self.tid, self.spec = tid, spec
        self.outputs = {o['output_id']: o for o in spec['deliverables']}
        self.rules = {r['rule_id']: r for r in groups['rules']}
        self.texts = [row['check'] for r in groups['rules'] for row in r['rows']]
        self.palette = {p['name']: p['hex'] for p in spec['brand_identity']['palette']}
        self.acts, self.series, self.licence, self.access, self.dates = [], None, None, None, {}
        for t in self.texts:
            m = re.search(r'follow the umbra_billing_autumn\.txt order: ([^.]+)\.', t)
            if m and not self.acts:
                self.acts = [a.strip() for a in re.split(r',\s*|\s+and\s+(?=[A-Z])', m.group(1)) if a.strip()]
            m = re.search(r'series title such as “([^”]+)”', t)
            if m:
                self.series = m.group(1)
            m = re.search(r'licence line on .* reads exactly, in any letter case: “([^”]+)”', t)
            if m:
                self.licence = m.group(1)
            m = re.search(r'accessibility line on .* reads exactly, in any letter case: “([^”]+)”', t)
            if m:
                self.access = m.group(1)
            m = re.search(r'On .*?, (.+?) is billed with the date (\d{1,2}) (\w{3})\.', t)
            if m:
                self.dates[m.group(1)] = (m.group(2), m.group(3))
        self.records = {oid: (o.get('source_record') or {}).get('values') or {} for oid, o in self.outputs.items()}
        self.talk_titles = sorted({v.get('Talk Title') for v in self.records.values() if v.get('Talk Title')})

    def suffix(self, output_id):
        name = self.outputs[output_id]['name']
        return name.rsplit(' - ', 1)[1] if ' - ' in name else name


def strip_ref(row) -> str:
    t = row['check']
    if row.get('deliverable_ref'):
        t = t.replace(row['deliverable_ref'], 'DLV')
    return t


# ------------------------------------------------------------------ handlers: each returns an assertion or None

def h_text_value(t, row, ctx):
    a = None
    m = re.search(r'The sleeps figure for .* reads “(\d+)”, as the owner states, not the sheet\'s “(\d+)”', t)
    if m:
        # the figures are read beside "sleeps", so a stray number elsewhere on the page cannot count
        return {'op': 'v2_text_present', 'expected': [{'regex': rf'\bsleeps?\W{{0,3}}{m.group(1)}\b'}],
                'forbidden': [{'regex': rf'\bsleeps?\W{{0,3}}{m.group(2)}\b'}]}
    m = (re.search(r'reads exactly(?:, in any letter case:)? ' + Q, t) or re.search(r'\breads ' + Q, t)
         or re.search(r'is spelled ' + Q, t) or re.search(r'contains ' + Q + r', the tall post line', t))
    if m:
        a = {'op': 'v2_text_present', 'expected': [m.group(1)]}
        if 'in any letter case' in t:
            a['any_case'] = True
        elif re.search(r'sentence case|in capitals', t):
            a['case_matters'] = True          # the check is about letter case itself, so a case difference fails
        forbidden = re.findall(r'\bnot (?:the sheet\'s |the code )?' + Q, t)
        if forbidden:
            # a forbidden form inside the expected one ("Meridian Certified" in "Meridian Certified Plus") counts only on its own
            a['forbidden'] = [{'text': f, 'outside': [m.group(1)]} if f.casefold() in m.group(1).casefold() else f for f in forbidden]
        field_m = re.match(r'Any (serial|timing result|regulator initials|size run|fabric line)\b', t)
        if field_m:
            field = field_m.group(1)
            a['if_any'] = {'serial': r'\bLC-\d{2}-\d{4}\b', 'timing result': r'[+-]\d+\s?s/day', 'regulator initials': r'\b[A-Z]\.\s?[A-Z]\.',
                           'size run': r'\bXS\b|\bXXL\b', 'fabric line': r'\bgsm\b|cotton|jersey'}[field]
        elif re.match(r'(?:Any|If)\b', t):
            return None
        if re.search(r'studio location', t):
            a['whole_line'] = True
        return a
    m = re.match(r'(Casa \w+) is named in full in DLV, spelled as in', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    m = re.search(r'DLV names (\w[\w ]*?), spelled as in', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    m = re.search(r'gives the year (\d{4})(?:, not (?:the catalogue\'s|cousin \w+\'s) (\d{4}))?', t)
    if m:
        a = {'op': 'v2_text_present', 'expected': [{'regex': rf'\b{m.group(1)}\b'}]}
        if m.group(2):
            a['forbidden'] = [{'regex': rf'\b{m.group(2)}\b'}]
        return a
    m = re.search(r'names the place (\w[\w ]*?), with or without', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    if re.search(r'names Ada Hollis; a shared surname', t):
        return {'op': 'v2_text_present', 'expected': [['Ada Hollis', {'regex': r'\bAda(?:,| and| &) [\w ,&]*Hollis\b'}]]}
    m = re.search(r'The (?:dealership|speaker|event) name ' + Q + r' appears', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    m = re.search(r'(?:tagline|upload line) ' + Q + r' appears on screen', t) or re.search(r'shows the handle ' + Q, t) \
        or re.search(r'carries the members line word for word: ' + Q, t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    m = re.search(r'The offer price on DLV is (\d+), the lowest', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [{'regex': num_regex(m.group(1))}]}
    m = re.search(r'The mileage on DLV is ([\d,]+), matching', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [{'regex': num_regex(m.group(1))}]}
    m = re.search(r'The asking price on DLV is \$([\d,]+), matching', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [{'regex': r'\$\s?' + num_regex(m.group(1))}]}
    m = re.search(r'The date on DLV reads ([\d-]+ \w+ \d{4}), as in', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    m = re.search(r'The validity on .* is through (\w{3}) (\d{4}), as in .*?, not last year\'s through (\w{3}) (\d{4})', t)
    if m:
        mon, old = MONTHS[m.group(1)], MONTHS[m.group(3)]
        return {'op': 'v2_text_present', 'expected': [{'regex': rf'\bthrough\s+{mon}\.?\s+{m.group(2)}\b'}],
                'forbidden': [{'regex': rf'\bthrough\s+{old}\.?\s+{m.group(4)}\b'}]}
    m = re.search(r'The date on DLV is (\d{1,2}) (\w{3}) \(.*?\)(?:, not (\d{1,2}) (\w{3})[^,]*)?, in any clear form', t)
    if m:
        a = {'op': 'v2_text_present', 'expected': [{'regex': date_regex(m.group(1), m.group(2))}]}
        if m.group(3):
            a['forbidden'] = [{'regex': date_regex(m.group(3), m.group(4))}]
        return a
    m = re.search(r'The (door|set) time on DLV is (\d{1,2}):(\d{2}) PM', t)
    if m:
        word = r'DOORS?' if m.group(1) == 'door' else r'SETS?'
        minutes = '' if m.group(3) == '00' else m.group(3)
        time = rf'{m.group(2)}(?:[:.]00)?' if not minutes else rf'{m.group(2)}[:.]{minutes}'
        return {'op': 'v2_text_present', 'expected': [{'regex': rf'\b{word}\b\W{{0,3}}(?:OPEN\W+)?(?:AT\W+)?{time}(?:\s?PM)?\b'}]}
    m = re.search(r'Any (standing capacity|season-average attendance|seated-cabaret capacity|season-average occupancy percentage) in promoter-deck\.pdf is (\d+)(%?)', t)
    if m:
        key = {'standing capacity': r'standing', 'season-average attendance': r'attendance', 'seated-cabaret capacity': r'cabaret|seated',
               'season-average occupancy percentage': r'occupancy'}[m.group(1)]
        return {'op': 'v2_text_present', 'line_has': key, 'optional': True, 'expected': [{'regex': rf'(?<![\d.]){m.group(2)}{re.escape(m.group(3))}(?![\d])'}]}
    m = re.search(r'credited on DLV as two words, ' + Q + r', never run together', t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)], 'any_case': True, 'forbidden': [m.group(1).replace(' ', '')]}
    if re.search(r'Every act name (?:on|in) DLV, support acts excepted, is spelled (?:exactly )?as credited', t) and ctx.acts:
        return {'op': 'v2_text_present', 'expected': list(ctx.acts), 'any_case': True}
    m = re.search(r'If a sleeps figure appears on DLV, it reads (\d+)(?:, as the owner states, never the sheet\'s (\d+))?\.', t)
    if m:
        a = {'op': 'v2_text_present', 'line_has': r'\bsleeps?\b', 'optional': True, 'expected': [{'regex': rf'\b{m.group(1)}\b'}]}
        if m.group(2):
            a['forbidden'] = [{'regex': rf'\b{m.group(2)}\b'}]
        return a
    m = re.search(r'If a minimum stay appears on DLV, it reads (\d+) nights', t)
    if m:
        return {'op': 'v2_text_present', 'line_has': r'minimum|min\.? stay', 'optional': True, 'expected': [{'regex': rf'\b{m.group(1)}\b'}]}
    m = re.search(r'The season on DLV is written ' + Q + r', not the code ' + Q, t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)], 'forbidden': [{'regex': rf'\b{m.group(2)}\b'}]}
    if re.search(r'season labels in DLV read “Spring”, “High Summer” and “Autumn”, not the codes', t):
        return {'op': 'v2_text_present', 'expected': ['Spring', 'High Summer', 'Autumn'], 'forbidden': [{'regex': r'\bS[123]\b'}]}
    m = re.search(r'The style name on DLV contains ' + Q, t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    m = re.search(r'The headline on DLV reads ' + Q, t) or re.search(r'The (?:body line|sign-off) on DLV reads ' + Q, t)
    if m:
        return {'op': 'v2_text_present', 'expected': [m.group(1)]}
    if re.search(r'The Disclosure Text on DLV matches the Disclosure Text field', t):
        value = ctx.records.get(row['output_id'], {}).get('Disclosure Text')
        return {'op': 'v2_text_present', 'expected': [value]} if value else None
    return None


def h_text_absent(t, row, ctx):
    if re.search(r'No copy on DLV names or offers Casa Fienile', t):
        return {'op': 'v2_text_absent', 'texts': ['Fienile']}
    if re.search(r'contains no entry for the sold house “Casa Fienile”', t):
        return {'op': 'v2_text_absent', 'texts': ['Fienile'], 'found_is': 'person'}
    m = re.search(r'No last-season placeholder value from [\w_.]+ \(([^)]+)\) appears', t)
    if m:
        # list items are separated by a comma and a space; "71,300" and "$22,900" keep their thousands commas
        values = [v.strip() for v in re.split(r',\s+', m.group(1)) if v.strip()]
        texts, patterns = [], {}
        for v in values:
            n = re.fullmatch(r'(\$)?([\d,]+)(?: mi)?', v)
            if n:
                patterns[v] = (r'\$\s?' if n.group(1) else '') + num_regex(n.group(2))
            else:
                texts.append(v)
        return {'op': 'v2_text_absent', 'texts': texts, 'patterns': patterns}
    m = re.search(r'does not carry the ' + Q + r' speaker-confirmation copy', t)
    if m:
        return {'op': 'v2_text_absent', 'texts': [m.group(1)]}
    if re.search(r'No (?:other talk\'s text|text from another talk), such as', t):
        own = ctx.records.get(row['output_id'], {}).get('Talk Title')
        others = [x for x in ctx.talk_titles if x != own]
        others += [q for q in re.findall(Q, t) if q != own and q not in others]
        return {'op': 'v2_text_absent', 'texts': others} if others else None
    if re.search(r'The text “&nbsp;” does not appear', t):
        return {'op': 'v2_text_absent', 'texts': ['&nbsp;']}
    kinds = [k for k in CONTACT if k in t or (k == 'web address' and 'web address' in t)]
    if re.search(r'no phone number, email(?: address)? or web address|gives no registration web address|adds no email address, phone number or web address|'
                 r'invents no web address, phone number or social handle', t) and kinds:
        a = {'op': 'v2_text_absent', 'patterns': {k: CONTACT[k] for k in kinds}}
        if 'verdastudio.example' in t:
            a['allow'] = [r'(?:[\w.+-]+@)?(?:www\.)?verdastudio\.example(?:/\S*)?']
        return a
    m = re.search(r'Any stock number shown for .* on DLV is (M\d{4}), its stock_no', t)
    if m:
        return {'op': 'v2_text_absent', 'patterns': {'other stock number': rf'\bM(?!{m.group(1)[1:]}\b)\d{{4}}\b'}}
    m = re.search(r'Any mileage shown for .* on DLV is ([\d,]+), matching', t)
    if m:
        return {'op': 'v2_text_absent', 'patterns': {'other mileage': r'\b\d{1,3},?\d{3}\s?(?:mi|miles)\b'},
                'allow': [num_regex(m.group(1)).replace('(?<![\\d,.])', '').replace('(?![\\d,.]|\\d)', '') + r'\s?(?:mi|miles)']}
    m = re.search(r'Any certification tier shown for .* on DLV is ' + Q, t)
    if m:
        if m.group(1).endswith('Plus'):
            return {'op': 'v2_text_absent', 'patterns': {'plain tier': r'Meridian Certified(?! Plus)'}}
        return {'op': 'v2_text_absent', 'texts': ['Meridian Certified Plus']}
    m = re.search(r'Any trim shown for .* on DLV is ' + Q + r', its trim', t)
    if m:
        trims = sorted({v.get('trim') for v in ctx.records.values() if v.get('trim')} - {m.group(1)})
        return {'op': 'v2_text_absent', 'texts': trims} if trims else None
    m = re.search(r'Any year shown with the date on DLV is (\d{4})', t)
    if m:
        mons = '|'.join(MONTHS.values())
        return {'op': 'v2_text_absent', 'patterns': {'other year with a date': rf'\b\d{{1,2}}\s*(?:{mons})\.?,?\s+(?!{m.group(1)}\b)(?:19|20)\d\d\b'}}
    return None


def h_prices(t, row, ctx):
    if re.search(r'No price appears on DLV', t):
        return {'op': 'v2_prices', 'mode': 'none'}
    m = re.search(r'shows no price outside the brand identity\'s ([\d,]+) to ([\d,]+) dollar', t)
    if m:
        return {'op': 'v2_prices', 'mode': 'range', 'min': float(m.group(1).replace(',', '')), 'max': float(m.group(2).replace(',', ''))}
    m = re.search(r'gives no price for .*?; any price shown is the band (\$[\d,]+-\$[\d,]+)', t)
    if m:
        return {'op': 'v2_prices', 'mode': 'only', 'allowed': [m.group(1)]}
    m = re.search(r'Any price shown for the .*? on DLV is (\$[\d,]+), its asking_price', t)
    if m:
        return {'op': 'v2_prices', 'mode': 'only', 'allowed': [m.group(1)]}
    m = re.search(r'Any price on DLV is the (\$\d+) single or (\$\d+) four-pack', t)
    if m:
        return {'op': 'v2_prices', 'mode': 'only', 'allowed': [m.group(1), m.group(2)]}
    return None


def h_weekdays(t, row, ctx):
    if re.search(r'weekday shown', t) and re.search(r'is Friday|correct for 2026', t):
        return {'op': 'v2_weekdays', 'year': 2026}
    return None


def h_layout(t, row, ctx):
    rec = ctx.records.get(row['output_id'], {})
    m = re.search(r'(?:Apart from (?:the )?([\w ]+?), )?[Tt]he largest text on (?:page (\d) of )?DLV(?:, other than any ([A-Z]+) wordmark,)? is (?:the [\w -]+? |her name )?' + Q, t)
    if m:
        a = {'op': 'v2_largest_text', 'text': m.group(4)}
        if m.group(2):
            a['page'] = int(m.group(2))
        if m.group(1) == 'series title' and ctx.series:
            a['except'] = [ctx.series]
        if m.group(3):
            a['except'] = [m.group(3)]
        return a
    m = re.match(r'The largest text on DLV is the title\.', t)
    if m:
        return {'op': 'v2_largest_text', 'text': ctx.suffix(row['output_id'])}
    m = re.match(r'Apart from the monogram(?: and her name)?, the talk title is the largest text on DLV\.', t)
    if m and rec.get('Talk Title'):
        a = {'op': 'v2_largest_text', 'text': rec['Talk Title']}
        if 'her name' in t:
            a['except'] = ['Astrid Vellacourt']
        return a
    m = re.search(r'On DLV the name ' + Q + r' sits above the role line ' + Q, t)
    if m:
        return {'op': 'v2_relation', 'rel': 'above', 'a': m.group(1), 'b': [m.group(2)]}
    if re.search(r'The role line on DLV is set larger than the affiliation and the session', t) and rec:
        return {'op': 'v2_relation', 'rel': 'larger', 'a': rec['Role Line'], 'b': [rec['Affiliation'], rec['Session']]}
    m = re.search(r'Her name ' + Q + r' on DLV is set larger than the date ' + Q, t)
    if m:
        return {'op': 'v2_relation', 'rel': 'larger', 'a': m.group(1), 'b': [m.group(2)]}
    m = re.search(r'The talk title on DLV is set (smaller|larger) than (?:her name|the date) ' + Q, t)
    if m and rec.get('Talk Title'):
        return {'op': 'v2_relation', 'rel': m.group(1), 'a': rec['Talk Title'], 'b': [m.group(2)]}
    m = re.search(r'On DLV the reference name ' + Q + r' is set larger than the specification lines', t)
    if m and rec:
        return {'op': 'v2_relation', 'rel': 'larger', 'a': m.group(1), 'b': [rec['case_metal'], rec['dial_finish']]}
    if re.search(r'each headline act, Sable Quartet, Meridian Brass and Night Ferry, is set larger than every act of the remaining nights', t) and ctx.acts:
        heads = ['Sable Quartet', 'Meridian Brass', 'Night Ferry']
        return {'op': 'v2_relation', 'rel': 'larger', 'a': heads, 'b': [x for x in ctx.acts if x not in heads]}
    if re.search(r'every act name is set smaller than the series title', t) and ctx.acts and ctx.series:
        return {'op': 'v2_relation', 'rel': 'smaller', 'a': list(ctx.acts), 'b': [ctx.series]}
    m = re.search(r'(?:The act name KOA is set on one line|If KOA is typeset in .*?, it is set on one line)', t)
    if m:
        return {'op': 'v2_line_count', 'text': 'KOA', 'max_lines': 1, 'optional': t.startswith('If')}
    m = re.search(r'The act name ' + Q + r' on DLV runs over one or two lines', t)
    if m:
        return {'op': 'v2_line_count', 'text': m.group(1), 'max_lines': 2}
    if re.search(r'Every act name on DLV runs over one or two lines', t) and ctx.acts:
        return {'op': 'v2_all_of', 'checks': [{'op': 'v2_line_count', 'text': x, 'max_lines': 2} for x in ctx.acts]}
    m = re.search(r'Acts on DLV follow the umbra_billing_autumn\.txt order', t)
    if m and ctx.acts:
        return {'op': 'v2_order', 'texts': list(ctx.acts)}
    return None


def h_inside(t, row, ctx):
    rec = ctx.records.get(row['output_id'], {})
    m = re.search(r'The date ([\d-]+ \w+ \d{4}) on DLV sits fully inside the image', t)
    if m:
        return {'op': 'v2_text_inside', 'texts': [m.group(1)]}
    m = re.search(r'The event name ' + Q + r' (?:on DLV is fully visible|sits fully inside DLV)', t)
    if m:
        return {'op': 'v2_text_inside', 'texts': [m.group(1)]}
    if re.search(r'No letter of the talk title, event name or date is cut off', t) and rec:
        return {'op': 'v2_text_inside', 'texts': [rec['Talk Title'], rec['Event Name'], rec['Date']]}
    if re.search(r'No letter of the title on DLV is cut off at the frame edge', t):
        return {'op': 'v2_text_inside', 'texts': [ctx.suffix(row['output_id'])]}
    return None


def h_style(t, row, ctx):
    """PDF type styles for text the check names exactly (act names, dates, door times, licence and accessibility lines)."""
    if not ctx.acts and ctx.tid == 'LAYOUT-12':
        return None
    deck = 'Promoter pitch deck' in t or 'promoter-deck' in t
    optional = bool(re.match(r'(?:Any|If)\b', t))
    date_pats = [date_regex(d, m) for d, m in ctx.dates.values()] if ctx.dates else []
    sel = None
    if re.search(r'act name', t) and not re.search(r'date line|support act|door', t):
        sel = {'texts': list(ctx.acts)}
    elif re.search(r'date line', t) and date_pats:
        sel = {'patterns': date_pats}
    elif re.search(r'door time', t):
        sel = {'patterns': [r'\bDOORS?\b']}
    elif re.search(r'licence line', t) and ctx.licence:
        sel = {'texts': [ctx.licence]}
    elif re.search(r'accessibility line', t) and ctx.access:
        sel = {'texts': [ctx.access]}
    elif re.search(r'series title', t) and ctx.series:
        sel = {'texts': [ctx.series]}
    elif re.search(r'Each talk title on', t) and ctx.talk_titles:
        sel, optional = {'texts': list(ctx.talk_titles)}, True
    elif re.search(r'Each reference name on', t):
        refs = sorted({v.get('reference') for v in ctx.records.values() if v.get('reference')})
        sel = {'texts': refs} if refs else None
    if not sel:
        return None
    a = {'op': 'v2_pdf_text_style', **sel, 'optional': optional or deck}
    m = re.search(r'is set in ((?:Sora|Archivo Narrow|Inter|Cormorant Garamond|Source Sans 3|Barlow Condensed)) (ExtraBold|SemiBold|Regular|Medium|Light|Bold)\b', t)
    if m:
        a.update(family=m.group(1), weight=m.group(2))
        return a
    if re.search(r'is set in capitals', t):
        a['caps'] = True
        return a
    m = re.search(r'is (?:Bone White|Sodium) (#[0-9A-F]{6})\.', t)
    if m:
        a['colors'] = [m.group(1)]
        return a
    return None


def h_all_text_colour(t, row, ctx):
    if re.search(r'Every title, support, door, set, body, billing and fine-print line on DLV is Bone White (#[0-9A-F]{6})', t) or \
            re.search(r'Outside the poster images, every heading, support, billing, body, table, chart-label, door, set and fine-print line in .* is Bone White (#[0-9A-F]{6})', t):
        hex_ = re.search(r'Bone White (#[0-9A-F]{6})', t).group(1)
        date_pats = [date_regex(d, m) for d, m in ctx.dates.values()]
        return {'op': 'v2_pdf_text_style', 'all_text': True, 'except': list(ctx.acts), 'except_patterns': date_pats, 'colors': [hex_]}
    return None


def h_palette(t, row, ctx):
    m = re.search(r'(?:come only from|use only|is one of(?: the six palette hexes:)?|are one of)\s*:?\s*((?:#[0-9A-F]{6}[, ]*(?:and |or )?)+)', t)
    if m:
        hexes = re.findall(r'#[0-9A-F]{6}', m.group(1))
        if len(hexes) >= 2:
            return {'op': 'v2_palette_only', 'hexes': hexes}
    m = re.search(r'(.+?) both appear in the type, grounds or panels', t)
    if m:
        return {'op': 'v2_colours_present', 'hexes': re.findall(r'#[0-9A-F]{6}', m.group(1))}
    m = re.search(r'(#[0-9A-F]{6}) is the main ground of every page', t) or re.search(r'keeps the Warm Neutral (#[0-9A-F]{6}) ground', t) \
        or re.search(r'page ground of every page of DLV is Warm Paper Ground (#[0-9A-F]{6})', t)
    if m:
        return {'op': 'v2_main_ground', 'hex': m.group(1)}
    m = re.search(r'together cover no more than (\d+)% of the non-photographic area', t)
    if m:
        return {'op': 'v2_area_share', 'hexes': re.findall(r'#[0-9A-F]{6}', t), 'max_pct': float(m.group(1))}
    m = re.search(r'If Ink Black (#[0-9A-F]{6}) appears on DLV, it covers no more than (\d+)% of the sticker\'s inked area', t)
    if m:
        return {'op': 'v2_area_share', 'hexes': [m.group(1)], 'max_pct': float(m.group(2))}
    m = re.search(r'Warm Paper Ground (#[0-9A-F]{6}) covers more of every page of DLV than all Oatmeal Glaze, Soft Clay and Indigo Dye areas combined', t)
    if m:
        others = [ctx.palette.get(n) for n in ('Oatmeal Glaze', 'Soft Clay', 'Indigo Dye')]
        return {'op': 'v2_area_share', 'hexes': [m.group(1)], 'compare_hexes': others} if all(others) else None
    return None


def h_match(t, row, ctx):
    optional = bool(re.match(r'(?:If|Any|Where|Wherever)\b', t))
    if re.search(r'No merchandise photo \(', t):
        return {'op': 'v2_lacks_asset', 'assets': files_in(re.search(r'\(([^)]+)\)', t).group(1))}
    if re.search(r'No photograph on DLV is any of the supplied headshots', t):
        return {'op': 'v2_lacks_asset', 'assets': expand_range(t)}
    m = re.search(r'([\w-]+\.jpg) appears on no page of DLV', t)
    if m:
        return {'op': 'v2_lacks_asset', 'assets': [m.group(1)]}
    if re.search(r'is not stretched or squashed', t):
        assets = files_in(t) or ([ 'meridian_roundel_transparent.svg'] if 'compass roundel' in t else [])
        return {'op': 'v2_contains_asset', 'assets': assets, 'shape': True, 'optional': True} if assets else None
    m = re.search(r'If venue_render\.jpg appears on DLV, it is shown no larger than its native', t)
    if m:
        return {'op': 'v2_contains_asset', 'assets': ['venue_render.jpg'], 'max_scale': 1.0, 'optional': True, 'shape': False}
    if re.search(r'CFS (?:summit )?mark on DLV stays fully inside the image|If a CFS mark appears on DLV, it stays fully inside', t):
        # the supplied artwork, or the mark's letters read as a line of their own
        return {'op': 'v2_any_of', 'checks': [
            {'op': 'v2_contains_asset', 'assets': ['cfs_mark_transparent.svg'], 'inside': True, 'shape': False, 'optional': optional},
            {'op': 'v2_text_inside', 'texts': ['CFS'], 'whole_line': True}]}
    if re.search(r'thumbnail|capture', t) and 'mp4' in t:
        return None                                     # matching against video captures is not built yet
    if re.search(r'traced from|keeps every part|not from meridian_bag|not from the halftone', t):
        return None                                     # how a drawing was built is not a file match
    assets = expand_range(t) or files_in(t)
    if not assets:
        return None
    if re.search(r'is the supplied|supplied mark from|is the [\w_.-]+ drawing|is the supplied frame|using the supplied photo|is built from|'
                 r'taken from one of|the Photo File|carries the supplied|is meridian_roundel|it is meridian_roundel|wordmark on DLV is the', t):
        if re.search(r'sits on Meridian Navy', t):
            return None
        return {'op': 'v2_contains_asset', 'assets': assets, 'shape': bool(re.search(r'proportions|retyped|redrawn|drawing', t)), 'optional': optional}
    return None


def h_print(t, row, ctx):
    """Print measurements read from the PDF itself: effective resolution of a placed photo, characters per line."""
    m = re.search(r'The headshot on DLV is placed at (\d+) ppi or more at its printed size\.$', t)
    if m:
        photo = ctx.records.get(row['output_id'], {}).get('Photo File')
        assets = [x['filename'] for x in (row.get('reference') or {}).get('assets', [])]
        if photo and assets == [photo]:
            return {'op': 'v2_image_ppi', 'asset': photo, 'min_ppi': int(m.group(1))}
        return None
    m = re.search(r'^Each line of the license text and the office text on DLV has (\d+) characters or fewer\.$', t)
    if m:
        rec = ctx.records.get(row['output_id'], {})
        if rec.get('License Line') and rec.get('Office'):
            return {'op': 'v2_line_lengths', 'texts': [rec['License Line'], rec['Office']], 'max_chars': int(m.group(1))}
    return None


HANDLERS = [h_print, h_weekdays, h_text_absent, h_prices, h_all_text_colour, h_style, h_palette, h_layout, h_inside, h_match, h_text_value]
HOW = {
    'v2_text_present': 'Reads the text (live PDF text, or OCR on images and video frames) and checks the expected wording is there.',
    'v2_text_absent': 'Reads all text and checks none of the named words or patterns appears.',
    'v2_prices': 'Finds every price and checks each meets the rule.',
    'v2_weekdays': 'Finds every weekday shown beside a date and checks it against the 2026 calendar.',
    'v2_largest_text': 'Compares text sizes (font size in PDFs, letter height on images).',
    'v2_relation': 'Compares the named texts\' size or position.',
    'v2_line_count': 'Counts the lines the named text runs over.',
    'v2_order': 'Checks the named texts appear in this order, top to bottom.',
    'v2_text_inside': 'Checks the named text is read in full inside the page or image (for a mark, its letters read as a line of their own).',
    'v2_pdf_text_style': 'Reads the font, size, letter case or colour of the named text from the PDF.',
    'v2_palette_only': 'Reads every type, shape and line colour from the file (photos excluded).',
    'v2_colours_present': 'Checks the named colours are used by type or shapes.',
    'v2_main_ground': 'Renders each page without photos and finds the colour covering the most area.',
    'v2_area_share': 'Renders the file without photos and measures the share of the named colours.',
    'v2_contains_asset': 'Searches the deliverable for the supplied file and checks its proportions.',
    'v2_lacks_asset': 'Searches the deliverable for the named supplied files.',
    'v2_all_of': 'Runs each part; all must pass.',
    'v2_any_of': 'Tries each route; one must pass and none may fail.',
    'v2_image_ppi': 'Finds the supplied photo among the PDF\'s placed images and divides its pixels by its placed size.',
    'v2_line_lengths': 'Counts the characters, spaces included, of every PDF text line carrying the named text.',
}


HOW.update(round2.HOW)
HOW.update(round3.HOW)
HOW.update(round4.HOW)
HOW.update(round5.HOW)


def how(a) -> str:
    """How the code checks it, in plain words; a combined check names its parts."""
    if a.get('how'):   # round 5: a handler may give the rule its own sentence (vision-model questions differ per rule)
        return a['how']
    if a['op'] == 'v2_contains_asset':
        tests = [t for t, on in (('keeps its own proportions', a.get('shape', True)), ('lies fully inside the image', a.get('inside')),
                                 ('is shown no larger than its native size', a.get('max_scale'))) if on]
        found = 'Searches the deliverable for the supplied file (feature matching, confirmed by correlation)'
        return found + (', then checks it ' + ' and '.join(tests) if tests else '') + '.'
    if a['op'] == 'v2_pictured':
        return HOW['v2_pictured'].rstrip('.') + ': ' + how(a['then'])[:1].lower() + how(a['then'])[1:]
    if a['op'] == 'v2_any_of':
        parts = [how(x).rstrip('.') for x in a['checks']]
        return 'Either route can answer: ' + '; or: '.join(p[:1].lower() + p[1:] for p in parts) + '. One must pass and none may fail.'
    if a['op'] == 'v2_all_of':
        kinds = sorted({x['op'] for x in a['checks']})
        if len(kinds) == 1:
            return HOW[kinds[0]].rstrip('.') + f', for each of the {len(a["checks"])} named texts; all must pass.'
        return 'Runs each part; all must pass: ' + '; '.join(HOW[k].rstrip('.') for k in kinds) + '.'
    return HOW[a['op']]


def convert(row, ctx):
    t = strip_ref(row)
    for h in HANDLERS:
        a = h(t, row, ctx)
        if a:
            return a
    return None


def main():
    # --out <dir>: write moved/ and not_converted.json there instead of beside this script
    out_root = Path(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv else HERE
    out_dir = out_root / 'moved'
    # round 3 also converts rules first sorted as later (colour on images), needing a definition, or judgement,
    # wherever a round-3 handler exists for them
    plan = [p for p in json.loads(PLAN.read_text())
            if p['status'] == 'auto' or (p['task'], p['rule']) in round3.R3 or (p['task'], p['rule']) in round4.R4
            or (p['task'], p['rule']) in round5.R5]
    # a round-4 or round-5 handler replaces an earlier conversion of the same rule: list every replacement
    for key in sorted(set(round4.R4) & (set(round2.R2) | set(round3.R3))):
        print('round 4 replaces', 'round 2' if key in round2.R2 else 'round 3', 'for', *key)
    for key in sorted(set(round5.R5) & (set(round2.R2) | set(round3.R3) | set(round4.R4))):
        print('round 5 replaces', 'round 4' if key in round4.R4 else 'round 2' if key in round2.R2 else 'round 3', 'for', *key)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary, left = Counter(), defaultdict(list)
    for tid in TASK_IDS:
        spec = json.loads((TASKS / tid / 'TASK_SPEC.json').read_text())
        groups = json.loads((GROUPS / f'{tid}.json').read_text())
        ctx = Ctx(tid, spec, groups)
        moved = []
        for p in (p for p in plan if p['task'] == tid):
            rule = ctx.rules[p['rule']]
            if (tid, p['rule']) in round5.R5:
                assertions = [round5.convert(tid, p['rule'], row, ctx) for row in rule['rows']]
            elif (tid, p['rule']) in round4.R4:
                assertions = [round4.convert(tid, p['rule'], row, ctx) for row in rule['rows']]
            elif (tid, p['rule']) in round2.R2:
                assertions = [round2.convert(tid, p['rule'], row, ctx) for row in rule['rows']]
            elif (tid, p['rule']) in round3.R3:
                assertions = [round3.convert(tid, p['rule'], row, ctx) for row in rule['rows']]
            else:
                assertions = [convert(row, ctx) for row in rule['rows']]
            if not all(assertions):
                left[tid].append((p['rule'], len(rule['rows']), rule['rows'][0]['check'][:120]))
                continue
            for row, a in zip(rule['rows'], assertions):
                moved.append({'check_id': row['check_id'], 'output_id': row['output_id'], 'rule_id': p['rule'], 'k_id': rule['k_id'],
                              'critical': rule['critical'], 'check': row['check'], 'assertion': a, 'how': how(a)})
            summary[(tid, 'rules')] += 1
            summary[(tid, 'checks')] += len(rule['rows'])
        (out_dir / f'{tid}.json').write_text(json.dumps({'task_id': tid, 'moved': moved}, ensure_ascii=False, indent=1) + '\n')
    total_r = sum(v for (t, k), v in summary.items() if k == 'rules')
    total_c = sum(v for (t, k), v in summary.items() if k == 'checks')
    for tid in TASK_IDS:
        print(f"{tid:10s} converted {summary[(tid, 'rules')]:3d} rules / {summary[(tid, 'checks')]:4d} checks; not yet {len(left[tid])} rules")
    print(f'TOTAL converted {total_r} rules / {total_c} checks')
    (out_root / 'not_converted.json').write_text(json.dumps(left, ensure_ascii=False, indent=1) + '\n')


if __name__ == '__main__':
    main()
