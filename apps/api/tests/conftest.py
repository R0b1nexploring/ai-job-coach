import io
import asyncio

import httpx
import pytest
from docx import Document
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db, make_engine
from app.main import app


@pytest.fixture()
def db(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session() as session:
        yield session
    Base.metadata.drop_all(engine)


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


def docx_file(text="机械工程本科\n毕业设计：使用 CAD 完成机械机构设计"):
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
