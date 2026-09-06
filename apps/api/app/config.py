import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]

TASK_TIERS = {
    "jd_normalize": "cheap",
    "match_explain": "cheap",
    "clarify": "cheap",
    "resume_analysis": "cheap",
    "resume_extract": "cheap",
    "resume_rewrite": "strong",
    "capability_plan": "strong",
    "interview_guide": "strong",
    "email_draft": "cheap",
    "target_profile": "cheap",
    "material_clarify": "cheap",
    "resume_plan": "strong",
    "resume_quality": "cheap",
    "interview_guide_v2": "strong",
}


class UnsafeConfigurationError(ValueError):
    """A sanitized startup error that never retains raw settings input."""


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production", "prod"] = "development"
    app_name: str = "AI Job Coach"
    app_secret_key: SecretStr = SecretStr("development-only-secret-change-me-123456789")
    database_url: str = "sqlite:///./var/app.db"
    frontend_origin: str = "http://localhost:5173"
    auth_cookie_name: str = "ai_job_session"
    auth_cookie_secure: bool = False
    access_token_expire_minutes: int = Field(default=1440, gt=0)
    llm_provider: str = "mock"
    llm_api_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_model_cheap: str = ""
    llm_model_strong: str = ""
    llm_timeout_seconds: int = Field(default=120, gt=0)
    llm_max_retries: int = Field(default=2, ge=0)
    llm_max_output_tokens: int = Field(default=8192, gt=0)
    llm_thinking_enabled: bool = False
    llm_reasoning_effort: Literal["", "high", "max"] = ""
    payment_provider: str = "disabled"
    payment_webhook_secret: SecretStr = SecretStr("demo-secret")
    storage_provider: str = "local"
    local_storage_path: str = "./var/uploads"
    max_upload_mb: int = Field(default=10, gt=0)
    data_retention_days: int = Field(default=180, ge=0)
    deletion_grace_days: int = Field(default=7, ge=0)
    job_stale_days: int = Field(default=45, ge=0)
    job_source_allowed_hosts: str = ""
    demo_admin_email: str = "admin@example.test"
    demo_admin_password: SecretStr = SecretStr("ChangeMe123!")
    demo_advisor_email: str = "advisor@example.test"
    demo_advisor_password: SecretStr = SecretStr("ChangeMe123!")
    demo_user_email: str = "user@example.test"
    demo_user_password: SecretStr = SecretStr("ChangeMe123!")

    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    def __init__(self, **values):
        super().__init__(**values)
        self._reject_unimplemented_storage_provider()
        self._reject_unsafe_production_defaults()

    def _reject_unimplemented_storage_provider(self) -> None:
        provider = self.storage_provider.strip().lower()
        if provider != "local":
            raise UnsafeConfigurationError(
                f"STORAGE_PROVIDER={provider or 'empty'} 尚未实现，应用拒绝启动"
            )

    def _reject_unsafe_production_defaults(self) -> None:
        if self.app_env.strip().lower() not in {"production", "prod"}:
            return

        errors: list[str] = []
        secret = self.app_secret_key.get_secret_value().strip()
        unsafe_secrets = {
            "development-only-secret-change-me-123456789",
            "replace-in-production-with-at-least-32-random-bytes",
        }
        if (
            len(secret.encode()) < 32
            or len(set(secret)) < 12
            or secret.lower() in unsafe_secrets
        ):
            errors.append("APP_SECRET_KEY 必须替换为至少 32 字节的随机值")
        if not self.auth_cookie_secure:
            errors.append("AUTH_COOKIE_SECURE 在生产环境必须为 true")
        if not self.frontend_origin.strip().lower().startswith("https://"):
            errors.append("FRONTEND_ORIGIN 在生产环境必须使用 https://")

        demo_passwords = {
            self.demo_admin_password.get_secret_value(),
            self.demo_advisor_password.get_secret_value(),
            self.demo_user_password.get_secret_value(),
        }
        if (
            "ChangeMe123!" in demo_passwords
            or len(demo_passwords) != 3
            or any(len(password) < 12 for password in demo_passwords)
        ):
            errors.append("生产环境演示账号密码必须非默认、互不相同且至少 12 字符")
        if (
            self.payment_provider != "disabled"
            and self.payment_webhook_secret.get_secret_value() == "demo-secret"
        ):
            errors.append("启用支付时必须替换 PAYMENT_WEBHOOK_SECRET")
        if not self.database_url.strip().lower().startswith(
            ("postgresql://", "postgresql+")
        ):
            errors.append("生产环境必须使用 PostgreSQL")
        # MVP currently implements LocalStorage only. Accepting a made-up provider
        # here would still route every call to LocalStorage, so production remains
        # deliberately unavailable until a real private-object provider lands.
        errors.append("当前版本尚未实现生产级私有对象存储，禁止以 production 启动")
        if self.llm_provider.strip().lower() != "compatible":
            errors.append("生产环境必须显式配置 compatible LLM Provider")
        if not all(
            [
                self.llm_api_base_url.strip(),
                self.llm_api_key.get_secret_value().strip(),
                self.model_for("resume_rewrite"),
            ]
        ):
            errors.append("生产环境必须完整配置 LLM 地址、密钥和模型")
        if errors:
            raise UnsafeConfigurationError("；".join(errors))

    def resolved_database_url(self) -> str:
        if self.database_url == "sqlite:///./var/app.db":
            return f"sqlite:///{ROOT / 'var' / 'app.db'}"
        return self.database_url

    def resolved_storage_path(self) -> Path:
        path = Path(self.local_storage_path)
        return path if path.is_absolute() else ROOT / path

    def tier_for(self, task: str) -> str:
        return TASK_TIERS.get(task, "cheap")

    def model_for(self, task: str) -> str:
        tier_model = (
            self.llm_model_strong if self.tier_for(task) == "strong" else self.llm_model_cheap
        )
        return tier_model.strip() or self.llm_model.strip()

    def allowed_job_source_hosts(self) -> set[str]:
        return {
            host.strip().lower()
            for host in self.job_source_allowed_hosts.split(",")
            if host.strip()
        }

    def harden_runtime_permissions(self) -> None:
        """Repair permissions for local PII-bearing runtime paths on POSIX.

        The application umask protects newly-created files. This also handles files
        created before that protection was introduced. Symlinks are deliberately
        skipped so a configured runtime path cannot change permissions elsewhere.
        """
        if os.name != "posix":
            return

        env_file = ROOT / ".env"
        if env_file.is_file() and not env_file.is_symlink():
            env_file.chmod(0o600)

        database_url = self.resolved_database_url()
        if database_url.startswith("sqlite:///"):
            database_value = database_url.removeprefix("sqlite:///").split("?", 1)[0]
            if database_value and database_value != ":memory:":
                database_path = Path(database_value)
                if database_path.is_file() and not database_path.is_symlink():
                    database_path.chmod(0o600)

        configured_storage_root = self.resolved_storage_path()
        if configured_storage_root.is_symlink():
            return
        storage_root = configured_storage_root.resolve()
        broad_paths = {Path("/").resolve(), ROOT.resolve(), ROOT.parent.resolve(), Path.home()}
        if storage_root in broad_paths:
            return
        if storage_root.is_dir():
            storage_root.chmod(0o700)
            for directory, names, filenames in os.walk(storage_root, followlinks=False):
                directory_path = Path(directory)
                if not directory_path.is_symlink():
                    directory_path.chmod(0o700)
                for name in names:
                    child = directory_path / name
                    if child.is_dir() and not child.is_symlink():
                        child.chmod(0o700)
                for filename in filenames:
                    child = directory_path / filename
                    if child.is_file() and not child.is_symlink():
                        child.chmod(0o600)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.harden_runtime_permissions()
    return settings
