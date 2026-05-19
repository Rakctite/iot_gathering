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


def test_missing_device_raises_key_error(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(KeyError, match="device not found"):
        service.get_device(999)
