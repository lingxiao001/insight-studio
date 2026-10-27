import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


STEP_LABELS = [
    ("read", "读取数据"), ("profile", "数据画像"), ("quality", "质量检查"),
    ("charts", "图表探索"), ("insights", "洞察推理"), ("report", "生成报告"),
]


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.db_path = root / "studio.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS uploads (
                    id TEXT PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL,
                    files TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, upload_id TEXT, selected_file TEXT,
                    filename TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL, progress INTEGER NOT NULL,
                    goal TEXT NOT NULL, is_demo INTEGER NOT NULL,
                    error TEXT, steps TEXT NOT NULL, use_llm INTEGER NOT NULL,
                    target_column TEXT
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('admin','user')),
                    session_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
            """)
            for table in ("uploads", "jobs"):
                if "user_id" not in {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT REFERENCES users(id)")
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_user_id ON {table}(user_id)")
        self.db_path.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        return db

    def user(self, user_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

    def user_by_username(self, username):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=? COLLATE NOCASE", (username,)).fetchone()
        return dict(row) if row else None

    def admin_user(self):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE role='admin' ORDER BY created_at,id LIMIT 1").fetchone()
        return dict(row) if row else None

    @staticmethod
    def public_user(user):
        return {key: user[key] for key in ("id", "username", "role")}

    def add_user(self, username, password_hash):
        user_id = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO users(id,username,password_hash,role,session_version,created_at) VALUES (?,?,?,'user',1,?)",
                       (user_id, username, password_hash, now()))
        return self.user(user_id)

    def seed_admin(self, username, password_hash=None):
        """Claim legacy records once, atomically, without changing an existing admin."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            admin = db.execute("SELECT * FROM users WHERE role='admin' ORDER BY created_at,id LIMIT 1").fetchone()
            if not admin and password_hash:
                user_id = uuid4().hex
                db.execute("INSERT INTO users(id,username,password_hash,role,session_version,created_at) VALUES (?,?,?,'admin',1,?)",
                           (user_id, username, password_hash, now()))
                admin = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if admin:
                db.execute("UPDATE uploads SET user_id=? WHERE user_id IS NULL", (admin["id"],))
                db.execute("UPDATE jobs SET user_id=? WHERE user_id IS NULL", (admin["id"],))
        return dict(admin) if admin else None

    def recover(self):
        with self.connect() as db:
            rows = db.execute("SELECT id, steps FROM jobs WHERE status IN ('queued','running')").fetchall()
            for row in rows:
                steps = json.loads(row["steps"])
                for step in steps:
                    if step["status"] == "running":
                        step["status"] = "failed"
                        step["detail"] = "服务重启中断了此步骤，可重试。"
                db.execute("UPDATE jobs SET status='failed', error=?, steps=? WHERE id=?",
                           ("服务重启导致任务中断，请点击重试。", json.dumps(steps, ensure_ascii=False), row["id"]))

    def add_upload(self, filename, path, files, user_id=None):
        uid = path.stem
        with self.connect() as db:
            db.execute("INSERT INTO uploads(id,filename,path,files,created_at,user_id) VALUES (?,?,?,?,?,?)",
                       (uid, filename, str(path), json.dumps(files, ensure_ascii=False), now(), user_id))
        return {"upload_id": uid, "filename": filename, "files": files}

    def upload(self, uid, user_id=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM uploads WHERE id=?" + (" AND user_id=?" if user_id is not None else ""),
                             (uid, user_id) if user_id is not None else (uid,)).fetchone()
        if not row:
            return None
        upload = dict(row)
        upload["files"] = json.loads(upload["files"])
        return upload

    def create_job(self, upload_id=None, selected_file="", filename="", goal="", is_demo=False,
                   use_llm=False, target_column=None, user_id=None):
        jid = uuid4().hex
        steps = [{"key": key, "label": label, "status": "pending", "detail": "等待执行"} for key, label in STEP_LABELS]
        with self.connect() as db:
            db.execute("INSERT INTO jobs(id,upload_id,selected_file,filename,created_at,status,progress,goal,is_demo,error,steps,use_llm,target_column,user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                jid, upload_id, selected_file, filename, now(), "queued", 0, goal,
                int(is_demo), None, json.dumps(steps, ensure_ascii=False), int(use_llm), target_column, user_id))
        return self.get_job(jid)

    def get_job(self, jid, include_result=True, user_id=None):
        with self.connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?" + (" AND user_id=?" if user_id is not None else ""),
                             (jid, user_id) if user_id is not None else (jid,)).fetchone()
        if not row:
            return None
        job = dict(row)
        job["steps"] = json.loads(job["steps"])
        job["is_demo"] = bool(job["is_demo"])
        job["use_llm"] = bool(job["use_llm"])
        if include_result and job["status"] == "completed":
            result_path = self.result_dir(jid) / "result.json"
            if result_path.exists():
                job["result"] = json.loads(result_path.read_text(encoding="utf-8"))
        return job

    def public(self, job):
        return {key: value for key, value in job.items() if key not in {"upload_id", "selected_file", "user_id"}}

    def list_jobs(self, user_id=None):
        with self.connect() as db:
            rows = db.execute("SELECT id FROM jobs" + (" WHERE user_id=?" if user_id is not None else "") + " ORDER BY created_at DESC LIMIT 100",
                              (user_id,) if user_id is not None else ()).fetchall()
        return [self.public(self.get_job(row["id"], False)) for row in rows]

    def active_count(self):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]

    def update(self, jid, **fields):
        allowed = {"status", "progress", "error", "steps"}
        assert set(fields) <= allowed
        if "steps" in fields:
            fields["steps"] = json.dumps(fields["steps"], ensure_ascii=False)
        with self.connect() as db:
            db.execute("UPDATE jobs SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                       (*fields.values(), jid))

    def result_dir(self, jid):
        return self.root / "results" / jid

    def delete_job(self, jid, user_id=None):
        with self.connect() as db:
            row = db.execute("SELECT upload_id FROM jobs WHERE id=?" + (" AND user_id=?" if user_id is not None else ""),
                             (jid, user_id) if user_id is not None else (jid,)).fetchone()
            if not row:
                return
            db.execute("DELETE FROM jobs WHERE id=?", (jid,))
            upload_id = row["upload_id"] if row else None
            if upload_id and not db.execute("SELECT 1 FROM jobs WHERE upload_id=?", (upload_id,)).fetchone():
                upload = db.execute("SELECT path FROM uploads WHERE id=?", (upload_id,)).fetchone()
                db.execute("DELETE FROM uploads WHERE id=?", (upload_id,))
                if upload:
                    Path(upload["path"]).unlink(missing_ok=True)
