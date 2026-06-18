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

    route = client.post(
        "/api/plugin-routes",
        json={
            "device_id": device["id"],
            "tag_group": "temp",
            "sink_type": "mqtt",
            "enabled": True,
            "config": {
                "topic": "plant/temp/current",
                "host": "route-broker",
                "port": 1883,
                "base_topic": "route",
                "client_id": "route",
                "qos": 0,
            },
        },
    )
    assert route.status_code == 200
    routes = client.get("/api/plugin-routes").json()
    assert routes[0]["device_id"] == device["id"]
    assert routes[0]["device_name"] == "plc-1"
    assert routes[0]["tag_group"] == "temp"
    assert routes[0]["sink_type"] == "mqtt"
    assert routes[0]["config"] == {"topic": "plant/temp/current"}


def test_schema_api_exposes_driver_and_plugin_fields(tmp_path):
    client = make_client(tmp_path)

    drivers = client.get("/api/schema/drivers")
    plugins = client.get("/api/schema/plugins")

    assert drivers.status_code == 200
    assert drivers.json()["modbus_tcp"]["connection_fields"][0]["key"] == "host"
    assert drivers.json()["opcua"]["tag_functions"] == ["opcua_node"]
    assert plugins.status_code == 200
    assert list(plugins.json()) == ["mqtt"]
    assert plugins.json()["mqtt"]["fields"][0]["key"] == "host"


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
    assert message["payload"]["running"] is True


def test_device_csv_import_and_export(tmp_path):
    client = make_client(tmp_path)
    csv_text = "\n".join(
        [
            "device_group,device_name,driver_type,enabled,poll_interval_ms,host,port,unit_id,tag_group,tag_name,address,function,data_type,scale,tag_enabled",
            "line-a,plc-1,modbus_tcp,1,1000,127.0.0.1,502,1,temp,temperature,100,holding_register,float32,1.0,1",
            "",
        ]
    )

    imported = client.post("/api/devices/import", content=csv_text, headers={"Content-Type": "text/csv"})

    assert imported.status_code == 200
    assert imported.json() == {"devices": 1, "tags": 1}
    devices = client.get("/api/devices").json()
    assert devices[0]["name"] == "plc-1"
    tags = client.get(f"/api/devices/{devices[0]['id']}/tags").json()
    assert tags[0]["name"] == "temperature"

    exported = client.get("/api/devices.csv")

    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "plc-1" in exported.text
    assert "temperature" in exported.text


def test_tag_csv_import_and_export(tmp_path):
    client = make_client(tmp_path)
    device = client.post(
        "/api/devices",
        json={
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840/freeopcua/server/", "mode": "polling"},
        },
    ).json()
    csv_text = "\n".join(
        [
            "tag_group,name,node_id,address,function,data_type,scale,enabled",
            "pressures,bar,ns=2;s=Machine.Bar,0,opcua_node,auto,1.0,1",
            "",
        ]
    )

    imported = client.post(
        f"/api/devices/{device['id']}/tags/import",
        content=csv_text,
        headers={"Content-Type": "text/csv"},
    )

    assert imported.status_code == 200
    assert imported.json() == {"tags": 1}
    tags = client.get(f"/api/devices/{device['id']}/tags").json()
    assert tags[0]["node_id"] == "ns=2;s=Machine.Bar"

    exported = client.get(f"/api/devices/{device['id']}/tags.csv")

    assert exported.status_code == 200
    assert "bar" in exported.text
    assert "ns=2;s=Machine.Bar" in exported.text


def test_plugin_csv_import_and_export(tmp_path):
    client = make_client(tmp_path)
    csv_text = "\n".join(
        [
            "sink_type,selected,enabled,host,port,base_topic,username,password,client_id,qos,dynamic_topic_enabled,mac_address",
            "mqtt,1,1,broker,1883,plant,user,secret,gw,1,1,AA:BB",
            "",
        ]
    )

    imported = client.post("/api/plugins/import", content=csv_text, headers={"Content-Type": "text/csv"})

    assert imported.status_code == 200
    assert imported.json() == {"plugins": 1, "routes": 0}
    plugin = client.get("/api/plugins/mqtt").json()
    assert plugin["config"]["host"] == "broker"
    assert plugin["config"]["dynamic_topic_enabled"] is True

    exported = client.get("/api/plugins.csv")

    assert exported.status_code == 200
    assert "text/csv" in exported.headers["content-type"]
    assert "broker" in exported.text
    assert "AA:BB" in exported.text

    device = client.post(
        "/api/devices",
        json={
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        },
    ).json()
    client.post(
        "/api/plugin-routes",
        json={"device_id": device["id"], "tag_group": "PHH01", "enabled": True, "config": {"topic": "plant/opc/PHH01/data"}},
    )

    exported_with_route = client.get("/api/plugins.csv")

    assert "route" in exported_with_route.text
    assert "PHH01" in exported_with_route.text
    assert "plant/opc/PHH01/data" in exported_with_route.text


def test_plugin_route_csv_import_and_export(tmp_path):
    client = make_client(tmp_path)
    device = client.post(
        "/api/devices",
        json={
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        },
    ).json()
    csv_text = "\n".join(
        [
            "device_group,device_name,tag_group,sink_type,enabled,topic",
            "line,opc,PHH01,mqtt,1,plant/opc/PHH01/data",
            "",
        ]
    )

    imported = client.post("/api/plugin-routes/import", content=csv_text, headers={"Content-Type": "text/csv"})

    assert imported.status_code == 200
    assert imported.json() == {"routes": 1}
    route = client.get("/api/plugin-routes").json()[0]
    assert route["device_id"] == device["id"]
    assert route["config"] == {"topic": "plant/opc/PHH01/data"}

    exported = client.get("/api/plugin-routes.csv")

    assert exported.status_code == 200
    assert "PHH01" in exported.text
    assert "plant/opc/PHH01/data" in exported.text
