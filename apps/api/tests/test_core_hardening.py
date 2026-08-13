import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import docx_file, register
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.core import _read_upload_limited
from app.errors import AppError
from app.models.entities import Job, Match, QuotaLedger, Resume, StorageDeletionTask, User
from app.providers.llm.schemas import JobStructuredOutput
from app.providers.storage.local import LocalStorage


def test_upload_reader_stops_immediately_after_crossing_limit():
    class ChunkedUpload:
        def __init__(self):
            self.chunks = [b"1234", b"56", b"must-not-be-read"]
            self.reads = 0

        async def read(self, _size):
            self.reads += 1
            return self.chunks.pop(0)

    upload = ChunkedUpload()
    with pytest.raises(AppError) as raised:
        asyncio.run(_read_upload_limited(upload, 5))

    assert raised.value.code == "FILE_TOO_LARGE"
    assert upload.reads == 2


def test_raw_jd_has_a_bounded_request_schema(client):
    register(client)
    response = client.post(
        "/api/jobs/import-text",
        json={"raw_jd": "岗" * 50_001},
    )

    assert response.status_code == 422
    fields = response.json()["error"]["details"]["fields"]
    assert any(item["location"].endswith("raw_jd") for item in fields)


def test_job_model_output_is_grounded_and_explicit_user_fields_win(client, monkeypatch):
    async def hallucinated_job(**_kwargs):
        return (
            JobStructuredOutput(
                title="伪造岗位",
                company_name="伪造公司",
                city="火星",
                responsibilities=["负责不存在的量子设备"],
                must_have=["必须持有不存在的证书"],
                nice_to_have=[],
                keywords=["Python"],
                work_conditions=[],
                uncertain_fields=[],
            ),
            "compatible",
        )

    monkeypatch.setattr("app.api.routes.core.generate_structured", hallucinated_job)
    register(client)
    raw_jd = "真实岗位\n负责设备维护。\n要求熟悉 CAD。"
    response = client.post(
        "/api/jobs/import-text",
        json={
            "raw_jd": raw_jd,
            "title": "用户指定岗位",
            "company_name": "用户指定公司",
            "city": "上海",
        },
    )

    assert response.status_code == 201, response.text
    job = response.json()
    assert job["title"] == "用户指定岗位"
    assert job["company_name"] == "用户指定公司"
    assert job["city"] == "上海"
    for value in [
        *job["responsibilities_json"],
        *job["must_have_json"],
        *job["nice_to_have_json"],
        *job["keywords_json"],
        *job["work_conditions_json"],
    ]:
        assert "".join(str(value).split()).casefold() in "".join(raw_jd.split()).casefold()
    assert "量子" not in str(job)
    assert "不存在的证书" not in str(job)
    assert "Python" not in str(job)


def test_rejecting_every_fact_does_not_confirm_resume(client):
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    facts = client.get(f"/api/resumes/{resume['id']}/facts").json()["items"]

    for fact in facts:
        rejected = client.post(f"/api/resume-facts/{fact['id']}/reject")
        assert rejected.status_code == 200

    response = client.post(f"/api/resumes/{resume['id']}/confirm-facts")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESUME_FACTS_EMPTY"
    assert client.get(f"/api/resumes/{resume['id']}").json()["facts_confirmed_at"] is None


def test_match_is_idempotent_for_same_resume_and_job(client, db):
    user = register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    assert client.post(f"/api/resumes/{resume['id']}/confirm-facts").status_code == 200
    job = client.post(
        "/api/jobs/import-text",
        json={
            "raw_jd": "设备工程师\n负责设备维护。\n要求熟悉 CAD。",
            "title": "设备工程师",
            "company_name": "示例公司",
        },
    ).json()

    payload = {"resume_id": resume["id"], "job_id": job["id"]}
    first = client.post("/api/matches", json=payload)
    second = client.post("/api/matches", json=payload)

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert db.scalar(
        select(func.count(Match.id)).where(
            Match.user_id == user["id"],
            Match.resume_id == resume["id"],
            Match.job_id == job["id"],
        )
    ) == 1
    assert db.scalar(
        select(func.count(QuotaLedger.id)).where(
            QuotaLedger.user_id == user["id"],
            QuotaLedger.quota_type == "match",
            QuotaLedger.idempotency_key == f"match:{resume['id']}:{job['id']}",
        )
    ) == 1


def test_upload_database_failure_rolls_back_and_deletes_new_file(client, db, monkeypatch):
    register(client)
    deleted = []
    monkeypatch.setattr(LocalStorage, "save", lambda _self, _content, _suffix: "new-file.docx")
    monkeypatch.setattr(LocalStorage, "delete", lambda _self, key: deleted.append(key))
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit")))

    with pytest.raises(RuntimeError, match="commit"):
        client.post("/api/resumes", files=docx_file())

    assert deleted == ["new-file.docx"]
    assert db.scalar(select(func.count(Resume.id))) == 0


def test_resume_delete_commits_before_best_effort_storage_cleanup(client, db, monkeypatch):
    register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    row = db.get(Resume, resume["id"])
    events = []
    original_commit = db.commit

    def tracked_commit():
        events.append("commit")
        original_commit()

    def failing_delete(_self, _key):
        events.append("delete")
        raise OSError("storage unavailable")

    monkeypatch.setattr(db, "commit", tracked_commit)
    monkeypatch.setattr(LocalStorage, "delete", failing_delete)
    response = client.delete(f"/api/resumes/{resume['id']}")

    assert response.status_code == 204
    assert events == ["commit", "delete", "commit"]
    assert row.deleted_at is not None
    assert db.scalar(
        select(func.count(StorageDeletionTask.id)).where(
            StorageDeletionTask.file_key == row.original_file_key
        )
    ) == 1


def test_upload_cleanup_failure_is_durably_queued(client, db, monkeypatch):
    register(client)
    monkeypatch.setattr(LocalStorage, "save", lambda _self, _content, _suffix: "orphan.docx")
    monkeypatch.setattr(
        LocalStorage,
        "delete",
        lambda _self, _key: (_ for _ in ()).throw(OSError("storage unavailable")),
    )
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit")))

    with pytest.raises(RuntimeError, match="commit"):
        client.post("/api/resumes", files=docx_file())

    task = db.scalar(
        select(StorageDeletionTask).where(StorageDeletionTask.file_key == "orphan.docx")
    )
    assert task is not None
    assert task.attempts == 1
    assert task.last_error == "OSError"


@pytest.mark.parametrize("entity_type", ["resume", "job"])
def test_stale_authenticated_session_cannot_create_pii_after_purge_claim(db, entity_type):
    user = User(email=f"race-{entity_type}@example.test", password_hash="test")
    db.add(user)
    db.commit()

    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    with Session() as request_db, Session() as maintenance_db:
        stale_user = request_db.get(User, user.id)
        assert stale_user is not None and stale_user.status == "active"

        claimed_user = maintenance_db.get(User, user.id)
        claimed_user.status = "purging"
        maintenance_db.commit()

        if entity_type == "resume":
            request_db.add(
                Resume(
                    user_id=user.id,
                    original_file_key="stale.docx",
                    original_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    display_name="stale",
                )
            )
        else:
            request_db.add(
                Job(
                    created_by=user.id,
                    company_name="stale",
                    title="stale",
                    raw_jd="stale personal job data",
                    content_hash="stale",
                )
            )

        with pytest.raises(AppError) as raised:
            request_db.commit()
        assert raised.value.code == "ACCOUNT_WRITE_CONFLICT"
        request_db.rollback()

    model = Resume if entity_type == "resume" else Job
    assert db.scalar(select(func.count(model.id))) == 0


def test_concurrent_purge_claim_wins_before_stale_writer_flush(db):
    user = User(email="threaded-race@example.test", password_hash="test")
    db.add(user)
    db.commit()

    Session = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    loaded = threading.Barrier(2)
    purge_committed = threading.Event()

    def stale_writer() -> str:
        with Session() as request_db:
            stale_user = request_db.get(User, user.id)
            assert stale_user is not None and stale_user.status == "active"
            loaded.wait(timeout=5)
            assert purge_committed.wait(timeout=5)
            request_db.add(
                Job(
                    created_by=user.id,
                    company_name="不应写入",
                    title="不应写入",
                    raw_jd="stale request personal data",
                    content_hash="threaded-race",
                )
            )
            try:
                request_db.commit()
            except AppError as exc:
                request_db.rollback()
                return exc.code
            return "unexpected-success"

    def purge_claim() -> None:
        with Session() as maintenance_db:
            loaded.wait(timeout=5)
            claimed = maintenance_db.get(User, user.id)
            assert claimed is not None
            claimed.status = "purging"
            maintenance_db.commit()
            purge_committed.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        write_future = executor.submit(stale_writer)
        purge_future = executor.submit(purge_claim)
        purge_future.result(timeout=10)
        assert write_future.result(timeout=10) == "ACCOUNT_WRITE_CONFLICT"

    db.expire_all()
    assert db.get(User, user.id).status == "purging"
    assert db.scalar(select(func.count(Job.id))) == 0
