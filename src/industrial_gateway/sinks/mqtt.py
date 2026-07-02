from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from industrial_gateway.models import BatchMessage, MqttConfig


class MqttSink:
    def __init__(self, config: MqttConfig | dict[str, Any]) -> None:
        self.config = _mqtt_config(config)
        self.client: Any | None = None

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
        try:
            self.client.connect(self.config.host, self.config.port)
            self.client.loop_start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if self.client is not None:
            client = self.client
            self.client = None
            try:
                client.loop_stop()
            finally:
                client.disconnect()

    def publish_batch(self, message: BatchMessage) -> None:
        if self.client is None:
            raise RuntimeError("MQTT sink is not started")
        payload = json.dumps(_mqtt_payload(message), ensure_ascii=False, separators=(",", ":"))
        result = self.client.publish(self._effective_topic(message), payload, qos=message.qos)
        if getattr(result, "rc", 0) != 0:
            raise RuntimeError(f"MQTT publish failed with rc={result.rc}")

    def _effective_topic(self, message: BatchMessage) -> str:
        if message.use_message_topic:
            return message.topic.strip("/")
        return self.config.base_topic.strip("/")


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


def _mqtt_payload(message: BatchMessage) -> dict[str, Any]:
    if "tags" not in message.payload:
        return dict(message.payload)
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
