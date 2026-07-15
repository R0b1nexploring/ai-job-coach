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
