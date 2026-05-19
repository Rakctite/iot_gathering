from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Any, Callable, Protocol

from industrial_gateway.models import BatchMessage, DeviceSpec, MqttConfig, ReadResult, TagResult, TagSpec


class Driver(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def read_tags(self) -> list[TagResult]: ...

    def read_server_status(self) -> Any: ...


class Sink(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def publish_batch(self, message: BatchMessage) -> None: ...


DriverFactory = Callable[[DeviceSpec, list[TagSpec]], Driver]


class DriverPoller(threading.Thread):
    def __init__(
        self,
        driver_factory: DriverFactory,
        device: DeviceSpec,
        tags: list[TagSpec],
        outbox: Queue[ReadResult],
        log_queue: Queue[dict[str, Any]] | None = None,
        status_outbox: Queue[Any] | None = None,
        health_interval_s: float = 10.0,
    ) -> None:
        super().__init__(daemon=True)
        self.driver_factory = driver_factory
        self.device = device
        self.tags = [tag for tag in tags if tag.enabled]
        self.outbox = outbox
        self.log_queue = log_queue
        self.status_outbox = status_outbox
        self.health_interval_s = health_interval_s
        self._last_health_check = 0.0
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def poll_once(self) -> None:
        driver = self.driver_factory(self.device, self.tags)
        timestamp = datetime.now(timezone.utc)
        try:
            driver.connect()
            self._check_server_status(driver)
            tag_results = driver.read_tags()
            self.outbox.put(ReadResult(self.device, timestamp, tag_results))
            self._log(
                "DEBUG",
                "driver",
                "driver read completed",
                {
                    "device": self.device.name,
                    "tags": [tag.to_payload() for tag in tag_results],
                },
            )
        except Exception as exc:
            self.outbox.put(ReadResult(self.device, timestamp, [], error=str(exc)))
            self._log("ERROR", "driver", "driver read failed", {"device": self.device.name, "error": str(exc)})
        finally:
            try:
                driver.disconnect()
            except Exception as exc:
                self._log("ERROR", "driver", "driver disconnect failed", {"device": self.device.name, "error": str(exc)})

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.device.poll_interval_ms / 1000)

    def _log(self, level: str, source: str, message: str, data: dict[str, Any]) -> None:
        if self.log_queue is not None:
            self.log_queue.put({"level": level, "source": source, "message": message, "data": data})


    def _check_server_status(self, driver: Driver) -> None:
        if self.status_outbox is None or self.device.driver_type != "opcua":
            return
        now = time.monotonic()
        if now - self._last_health_check < self.health_interval_s:
            return
        self._last_health_check = now
        try:
            reader = getattr(driver, "read_server_status", None)
            if not callable(reader):
                return
            reader()
            self.status_outbox.put(_server_status(self.device, "OK", None))
        except Exception as exc:
            self.status_outbox.put(_server_status(self.device, "ERROR", str(exc)))
            self._log(
                "ERROR",
                "driver",
                "server health check failed",
                {"device": self.device.name, "error": str(exc)},
            )


class SubscriptionDriver(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def start_subscription(self, emit: Callable[[ReadResult], None]) -> None: ...

    def stop_subscription(self) -> None: ...

    def run_subscription_once(self, timeout: float = 0.2) -> None: ...

    def read_server_status(self) -> Any: ...


SubscriptionDriverFactory = Callable[[DeviceSpec, list[TagSpec]], SubscriptionDriver]


class OpcUaSubscriptionWorker(threading.Thread):
    def __init__(
        self,
        driver_factory: SubscriptionDriverFactory,
        device: DeviceSpec,
        tags: list[TagSpec],
        outbox: Queue[ReadResult],
        log_queue: Queue[dict[str, Any]] | None = None,
        status_outbox: Queue[Any] | None = None,
        health_interval_s: float = 10.0,
    ) -> None:
        super().__init__(daemon=True)
        self.driver_factory = driver_factory
        self.device = device
        self.tags = [tag for tag in tags if tag.enabled]
        self.outbox = outbox
        self.log_queue = log_queue
        self.status_outbox = status_outbox
        self.health_interval_s = health_interval_s
        self._last_health_check = 0.0
        self._stop_event = threading.Event()
        self.driver: SubscriptionDriver | None = None

    def start_once(self) -> None:
        self.driver = self.driver_factory(self.device, self.tags)
        self.driver.connect()
        self.driver.start_subscription(self._emit_result)
        self._log("INFO", "driver", "opcua subscription started", {"device": self.device.name})

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            self.start_once()
            while not self._stop_event.is_set():
                try:
                    self.driver.run_subscription_once(0.2)
                    self._check_server_status()
                except Exception as exc:
                    self.outbox.put(ReadResult(self.device, datetime.now(timezone.utc), [], error=str(exc)))
                    self._log(
                        "ERROR",
                        "driver",
                        "opcua subscription failed",
                        {"device": self.device.name, "error": str(exc)},
                    )
                    self._stop_event.set()
        except Exception as exc:
            self.outbox.put(ReadResult(self.device, datetime.now(timezone.utc), [], error=str(exc)))
            self._log(
                "ERROR",
                "driver",
                "opcua subscription start failed",
                {"device": self.device.name, "error": str(exc)},
            )
        finally:
            if self.driver is not None:
                try:
                    self.driver.stop_subscription()
                except Exception as exc:
                    self._log(
                        "ERROR",
                        "driver",
                        "opcua subscription stop failed",
                        {"device": self.device.name, "error": str(exc)},
                    )
                try:
                    self.driver.disconnect()
                except Exception as exc:
                    self._log(
                        "ERROR",
                        "driver",
                        "opcua subscription disconnect failed",
                        {"device": self.device.name, "error": str(exc)},
                    )

    def _emit_result(self, result: ReadResult) -> None:
        self.outbox.put(result)
        self._log(
            "INFO",
            "driver",
            "opcua subscription datachange",
            {"device": result.device.name, "tags": [tag.to_payload() for tag in result.tags]},
        )

    def _log(self, level: str, source: str, message: str, data: dict[str, Any]) -> None:
        if self.log_queue is not None:
            self.log_queue.put({"level": level, "source": source, "message": message, "data": data})


    def _check_server_status(self) -> None:
        if self.status_outbox is None or self.driver is None:
            return
        now = time.monotonic()
        if now - self._last_health_check < self.health_interval_s:
            return
        self._last_health_check = now
        try:
            reader = getattr(self.driver, "read_server_status", None)
            if not callable(reader):
                return
            reader()
            self.status_outbox.put(_server_status(self.device, "OK", None))
        except Exception as exc:
            self.status_outbox.put(_server_status(self.device, "ERROR", str(exc)))
            self._log(
                "ERROR",
                "driver",
                "server health check failed",
                {"device": self.device.name, "error": str(exc)},
            )


class SinkPublisher(threading.Thread):
    def __init__(
        self,
        sink: Sink,
        mqtt_config: MqttConfig,
        inbox: Queue[ReadResult],
        status_outbox: Queue[Any] | None = None,
        log_queue: Queue[dict[str, Any]] | None = None,
        publish_interval_s: float = 1.0,
    ) -> None:
        super().__init__(daemon=True)
        self.sink = sink
        self.mqtt_config = mqtt_config
        self.inbox = inbox
        self.status_outbox = status_outbox
        self.log_queue = log_queue
        self.publish_interval_s = publish_interval_s
        self._latest: dict[tuple[str, str], dict[str, Any]] = {}
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def publish_once(self, timeout: float = 0) -> bool:
        try:
            result = self.inbox.get(timeout=timeout)
        except Empty:
            return False
        if result.error:
            self._status(f"{result.device.name}: read failed: {result.error}")
            self._log("ERROR", "driver", "read result error", {"device": result.device.name, "error": result.error})
            return True
        self._cache_result(result)
        return True

    def publish_cached(self, timestamp: datetime | None = None) -> int:
        published = 0
        for snapshot in list(self._latest.values()):
            device = snapshot["device"]
            groups: dict[str | None, list[TagResult]] = {}
            for tag in snapshot["tags"].values():
                groups.setdefault(_tag_topic_group(tag), []).append(tag)
            for group, tags in groups.items():
                if not tags:
                    continue
                message = BatchMessage.from_results(
                    device,
                    tags,
                    timestamp or datetime.now(timezone.utc),
                    self.mqtt_config,
                )
                if group:
                    message = BatchMessage(
                        topic=_topic_with_group(message.topic, group),
                        payload=message.payload,
                        qos=message.qos,
                    )
                self._publish_message(message, device, len(tags))
                published += 1
        return published

    def _cache_result(self, result: ReadResult) -> None:
        device_key = _device_key(result.device)
        snapshot = self._latest.setdefault(
            device_key,
            {
                "device": result.device,
                "tags": {},
            },
        )
        snapshot["device"] = result.device
        for tag in result.tags:
            snapshot["tags"][_tag_key(tag)] = tag
            if tag.quality == "bad" or tag.error:
                self._log(
                    "ERROR",
                    "driver",
                    "tag read failed",
                    {
                        "device": result.device.name,
                        "tag": tag.name,
                        "node_id": tag.node_id or "",
                        "quality": tag.quality,
                        "error": tag.error,
                    },
                )
            self._status(
                {
                    "type": "tag_update",
                    "device": result.device.name,
                    "tag": tag.name,
                    "node_id": tag.node_id or "",
                    "mode": _runtime_mode(result.device),
                    "timestamp": tag.timestamp.isoformat(),
                    "quality": tag.quality,
                    "error": tag.error,
                }
            )

    def _publish_message(self, message: BatchMessage, device: DeviceSpec, tag_count: int) -> None:
        try:
            self.sink.publish_batch(message)
        except Exception as exc:
            self._status(f"{device.name}: publish failed: {exc}")
            self._log("ERROR", "sink", "sink publish failed", {"device": device.name, "error": str(exc)})

    def run(self) -> None:
        try:
            self.sink.start()
        except Exception as exc:
            self._status(f"sink start failed: {exc}")
            self._log("ERROR", "sink", "sink start failed", {"error": str(exc)})
            return
        next_publish = time.monotonic() + self.publish_interval_s
        try:
            while not self._stop_event.is_set():
                timeout = max(0, min(0.2, next_publish - time.monotonic()))
                self.publish_once(timeout=timeout)
                now = time.monotonic()
                if now >= next_publish:
                    self.publish_cached(datetime.now(timezone.utc))
                    while next_publish <= now:
                        next_publish += self.publish_interval_s
        finally:
            try:
                self.sink.stop()
            except Exception as exc:
                self._log("ERROR", "sink", "sink stop failed", {"error": str(exc)})

    def _status(self, message: Any) -> None:
        if self.status_outbox is not None:
            self.status_outbox.put(message)

    def _log(self, level: str, source: str, message: str, data: dict[str, Any]) -> None:
        if self.log_queue is not None:
            self.log_queue.put({"level": level, "source": source, "message": message, "data": data})


def _device_key(device: DeviceSpec) -> tuple[str, str]:
    if device.id is not None:
        return ("id", str(device.id))
    return ("name", device.name)


def _tag_key(tag: TagResult) -> str:
    return tag.node_id or f"{tag.name}:{tag.address}"


def _tag_topic_group(tag: TagResult) -> str | None:
    if not tag.node_id:
        return None
    text = tag.node_id
    if ";s=" in text:
        text = text.split(";s=", 1)[1]
    first = text.split(".", 1)[0].strip()
    if not first.upper().startswith("PHH"):
        return None
    return first


def _topic_with_group(topic: str, group: str) -> str:
    parts = topic.strip("/").split("/")
    if len(parts) >= 2:
        return "/".join([*parts[:-1], group, parts[-1]])
    return f"{topic.strip('/')}/{group}"


def _runtime_mode(device: DeviceSpec) -> str:
    if device.driver_type == "opcua" and device.connection.get("mode") == "subscription":
        return "Subscription"
    return "Polling"


def _server_status(device: DeviceSpec, status: str, error: str | None) -> dict[str, Any]:
    return {
        "type": "server_status",
        "device": device.name,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "error": error,
    }
