from sqlalchemy import select

from app.models.entities import ExperienceEntry, ResumeFact
from app.services.experience_service import seed_templates
from conftest import register


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
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["is_own"] is True
    assert body["linked_to_facts"] is True
    fact = db.get(ResumeFact, body["linked_fact_id"])
    assert fact.provenance == "user_added"
    assert fact.verification_status == "user_confirmed"
    assert fact.category == "employment"


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


def test_seed_templates_are_idempotent(db):
    assert seed_templates(db) >= 1
    db.commit()
    assert seed_templates(db) == 0
    assert len(list(db.scalars(select(ExperienceEntry).where(ExperienceEntry.source == "template")))) >= 4
