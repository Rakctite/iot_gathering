from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FieldKind = Literal["text", "int", "float", "choice"]


@dataclass(frozen=True)
class ConnectionField:
    key: str
    label: str
    kind: FieldKind
    default: Any
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


_COMMON_MODBUS_LIMITS = (
    ConnectionField("unit_id", "Unit ID", "int", 1, minimum=1, maximum=247),
    ConnectionField("max_block_gap", "Max block gap", "int", 4, minimum=0, maximum=1000),
    ConnectionField("max_registers_per_read", "Max registers/read", "int", 125, minimum=1, maximum=125),
    ConnectionField("max_bits_per_read", "Max bits/read", "int", 2000, minimum=1, maximum=2000),
)

_FIELDS: dict[str, tuple[ConnectionField, ...]] = {
    "modbus_tcp": (
        ConnectionField("host", "IP / Host", "text", "127.0.0.1"),
        ConnectionField("port", "Port", "int", 502, minimum=1, maximum=65535),
        *_COMMON_MODBUS_LIMITS,
    ),
    "modbus_serial": (
        ConnectionField("port", "Serial port", "text", "COM1"),
        ConnectionField("baudrate", "Baudrate", "int", 9600, minimum=300, maximum=4000000),
        ConnectionField("parity", "Parity", "choice", "N", choices=("N", "E", "O")),
        ConnectionField("stopbits", "Stop bits", "int", 1, minimum=1, maximum=2),
        ConnectionField("bytesize", "Byte size", "int", 8, minimum=5, maximum=8),
        ConnectionField("timeout", "Timeout sec", "float", 2.0),
        *_COMMON_MODBUS_LIMITS,
    ),
    "opcua": (
        ConnectionField("endpoint", "Endpoint", "text", "opc.tcp://127.0.0.1:4840/freeopcua/server/"),
        ConnectionField("mode", "Mode", "choice", "polling", choices=("polling", "subscription")),
        ConnectionField("subscription_interval_ms", "Subscription ms", "int", 250, minimum=50, maximum=60000),
    ),
}


def connection_fields_for_driver(driver_type: str) -> list[ConnectionField]:
    return list(_FIELDS.get(driver_type, ()))


def default_connection_for_driver(driver_type: str) -> dict[str, Any]:
    return {field.key: field.default for field in connection_fields_for_driver(driver_type)}


def normalize_connection_for_driver(driver_type: str, existing: dict[str, Any] | None) -> dict[str, Any]:
    values = default_connection_for_driver(driver_type)
    if existing:
        for field in connection_fields_for_driver(driver_type):
            if field.key in existing:
                values[field.key] = existing[field.key]
    return values


def tag_function_choices_for_driver(driver_type: str) -> list[str]:
    if driver_type == "opcua":
        return ["opcua_node"]
    return ["holding_register", "input_register", "coil", "discrete_input"]


def tag_type_choices_for_driver(driver_type: str) -> list[str]:
    if driver_type == "opcua":
        return ["auto", "bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"]
    return ["bool", "int16", "uint16", "int32", "uint32", "float32", "float64", "string"]
