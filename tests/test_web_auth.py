from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def make_client(tmp_path):
    app = create_app(
        store_path=tmp_path / "gateway.sqlite3",
        session_secret="secret",
        admin_username="admin",
        admin_password="password",
    )
    return TestClient(app)


def test_protected_session_requires_login(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/session")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_login_and_logout(tmp_path):
    client = make_client(tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    assert login.json() == {"authenticated": True, "username": "admin"}

    session = client.get("/api/session")
    assert session.status_code == 200
    assert session.json()["username"] == "admin"

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    assert client.get("/api/session").status_code == 401


def test_bad_login_rejected(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_credentials"
