from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

TagFunction = Literal["holding_register", "input_register", "coil", "discrete_input", "opcua_node"]
TagDataType = Literal[
    "auto",
    "bool",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "float32",
    "float64",
    "string",
]
Quality = Literal["good", "bad"]


@dataclass(frozen=True)
class DeviceSpec:
    id: int | None
    name: str
    driver_type: str
    enabled: bool
    poll_interval_ms: int
    connection: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TagSpec:
    name: str
    address: int
    function: TagFunction
    data_type: TagDataType
    id: int | None = None
    device_id: int | None = None
    scale: float = 1.0
    enabled: bool = True
    word_count: int | None = None
    byte_order: str = "big"
    word_order: str = "big"
    node_id: str | None = None


@dataclass(frozen=True)
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    base_topic: str = "industrial"
    username: str | None = None
    password: str | None = None
    client_id: str = "industrial-gateway"
    qos: int = 0
    enabled: bool = True


@dataclass(frozen=True)
class SinkConfig:
    sink_type: str = "mqtt"
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TagResult:
    name: str
    address: int
    value: Any
    quality: Quality
    error: str | None
    timestamp: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "address": self.address,
            "value": self.value,
            "quality": self.quality,
            "error": self.error,
            "timestamp": _iso(self.timestamp),
        }


@dataclass(frozen=True)
class ReadResult:
    device: DeviceSpec
    timestamp: datetime
    tags: list[TagResult]
    error: str | None = None


@dataclass(frozen=True)
class BatchMessage:
    topic: str
    payload: dict[str, Any]
    qos: int = 0

    @classmethod
    def from_results(
        cls,
        device: DeviceSpec,
        tags: list[TagResult],
        timestamp: datetime | None,
        mqtt: MqttConfig,
    ) -> "BatchMessage":
        effective_timestamp = timestamp or datetime.now(timezone.utc)
        base_topic = mqtt.base_topic.strip("/")
        device_topic = _topic_token(device.name)
        return cls(
            topic=f"{base_topic}/{device_topic}/data",
            qos=mqtt.qos,
            payload={
                "device": {"id": device.id, "name": device.name},
                "timestamp": _iso(effective_timestamp),
                "tags": [tag.to_payload() for tag in tags],
            },
        )


def validate_modbus_tag(tag: TagSpec) -> None:
    if not tag.name.strip():
        raise ValueError("tag name is required")
    if tag.address < 0:
        raise ValueError("tag address must be zero or greater")
    if tag.function not in {"holding_register", "input_register", "coil", "discrete_input"}:
        raise ValueError(f"unsupported Modbus function: {tag.function}")
    _validate_common_tag_fields(tag)


def validate_opcua_tag(tag: TagSpec) -> None:
    if not tag.name.strip():
        raise ValueError("tag name is required")
    if tag.function != "opcua_node":
        raise ValueError(f"unsupported OPC UA function: {tag.function}")
    if not tag.node_id or not tag.node_id.strip():
        raise ValueError("OPC UA tag node_id is required")
    _validate_common_tag_fields(tag)


def validate_tag(driver_type: str, tag: TagSpec) -> None:
    if driver_type == "opcua":
        validate_opcua_tag(tag)
    else:
        validate_modbus_tag(tag)


def _validate_common_tag_fields(tag: TagSpec) -> None:
    if tag.data_type not in {"auto", "bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"}:
        raise ValueError(f"unsupported tag data type: {tag.data_type}")
    if tag.scale == 0:
        raise ValueError("tag scale cannot be zero")
    if tag.data_type == "string" and (tag.word_count is None or tag.word_count < 1):
        raise ValueError("string tag word_count must be at least 1")
    if tag.data_type != "string" and tag.word_count is not None and tag.word_count < 1:
        raise ValueError("tag word_count must be at least 1")
    if tag.byte_order not in {"big", "little"}:
        raise ValueError("tag byte_order must be big or little")
    if tag.word_order not in {"big", "little"}:
        raise ValueError("tag word_order must be big or little")


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _topic_token(value: str) -> str:
    return value.strip().replace(" ", "-")
