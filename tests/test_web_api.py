from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def make_client(tmp_path):
    app = create_app(
        store_path=tmp_path / "gateway.sqlite3",
        session_secret="secret",
        admin_username="admin",
        admin_password="password",
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    return client


def test_device_tag_plugin_api_round_trip(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/devices",
        json={
            "name": "plc-1",
            "driver_type": "modbus_tcp",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"host": "127.0.0.1", "port": 502, "unit_id": 1},
        },
    )
    assert created.status_code == 200
    device = created.json()
    assert client.get("/api/devices").json()[0]["name"] == "plc-1"

    tag_response = client.post(
        f"/api/devices/{device['id']}/tags",
        json={
            "name": "temperature",
            "address": 100,
            "function": "holding_register",
            "data_type": "float32",
            "scale": 1.0,
            "enabled": True,
        },
    )
    assert tag_response.status_code == 200
    assert client.get(f"/api/devices/{device['id']}/tags").json()[0]["name"] == "temperature"

    plugin = client.put(
        "/api/plugins/mqtt",
        json={
            "enabled": True,
            "config": {"host": "broker", "port": 1883, "base_topic": "plant", "client_id": "gw", "qos": 0},
        },
    )
    assert plugin.status_code == 200
    assert client.get("/api/plugins/mqtt").json()["config"]["host"] == "broker"


def test_runtime_status_endpoint_is_protected(tmp_path):
    app = create_app(
        tmp_path / "gateway.sqlite3",
        session_secret="secret",
        admin_username="admin",
        admin_password="password",
    )
    client = TestClient(app)

    response = client.get("/api/runtime/status")

    assert response.status_code == 401


def test_runtime_events_websocket_sends_snapshot(tmp_path):
    client = make_client(tmp_path)

    with client.websocket_connect("/api/runtime/events") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "snapshot"
    assert message["payload"]["running"] is False
