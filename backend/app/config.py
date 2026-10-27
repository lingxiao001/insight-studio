from dataclasses import dataclass, field
from pathlib import Path
import os


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("DATA_DIR", "./data")))
    # Retained only for configuration compatibility; shared-password login no
    # longer exists and this value never authorizes a request.
    password: str = field(default_factory=lambda: os.getenv("APP_PASSWORD", ""), repr=False)
    admin_username: str = field(default_factory=lambda: os.getenv("ADMIN_USERNAME", "admin"))
    admin_password: str = field(default_factory=lambda: os.getenv("ADMIN_PASSWORD", ""), repr=False)
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", ""))
    cookie_secure: bool = field(default_factory=lambda: os.getenv("COOKIE_SECURE", "false").lower() == "true")
    llm_key: str = field(default_factory=lambda: os.getenv("LLM_API_KEY", ""), repr=False)
    llm_base_url: str = field(default_factory=lambda: os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", ""))
    llm_input_price: str = field(default_factory=lambda: os.getenv("LLM_INPUT_PER_MILLION_USD", ""))
    llm_output_price: str = field(default_factory=lambda: os.getenv("LLM_OUTPUT_PER_MILLION_USD", ""))
    llm_provider_only: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER_ONLY", ""))
    static_dir: str = field(default_factory=lambda: os.getenv("STATIC_DIR", ""))
    max_upload_bytes: int = 50 * 1024 * 1024
    max_rows: int = 100_000
    max_columns: int = 80
    max_active_jobs: int = 5  # One running task and at most four queued tasks.

    def validate(self):
        self.data_dir = Path(self.data_dir).resolve()
        if (self.admin_password or self.cookie_secure) and len(self.session_secret) < 32:
            raise RuntimeError("创建管理员或启用安全 Cookie 时，SESSION_SECRET 必须至少为 32 个字符。")
        for directory in (self.data_dir, self.data_dir / "uploads", self.data_dir / "results"):
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o700)
