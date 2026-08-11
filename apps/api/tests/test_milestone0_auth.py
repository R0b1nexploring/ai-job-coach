from app.security import hash_password, verify_password
from conftest import register


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"
    providers = response.json()["providers"]
    assert providers["llm"]["provider"] == "mock"
    assert providers["llm"]["operational"] is True
    assert providers["payment"]["provider"] == "disabled"
    assert providers["jobs"]["providers"] == [
        "sample",
        "public_catalog",
        "greenhouse",
        "lever",
        "public_jsonld",
    ]


def test_password_hash_and_login(client):
    hashed = hash_password("Password123!")
    assert hashed != "Password123!" and verify_password("Password123!", hashed)
    register(client)
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"email": "a@example.test", "password": "Password123!"}
        ).status_code
        == 200
    )


def test_duplicate_registration_has_standard_error(client):
    register(client)
    response = client.post(
        "/api/auth/register",
        json={"email": "a@example.test", "password": "Password123!", "display_name": "重复"},
    )
    assert response.status_code == 409
    assert set(response.json()["error"]) == {"code", "message", "details", "request_id"}


def test_validation_error_uses_standard_contract(client):
    response = client.post(
        "/api/auth/register", json={"email": "bad", "password": "short", "display_name": ""}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
