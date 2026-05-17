from industrial_gateway.defaults import driver_registry
from industrial_gateway.drivers.opcua import OpcUaDriver
from industrial_gateway.models import TagSpec, validate_tag
from industrial_gateway.store import ConfigStore


def test_opcua_driver_is_registered():
    assert driver_registry.get("opcua") is OpcUaDriver


def test_opcua_tag_validation_requires_node_id():
    tag = TagSpec(name="speed", address=0, function="opcua_node", data_type="auto", node_id="ns=2;s=Speed")

    validate_tag("opcua", tag)


def test_sqlite_store_round_trips_opcua_node_id(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    device_id = store.save_device(
        device=__import__("industrial_gateway.models", fromlist=["DeviceSpec"]).DeviceSpec(
            id=None,
            name="opc",
            driver_type="opcua",
            enabled=True,
            poll_interval_ms=1000,
            connection={"endpoint": "opc.tcp://localhost:4840"},
        )
    )

    store.save_tag(
        TagSpec(
            device_id=device_id,
            name="speed",
            address=0,
            function="opcua_node",
            data_type="auto",
            node_id="ns=2;s=Speed",
        )
    )

    assert store.list_tags(device_id)[0].node_id == "ns=2;s=Speed"
