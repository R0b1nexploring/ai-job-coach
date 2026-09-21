import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


def normalize_database_url(url: str) -> str:
    """Force the psycopg v3 driver for bare PostgreSQL URLs.

    SQLAlchemy defaults ``postgresql://`` to psycopg2, which is not installed.
    Operators write the plain scheme in .env; the driver choice is an
    implementation detail and must not be leaked into deployment config.
    """
    value = url.strip()
    lowered = value.lower()
    if lowered.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://") :]
    if lowered.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


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
    # PostgreSQL connection pool. Ignored for SQLite.
    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_recycle_seconds: int = Field(default=1800, ge=0)
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
    llm_timeout_seconds: int = Field(default=300, gt=0)
    llm_max_retries: int = Field(default=1, ge=0)
    # Transport retry backoff for transient failures. Jitter is added on top so
    # several workers do not retry a rate-limited upstream in lockstep.
    llm_retry_backoff_base_seconds: float = Field(default=1.0, ge=0)
    llm_retry_backoff_max_seconds: float = Field(default=30.0, ge=0)
    llm_max_output_tokens: int = Field(default=8192, gt=0)
    llm_thinking_enabled: bool = False
    llm_reasoning_effort: Literal["", "high", "max"] = ""
    # Local debugging escape hatch. Test and production environments always
    # keep the hard quality gate enabled regardless of this value.
    resume_quality_gate_enabled: bool = True
    payment_provider: str = "disabled"
    payment_webhook_secret: SecretStr = SecretStr("demo-secret")
    storage_provider: str = "local"
    local_storage_path: str = "./var/uploads"
    # Private S3-compatible object storage (production). Only read when
    # storage_provider == "s3"; the secret is never logged or rendered.
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_region: str = ""
    s3_access_key_id: SecretStr = SecretStr("")
    s3_secret_access_key: SecretStr = SecretStr("")
    s3_prefix: str = ""
    s3_use_path_style: bool = False
    max_upload_mb: int = Field(default=10, gt=0)
    data_retention_days: int = Field(default=180, ge=0)
    deletion_grace_days: int = Field(default=7, ge=0)
    job_stale_days: int = Field(default=45, ge=0)
    job_source_allowed_hosts: str = ""
    # Invite-only trial signup. Development and tests may keep open registration;
    # production must require an invite code.
    registration_require_invite: bool = False
    invite_default_expires_days: int = Field(default=7, ge=1)
    invite_resume_quota: int = Field(default=5, ge=0)
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
        if provider not in {"local", "s3"}:
            raise UnsafeConfigurationError(
                f"STORAGE_PROVIDER={provider or 'empty'} 尚未实现，应用拒绝启动"
            )

    def s3_missing_configuration(self) -> list[str]:
        """Names only; never returns or renders the secret value."""
        missing: list[str] = []
        if not self.s3_bucket.strip():
            missing.append("S3_BUCKET")
        if not self.s3_access_key_id.get_secret_value().strip():
            missing.append("S3_ACCESS_KEY_ID")
        if not self.s3_secret_access_key.get_secret_value().strip():
            missing.append("S3_SECRET_ACCESS_KEY")
        return missing

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
            ("postgresql://", "postgresql+", "postgres://")
        ):
            errors.append("生产环境必须使用 PostgreSQL")
        if self.storage_provider.strip().lower() != "s3":
            errors.append("生产环境必须使用私有对象存储（STORAGE_PROVIDER=s3）")
        else:
            missing = self.s3_missing_configuration()
            if missing:
                errors.append(
                    "生产环境 S3 配置不完整：" + "、".join(missing)
                )
        if not self.registration_require_invite:
            errors.append("生产环境必须开启邀请码注册（REGISTRATION_REQUIRE_INVITE=true）")
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
        return normalize_database_url(self.database_url)

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

    def resume_quality_gate_active(self) -> bool:
        """Whether quality failures may block delivery.

        The local development switch is deliberately unavailable in test and
        production environments so a developer's .env cannot weaken CI or a
        deployment by accident.
        """
        if self.app_env.strip().lower() in {"test", "production", "prod"}:
            return True
        return self.resume_quality_gate_enabled

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
