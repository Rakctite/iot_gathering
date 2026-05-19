from pathlib import Path

from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def test_index_served(tmp_path):
    app = create_app(tmp_path / "gateway.sqlite3", session_secret="secret")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Industrial Gateway" in response.text
    assert "/static/app.js" in response.text


def test_web_ui_uses_field_forms_instead_of_json_inputs():
    script = (Path(__file__).parents[1] / "src" / "industrial_gateway" / "web" / "static" / "app.js").read_text()

    assert "Connection JSON" not in script
    assert "Config JSON" not in script
