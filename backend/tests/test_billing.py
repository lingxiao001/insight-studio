from concurrent.futures import ThreadPoolExecutor
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.billing import BudgetLedger, BudgetError, micro_usd
from app.config import Settings
from app.main import create_app
from app.store import Store

KEY = "sk-or-test-" + "0" * 32  # Synthetic; never valid with OpenRouter.


@pytest.fixture
def ledger(tmp_path):
    settings = Settings(data_dir=tmp_path, llm_key=KEY, llm_model="test/model",
        llm_input_price="0.132", llm_output_price="0.396", llm_provider_only="test/fp8")
    settings.validate()
    store = Store(tmp_path)
    store.seed_admin("admin", "test-hash-not-used-for-login")
    user = store.add_user("member", "test-hash-not-used-for-login")
    ledger = BudgetLedger(store, settings).for_user(user["id"])
    ledger.catalog_until = time.monotonic() + 3600
    with ledger.store.connect() as db:
        fingerprint = ledger.current(db)["fingerprint"]
    ledger.key_validation[fingerprint] = time.monotonic() + 3600
    return ledger


def one_reservation(ledger):
    return ledger.prepare([{"role": "user", "content": "bounded aggregates"}])[0]


def set_committed_spend(ledger, cost):
    rid = one_reservation(ledger)
    with ledger.store.connect() as db:
        db.execute("UPDATE model_requests SET state='settled',cost_micro=? WHERE id=?", (cost, rid))


def test_boundary_reservation_and_decimal_rounding(ledger):
    rid = one_reservation(ledger)
    with ledger.store.connect() as db:
        amount = db.execute("SELECT reserved_micro FROM model_requests WHERE id=?", (rid,)).fetchone()[0]
        db.execute("DELETE FROM model_requests")
    assert amount > 10_000
    set_committed_spend(ledger, 1_000_000 - amount)
    assert one_reservation(ledger) and ledger.usage()["remaining_usd"] == 0
    with pytest.raises(BudgetError, match="额度不足"): one_reservation(ledger)
    assert ledger.usage()["locked"] is True
    assert micro_usd("0.00000001") == 1 and micro_usd("0.123456000001") == 123457


def test_reservation_prices_all_3200_output_tokens_before_request(ledger):
    from decimal import Decimal, ROUND_CEILING
    messages = [{"role":"user","content":"bounded aggregates"}]
    request_id,_ = ledger.prepare(messages)
    with ledger.store.connect() as db:
        row = db.execute("SELECT * FROM model_requests WHERE id=?",(request_id,)).fetchone()
    prompt_upper = len(json.dumps(messages,ensure_ascii=False).encode("utf-8"))*2+8192
    expected = 10_000+int((Decimal(prompt_upper)*Decimal(".132")+3200*Decimal(".396")).to_integral_value(rounding=ROUND_CEILING))
    assert row["output_upper"] == 3200 and row["reserved_micro"] == expected


def test_atomic_concurrent_reservations_cannot_overcommit(ledger):
    rid = one_reservation(ledger)
    with ledger.store.connect() as db:
        amount = db.execute("SELECT reserved_micro FROM model_requests WHERE id=?", (rid,)).fetchone()[0]
        db.execute("DELETE FROM model_requests")
    set_committed_spend(ledger, 1_000_000 - amount)
    def attempt(_):
        try: return one_reservation(ledger)
        except BudgetError: return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert sum(bool(r) for r in results) == 1 and ledger.usage()["remaining_usd"] == 0
    assert ledger.usage()["spent_usd"] + ledger.usage()["reserved_usd"] <= 1


def test_restart_and_environment_key_change_cannot_reset_budget(ledger):
    one_reservation(ledger)
    before = ledger.usage()
    ledger.settings.llm_key = "sk-or-v1-different-env-key-does-not-reset"
    restarted = BudgetLedger(ledger.store, ledger.settings).for_user(ledger.user_id)
    restarted.recover()
    after = restarted.usage()
    assert after["uncertain_usd"] == before["reserved_usd"]
    assert after["remaining_usd"] == before["remaining_usd"] and after["request_count"] == 1
    with ledger.store.connect() as db: epoch = restarted.current(db)
    assert restarted.credential(epoch) == KEY
    restarted.recover()
    assert restarted.usage() == after


def test_authorization_requires_valid_key_and_preserves_audit(ledger, monkeypatch):
    ledger = ledger.for_user(ledger.store.admin_user()["id"])
    rid = one_reservation(ledger)
    ledger.settle(rid, {"cost": "0.001", "prompt_tokens": 12, "completion_tokens": 8})
    def validate(key):
        if key != KEY: raise BudgetError("密钥验证失败")
        import hashlib
        return hashlib.sha256(key.encode()).hexdigest()
    monkeypatch.setattr(ledger, "verify_key", validate)
    with pytest.raises(BudgetError): ledger.authorize("invalid-key")
    assert ledger.usage()["spent_usd"] == .001
    usage = ledger.authorize(KEY)
    assert usage["spent_usd"] == .001 and usage["remaining_usd"] is None
    assert usage["lifetime_spent_usd"] == .001 and usage["request_count"] == 1
    assert usage["unlimited"] is True and usage["limit_usd"] is None
    with ledger.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM budget_epochs").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM model_requests").fetchone()[0] == 1
    assert KEY not in json.dumps(usage)
    for path in ledger.secret_dir.glob("*.key"):
        assert path.stat().st_mode & 0o777 == 0o600


def test_reauthorization_rejected_during_inflight_request(ledger, monkeypatch):
    ledger = ledger.for_user(ledger.store.admin_user()["id"])
    one_reservation(ledger)
    monkeypatch.setattr(ledger, "verify_key", lambda key: "validated")
    with pytest.raises(BudgetError, match="正在结算"): ledger.authorize(KEY)
    with ledger.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM budget_epochs").fetchone()[0] == 1


def test_price_verification_fails_closed_without_paid_request(ledger, monkeypatch):
    ledger.catalog_until = 0
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url):
            return httpx.Response(200, json={"data": {"endpoints": [{"tag": "test/fp8", "provider_name": "Test",
                "pricing": {"prompt": "0.00000132", "completion": "0.00000396"}}]}}, request=httpx.Request("GET", url))
        def post(self, *args, **kwargs): raise AssertionError("must not make a paid request")
    monkeypatch.setattr("app.billing.httpx.Client", Client)
    with pytest.raises(BudgetError, match="超过"): one_reservation(ledger)
    assert ledger.usage()["request_count"] == 0


def test_usage_authorization_api_never_returns_key(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, admin_password="admin-test-password", session_secret="x" * 40,
        llm_model="test/model", llm_input_price=".132", llm_output_price=".396", llm_provider_only="test/fp8")
    app = create_app(settings)
    monkeypatch.setattr(app.state.ledger, "verify_key", lambda key: (_ for _ in ()).throw(BudgetError("密钥验证失败")))
    with TestClient(app) as c:
        assert c.get("/api/usage").status_code == 401
        assert c.post("/api/model/authorize", json={"api_key": KEY, "confirm_budget": True}).status_code == 401
        assert c.post("/api/login", json={"username": "admin", "password": "admin-test-password"}).status_code == 200
        usage = c.get("/api/usage").json()
        assert usage["locked"] and usage["remaining_usd"] is None and usage["unlimited"]
        assert c.post("/api/model/authorize", json={"api_key": KEY, "confirm_budget": False}).status_code == 400
        response = c.post("/api/model/authorize", json={"api_key": KEY, "confirm_budget": True})
        assert response.status_code == 400 and KEY not in response.text
        assert KEY not in c.get("/api/session").text
        for body in [
            {"api_key": {"nested_secret": KEY}, "confirm_budget": True},
            {"api_key": KEY, "confirm_budget": {"secret": KEY}},
            {"api_key": [KEY], "confirm_budget": True},
        ]:
            response = c.post("/api/model/authorize", json=body)
            assert response.status_code == 422 and KEY not in response.text
        response = c.post("/api/model/authorize", content='{"api_key":"' + KEY, headers={"Content-Type": "application/json"})
        assert response.status_code == 422 and KEY not in response.text


def test_absurd_cost_exponent_is_held_and_locked_without_int_expansion(ledger):
    rid = one_reservation(ledger)
    before = ledger.usage()["reserved_usd"]
    assert ledger.settle(rid, {"cost": "1e999999"}) is False
    usage = ledger.usage()
    assert usage["uncertain_usd"] == before and usage["locked"] is True
    assert usage["spent_usd"] == 0


def test_real_key_validation_readonly_and_rejects_provider_invalid_key(ledger, monkeypatch):
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, url, headers):
            assert url == "https://openrouter.ai/api/v1/key"
            status = 200 if headers["Authorization"] == "Bearer " + KEY else 401
            return httpx.Response(status, json={"data": {"is_management_key": False}}, request=httpx.Request("GET", url))
        def post(self, *args, **kwargs): raise AssertionError("key validation cannot incur a paid call")
    monkeypatch.setattr("app.billing.httpx.Client", Client)
    assert ledger.verify_key(KEY)
    with pytest.raises(BudgetError, match="验证失败"):
        ledger.verify_key("sk-or-v1-invalid-but-correct-shape-key")


def test_generic_provider_disabled_without_budget_protection(tmp_path):
    settings = Settings(data_dir=tmp_path, llm_key=KEY, llm_model="test/model", llm_base_url="https://example.com/v1",
        llm_input_price=".132", llm_output_price=".396", llm_provider_only="test/fp8")
    settings.validate()
    store = Store(tmp_path)
    user = store.add_user("member", "test-hash-not-used-for-login")
    ledger = BudgetLedger(store, settings).for_user(user["id"])
    assert not ledger.enabled() and ledger.usage()["locked"]


def test_account_allowances_are_isolated_and_admin_has_no_cumulative_cap(ledger):
    bob = ledger.for_user(ledger.store.add_user("another-member", "unused-test-hash")["id"])
    admin = ledger.for_user(ledger.store.admin_user()["id"])
    set_committed_spend(ledger, 1_000_000)
    with pytest.raises(BudgetError, match="额度不足"):
        one_reservation(ledger)
    assert ledger.usage()["locked"] and ledger.usage()["remaining_usd"] == 0
    assert bob.usage()["spent_usd"] == 0 and bob.usage()["remaining_usd"] == 1
    assert one_reservation(bob)
    set_committed_spend(admin, 20_000_000)
    assert one_reservation(admin)
    usage = admin.usage()
    assert usage["unlimited"] and usage["is_admin"] and usage["role"] == "admin"
    assert usage["limit_usd"] is None and usage["remaining_usd"] is None
    assert usage["spent_usd"] == usage["lifetime_spent_usd"] == 20 and not usage["locked"]
    with ledger.store.connect() as db:
        assert ledger.current(db)["locked"] == 0


def test_admin_key_change_cannot_restore_ordinary_budget_or_erase_holds(ledger, monkeypatch):
    admin = ledger.for_user(ledger.store.admin_user()["id"])
    set_committed_spend(ledger, 700_000)
    rid = one_reservation(ledger)
    ledger.uncertain(rid, "unknown cost")
    before = ledger.usage()
    monkeypatch.setattr(ledger, "verify_key", lambda key: "validated-test-key")
    admin.authorize(KEY)
    after = ledger.usage()
    assert after == before
    with ledger.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM budget_epochs").fetchone()[0] == 2
    assert after["spent_usd"] == .7 and after["uncertain_usd"] > .01
    set_committed_spend(ledger, 300_000)
    with pytest.raises(BudgetError, match="额度不足"):
        one_reservation(ledger)
    admin.authorize(KEY)
    assert ledger.usage()["locked"] and ledger.usage()["remaining_usd"] == 0
    restarted = BudgetLedger(ledger.store, ledger.settings).for_user(ledger.user_id)
    restarted.recover()
    assert restarted.usage() == ledger.usage()


def test_ordinary_user_cannot_authorize_even_with_a_valid_key(ledger, monkeypatch):
    monkeypatch.setattr(ledger, "verify_key", lambda key: pytest.fail("ordinary user must not validate a shared key"))
    with pytest.raises(BudgetError, match="只有管理员"):
        ledger.authorize(KEY)
    with ledger.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM budget_epochs").fetchone()[0] == 1


def test_exhausted_user_never_contacts_catalog_or_reads_model_key(ledger, monkeypatch):
    set_committed_spend(ledger, 1_000_000)
    monkeypatch.setattr(ledger, "verify_catalog", lambda: pytest.fail("exhausted account must not contact provider"))
    monkeypatch.setattr(ledger, "credential", lambda epoch: pytest.fail("exhausted account must not read provider key"))
    with pytest.raises(BudgetError, match="额度不足"):
        one_reservation(ledger)


def test_unbound_and_cross_user_accounting_are_rejected(ledger):
    root = ledger._ledger
    other = ledger.for_user(ledger.store.add_user("another-member", "unused-test-hash")["id"])
    with pytest.raises(BudgetError, match="绑定"):
        root.prepare([])
    with pytest.raises(BudgetError, match="绑定"):
        root.usage()
    with pytest.raises(BudgetError, match="绑定"):
        root.authorize(KEY)
    with pytest.raises(BudgetError, match="不存在"):
        root.for_user("not-a-user")
    with pytest.raises(BudgetError, match="覆盖"):
        ledger.prepare([], user_id=other.user_id)
    rid = one_reservation(ledger)
    before = ledger.usage()
    for operation in [lambda: other.settle(rid, {"cost":".01"}),
                      lambda: other.uncertain(rid, "other user's error"),
                      lambda: other.rejected(rid, "other user's rejection"),
                      lambda: root.settle(rid, {"cost":".01"})]:
        with pytest.raises(BudgetError):
            operation()
    assert ledger.usage() == before and other.usage()["request_count"] == 0


def test_request_owner_must_match_job_and_inflight_other_user_blocks_key_change(ledger, monkeypatch):
    job = ledger.store.create_job(user_id=ledger.user_id)
    admin = ledger.for_user(ledger.store.admin_user()["id"])
    with pytest.raises(BudgetError, match="不匹配"):
        admin.prepare([], job["id"])
    rid, _ = ledger.prepare([], job["id"])
    with ledger.store.connect() as db:
        assert db.execute("SELECT user_id FROM model_requests WHERE id=?", (rid,)).fetchone()[0] == ledger.user_id
    monkeypatch.setattr(ledger, "verify_key", lambda key: "validated-test-key")
    with pytest.raises(BudgetError, match="正在结算"):
        admin.authorize(KEY)


def test_admin_is_still_locked_on_invalid_provider_cost_without_locking_others(ledger):
    admin = ledger.for_user(ledger.store.admin_user()["id"])
    rid = one_reservation(admin)
    assert admin.settle(rid, {"cost":"1e999999"}) is False
    usage = admin.usage()
    assert usage["unlimited"] and usage["locked"] and usage["uncertain_usd"] > .01
    assert not ledger.usage()["locked"] and one_reservation(ledger)


def test_request_terminal_states_and_tokens_are_not_changed_by_late_updates(ledger):
    rid = one_reservation(ledger)
    assert ledger.settle(rid, {"cost":".001", "prompt_tokens":13,"completion_tokens":17})
    before = ledger.usage()
    ledger.uncertain(rid, "late unknown response", locked=True)
    ledger.rejected(rid, "late rejection")
    assert ledger.settle(rid, {"cost":".9", "prompt_tokens":999})
    assert ledger.usage() == before


def test_legacy_costs_are_migrated_to_admin_without_resetting_history(ledger):
    with ledger.store.connect() as db:
        epoch = ledger.current(db)["id"]
        db.execute("DROP TABLE model_requests")
        db.execute("""CREATE TABLE model_requests (
            id TEXT PRIMARY KEY,epoch_id INTEGER NOT NULL,job_id TEXT,created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,state TEXT NOT NULL,reserved_micro INTEGER NOT NULL,
            cost_micro INTEGER NOT NULL DEFAULT 0,prompt_upper INTEGER NOT NULL,output_upper INTEGER NOT NULL,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,completion_tokens INTEGER NOT NULL DEFAULT 0,
            model TEXT NOT NULL,input_price TEXT NOT NULL,output_price TEXT NOT NULL,provider_id TEXT,error TEXT)""")
        db.execute("""INSERT INTO model_requests(id,epoch_id,job_id,created_at,updated_at,state,reserved_micro,
            cost_micro,prompt_upper,output_upper,prompt_tokens,completion_tokens,model,input_price,output_price,provider_id)
            VALUES('legacy-cost',?,NULL,'before','before','settled',30000,20680,10000,3200,36661,5225,
            'test/model','.132','.396','original-provider-id')""", (epoch,))
    migrated = BudgetLedger(ledger.store, ledger.settings)
    admin = migrated.for_user(ledger.store.admin_user()["id"])
    assert admin.usage()["spent_usd"] == .02068 and admin.usage()["prompt_tokens"] == 36661
    assert admin.usage()["request_count"] == 1 and admin.usage()["unlimited"]
    assert migrated.for_user(ledger.user_id).usage()["spent_usd"] == 0
    with ledger.store.connect() as db:
        row = db.execute("SELECT * FROM model_requests WHERE id='legacy-cost'").fetchone()
        assert row["user_id"] == admin.user_id and row["provider_id"] == "original-provider-id"
        assert row["cost_micro"] == 20680 and row["created_at"] == row["updated_at"] == "before"
    again = BudgetLedger(ledger.store, ledger.settings).for_user(admin.user_id)
    assert again.usage() == admin.usage()


def test_orphan_legacy_costs_fail_closed_at_start_until_admin_is_seeded(ledger):
    rid = one_reservation(ledger)
    ledger.settle(rid, {"cost":".02068"})
    with ledger.store.connect() as db:
        # The migrated legacy column is nullable; build that same old shape.
        db.execute("DROP INDEX idx_model_requests_user_state")
        db.execute("ALTER TABLE model_requests DROP COLUMN user_id")
        db.execute("DELETE FROM users WHERE role='admin'")
    restarted = BudgetLedger(ledger.store, ledger.settings)
    with pytest.raises(BudgetError, match="旧模型账单"):
        restarted.recover()
    with pytest.raises(BudgetError, match="旧模型账单"):
        restarted.for_user(ledger.user_id).prepare([])
    admin = ledger.store.seed_admin("restored-admin", "unused-test-hash")
    restarted.recover()
    assert restarted.for_user(admin["id"]).usage()["spent_usd"] == .02068
