"""Local account authentication; no shared-password or client role fallback."""

from collections import defaultdict
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
import unicodedata


ITERATIONS = 600_000
USERNAME = re.compile(r"[A-Za-z0-9_\u3400-\u9fff][A-Za-z0-9_.\-\u3400-\u9fff]{2,31}\Z")


def normalize_username(value):
    return unicodedata.normalize("NFKC", value).strip()


def hash_password(password):
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or not 600_000 <= int(iterations) <= 1_000_000:
            return False
        salt_bytes, expected_bytes = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt_bytes) < 16 or len(expected_bytes) != 32:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, int(iterations))
        return hmac.compare_digest(actual, expected_bytes)
    except (ValueError, TypeError, AttributeError):
        return False


class AuthService:
    def __init__(self, store, settings):
        self.store = store
        existing = store.admin_user()
        if existing:
            # Restart configuration never overwrites an existing identity.
            store.seed_admin(existing["username"])
        elif settings.admin_password:
            username = normalize_username(settings.admin_username)
            if not USERNAME.fullmatch(username) or not 10 <= len(settings.admin_password) <= 128:
                raise RuntimeError("管理员用户名或密码配置不符合账号安全要求。")
            try:
                store.seed_admin(username, hash_password(settings.admin_password))
            except sqlite3.IntegrityError as exc:
                raise RuntimeError("管理员种子用户名已被普通账号占用，请设置其他 ADMIN_USERNAME。") from exc
        if settings.cookie_secure and not store.admin_user():
            raise RuntimeError("生产账号服务尚未初始化管理员，请配置 ADMIN_USERNAME 和 ADMIN_PASSWORD。")
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))
        self.attempts = defaultdict(list)
        self.lock = threading.Lock()

    def check_rate(self, action, address, maximum, window, record=True):
        current = time.monotonic()
        key = (action, address)
        with self.lock:
            # Evict only expired keys; clearing an overloaded map would allow
            # attackers to erase an active throttle by adding new identities.
            if len(self.attempts) > 2048:
                for old_key in list(self.attempts):
                    self.attempts[old_key] = [entry for entry in self.attempts[old_key] if entry > current - 900]
                    if not self.attempts[old_key]:
                        del self.attempts[old_key]
            entries = [entry for entry in self.attempts[key] if entry > current - window]
            self.attempts[key] = entries
            if len(entries) >= maximum:
                return False
            if record:
                entries.append(current)
            return True

    def login(self, username, password):
        user = self.store.user_by_username(normalize_username(username))
        valid = verify_password(password, user["password_hash"] if user else self.dummy_hash)
        return user if valid and user else None

    def register(self, username, password):
        username = normalize_username(username)
        if not USERNAME.fullmatch(username):
            raise ValueError("用户名需为 3–32 位中英文、数字、下划线、点或短横线。")
        if not 10 <= len(password) <= 128:
            raise ValueError("密码长度需为 10–128 个字符。")
        return self.store.add_user(username, hash_password(password))
