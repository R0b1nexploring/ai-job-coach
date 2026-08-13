import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"


def validate_test_environment() -> None:
    test_root_value = os.environ.get("AI_JOB_COACH_TEST_ROOT", "")
    test_root = Path(test_root_value)
    if not test_root_value or not test_root.is_absolute():
        raise RuntimeError("E2E 测试启动已拒绝：AI_JOB_COACH_TEST_ROOT 必须是绝对路径。")
    test_root = test_root.resolve()
    if not test_root.is_dir():
        raise RuntimeError("E2E 测试启动已拒绝：隔离测试目录不存在。")

    expected_environment = {
        "APP_ENV": "test",
        "LLM_PROVIDER": "mock",
        "PAYMENT_PROVIDER": "disabled",
        "STORAGE_PROVIDER": "local",
        "DEMO_ADMIN_EMAIL": "admin@example.test",
        "DEMO_ADMIN_PASSWORD": "ChangeMe123!",
        "DEMO_ADVISOR_EMAIL": "advisor@example.test",
        "DEMO_ADVISOR_PASSWORD": "ChangeMe123!",
        "DEMO_USER_EMAIL": "user@example.test",
        "DEMO_USER_PASSWORD": "ChangeMe123!",
    }
    for name, expected in expected_environment.items():
        if os.environ.get(name) != expected:
            raise RuntimeError(f"E2E 测试启动已拒绝：{name} 必须为 {expected}。")

    database_url = os.environ.get("DATABASE_URL", "")
    sqlite_prefix = "sqlite:///"
    if not database_url.startswith(sqlite_prefix):
        raise RuntimeError("E2E 测试启动已拒绝：DATABASE_URL 必须为临时 SQLite 文件。")
    database_path = Path(database_url[len(sqlite_prefix) :])
    storage_path = Path(os.environ.get("LOCAL_STORAGE_PATH", ""))
    if not database_path.is_absolute() or not database_path.resolve().is_relative_to(test_root):
        raise RuntimeError("E2E 测试启动已拒绝：数据库不在隔离测试目录中。")
    if database_path.resolve() == test_root:
        raise RuntimeError("E2E 测试启动已拒绝：DATABASE_URL 必须指向文件。")
    if not storage_path.is_absolute() or not storage_path.resolve().is_relative_to(test_root):
        raise RuntimeError("E2E 测试启动已拒绝：上传目录不在隔离测试目录中。")
    if storage_path.resolve() == test_root:
        raise RuntimeError("E2E 测试启动已拒绝：上传目录不能覆盖测试根目录。")


def main() -> int:
    validate_test_environment()
    environment = os.environ.copy()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_ROOT,
        env=environment,
        check=True,
    )
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo.py")],
        cwd=ROOT,
        env=environment,
        check=True,
    )
    os.chdir(API_ROOT)
    os.execve(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        environment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
