import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, UnsafeConfigurationError


def production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "app_secret_key": "prod-secret-A9!c7D2#v5K8@x4M1$q6T3&b0N7*",
        "frontend_origin": "https://coach.example.com",
        "auth_cookie_secure": True,
        "demo_admin_password": "Admin-Production-Password!",
        "demo_advisor_password": "Advisor-Production-Password!",
        "demo_user_password": "User-Production-Password!",
        "database_url": "postgresql+psycopg://coach@db.example/coach",
        "storage_provider": "s3",
        "s3_bucket": "coach-private",
        "s3_access_key_id": "production-s3-access-key",
        "s3_secret_access_key": "production-s3-secret-key",
        "registration_require_invite": True,
        "llm_provider": "compatible",
        "llm_api_base_url": "https://llm.example.com/v1",
        "llm_api_key": "production-llm-key",
        "llm_model_strong": "production-model",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("data_retention_days", -1),
        ("deletion_grace_days", -1),
        ("job_stale_days", -1),
        ("llm_max_retries", -1),
    ],
)
def test_nonnegative_settings_reject_negative_values(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_unknown_environment_name_is_rejected_instead_of_bypassing_production_checks():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="prodution")


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_secret_key": "development-only-secret-change-me-123456789"},
        {"auth_cookie_secure": False},
        {"frontend_origin": "http://coach.example.com"},
        {"demo_user_password": "ChangeMe123!"},
        {"payment_provider": "stripe", "payment_webhook_secret": "demo-secret"},
    ],
)
def test_production_rejects_unsafe_security_defaults(overrides):
    with pytest.raises(UnsafeConfigurationError):
        production_settings(**overrides)


def test_production_requires_private_object_storage_with_complete_config():
    with pytest.raises(UnsafeConfigurationError, match="私有对象存储"):
        production_settings(storage_provider="local")

    with pytest.raises(UnsafeConfigurationError, match="S3 配置不完整"):
        production_settings(s3_bucket="")

    with pytest.raises(UnsafeConfigurationError, match="S3 配置不完整"):
        production_settings(s3_secret_access_key="")


def test_production_settings_with_complete_s3_config_are_accepted():
    settings = production_settings()
    assert settings.storage_provider == "s3"
    assert settings.s3_missing_configuration() == []


def test_unknown_storage_provider_never_silently_falls_back_in_development():
    with pytest.raises(UnsafeConfigurationError, match="应用拒绝启动"):
        Settings(_env_file=None, storage_provider="typo-or-unimplemented")

    with pytest.raises(UnsafeConfigurationError, match="应用拒绝启动"):
        Settings(_env_file=None, storage_provider="private_object_storage")


def test_production_error_does_not_retain_or_render_secret_values():
    sentinel = "SUPER-SENSITIVE-SENTINEL-DO-NOT-LOG"
    with pytest.raises(UnsafeConfigurationError) as captured:
        production_settings(app_secret_key=sentinel, auth_cookie_secure=False)
    assert sentinel not in str(captured.value)
    assert sentinel not in repr(captured.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url": "sqlite:///./var/app.db"},
        {"database_url": "mysql://coach@db.example/coach"},
        {"storage_provider": "local"},
        {"llm_provider": "mock"},
        {"llm_api_key": ""},
        {"registration_require_invite": False},
    ],
)
def test_production_rejects_demo_only_infrastructure(overrides):
    with pytest.raises(UnsafeConfigurationError):
        production_settings(**overrides)


def test_development_scripts_default_to_loopback_and_private_umask():
    root = Path(__file__).resolve().parents[3]
    shell_script = (root / "scripts" / "dev.sh").read_text()
    powershell_script = (root / "scripts" / "dev.ps1").read_text()
    assert "umask 077" in shell_script
    assert "${DEV_API_HOST:-127.0.0.1}" in shell_script
    assert "${DEV_WEB_HOST:-127.0.0.1}" in shell_script
    assert 'else { "127.0.0.1" }' in powershell_script
    assert "0.0.0.0" not in shell_script
    assert "0.0.0.0" not in powershell_script


@pytest.mark.skipif(os.name != "posix", reason="POSIX umask only")
def test_runtime_creates_private_files_by_default(tmp_path):
    private_file = tmp_path / "runtime-private.txt"
    private_file.write_text("private")
    assert stat.S_IMODE(private_file.stat().st_mode) & 0o077 == 0
