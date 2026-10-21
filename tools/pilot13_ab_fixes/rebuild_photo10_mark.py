#!/usr/bin/env python3
"""Rebuild the four Northgrove (PHOTO-10) production mark files from the Adobe trace.

Why: benchmark_v4/clean_adobe_vectors.py kept only traced shapes whose fill was near-black
(every RGB channel <= 100). That dropped the olive leaf (traced fill rgb(114,114,65)) and kept
dark shapes from the shadowed left edge of the photographed card, so the published
northgrove_mark_transparent/reversed files had no leaf and a junk sliver.

This script keeps exactly the leaf (trace path 52) and the ten NORTHGROVE letter shapes
(trace paths 53 to 62; indexes count every child element), discards everything else, and colours them with the brand palette:
leaf Olive #6B7248 and wordmark Charcoal #2E2E2C; reversed version wholly Off White #F5F2EC.
Geometry is the Adobe trace unchanged. Run with benchmark_v4/.venv/bin/python (needs cairosvg,
svgpathtools).
"""
import ctypes.util
import hashlib
import json
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

_finder = ctypes.util.find_library
ctypes.util.find_library = lambda name: '/opt/homebrew/lib/libcairo.2.dylib' if 'cairo' in name else _finder(name)
import cairosvg  # noqa: E402
from svgpathtools import parse_path  # noqa: E402

HERE = Path(__file__).resolve().parent
TRACE = HERE / 'source/northgrove_mark_adobe_trace.svg'
SVG = '{http://www.w3.org/2000/svg}'
LEAF, LETTERS = 52, range(53, 63)
OLIVE, CHARCOAL, OFF_WHITE = '#6B7248', '#2E2E2C', '#F5F2EC'


def main(out: Path) -> None:
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    root = ET.parse(TRACE).getroot()
    paths = list(root)  # child indexes as listed by the trace (index 0 is <defs>)
    assert all(paths[i].tag == SVG + 'path' for i in (52, *range(53, 63)))
    assert paths[LEAF].get('fill') == 'rgb(114,114,65)', 'trace changed: leaf path not where expected'
    keep = [LEAF, *LETTERS]
    boxes = [parse_path(paths[i].get('d')).bbox() for i in keep]
    xmin = min(b[0] for b in boxes); xmax = max(b[1] for b in boxes)
    ymin = min(b[2] for b in boxes); ymax = max(b[3] for b in boxes)
    margin = max(4.0, (xmax - xmin) * 0.04)
    x, y = xmin - margin, ymin - margin
    width, height = xmax - xmin + 2 * margin, ymax - ymin + 2 * margin
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    for label, colours in (('transparent', {LEAF: OLIVE, 'letters': CHARCOAL}), ('reversed', {LEAF: OFF_WHITE, 'letters': OFF_WHITE})):
        svg = ET.Element(SVG + 'svg', {'viewBox': f'{x:.3f} {y:.3f} {width:.3f} {height:.3f}', 'width': f'{width:.3f}', 'height': f'{height:.3f}', 'role': 'img'})
        ET.SubElement(svg, SVG + 'title').text = 'Northgrove'
        ET.SubElement(svg, SVG + 'path', {'d': paths[LEAF].get('d'), 'fill': colours[LEAF]})
        for i in LETTERS:
            ET.SubElement(svg, SVG + 'path', {'d': paths[i].get('d'), 'fill': colours['letters']})
        target = out / f'northgrove_mark_{label}.svg'
        ET.ElementTree(svg).write(target, encoding='utf-8', xml_declaration=True)
        png = target.with_suffix('.png')
        cairosvg.svg2png(url=str(target), write_to=str(png), output_width=1600)
        for f in (target, png):
            report[f.name] = {'bytes': f.stat().st_size, 'sha256': hashlib.sha256(f.read_bytes()).hexdigest()}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'build')
