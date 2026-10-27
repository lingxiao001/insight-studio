"""One paid transport/accounting check; model claims still require separate review. Never retries."""
import argparse
import csv
from datetime import date, timedelta
import io
import json
from pathlib import Path
import time

import httpx


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm-paid-call', action='store_true')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--access-file', default='.local/access.json')
    parser.add_argument('--url')
    parser.add_argument('--evidence-file', default='.local/live-model-job.json')
    args = parser.parse_args()
    evidence_path = Path(args.evidence_file)
    access = json.loads(Path(args.access_file).read_text())
    with httpx.Client(base_url=args.url or access['url'], timeout=60, follow_redirects=False) as client:
        def api(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        api('POST', '/api/login', json={'username': access['username'], 'password': access['password']})
        if args.resume:
            evidence = json.loads(evidence_path.read_text())
        else:
            if not args.confirm_paid_call:
                raise SystemExit('Pass --confirm-paid-call to authorize exactly one paid analysis.')
            if evidence_path.exists():
                raise SystemExit('Existing evidence found. Use --resume; no new paid job submitted.')
            before = api('GET', '/api/usage')
            assert before['model'], 'Configure a model before requesting a paid check.'
            assert not before['locked'] and (before['unlimited'] or before['remaining_usd'] > 0)
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(['日期', '地区', '品类', '销售额', '件数'])
            for i in range(120):
                writer.writerow([(date(2026, 1, 1) + timedelta(days=i)).isoformat(),
                                 ['华东', '华北', '华南'][i % 3], ['食品', '家居'][i % 2],
                                 120 + (i % 17) * 23 + i * 2, 1 + i % 8])
            upload = api('POST', '/api/uploads', files={
                'file': ('synthetic-retail-acceptance.csv', buffer.getvalue().encode(), 'text/csv')})
            job = api('POST', '/api/jobs', json={
                'upload_id': upload['upload_id'], 'selected_file': upload['files'][0]['name'],
                'goal': '这是公开合成的验收数据，分析销售额分布、时间趋势和地区差异，并说明局限。',
                'target_column': '销售额', 'use_llm': True})
            evidence = {'job_id': job['id'], 'usage_before': before}
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
            evidence_path.chmod(0o600)
            print('Submitted exactly one paid analysis; job ID saved for resume.', flush=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            job = api('GET', '/api/jobs/' + evidence['job_id'])
            if job['status'] in ('completed', 'failed'):
                break
            time.sleep(1)
        else:
            raise SystemExit('Job still running; use --resume, without submitting another paid call.')
        after = api('GET', '/api/usage')
        result = job.get('result') or {}
        evidence.update({'status': job['status'], 'agent': result.get('agent'),
                         'chart_count': len(result.get('charts', [])), 'usage_after': after,
                         'eda_version': result.get('eda', {}).get('version'),
                         'eda_section_counts': {s['key']: len(s['chart_ids']) for s in result.get('eda', {}).get('sections', [])},
                         'semantic_review': 'Required separately; transport success does not validate model conclusions.',
                         'steps': job['steps']})
        evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        assert job['status'] == 'completed'
        assert all(step['status'] == 'completed' for step in job['steps'])
        assert result['agent']['mode'] == 'llm'
        assert result['agent']['model'] == evidence['usage_before']['model']
        assert result.get('eda', {}).get('version') == 2
        assert result['eda']['groups'] and result['eda']['time']
        assert after['spent_usd'] > evidence['usage_before']['spent_usd']
        assert after['prompt_tokens'] > evidence['usage_before']['prompt_tokens']
        assert after['completion_tokens'] > evidence['usage_before']['completion_tokens']
        assert after['reserved_usd'] == 0 and after['uncertain_usd'] == 0
        if not after['unlimited']:
            assert after['spent_usd'] <= after['limit_usd'] and after['remaining_usd'] < after['limit_usd']
        print('PASS (transport/accounting only): flagship call, six steps, charts, settled cost and tokens. Model conclusions still require review.')


if __name__ == '__main__':
    run()
