import hashlib
import json
import sqlite3

import pytest

from app.auth import AuthService, hash_password, verify_password
from app.config import Settings
from app.store import Store


def configured(tmp_path, **kwargs):
    return Settings(data_dir=tmp_path, admin_username="admin", admin_password="safe-admin-password",
                    session_secret="s" * 40, **kwargs)


def test_password_hash_is_salted_strong_and_verifies_unicode():
    password = "A long 密码 with spaces 123"
    first, second = hash_password(password), hash_password(password)
    assert first != second and password not in first
    algorithm, iterations, salt, derived = first.split("$")
    assert algorithm == "pbkdf2_sha256" and int(iterations) >= 600_000
    assert len(bytes.fromhex(salt)) >= 16 and len(bytes.fromhex(derived)) == 32
    assert verify_password(password, first) and not verify_password("wrong", first)
    assert not verify_password(password, "broken")
    assert not verify_password(password, first.replace("600000", "1000000000"))


def test_registered_identity_is_fixed_user_and_case_insensitive(tmp_path):
    settings = configured(tmp_path)
    settings.validate()
    store = Store(tmp_path)
    auth = AuthService(store, settings)
    user = auth.register("Alice_01", "strong-new-user-password")
    assert user["role"] == "user" and len(user["id"]) == 32
    assert auth.login("alice_01", "strong-new-user-password")["id"] == user["id"]
    assert auth.login("Alice_01", "wrong") is None
    assert auth.login("nobody", "strong-new-user-password") is None
    with pytest.raises(sqlite3.IntegrityError):
        auth.register("ALICE_01", "another-strong-password")
    assert set(store.public_user(user)) == {"id", "username", "role"}


@pytest.mark.parametrize("username,password", [
    ("aa", "long-enough-password"), ("../evil", "long-enough-password"),
    ("normal_user", "short"), ("normal_user", "x" * 129),
])
def test_registration_rejects_invalid_credentials(tmp_path, username, password):
    settings = configured(tmp_path)
    settings.validate()
    auth = AuthService(Store(tmp_path), settings)
    with pytest.raises(ValueError):
        auth.register(username, password)


def test_production_settings_require_persistent_secret_and_admin(tmp_path):
    settings = Settings(data_dir=tmp_path, cookie_secure=True)
    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        settings.validate()
    settings.session_secret = "s" * 40
    settings.validate()
    with pytest.raises(RuntimeError, match="管理员"):
        AuthService(Store(tmp_path), settings)


def test_legacy_schema_and_reports_migrate_once_without_resetting_admin(tmp_path):
    """Real pre-account table layout; migration must preserve records and files."""
    settings = configured(tmp_path)
    settings.validate()
    source = tmp_path / "uploads" / "legacy.csv"
    source.write_text("metric\n12\n", encoding="utf-8")
    result_dir = tmp_path / "results" / "legacy-report"
    result_dir.mkdir()
    result_path = result_dir / "result.json"
    result_path.write_text(json.dumps({"original": True}), encoding="utf-8")
    original_digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    with sqlite3.connect(tmp_path / "studio.sqlite3") as db:
        db.executescript("""
            CREATE TABLE uploads(id TEXT PRIMARY KEY,filename TEXT NOT NULL,path TEXT NOT NULL,files TEXT NOT NULL,created_at TEXT NOT NULL);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,upload_id TEXT,selected_file TEXT,filename TEXT NOT NULL,created_at TEXT NOT NULL,status TEXT NOT NULL,progress INTEGER NOT NULL,goal TEXT NOT NULL,is_demo INTEGER NOT NULL,error TEXT,steps TEXT NOT NULL,use_llm INTEGER NOT NULL,target_column TEXT);
        """)
        db.execute("INSERT INTO uploads VALUES (?,?,?,?,?)", ("legacy", "legacy.csv", str(source), "[]", "2026-01-01"))
        db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            "legacy-report", "legacy", "legacy.csv", "legacy.csv", "2026-01-01", "completed", 100,
            "original goal", 0, None, "[]", 1, "metric"))
    store = Store(tmp_path)
    AuthService(store, settings)
    admin = store.admin_user()
    assert store.get_job("legacy-report")["user_id"] == admin["id"]
    assert store.upload("legacy")["user_id"] == admin["id"]
    user = store.add_user("ordinary", hash_password("ordinary-password"))
    owned = store.create_job(filename="owned.csv", user_id=user["id"])
    original_hash = admin["password_hash"]
    settings.admin_username, settings.admin_password = "different_admin", "different-password"
    auth = AuthService(store, settings)
    assert store.admin_user()["id"] == admin["id"]
    assert store.admin_user()["password_hash"] == original_hash
    assert auth.login("admin", "safe-admin-password")
    assert auth.login("different_admin", "different-password") is None
    assert store.get_job(owned["id"])["user_id"] == user["id"]
    assert store.get_job("legacy-report")["result"] == {"original": True}
    assert hashlib.sha256(result_path.read_bytes()).hexdigest() == original_digest
    assert source.read_text() == "metric\n12\n"
