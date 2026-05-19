from __future__ import annotations

from typing import Any

from industrial_gateway.gui.connection_forms import normalize_connection_for_driver
from industrial_gateway.gui.plugin_forms import normalize_plugin_config
from industrial_gateway.models import DeviceSpec, SinkConfig, TagSpec
from industrial_gateway.store import ConfigStore


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
