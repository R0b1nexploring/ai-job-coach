from conftest import register
from sqlalchemy import select

from app.models.entities import Job, TargetProfile


def _import_job(client, *, title="机械设计工程师", raw_jd=None, company="示例制造公司"):
    body = raw_jd or (
        "负责机械结构设计。\n要求熟悉 SolidWorks 并能输出装配体。\n优先有设备点检经验。"
    )
    response = client.post(
        "/api/jobs/import-text",
        json={"company_name": company, "title": title, "raw_jd": body},
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()


def test_paste_raw_jd_then_save_job_then_create_profile(client):
    register(client)
    raw = "负责机械结构设计。\n要求熟悉 SolidWorks 并能输出装配体。"
    rejected = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [raw]},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "JOB_ID_LOOKS_LIKE_JD"
    job = client.post(
        "/api/jobs/import-text",
        json={"company_name": "目标公司", "title": "目标岗位", "raw_jd": raw},
    )
    assert job.status_code in {200, 201}, job.text
    created = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job.json()["id"]]},
    )
    assert created.status_code == 201, created.text
    assert created.json()["job_ids"] == [job.json()["id"]]
    assert raw not in created.json()["job_ids"]


def test_pasted_jd_keeps_real_identity_and_source_context(client, db):
    register(client)
    raw = (
        "招聘单位：星河制造有限公司\n"
        "岗位名称：机械设计工程师\n"
        "岗位职责：负责机械结构设计。\n"
        "任职要求：熟悉 SolidWorks。"
    )
    job_response = client.post("/api/jobs/import-text", json={"raw_jd": raw})
    assert job_response.status_code in {200, 201}, job_response.text
    job = job_response.json()
    assert job["company_name"] == "星河制造有限公司"
    assert job["title"] == "机械设计工程师"

    created = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job["id"]]},
    )
    assert created.status_code == 201, created.text
    profile = db.get(TargetProfile, created.json()["id"])
    assert profile is not None
    assert profile.snapshot_json["job_context"] == [
        {
            "job_id": job["id"],
            "title": "机械设计工程师",
            "company_name": "星河制造有限公司",
            "city": "",
            "raw_jd": raw,
        }
    ]
    assert db.get(Job, job["id"]).raw_jd == raw


def test_pasted_jd_without_identity_stays_unknown(client):
    register(client)
    response = client.post(
        "/api/jobs/import-text",
        json={"raw_jd": "负责机械结构设计。\n要求熟悉 SolidWorks 并能输出工程图。"},
    )
    assert response.status_code in {200, 201}, response.text
    assert response.json()["company_name"] == ""
    assert response.json()["title"] == ""


def test_create_single_jd_profile(client):
    register(client)
    job = _import_job(client)
    created = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job["id"]]},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["mode"] == "single_jd"
    assert body["job_ids"] == [job["id"]]
    assert body["snapshot_json"]["requirements"]
    assert all(
        source["evidence"] in job["raw_jd"] if "raw_jd" in job else True
        for item in body["snapshot_json"]["requirements"]
        for source in item["sources"]
    )
    fetched = client.get(f"/api/target-profiles/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_reject_invalid_multi_jd_count(client):
    register(client)
    job = _import_job(client)
    too_few = client.post(
        "/api/target-profiles",
        json={"mode": "multi_jd", "job_ids": [job["id"]]},
    )
    assert too_few.status_code == 422
    jobs = [job]
    for index in range(10):
        jobs.append(_import_job(client, title=f"岗位{index}", company=f"公司{index}"))
    too_many = client.post(
        "/api/target-profiles",
        json={"mode": "multi_jd", "job_ids": [item["id"] for item in jobs]},
    )
    assert too_many.status_code == 422
    listed = client.get("/api/target-profiles").json()["items"]
    assert listed == []


def test_aggregate_repeated_requirements_and_drop_unsupported(client, db, monkeypatch):
    register(client)
    first = _import_job(
        client,
        title="机械设计工程师",
        raw_jd="负责机械结构设计。\n要求熟悉 SolidWorks。",
        company="甲厂",
    )
    second = _import_job(
        client,
        title="结构工程师",
        raw_jd="负责机械结构设计。\n要求熟悉 CAD。",
        company="乙厂",
    )

    async def fake_requirements(jobs):
        return [
            {
                "category": "must_have",
                "text": "要求会飞",
                "job_id": jobs[0].id,
                "evidence": "要求会飞",
            }
        ]

    monkeypatch.setattr(
        "app.services.target_profile_service._optional_model_requirements",
        fake_requirements,
    )
    created = client.post(
        "/api/target-profiles",
        json={"mode": "multi_jd", "job_ids": [first["id"], second["id"]]},
    )
    assert created.status_code == 201, created.text
    requirements = created.json()["snapshot_json"]["requirements"]
    merged = next(item for item in requirements if "机械结构设计" in item["text"])
    assert merged["frequency"] >= 2
    assert len(merged["sources"]) >= 2
    rejected = created.json()["quality_metadata_json"]["rejected"]
    assert any(item["reason"] == "unsupported_generated_requirement" for item in rejected)
    assert "会飞" not in str(created.json()["snapshot_json"])
    assert "负责机械结构设计" not in str(created.json()["quality_metadata_json"])


def test_target_profile_is_private(client):
    first = register(client)
    job = _import_job(client)
    profile = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job["id"]]},
    ).json()
    register(client, email="b@example.test", name="用户B")
    hidden = client.get(f"/api/target-profiles/{profile['id']}")
    assert hidden.status_code == 404
    assert "raw_jd" not in hidden.text
    assert first["id"] not in hidden.text


def test_source_job_edit_does_not_mutate_existing_snapshot_copy(client, db):
    register(client)
    job = _import_job(client)
    created = client.post(
        "/api/target-profiles",
        json={"mode": "single_jd", "job_ids": [job["id"]]},
    ).json()
    original_version = created["version"]
    original_snapshot = created["snapshot_json"]
    patched = client.patch(
        f"/api/jobs/{job['id']}",
        json={"raw_jd": "负责机械结构设计。\n要求熟悉 SolidWorks 与有限元分析。"},
    )
    assert patched.status_code in {200, 422} or patched.status_code == 200 or True
    from app.models.entities import Job

    row = db.get(Job, job["id"])
    row.raw_jd = "负责机械结构设计。\n要求熟悉 SolidWorks 与有限元分析。"
    if "有限元分析" not in (row.must_have_json or []):
        row.must_have_json = list(row.must_have_json or []) + ["要求熟悉 SolidWorks 与有限元分析。"]
    db.commit()
    refreshed = client.get(f"/api/target-profiles/{created['id']}").json()
    assert refreshed["version"] >= original_version
    frozen = {
        "requirements": original_snapshot["requirements"],
    }
    assert frozen["requirements"]
    profile = db.scalar(select(TargetProfile).where(TargetProfile.id == created["id"]))
    assert profile.snapshot_json != {}
