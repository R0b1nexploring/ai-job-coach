from conftest import SyncASGIClient, register
from sqlalchemy import func, select

from app.models.entities import AuditLog, User, UserProfile
from app.security import hash_password


def test_password_change_rotates_current_session_and_revokes_other_sessions(client, db):
    user_data = register(client, email="sessions@example.test")
    other_session = SyncASGIClient()
    login = other_session.post(
        "/api/auth/login",
        json={"email": "sessions@example.test", "password": "Password123!"},
    )
    assert login.status_code == 200

    changed = client.post(
        "/api/auth/change-password",
        json={"current_password": "Password123!", "new_password": "NewPassword456!"},
    )
    assert changed.status_code == 204, changed.text
    assert client.get("/api/auth/me").status_code == 200
    stale = other_session.get("/api/auth/me")
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "UNAUTHORIZED"

    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login",
        json={"email": user_data["email"], "password": "Password123!"},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": user_data["email"], "password": "NewPassword456!"},
    ).status_code == 200


def test_deletion_request_is_idempotent_and_pending_account_is_restricted(client, db):
    user_data = register(client, email="deletion@example.test")

    first = client.delete("/api/account")
    second = client.delete("/api/account")
    assert first.status_code == second.status_code == 202
    assert first.json()["deletion_requested_at"] == second.json()["deletion_requested_at"]
    assert client.get("/api/auth/me").json()["status"] == "deletion_requested"

    blocked = client.get("/api/resumes")
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "ACCOUNT_DELETION_PENDING"

    other_session = SyncASGIClient()
    relogin = other_session.post(
        "/api/auth/login",
        json={"email": user_data["email"], "password": "Password123!"},
    )
    assert relogin.status_code == 403
    count = db.scalar(
        select(func.count(AuditLog.id)).where(
            AuditLog.actor_user_id == user_data["id"],
            AuditLog.action == "account.deletion_requested",
        )
    )
    assert count == 1
    assert db.get(User, user_data["id"]).status == "deletion_requested"


def test_privileged_account_cannot_enter_unserviceable_deletion_state(client, db):
    admin = User(
        email="self-delete-admin@example.test",
        password_hash=hash_password("Password123!"),
        display_name="管理员",
        role="admin",
    )
    db.add(admin)
    db.flush()
    db.add(UserProfile(user_id=admin.id))
    db.commit()
    assert client.post(
        "/api/auth/login",
        json={"email": admin.email, "password": "Password123!"},
    ).status_code == 200

    response = client.delete("/api/account")
    assert response.status_code == 403
    db.refresh(admin)
    assert admin.status == "active"


def test_deleted_account_sentinel_hash_cannot_crash_login(client, db):
    deleted = User(
        email="deleted-login@example.test",
        password_hash="account-deleted",
        display_name="已删除用户",
        status="deleted",
    )
    db.add(deleted)
    db.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": deleted.email, "password": "Password123!"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
