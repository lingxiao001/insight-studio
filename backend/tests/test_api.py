import time
from pathlib import Path
import threading

from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
import pytest

from app.config import Settings
from app.main import create_app
from app.store import Store


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path, admin_username="admin", admin_password="test password", session_secret="x" * 40, cookie_secure=False)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        assert client.post("/api/login", json={"username": settings.admin_username, "password": settings.admin_password}).status_code == 200
        yield client


def wait(client, job):
    for _ in range(200):
        result = client.get("/api/jobs/" + job["id"]).json()
        if result["status"] in {"completed", "failed"}:
            return result
        time.sleep(.05)
    raise AssertionError("job did not finish")


def upload(client, content=b"name,value,quantity\na,1,2\nb,4,5\na,3,2\nc,9,4\nb,2,1\nc,5,2\n"):
    response = client.post("/api/uploads", files={"file": ("sample.csv", content, "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


def create(client, upload):
    response = client.post("/api/jobs", json={"upload_id": upload["upload_id"],
                           "selected_file": upload["files"][0]["name"], "goal": "比较数据分布", "use_llm": False})
    assert response.status_code == 200, response.text
    return response.json()


def test_session_auth_cookie_logout_and_csrf(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/health").json() == {"status": "ok"}
        assert c.get("/api/session").json()["authenticated"] is False
        assert c.get("/api/jobs").status_code == 401
        assert c.post("/api/login", json={"username": settings.admin_username, "password": "wrong"}).status_code == 401
        login = c.post("/api/login", json={"username": settings.admin_username, "password": settings.admin_password})
        assert login.json()["authenticated"] is True
        assert "httponly" in login.headers["set-cookie"].lower()
        assert "samesite=strict" in login.headers["set-cookie"].lower()
        assert c.post("/api/demo", headers={"Origin": "https://evil.example"}).status_code == 403
        assert c.get("/api/jobs").status_code == 200
        c.post("/api/logout")
        assert c.get("/api/jobs").status_code == 401
        c.cookies.set("insight_session", "tampered")
        assert c.get("/api/jobs").status_code == 401


def test_login_throttling(settings):
    with TestClient(create_app(settings)) as c:
        for _ in range(5):
            assert c.post("/api/login", json={"username": settings.admin_username, "password": "wrong"}).status_code == 401
        assert c.post("/api/login", json={"username": settings.admin_username, "password": settings.admin_password}).status_code == 429


def test_registration_session_role_and_legacy_cookie_are_safe(settings):
    settings.password = "old shared password is ignored"
    with TestClient(create_app(settings)) as c:
        anonymous = c.get("/api/session").json()
        assert anonymous["auth_required"] is True and anonymous["user"] is None
        assert c.post("/api/login", json={"password": settings.password}).status_code == 422
        old_signer = URLSafeTimedSerializer(settings.session_secret, salt="insight-studio-session-v1")
        c.cookies.set("insight_session", old_signer.dumps({"v": "legacy-shared-password-hash"}))
        assert c.get("/api/jobs").status_code == 401
        assert c.post("/api/register", json={"username": "hacker", "password": "secure-password", "role": "admin"}).status_code == 422
        response = c.post("/api/register", json={"username": "new_user", "password": "secure-password"})
        assert response.status_code == 200
        state = response.json()
        assert state["authenticated"] and state["auth_required"]
        assert set(state["user"]) == {"id", "username", "role"} and state["user"]["role"] == "user"
        assert {"model_enabled", "model_name", "limits"} <= set(state)
        assert "secure-password" not in response.text and "password_hash" not in response.text
        assert c.post("/api/model/authorize", json={"api_key": "private-key", "confirm_budget": True}).status_code == 403
        assert c.get("/api/session").json()["user"] == state["user"]
        usage = c.get("/api/usage").json()
        assert usage["user_id"] == state["user"]["id"] and usage["limit_usd"] == 1
        assert usage["remaining_usd"] == 1 and usage["unlimited"] is False
        with c.app.state.store.connect() as db:
            db.execute("UPDATE users SET session_version=session_version+1 WHERE id=?", (state["user"]["id"],))
        assert c.get("/api/jobs").status_code == 401
        assert c.post("/api/login", json={"username": "new_user", "password": "secure-password"}).status_code == 200


def test_empty_shared_password_never_opens_anonymous_access(tmp_path):
    settings = Settings(data_dir=tmp_path, password="", session_secret="s" * 40)
    with TestClient(create_app(settings)) as c:
        assert c.get("/api/session").json()["auth_required"] is True
        assert c.get("/api/jobs").status_code == 401
        assert c.post("/api/demo").status_code == 401
        assert c.post("/api/login", json={"username": "admin", "password": "anything"}).status_code == 401


def test_login_errors_do_not_reveal_account_existence(settings):
    with TestClient(create_app(settings)) as c:
        known = c.post("/api/login", json={"username": "admin", "password": "wrong-password"})
        unknown = c.post("/api/login", json={"username": "unknown", "password": "wrong-password"})
        assert known.status_code == unknown.status_code == 401 and known.json() == unknown.json()
        malformed = c.post("/api/login", json={"username": 123, "password": "never-echo-this-password"})
        assert malformed.status_code == 422 and "never-echo" not in malformed.text


def test_register_is_rate_limited_and_password_validation_is_safe(settings):
    with TestClient(create_app(settings)) as c:
        for _ in range(5):
            response = c.post("/api/register", json={"username": "new_user", "password": "short"})
            assert response.status_code == 400 and "short" not in response.text
        assert c.post("/api/register", json={"username": "new_user", "password": "strong-enough-password"}).status_code == 429


def test_secure_cookie_and_database_role_are_used(settings):
    settings.cookie_secure = True
    with TestClient(create_app(settings), base_url="https://testserver") as c:
        response = c.post("/api/register", json={"username": "new_user", "password": "secure-password"})
        assert "secure" in response.headers["set-cookie"].lower()
        user_id = response.json()["user"]["id"]
        with c.app.state.store.connect() as db:
            db.execute("UPDATE users SET role='admin' WHERE id=?", (user_id,))
        assert c.get("/api/session").json()["user"]["role"] == "admin"
        usage = c.get("/api/usage").json()
        assert usage["user_id"] == user_id and usage["unlimited"] is True
        assert usage["limit_usd"] is None and usage["remaining_usd"] is None


def test_upload_analyze_download_retry_shared_upload_and_delete(client, settings):
    up = upload(client)
    one = wait(client, create(client, up))
    assert one["status"] == "completed", one.get("error")
    assert one["progress"] == 100 and all(s["status"] == "completed" for s in one["steps"])
    assert one["result"]["overview"]["rows"] == 6
    assert "upload_id" not in one
    assert client.get(f"/api/jobs/{one['id']}/report.md").status_code == 200
    html = client.get(f"/api/jobs/{one['id']}/report.html")
    assert html.status_code == 200 and "Plotly.newPlot" in html.text
    assert "attachment" in html.headers["content-disposition"]
    retry = client.post(f"/api/jobs/{one['id']}/retry").json()
    assert retry["id"] != one["id"]
    two = wait(client, retry)
    assert two["status"] == "completed"
    path = Path(client.app.state.store.upload(up["upload_id"])["path"])
    assert client.delete(f"/api/jobs/{one['id']}").status_code == 200
    assert path.exists(), "shared upload must survive while retry still references it"
    assert client.delete(f"/api/jobs/{two['id']}").status_code == 200
    assert not path.exists()
    assert client.get(f"/api/jobs/{one['id']}").status_code == 404


def test_uploads_reports_retries_and_deletes_are_isolated_between_users(client):
    admin_id = client.get("/api/session").json()["user"]["id"]
    admin_upload = upload(client)
    admin_job = wait(client, create(client, admin_upload))
    client.post("/api/logout")
    registered = client.post("/api/register", json={"username": "second_user", "password": "second-user-password"})
    user_id = registered.json()["user"]["id"]
    assert client.get("/api/jobs").json() == {"jobs": []}
    for method, suffix in [("get", ""), ("get", "/report.md"), ("get", "/report.html"), ("post", "/retry"), ("delete", "")]:
        assert getattr(client, method)(f"/api/jobs/{admin_job['id']}" + suffix).status_code == 404
    assert client.post("/api/jobs", json={"upload_id": admin_upload["upload_id"],
        "selected_file": admin_upload["files"][0]["name"]}).status_code == 404
    own_upload = upload(client)
    own_job = wait(client, create(client, own_upload))
    assert client.app.state.store.upload(own_upload["upload_id"])["user_id"] == user_id
    assert client.app.state.store.get_job(own_job["id"])["user_id"] == user_id
    assert client.app.state.store.get_job(admin_job["id"])["user_id"] == admin_id
    assert {job["id"] for job in client.get("/api/jobs").json()["jobs"]} == {own_job["id"]}
    client.post("/api/logout")
    client.post("/api/login", json={"username": "admin", "password": "test password"})
    assert {job["id"] for job in client.get("/api/jobs").json()["jobs"]} == {admin_job["id"]}
    assert client.get(f"/api/jobs/{own_job['id']}").status_code == 404
    assert client.app.state.store.upload(admin_upload["upload_id"]), "cross-user delete must preserve the original upload"


def test_worker_uses_job_owner_bound_ledger(client, monkeypatch):
    client.post("/api/logout")
    user_id = client.post("/api/register", json={"username": "model_user", "password": "strong-model-password"}).json()["user"]["id"]
    captured = []
    marker = object()

    def bind(uid):
        captured.append(uid)
        return marker

    def fake_enrich(result, aggregates, goal, target, settings, ledger, job_id):
        assert ledger is marker
        assert client.app.state.store.get_job(job_id)["user_id"] == user_id

    monkeypatch.setattr(client.app.state.ledger, "for_user", bind)
    monkeypatch.setattr("app.main.enrich", fake_enrich)
    data = upload(client)
    response = client.post("/api/jobs", json={"upload_id": data["upload_id"],
        "selected_file": data["files"][0]["name"], "use_llm": True})
    result = wait(client, response.json())
    assert result["status"] == "completed" and captured == [user_id]


def test_demo_and_job_listing(client):
    job = wait(client, client.post("/api/demo").json())
    assert job["status"] == "completed", job.get("error")
    assert job["is_demo"] and job["result"]["source"]["is_demo"]
    assert job["result"]["overview"]["rows"] == 4800
    listing = client.get("/api/jobs").json()["jobs"]
    assert listing[0]["id"] == job["id"] and "result" not in listing[0]


def test_invalid_upload_and_member_selection(client):
    assert client.post("/api/uploads", files={"file": ("bad.exe", b"binary")}).status_code == 400
    assert client.post("/api/uploads", files={"file": ("bad.zip", b"notzip")}).status_code == 400
    up = upload(client)
    assert client.post("/api/jobs", json={"upload_id": up["upload_id"], "selected_file": "../bad.csv"}).status_code == 400
    assert client.post("/api/jobs", json={"upload_id": "unknown", "selected_file": "bad.csv"}).status_code == 404


def test_failed_parse_is_useful_and_retryable(client):
    up = upload(client, b"only_header\n")
    failed = wait(client, create(client, up))
    assert failed["status"] == "failed" and "数据行" in failed["error"]
    assert client.get(f"/api/jobs/{failed['id']}/report.md").status_code == 409
    assert client.post(f"/api/jobs/{failed['id']}/retry").status_code == 200


def test_queue_is_bounded_and_active_delete_is_rejected(settings, monkeypatch):
    app = create_app(settings)
    release = threading.Event()
    original = app.state.manager.execute

    def block(jid):
        release.wait(5)
        return original(jid)

    monkeypatch.setattr(app.state.manager, "execute", block)
    with TestClient(app) as c:
        c.post("/api/login", json={"username": settings.admin_username, "password": settings.admin_password})
        first = c.post("/api/demo").json()
        assert c.delete(f"/api/jobs/{first['id']}").status_code == 409
        assert c.post(f"/api/jobs/{first['id']}/retry").status_code == 409
        responses = [c.post("/api/demo") for _ in range(6)]
        assert any(r.status_code == 429 for r in responses)
        assert app.state.store.active_count() <= 5
        release.set()
        wait(c, first)


def test_restart_marks_incomplete_jobs_failed(settings):
    settings.validate()
    store = Store(settings.data_dir)
    queued = store.create_job(filename="x.csv")
    running = store.create_job(filename="y.csv")
    store.update(running["id"], status="running")
    with TestClient(create_app(settings)) as c:
        c.post("/api/login", json={"username": settings.admin_username, "password": settings.admin_password})
        for job in [queued, running]:
            recovered = c.get("/api/jobs/" + job["id"]).json()
            assert recovered["status"] == "failed" and "重启" in recovered["error"]


def test_file_and_stream_size_limit(settings):
    settings.max_upload_bytes = 15
    with TestClient(create_app(settings)) as c:
        c.post("/api/login", json={"username": settings.admin_username, "password": settings.admin_password})
        assert c.post("/api/uploads", files={"file": ("x.csv", b"a,b\n" + b"1,2\n" * 10)}).status_code == 413
        assert not list((settings.data_dir / "uploads").iterdir())


def test_statistical_upgrade_explicitly_overrides_old_llm_setting(client):
    original = wait(client,create(client,upload(client)))
    with client.app.state.store.connect() as db:
        db.execute("UPDATE jobs SET use_llm=1 WHERE id=?",(original["id"],))
    assert client.get("/api/jobs/"+original["id"]).json()["use_llm"] is True
    response = client.post(f"/api/jobs/{original['id']}/retry",json={"use_llm":False})
    assert response.status_code == 200 and response.json()["use_llm"] is False
    upgraded = wait(client,response.json())
    assert upgraded["result"]["eda"]["version"] == 2
    assert upgraded["result"]["agent"]["mode"] == "statistical"
    assert client.get("/api/jobs/"+original["id"]).json()["use_llm"] is True
    for body in [{"use_llm":"false"},{"use_llm":0},{"use_llm":None},{"use_llm":False,"unknown":True}]:
        assert client.post(f"/api/jobs/{original['id']}/retry",json=body).status_code == 422
    # Empty body retains old behavior, and this test installation has no model credentials.
    inherited = client.post(f"/api/jobs/{original['id']}/retry",json={})
    assert inherited.status_code == 200 and inherited.json()["use_llm"] is True
