import json
import sys
import types

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


class ConnectFailingClient:
    def __init__(self):
        self.loop_stops = 0
        self.disconnects = 0

    def connect(self, host, port):
        raise OSError("broker down")

    def loop_stop(self):
        self.loop_stops += 1

    def disconnect(self):
        self.disconnects += 1


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


def test_mqtt_sink_publishes_status_payload_to_message_topic():
    sink = MqttSink({})
    sink.client = FakeClient()
    message = BatchMessage(
        topic="industrial/status/NeatherD",
        qos=1,
        payload={"device": {"id": 8, "name": "NeatherD"}, "status": "stale"},
        use_message_topic=True,
    )

    sink.publish_batch(message)

    topic, payload, qos, _retain = sink.client.published[0]
    assert topic == "industrial/status/NeatherD"
    assert json.loads(payload)["status"] == "stale"
    assert qos == 1


def test_mqtt_sink_start_cleans_up_client_when_connect_fails(monkeypatch):
    created = []

    class FakeMqttModule:
        @staticmethod
        def Client(client_id=None):
            client = ConnectFailingClient()
            created.append(client)
            return client

    paho_module = types.ModuleType("paho")
    mqtt_package = types.ModuleType("paho.mqtt")
    mqtt_package.client = FakeMqttModule
    paho_module.mqtt = mqtt_package
    monkeypatch.setitem(sys.modules, "paho", paho_module)
    monkeypatch.setitem(sys.modules, "paho.mqtt", mqtt_package)
    monkeypatch.setitem(sys.modules, "paho.mqtt.client", FakeMqttModule)
    sink = MqttSink({"host": "broker", "port": 1883})

    with pytest.raises(OSError, match="broker down"):
        sink.start()

    assert created[0].loop_stops == 1
    assert created[0].disconnects == 1
    assert sink.client is None
