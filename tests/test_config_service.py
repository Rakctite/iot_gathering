import pytest

from industrial_gateway.services.config_service import ConfigService
from industrial_gateway.store import ConfigStore


def make_service(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    return ConfigService(store)


def test_device_crud_round_trip(tmp_path):
    service = make_service(tmp_path)

    device = service.create_device(
        {
            "device_group": "line1",
            "name": "plc-1",
            "driver_type": "modbus_tcp",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"host": "127.0.0.1", "port": 502, "unit_id": 1},
        }
    )

    assert device["id"] is not None
    assert service.list_devices()[0]["name"] == "plc-1"

    updated = service.update_device(device["id"], {**device, "name": "plc-main"})
    assert updated["name"] == "plc-main"

    service.delete_device(device["id"])
    assert service.list_devices() == []


def test_tag_crud_round_trip(tmp_path):
    service = make_service(tmp_path)
    device = service.create_device(
        {
            "name": "plc-1",
            "driver_type": "modbus_tcp",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"host": "127.0.0.1", "port": 502, "unit_id": 1},
        }
    )

    tag = service.create_tag(
        device["id"],
        {
            "name": "temperature",
            "address": 100,
            "function": "holding_register",
            "data_type": "float32",
            "scale": 1.0,
            "enabled": True,
        },
    )

    assert service.list_tags(device["id"])[0]["name"] == "temperature"

    updated = service.update_tag(tag["id"], {**tag, "scale": 10.0})
    assert updated["scale"] == 10.0

    service.delete_tag(tag["id"])
    assert service.list_tags(device["id"]) == []


def test_plugin_save_selects_sink(tmp_path):
    service = make_service(tmp_path)

    saved = service.save_sink_config(
        {
            "sink_type": "mqtt",
            "enabled": True,
            "config": {"host": "broker", "port": 1883, "base_topic": "plant", "client_id": "gw", "qos": 1},
        }
    )

    assert saved["sink_type"] == "mqtt"
    assert service.get_selected_sink_config()["config"]["host"] == "broker"


def test_plugin_csv_import_and_export_round_trip(tmp_path):
    service = make_service(tmp_path)
    device = service.create_device(
        {
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        }
    )
    service.save_sink_config(
        {
            "sink_type": "mqtt",
            "enabled": True,
            "config": {
                "host": "broker",
                "port": 1883,
                "base_topic": "plant",
                "username": "user",
                "password": "secret",
                "client_id": "gw",
                "qos": 1,
                "topic_request_on_start": True,
                "topic_refresh_interval_s": 120,
            },
        }
    )
    service.save_sink_config(
        {
            "sink_type": "postgresql",
            "enabled": False,
            "config": {"host": "db", "port": 5432, "database": "gateway", "username": "admin", "password": "pw"},
        }
    )
    service.save_output_route(
        {
            "device_id": device["id"],
            "tag_group": "PHH01",
            "enabled": True,
            "config": {
                "topic": "plant/opc/PHH01/data",
                "dynamic_topic_enabled": True,
                "mac_address": "AA:BB",
            },
        }
    )

    csv_text = service.export_plugins_csv()
    imported = make_service(tmp_path / "plugins")
    imported.create_device(
        {
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        }
    )
    result = imported.import_plugins_csv(csv_text)

    mqtt = imported.get_sink_config("mqtt")
    pg = imported.get_sink_config("postgresql")
    routes = imported.list_output_routes()
    assert result == {"plugins": 2, "routes": 1}
    assert "record_type" in csv_text
    assert "route" in csv_text
    assert "plant/opc/PHH01/data" in csv_text
    assert mqtt["enabled"] is True
    assert mqtt["selected"] is False
    assert mqtt["config"]["host"] == "broker"
    assert mqtt["config"]["topic_request_on_start"] is True
    assert mqtt["config"]["topic_refresh_interval_s"] == 120
    assert "dynamic_topic_enabled" not in mqtt["config"]
    assert "mac_address" not in mqtt["config"]
    assert pg["enabled"] is False
    assert pg["selected"] is True
    assert pg["config"]["host"] == "db"
    assert routes[0]["device_name"] == "opc"
    assert routes[0]["tag_group"] == "PHH01"
    assert routes[0]["config"]["topic"] == "plant/opc/PHH01/data"
    assert routes[0]["config"]["dynamic_topic_enabled"] is True
    assert routes[0]["config"]["mac_address"] == "AA:BB"


def test_resolve_output_route_topic_updates_route_config(tmp_path):
    service = make_service(tmp_path)
    device = service.create_device(
        {
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        }
    )
    route = service.save_output_route(
        {
            "device_id": device["id"],
            "tag_group": "PHH01",
            "enabled": True,
            "config": {"dynamic_topic_enabled": True, "mac_address": "AA:BB"},
        }
    )

    resolved = service.resolve_output_route_topic(
        route["id"],
        resolver=lambda mac, _mqtt_config: {
            "topic": "3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/",
            "sensor_count": 12,
        },
    )

    assert resolved["resolved_topic"] == "C-S/3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/"
    assert resolved["sensor_count"] == 12
    saved = service.list_output_routes()[0]
    assert saved["config"]["resolved_topic"] == "C-S/3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/"
    assert saved["config"]["resolved_sensor_count"] == 12
    assert saved["mac_address"] == "AA:BB"


def test_resolve_output_route_topic_stores_error_result(tmp_path):
    service = make_service(tmp_path)
    device = service.create_device(
        {
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        }
    )
    route = service.save_output_route(
        {
            "device_id": device["id"],
            "tag_group": "PHH01",
            "enabled": True,
            "config": {"dynamic_topic_enabled": True, "mac_address": "AA:BB"},
        }
    )

    result = service.resolve_output_route_topic(
        route["id"],
        resolver=lambda _mac, _mqtt_config: (_ for _ in ()).throw(TimeoutError("topic response timeout")),
    )

    assert result["error"] == "topic response timeout"
    saved = service.list_output_routes()[0]
    assert saved["config"]["resolved_error"] == "topic response timeout"


def test_plugin_route_csv_import_and_export_round_trip(tmp_path):
    service = make_service(tmp_path)
    device = service.create_device(
        {
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        }
    )
    service.save_output_route(
        {
            "device_id": device["id"],
            "tag_group": "PHH01",
            "enabled": True,
            "config": {
                "topic": "plant/opc/PHH01/data",
                "dynamic_topic_enabled": True,
                "mac_address": "AA:BB",
            },
        }
    )

    csv_text = service.export_plugin_routes_csv()
    imported = make_service(tmp_path / "routes")
    imported_device = imported.create_device(
        {
            "device_group": "line",
            "name": "opc",
            "driver_type": "opcua",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        }
    )
    result = imported.import_plugin_routes_csv(csv_text)

    routes = imported.list_output_routes()
    assert result == {"routes": 1}
    assert routes[0]["device_id"] == imported_device["id"]
    assert routes[0]["device_name"] == "opc"
    assert routes[0]["tag_group"] == "PHH01"
    assert routes[0]["config"]["topic"] == "plant/opc/PHH01/data"
    assert routes[0]["config"]["dynamic_topic_enabled"] is True
    assert routes[0]["config"]["mac_address"] == "AA:BB"


def test_device_csv_round_trips_mqtt_connection_fields(tmp_path):
    service = make_service(tmp_path)
    service.create_device(
        {
            "device_group": "sensors",
            "name": "rollgap",
            "driver_type": "mqtt",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {
                "host": "10.10.49.7",
                "port": 1883,
                "topic_filter": "rollgap/+/data",
                "client_id": "rollgap-input",
                "username": "user",
                "password": "secret",
                "qos": 1,
                "topic_mac_index": 2,
                "timestamp_field": "Time",
                "sensor_id_field": "sensor_id",
            },
        }
    )

    csv_text = service.export_devices_csv()
    imported = make_service(tmp_path / "imported")
    imported.import_devices_csv(csv_text)

    device = imported.list_devices()[0]
    assert device["connection"]["topic_filter"] == "rollgap/+/data"
    assert device["connection"]["client_id"] == "rollgap-input"
    assert device["connection"]["username"] == "user"
    assert device["connection"]["password"] == "secret"
    assert device["connection"]["qos"] == 1
    assert device["connection"]["topic_mac_index"] == 2
    assert device["connection"]["timestamp_field"] == "Time"
    assert device["connection"]["sensor_id_field"] == "sensor_id"


def test_missing_device_raises_key_error(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(KeyError, match="device not found"):
        service.get_device(999)
