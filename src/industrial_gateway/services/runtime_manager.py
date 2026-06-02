from __future__ import annotations

import threading
from collections import deque
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from industrial_gateway.defaults import driver_registry as default_driver_registry
from industrial_gateway.defaults import sink_registry as default_sink_registry
from industrial_gateway.logging_worker import AsyncLogWorker
from industrial_gateway.models import MqttConfig
from industrial_gateway.store import ConfigStore
from industrial_gateway.workers import DriverPoller, OpcUaSubscriptionWorker, OutputRoute, SinkPublisher


class RuntimeManager:
    def __init__(
        self,
        store: ConfigStore,
        *,
        driver_registry: Any | None = None,
        sink_registry: Any | None = None,
        poller_class: type = DriverPoller,
        subscription_worker_class: type = OpcUaSubscriptionWorker,
        publisher_class: type = SinkPublisher,
        log_root: str | Path | None = None,
    ) -> None:
        self.store = store
        self.driver_registry = default_driver_registry if driver_registry is None else driver_registry
        self.sink_registry = default_sink_registry if sink_registry is None else sink_registry
        self.poller_class = poller_class
        self.subscription_worker_class = subscription_worker_class
        self.publisher_class = publisher_class
        self.result_queue: Queue[Any] = Queue()
        self.status_queue: Queue[Any] = Queue()
        self.log_display_queue: Queue[str] = Queue()
        self.pollers: list[Any] = []
        self.subscription_workers: list[Any] = []
        self.publisher: Any | None = None
        self.running = False
        self.health_interval_s = 10
        self.runtime_log_enabled = True
        self.runtime_tags: dict[tuple[str, str], dict[str, Any]] = {}
        self.server_statuses: dict[str, dict[str, Any]] = {}
        self.logs: deque[str] = deque(maxlen=500)
        self._lock = threading.Lock()
        log_base = Path(log_root) if log_root is not None else self.store.path.parent / "industrial_gateway_log"
        self.logger = AsyncLogWorker(
            self.log_display_queue,
            debug_enabled=False,
            log_dir=log_base / "runtime",
            error_log_dir=log_base / "error",
            audit_log_dir=log_base / "audit",
        )
        self.logger.start()

    def start(
        self,
        health_interval_s: int | None = None,
        runtime_log_enabled: bool | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self.running:
                return self.snapshot()
            if health_interval_s is not None:
                self.health_interval_s = health_interval_s
            if runtime_log_enabled is not None:
                self.runtime_log_enabled = runtime_log_enabled
            self.logger.set_runtime_log_enabled(self.runtime_log_enabled)
            self._clear_queue(self.result_queue)
            self._clear_queue(self.status_queue)
            self.runtime_tags = self._initial_runtime_tags()
            self.server_statuses = {}

            sink_config = self.store.get_sink_config()
            sink_class = self.sink_registry.get(sink_config.sink_type)
            sink = sink_class({**sink_config.config, "enabled": sink_config.enabled})
            message_config = MqttConfig(
                base_topic=sink_config.config.get("base_topic", "industrial"),
                qos=int(sink_config.config.get("qos", 0)),
            )
            output_routes = self._output_routes()
            self.publisher = self.publisher_class(
                sink,
                message_config,
                self.result_queue,
                self.status_queue,
                log_queue=self.logger.input_queue,
                plugin_type=sink_config.sink_type,
                output_routes=output_routes,
            )
            self.publisher.start()

            self.pollers = []
            self.subscription_workers = []
            for device in self.store.list_devices():
                if not device.enabled:
                    continue
                driver_class = self.driver_registry.get(device.driver_type)
                tags = self.store.list_tags(device.id or 0)
                if _uses_subscription_worker(device):
                    worker = self.subscription_worker_class(
                        driver_class,
                        device,
                        tags,
                        self.result_queue,
                        log_queue=self.logger.input_queue,
                        status_outbox=self.status_queue,
                        health_interval_s=self.health_interval_s,
                    )
                    worker.start()
                    self.subscription_workers.append(worker)
                else:
                    poller = self.poller_class(
                        driver_class,
                        device,
                        tags,
                        self.result_queue,
                        log_queue=self.logger.input_queue,
                        status_outbox=self.status_queue,
                        health_interval_s=self.health_interval_s,
                    )
                    poller.start()
                    self.pollers.append(poller)
            self.running = True
            return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            if not self.running:
                return self.snapshot()
            for poller in self.pollers:
                poller.stop()
            for worker in self.subscription_workers:
                worker.stop()
            if self.publisher is not None:
                self.publisher.stop()
            self.running = False
            return self.snapshot()

    def set_health_interval(self, seconds: int) -> dict[str, Any]:
        self.health_interval_s = seconds
        for poller in self.pollers:
            poller.health_interval_s = seconds
        for worker in self.subscription_workers:
            worker.health_interval_s = seconds
        return self.snapshot()

    def drain_events(self, limit: int = 1000) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for _ in range(limit):
            try:
                item = self.status_queue.get_nowait()
            except Empty:
                break
            event = self._record_status(item)
            events.append(event)
        while self.logger.drain_once(timeout=0):
            pass
        while not self.log_display_queue.empty():
            line = self.log_display_queue.get()
            self.logs.append(line)
            events.append({"type": "log", "message": line})
        return events

    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "device_count": len(self.pollers) + len(self.subscription_workers),
            "health_interval_s": self.health_interval_s,
            "runtime_log_enabled": self.runtime_log_enabled,
            "runtime_tags": list(self.runtime_tags.values()),
            "server_statuses": list(self.server_statuses.values()),
            "logs": list(self.logs),
        }

    def shutdown(self) -> None:
        self.stop()
        self.logger.stop()

    def _record_status(self, item: Any) -> dict[str, Any]:
        if isinstance(item, dict) and item.get("type") == "tag_update":
            key = (str(item.get("device", "")), str(item.get("node_id") or item.get("tag", "")))
            existing = self.runtime_tags.get(key, {})
            merged = {**existing, **item}
            self.runtime_tags[key] = merged
            return merged
        if isinstance(item, dict) and item.get("type") == "server_status":
            self.server_statuses[str(item.get("device", ""))] = item
            return item
        return {"type": "status", "message": str(item)}

    def _initial_runtime_tags(self) -> dict[tuple[str, str], dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for device in self.store.list_devices():
            if not device.enabled:
                continue
            mode = (
                "Subscription"
                if _uses_subscription_worker(device)
                else "Polling"
            )
            for tag in self.store.list_tags(device.id or 0):
                if not tag.enabled:
                    continue
                key = (device.name, tag.node_id or tag.name)
                rows[key] = {
                    "type": "tag_update",
                    "device": device.name,
                    "tag_group": tag.tag_group,
                    "tag": tag.name,
                    "node_id": tag.node_id or "",
                    "mode": mode,
                    "timestamp": "",
                    "quality": "unknown",
                    "error": None,
                }
        return rows

    def _clear_queue(self, queue: Queue[Any]) -> None:
        while True:
            try:
                queue.get_nowait()
            except Empty:
                return

    def _output_routes(self) -> list[OutputRoute]:
        selected_sink = self.store.get_sink_config()
        if selected_sink.sink_type != "mqtt":
            return []
        routes = []
        for route in self.store.list_output_routes():
            if not route.enabled or route.sink_type != "mqtt":
                continue
            config = {**selected_sink.config, "enabled": route.enabled}
            base_topic = str(config.get("base_topic") or "industrial").strip("/")
            mqtt_config = MqttConfig(
                base_topic=base_topic,
                qos=int(config.get("qos", 0)),
            )
            routes.append(
                OutputRoute(
                    device_id=route.device_id,
                    tag_group=route.tag_group,
                    sink_type=route.sink_type,
                    mqtt_config=mqtt_config,
                    topic=_route_topic(base_topic, route.config.get("topic")),
                )
            )
        return routes


def _uses_subscription_worker(device: Any) -> bool:
    return device.driver_type == "mqtt" or (
        device.driver_type == "opcua" and device.connection.get("mode") == "subscription"
    )


def _route_topic(base_topic: str, route_topic: Any) -> str:
    topic = str(route_topic or "").strip("/")
    if not topic:
        return ""
    base = base_topic.strip("/")
    if not base or topic == base or topic.startswith(f"{base}/"):
        return topic
    return f"{base}/{topic}"
