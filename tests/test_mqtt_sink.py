import json

import pytest

from industrial_gateway.models import BatchMessage
from industrial_gateway.sinks.mqtt import MqttSink


class FakePublishResult:
    rc = 0


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return FakePublishResult()


class FakeMessage:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload


def test_mqtt_sink_updates_received_topic_path_from_request_response():
    sink = MqttSink({"dynamic_topic_enabled": True, "mac_address": "AA:BB"})

    sink._handle_config_message(
        None,
        None,
        FakeMessage("S-C/request-topic/AA:BB", b'{"topic":"3120/PH/PHH/LO001/MC08/-/OPCUA:PLC/"}'),
    )

    assert sink.received_topic_path == "C-S/3120/PH/PHH/LO001/MC08/-/OPCUA:PLC/"


def test_mqtt_sink_rewrites_publish_topic_when_dynamic_topic_is_available():
    sink = MqttSink({"dynamic_topic_enabled": True, "mac_address": "AA:BB"})
    sink.client = FakeClient()
    sink.received_topic_path = "C-S/3120/PH/PHH/LO001/MC08/-/OPCUA:PLC/"
    message = BatchMessage(
        topic="industrial/CKP_OPCUA/PHH01/data",
        qos=2,
        payload={"device": {"id": 1, "name": "CKP_OPCUA"}, "tags": []},
    )

    sink.publish_batch(message)

    assert sink.client.published[0][0] == "C-S/3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/"
    assert sink.client.published[0][2] == 2


def test_mqtt_sink_keeps_matching_mc_group_for_phh08():
    sink = MqttSink({"dynamic_topic_enabled": True, "mac_address": "AA:BB"})
    sink.client = FakeClient()
    sink.received_topic_path = "C-S/3120/PH/PHH/LO001/MC08/-/OPCUA:PLC/"
    message = BatchMessage(
        topic="industrial/CKP_OPCUA/PHH08/data",
        qos=0,
        payload={"device": {"id": 1, "name": "CKP_OPCUA"}, "tags": []},
    )

    sink.publish_batch(message)

    assert sink.client.published[0][0] == "C-S/3120/PH/PHH/LO001/MC08/-/OPCUA:PLC/"


def test_mqtt_sink_uses_latest_received_topic_path():
    sink = MqttSink({"dynamic_topic_enabled": True, "mac_address": "AA:BB"})
    sink.client = FakeClient()
    sink._handle_config_message(
        None,
        None,
        FakeMessage("S-C/request-topic/AA:BB", b'{"topic":"3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/"}'),
    )
    sink._handle_config_message(
        None,
        None,
        FakeMessage("S-C/request-topic/AA:BB", b'{"topic":"9999/PH/PHH/LO777/MC01/-/OPCUA:PLC/"}'),
    )
    message = BatchMessage(
        topic="industrial/CKP_OPCUA/PHH08/data",
        qos=0,
        payload={"device": {"id": 1, "name": "CKP_OPCUA"}, "tags": []},
    )

    sink.publish_batch(message)

    assert sink.client.published[0][0] == "C-S/9999/PH/PHH/LO777/MC08/-/OPCUA:PLC/"


def test_mqtt_sink_stores_sensor_codes_sorted_by_id():
    sink = MqttSink({"dynamic_topic_enabled": True, "mac_address": "AA:BB"})

    sink._handle_config_message(
        None,
        None,
        FakeMessage(
            "S-C/request-sensor_cd/AA:BB",
            b'[{"id":2,"sensor_code":"B"},{"id":1,"sensor_code":"A"}]',
        ),
    )

    assert sink.sensor_codes == ["A", "B"]


def test_mqtt_sink_publishes_flat_tag_payload():
    sink = MqttSink({})
    sink.client = FakeClient()
    message = BatchMessage(
        topic="industrial/CKP_OPCUA/data",
        qos=0,
        payload={
            "device": {"id": 1, "name": "CKP_OPCUA"},
            "timestamp": "2026-05-18T11:36:45.278+07",
            "tags": [
                {"name": "PV_CUR_MOLD_N11", "value": 12.3},
                {"name": "SV_Mold_N01_P1", "value": "ABC"},
            ],
        },
    )

    sink.publish_batch(message)

    payload = json.loads(sink.client.published[0][1])
    assert payload == {
        "timestamp": "2026-05-18 11:36:45.278+07",
        "PV_CUR_MOLD_N11": 12.3,
        "SV_Mold_N01_P1": "ABC",
    }


def test_mqtt_sink_formats_timestamp_for_telegraf_json_time_format():
    sink = MqttSink({})
    sink.client = FakeClient()
    message = BatchMessage(
        topic="industrial/current",
        qos=0,
        payload={
            "timestamp": "2026-05-26T08:18:54.674316+00:00",
            "tags": [{"name": "r", "value": 0.1}],
        },
    )

    sink.publish_batch(message)

    payload = json.loads(sink.client.published[0][1])
    assert payload["timestamp"] == "2026-05-26 08:18:54.674+00"


def test_mqtt_sink_without_dynamic_topic_publishes_to_base_topic_only():
    sink = MqttSink({"base_topic": "industrial/current"})
    sink.client = FakeClient()
    message = BatchMessage(
        topic="industrial/CKP_OPCUA/PHH08/data",
        qos=0,
        payload={"timestamp": "t", "tags": [{"name": "r", "value": 1.2}]},
    )

    sink.publish_batch(message)

    assert sink.client.published[0][0] == "industrial/current"


def test_mqtt_sink_can_publish_routed_message_topic_with_shared_client():
    sink = MqttSink({"base_topic": "industrial/current"})
    sink.client = FakeClient()
    message = BatchMessage(
        topic="industrial/CKP_OPCUA/PHH08/data",
        qos=0,
        payload={"timestamp": "t", "tags": [{"name": "r", "value": 1.2}]},
        use_message_topic=True,
    )

    sink.publish_batch(message)

    assert sink.client.published[0][0] == "industrial/CKP_OPCUA/PHH08/data"


def test_mqtt_sink_dynamic_topic_waits_for_received_topic():
    sink = MqttSink({"dynamic_topic_enabled": True, "mac_address": "TCP:OPCUA"})
    sink.client = FakeClient()
    message = BatchMessage(
        topic="industrial/CKP_OPCUA/PHH08/data",
        qos=0,
        payload={"timestamp": "t", "tags": []},
    )

    with pytest.raises(RuntimeError, match="dynamic topic"):
        sink.publish_batch(message)
