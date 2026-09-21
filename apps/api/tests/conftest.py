import asyncio
import atexit
import io
import os
import shutil
import tempfile
from pathlib import Path

_PYTEST_SESSION_ROOT = Path(tempfile.mkdtemp(prefix="ai-job-coach-pytest-")).resolve()
_PYTEST_SESSION_STORAGE = _PYTEST_SESSION_ROOT / "uploads"
_PYTEST_SESSION_STORAGE.mkdir()
os.environ.update(
    {
        "AI_JOB_COACH_TEST_ROOT": str(_PYTEST_SESSION_ROOT),
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{_PYTEST_SESSION_ROOT / 'app.db'}",
        "LOCAL_STORAGE_PATH": str(_PYTEST_SESSION_STORAGE),
        "STORAGE_PROVIDER": "local",
        "LLM_PROVIDER": "mock",
        "LLM_API_BASE_URL": "",
        "LLM_API_KEY": "",
        "LLM_MODEL": "",
        "LLM_MODEL_CHEAP": "",
        "LLM_MODEL_STRONG": "",
        "PAYMENT_PROVIDER": "disabled",
        "JOB_SOURCE_ALLOWED_HOSTS": "",
    }
)
atexit.register(shutil.rmtree, _PYTEST_SESSION_ROOT, True)

import httpx
import pytest
from docx import Document
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.config import get_settings


def _assert_isolated_environment(test_root: Path) -> None:
    settings = get_settings()
    if settings.app_env != "test":
        raise RuntimeError("测试启动已拒绝：APP_ENV 必须为 test。")
    if settings.llm_provider != "mock" or settings.payment_provider != "disabled":
        raise RuntimeError("测试启动已拒绝：外部服务必须使用 mock/disabled provider。")
    if settings.storage_provider != "local":
        raise RuntimeError("测试启动已拒绝：STORAGE_PROVIDER 必须为 local。")

    database_url = make_url(settings.resolved_database_url())
    if database_url.get_backend_name() != "sqlite" or not database_url.database:
        raise RuntimeError("测试启动已拒绝：DATABASE_URL 必须为临时 SQLite 文件。")
    database_path = Path(database_url.database).resolve()
    storage_path = settings.resolved_storage_path().resolve()
    if not database_path.is_relative_to(test_root) or database_path == test_root:
        raise RuntimeError("测试启动已拒绝：数据库不在隔离测试目录中。")
    if not storage_path.is_relative_to(test_root) or storage_path == test_root:
        raise RuntimeError("测试启动已拒绝：上传目录不在隔离测试目录中。")


_assert_isolated_environment(_PYTEST_SESSION_ROOT)

from app.database import Base, get_db, make_engine
from app.main import app


# Building the full schema costs ~0.3s per test (31 tables), which dominated the
# suite: ~280 DB tests spent most of their time in create_all. The schema is
# identical for every test, so it is built once per session and each test gets a
# cheap file copy. Isolation is unchanged: every test still owns a private
# database file that is removed with its test root.
_SCHEMA_TEMPLATE = _PYTEST_SESSION_ROOT / "schema-template.db"
_schema_template_ready = False


def _ensure_schema_template() -> Path:
    global _schema_template_ready
    if not _schema_template_ready:
        template_engine = make_engine(f"sqlite:///{_SCHEMA_TEMPLATE}")
        try:
            Base.metadata.create_all(template_engine)
        finally:
            # Dispose so the file is fully flushed before it is copied.
            template_engine.dispose()
        _schema_template_ready = True
    return _SCHEMA_TEMPLATE


@pytest.fixture(autouse=True)
def isolated_test_environment(tmp_path, monkeypatch):
    test_root = (tmp_path / "isolated-runtime").resolve()
    storage_path = test_root / "uploads"
    storage_path.mkdir(parents=True)
    environment = {
        "AI_JOB_COACH_TEST_ROOT": str(test_root),
        "APP_ENV": "test",
        "DATABASE_URL": f"sqlite:///{test_root / 'app.db'}",
        "LOCAL_STORAGE_PATH": str(storage_path),
        "STORAGE_PROVIDER": "local",
        "LLM_PROVIDER": "mock",
        "LLM_API_BASE_URL": "",
        "LLM_API_KEY": "",
        "LLM_MODEL": "",
        "LLM_MODEL_CHEAP": "",
        "LLM_MODEL_STRONG": "",
        "PAYMENT_PROVIDER": "disabled",
        "JOB_SOURCE_ALLOWED_HOSTS": "",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    _assert_isolated_environment(test_root)
    try:
        yield test_root
    finally:
        get_settings.cache_clear()
        shutil.rmtree(test_root, ignore_errors=True)


@pytest.fixture()
def db(isolated_test_environment):
    # Copy the pre-built schema instead of recreating 31 tables (~0.3s -> <1ms).
    database_url = get_settings().resolved_database_url()
    database_path = Path(make_url(database_url).database or "")
    shutil.copyfile(_ensure_schema_template(), database_path)
    engine = make_engine()
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with Session() as session:
            yield session
    finally:
        engine.dispose()


@pytest.fixture()
def client(db):
    async def override():
        yield db

    app.dependency_overrides[get_db] = override
    value = SyncASGIClient()
    yield value
    app.dependency_overrides.clear()


class SyncASGIClient:
    """Thread-free ASGI client for execution environments that block AnyIO portals."""

    def __init__(self):
        self.cookies = httpx.Cookies()

    def request(self, method: str, path: str, **kwargs):
        async def run():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test", cookies=self.cookies
            ) as client:
                response = await client.request(method, path, **kwargs)
                self.cookies = httpx.Cookies(client.cookies)
                return response

        return asyncio.run(run())

    def get(self, path: str, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self.request("DELETE", path, **kwargs)


def register(client, email="a@example.test", name="用户A"):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "Password123!", "display_name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def docx_file(
    text=(
        "机械工程本科\n项目经历\n"
        "示例大学 | 毕业设计项目 | 杭州 | 2024-03 至 2024-06\n"
        "使用 CAD 完成机械机构设计"
    ),
):
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    stream = io.BytesIO()
    doc.save(stream)
    return {
        "file": (
            "resume.docx",
            stream.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    }


def pdf_file(text="Mechanical engineering bachelor and CAD project"):
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    content = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f"{number} 0 obj\n".encode())
        content.extend(body)
        content.extend(b"\nendobj\n")
    xref = len(content)
    content.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    content.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        content.extend(f"{offset:010d} 00000 n \n".encode())
    content.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return {"file": ("resume.pdf", bytes(content), "application/pdf")}
