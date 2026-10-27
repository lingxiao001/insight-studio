"""Exercise a real deployment without logging its password or dataset rows."""
import argparse
import io
import json
import time
import zipfile
from pathlib import Path

import httpx


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument('--access-file', default='.local/access.json')
    parser.add_argument('--url')
    args = parser.parse_args()
    credentials = json.loads(Path(args.access_file).read_text())
    url = args.url or credentials['url']
    jobs = []
    with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as client:
        def request(method, path, **kwargs):
            response = client.request(method, path, **kwargs)
            response.raise_for_status()
            return response

        def wait(job):
            jobs.append(job['id'])
            end = time.monotonic() + 120
            while time.monotonic() < end:
                item = request('GET', '/api/jobs/' + job['id']).json()
                if item['status'] == 'failed':
                    raise AssertionError('Analysis failed: ' + str(item.get('error')))
                if item['status'] == 'completed':
                    assert item['progress'] == 100
                    assert all(step['status'] == 'completed' for step in item['steps'])
                    result = item['result']
                    assert result['overview']['rows'] > 0
                    assert result['insights']
                    assert result['charts']
                    assert result['agent']['mode'] in ('statistical', 'llm')
                    return item
                time.sleep(.5)
            raise AssertionError('Analysis did not finish in 120 seconds')

        assert request('GET', '/api/health').json()['status'] == 'ok'
        session = request('GET', '/api/session').json()
        assert session['auth_required']
        assert client.get('/api/jobs').status_code == 401
        login = request('POST', '/api/login', json={'username': credentials['username'], 'password': credentials['password']})
        assert 'HttpOnly' in login.headers.get('set-cookie', '')
        if url.startswith('https://'):
            assert 'Secure' in login.headers.get('set-cookie', '')
        assert login.json()['user']['role'] == 'admin'
        usage_before = request('GET', '/api/usage').json()
        assert usage_before['unlimited'] and usage_before['limit_usd'] is None and usage_before['remaining_usd'] is None
        print('PASS: public health, account session, session cookie and unlimited admin budget')
        try:
            demo = wait(request('POST', '/api/demo').json())
            assert demo['result']['source']['is_demo'] is True
            assert demo['result']['overview']['rows'] == 4800
            print('PASS: demo analysis, six steps, real charts and evidence')
            for extension in ('md', 'html'):
                report = request('GET', '/api/jobs/' + demo['id'] + '/report.' + extension)
                assert len(report.content) > 500
                assert 'attachment' in report.headers.get('content-disposition', '')
            print('PASS: Markdown and standalone HTML downloads')

            csv_data = '日期,地区,销售额,件数\n2026-01-01,华东,100,1\n2026-01-02,华北,240,2\n2026-01-03,华东,360,3\n2026-01-04,华南,480,4\n2026-01-05,华北,600,5\n'
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                archive.writestr('train.csv', csv_data)
                archive.writestr('test.csv', 'foo,bar\n1,2\n')
            upload = request('POST', '/api/uploads', files={'file': ('kaggle-style.zip', buffer.getvalue(), 'application/zip')}).json()
            assert len(upload['files']) == 2
            analyzed = wait(request('POST', '/api/jobs', json={
                'upload_id': upload['upload_id'], 'selected_file': 'train.csv',
                'goal': '检查销售额分布和地区差异', 'target_column': '销售额', 'use_llm': False,
            }).json())
            assert analyzed['result']['overview']['rows'] == 5
            assert analyzed['result']['source']['filename'] == 'train.csv'
            assert analyzed['result']['source']['is_demo'] is False
            print('PASS: real ZIP upload, explicit member selection, goal and target analysis')
            assert client.post('/api/jobs', json={
                'upload_id': upload['upload_id'], 'selected_file': '../escape.csv',
                'goal': '', 'use_llm': False,
            }).status_code in (400, 422)
            assert client.post('/api/uploads', files={'file': ('unsafe.py', b'print(1)', 'text/plain')}).status_code in (400, 415, 422)
            assert client.post('/api/demo', headers={'Origin': 'https://untrusted.example'}).status_code == 403
            print('PASS: invalid member, invalid extension and cross-origin write rejected')
            retried = wait(request('POST', '/api/jobs/' + analyzed['id'] + '/retry').json())
            assert retried['id'] != analyzed['id']
            assert retried['result']['overview']['rows'] == 5
            assert len(request('GET', '/api/jobs').json()['jobs']) >= 3
            print('PASS: history, retry and persistence')
        finally:
            for job_id in reversed(jobs):
                client.delete('/api/jobs/' + job_id)
        assert request('GET', '/api/usage').json() == usage_before
        request('POST', '/api/logout')
        assert client.get('/api/jobs').status_code == 401
        print('PASS: cleanup, logout and access revocation')
    print('Deployment smoke test passed.')


if __name__ == '__main__':
    run()
