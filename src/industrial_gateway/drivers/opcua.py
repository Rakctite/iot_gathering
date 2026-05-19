from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from industrial_gateway.models import DeviceSpec, TagResult, TagSpec


class OpcUaDriver:
    def __init__(self, device: DeviceSpec, tags: list[TagSpec]) -> None:
        self.device = device
        self.tags = tags
        self.client: Any | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscription: Any | None = None

    def connect(self) -> None:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        if self.client is None:
            try:
                from asyncua import Client
            except ImportError as exc:
                raise RuntimeError("asyncua is required for OPC UA") from exc
            endpoint = self.device.connection.get("endpoint") or self.device.connection.get("url")
            if not endpoint:
                raise RuntimeError("OPC UA endpoint is required in connection JSON")
            self.client = Client(url=endpoint)
        self._run(self.client.connect())

    def disconnect(self) -> None:
        if self.client is not None and self._loop is not None:
            self._run(self.client.disconnect())
        if self._loop is not None:
            self._loop.close()
            self._loop = None

    def read_tags(self) -> list[TagResult]:
        if self.client is None:
            timestamp = datetime.now(timezone.utc)
            return [_bad(tag, timestamp, "OPC UA client is not connected") for tag in self.tags]
        return [self._read_tag(tag) for tag in self.tags]

    def read_server_status(self) -> Any:
        if self.client is None:
            raise RuntimeError("OPC UA client is not connected")
        node = self.client.get_node("ns=0;i=2259")
        return self._run(node.read_value())

    def start_subscription(self, emit: Callable[[Any], None]) -> None:
        if self.client is None:
            raise RuntimeError("OPC UA client is not connected")
        interval = int(self.device.connection.get("subscription_interval_ms", self.device.poll_interval_ms))
        self._run(self._start_subscription(interval, emit))

    def stop_subscription(self) -> None:
        if self._subscription is not None:
            self._run(self._subscription.delete())
            self._subscription = None

    def run_subscription_once(self, timeout: float = 0.2) -> None:
        if self._subscription is None:
            return
        self._run(asyncio.sleep(timeout))

    def _read_tag(self, tag: TagSpec) -> TagResult:
        timestamp = datetime.now(timezone.utc)
        if not tag.node_id:
            return _bad(tag, timestamp, "OPC UA node_id is required")
        try:
            node = self.client.get_node(tag.node_id)
            value = self._run(node.read_value())
            value = _coerce_value(value, tag)
            return TagResult(tag.name, tag.address, value, "good", None, timestamp, node_id=tag.node_id)
        except Exception as exc:
            return _bad(tag, timestamp, str(exc))

    def _run(self, coro: Any) -> Any:
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop.run_until_complete(coro)

    async def _start_subscription(self, interval: int, emit: Callable[[Any], None]) -> None:
        node_map = {tag.node_id: tag for tag in self.tags if tag.node_id}
        handler = _OpcUaDataChangeHandler(self.device, node_map, emit)
        self._subscription = await self.client.create_subscription(interval, handler)
        nodes = [self.client.get_node(tag.node_id) for tag in self.tags if tag.node_id]
        await self._subscription.subscribe_data_change(nodes)


class _OpcUaDataChangeHandler:
    def __init__(
        self,
        device: DeviceSpec,
        node_map: dict[str, TagSpec],
        emit: Callable[[Any], None],
    ) -> None:
        self.device = device
        self.node_map = node_map
        self.emit = emit

    def datachange_notification(self, node: Any, value: Any, data: Any) -> None:
        timestamp = datetime.now(timezone.utc)
        node_id = _node_id_text(node)
        tag = self.node_map.get(node_id)
        if tag is None:
            return
        try:
            coerced = _coerce_value(value, tag)
            tag_result = TagResult(tag.name, tag.address, coerced, "good", None, timestamp, node_id=tag.node_id)
        except Exception as exc:
            tag_result = _bad(tag, timestamp, str(exc))
        from industrial_gateway.models import ReadResult

        self.emit(ReadResult(self.device, timestamp, [tag_result]))


def _node_id_text(node: Any) -> str:
    node_id = getattr(node, "nodeid", node)
    to_string = getattr(node_id, "to_string", None)
    if callable(to_string):
        return to_string()
    return str(node_id)


def _coerce_value(value: Any, tag: TagSpec) -> Any:
    if tag.data_type == "auto":
        return value
    if tag.data_type == "string":
        return str(value)
    if tag.data_type == "bool":
        return bool(value)
    if tag.data_type in {"int16", "uint16", "int32", "uint32"}:
        return int(value) * tag.scale
    if tag.data_type in {"float32", "float64"}:
        return float(value) * tag.scale
    return value


def _bad(tag: TagSpec, timestamp: datetime, error: str) -> TagResult:
    return TagResult(tag.name, tag.address, None, "bad", error, timestamp, node_id=tag.node_id)
