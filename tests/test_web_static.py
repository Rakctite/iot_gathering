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


def test_runtime_tab_has_pagination_controls():
    root = Path(__file__).parents[1] / "src" / "industrial_gateway" / "web" / "static"
    html = (root / "index.html").read_text()
    script = (root / "app.js").read_text()
    styles = (root / "styles.css").read_text()

    assert "prevTagGroupPage" in html
    assert "prevTagListPage" in html
    assert "prevDevicePage" in html
    assert "prevGroupPage" in html
    assert "prevTagPage" in html
    assert "tagPageRows" in script
    assert "tagPageSize: 12" in script
    assert "runtimePageRows" in script
    assert "runtimePageSize: 12" in script
    assert "grid-template-rows: minmax(0, 3fr) minmax(0, 1fr)" in styles
    assert "grid-template-rows: auto auto" not in styles
