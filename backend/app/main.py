from contextlib import asynccontextmanager
import logging
from pathlib import Path
import queue
import secrets
import shutil
import sqlite3
import threading
import time
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from pydantic import BaseModel, Field, SecretStr, StrictBool, StrictStr, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from .analysis import analyze
from .auth import AuthService
from .billing import BudgetLedger, BudgetError, AuthorizationPending, KeyValidationUnavailable
from .config import Settings
from .ingest import DatasetError, demo_dataset, inspect_upload, read_dataset
from .llm import enrich
from .report import save_reports
from .store import Store

logger = logging.getLogger("insight-studio")
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
COOKIE = "insight_session"


class UploadLimitMiddleware:
    """Bound the body while streaming, before multipart parsing or spooling."""
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = self.max_bytes + 1024 * 1024 if scope["path"] == "/api/uploads" else 64 * 1024
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = limit + 1
        if declared > limit:
            return await JSONResponse({"detail": "请求内容过大；单个文件最多 50 MB。"}, 413)(scope, receive, send)
        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    raise HTTPException(413, "请求内容过大；单个文件最多 50 MB。")
            return message

        return await self.app(scope, limited_receive, send)


class JobRequest(BaseModel):
    upload_id: str = Field(min_length=1, max_length=64)
    selected_file: str = Field(min_length=1, max_length=1000)
    goal: str = Field(default="", max_length=2000)
    use_llm: bool = False
    target_column: str | None = Field(default=None, max_length=200)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: StrictStr = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=128)


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_llm: StrictBool = False


class ModelAuthorizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: SecretStr
    confirm_budget: StrictBool = False


class JobManager:
    def __init__(self, store, settings, ledger):
        self.store, self.settings = store, settings
        self.ledger = ledger
        self.tasks = queue.Queue(maxsize=4)
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.worker = threading.Thread(target=self.run, name="analysis-worker", daemon=True)

    def start(self):
        self.store.recover()
        self.ledger.recover()
        self.worker.start()

    def submit(self, **kwargs):
        with self.lock:
            if self.stopping.is_set() or self.store.active_count() >= self.settings.max_active_jobs or self.tasks.full():
                raise HTTPException(429, "当前分析队列已满，请等待已有任务完成后再提交。")
            if not kwargs.get("user_id") or not self.store.user(kwargs["user_id"]):
                raise HTTPException(401, "请先登录账号。")
            if kwargs.get("upload_id") and not self.store.upload(kwargs["upload_id"], kwargs["user_id"]):
                raise HTTPException(404, "原始上传文件已不存在，请重新上传。")
            job = self.store.create_job(**kwargs)
            self.tasks.put_nowait(job["id"])
            return self.store.public(job)

    def stop(self):
        self.stopping.set()
        self.worker.join(timeout=2)

    def run(self):
        while not self.stopping.is_set():
            try:
                jid = self.tasks.get(timeout=.3)
            except queue.Empty:
                continue
            try:
                self.execute(jid)
            except Exception as exc:
                # Do not log provider responses, dataset content, paths or credentials.
                logger.error("Analysis failed: job=%s type=%s", jid, type(exc).__name__)
                job = self.store.get_job(jid, False)
                if job:
                    steps = job["steps"]
                    for step in steps:
                        if step["status"] == "running":
                            step["status"], step["detail"] = "failed", "此步骤未完成，可检查数据后重试。"
                    message = str(exc) if isinstance(exc, DatasetError) else "分析未能完成。请确认数据格式与数值范围，或稍后重试。"
                    self.store.update(jid, status="failed", error=message, steps=steps)
            finally:
                self.tasks.task_done()

    def execute(self, jid):
        started = time.monotonic()
        job = self.store.get_job(jid, False)
        steps = job["steps"]

        def progress(key, detail):
            index = next(i for i, step in enumerate(steps) if step["key"] == key)
            for i, step in enumerate(steps):
                if i < index:
                    step["status"] = "completed"
                elif i == index:
                    step["status"], step["detail"] = "running", detail
            self.store.update(jid, status="running", progress=5 + index * 15, steps=steps)

        progress("read", "安全读取所选数据表；识别编码与分析范围。")
        if job["is_demo"]:
            df, source = demo_dataset()
        else:
            upload = self.store.upload(job["upload_id"], job["user_id"])
            if not upload or not Path(upload["path"]).exists():
                raise DatasetError("原始上传文件已不存在，请重新上传。")
            df, source = read_dataset(Path(upload["path"]), upload["filename"], job["selected_file"],
                                      self.settings.max_rows, self.settings.max_columns)
        result, aggregates = analyze(df, source, job["goal"], job["target_column"], progress)
        if job["use_llm"]:
            enrich(result, aggregates, job["goal"], job["target_column"], self.settings,
                   self.ledger.for_user(job["user_id"]), jid)
        else:
            result["agent"]["notes"].append("本次未启用外部模型，使用可复算的统计规则生成洞察。")
        progress("report", "保存分析结果和离线 HTML / Markdown 报告。")
        result["duration_seconds"] = round(time.monotonic() - started, 2)
        save_reports(self.store.result_dir(jid), result, job["goal"])
        for step in steps:
            step["status"] = "completed"
        steps[-1]["detail"] = "看板与两种格式报告已生成。"
        self.store.update(jid, status="completed", progress=100, steps=steps, error=None)


class SPAFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path.startswith("api/") or path == "api":
            raise StarletteHTTPException(404)
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)


def create_app(settings=None):
    settings = settings or Settings()
    settings.validate()
    store = Store(settings.data_dir)
    auth = AuthService(store, settings)
    ledger = BudgetLedger(store, settings)
    manager = JobManager(store, settings, ledger)
    signer = URLSafeTimedSerializer(settings.session_secret or secrets.token_hex(32), salt="insight-studio-accounts-v2")

    @asynccontextmanager
    async def lifespan(application):
        manager.start()
        yield
        manager.stop()

    app = FastAPI(title="Insight Studio", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.manager, app.state.settings = store, manager, settings
    app.state.ledger, app.state.auth = ledger, auth
    app.add_middleware(UploadLimitMiddleware, max_bytes=settings.max_upload_bytes)
    app.add_middleware(CORSMiddleware, allow_origins=sorted(DEV_ORIGINS), allow_credentials=True,
                       allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Pydantic's default error payload includes raw inputs, which may contain
        # a re-entered API key. Return no input values, even for malformed JSON.
        return JSONResponse({"detail": "请求参数格式不正确，请检查必填字段及字段类型。"}, 422)

    def authenticated_user(request):
        token = request.cookies.get(COOKIE)
        if not token:
            return None
        try:
            payload = signer.loads(token, max_age=7 * 24 * 3600)
            if not isinstance(payload, dict) or not isinstance(payload.get("uid"), str) or type(payload.get("v")) is not int:
                return None
            user = store.user(payload["uid"])
            return user if user and user["session_version"] == payload["v"] else None
        except (BadSignature, SignatureExpired):
            return None

    @app.middleware("http")
    async def guard(request, call_next):
        path = request.url.path
        request.state.user = authenticated_user(request)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                host = request.headers.get("host", "")
                same_origin = parsed.scheme in {"http", "https"} and parsed.netloc == host
                # Development origins are permitted only when the API itself is on loopback.
                api_local = request.url.hostname in {"localhost", "127.0.0.1", "testserver"}
                if not same_origin and not (api_local and origin in DEV_ORIGINS):
                    return JSONResponse({"detail": "请求来源不受信任，请从系统页面发起操作。"}, 403)
        public = {"/api/health", "/api/session", "/api/login", "/api/register", "/api/logout"}
        if path.startswith("/api/") and path not in public and request.method != "OPTIONS" and not request.state.user:
            return JSONResponse({"detail": "请先登录账号。"}, 401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def session(request):
        user = request.state.user
        return {"auth_required": True, "authenticated": bool(user), "user": store.public_user(user) if user else None,
                "model_enabled": ledger.enabled(), "model_name": settings.llm_model if ledger.enabled() else None,
                "limits": {"max_upload_mb": 50, "max_rows": settings.max_rows, "max_columns": settings.max_columns}}

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/session")
    def get_session(request: Request):
        return session(request)

    @app.post("/api/login")
    def login(body: LoginRequest, request: Request, response: Response):
        address = request.client.host if request.client else "unknown"
        if not auth.check_rate("login", address, 5, 300):
            raise HTTPException(429, "尝试次数过多，请在 5 分钟后重试。")
        user = auth.login(body.username, body.password.get_secret_value())
        if not user:
            raise HTTPException(401, "用户名或密码不正确。")
        return set_session(user, request, response)

    def set_session(user, request, response):
        response.set_cookie(COOKIE, signer.dumps({"uid": user["id"], "v": user["session_version"]}),
                            httponly=True, secure=settings.cookie_secure, samesite="strict", max_age=7 * 24 * 3600, path="/")
        request.state.user = user
        return session(request)

    @app.post("/api/register")
    def register(body: LoginRequest, request: Request, response: Response):
        address = request.client.host if request.client else "unknown"
        if not auth.check_rate("register", address, 5, 900):
            raise HTTPException(429, "注册尝试过于频繁，请在 15 分钟后重试。")
        try:
            user = auth.register(body.username, body.password.get_secret_value())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, "该用户名已被使用，请选择其他用户名。") from exc
        return set_session(user, request, response)

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE, path="/", secure=settings.cookie_secure, httponly=True, samesite="strict")
        return {"ok": True}

    @app.get("/api/usage")
    def usage(request: Request):
        return ledger.for_user(request.state.user["id"]).usage()

    @app.post("/api/model/authorize")
    def authorize_model(body: ModelAuthorizationRequest, request: Request):
        if request.state.user["role"] != "admin":
            raise HTTPException(403, "仅管理员可以配置模型密钥。")
        if body.confirm_budget is not True:
            raise HTTPException(400, "请明确确认授权使用此模型密钥。")
        try:
            return ledger.for_user(request.state.user["id"]).authorize(body.api_key.get_secret_value())
        except AuthorizationPending as exc:
            raise HTTPException(409, str(exc)) from exc
        except KeyValidationUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        except BudgetError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/uploads")
    async def upload(request: Request, file: UploadFile = File(...)):
        filename = Path((file.filename or "dataset.csv").replace("\\", "/")).name
        if not filename or len(filename) > 240 or any(ord(c) < 32 for c in filename):
            raise HTTPException(400, "文件名无效或过长。")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".csv", ".tsv", ".xlsx", ".zip"}:
            raise HTTPException(400, "支持 CSV、TSV、XLSX 或包含表格的 ZIP 文件。")
        destination = settings.data_dir / "uploads" / (uuid4().hex + suffix)
        total = 0
        try:
            with destination.open("wb") as output:
                destination.chmod(0o600)
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise HTTPException(413, "上传文件超过 50 MB，请拆分或压缩数据。")
                    output.write(chunk)
            files = inspect_upload(destination, filename)
            return store.add_upload(filename, destination, files, request.state.user["id"])
        except DatasetError as exc:
            destination.unlink(missing_ok=True)
            raise HTTPException(400, str(exc)) from exc
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    @app.get("/api/jobs")
    def jobs(request: Request):
        return {"jobs": store.list_jobs(request.state.user["id"])}

    @app.get("/api/uploads/{uid}/schema")
    def upload_schema(uid: str, selected_file: str, request: Request):
        upload = store.upload(uid, request.state.user["id"])
        if not upload:
            raise HTTPException(404, "未找到上传文件，请重新上传。")
        try:
            df, source = read_dataset(Path(upload["path"]), upload["filename"], selected_file,
                                      settings.max_rows, settings.max_columns)
            from .explanations import schema_description
            return schema_description(df, source)
        except DatasetError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/jobs")
    def create_job(body: JobRequest, request: Request):
        upload = store.upload(body.upload_id, request.state.user["id"])
        if not upload:
            raise HTTPException(404, "未找到上传文件，请重新上传。")
        if body.selected_file not in {item["name"] for item in upload["files"]}:
            raise HTTPException(400, "请从上传文件列表中选择有效数据表。")
        return manager.submit(upload_id=body.upload_id, selected_file=body.selected_file,
                              filename=body.selected_file, goal=body.goal, use_llm=body.use_llm, target_column=body.target_column,
                              user_id=request.state.user["id"])

    @app.post("/api/demo")
    def demo(request: Request):
        return manager.submit(filename="合成零售演示数据.csv", is_demo=True,
                              goal="探索销售额、利润及地区与品类表现，检查数据质量并提出可验证的建议。", target_column="销售额", user_id=request.state.user["id"])

    def required_job(jid, request, result=True):
        job = store.get_job(jid, result, request.state.user["id"])
        if not job:
            raise HTTPException(404, "未找到此分析任务。")
        return job

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str, request: Request):
        return store.public(required_job(jid, request))

    @app.post("/api/jobs/{jid}/retry")
    def retry(jid: str, request: Request, body: RetryRequest | None = None):
        job = required_job(jid, request, False)
        if job["status"] in {"queued", "running"}:
            raise HTTPException(409, "任务仍在执行，请等待完成后再重试。")
        return manager.submit(upload_id=job["upload_id"], selected_file=job["selected_file"],
                              filename=job["filename"], goal=job["goal"], is_demo=job["is_demo"],
                              use_llm=body.use_llm if body is not None and "use_llm" in body.model_fields_set else job["use_llm"], target_column=job["target_column"],
                              user_id=request.state.user["id"])

    @app.delete("/api/jobs/{jid}")
    def delete(jid: str, request: Request):
        # Synchronize with submit so a shared-upload retry cannot race with deletion.
        with manager.lock:
            job = required_job(jid, request, False)
            if job["status"] in {"queued", "running"}:
                raise HTTPException(409, "任务仍在执行，暂时不能删除。")
            store.delete_job(jid, request.state.user["id"])
            shutil.rmtree(store.result_dir(jid), ignore_errors=True)
        return {"ok": True}

    @app.get("/api/jobs/{jid}/report.{extension}")
    def report(jid: str, extension: str, request: Request):
        if extension not in {"md", "html"}:
            raise HTTPException(404, "不支持此报告格式。")
        job = required_job(jid, request, False)
        if job["status"] != "completed":
            raise HTTPException(409, "报告尚未生成。")
        path = store.result_dir(jid) / ("report." + extension)
        if not path.exists():
            raise HTTPException(404, "报告文件不存在，请重试生成。")
        return FileResponse(path, filename=f"insight-report-{jid[:8]}.{extension}",
                            media_type="text/markdown; charset=utf-8" if extension == "md" else "text/html; charset=utf-8")

    if settings.static_dir and Path(settings.static_dir).is_dir():
        app.mount("/", SPAFiles(directory=settings.static_dir, html=True), name="frontend")
    else:
        @app.get("/")
        def home():
            return {"service": "Insight Studio", "frontend": "请启动前端开发服务或配置 STATIC_DIR。"}
    return app


app = create_app()
