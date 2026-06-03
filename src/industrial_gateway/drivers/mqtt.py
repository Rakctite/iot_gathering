from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Callable

from industrial_gateway.models import DeviceSpec, ReadResult, TagResult, TagSpec


class MqttInputDriver:
    def __init__(self, device: DeviceSpec, tags: list[TagSpec]) -> None:
        self.device = device
        self.tags = tags
        self.client: Any | None = None
        self.emit: Callable[[ReadResult], None] | None = None
        self._connected = False

    def connect(self) -> None:
        if self.client is None:
            try:
                import paho.mqtt.client as mqtt
            except ImportError as exc:
                raise RuntimeError("paho-mqtt is required for MQTT input") from exc
            client_id = _client_id(self.device)
            self.client = mqtt.Client(client_id=client_id)
        username = str(self.device.connection.get("username") or "")
        password = str(self.device.connection.get("password") or "")
        if username:
            self.client.username_pw_set(username, password or None)
        host = str(self.device.connection.get("host") or "localhost")
        port = int(self.device.connection.get("port") or 1883)
        self.client.connect(host, port)
        self.client.loop_start()
        self._connected = True

    def disconnect(self) -> None:
        if self.client is None:
            return
        if self._connected:
            self.client.loop_stop()
            self.client.disconnect()
        self._connected = False

    def read_tags(self) -> list[TagResult]:
        timestamp = datetime.now(timezone.utc)
        return [_bad(tag, timestamp, "MQTT input driver only supports subscription mode") for tag in self.tags]

    def read_server_status(self) -> Any:
        if not self._connected:
            raise RuntimeError("MQTT input client is not connected")
        return {"connected": True}

    def start_subscription(self, emit: Callable[[ReadResult], None]) -> None:
        if self.client is None:
            raise RuntimeError("MQTT input client is not connected")
        self.emit = emit
        self.client.on_message = self._on_message
        topic_filter = str(self.device.connection.get("topic_filter") or "").strip()
        if not topic_filter:
            raise RuntimeError("MQTT topic_filter is required")
        qos = int(self.device.connection.get("qos") or 0)
        self.client.subscribe(topic_filter, qos=qos)

    def stop_subscription(self) -> None:
        if self.client is None:
            return
        topic_filter = str(self.device.connection.get("topic_filter") or "").strip()
        if topic_filter:
            self.client.unsubscribe(topic_filter)
        self.emit = None

    def run_subscription_once(self, timeout: float = 0.2) -> None:
        time.sleep(timeout)

    def _on_message(self, _client: Any, _userdata: Any, message: Any) -> None:
        if self.emit is None:
            return
        timestamp = datetime.now(timezone.utc)
        try:
            payload = json.loads(_payload_text(message.payload))
            timestamp = _payload_timestamp(payload, self.device.connection) or timestamp
            tags = [_tag_result(tag, payload, timestamp) for tag in self.tags]
        except Exception as exc:
            tags = [_bad(tag, timestamp, str(exc)) for tag in self.tags]
        self.emit(ReadResult(self.device, timestamp, tags))


def _client_id(device: DeviceSpec) -> str:
    base = str(device.connection.get("client_id") or "industrial-gateway-input").strip()
    suffix = str(device.id or device.name).strip().replace(" ", "-")
    if not suffix:
        return base
    if base.endswith(f"-{suffix}"):
        return base
    return f"{base}-{suffix}"


def _payload_text(payload: bytes | bytearray | str) -> str:
    if isinstance(payload, str):
        return payload
    return bytes(payload).decode("utf-8")


def _payload_timestamp(payload: dict[str, Any], connection: dict[str, Any]) -> datetime | None:
    field = str(connection.get("timestamp_field") or "").strip()
    if not field:
        return None
    value = _field_value(payload, field)
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def _tag_result(tag: TagSpec, payload: dict[str, Any], timestamp: datetime) -> TagResult:
    field = tag.node_id or tag.name
    try:
        value = _field_value(payload, field)
        if value is None:
            raise KeyError(field)
        return TagResult(
            tag.name,
            tag.address,
            _coerce_value(value, tag),
            "good",
            None,
            timestamp,
            node_id=field,
            tag_group=tag.tag_group,
        )
    except Exception as exc:
        return TagResult(
            tag.name,
            tag.address,
            None,
            "bad",
            str(exc),
            timestamp,
            node_id=field,
            tag_group=tag.tag_group,
        )


def _field_value(payload: dict[str, Any], field: str) -> Any:
    value: Any = payload
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _coerce_value(value: Any, tag: TagSpec) -> Any:
    if tag.data_type == "auto":
        return _auto_value(value)
    if tag.data_type == "string":
        return str(value)
    if tag.data_type == "bool":
        return bool(value)
    if tag.data_type in {"int16", "uint16", "int32", "uint32"}:
        return int(value) * tag.scale
    if tag.data_type in {"float32", "float64"}:
        return float(value) * tag.scale
    return value


def _auto_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        if any(marker in text for marker in (".", "e", "E")):
            return float(text)
        return int(text)
    except ValueError:
        return value


def _bad(tag: TagSpec, timestamp: datetime, error: str) -> TagResult:
    return TagResult(tag.name, tag.address, None, "bad", error, timestamp, node_id=tag.node_id, tag_group=tag.tag_group)
