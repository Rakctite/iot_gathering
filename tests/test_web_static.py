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
    assert "prevTagPage" in html
    assert "prevDevicePage" not in html
    assert "prevGroupPage" not in html
    assert "runtime-log-scroll" in html
    assert "pluginRouteForm" in html
    assert "pluginRouteList" in html
    assert "pluginRouteEditor" in html
    assert "pluginRouteListPanel" in html
    assert "tagPageRows" in script
    assert "deleteDevice" in script
    assert "deleteTag" in script
    assert "savePluginRoute" in script
    assert "renderPluginRouteVisibility" in script
    assert 'sink_type: "mqtt"' in script
    assert "pluginRouteFields" not in script
    assert 'name="topic"' in script
    assert "tag_group" in script
    assert "tagPageSize: 12" in script
    assert "runtimePageRows" in script
    assert "runtimePageSize: 12" in script
    assert "runtimeDevicePage" not in script
    assert "runtimeGroupPage" not in script
    assert "grid-template-rows: minmax(0, 3fr) minmax(0, 1fr)" in styles
    assert "grid-template-rows: auto auto" not in styles
    assert ".runtime-log-scroll" in styles
    assert "overflow-x: auto" in styles
    assert "white-space: pre" in styles
    assert ".runtime-log-scroll { position: relative" in styles
    assert ".runtime-log-panel pre { position: absolute" in styles
    assert "width: max-content" in styles
    assert "max-width: 0" in styles
    assert "body { margin: 0; font-family: Segoe UI, Arial, sans-serif; color: #172026; background: #f4f6f8; overflow-x: hidden; }" in styles
    assert ".runtime-grid { width: 100%; max-width: calc(100vw - 36px)" in styles
    assert ".runtime-tags-panel, .runtime-log-panel { min-height: 0; min-width: 0; max-width: 100%; overflow: hidden;" in styles
