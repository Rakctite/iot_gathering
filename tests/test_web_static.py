from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def test_index_served(tmp_path):
    app = create_app(tmp_path / "gateway.sqlite3", session_secret="secret")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Industrial Gateway" in response.text
    assert "/static/app.js" in response.text
