from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any

from industrial_gateway.models import BatchMessage, MqttConfig


class MqttSink:
    def __init__(self, config: MqttConfig | dict[str, Any]) -> None:
        raw_config = config if isinstance(config, dict) else {}
        self.config = _mqtt_config(config)
        self.client: Any | None = None
        self.dynamic_topic_enabled = bool(raw_config.get("dynamic_topic_enabled", False))
        self.mac_address = str(raw_config.get("mac_address") or "").strip()
        self.received_topic_path: str | None = None
        self.sensor_codes: list[str] = []
        self._topic_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._topic_event = threading.Event()
        self._sensor_event = threading.Event()

    def start(self) -> None:
        if not self.config.enabled:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required for MQTT publishing") from exc
        self.client = mqtt.Client(client_id=self.config.client_id)
        if self.config.username:
            self.client.username_pw_set(self.config.username, self.config.password)
        self.client.connect(self.config.host, self.config.port)
        self.client.loop_start()
        if self.dynamic_topic_enabled and self.mac_address:
            self.client.on_message = self._handle_config_message
            self.client.subscribe(
                [
                    (f"S-C/request-topic/{self.mac_address}", 2),
                    (f"S-C/request-sensor_cd/{self.mac_address}", 2),
                ]
            )
            self._topic_thread = threading.Thread(target=self._run_topic_requests, daemon=True)
            self._topic_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._topic_thread is not None:
            self._topic_thread.join(timeout=2)
            self._topic_thread = None
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

    def publish_batch(self, message: BatchMessage) -> None:
        if self.client is None:
            raise RuntimeError("MQTT sink is not started")
        payload = json.dumps(_mqtt_payload(message), ensure_ascii=False, separators=(",", ":"))
        result = self.client.publish(self._effective_topic(message), payload, qos=message.qos)
        if getattr(result, "rc", 0) != 0:
            raise RuntimeError(f"MQTT publish failed with rc={result.rc}")

    def _effective_topic(self, message: BatchMessage) -> str:
        if not self.received_topic_path:
            if self.dynamic_topic_enabled:
                raise RuntimeError("MQTT dynamic topic has not been received yet")
            if message.use_message_topic:
                return message.topic.strip("/")
            return self.config.base_topic.strip("/")
        group = _phh_group_from_topic(message.topic)
        if group is None:
            return self.received_topic_path
        return _topic_for_phh_group(self.received_topic_path, group)

    def _run_topic_requests(self) -> None:
        while not self._stop_event.is_set():
            if self.client is None:
                return
            self._topic_event.clear()
            self.client.publish("C-S/request-topic", json.dumps({"mac": self.mac_address}), qos=2, retain=False)
            if not self._topic_event.wait(timeout=3):
                self._stop_event.wait(3)
                continue

            self._sensor_event.clear()
            self.client.publish("C-S/request-sensor_cd", json.dumps({"mac": self.mac_address}), qos=2, retain=False)
            if not self._sensor_event.wait(timeout=3):
                self._stop_event.wait(3)
                continue

            for _ in range(60):
                if self._stop_event.wait(1):
                    return

    def _handle_config_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            topic = str(message.topic)
            payload = _decode_payload(message.payload)
            if topic == f"S-C/request-topic/{self.mac_address}":
                new_topic = payload.get("topic") if isinstance(payload, dict) else None
                if not new_topic:
                    return
                self.received_topic_path = _received_topic_path(str(new_topic))
                self._topic_event.set()
            elif topic == f"S-C/request-sensor_cd/{self.mac_address}":
                if not isinstance(payload, list):
                    return
                sorted_payload = sorted(payload, key=lambda item: item.get("id", 0))
                self.sensor_codes = [item["sensor_code"] for item in sorted_payload if "sensor_code" in item]
                self._sensor_event.set()
        except Exception:
            return


def _mqtt_config(config: MqttConfig | dict[str, Any]) -> MqttConfig:
    if isinstance(config, MqttConfig):
        return config
    return MqttConfig(
        host=config.get("host", "localhost"),
        port=int(config.get("port", 1883)),
        base_topic=config.get("base_topic", "industrial"),
        username=config.get("username") or None,
        password=config.get("password") or None,
        client_id=config.get("client_id", "industrial-gateway"),
        qos=int(config.get("qos", 0)),
        enabled=bool(config.get("enabled", True)),
    )


def _decode_payload(payload: bytes | str) -> Any:
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)


def _mqtt_payload(message: BatchMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"timestamp": _mqtt_timestamp(message.payload.get("timestamp"))}
    for tag in message.payload.get("tags", []):
        name = tag.get("name")
        if not name:
            continue
        value = tag.get("value")
        payload[name] = value
    return payload


def _mqtt_timestamp(timestamp: Any) -> str:
    if timestamp is None:
        return ""
    parsed = _parse_timestamp(timestamp)
    if parsed is None:
        return str(timestamp).replace("T", " ")
    offset = parsed.strftime("%z")
    offset_hour = offset[:3] if len(offset) >= 3 else offset
    return f"{parsed:%Y-%m-%d %H:%M:%S}.{parsed.microsecond // 1000:03d}{offset_hour}"


def _parse_timestamp(timestamp: Any) -> datetime | None:
    if isinstance(timestamp, datetime):
        return timestamp
    if not isinstance(timestamp, str):
        return None
    text = timestamp.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _phh_group_from_topic(topic: str) -> str | None:
    for part in topic.strip("/").split("/"):
        if part.upper().startswith("PHH"):
            return part.upper()
    return None


def _topic_for_phh_group(topic_template: str, phh_group: str) -> str:
    mc_group = _mc_group_from_phh(phh_group)
    has_trailing_slash = topic_template.endswith("/")
    parts = topic_template.strip("/").split("/")
    for index, part in enumerate(parts):
        if part.upper().startswith("MC") and part[2:].isdigit():
            parts[index] = mc_group
            return _join_topic_parts(parts, has_trailing_slash)
    return _join_topic_parts(parts, has_trailing_slash)


def _mc_group_from_phh(phh_group: str) -> str:
    suffix = phh_group[3:]
    if suffix.isdigit():
        return f"MC{int(suffix):02d}"
    return phh_group


def _received_topic_path(topic: str) -> str:
    stripped = topic.lstrip("/")
    if stripped.startswith("C-S/"):
        return stripped
    return f"C-S/{stripped}"


def _join_topic_parts(parts: list[str], has_trailing_slash: bool) -> str:
    topic = "/".join(parts)
    if has_trailing_slash:
        return f"{topic}/"
    return topic
