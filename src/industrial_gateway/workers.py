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
    ) -> None:
        super().__init__(daemon=True)
        self.driver_factory = driver_factory
        self.device = device
        self.tags = [tag for tag in tags if tag.enabled]
        self.outbox = outbox
        self.log_queue = log_queue
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def poll_once(self) -> None:
        driver = self.driver_factory(self.device, self.tags)
        timestamp = datetime.now(timezone.utc)
        try:
            driver.connect()
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
            driver.disconnect()

    def run(self) -> None:
        while not self._stop_event.is_set():
            self.poll_once()
            self._stop_event.wait(self.device.poll_interval_ms / 1000)

    def _log(self, level: str, source: str, message: str, data: dict[str, Any]) -> None:
        if self.log_queue is not None:
            self.log_queue.put({"level": level, "source": source, "message": message, "data": data})


class SubscriptionDriver(Protocol):
    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def start_subscription(self, emit: Callable[[ReadResult], None]) -> None: ...

    def stop_subscription(self) -> None: ...


SubscriptionDriverFactory = Callable[[DeviceSpec, list[TagSpec]], SubscriptionDriver]


class OpcUaSubscriptionWorker(threading.Thread):
    def __init__(
        self,
        driver_factory: SubscriptionDriverFactory,
        device: DeviceSpec,
        tags: list[TagSpec],
        outbox: Queue[ReadResult],
        log_queue: Queue[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.driver_factory = driver_factory
        self.device = device
        self.tags = [tag for tag in tags if tag.enabled]
        self.outbox = outbox
        self.log_queue = log_queue
        self._stop_event = threading.Event()
        self.driver: SubscriptionDriver | None = None

    def start_once(self) -> None:
        self.driver = self.driver_factory(self.device, self.tags)
        self.driver.connect()
        self.driver.start_subscription(self._emit_result)
        self._log("INFO", "driver", "opcua subscription started", {"device": self.device.name})

    def stop(self) -> None:
        self._stop_event.set()
        if self.driver is not None:
            self.driver.stop_subscription()
            self.driver.disconnect()

    def run(self) -> None:
        try:
            self.start_once()
            while not self._stop_event.is_set():
                self._stop_event.wait(0.2)
        finally:
            if self.driver is not None:
                self.driver.stop_subscription()
                self.driver.disconnect()

    def _emit_result(self, result: ReadResult) -> None:
        self.outbox.put(result)
        self._log(
            "DEBUG",
            "driver",
            "opcua subscription datachange",
            {"device": result.device.name, "tags": [tag.to_payload() for tag in result.tags]},
        )

    def _log(self, level: str, source: str, message: str, data: dict[str, Any]) -> None:
        if self.log_queue is not None:
            self.log_queue.put({"level": level, "source": source, "message": message, "data": data})


class SinkPublisher(threading.Thread):
    def __init__(
        self,
        sink: Sink,
        mqtt_config: MqttConfig,
        inbox: Queue[ReadResult],
        status_outbox: Queue[str] | None = None,
        log_queue: Queue[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.sink = sink
        self.mqtt_config = mqtt_config
        self.inbox = inbox
        self.status_outbox = status_outbox
        self.log_queue = log_queue
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
        message = BatchMessage.from_results(
            result.device,
            result.tags,
            result.timestamp,
            self.mqtt_config,
        )
        try:
            self.sink.publish_batch(message)
            self._status(f"{result.device.name}: published {len(result.tags)} tags")
            self._log(
                "DEBUG",
                "sink",
                "sink publish completed",
                {"device": result.device.name, "tag_count": len(result.tags), "payload": message.payload},
            )
        except Exception as exc:
            self._status(f"{result.device.name}: publish failed: {exc}")
            self._log("ERROR", "sink", "sink publish failed", {"device": result.device.name, "error": str(exc)})
        return True

    def run(self) -> None:
        self.sink.start()
        try:
            while not self._stop_event.is_set():
                self.publish_once(timeout=0.2)
                time.sleep(0.01)
        finally:
            self.sink.stop()

    def _status(self, message: str) -> None:
        if self.status_outbox is not None:
            self.status_outbox.put(message)

    def _log(self, level: str, source: str, message: str, data: dict[str, Any]) -> None:
        if self.log_queue is not None:
            self.log_queue.put({"level": level, "source": source, "message": message, "data": data})
