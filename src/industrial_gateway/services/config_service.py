from __future__ import annotations

import csv
import io
from typing import Any

from industrial_gateway.config_schema import (
    connection_fields_for_driver,
    normalize_connection_for_driver,
    normalize_plugin_config,
    plugin_fields,
    tag_function_choices_for_driver,
    tag_type_choices_for_driver,
)
from industrial_gateway.models import DeviceSpec, OutputRouteConfig, SinkConfig, TagSpec
from industrial_gateway.store import ConfigStore


_TAG_CSV_FIELDS = [
    "tag_group",
    "name",
    "node_id",
    "address",
    "function",
    "data_type",
    "scale",
    "enabled",
    "word_count",
    "byte_order",
    "word_order",
]

_DEVICE_CSV_FIELDS = [
    "device_group",
    "device_name",
    "driver_type",
    "enabled",
    "poll_interval_ms",
    "host",
    "port",
    "unit_id",
    "max_block_gap",
    "max_registers_per_read",
    "max_bits_per_read",
    "baudrate",
    "parity",
    "stopbits",
    "bytesize",
    "timeout",
    "endpoint",
    "mode",
    "subscription_interval_ms",
    "topic_filter",
    "client_id",
    "username",
    "password",
    "qos",
    "topic_mac_index",
    "timestamp_field",
    "sensor_id_field",
    "tag_group",
    "tag_name",
    "node_id",
    "address",
    "function",
    "data_type",
    "scale",
    "tag_enabled",
    "word_count",
    "byte_order",
    "word_order",
]

_PLUGIN_CSV_FIELDS = [
    "record_type",
    "sink_type",
    "selected",
    "enabled",
    "device_group",
    "device_name",
    "tag_group",
    "topic",
    "host",
    "port",
    "base_topic",
    "username",
    "password",
    "client_id",
    "qos",
    "dynamic_topic_enabled",
    "mac_address",
    "database",
    "table",
    "auto_create",
    "server",
    "driver",
    "trust_server_certificate",
]

_PLUGIN_ROUTE_CSV_FIELDS = [
    "record_type",
    "device_group",
    "device_name",
    "tag_group",
    "sink_type",
    "enabled",
    "topic",
]


class ConfigService:
    def __init__(self, store: ConfigStore) -> None:
        self.store = store

    def list_devices(self) -> list[dict[str, Any]]:
        return [_device_to_dict(device) for device in self.store.list_devices()]

    def get_device(self, device_id: int) -> dict[str, Any]:
        for device in self.store.list_devices():
            if device.id == device_id:
                return _device_to_dict(device)
        raise KeyError(f"device not found: {device_id}")

    def create_device(self, payload: dict[str, Any]) -> dict[str, Any]:
        device = _device_from_payload(None, payload)
        device_id = self.store.save_device(device)
        return self.get_device(device_id)

    def update_device(self, device_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_device(device_id)
        self.store.save_device(_device_from_payload(device_id, payload))
        return self.get_device(device_id)

    def delete_device(self, device_id: int) -> None:
        self.get_device(device_id)
        self.store.delete_device(device_id)

    def list_tags(self, device_id: int) -> list[dict[str, Any]]:
        self.get_device(device_id)
        return [_tag_to_dict(tag) for tag in self.store.list_tags(device_id)]

    def get_tag(self, tag_id: int) -> dict[str, Any]:
        for device in self.store.list_devices():
            for tag in self.store.list_tags(device.id or 0):
                if tag.id == tag_id:
                    return _tag_to_dict(tag)
        raise KeyError(f"tag not found: {tag_id}")

    def create_tag(self, device_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_device(device_id)
        tag_id = self.store.save_tag(_tag_from_payload(None, device_id, payload))
        return self.get_tag(tag_id)

    def update_tag(self, tag_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_tag(tag_id)
        device_id = int(payload.get("device_id") or existing["device_id"])
        self.store.save_tag(_tag_from_payload(tag_id, device_id, payload))
        return self.get_tag(tag_id)

    def delete_tag(self, tag_id: int) -> None:
        self.get_tag(tag_id)
        self.store.delete_tag(tag_id)

    def list_sink_configs(self) -> list[dict[str, Any]]:
        configs = {config.sink_type: config for config in self.store.list_sink_configs()}
        selected = self.store.get_selected_sink_type()
        if selected not in configs:
            configs[selected] = self.store.get_sink_config(selected)
        return [_sink_to_dict(config, config.sink_type == selected) for config in configs.values()]

    def get_sink_config(self, sink_type: str) -> dict[str, Any]:
        selected = self.store.get_selected_sink_type()
        return _sink_to_dict(self.store.get_sink_config(sink_type), sink_type == selected)

    def get_selected_sink_config(self) -> dict[str, Any]:
        selected = self.store.get_selected_sink_type()
        return self.get_sink_config(selected)

    def save_sink_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        sink_type = str(payload["sink_type"])
        config = normalize_plugin_config(sink_type, payload.get("config") or {})
        sink_config = SinkConfig(sink_type=sink_type, enabled=bool(payload.get("enabled", True)), config=config)
        self.store.save_sink_config(sink_config)
        return self.get_sink_config(sink_type)

    def export_plugins_csv(self) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_PLUGIN_CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        selected = self.store.get_selected_sink_type()
        configs = {config.sink_type: config for config in self.store.list_sink_configs()}
        configs.setdefault(selected, self.store.get_sink_config(selected))
        for config in configs.values():
            writer.writerow(_plugin_csv_row(config, config.sink_type == selected))
        devices = {device.id: device for device in self.store.list_devices()}
        for route in self.store.list_output_routes():
            writer.writerow(_plugin_route_csv_row(route, devices.get(route.device_id)))
        return output.getvalue()

    def import_plugins_csv(self, csv_text: str) -> dict[str, int]:
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise ValueError("CSV header is required")
        imported_plugins = 0
        imported_routes = 0
        selected_config: SinkConfig | None = None
        devices_by_key = {_device_import_key(device): device for device in self.store.list_devices()}
        existing_routes = self.store.list_output_routes()
        for row in reader:
            record_type = (row.get("record_type") or "plugin").strip().lower()
            if record_type == "route":
                route_id = self._import_plugin_route_row(row, devices_by_key, existing_routes)
                existing_routes = [
                    *[item for item in existing_routes if item.id != route_id],
                    *_route_by_id(self.store.list_output_routes(), route_id),
                ]
                imported_routes += 1
                continue
            sink_type = (row.get("sink_type") or "mqtt").strip()
            config = SinkConfig(
                sink_type=sink_type,
                enabled=_csv_bool(row.get("enabled"), True),
                config=_csv_plugin_config(sink_type, row),
            )
            self.store.save_sink_config(config)
            if _csv_bool(row.get("selected"), False):
                selected_config = config
            imported_plugins += 1
        if selected_config is not None:
            self.store.save_sink_config(selected_config)
        return {"plugins": imported_plugins, "routes": imported_routes}

    def list_output_routes(self) -> list[dict[str, Any]]:
        devices = {device.id: device for device in self.store.list_devices()}
        rows = []
        for route in self.store.list_output_routes():
            payload = _route_to_dict(route)
            device = devices.get(route.device_id)
            payload["device_name"] = device.name if device is not None else "All devices"
            rows.append(payload)
        return rows

    def save_output_route(self, payload: dict[str, Any]) -> dict[str, Any]:
        route_id = payload.get("id")
        sink_type = "mqtt"
        device_id_value = payload.get("device_id")
        device_id = None if device_id_value in (None, "", "all") else int(device_id_value)
        if device_id is not None:
            self.get_device(device_id)
        route = OutputRouteConfig(
            id=None if route_id in (None, "") else int(route_id),
            device_id=device_id,
            tag_group=str(payload.get("tag_group", "")).strip(),
            sink_type=sink_type,
            enabled=bool(payload.get("enabled", True)),
            config=_route_config(payload),
        )
        saved_id = self.store.save_output_route(route)
        return next(route for route in self.list_output_routes() if route["id"] == saved_id)

    def delete_output_route(self, route_id: int) -> None:
        self.store.delete_output_route(route_id)

    def export_plugin_routes_csv(self) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_PLUGIN_ROUTE_CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        devices = {device.id: device for device in self.store.list_devices()}
        for route in self.store.list_output_routes():
            writer.writerow(_plugin_route_csv_row(route, devices.get(route.device_id)))
        return output.getvalue()

    def import_plugin_routes_csv(self, csv_text: str) -> dict[str, int]:
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise ValueError("CSV header is required")
        imported = 0
        devices_by_key = {_device_import_key(device): device for device in self.store.list_devices()}
        existing_routes = self.store.list_output_routes()
        for row in reader:
            route_id = self._import_plugin_route_row(row, devices_by_key, existing_routes)
            existing_routes = [
                *[item for item in existing_routes if item.id != route_id],
                *_route_by_id(self.store.list_output_routes(), route_id),
            ]
            imported += 1
        return {"routes": imported}

    def _import_plugin_route_row(
        self,
        row: dict[str, Any],
        devices_by_key: dict[tuple[str, str], DeviceSpec],
        existing_routes: list[OutputRouteConfig],
    ) -> int:
        sink_type = (row.get("sink_type") or "mqtt").strip()
        device_id = _csv_route_device_id(row, devices_by_key)
        route = OutputRouteConfig(
            id=_existing_route_id(existing_routes, device_id, (row.get("tag_group") or "").strip(), sink_type),
            device_id=device_id,
            tag_group=(row.get("tag_group") or "").strip(),
            sink_type=sink_type,
            enabled=_csv_bool(row.get("enabled"), True),
            config=_route_config({"topic": row.get("topic") or ""}),
        )
        return self.store.save_output_route(route)

    def export_devices_csv(self) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_DEVICE_CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for device in self.store.list_devices():
            tags = self.store.list_tags(device.id or 0)
            if not tags:
                writer.writerow(_device_csv_row(device, None))
                continue
            for tag in tags:
                writer.writerow(_device_csv_row(device, tag))
        return output.getvalue()

    def import_devices_csv(self, csv_text: str) -> dict[str, int]:
        devices_by_key = {_device_import_key(device): device for device in self.store.list_devices()}
        imported_devices = 0
        imported_tags = 0
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise ValueError("CSV header is required")
        for row in reader:
            driver_type = (row.get("driver_type") or "modbus_tcp").strip()
            device_name = (row.get("device_name") or row.get("name") or "").strip()
            device = DeviceSpec(
                id=None,
                device_group=(row.get("device_group") or "").strip(),
                name=device_name,
                driver_type=driver_type,
                enabled=_csv_bool(row.get("enabled"), True),
                poll_interval_ms=int(row.get("poll_interval_ms") or 1000),
                connection=_csv_connection(driver_type, row),
            )
            key = _device_import_key(device)
            existing = devices_by_key.get(key)
            if existing is None:
                device_id = self.store.save_device(device)
                existing = DeviceSpec(
                    id=device_id,
                    device_group=device.device_group,
                    name=device.name,
                    driver_type=device.driver_type,
                    enabled=device.enabled,
                    poll_interval_ms=device.poll_interval_ms,
                    connection=device.connection,
                )
                devices_by_key[key] = existing
                imported_devices += 1
            else:
                _validate_same_device_config(existing, device)
            tag_name = (row.get("tag_name") or "").strip()
            if not tag_name:
                continue
            self._upsert_tag(existing.id or 0, _tag_from_csv_row(row, existing.driver_type, tag_name_key="tag_name"))
            imported_tags += 1
        return {"devices": imported_devices, "tags": imported_tags}

    def export_tags_csv(self, device_id: int) -> str:
        self.get_device(device_id)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=_TAG_CSV_FIELDS, lineterminator="\n")
        writer.writeheader()
        for tag in self.store.list_tags(device_id):
            writer.writerow(_tag_csv_row(tag))
        return output.getvalue()

    def import_tags_csv(self, device_id: int, csv_text: str) -> dict[str, int]:
        device = self.get_device(device_id)
        reader = csv.DictReader(io.StringIO(csv_text))
        if reader.fieldnames is None:
            raise ValueError("CSV header is required")
        imported = 0
        for row in reader:
            self._upsert_tag(device_id, _tag_from_csv_row(row, str(device["driver_type"]), tag_name_key="name"))
            imported += 1
        return {"tags": imported}

    def _upsert_tag(self, device_id: int, tag: TagSpec) -> int:
        existing_id = _existing_tag_id(self.store.list_tags(device_id), tag)
        saved = TagSpec(
            id=existing_id,
            device_id=device_id,
            tag_group=tag.tag_group,
            name=tag.name,
            address=tag.address,
            function=tag.function,
            data_type=tag.data_type,
            scale=tag.scale,
            enabled=tag.enabled,
            word_count=tag.word_count,
            byte_order=tag.byte_order,
            word_order=tag.word_order,
            node_id=tag.node_id,
        )
        return self.store.save_tag(saved)


def _device_from_payload(device_id: int | None, payload: dict[str, Any]) -> DeviceSpec:
    driver_type = str(payload["driver_type"])
    return DeviceSpec(
        id=device_id,
        device_group=str(payload.get("device_group", "")),
        name=str(payload["name"]),
        driver_type=driver_type,
        enabled=bool(payload.get("enabled", True)),
        poll_interval_ms=int(payload.get("poll_interval_ms", 1000)),
        connection=normalize_connection_for_driver(driver_type, payload.get("connection") or {}),
    )


def _tag_from_payload(tag_id: int | None, device_id: int, payload: dict[str, Any]) -> TagSpec:
    word_count_value = payload.get("word_count")
    word_count = None if word_count_value in (None, "") else int(word_count_value)
    return TagSpec(
        id=tag_id,
        device_id=device_id,
        tag_group=str(payload.get("tag_group", "")),
        name=str(payload["name"]),
        address=int(payload.get("address", 0)),
        function=payload["function"],
        data_type=payload["data_type"],
        scale=float(payload.get("scale", 1.0)),
        enabled=bool(payload.get("enabled", True)),
        word_count=word_count,
        byte_order=str(payload.get("byte_order", "big")),
        word_order=str(payload.get("word_order", "big")),
        node_id=payload.get("node_id") or None,
    )


def _device_to_dict(device: DeviceSpec) -> dict[str, Any]:
    return {
        "id": device.id,
        "device_group": device.device_group,
        "name": device.name,
        "driver_type": device.driver_type,
        "enabled": device.enabled,
        "poll_interval_ms": device.poll_interval_ms,
        "connection": device.connection,
    }


def _tag_to_dict(tag: TagSpec) -> dict[str, Any]:
    return {
        "id": tag.id,
        "device_id": tag.device_id,
        "tag_group": tag.tag_group,
        "name": tag.name,
        "address": tag.address,
        "function": tag.function,
        "data_type": tag.data_type,
        "scale": tag.scale,
        "enabled": tag.enabled,
        "word_count": tag.word_count,
        "byte_order": tag.byte_order,
        "word_order": tag.word_order,
        "node_id": tag.node_id,
    }


def _sink_to_dict(config: SinkConfig, selected: bool) -> dict[str, Any]:
    return {
        "sink_type": config.sink_type,
        "enabled": config.enabled,
        "config": config.config,
        "selected": selected,
    }


def _route_to_dict(route: OutputRouteConfig) -> dict[str, Any]:
    return {
        "id": route.id,
        "device_id": route.device_id,
        "tag_group": route.tag_group,
        "sink_type": route.sink_type,
        "enabled": route.enabled,
        "config": _route_config({"config": route.config}),
    }


def _route_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload.get("config") or {}
    topic = str(config.get("topic") or payload.get("topic") or "").strip()
    return {"topic": topic} if topic else {}


def _csv_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _csv_optional_int(value: Any) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def _csv_connection(driver_type: str, row: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for field in connection_fields_for_driver(driver_type):
        value = row.get(field.key)
        if value is not None and str(value).strip() != "":
            values[field.key] = _csv_connection_value(field.kind, value)
    return normalize_connection_for_driver(driver_type, values)


def _csv_connection_value(kind: str, value: Any) -> Any:
    if kind == "int":
        return int(value)
    if kind == "float":
        return float(value)
    return str(value)


def _csv_plugin_config(sink_type: str, row: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for field in plugin_fields(sink_type):
        value = row.get(field.key)
        if value is not None and str(value).strip() != "":
            values[field.key] = _csv_plugin_value(field.kind, value)
    return normalize_plugin_config(sink_type, values)


def _csv_plugin_value(kind: str, value: Any) -> Any:
    if kind == "int":
        return int(value)
    if kind == "bool":
        return _csv_bool(value, False)
    return str(value)


def _tag_from_csv_row(row: dict[str, Any], driver_type: str, tag_name_key: str) -> TagSpec:
    name = (row.get(tag_name_key) or "").strip()
    if not name:
        raise ValueError("tag name is required")
    return TagSpec(
        name=name,
        device_id=None,
        tag_group=(row.get("tag_group") or "").strip(),
        node_id=(row.get("node_id") or "").strip() or None,
        address=int(row.get("address") or 0),
        function=(row.get("function") or tag_function_choices_for_driver(driver_type)[0]).strip(),
        data_type=(row.get("data_type") or tag_type_choices_for_driver(driver_type)[0]).strip(),
        scale=float(row.get("scale") or 1.0),
        enabled=_csv_bool(row.get("tag_enabled" if tag_name_key == "tag_name" else "enabled"), True),
        word_count=_csv_optional_int(row.get("word_count")),
        byte_order=(row.get("byte_order") or "big").strip(),
        word_order=(row.get("word_order") or "big").strip(),
    )


def _device_import_key(device: DeviceSpec) -> tuple[str, str]:
    return (device.device_group, device.name)


def _csv_route_device_id(row: dict[str, Any], devices_by_key: dict[tuple[str, str], DeviceSpec]) -> int | None:
    device_name = (row.get("device_name") or "").strip()
    if not device_name:
        return None
    device_group = (row.get("device_group") or "").strip()
    device = devices_by_key.get((device_group, device_name))
    if device is None:
        group = device_group or "default"
        raise ValueError(f"route device '{device_name}' in group '{group}' does not exist")
    return device.id


def _existing_route_id(
    routes: list[OutputRouteConfig],
    device_id: int | None,
    tag_group: str,
    sink_type: str,
) -> int | None:
    for route in routes:
        if route.device_id == device_id and route.tag_group == tag_group and route.sink_type == sink_type:
            return route.id
    return None


def _route_by_id(routes: list[OutputRouteConfig], route_id: int) -> list[OutputRouteConfig]:
    return [route for route in routes if route.id == route_id]


def _validate_same_device_config(existing: DeviceSpec, imported: DeviceSpec) -> None:
    if (
        existing.driver_type != imported.driver_type
        or existing.enabled != imported.enabled
        or existing.poll_interval_ms != imported.poll_interval_ms
        or existing.connection != imported.connection
    ):
        group = imported.device_group or "default"
        raise ValueError(
            f"device '{imported.name}' in group '{group}' already exists with different connection/settings"
        )


def _device_csv_row(device: DeviceSpec, tag: TagSpec | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "device_group": device.device_group,
        "device_name": device.name,
        "driver_type": device.driver_type,
        "enabled": int(device.enabled),
        "poll_interval_ms": device.poll_interval_ms,
    }
    for key in _DEVICE_CSV_FIELDS:
        if key not in row and key in device.connection:
            row[key] = device.connection[key]
    if tag is not None:
        row.update(
            {
                "tag_group": tag.tag_group,
                "tag_name": tag.name,
                "node_id": tag.node_id or "",
                "address": tag.address,
                "function": tag.function,
                "data_type": tag.data_type,
                "scale": tag.scale,
                "tag_enabled": int(tag.enabled),
                "word_count": tag.word_count or "",
                "byte_order": tag.byte_order,
                "word_order": tag.word_order,
            }
        )
    return row


def _tag_csv_row(tag: TagSpec) -> dict[str, Any]:
    return {
        "tag_group": tag.tag_group,
        "name": tag.name,
        "node_id": tag.node_id or "",
        "address": tag.address,
        "function": tag.function,
        "data_type": tag.data_type,
        "scale": tag.scale,
        "enabled": int(tag.enabled),
        "word_count": tag.word_count or "",
        "byte_order": tag.byte_order,
        "word_order": tag.word_order,
    }


def _plugin_csv_row(config: SinkConfig, selected: bool) -> dict[str, Any]:
    row: dict[str, Any] = {
        "record_type": "plugin",
        "sink_type": config.sink_type,
        "selected": int(selected),
        "enabled": int(config.enabled),
    }
    for key in _PLUGIN_CSV_FIELDS:
        if key not in row and key in config.config:
            row[key] = config.config[key]
    return row


def _plugin_route_csv_row(route: OutputRouteConfig, device: DeviceSpec | None) -> dict[str, Any]:
    return {
        "record_type": "route",
        "device_group": "" if device is None else device.device_group,
        "device_name": "" if device is None else device.name,
        "tag_group": route.tag_group,
        "sink_type": route.sink_type,
        "enabled": int(route.enabled),
        "topic": route.config.get("topic", ""),
    }


def _existing_tag_id(tags: list[TagSpec], imported: TagSpec) -> int | None:
    for tag in tags:
        if tag.tag_group == imported.tag_group and tag.name == imported.name:
            return tag.id
    return None
