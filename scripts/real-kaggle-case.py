"""Reproduce one pinned, complete Kaggle case through the app's guarded API.

Default validates/downloads the original CSV only. --submit --with-agent submits
one model-enabled job; the durable intent file prevents accidental resubmission.
Use --resume to retrieve that same job. No model request is retried here.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time
import zipfile

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.ingest import read_dataset

DATASET = 'https://www.kaggle.com/datasets/dgomonov/new-york-city-airbnb-open-data'
DOWNLOAD = 'https://www.kaggle.com/api/v1/datasets/download/dgomonov/new-york-city-airbnb-open-data?datasetVersionNumber=3'
CSV_SHA = 'e420db40ff10fcb40efc1b5b1648ee0b18a48f4e4537155cecc59fe95d18783a'
GOAL = ('分析 Kaggle New York City Airbnb Open Data 版本3原始文件 AB_NYC_2019.csv，'
        '以 price 为关注字段，比较行政区、社区与房型的挂牌价格分布、中位数、四分位范围和有效样本量，'
        '检查缺失、零价格、极端值和关联。来源：' + DATASET + '。'
        '这是2019年真实房源观测快照，共48895行16列。price 是美元每晚挂牌价，不是成交价或营收；'
        'availability_365 是未来365天可订天数，不代表实际空置或入住率；'
        'last_review 是截至快照最近评论日，按此日期分桶比较挂牌价不能解释成历史价格变化。'
        '只描述该历史样本的统计差异，不宣称因果、显著性、价格驱动因素、正态性或对称性；'
        '分组引用须同时注明类别字段与G别名，优先讨论price，不把经纬度相关视为价格原因。'
        '文字仅选3个重点：总体价格分位数、行政区及房型的挂牌价中位数对比、评论日期缺失的分析边界。'
        '仅用输入证据逐项引用数字，不解释经纬度方向，不推断市场占有率、组别最小样本或显著性；'
        '不要把P95当作IQR异常阈值，不把按最后评论日分组写成市场历史趋势。'
        '请用300至450字正文、最多3条观察和3条简短后续建议结束，避免逐图复述。')


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', default='.local/datasets/airbnb-nyc2019/AB_NYC_2019.csv')
    parser.add_argument('--access-file', default='.local/access.json')
    parser.add_argument('--url')
    parser.add_argument('--output-dir', default='.local/real-kaggle-airbnb')
    parser.add_argument('--submit', action='store_true')
    parser.add_argument('--with-agent', action='store_true')
    parser.add_argument('--confirm-paid-call', action='store_true', help='Explicitly authorize one paid job together with --submit --with-agent.')
    parser.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    if args.submit and args.resume:
        parser.error('--submit and --resume are mutually exclusive.')
    if args.submit and args.with_agent and not args.confirm_paid_call:
        parser.error('--submit --with-agent requires --confirm-paid-call; no model call was submitted.')
    csv = Path(args.csv)
    if not csv.exists():
        csv.parent.mkdir(parents=True, exist_ok=True)
        csv.parent.chmod(0o700)
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            with client.stream('GET', DOWNLOAD) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 20_000_000:
                        raise SystemExit('Unexpectedly large archive; no file saved.')
                    chunks.append(chunk)
        archive = b''.join(chunks)
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            info = bundle.getinfo('AB_NYC_2019.csv')
            assert info.file_size < 10_000_000
            raw = bundle.read(info)
        assert hashlib.sha256(raw).hexdigest() == CSV_SHA, 'Pinned source bytes changed.'
        csv.write_bytes(raw)
        csv.chmod(0o600)
        save(csv.parent / 'provenance.json', {
            'source_url': DATASET, 'download_url': DOWNLOAD, 'version': 3,
            'downloaded_at_utc': datetime.now(timezone.utc).isoformat(),
            'csv_sha256': CSV_SHA, 'csv_bytes': len(raw),
            'archive_sha256': hashlib.sha256(archive).hexdigest(),
            'archive_bytes': len(archive), 'transforms': [],
        })
    assert hashlib.sha256(csv.read_bytes()).hexdigest() == CSV_SHA
    frame, source = read_dataset(csv, csv.name, csv.name)
    assert frame.shape == (48_895, 16) and not source['sampled'] and not source['is_demo']
    if not args.submit and not args.resume:
        print(json.dumps({'status': 'SOURCE_VERIFIED', 'rows': len(frame), 'columns': len(frame.columns),
                          'sha256': CSV_SHA, 'source_url': DATASET}))
        return

    folder = Path(args.output_dir)
    intent = folder / 'evidence.json'
    access = json.loads(Path(args.access_file).read_text())
    with httpx.Client(base_url=args.url or access['url'], timeout=90, follow_redirects=False) as client:
        def api(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        if api('GET', '/api/session').json()['auth_required']:
            api('POST', '/api/login', json={'username': access['username'], 'password': access['password']})
        if args.resume:
            evidence = json.loads(intent.read_text())
            if not evidence.get('job_id'):
                raise SystemExit('Submission outcome uncertain; inspect app history before another submission.')
        else:
            folder.mkdir(parents=True, exist_ok=True)
            folder.chmod(0o700)
            with intent.open('x') as marker:
                marker.write('{}\n')
            intent.chmod(0o600)
            before = api('GET', '/api/usage').json()
            if args.with_agent:
                assert not before['locked'] and (before['unlimited'] or before['remaining_usd'] > 0)
                assert before['model'] == 'deepseek/deepseek-v4-pro-0813'
            evidence = {'status': 'PREPARED', 'source_url': DATASET, 'csv_sha256': CSV_SHA,
                        'rows': 48_895, 'columns': 16, 'use_llm': args.with_agent,
                        'usage_before': before, 'analysis_goal': GOAL}
            save(intent, evidence)
            upload = api('POST', '/api/uploads', files={'file': (csv.name, csv.read_bytes(), 'text/csv')}).json()
            evidence['status'] = 'SUBMISSION_PENDING'
            save(intent, evidence)
            job = api('POST', '/api/jobs', json={'upload_id': upload['upload_id'],
                'selected_file': upload['files'][0]['name'], 'goal': GOAL,
                'target_column': 'price', 'use_llm': args.with_agent}).json()
            evidence.update({'job_id': job['id'], 'status': 'SUBMITTED'})
            save(intent, evidence)
            print('Submitted exactly one real-data job; saved its ID for resume.', flush=True)

        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            job = api('GET', '/api/jobs/' + evidence['job_id']).json()
            if job['status'] in ('completed', 'failed'):
                break
            time.sleep(1)
        else:
            raise SystemExit('Job pending; use --resume. Do not submit another model call.')
        after = api('GET', '/api/usage').json()
        result = job.get('result') or {}
        evidence.update({'status': job['status'], 'usage_after': after,
            'agent_mode': result.get('agent', {}).get('mode'), 'agent_notes': result.get('agent', {}).get('notes'),
            'overview': result.get('overview'), 'source': result.get('source'),
            'chart_count': len(result.get('charts', [])), 'insight_count': len(result.get('insights', [])),
            'section_counts': {s['key']: len(s['chart_ids']) for s in result.get('eda', {}).get('sections', [])},
            'steps': job['steps'], 'semantic_review': 'Requires independent reading; successful transport is not validation.'})
        save(intent, evidence)
        assert job['status'] == 'completed' and all(s['status'] == 'completed' for s in job['steps'])
        assert result['overview']['rows'] == 48_895 and result['overview']['columns'] == 16
        assert not result['source']['sampled'] and not result['source']['is_demo']
        assert result['eda']['target']['column'] == 'price'
        save(folder / 'result.json', result)
        for ext in ('md', 'html'):
            path = folder / ('report.' + ext)
            path.write_bytes(api('GET', '/api/jobs/' + job['id'] + '/report.' + ext).content)
            path.chmod(0o600)
        if evidence['use_llm']:
            assert after['unlimited'] or after['spent_usd'] <= after['limit_usd']
            assert after['reserved_usd'] == 0 and after['uncertain_usd'] == 0
        else:
            assert after == evidence['usage_before']
        print(json.dumps(evidence, ensure_ascii=False, indent=2))
        if evidence['use_llm'] and result['agent']['mode'] != 'llm':
            raise SystemExit('Statistics completed, but model text was not adopted. Review the saved evidence; no retry was submitted.')


if __name__ == '__main__':
    main()
