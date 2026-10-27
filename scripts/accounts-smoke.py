"""Verify account isolation on a fresh or existing installation, without a model.

Creates/reuses a private test member and removes only its own temporary jobs.
Existing reports and billing records are preserved.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--access-file', default='.local/access.json')
    parser.add_argument('--member-access-file', default='.local/member-smoke-access.json')
    parser.add_argument('--evidence-file', default='.local/accounts-smoke.json')
    parser.add_argument('--url')
    args = parser.parse_args()
    admin_access = json.loads(Path(args.access_file).read_text())
    member_file = Path(args.member_access_file)
    member_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    new_member = not member_file.exists()
    member_access = ({'username': 'qa_' + secrets.token_hex(8), 'password': secrets.token_urlsafe(32)}
                     if new_member else json.loads(member_file.read_text()))
    url = args.url or admin_access['url']
    created = []
    with httpx.Client(base_url=url, timeout=90) as admin, httpx.Client(base_url=url, timeout=90) as member:
        def call(client, method, path, **kwargs):
            response = client.request(method, '/api' + path, **kwargs)
            response.raise_for_status()
            return response

        def statistical_job(client):
            uploaded = call(client, 'POST', '/uploads', files={'file': (
                'account-check.csv', b'group,value\na,2\nb,5\na,3\nb,7\na,9\nb,4\n', 'text/csv')}).json()
            job_id = call(client, 'POST', '/jobs', json={'upload_id': uploaded['upload_id'],
                'selected_file': 'account-check.csv', 'use_llm': False}).json()['id']
            created.append((client, job_id))
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                job = call(client, 'GET', '/jobs/' + job_id).json()
                if job['status'] in ('completed', 'failed'):
                    assert job['status'] == 'completed', 'Statistical account check failed.'
                    assert job['result']['overview']['rows'] == 6
                    return uploaded, job_id
                time.sleep(.5)
            raise AssertionError('Statistical account check timed out.')

        assert member.get('/api/jobs').status_code == 401
        assert member.post('/api/login', json={'password': 'legacy shared password'}).status_code == 422
        state = call(admin, 'POST', '/login', json={k: admin_access[k] for k in ('username', 'password')}).json()
        assert state['user']['role'] == 'admin'
        admin_usage = call(admin, 'GET', '/usage').json()
        assert admin_usage['unlimited'] and admin_usage['limit_usd'] is None and admin_usage['remaining_usd'] is None
        original_ids = {job['id'] for job in call(admin, 'GET', '/jobs').json()['jobs']}
        response = call(member, 'POST', '/register' if new_member else '/login',
                        json={k: member_access[k] for k in ('username', 'password')})
        assert response.json()['user']['role'] == 'user'
        if new_member:
            # Create owner-only before writing any credential bytes.
            with open(member_file, 'w', opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
                json.dump({'url': url, **member_access}, output)
            member_file.chmod(0o600)
        member_usage = call(member, 'GET', '/usage').json()
        assert member_usage['limit_usd'] == 1 and member_usage['remaining_usd'] == 1
        assert member_usage['spent_usd'] == 0 and not member_usage['unlimited']
        assert member.post('/api/model/authorize', json={'api_key': 'not-a-key', 'confirm_budget': True}).status_code == 403
        assert member.post('/api/register', json={'username': 'cannot_escalate',
            'password': member_access['password'], 'role': 'admin'}).status_code == 422
        try:
            _, target = statistical_job(admin)
            for method, suffix in [('GET', ''), ('GET', '/report.md'), ('GET', '/report.html'), ('POST', '/retry'), ('DELETE', '')]:
                assert member.request(method, '/api/jobs/' + target + suffix).status_code == 404
            upload, job_id = statistical_job(member)
            assert admin.post('/api/jobs', json={'upload_id': upload['upload_id'],
                'selected_file': 'account-check.csv', 'use_llm': False}).status_code == 404
            assert admin.get('/api/jobs/' + job_id).status_code == 404
            assert call(member, 'GET', '/jobs/' + job_id + '/report.md').content
        finally:
            for client, job_id in reversed(created):
                call(client, 'DELETE', '/jobs/' + job_id)
        assert call(member, 'GET', '/usage').json() == member_usage
        assert call(admin, 'GET', '/usage').json() == admin_usage
        assert original_ids <= {job['id'] for job in call(admin, 'GET', '/jobs').json()['jobs']}
        call(member, 'POST', '/logout')
        assert member.get('/api/jobs').status_code == 401
        evidence = {'status': 'passed', 'existing_reports_preserved': True,
                    'cross_account_access': '404', 'ordinary_key_update': '403',
                    'privilege_field': '422', 'statistical_rows': 6, 'new_model_requests': 0,
                    'temporary_jobs_removed': True, 'acceptance_member_retained': True}
        evidence_file = Path(args.evidence_file)
        evidence_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        evidence_file.write_text(json.dumps(evidence, indent=2) + '\n')
        evidence_file.chmod(0o600)
        print(json.dumps(evidence))


if __name__ == '__main__':
    main()
