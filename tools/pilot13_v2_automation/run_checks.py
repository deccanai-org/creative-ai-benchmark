#!/usr/bin/env python3
"""Run the moved checks on a folder of delivered files (default: the 2026-09-28 pilot run) and write a report.

Usage: python run_checks.py [--run <run root>] [--tasks PHOTO-19 ...] [--out results.json] [--shard K/N]
(--shard K/N: only the checks on every N-th delivered file, starting at the K-th (0-based), so N processes can share
one task; each file's checks stay in one process, so what one check reads from a file is reused by the next)
Run with the benchmark_v4 venv (PyMuPDF, OpenCV) and Tesseract on PATH.
"""
import argparse
import json
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'tools/auto_verifier'))
import objective_ops  # noqa: E402

DEFAULT_RUN = ROOT.parents[1] / 'benchmark_runs/pilot_v7_hybrid_2026-09-28'
REFRESH = ROOT.parents[1] / 'reviews/pilot13-refresh-2026-10-14'


def asset_dirs(tid):
    """Every local folder that may hold the task's supplied files, newest refresh first."""
    return [str(d) for d in (REFRESH / 'upload' / tid, REFRESH / 'sources' / tid, DEFAULT_RUN / tid / 'source') if d.is_dir()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run', type=Path, default=DEFAULT_RUN)
    ap.add_argument('--tasks', nargs='*')
    ap.add_argument('--out', type=Path, default=HERE / 'run_results.json')
    ap.add_argument('--shard', default='0/1')
    args = ap.parse_args()
    shard, shards = map(int, args.shard.split('/'))
    results, counts = [], Counter()
    for f in sorted((HERE / 'moved').glob('*.json')):
        tid = f.stem
        if args.tasks and tid not in args.tasks:
            continue
        spec = json.loads((ROOT / 'docs/gatsby-v7/tasks' / tid / 'TASK_SPEC.json').read_text())
        outputs = {o['output_id']: o for o in spec['deliverables']}
        moved = json.loads(f.read_text())['moved']
        files = sorted({m['output_id'] for m in moved})
        mine = set(files[shard::shards])
        moved = [m for m in moved if m['output_id'] in mine]
        started = time.time()
        for m in moved:
            file = args.run / tid / outputs[m['output_id']]['path']
            r = {'task': tid, 'check_id': m['check_id'], 'rule_id': m['rule_id'], 'op': m['assertion']['op'], 'critical': m['critical']}
            if not file.is_file():
                r.update(status='no_output')
            else:
                a = dict(m['assertion'], _asset_dirs=asset_dirs(tid), _artifacts=str(args.run / tid))
                try:
                    status, evidence = objective_ops.run(file, a)
                    r.update(status=status, evidence=evidence)
                except Exception as e:  # an operation error is never a pass
                    r.update(status='error', evidence={'error': f'{type(e).__name__}: {e}', 'trace': traceback.format_exc()[-600:]})
            results.append(r)
            counts[(tid, r['status'])] += 1
        print(f'{tid}: {len(moved)} checks in {time.time() - started:.0f}s ->',
              {k[1]: v for k, v in counts.items() if k[0] == tid}, flush=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1, default=str) + '\n')
    total = Counter(r['status'] for r in results)
    print('TOTAL', dict(total))


if __name__ == '__main__':
    main()
