import os
import stat
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import ROOT, get_settings
from app.providers.storage.local import LocalStorage


def test_pytest_database_and_storage_are_isolated(isolated_test_environment):
    settings = get_settings()
    database_path = make_url(settings.resolved_database_url()).database
    assert database_path is not None
    assert settings.app_env == "test"
    assert settings.llm_provider == "mock"
    assert settings.payment_provider == "disabled"
    assert settings.storage_provider == "local"
    assert isolated_test_environment in Path(database_path).resolve().parents

    storage = LocalStorage()
    key = storage.save(b"isolated", ".txt")
    assert isolated_test_environment in storage.path(key).resolve().parents
    assert storage.root.resolve() != (ROOT / "var" / "uploads").resolve()
    assert Path(database_path).resolve() != (ROOT / "var" / "app.db").resolve()
    if os.name == "posix":
        assert stat.S_IMODE(storage.root.stat().st_mode) == 0o700
        assert stat.S_IMODE(storage.path(key).stat().st_mode) == 0o600
