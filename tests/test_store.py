from industrial_gateway.models import DeviceSpec, MqttConfig, TagSpec
from industrial_gateway.store import ConfigStore
import pytest


def test_sqlite_store_round_trips_device_tags_and_mqtt_config(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()

    device = DeviceSpec(
        id=None,
        name="line-1",
        driver_type="modbus_tcp",
        enabled=True,
        poll_interval_ms=500,
        connection={"host": "10.0.0.5", "port": 502, "unit_id": 1},
    )
    device_id = store.save_device(device)
    store.save_tag(
        TagSpec(
            id=None,
            device_id=device_id,
            name="speed",
            address=100,
            function="holding_register",
            data_type="uint16",
            scale=0.1,
            enabled=True,
        )
    )
    store.save_mqtt_config(MqttConfig(host="broker.local", port=1884, base_topic="factory"))

    devices = store.list_devices()
    tags = store.list_tags(device_id)
    mqtt = store.get_mqtt_config()

    assert devices[0].id == device_id
    assert devices[0].device_group == ""
    assert devices[0].connection["host"] == "10.0.0.5"
    assert tags[0].name == "speed"
    assert tags[0].scale == 0.1
    assert mqtt.host == "broker.local"
    assert mqtt.base_topic == "factory"


def test_sqlite_store_updates_and_deletes_tags(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    device_id = store.save_device(
        DeviceSpec(
            id=None,
            name="line-1",
            driver_type="modbus_tcp",
            enabled=True,
            poll_interval_ms=500,
            connection={"host": "10.0.0.5", "port": 502, "unit_id": 1},
        )
    )
    tag_id = store.save_tag(
        TagSpec(
            id=None,
            device_id=device_id,
            name="speed",
            address=100,
            function="holding_register",
            data_type="uint16",
            enabled=True,
        )
    )

    store.save_tag(
        TagSpec(
            id=tag_id,
            device_id=device_id,
            name="line_speed",
            address=101,
            function="holding_register",
            data_type="uint16",
            enabled=True,
        )
    )

    assert store.list_tags(device_id)[0].name == "line_speed"
    assert store.list_tags(device_id)[0].address == 101

    store.delete_tag(tag_id)

    assert store.list_tags(device_id) == []


def test_sqlite_store_rejects_duplicate_tag_names_in_same_group(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    device_id = store.save_device(
        DeviceSpec(
            id=None,
            name="line-1",
            driver_type="modbus_tcp",
            enabled=True,
            poll_interval_ms=500,
            connection={"host": "10.0.0.5", "port": 502, "unit_id": 1},
        )
    )
    store.save_tag(
        TagSpec(
            device_id=device_id,
            tag_group="PHH01",
            name="speed",
            address=100,
            function="holding_register",
            data_type="uint16",
        )
    )

    with pytest.raises(ValueError, match="already exists"):
        store.save_tag(
            TagSpec(
                device_id=device_id,
                tag_group="PHH01",
                name="speed",
                address=101,
                function="holding_register",
                data_type="uint16",
            )
        )

    store.save_tag(
        TagSpec(
            device_id=device_id,
            tag_group="PHH02",
            name="speed",
            address=101,
            function="holding_register",
            data_type="uint16",
        )
    )

    assert len(store.list_tags(device_id)) == 2
