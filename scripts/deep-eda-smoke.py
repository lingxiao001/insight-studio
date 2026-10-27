"""Verify a deployed EDA v2 with statistical jobs only; never invokes a model."""
import argparse
import json
from pathlib import Path
import time

import httpx


SECTIONS = {'quality', 'distributions', 'categories', 'relationships', 'groups', 'time', 'target'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--access-file', default='.local/access.json')
    parser.add_argument('--url')
    parser.add_argument('--keep-demo', action='store_true')
    parser.add_argument('--upgrade-job', help='Explicitly reanalyze an existing job with use_llm:false.')
    parser.add_argument('--evidence-file', default='.local/deep-eda-smoke.json')
    parser.add_argument('--export-preview-dir', help='Save the synthetic demo exports for local browser review.')
    args = parser.parse_args()
    access = json.loads(Path(args.access_file).read_text())
    created = []
    retained = None
    with httpx.Client(base_url=args.url or access['url'], timeout=90, follow_redirects=False) as client:
        def api(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

        session = api('GET', '/api/session').json()
        if session['auth_required']:
            api('POST', '/api/login', json={'username': access['username'], 'password': access['password']})
        before = api('GET', '/api/usage').json()

        def wait(submitted):
            created.append(submitted['id'])
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                job = api('GET', '/api/jobs/' + submitted['id']).json()
                if job['status'] in ('completed', 'failed'):
                    break
                time.sleep(.5)
            assert job['status'] == 'completed', job.get('error')
            assert job['progress'] == 100 and all(s['status'] == 'completed' for s in job['steps'])
            result = job['result']
            assert result['agent']['mode'] == 'statistical'
            eda = result['eda']
            assert eda['version'] == 2
            assert {s['key'] for s in eda['sections']} == SECTIONS
            ids = [c['id'] for c in result['charts']]
            assert len(ids) == len(set(ids)) and len(ids) <= 60
            assert len(ids) == eda['coverage']['chart_count']
            referenced = [i for s in eda['sections'] for i in s['chart_ids']]
            assert set(referenced) == set(ids)
            assert all(len(s['chart_ids']) == len(set(s['chart_ids'])) for s in eda['sections'])
            assert all(c['section'] in SECTIONS and isinstance(c['fields'], list) for c in result['charts'])
            json.dumps(result, ensure_ascii=False, allow_nan=False)
            return job

        evidence = {}
        try:
            demo = wait(api('POST', '/api/demo').json())
            result = demo['result']
            assert result['overview']['rows'] == 4800 and 35 <= len(result['charts']) <= 60
            assert all(section['chart_ids'] for section in result['eda']['sections'])
            assert result['eda']['correlations']['pearson'] and result['eda']['correlations']['spearman']
            assert result['eda']['groups'] and result['eda']['time'] and result['eda']['distributions']
            md = api('GET', '/api/jobs/' + demo['id'] + '/report.md')
            html = api('GET', '/api/jobs/' + demo['id'] + '/report.html')
            assert 'attachment' in html.headers.get('content-disposition', '')
            assert len(html.content) > 100_000 and 'Plotly.newPlot' in html.text
            assert '<script src="https://cdn.plot.ly' not in html.text
            assert all(section['label'] in md.text for section in result['eda']['sections'])
            if args.export_preview_dir:
                preview = Path(args.export_preview_dir)
                preview.mkdir(parents=True, exist_ok=True)
                (preview / 'report.html').write_bytes(html.content)
                (preview / 'report.md').write_bytes(md.content)
            evidence['demo'] = {'job_id': demo['id'], 'charts': len(result['charts']),
                                'section_counts': {s['key']: len(s['chart_ids']) for s in result['eda']['sections']},
                                'insights': len(result['insights']), 'html_bytes': len(html.content),
                                'duration_seconds': result['duration_seconds']}
            if args.keep_demo:
                retained = demo['id']

            upload = api('POST', '/api/uploads', files={'file': (
                'synthetic-category-only.csv', 'category,flag\nA,yes\nB,no\nA,yes\nC,no\nA,yes\nB,no\nA,yes\nC,no\n'.encode(), 'text/csv')}).json()
            categorical = wait(api('POST', '/api/jobs', json={
                'upload_id': upload['upload_id'], 'selected_file': upload['files'][0]['name'],
                'goal': 'Synthetic categorical-only acceptance', 'target_column': 'category', 'use_llm': False}).json())
            eda = categorical['result']['eda']
            assert not eda['coverage']['selected_numeric_fields']
            assert any(s['key'] == 'categories' and s['chart_ids'] for s in eda['sections'])
            assert {'time', 'relationships'} <= {i['section'] for i in eda['coverage']['not_applicable']}
            assert eda['target']['column'] == 'category' and eda['target']['chart_ids']
            evidence['categorical_only'] = {'charts': len(categorical['result']['charts']),
                'target_chart_references': len(eda['target']['chart_ids']), 'not_applicable': eda['coverage']['not_applicable']}

            if args.upgrade_job:
                original = api('GET', '/api/jobs/' + args.upgrade_job).json()
                upgraded = wait(api('POST', '/api/jobs/' + args.upgrade_job + '/retry', json={'use_llm': False}).json())
                assert upgraded['use_llm'] is False
                assert api('GET', '/api/jobs/' + args.upgrade_job).json() == original
                evidence['explicit_statistical_upgrade'] = {'original_job_id': args.upgrade_job,
                    'original_use_llm': original.get('use_llm'), 'new_use_llm': upgraded['use_llm'],
                    'charts': len(upgraded['result']['charts']), 'original_unchanged': True}
            after = api('GET', '/api/usage').json()
            assert after == before, 'Statistical analysis changed model accounting.'
            evidence.update({'usage_before': before, 'usage_after': after, 'retained_demo_job_id': retained, 'status': 'PASS'})
            out = Path(args.evidence_file)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + '\n')
            out.chmod(0o600)
            print(json.dumps(evidence, ensure_ascii=False, indent=2))
        finally:
            for jid in reversed(created):
                if jid != retained:
                    api('DELETE', '/api/jobs/' + jid)


if __name__ == '__main__':
    main()
