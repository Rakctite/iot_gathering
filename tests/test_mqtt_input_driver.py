from types import SimpleNamespace

from industrial_gateway.drivers.mqtt import MqttInputDriver, _client_id
from industrial_gateway.models import DeviceSpec, TagSpec


class FakeMqttClient:
    def __init__(self):
        self.on_message = None
        self.subscriptions = []
        self.unsubscriptions = []

    def subscribe(self, topic_filter, qos=0):
        self.subscriptions.append((topic_filter, qos))

    def unsubscribe(self, topic_filter):
        self.unsubscriptions.append(topic_filter)


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
