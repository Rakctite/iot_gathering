from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

FieldKind = Literal["text", "int", "bool", "password"]


@dataclass(frozen=True)
class PluginField:
    key: str
    label: str
    kind: FieldKind
    default: Any
    minimum: int | None = None
    maximum: int | None = None


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
