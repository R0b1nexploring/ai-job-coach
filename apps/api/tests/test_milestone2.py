from datetime import datetime, timezone

import pytest

from app.models.entities import Application, Job, QuotaLedger, ResumeFact
from app.services.fact_guard import guard_content
from app.services.quota_service import balance, change
from conftest import register


def test_fact_guard_blocks_new_metric():
    fact = type("Fact", (), {"value_json":{"text":"完成机构设计"}})()
    content = {"sections":[{"items":[{"text":"提升效率 30%","source_fact_ids":["f1"],"new_claims":[]}]}]}
    status, claims = guard_content(content, [fact])
    assert status == "blocked" and "30%" in claims


def test_fact_guard_requires_traceability():
    status, claims = guard_content({"sections":[{"items":[{"text":"真实描述","source_fact_ids":[],"new_claims":[]}]}]}, [])
    assert status == "blocked" and "缺少事实来源" in claims


def test_quota_deduction_and_idempotency(db):
    change(db,user_id="u",quota_type="resume",delta=2,reason="grant",idempotency_key="grant")
    change(db,user_id="u",quota_type="resume",delta=-1,reason="use",idempotency_key="same")
    change(db,user_id="u",quota_type="resume",delta=-1,reason="use",idempotency_key="same")
    assert balance(db,"u","resume") == 1


def test_quota_idempotency_is_scoped_by_user_and_type(db):
    first = change(db, user_id="user-a", quota_type="resume", delta=2, reason="grant", idempotency_key="shared-key")
    second = change(db, user_id="user-b", quota_type="resume", delta=3, reason="grant", idempotency_key="shared-key")
    third = change(db, user_id="user-a", quota_type="application", delta=4, reason="grant", idempotency_key="shared-key")
    db.commit()
    assert len({first.id, second.id, third.id}) == 3
    assert balance(db, "user-a", "resume") == 2
    assert balance(db, "user-b", "resume") == 3
    assert balance(db, "user-a", "application") == 4


def test_application_valid_and_invalid_transitions(client, db):
    user = register(client)
    job = Job(created_by=user["id"],company_name="示例",title="工程师",raw_jd="负责机械设计",content_hash="1")
    db.add(job); db.flush()
    change(db,user_id=user["id"],quota_type="application",delta=2,reason="test",idempotency_key="grant-app"); db.commit()
    app = client.post("/api/applications",json={"job_id":job.id}).json()
    bad = client.patch(f"/api/applications/{app['id']}/status",json={"status":"offer"})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    good = client.patch(f"/api/applications/{app['id']}/status",json={"status":"preparing_resume"})
    assert good.status_code == 200
    events = client.get(f"/api/applications/{app['id']}/events").json()
    assert events["total"] == 2


def test_application_create_is_idempotent(client, db):
    user = register(client)
    job = Job(created_by=user["id"], company_name="示例", title="工程师", raw_jd="负责机械设计", content_hash="2")
    db.add(job); db.flush()
    change(db, user_id=user["id"], quota_type="application", delta=2, reason="test", idempotency_key="grant-app-idempotent")
    db.commit()
    headers = {"Idempotency-Key": "same-application-request"}
    first = client.post("/api/applications", headers=headers, json={"job_id": job.id})
    second = client.post("/api/applications", headers=headers, json={"job_id": job.id})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert db.query(Application).count() == 1
    assert balance(db, user["id"], "application") == 1
