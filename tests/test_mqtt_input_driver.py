from types import SimpleNamespace

import pytest

from industrial_gateway.drivers.mqtt import MqttInputDriver, _client_id
from industrial_gateway.models import DeviceSpec, TagSpec


class FakeMqttClient:
    def __init__(self):
        self.on_message = None
        self.subscriptions = []
        self.unsubscriptions = []
        self.loop_stops = 0
        self.disconnects = 0

    def subscribe(self, topic_filter, qos=0):
        self.subscriptions.append((topic_filter, qos))

    def unsubscribe(self, topic_filter):
        self.unsubscriptions.append(topic_filter)

    def loop_stop(self):
        self.loop_stops += 1

    def disconnect(self):
        self.disconnects += 1


def test_mqtt_input_driver_subscribes_and_maps_json_payload_to_tags():
    device = DeviceSpec(
        id=1,
        name="curiot",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={
            "topic_filter": "curiot/+/data",
            "qos": 1,
            "timestamp_field": "Time",
            "sensor_id_field": "sensor_id",
        },
    )
    tags = [
        TagSpec(name="r", address=0, function="json_field", data_type="float32", node_id="r"),
        TagSpec(name="s", address=0, function="json_field", data_type="float32", node_id="s"),
        TagSpec(name="t", address=0, function="json_field", data_type="float32", node_id="t"),
    ]
    driver = MqttInputDriver(device, tags)
    driver.client = FakeMqttClient()
    emitted = []

    driver.start_subscription(lambda result: emitted.append(result))
    driver._on_message(
        None,
        None,
        SimpleNamespace(
            topic="curiot/AABBCCDDEEFF/data",
            payload=b'{"sensor_id":"CURIOT-A213","Time":"2026-05-26 11:31:39","r":1.397,"s":1.364,"t":1.23}',
        ),
    )
    driver.stop_subscription()

    assert driver.client.subscriptions == [("curiot/+/data", 1)]
    assert driver.client.unsubscriptions == ["curiot/+/data"]
    assert emitted[0].device.name == "curiot"
    assert emitted[0].timestamp.year == 2026
    assert [tag.name for tag in emitted[0].tags] == ["r", "s", "t"]
    assert [tag.value for tag in emitted[0].tags] == [1.397, 1.364, 1.23]
    assert all(tag.quality == "good" for tag in emitted[0].tags)


def test_mqtt_input_driver_marks_missing_fields_bad():
    device = DeviceSpec(
        id=1,
        name="curiot",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={"topic_filter": "curiot/+/data"},
    )
    tags = [TagSpec(name="r", address=0, function="json_field", data_type="auto", node_id="r")]
    driver = MqttInputDriver(device, tags)
    driver.client = FakeMqttClient()
    emitted = []

    driver.start_subscription(lambda result: emitted.append(result))
    driver._on_message(None, None, SimpleNamespace(topic="curiot/mac/data", payload=b'{"s":1.0}'))

    assert emitted[0].tags[0].quality == "bad"
    assert emitted[0].tags[0].error == "'r'"


def test_mqtt_input_driver_auto_converts_numeric_strings():
    device = DeviceSpec(
        id=1,
        name="ipriot",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={"topic_filter": "ipriot/+/data"},
    )
    tags = [
        TagSpec(name="temperature", address=0, function="json_field", data_type="auto", node_id="temperature"),
        TagSpec(name="left", address=0, function="json_field", data_type="auto", node_id="left"),
        TagSpec(name="din1", address=0, function="json_field", data_type="auto", node_id="din1"),
        TagSpec(name="sensor_id", address=0, function="json_field", data_type="auto", node_id="sensor_id"),
    ]
    driver = MqttInputDriver(device, tags)
    driver.client = FakeMqttClient()
    emitted = []

    driver.start_subscription(lambda result: emitted.append(result))
    driver._on_message(
        None,
        None,
        SimpleNamespace(
            topic="ipriot/mac/data",
            payload=(
                b'{"sensor_id":"IPRIOT-A201","temperature":"76.5",'
                b'"left":"0.4835249999999981","din1":"0"}'
            ),
        ),
    )

    values = [tag.value for tag in emitted[0].tags]
    assert values == [76.5, 0.4835249999999981, 0, "IPRIOT-A201"]
    assert [type(value) for value in values] == [float, float, int, str]


def test_mqtt_input_driver_client_id_is_unique_per_device():
    first = DeviceSpec(
        id=3,
        name="NeatherA",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={"client_id": "industrial-gateway-input"},
    )
    second = DeviceSpec(
        id=4,
        name="MixingRollA",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={"client_id": "industrial-gateway-input"},
    )

    assert _client_id(first) == "industrial-gateway-input-3"
    assert _client_id(second) == "industrial-gateway-input-4"


def test_mqtt_input_driver_raises_when_client_disconnects_during_subscription():
    device = DeviceSpec(
        id=1,
        name="curiot",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={"topic_filter": "curiot/+/data"},
    )
    driver = MqttInputDriver(device, [])
    driver.client = FakeMqttClient()
    driver._connected = True

    driver._on_disconnect(None, None, 7)

    with pytest.raises(RuntimeError, match="disconnected"):
        driver.run_subscription_once(0)


def test_mqtt_input_driver_disconnect_cleans_up_after_unexpected_disconnect():
    device = DeviceSpec(
        id=1,
        name="curiot",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={"topic_filter": "curiot/+/data"},
    )
    driver = MqttInputDriver(device, [])
    client = FakeMqttClient()
    driver.client = client
    driver._connected = True

    driver._on_disconnect(None, None, 7)
    driver.disconnect()

    assert client.loop_stops == 1
    assert client.disconnects == 1
    assert driver.client is None
