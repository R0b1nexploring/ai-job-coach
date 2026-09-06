from sqlalchemy import select

from app.models.entities import ExperienceEntry, ResumeFact
from app.services.experience_service import seed_templates, sync_confirmed_facts_to_experience
from conftest import docx_file, register


def test_user_can_add_internship_and_it_becomes_a_confirmed_fact(client, db):
    register(client)
    created = client.post(
        "/api/experience",
        json={
            "kind": "internship",
            "title": "设备点检实习",
            "organization": "用户自己的实习单位",
            "role_title": "实习生",
            "start_date": "2025-07",
            "summary": "按点检表完成指定工位检查并记录异常。",
            "bullets_json": ["完成点检记录"],
            "skills_json": ["设备点检"],
            "details_json": {
                "actions": "按点检表完成指定工位检查并记录异常",
                "tools": "点检表",
                "results": "完成点检记录",
            },
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["is_own"] is True
    assert body["status"] == "draft"
    assert body["linked_to_facts"] is False
    confirmed = client.post(f"/api/experience/{body['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "confirmed"
    facts = list(
        db.scalars(select(ResumeFact).where(ResumeFact.material_id == body["id"]))
    )
    assert {fact.claim_type for fact in facts} >= {"organization", "role", "action", "tool", "result"}
    assert all(fact.verification_status == "user_confirmed" for fact in facts)
    assert all(fact.material_id == body["id"] for fact in facts)


def test_templates_are_readonly_and_copy_does_not_become_a_fact(client, db):
    seed_templates(db)
    db.commit()
    first = register(client)
    templates = client.get("/api/experience?source=template").json()["items"]
    assert len(templates) >= 2
    template = next(item for item in templates if item["kind"] == "internship")
    copied = client.post(f"/api/experience/from-template/{template['id']}")
    assert copied.status_code == 201
    assert copied.json()["linked_to_facts"] is False
    assert copied.json()["organization"] == ""

    blocked = client.post(f"/api/experience/{copied.json()['id']}/confirm")
    assert blocked.status_code == 422

    other = register(client, email="b@example.test", name="用户B")
    assert other["id"]
    listed = client.get("/api/experience?source=user_added").json()["items"]
    assert listed == []
    patched = client.patch(
        f"/api/experience/{copied.json()['id']}",
        json={"organization": "用户B不该改到的单位"},
    )
    assert patched.status_code == 404

    client.post(
        "/api/auth/login",
        json={"email": first["email"], "password": "Password123!"},
    )
    filled = client.patch(
        f"/api/experience/{copied.json()['id']}",
        json={
            "organization": template["organization"],
            "summary": template["summary"],
        },
    )
    assert filled.status_code == 200
    still_blocked = client.post(f"/api/experience/{copied.json()['id']}/confirm")
    assert still_blocked.status_code == 422

    own = client.patch(
        f"/api/experience/{copied.json()['id']}",
        json={
            "organization": "我自己实习过的工厂",
            "summary": "跟随师傅完成点检，只描述自己做过的步骤。",
        },
    )
    assert own.status_code == 200
    confirmed = client.post(f"/api/experience/{copied.json()['id']}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["linked_to_facts"] is True


def test_parse_resume_prefills_materials_without_inventing_metrics(client, db):
    user = register(client)
    resume = client.post("/api/resumes", files=docx_file()).json()
    assert client.post(f"/api/resumes/{resume['id']}/confirm-facts").status_code == 200
    from app.models.entities import Resume, User as UserModel

    db_user = db.get(UserModel, user["id"])
    db_resume = db.get(Resume, resume["id"])
    sync_confirmed_facts_to_experience(db, db_user, db_resume)
    db.commit()
    items = client.get("/api/experience?source=original_resume").json()["items"]
    assert items
    for item in items:
        details = item.get("details_json") or {}
        assert details.get("metrics", "") == ""


def test_blank_project_material_does_not_require_upload(client):
    register(client)
    created = client.post(
        "/api/experience",
        json={"kind": "project", "title": "课程装配体练习"},
    )
    assert created.status_code == 201
    assert created.json()["status"] == "draft"
    assert created.json()["linked_to_facts"] is False


def test_clarifications_only_cover_missing_fields(client):
    register(client)
    created = client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": "课程装配体",
            "organization": "示例大学",
            "summary": "完成装配体建模",
            "details_json": {"results": "输出工程图"},
        },
    ).json()
    asked = client.post(f"/api/experience/{created['id']}/clarifications")
    assert asked.status_code == 200, asked.text
    fields = {item["field"] for item in asked.json()["clarifications_json"]}
    assert "ownership" in fields
    assert "results" not in fields
    assert asked.json()["status"] == "draft"


def test_award_without_verification_is_rejected(client):
    register(client)
    created = client.post(
        "/api/experience",
        json={
            "kind": "award",
            "title": "优秀学生奖学金",
            "organization": "示例大学",
            "summary": "获得校级奖学金",
        },
    ).json()
    blocked = client.post(f"/api/experience/{created['id']}/confirm")
    assert blocked.status_code == 422
    assert "核验" in blocked.text


def test_edit_confirmed_material_unconfirms_facts(client, db):
    register(client)
    created = client.post(
        "/api/experience",
        json={
            "kind": "project",
            "title": "装配体",
            "organization": "我自己的实验室",
            "role_title": "负责人",
            "summary": "完成装配体建模",
            "details_json": {"actions": "建模", "tools": "SolidWorks", "results": "输出工程图"},
        },
    ).json()
    confirmed = client.post(f"/api/experience/{created['id']}/confirm")
    assert confirmed.status_code == 200
    edited = client.patch(
        f"/api/experience/{created['id']}",
        json={"details_json": {"results": "输出修改后的工程图"}},
    )
    assert edited.status_code == 200
    assert edited.json()["status"] == "draft"
    facts = list(db.scalars(select(ResumeFact).where(ResumeFact.material_id == created["id"])))
    assert facts
    assert all(fact.verification_status != "user_confirmed" for fact in facts)


def test_seed_templates_are_idempotent(db):
    assert seed_templates(db) >= 1
    db.commit()
    assert seed_templates(db) == 0
    assert len(list(db.scalars(select(ExperienceEntry).where(ExperienceEntry.source == "template")))) >= 4
