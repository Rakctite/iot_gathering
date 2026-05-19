from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ConnectionFieldKind = Literal["text", "int", "float", "choice"]
PluginFieldKind = Literal["text", "int", "bool", "password"]


@dataclass(frozen=True)
class ConnectionField:
    key: str
    label: str
    kind: ConnectionFieldKind
    default: Any
    choices: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class PluginField:
    key: str
    label: str
    kind: PluginFieldKind
    default: Any
    minimum: int | None = None
    maximum: int | None = None


_COMMON_MODBUS_LIMITS = (
    ConnectionField("unit_id", "Unit ID", "int", 1, minimum=1, maximum=247),
    ConnectionField("max_block_gap", "Max block gap", "int", 4, minimum=0, maximum=1000),
    ConnectionField("max_registers_per_read", "Max registers/read", "int", 125, minimum=1, maximum=125),
    ConnectionField("max_bits_per_read", "Max bits/read", "int", 2000, minimum=1, maximum=2000),
)

_CONNECTION_FIELDS: dict[str, tuple[ConnectionField, ...]] = {
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

_PLUGIN_FIELDS: dict[str, tuple[PluginField, ...]] = {
    "mqtt": (
        PluginField("host", "Host", "text", "localhost"),
        PluginField("port", "Port", "int", 1883, minimum=1, maximum=65535),
        PluginField("base_topic", "Base topic", "text", "industrial"),
        PluginField("username", "Username", "text", ""),
        PluginField("password", "Password", "password", ""),
        PluginField("client_id", "Client ID", "text", "industrial-gateway"),
        PluginField("qos", "QoS", "int", 0, minimum=0, maximum=2),
        PluginField("dynamic_topic_enabled", "Request topic by MAC", "bool", False),
        PluginField("mac_address", "MAC address", "text", ""),
    ),
    "postgresql": (
        PluginField("host", "Host", "text", "localhost"),
        PluginField("port", "Port", "int", 5432, minimum=1, maximum=65535),
        PluginField("database", "Database", "text", "gateway"),
        PluginField("username", "Username", "text", "postgres"),
        PluginField("password", "Password", "password", ""),
        PluginField("table", "Table", "text", "gateway_tag_values"),
        PluginField("auto_create", "Auto create table", "bool", True),
    ),
    "mssql": (
        PluginField("server", "Server", "text", "localhost"),
        PluginField("port", "Port", "int", 1433, minimum=1, maximum=65535),
        PluginField("database", "Database", "text", "gateway"),
        PluginField("username", "Username", "text", "sa"),
        PluginField("password", "Password", "password", ""),
        PluginField("driver", "ODBC Driver", "text", "ODBC Driver 18 for SQL Server"),
        PluginField("table", "Table", "text", "gateway_tag_values"),
        PluginField("auto_create", "Auto create table", "bool", True),
        PluginField("trust_server_certificate", "Trust server certificate", "bool", True),
    ),
}


def connection_fields_for_driver(driver_type: str) -> list[ConnectionField]:
    return list(_CONNECTION_FIELDS.get(driver_type, ()))


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


def plugin_fields(plugin_type: str) -> list[PluginField]:
    return list(_PLUGIN_FIELDS.get(plugin_type, ()))


def default_plugin_config(plugin_type: str) -> dict[str, Any]:
    return {field.key: field.default for field in plugin_fields(plugin_type)}


def normalize_plugin_config(plugin_type: str, existing: dict[str, Any] | None) -> dict[str, Any]:
    values = default_plugin_config(plugin_type)
    if existing:
        for field in plugin_fields(plugin_type):
            if field.key in existing:
                values[field.key] = existing[field.key]
    return values
