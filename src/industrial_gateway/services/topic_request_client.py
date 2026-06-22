from __future__ import annotations

import json
import threading
import time
from typing import Any


def request_topic_by_mac(mac_address: str, mqtt_config: dict[str, Any]) -> dict[str, Any]:
    try:
        import paho.mqtt.client as mqtt
    except ImportError as exc:
        raise RuntimeError("paho-mqtt is required for topic requests") from exc

    mac = str(mac_address).strip()
    if not mac:
        raise ValueError("mac_address is required")

    topic_event = threading.Event()
    sensor_event = threading.Event()
    state: dict[str, Any] = {"topic": "", "sensor_count": 0}
    client_id = str(mqtt_config.get("client_id") or "industrial-gateway")
    client = mqtt.Client(client_id=f"{client_id}-topic-request-{int(time.time() * 1000)}")
    username = mqtt_config.get("username")
    if username:
        client.username_pw_set(str(username), mqtt_config.get("password") or None)

    def on_message(_client: Any, _userdata: Any, message: Any) -> None:
        payload = _decode_payload(message.payload)
        if message.topic == f"S-C/request-topic/{mac}" and isinstance(payload, dict):
            state["topic"] = str(payload.get("topic") or "")
            topic_event.set()
        elif message.topic == f"S-C/request-sensor_cd/{mac}" and isinstance(payload, list):
            state["sensor_count"] = len(payload)
            sensor_event.set()

    client.on_message = on_message
    try:
        client.connect(str(mqtt_config.get("host") or "localhost"), int(mqtt_config.get("port") or 1883))
        client.subscribe([(f"S-C/request-topic/{mac}", 2), (f"S-C/request-sensor_cd/{mac}", 2)])
        client.loop_start()
        client.publish("C-S/request-topic", json.dumps({"mac": mac}), qos=2, retain=False)
        if not topic_event.wait(timeout=5):
            raise TimeoutError(f"topic response timeout for {mac}")
        client.publish("C-S/request-sensor_cd", json.dumps({"mac": mac}), qos=2, retain=False)
        sensor_event.wait(timeout=5)
        return state
    finally:
        client.loop_stop()
        client.disconnect()


def _decode_payload(payload: bytes | str) -> Any:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)
