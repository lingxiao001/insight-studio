"""Measure the bounded EDA pipeline on deterministic synthetic data; never calls a model."""
import argparse
import json
from pathlib import Path
import resource
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.analysis import analyze
from app.report import render_html, render_markdown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=100_000)
    parser.add_argument('--columns', type=int, default=80)
    parser.add_argument('--output')
    args = parser.parse_args()
    if not 100 <= args.rows <= 100_000 or not 12 <= args.columns <= 80:
        raise SystemExit('Use 100–100,000 rows and 12–80 columns.')
    rng = np.random.default_rng(20261027)
    n = args.rows
    base = rng.lognormal(3, .8, n)
    values = {'record_id': np.arange(n), 'date': pd.Timestamp('2025-01-01') + pd.to_timedelta(rng.integers(0, 700, n), unit='D'),
              'revenue': base, 'cost': base * .6 + rng.normal(0, 2, n),
              'segment': rng.choice(['group-A', 'group-B', 'group-C'], n),
              'channel': rng.choice(['online', 'retail'], n),
              'constant': np.ones(n), 'all_missing': np.full(n, np.nan)}
    for index in range(args.columns - len(values)):
        data = rng.normal(10 + index, 2 + index % 4, n)
        data[rng.random(n) < .035] = np.nan
        values[f'measure_{index:02d}'] = data
    frame = pd.DataFrame(values)
    source = {'filename': 'synthetic-capacity-benchmark.csv', 'is_demo': False,
              'analyzed_rows': n, 'total_rows': n, 'sampled': False, 'notes': []}
    started = time.monotonic()
    result, aggregates = analyze(frame, source, 'Explore revenue, groups and time.', 'revenue', lambda *_: None)
    analysis_seconds = time.monotonic() - started
    assert result.get('eda', {}).get('version') == 2
    assert len(result['charts']) <= 60
    serialized = json.dumps(result, ensure_ascii=False, allow_nan=False)
    markdown = render_markdown(result, 'Synthetic capacity benchmark')
    html = render_html(result, markdown, 'Synthetic capacity benchmark')
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report = {'rows': n, 'columns': len(frame.columns), 'chart_count': len(result['charts']),
              'analysis_seconds': round(analysis_seconds, 3),
              'total_seconds_including_exports': round(time.monotonic() - started, 3),
              'peak_process_mib': round(peak / (1024 * 1024 if sys.platform == 'darwin' else 1024), 1),
              'result_bytes': len(serialized.encode()), 'markdown_bytes': len(markdown.encode()),
              'offline_html_bytes': len(html.encode()),
              'aggregate_chars': len(json.dumps(aggregates, ensure_ascii=False, allow_nan=False)),
              'section_counts': {section['key']: len(section['chart_ids']) for section in result['eda']['sections']}}
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
