import io

from PIL import Image

from app.api.routes import coach
from app.models.entities import Application, Interview, ResumeFact, ResumeVersion
from app.providers.ocr.base import OCRProviderError
from app.providers.ocr.rapidocr import RapidOCRProvider
from conftest import docx_file, register


def image_file():
    stream = io.BytesIO()
    Image.new("RGB", (320, 180), "white").save(stream, format="PNG")
    return ("jd.png", stream.getvalue(), "image/png")


def coach_files():
    return {"resume_file": docx_file()["file"], "jd_image": image_file()}


def test_rapidocr_provider_filters_low_confidence_lines():
    class FakeEngine:
        def __call__(self, _pixels):
            return (
                [
                    [[[0, 0]], "设备工程师", 0.99],
                    [[[0, 0]], "负责设备点检和 CAD 图纸维护", 0.88],
                    [[[0, 0]], "错误文字", 0.2],
                ],
                None,
            )

    provider = RapidOCRProvider(engine=FakeEngine())
    assert provider.extract_text(image_file()[1]) == "设备工程师\n负责设备点检和 CAD 图纸维护"


def test_single_page_coach_flow_creates_traceable_draft(client, db, monkeypatch):
    user = register(client)
    monkeypatch.setattr(
        coach,
        "extract_jd_text",
        lambda _content: (
            "设备工程师\n负责设备点检和维护，要求机械工程本科并熟悉 CAD。",
            "rapidocr",
        ),
    )

    response = client.post("/api/coach/optimize", files=coach_files())

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["job"]["title"] == "设备工程师"
    assert payload["ocr_provider"] == "rapidocr"
    assert payload["tailored_resume"]["guard_status"] == "passed"
    items = [
        item
        for section in payload["tailored_resume"]["content"]["sections"]
        for item in section["items"]
    ]
    assert items and all(item["source_fact_ids"] for item in items)
    assert payload["interview_guide"]["self_introduction"]["text"]
    assert len(payload["interview_guide"]["questions"]) == 3
    assert all(
        fact.verification_status == "extracted"
        for fact in db.query(ResumeFact).filter(ResumeFact.user_id == user["id"])
    )
    assert db.query(ResumeVersion).count() == 1
    assert db.query(Interview).count() == 1
    assert db.query(Application).count() == 0

    download = client.get(
        f"/api/coach/resume-versions/{payload['tailored_resume']['id']}/download"
    )
    assert download.status_code == 200
    assert download.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert download.headers["cache-control"] == "private, no-store"


def test_coach_uses_user_text_when_local_ocr_fails(client, monkeypatch):
    register(client)

    def fail_ocr(_content):
        raise OCRProviderError("本地 OCR 暂时不可用。")

    monkeypatch.setattr(coach, "extract_jd_text", fail_ocr)
    response = client.post(
        "/api/coach/optimize",
        files=coach_files(),
        data={"jd_text": "机械工程师，负责机械结构设计，要求熟悉 CAD 并能维护图纸。"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["ocr_provider"] == "user_text_fallback"


def test_coach_rejects_unreadable_jd_without_text_fallback(client, monkeypatch):
    register(client)

    def fail_ocr(_content):
        raise OCRProviderError("本地 OCR 暂时不可用。")

    monkeypatch.setattr(coach, "extract_jd_text", fail_ocr)
    response = client.post("/api/coach/optimize", files=coach_files())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "JD_TEXT_NOT_RECOGNIZED"


def test_coach_requires_login(client):
    response = client.post("/api/coach/optimize", files=coach_files())
    assert response.status_code == 401
