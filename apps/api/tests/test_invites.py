from datetime import UTC, datetime, timedelta

from conftest import register
from sqlalchemy import select

from app.config import get_settings
from app.models.entities import InviteCode, User
from app.security import hash_invite_code, hash_password


def login_admin(client, db):
    db.add(
        User(
            email="admin@example.test",
            password_hash=hash_password("Password123!"),
            display_name="管理员",
            role="admin",
        )
    )
    db.commit()
    response = client.post(
        "/api/auth/login",
        json={"email": "admin@example.test", "password": "Password123!"},
    )
    assert response.status_code == 200, response.text


def create_invite(client, **overrides):
    payload = {"label": "首批试用", "max_uses": 1}
    payload.update(overrides)
    response = client.post("/api/admin/invites", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_admin_creates_invite_and_only_hash_is_persisted(client, db):
    login_admin(client, db)
    created = create_invite(client)
    assert created["code"]

    row = db.scalar(select(InviteCode).where(InviteCode.id == created["id"]))
    assert row is not None
    assert row.code_hash == hash_invite_code(created["code"])
    assert created["code"] not in row.code_hash
    assert "code" not in client.get("/api/admin/invites").json()["items"][0]


def test_invite_signup_redeems_code_and_grants_resume_quota(client, db):
    login_admin(client, db)
    created = create_invite(client)
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/register",
        json={
            "email": "invited@example.test",
            "password": "Password123!",
            "display_name": "受邀用户",
            "invite_code": created["code"],
        },
    )
    assert response.status_code == 201, response.text
    assert client.get("/api/quotas").json()["resume"] == get_settings().invite_resume_quota

    row = db.scalar(select(InviteCode).where(InviteCode.id == created["id"]))
    db.refresh(row)
    assert row.used_count == 1


def test_single_use_invite_cannot_register_twice(client, db):
    login_admin(client, db)
    created = create_invite(client)
    client.post("/api/auth/logout")

    first = client.post(
        "/api/auth/register",
        json={
            "email": "first@example.test",
            "password": "Password123!",
            "display_name": "甲",
            "invite_code": created["code"],
        },
    )
    assert first.status_code == 201
    client.post("/api/auth/logout")

    second = client.post(
        "/api/auth/register",
        json={
            "email": "second@example.test",
            "password": "Password123!",
            "display_name": "乙",
            "invite_code": created["code"],
        },
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "INVITE_INVALID"


def test_revoked_invite_is_rejected(client, db):
    login_admin(client, db)
    created = create_invite(client)
    assert client.post(f"/api/admin/invites/{created['id']}/revoke").status_code == 200
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/register",
        json={
            "email": "revoked@example.test",
            "password": "Password123!",
            "display_name": "丙",
            "invite_code": created["code"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVITE_INVALID"


def test_expired_invite_is_rejected(client, db):
    login_admin(client, db)
    created = create_invite(client)
    row = db.scalar(select(InviteCode).where(InviteCode.id == created["id"]))
    row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    client.post("/api/auth/logout")

    response = client.post(
        "/api/auth/register",
        json={
            "email": "expired@example.test",
            "password": "Password123!",
            "display_name": "丁",
            "invite_code": created["code"],
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVITE_INVALID"


def test_invite_required_only_when_enabled(client, monkeypatch):
    monkeypatch.setenv("REGISTRATION_REQUIRE_INVITE", "true")
    get_settings.cache_clear()
    try:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "no-invite@example.test",
                "password": "Password123!",
                "display_name": "无码",
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "INVITE_REQUIRED"
    finally:
        get_settings.cache_clear()


def test_non_admin_cannot_manage_invites(client):
    register(client)
    assert client.post("/api/admin/invites", json={}).status_code == 403
    assert client.get("/api/admin/invites").status_code == 403
