"""Conservative OpenRouter reservations, owned by authenticated users.

Amounts are integer micro-US dollars, rounded UP from Decimal provider costs.
Unknown charges retain their full reservation permanently; no automatic paid retry.
Ordinary users have a lifetime $1 allowance; administrators have no cumulative cap.
Credential epochs are global and can never reset an ordinary user's allowance.
"""
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

import httpx

from .store import now

MICRO = Decimal(1_000_000)
USER_LIMIT_MICRO = 1_000_000
OPENROUTER = "https://openrouter.ai/api/v1"
MAX_OUTPUT_TOKENS = 3200


class BudgetError(ValueError):
    pass


class AuthorizationPending(BudgetError):
    pass


class KeyValidationUnavailable(BudgetError):
    pass


def decimal_amount(value):
    if isinstance(value, bool):
        raise ValueError("invalid amount")
    encoded = str(value)
    if len(encoded) > 128:
        raise ValueError("invalid amount")
    number = Decimal(encoded)
    if not number.is_finite() or number < 0:
        raise ValueError("invalid amount")
    return number


def micro_usd(value):
    amount = decimal_amount(value)
    if amount > Decimal("1000"):
        raise ValueError("implausible single-request cost")
    return int((amount * MICRO).to_integral_value(rounding=ROUND_CEILING))


def safe_tokens(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100_000_000:
        return 0
    return value


def bounded_json(response, maximum=1_000_000):
    if len(response.content) > maximum:
        raise ValueError("oversized provider response")
    return json.loads(response.content, parse_float=Decimal)


class UserBudgetLedger:
    """Bind all accounting operations to one server-validated user ID."""
    _bound_methods = {"usage", "prepare", "settle", "uncertain", "rejected", "last_error", "authorize", "budget_note"}

    def __init__(self, ledger, user_id):
        object.__setattr__(self, "_ledger", ledger)
        object.__setattr__(self, "user_id", user_id)

    def __getattr__(self, name):
        value = getattr(self._ledger, name)
        if name not in self._bound_methods:
            return value
        def bound(*args, **kwargs):
            if "user_id" in kwargs:
                raise BudgetError("不能覆盖已绑定的模型计费账户。")
            return value(*args, user_id=self.user_id, **kwargs)
        return bound

    def __setattr__(self, name, value):
        if name in {"_ledger", "user_id"}:
            raise AttributeError("accounting identity is immutable")
        setattr(self._ledger, name, value)


class BudgetLedger:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.secret_dir = settings.data_dir / "model-secrets"
        self.secret_dir.mkdir(mode=0o700, exist_ok=True)
        self.secret_dir.chmod(0o700)
        self.catalog_lock = threading.Lock()
        self.catalog_until = 0
        self.catalog_names = set()
        self.key_validation = {}
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS budget_epochs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
                    secret_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    authorized_by TEXT NOT NULL, limit_micro INTEGER NOT NULL,
                    locked INTEGER NOT NULL DEFAULT 0, last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS model_requests (
                    id TEXT PRIMARY KEY, epoch_id INTEGER NOT NULL, job_id TEXT,
                    user_id TEXT NOT NULL REFERENCES users(id),
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    state TEXT NOT NULL, reserved_micro INTEGER NOT NULL,
                    cost_micro INTEGER NOT NULL DEFAULT 0, prompt_upper INTEGER NOT NULL,
                    output_upper INTEGER NOT NULL, prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    model TEXT NOT NULL, input_price TEXT NOT NULL, output_price TEXT NOT NULL,
                    provider_id TEXT, error TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_model_requests_epoch ON model_requests(epoch_id);
                CREATE TABLE IF NOT EXISTS model_user_state (
                    user_id TEXT PRIMARY KEY REFERENCES users(id),
                    locked INTEGER NOT NULL DEFAULT 0, last_error TEXT
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(model_requests)")}
            if "user_id" not in columns:
                db.execute("ALTER TABLE model_requests ADD COLUMN user_id TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS idx_model_requests_user_state ON model_requests(user_id,state)")
            # Old cumulative $5 exhaustion is obsolete. Other financial-safety
            # locks remain fail-closed until an administrator replaces the key.
            db.execute("UPDATE budget_epochs SET locked=0,last_error=NULL WHERE locked=1 AND last_error LIKE '当前 $5 额度不足%'")
            self._migrate_ownership(db, require_admin=False)
        # Bootstrap exactly once. Restarting, changing the environment key, or
        # deleting analysis jobs can never reset an existing authorization epoch.
        if settings.llm_key and self.configured():
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                if not self.current(db):
                    self._new_epoch(db, settings.llm_key, "initial_environment")

    @staticmethod
    def _user(db, user_id):
        if not isinstance(user_id, str) or not user_id:
            raise BudgetError("模型账本必须绑定已登录账户。")
        user = db.execute("SELECT id,username,role FROM users WHERE id=?", (user_id,)).fetchone()
        if not user or user["role"] not in {"admin", "user"}:
            raise BudgetError("模型账户不存在或无效，请重新登录。")
        return user

    @staticmethod
    def _migrate_ownership(db, require_admin=True):
        if not db.execute("SELECT 1 FROM model_requests WHERE user_id IS NULL LIMIT 1").fetchone():
            return
        admin = db.execute("SELECT id FROM users WHERE role='admin' ORDER BY created_at,id LIMIT 1").fetchone()
        if admin:
            db.execute("UPDATE model_requests SET user_id=? WHERE user_id IS NULL", (admin["id"],))
        elif require_admin:
            raise BudgetError("旧模型账单尚未归属管理员；请先配置管理员账户后启动服务。")

    def for_user(self, user_id):
        with self.store.connect() as db:
            self._user(db, user_id)
        return UserBudgetLedger(self, user_id)

    @staticmethod
    def _state(db, user_id):
        row = db.execute("SELECT locked,last_error FROM model_user_state WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else {"locked": 0, "last_error": None}

    @staticmethod
    def _set_error(db, user_id, message, locked=False):
        db.execute("""INSERT INTO model_user_state(user_id,locked,last_error) VALUES(?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET last_error=excluded.last_error,
            locked=MAX(model_user_state.locked,excluded.locked)""", (user_id, int(locked), message))

    def configured(self):
        try:
            a, b = self.prices()
            providers = self.providers()
            return (self.settings.llm_base_url.rstrip("/") == OPENROUTER
                    and bool(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.:-]+", self.settings.llm_model))
                    and bool(providers) and a > 0 and b > 0)
        except (ValueError, InvalidOperation):
            return False

    def prices(self):
        a = decimal_amount(self.settings.llm_input_price)
        b = decimal_amount(self.settings.llm_output_price)
        if a > 1000 or b > 1000:
            raise ValueError("unsafe price cap")
        return a, b

    def providers(self):
        names = [part.strip() for part in self.settings.llm_provider_only.split(",") if part.strip()]
        if not names or len(names) > 5 or any(not re.fullmatch(r"[a-z0-9][a-z0-9_/-]{0,79}", name) for name in names):
            raise ValueError("invalid provider allowlist")
        return names

    @staticmethod
    def current(db):
        return db.execute("SELECT * FROM budget_epochs ORDER BY id DESC LIMIT 1").fetchone()

    def _new_epoch(self, db, key, authorization):
        secret_id = uuid4().hex
        path = self.secret_dir / (secret_id + ".key")
        temporary = self.secret_dir / (secret_id + ".tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(key)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        fingerprint = hashlib.sha256(key.encode()).hexdigest()
        db.execute("INSERT INTO budget_epochs(created_at,secret_id,fingerprint,authorized_by,limit_micro) VALUES(?,?,?,?,?)",
                   (now(), secret_id, fingerprint, authorization, 0))

    def recover(self):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._migrate_ownership(db)
            db.execute("UPDATE model_requests SET state='uncertain', updated_at=?, error=? WHERE state='pending'",
                       (now(), "服务重启前的调用账单未确认，保留全部预留费用。"))

    def credential(self, epoch):
        path = self.secret_dir / (epoch["secret_id"] + ".key")
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise BudgetError("服务端模型密钥不可读，请重新输入密钥授权。") from exc

    def enabled(self):
        if not self.configured():
            return False
        with self.store.connect() as db:
            epoch = self.current(db)
        return bool(epoch and (self.secret_dir / (epoch["secret_id"] + ".key")).is_file())

    @staticmethod
    def totals(db, user_id):
        row = db.execute("""SELECT
            COALESCE(SUM(CASE WHEN state='settled' THEN cost_micro ELSE 0 END),0) spent,
            COALESCE(SUM(CASE WHEN state='pending' THEN reserved_micro ELSE 0 END),0) reserved,
            COALESCE(SUM(CASE WHEN state='uncertain' THEN reserved_micro ELSE 0 END),0) uncertain,
            COALESCE(SUM(prompt_tokens),0) prompt_tokens,
            COALESCE(SUM(completion_tokens),0) completion_tokens, COUNT(*) request_count
            FROM model_requests WHERE user_id=?""", (user_id,)).fetchone()
        return dict(row)

    def usage(self, *, user_id=None):
        with self.store.connect() as db:
            user = self._user(db, user_id)
            epoch = self.current(db)
            totals = self.totals(db, user_id)
            state = self._state(db, user_id)
        unlimited = user["role"] == "admin"
        available = None if unlimited else max(0, USER_LIMIT_MICRO-totals["spent"]-totals["reserved"]-totals["uncertain"])
        configured = self.configured()
        a, b = self.prices() if configured else (None, None)
        error = state["last_error"]
        if not epoch:
            error = "服务端尚未配置模型密钥，请联系管理员；统计分析仍可使用。"
        elif epoch["locked"] and not error:
            error = "服务端模型因账单异常暂停，请管理员核对。"
        return {"currency": "USD", "user_id": user_id, "role": user["role"], "is_admin": unlimited, "unlimited": unlimited,
                "limit_usd": None if unlimited else 1, "spent_usd": totals["spent"] / 1_000_000,
                "reserved_usd": totals["reserved"] / 1_000_000, "uncertain_usd": totals["uncertain"] / 1_000_000,
                "remaining_usd": None if unlimited else available / 1_000_000,
                "locked": not self.enabled() or not epoch or bool(epoch["locked"]) or bool(state["locked"]) or (not unlimited and available <= 0),
                "model": self.settings.llm_model or None, "input_per_million_usd": float(a) if a is not None else None,
                "output_per_million_usd": float(b) if b is not None else None,
                "prompt_tokens": totals["prompt_tokens"], "completion_tokens": totals["completion_tokens"],
                "request_count": totals["request_count"], "lifetime_spent_usd": totals["spent"] / 1_000_000,
                "last_error": error}

    def last_error(self, message, locked=False, *, user_id=None):
        with self.store.connect() as db:
            self._user(db, user_id)
            self._set_error(db, user_id, message, locked)

    def budget_note(self, *, user_id=None):
        with self.store.connect() as db:
            user = self._user(db, user_id)
        if user["role"] == "admin":
            return "费用按 OpenRouter usage.cost 向上取整到微美元入账；管理员不设应用内累计额度上限，仍执行单价和账单安全检查。"
        return "费用按 OpenRouter usage.cost 向上取整到微美元入账；本账户累计模型额度为 $1，换密钥或重启不会恢复额度。"

    def verify_key(self, key):
        if not isinstance(key, str) or not 20 <= len(key) <= 1000 or not key.startswith("sk-or-") or any(c.isspace() for c in key):
            raise BudgetError("请输入有效的 OpenRouter API 密钥。")
        try:
            with httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=False) as client:
                response = client.get(OPENROUTER + "/key", headers={"Authorization": "Bearer " + key})
                if response.status_code in {401, 403}:
                    raise BudgetError("OpenRouter 密钥验证失败，请检查后重新输入。")
                response.raise_for_status()
                body = bounded_json(response, 64_000)
            if not isinstance(body, dict) or not isinstance(body.get("data"), dict) or body["data"].get("is_management_key") is True:
                raise BudgetError("该密钥不能用于模型调用，请输入有效的 OpenRouter 推理密钥。")
        except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
            if isinstance(exc, BudgetError):
                raise
            raise KeyValidationUnavailable("暂时无法验证 OpenRouter 密钥，未更新服务端密钥，请稍后重试。") from exc
        return hashlib.sha256(key.encode()).hexdigest()

    def authorize(self, key, *, user_id=None):
        with self.store.connect() as db:
            if self._user(db, user_id)["role"] != "admin":
                raise BudgetError("只有管理员可以配置服务端模型密钥，普通账户额度不能重新授权。")
        if not self.configured():
            raise BudgetError("服务端模型、指定提供商和单价上限尚未完整配置。")
        key = key.strip()
        fingerprint = self.verify_key(key)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM model_requests WHERE state='pending' LIMIT 1").fetchone():
                raise AuthorizationPending("仍有模型调用正在结算，请完成后再更换服务端密钥。")
            self._new_epoch(db, key, "admin_key_update:" + user_id)
            db.execute("UPDATE model_user_state SET locked=0,last_error=NULL WHERE user_id=?", (user_id,))
        self.key_validation[fingerprint] = time.monotonic() + 600
        return self.usage(user_id=user_id)

    def verify_catalog(self):
        with self.catalog_lock:
            if self.catalog_until > time.monotonic():
                return
            try:
                with httpx.Client(timeout=httpx.Timeout(12, connect=5), follow_redirects=False) as client:
                    response = client.get(OPENROUTER + "/models/" + self.settings.llm_model + "/endpoints")
                    response.raise_for_status()
                    document = bounded_json(response, 2_000_000)
                endpoints = document["data"]["endpoints"]
                if not isinstance(endpoints, list) or len(endpoints) > 200:
                    raise ValueError("invalid endpoint catalog")
                a, b = self.prices()
                matches, names = {}, set()
                for endpoint in endpoints[:200]:
                    if not isinstance(endpoint, dict):
                        raise ValueError("invalid endpoint")
                    if endpoint.get("tag") not in self.providers():
                        continue
                    pricing = endpoint["pricing"]
                    if (decimal_amount(pricing["prompt"]) * MICRO > a
                            or decimal_amount(pricing["completion"]) * MICRO > b):
                        raise BudgetError("指定提供商的实时单价超过已授权上限，已停止模型调用。")
                    if pricing.get("overrides"):
                        raise BudgetError("指定提供商使用动态时段价格，无法安全确认上限，已停止模型调用。")
                    # Text-only inference must not have extra per-request/tool charges.
                    for field in ("request", "image", "web_search", "internal_reasoning", "input_cache_write"):
                        if field in pricing and decimal_amount(pricing[field]) > 0:
                            raise BudgetError("指定端点包含额外计费项目，已停止模型调用。")
                    supported = set(endpoint.get("supported_parameters", []))
                    if not {"max_tokens", "response_format", "reasoning_effort"} <= supported:
                        raise BudgetError("指定提供商不能完整执行输出与推理限制，已停止模型调用。")
                    matches[endpoint["tag"]] = True
                    names.add(str(endpoint["provider_name"]))
                if set(matches) != set(self.providers()):
                    raise BudgetError("未找到全部指定模型提供商，已停止模型调用，不会切换模型。")
                self.catalog_names, self.catalog_until = names, time.monotonic() + 300
            except (httpx.HTTPError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
                if isinstance(exc, BudgetError):
                    raise
                raise BudgetError("无法核验指定模型的实时单价，已停止模型调用。") from exc

    def _check_allowance(self, db, user_id, epoch, reservation):
        user = self._user(db, user_id)
        state = self._state(db, user_id)
        if epoch["locked"] or state["locked"]:
            raise BudgetError(state["last_error"] or "模型调用因费用安全检查暂停，请联系管理员。")
        totals = self.totals(db, user_id)
        remaining = USER_LIMIT_MICRO-totals["spent"]-totals["reserved"]-totals["uncertain"]
        if user["role"] != "admin" and reservation > remaining:
            message = "本账户累计 $1 额度不足以安全预留本次调用，模型调用已停止；额度不会因重启、删除报告或更换密钥恢复，统计分析仍可使用。"
            self._set_error(db, user_id, message, locked=True)
            db.commit()
            raise BudgetError(message)

    def prepare(self, messages, job_id=None, *, user_id=None):
        # Identity and legacy ownership are checked before any provider request.
        with self.store.connect() as db:
            self._user(db, user_id)
            self._migrate_ownership(db)
        if not self.enabled():
            raise BudgetError("OpenRouter 模型、密钥或单价上限尚未完整配置，使用统计分析模式。")
        input_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
        prompt_upper = input_bytes * 2 + 8192
        a, b = self.prices()
        # Prices are USD per million tokens, so token_count * price is microUSD.
        reservation = 10_000 + int((Decimal(prompt_upper) * a + MAX_OUTPUT_TOKENS * b).to_integral_value(rounding=ROUND_CEILING))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            epoch = self.current(db)
            self._check_allowance(db, user_id, epoch, reservation)
        # Do not even contact the provider for an already exhausted account.
        # Recheck atomically after these readonly calls, before reserving funds.
        self.verify_catalog()
        key = self.credential(epoch)
        if self.key_validation.get(epoch["fingerprint"], 0) <= time.monotonic():
            self.verify_key(key)
            self.key_validation[epoch["fingerprint"]] = time.monotonic() + 600
        request_id = uuid4().hex
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self.current(db)
            if not current or current["id"] != epoch["id"]:
                raise BudgetError("模型授权状态已更新，请重新提交分析。")
            if job_id is not None:
                job = db.execute("SELECT user_id FROM jobs WHERE id=?", (job_id,)).fetchone()
                if not job or job["user_id"] != user_id:
                    raise BudgetError("分析任务与模型计费账户不匹配。")
            self._check_allowance(db, user_id, current, reservation)
            db.execute("""INSERT INTO model_requests
                (id,epoch_id,job_id,user_id,created_at,updated_at,state,reserved_micro,prompt_upper,output_upper,model,input_price,output_price)
                VALUES(?,?,?,?,?,?,'pending',?,?,?,?,?,?)""", (request_id, epoch["id"], job_id, user_id, now(), now(),
                    reservation, prompt_upper, MAX_OUTPUT_TOKENS, self.settings.llm_model, str(a), str(b)))
        return request_id, key

    @staticmethod
    def _request(db, request_id, user_id):
        BudgetLedger._user(db, user_id)
        row = db.execute("SELECT * FROM model_requests WHERE id=? AND user_id=?", (request_id, user_id)).fetchone()
        if not row:
            raise BudgetError("模型请求不属于当前计费账户。")
        return row

    def settle(self, request_id, usage, provider_id=None, *, user_id=None):
        with self.store.connect() as db:
            self._request(db, request_id, user_id)
        if not isinstance(usage, dict) or "cost" not in usage:
            self.uncertain(request_id, "OpenRouter 未返回可核验费用，保留全部预留费用。", user_id=user_id)
            return False
        try:
            cost = micro_usd(usage["cost"])
        except (ValueError, InvalidOperation, TypeError, OverflowError):
            self.uncertain(request_id, "OpenRouter 返回费用无效，保留全部预留费用并锁定模型，请人工核查账单。", locked=True, user_id=user_id)
            return False
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._request(db, request_id, user_id)
            if row["state"] != "pending":
                return row["state"] == "settled"
            db.execute("""UPDATE model_requests SET state='settled',cost_micro=?,prompt_tokens=?,completion_tokens=?,provider_id=?,updated_at=? WHERE id=?""",
                       (cost, safe_tokens(usage.get("prompt_tokens")), safe_tokens(usage.get("completion_tokens")),
                        str(provider_id)[:160] if provider_id else None, now(), request_id))
            if cost > row["reserved_micro"]:
                self._set_error(db, user_id, "提供商返回费用超过保守预留，已锁定本账户模型；请先人工核对账单。", locked=True)
                return False
            db.execute("UPDATE model_user_state SET last_error=NULL WHERE user_id=? AND locked=0", (user_id,))
        return True

    def uncertain(self, request_id, message, locked=False, *, user_id=None):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._request(db, request_id, user_id)
            if row["state"] != "pending":
                return
            db.execute("UPDATE model_requests SET state='uncertain',error=?,updated_at=? WHERE id=? AND state='pending'",
                       (message, now(), request_id))
            self._set_error(db, user_id, message, locked)

    def rejected(self, request_id, message, *, user_id=None):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._request(db, request_id, user_id)
            if row["state"] != "pending":
                return
            db.execute("UPDATE model_requests SET state='rejected',error=?,updated_at=? WHERE id=? AND state='pending'", (message, now(), request_id))
            self._set_error(db, user_id, message)
