from pathlib import Path

from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def test_index_served(tmp_path):
    app = create_app(tmp_path / "gateway.sqlite3", session_secret="secret")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Industrial Gateway" in response.text
    assert 'id="appVersion"' in response.text
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
    assert "runtimeLogEnabled" in html
    assert "device-layout" in html
    assert "device-editor-grid" in html
    assert "device-data-stack" in html
    assert "device-list-scroll" in html
    assert "device-list-table" in html
    assert "tagListHead" in html
    assert "tagViewMode" in html
    assert "pluginRouteForm" in html
    assert "pluginRouteList" in html
    assert "plugin-editor-grid" in html
    assert "pluginRouteEditor" in html
    assert "pluginRouteListPanel" in html
    assert "importPlugins" in html
    assert "exportPlugins" in html
    assert "pluginCsvFile" in html
    assert "importTags" not in html
    assert "exportTags" not in html
    assert "tagCsvFile" not in html
    assert "importPluginRoutes" not in html
    assert "exportPluginRoutes" not in html
    assert "pluginRouteCsvFile" not in html
    assert "tagPageRows" in script
    assert "tagViewMode: \"group\"" in script
    assert "toggleTagViewMode" in script
    assert "tagViewMode === \"all\"" in script
    assert "loadAllDeviceTags" in script
    assert 'api("/api/tags")' in script
    assert "Promise.all(state.devices.map" not in script
    assert "renderTagTableHeader" in script
    assert "device_name" in script
    assert "deviceEndpoint" in script
    assert "deviceMode" in script
    assert "deleteDevice" in script
    assert "deleteTag" in script
    assert "savePluginRoute" in script
    assert "importPluginsCsv" in script
    assert "importTagsCsv" not in script
    assert "importPluginRoutesCsv" not in script
    assert "/api/plugins.csv" in script
    assert "/api/plugin-routes.csv" not in script
    assert "renderPluginRouteVisibility" in script
    assert 'sink_type: "mqtt"' in script
    assert "pluginRouteFields" not in script
    assert 'name="topic"' in script
    assert "System Heartbeat" in script
    assert "system_heartbeat" in script
    assert 'name="heartbeat_interval_s"' in script
    assert 'name="sensor_code"' in script
    assert "tag_group" in script
    assert "tagPageSize: 21" in script
    assert "runtimePageRows" in script
    assert "runtimePageSize: 12" in script
    assert "runtime_log_enabled" in script
    assert "runtimeLogEnabled.disabled" in script
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
    assert ".device-layout { display: grid; grid-template-columns: minmax(560px, 700px) minmax(0, 1fr)" in styles
    assert ".device-editor-grid { display: grid; grid-template-columns: minmax(260px, 320px) minmax(280px, 360px)" in styles
    assert ".device-list-scroll { max-height: 198px; overflow-y: auto;" in styles
    assert ".device-list-table th:nth-child(4), .device-list-table td:nth-child(4)" in styles
    assert ".runtime-grid { width: 100%; max-width: calc(100vw - 36px)" in styles
    assert ".runtime-tags-panel { min-height: 430px;" in styles
    assert ".runtime-table { width: 100%; max-width: 100%; min-width: 0; table-layout: fixed; flex: 0 0 auto;" in styles
    assert ".plugin-layout { display: grid; grid-template-columns: minmax(560px, 700px) minmax(0, 1fr)" in styles
    assert ".plugin-editor-grid { display: grid; grid-template-columns: minmax(260px, 320px) minmax(280px, 360px)" in styles
    assert ".runtime-tags-panel, .runtime-log-panel { min-height: 0; min-width: 0; max-width: 100%; overflow: hidden;" in styles


def test_runtime_events_update_local_state_without_refetching_status():
    script = (Path(__file__).parents[1] / "src" / "industrial_gateway" / "web" / "static" / "app.js").read_text()

    assert "applyRuntimeEvent(message)" in script
    assert "function upsertRuntimeTag" in script
    assert "function scheduleRuntimeRender" in script
    assert "requestAnimationFrame" in script
    assert 'if (message.type === "log" || message.type === "tag_update" || message.type === "server_status") loadRuntime();' not in script


def test_tag_form_exposes_modbus_count_and_readable_data_type_labels():
    script = (Path(__file__).parents[1] / "src" / "industrial_gateway" / "web" / "static" / "app.js").read_text()

    assert "isModbusDriver(driverType)" in script
    assert 'name="count"' in script
    assert "NodeId" in script
    assert "int16 (2 bytes, 1 word)" in script
    assert "float64 (8 bytes, 4 words)" in script


def test_modbus_rtu_monitor_device_form_has_probe_controls():
    script = (Path(__file__).parents[1] / "src" / "industrial_gateway" / "web" / "static" / "app.js").read_text()

    assert "isModbusRtuMonitorDriver" in script
    assert "Read first frame" in script
    assert "First frame result" in script
    assert "/api/devices/modbus-rtu-monitor/probe" in script
    assert "probeModbusRtuMonitor" in script
