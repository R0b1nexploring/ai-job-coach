from functools import lru_cache
from pathlib import Path

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
}


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "AI Job Coach"
    app_secret_key: str = "development-only-secret-change-me-123456789"
    database_url: str = "sqlite:///./var/app.db"
    frontend_origin: str = "http://localhost:5173"
    auth_cookie_name: str = "ai_job_session"
    auth_cookie_secure: bool = False
    access_token_expire_minutes: int = 1440
    llm_provider: str = "mock"
    llm_api_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_model_cheap: str = ""
    llm_model_strong: str = ""
    llm_timeout_seconds: int = 45
    llm_max_retries: int = 2
    payment_provider: str = "disabled"
    payment_webhook_secret: str = "demo-secret"
    storage_provider: str = "local"
    local_storage_path: str = "./var/uploads"
    max_upload_mb: int = 10
    data_retention_days: int = 180
    deletion_grace_days: int = 7
    job_stale_days: int = 45
    job_source_allowed_hosts: str = ""
    demo_admin_email: str = "admin@example.test"
    demo_admin_password: str = "ChangeMe123!"
    demo_advisor_email: str = "advisor@example.test"
    demo_advisor_password: str = "ChangeMe123!"
    demo_user_email: str = "user@example.test"
    demo_user_password: str = "ChangeMe123!"

    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
