# Web UI Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LAN-accessible authenticated web UI and daemon service for Industrial Gateway on `0.0.0.0:50137`.

**Architecture:** Add a FastAPI service process that serves REST APIs, a WebSocket runtime event stream, and static web assets. Extract non-Qt configuration and runtime logic into service modules so the existing PySide6 app can remain while the web service reaches parity.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, itsdangerous signed sessions, SQLite via existing `ConfigStore`, vanilla HTML/CSS/JavaScript for the first web UI, pytest, FastAPI `TestClient`.

---

## File Structure

- Create `src/industrial_gateway/services/__init__.py`: service package marker.
- Create `src/industrial_gateway/services/config_service.py`: UI-independent CRUD and normalization boundary over `ConfigStore`.
- Create `src/industrial_gateway/services/runtime_manager.py`: background runtime ownership, status snapshots, event fan-out.
- Create `src/industrial_gateway/web/__init__.py`: web package marker.
- Create `src/industrial_gateway/web/auth.py`: signed-cookie auth helpers and login dependency.
- Create `src/industrial_gateway/web/api.py`: FastAPI app factory, REST routes, WebSocket route, static UI mount.
- Create `src/industrial_gateway/web/app.py`: CLI entry point for `industrial-gateway-web`.
- Create `src/industrial_gateway/web/static/index.html`: single-page operations console.
- Create `src/industrial_gateway/web/static/styles.css`: restrained operations UI styling.
- Create `src/industrial_gateway/web/static/app.js`: browser API client and live runtime UI.
- Modify `pyproject.toml`: add web dependencies and console script.
- Test `tests/test_config_service.py`: service CRUD and normalization.
- Test `tests/test_runtime_manager.py`: runtime start/stop/status/event behavior with fake workers/sinks.
- Test `tests/test_web_auth.py`: login/session/protected endpoint behavior.
- Test `tests/test_web_api.py`: devices/tags/plugins/runtime API behavior.
- Test `tests/test_web_static.py`: static UI route serves the app after login.

---

### Task 1: Packaging and Web App Skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `src/industrial_gateway/web/__init__.py`
- Create: `src/industrial_gateway/web/api.py`
- Create: `src/industrial_gateway/web/app.py`
- Test: `tests/test_web_app_import.py`

- [ ] **Step 1: Write the failing import and app factory test**

Create `tests/test_web_app_import.py`:

```python
from industrial_gateway.web.api import create_app


def test_create_app_returns_fastapi_app(tmp_path):
    app = create_app(store_path=tmp_path / "gateway.sqlite3", session_secret="secret")

    assert app.title == "Industrial Gateway"
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_app_import.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'industrial_gateway.web'`.

- [ ] **Step 3: Add dependencies and the console script**

Modify `pyproject.toml` dependencies and scripts:

```toml
dependencies = [
    "PySide6>=6.7",
    "pymodbus>=3.7",
    "pyserial>=3.5",
    "asyncua>=1.1",
    "paho-mqtt>=2.1",
    "psycopg[binary]>=3.2",
    "pyodbc>=5.1",
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "itsdangerous>=2.2",
]

[project.scripts]
industrial-gateway = "industrial_gateway.app:main"
industrial-gateway-web = "industrial_gateway.web.app:main"
```

- [ ] **Step 4: Add the minimal web app package**

Create `src/industrial_gateway/web/__init__.py`:

```python
"""Web service for Industrial Gateway."""
```

Create `src/industrial_gateway/web/api.py`:

```python
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from industrial_gateway.store import ConfigStore


def create_app(store_path: str | Path, session_secret: str) -> FastAPI:
    store = ConfigStore(store_path)
    store.initialize()
    app = FastAPI(title="Industrial Gateway")
    app.state.store = store
    app.state.session_secret = session_secret

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

Create `src/industrial_gateway/web/app.py`:

```python
from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from industrial_gateway.web.api import create_app


def _default_store_path() -> Path:
    return Path.home() / ".industrial_gateway" / "gateway.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Industrial Gateway web service")
    parser.add_argument("--host", default=os.getenv("INDUSTRIAL_GATEWAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("INDUSTRIAL_GATEWAY_PORT", "50137")))
    parser.add_argument("--store", default=os.getenv("INDUSTRIAL_GATEWAY_STORE", str(_default_store_path())))
    parser.add_argument("--session-secret", default=os.getenv("INDUSTRIAL_GATEWAY_SESSION_SECRET", "dev-session-secret"))
    args = parser.parse_args()

    app = create_app(Path(args.store), args.session_secret)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the focused test to verify it passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_app_import.py -q
```

Expected: `1 passed`.

- [ ] **Step 6: Install editable package and check console script metadata**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\industrial-gateway-web.exe --help
```

Expected: help output includes `Run the Industrial Gateway web service`.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml src\industrial_gateway\web tests\test_web_app_import.py
git commit -m "feat: add web service skeleton"
```

---

### Task 2: Config Service

**Files:**
- Create: `src/industrial_gateway/services/__init__.py`
- Create: `src/industrial_gateway/services/config_service.py`
- Test: `tests/test_config_service.py`

- [ ] **Step 1: Write failing config service tests**

Create `tests/test_config_service.py`:

```python
import pytest

from industrial_gateway.models import SinkConfig
from industrial_gateway.services.config_service import ConfigService
from industrial_gateway.store import ConfigStore


def make_service(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    return ConfigService(store)


def test_device_crud_round_trip(tmp_path):
    service = make_service(tmp_path)

    device = service.create_device(
        {
            "device_group": "line1",
            "name": "plc-1",
            "driver_type": "modbus_tcp",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"host": "127.0.0.1", "port": 502, "unit_id": 1},
        }
    )

    assert device["id"] is not None
    assert service.list_devices()[0]["name"] == "plc-1"

    updated = service.update_device(device["id"], {**device, "name": "plc-main"})
    assert updated["name"] == "plc-main"

    service.delete_device(device["id"])
    assert service.list_devices() == []


def test_tag_crud_round_trip(tmp_path):
    service = make_service(tmp_path)
    device = service.create_device(
        {
            "name": "plc-1",
            "driver_type": "modbus_tcp",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"host": "127.0.0.1", "port": 502, "unit_id": 1},
        }
    )

    tag = service.create_tag(
        device["id"],
        {
            "name": "temperature",
            "address": 100,
            "function": "holding_register",
            "data_type": "float32",
            "scale": 1.0,
            "enabled": True,
        },
    )

    assert service.list_tags(device["id"])[0]["name"] == "temperature"

    updated = service.update_tag(tag["id"], {**tag, "scale": 10.0})
    assert updated["scale"] == 10.0

    service.delete_tag(tag["id"])
    assert service.list_tags(device["id"]) == []


def test_plugin_save_selects_sink(tmp_path):
    service = make_service(tmp_path)

    saved = service.save_sink_config(
        {
            "sink_type": "mqtt",
            "enabled": True,
            "config": {"host": "broker", "port": 1883, "base_topic": "plant", "client_id": "gw", "qos": 1},
        }
    )

    assert saved["sink_type"] == "mqtt"
    assert service.get_selected_sink_config()["config"]["host"] == "broker"


def test_missing_device_raises_key_error(tmp_path):
    service = make_service(tmp_path)

    with pytest.raises(KeyError, match="device not found"):
        service.get_device(999)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config_service.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'industrial_gateway.services'`.

- [ ] **Step 3: Add the service package and implementation**

Create `src/industrial_gateway/services/__init__.py`:

```python
"""Application services for non-UI gateway behavior."""
```

Create `src/industrial_gateway/services/config_service.py`:

```python
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
        configs = {_config.sink_type: _config for _config in self.store.list_sink_configs()}
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
```

- [ ] **Step 4: Run tests to verify service passes**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config_service.py -q
```

Expected: `4 passed`.

- [ ] **Step 5: Run existing store and form tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_store.py tests\test_sink_config.py tests\test_connection_forms.py tests\test_plugin_forms.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src\industrial_gateway\services tests\test_config_service.py
git commit -m "feat: add config service"
```

---

### Task 3: Runtime Manager

**Files:**
- Create: `src/industrial_gateway/services/runtime_manager.py`
- Test: `tests/test_runtime_manager.py`

- [ ] **Step 1: Write failing runtime manager tests**

Create `tests/test_runtime_manager.py`:

```python
from queue import Queue

from industrial_gateway.models import DeviceSpec, SinkConfig, TagResult
from industrial_gateway.services.runtime_manager import RuntimeManager
from industrial_gateway.store import ConfigStore


class FakeWorker:
    started = 0
    stopped = 0

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        type(self).started += 1

    def stop(self):
        type(self).stopped += 1


class FakeSink:
    def __init__(self, config):
        self.config = config

    def start(self):
        pass

    def stop(self):
        pass

    def publish_batch(self, message):
        pass


def make_store(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    store.save_device(
        DeviceSpec(
            id=None,
            name="plc-1",
            driver_type="modbus_tcp",
            enabled=True,
            poll_interval_ms=1000,
            connection={"host": "127.0.0.1", "port": 502, "unit_id": 1},
        )
    )
    store.save_sink_config(SinkConfig(sink_type="mqtt", enabled=True, config={"host": "localhost", "port": 1883}))
    return store


def test_start_stop_are_idempotent(tmp_path):
    FakeWorker.started = 0
    FakeWorker.stopped = 0
    manager = RuntimeManager(
        make_store(tmp_path),
        driver_registry={"modbus_tcp": lambda device, tags: object()},
        sink_registry={"mqtt": FakeSink},
        poller_class=FakeWorker,
        subscription_worker_class=FakeWorker,
        publisher_class=FakeWorker,
    )

    first = manager.start()
    second = manager.start()

    assert first["running"] is True
    assert second["running"] is True
    assert FakeWorker.started == 2

    manager.stop()
    manager.stop()

    assert FakeWorker.stopped == 2
    assert manager.snapshot()["running"] is False


def test_drain_status_records_tag_and_log_events(tmp_path):
    manager = RuntimeManager(make_store(tmp_path), driver_registry={}, sink_registry={})

    manager.status_queue.put(
        {
            "type": "tag_update",
            "device": "plc-1",
            "tag": "temperature",
            "node_id": "",
            "mode": "Polling",
            "timestamp": "2026-05-19T00:00:00+00:00",
            "quality": "good",
            "error": None,
        }
    )
    manager.log_display_queue.put("log line")
    events = manager.drain_events()

    assert events[0]["type"] == "tag_update"
    assert manager.snapshot()["runtime_tags"][0]["tag"] == "temperature"
    assert manager.snapshot()["logs"] == ["log line"]
```

- [ ] **Step 2: Run runtime manager tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_runtime_manager.py -q
```

Expected: fail with `ModuleNotFoundError` for `runtime_manager`.

- [ ] **Step 3: Add runtime manager implementation**

Create `src/industrial_gateway/services/runtime_manager.py`:

```python
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
from industrial_gateway.workers import DriverPoller, OpcUaSubscriptionWorker, SinkPublisher


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
        self.driver_registry = driver_registry or default_driver_registry
        self.sink_registry = sink_registry or default_sink_registry
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

    def start(self, health_interval_s: int | None = None) -> dict[str, Any]:
        with self._lock:
            if self.running:
                return self.snapshot()
            if health_interval_s is not None:
                self.health_interval_s = health_interval_s
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
            self.publisher = self.publisher_class(
                sink,
                message_config,
                self.result_queue,
                self.status_queue,
                log_queue=self.logger.input_queue,
            )
            self.publisher.start()
            self.pollers = []
            self.subscription_workers = []
            for device in self.store.list_devices():
                if not device.enabled:
                    continue
                driver_class = self.driver_registry.get(device.driver_type)
                tags = self.store.list_tags(device.id or 0)
                if device.driver_type == "opcua" and device.connection.get("mode") == "subscription":
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
            self.runtime_tags[key] = item
            return item
        if isinstance(item, dict) and item.get("type") == "server_status":
            self.server_statuses[str(item.get("device", ""))] = item
            return item
        return {"type": "status", "message": str(item)}

    def _initial_runtime_tags(self) -> dict[tuple[str, str], dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for device in self.store.list_devices():
            if not device.enabled:
                continue
            mode = "Subscription" if device.driver_type == "opcua" and device.connection.get("mode") == "subscription" else "Polling"
            for tag in self.store.list_tags(device.id or 0):
                if not tag.enabled:
                    continue
                key = (device.name, tag.node_id or tag.name)
                rows[key] = {
                    "type": "tag_update",
                    "device": device.name,
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
```

- [ ] **Step 4: Run runtime manager tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_runtime_manager.py -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run worker tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_workers.py -q
```

Expected: all worker tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src\industrial_gateway\services\runtime_manager.py tests\test_runtime_manager.py
git commit -m "feat: add runtime manager"
```

---

### Task 4: Authentication

**Files:**
- Create: `src/industrial_gateway/web/auth.py`
- Modify: `src/industrial_gateway/web/api.py`
- Test: `tests/test_web_auth.py`

- [ ] **Step 1: Write failing auth tests**

Create `tests/test_web_auth.py`:

```python
from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def make_client(tmp_path):
    app = create_app(
        store_path=tmp_path / "gateway.sqlite3",
        session_secret="secret",
        admin_username="admin",
        admin_password="password",
    )
    return TestClient(app)


def test_protected_session_requires_login(tmp_path):
    client = make_client(tmp_path)

    response = client.get("/api/session")

    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_login_and_logout(tmp_path):
    client = make_client(tmp_path)

    login = client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    assert login.status_code == 200
    assert login.json() == {"authenticated": True, "username": "admin"}

    session = client.get("/api/session")
    assert session.status_code == 200
    assert session.json()["username"] == "admin"

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    assert client.get("/api/session").status_code == 401


def test_bad_login_rejected(tmp_path):
    client = make_client(tmp_path)

    response = client.post("/api/auth/login", json={"username": "admin", "password": "bad"})

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_credentials"
```

- [ ] **Step 2: Run auth tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py -q
```

Expected: fail because `create_app` does not accept admin credentials and auth routes do not exist.

- [ ] **Step 3: Add auth helpers**

Create `src/industrial_gateway/web/auth.py`:

```python
from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, HTTPException, Response
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

SESSION_COOKIE = "industrial_gateway_session"


class LoginRequest(BaseModel):
    username: str
    password: str


@dataclass(frozen=True)
class AuthSettings:
    username: str
    password: str
    session_secret: str


def create_session_token(settings: AuthSettings) -> str:
    return URLSafeSerializer(settings.session_secret, salt="industrial-gateway-session").dumps(
        {"username": settings.username}
    )


def read_session_token(token: str, settings: AuthSettings) -> dict[str, str]:
    try:
        data = URLSafeSerializer(settings.session_secret, salt="industrial-gateway-session").loads(token)
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Login required"}) from exc
    if data.get("username") != settings.username:
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Login required"})
    return {"username": settings.username}


def verify_login(request: LoginRequest, settings: AuthSettings) -> bool:
    return hmac.compare_digest(request.username, settings.username) and hmac.compare_digest(
        request.password,
        settings.password,
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def require_session(
    settings: AuthSettings,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> dict[str, str]:
    if not token:
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Login required"})
    return read_session_token(token, settings)
```

- [ ] **Step 4: Wire auth into the app**

Modify `src/industrial_gateway/web/api.py` so `create_app` signature and routes include auth:

```python
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse

from industrial_gateway.store import ConfigStore
from industrial_gateway.web.auth import (
    AuthSettings,
    LoginRequest,
    clear_session_cookie,
    create_session_token,
    require_session,
    set_session_cookie,
    verify_login,
)


def create_app(
    store_path: str | Path,
    session_secret: str,
    admin_username: str = "admin",
    admin_password: str = "admin",
) -> FastAPI:
    store = ConfigStore(store_path)
    store.initialize()
    auth_settings = AuthSettings(admin_username, admin_password, session_secret)
    app = FastAPI(title="Industrial Gateway")
    app.state.store = store
    app.state.auth_settings = auth_settings

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "message": str(exc.detail)})

    def session_dependency(industrial_gateway_session: str | None = Cookie(default=None)) -> dict[str, str]:
        return require_session(auth_settings, industrial_gateway_session)

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, object]:
        if not verify_login(payload, auth_settings):
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_credentials", "message": "Invalid username or password"},
            )
        set_session_cookie(response, create_session_token(auth_settings))
        return {"authenticated": True, "username": auth_settings.username}

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict[str, bool]:
        clear_session_cookie(response)
        return {"authenticated": False}

    @app.get("/api/session")
    def session(user: Annotated[dict[str, str], Depends(session_dependency)]) -> dict[str, object]:
        return {"authenticated": True, "username": user["username"]}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
```

- [ ] **Step 5: Run auth tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_auth.py -q
```

Expected: `3 passed`.

- [ ] **Step 6: Commit**

```powershell
git add src\industrial_gateway\web\auth.py src\industrial_gateway\web\api.py tests\test_web_auth.py
git commit -m "feat: add web authentication"
```

---

### Task 5: REST API and WebSocket

**Files:**
- Modify: `src/industrial_gateway/web/api.py`
- Test: `tests/test_web_api.py`

- [ ] **Step 1: Write failing API tests**

Create `tests/test_web_api.py`:

```python
from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def make_client(tmp_path):
    app = create_app(
        store_path=tmp_path / "gateway.sqlite3",
        session_secret="secret",
        admin_username="admin",
        admin_password="password",
    )
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "admin", "password": "password"})
    return client


def test_device_tag_plugin_api_round_trip(tmp_path):
    client = make_client(tmp_path)

    created = client.post(
        "/api/devices",
        json={
            "name": "plc-1",
            "driver_type": "modbus_tcp",
            "enabled": True,
            "poll_interval_ms": 1000,
            "connection": {"host": "127.0.0.1", "port": 502, "unit_id": 1},
        },
    )
    assert created.status_code == 200
    device = created.json()
    assert client.get("/api/devices").json()[0]["name"] == "plc-1"

    tag_response = client.post(
        f"/api/devices/{device['id']}/tags",
        json={
            "name": "temperature",
            "address": 100,
            "function": "holding_register",
            "data_type": "float32",
            "scale": 1.0,
            "enabled": True,
        },
    )
    assert tag_response.status_code == 200
    assert client.get(f"/api/devices/{device['id']}/tags").json()[0]["name"] == "temperature"

    plugin = client.put(
        "/api/plugins/mqtt",
        json={"enabled": True, "config": {"host": "broker", "port": 1883, "base_topic": "plant", "client_id": "gw", "qos": 0}},
    )
    assert plugin.status_code == 200
    assert client.get("/api/plugins/mqtt").json()["config"]["host"] == "broker"


def test_runtime_status_endpoint_is_protected(tmp_path):
    app = create_app(tmp_path / "gateway.sqlite3", session_secret="secret", admin_username="admin", admin_password="password")
    client = TestClient(app)

    response = client.get("/api/runtime/status")

    assert response.status_code == 401


def test_runtime_events_websocket_sends_snapshot(tmp_path):
    client = make_client(tmp_path)

    with client.websocket_connect("/api/runtime/events") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "snapshot"
    assert message["payload"]["running"] is False
```

- [ ] **Step 2: Run API tests to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -q
```

Expected: fail with 404 responses for the new API routes.

- [ ] **Step 3: Wire services and REST routes**

Modify `src/industrial_gateway/web/api.py`:

```python
from fastapi import WebSocket, WebSocketDisconnect

from industrial_gateway.services.config_service import ConfigService
from industrial_gateway.services.runtime_manager import RuntimeManager
```

Inside `create_app`, after `auth_settings`:

```python
    config_service = ConfigService(store)
    runtime_manager = RuntimeManager(store)
    app.state.config_service = config_service
    app.state.runtime_manager = runtime_manager

    @app.on_event("shutdown")
    def shutdown_runtime() -> None:
        runtime_manager.shutdown()
```

Add protected routes:

```python
    @app.get("/api/devices")
    def list_devices(_user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.list_devices()

    @app.post("/api/devices")
    def create_device(payload: dict, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.create_device(payload)

    @app.put("/api/devices/{device_id}")
    def update_device(device_id: int, payload: dict, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.update_device(device_id, payload)

    @app.delete("/api/devices/{device_id}")
    def delete_device(device_id: int, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        config_service.delete_device(device_id)
        return {"deleted": True}

    @app.get("/api/devices/{device_id}/tags")
    def list_tags(device_id: int, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.list_tags(device_id)

    @app.post("/api/devices/{device_id}/tags")
    def create_tag(device_id: int, payload: dict, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.create_tag(device_id, payload)

    @app.put("/api/tags/{tag_id}")
    def update_tag(tag_id: int, payload: dict, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.update_tag(tag_id, payload)

    @app.delete("/api/tags/{tag_id}")
    def delete_tag(tag_id: int, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        config_service.delete_tag(tag_id)
        return {"deleted": True}

    @app.get("/api/plugins")
    def list_plugins(_user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.list_sink_configs()

    @app.get("/api/plugins/{sink_type}")
    def get_plugin(sink_type: str, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.get_sink_config(sink_type)

    @app.put("/api/plugins/{sink_type}")
    def save_plugin(sink_type: str, payload: dict, _user: Annotated[dict[str, str], Depends(session_dependency)]):
        return config_service.save_sink_config({"sink_type": sink_type, **payload})

    @app.post("/api/runtime/start")
    def start_runtime(payload: dict | None = None, _user: Annotated[dict[str, str], Depends(session_dependency)] = None):
        health_interval = None if payload is None else payload.get("health_interval_s")
        return runtime_manager.start(health_interval)

    @app.post("/api/runtime/stop")
    def stop_runtime(_user: Annotated[dict[str, str], Depends(session_dependency)]):
        return runtime_manager.stop()

    @app.get("/api/runtime/status")
    def runtime_status(_user: Annotated[dict[str, str], Depends(session_dependency)]):
        runtime_manager.drain_events()
        return runtime_manager.snapshot()
```

Add WebSocket route:

```python
    @app.websocket("/api/runtime/events")
    async def runtime_events(websocket: WebSocket):
        token = websocket.cookies.get("industrial_gateway_session")
        try:
            require_session(auth_settings, token)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "snapshot", "payload": runtime_manager.snapshot()})
        try:
            while True:
                for event in runtime_manager.drain_events():
                    await websocket.send_json(event)
                await websocket.receive_text()
        except WebSocketDisconnect:
            return
```

Add a KeyError exception handler:

```python
    @app.exception_handler(KeyError)
    async def key_error_handler(_request, exc: KeyError):
        return JSONResponse(status_code=404, content={"error": "not_found", "message": str(exc)})
```

- [ ] **Step 4: Run API tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_api.py -q
```

Expected: all API tests pass.

- [ ] **Step 5: Run service and auth tests together**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_config_service.py tests\test_runtime_manager.py tests\test_web_auth.py tests\test_web_api.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```powershell
git add src\industrial_gateway\web\api.py tests\test_web_api.py
git commit -m "feat: add web api routes"
```

---

### Task 6: Static Web UI

**Files:**
- Create: `src/industrial_gateway/web/static/index.html`
- Create: `src/industrial_gateway/web/static/styles.css`
- Create: `src/industrial_gateway/web/static/app.js`
- Modify: `src/industrial_gateway/web/api.py`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Write failing static UI test**

Create `tests/test_web_static.py`:

```python
from fastapi.testclient import TestClient

from industrial_gateway.web.api import create_app


def test_index_served(tmp_path):
    app = create_app(tmp_path / "gateway.sqlite3", session_secret="secret")
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Industrial Gateway" in response.text
    assert "/static/app.js" in response.text
```

- [ ] **Step 2: Run static test to verify failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_static.py -q
```

Expected: fail with 404 for `/`.

- [ ] **Step 3: Add static UI files**

Create `src/industrial_gateway/web/static/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Industrial Gateway</title>
    <link rel="stylesheet" href="/static/styles.css">
  </head>
  <body>
    <main class="app">
      <section id="loginView" class="login">
        <h1>Industrial Gateway</h1>
        <form id="loginForm">
          <label>Username <input id="username" autocomplete="username" value="admin"></label>
          <label>Password <input id="password" type="password" autocomplete="current-password"></label>
          <button type="submit">Log in</button>
          <p id="loginError" class="error"></p>
        </form>
      </section>

      <section id="consoleView" class="console hidden">
        <header class="topbar">
          <h1>Industrial Gateway</h1>
          <div class="status"><span id="runtimeBadge">Stopped</span><button id="logoutButton">Log out</button></div>
        </header>
        <nav class="tabs">
          <button data-tab="devices" class="active">Devices</button>
          <button data-tab="plugins">Plugins</button>
          <button data-tab="runtime">Runtime</button>
        </nav>
        <section id="devicesTab" class="tab-panel">
          <div class="split">
            <div><h2>Devices</h2><ul id="deviceList" class="list"></ul><button id="newDevice">New device</button></div>
            <form id="deviceForm" class="panel"></form>
            <form id="tagForm" class="panel"></form>
          </div>
        </section>
        <section id="pluginsTab" class="tab-panel hidden">
          <h2>Output Plugin</h2>
          <form id="pluginForm" class="panel"></form>
        </section>
        <section id="runtimeTab" class="tab-panel hidden">
          <div class="runtime-actions">
            <button id="startRuntime">Start</button>
            <button id="stopRuntime">Stop</button>
            <label>Health interval <input id="healthInterval" type="number" min="1" value="10"></label>
          </div>
          <h2>Runtime Tags</h2>
          <table><thead><tr><th>Device</th><th>Tag</th><th>Mode</th><th>Updated</th><th>Status</th></tr></thead><tbody id="runtimeTags"></tbody></table>
          <h2>Logs</h2>
          <pre id="logs"></pre>
        </section>
      </section>
    </main>
    <script src="/static/app.js"></script>
  </body>
</html>
```

Create `src/industrial_gateway/web/static/styles.css` with dense operations styling:

```css
* { box-sizing: border-box; }
body { margin: 0; font-family: Segoe UI, Arial, sans-serif; color: #172026; background: #f4f6f8; }
button, input, select { font: inherit; }
button { border: 1px solid #8a99a8; background: #ffffff; padding: 7px 10px; cursor: pointer; }
button.active, button:hover { background: #e7eef5; }
.hidden { display: none !important; }
.app { min-height: 100vh; }
.login { width: min(360px, calc(100vw - 32px)); margin: 12vh auto; background: #fff; border: 1px solid #d8dee6; padding: 24px; }
.login form, .panel { display: grid; gap: 10px; }
label { display: grid; gap: 4px; color: #33414f; }
input, select { width: 100%; border: 1px solid #b8c2cc; padding: 7px 8px; background: #fff; }
.error { color: #b42318; min-height: 20px; }
.topbar { display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; background: #1f2a33; color: #fff; }
.topbar h1 { font-size: 18px; margin: 0; }
.status { display: flex; align-items: center; gap: 12px; }
.tabs { display: flex; gap: 4px; padding: 8px 18px; background: #dfe5eb; }
.tab-panel { padding: 16px 18px; }
.split { display: grid; grid-template-columns: 260px minmax(280px, 420px) 1fr; gap: 16px; align-items: start; }
.panel { background: #fff; border: 1px solid #d8dee6; padding: 14px; }
.list { list-style: none; padding: 0; margin: 0 0 10px; background: #fff; border: 1px solid #d8dee6; min-height: 320px; }
.list li { padding: 8px 10px; border-bottom: 1px solid #edf0f3; cursor: pointer; }
.list li.active { background: #dcebf8; }
.runtime-actions { display: flex; gap: 10px; align-items: end; margin-bottom: 16px; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d8dee6; }
th, td { padding: 7px 8px; border-bottom: 1px solid #edf0f3; text-align: left; }
pre { min-height: 180px; max-height: 280px; overflow: auto; background: #111820; color: #d7e2ec; padding: 12px; }
@media (max-width: 900px) { .split { grid-template-columns: 1fr; } .runtime-actions { flex-wrap: wrap; } }
```

Create `src/industrial_gateway/web/static/app.js` with API calls, login, tabs, and runtime rendering:

```javascript
const state = { devices: [], selectedDevice: null, ws: null };

async function api(path, options = {}) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) throw await response.json().catch(() => ({ message: response.statusText }));
  return response.json();
}

function showConsole(show) {
  document.getElementById("loginView").classList.toggle("hidden", show);
  document.getElementById("consoleView").classList.toggle("hidden", !show);
}

async function login(event) {
  event.preventDefault();
  try {
    await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value
      })
    });
    document.getElementById("loginError").textContent = "";
    await loadAll();
    showConsole(true);
  } catch (error) {
    document.getElementById("loginError").textContent = error.message || "Login failed";
  }
}

async function loadAll() {
  state.devices = await api("/api/devices");
  renderDevices();
  await loadPlugin();
  await loadRuntime();
  connectRuntimeEvents();
}

function renderDevices() {
  const list = document.getElementById("deviceList");
  list.innerHTML = "";
  state.devices.forEach(device => {
    const item = document.createElement("li");
    item.textContent = `${device.device_group ? device.device_group + " / " : ""}${device.name}`;
    item.className = state.selectedDevice && state.selectedDevice.id === device.id ? "active" : "";
    item.onclick = () => selectDevice(device);
    list.appendChild(item);
  });
  renderDeviceForm(state.selectedDevice || state.devices[0] || null);
}

function renderDeviceForm(device) {
  state.selectedDevice = device;
  const form = document.getElementById("deviceForm");
  const data = device || { name: "", device_group: "", driver_type: "modbus_tcp", enabled: true, poll_interval_ms: 1000, connection: {} };
  form.innerHTML = `
    <h2>Device</h2>
    <label>Group <input name="device_group" value="${data.device_group || ""}"></label>
    <label>Name <input name="name" value="${data.name || ""}" required></label>
    <label>Driver <select name="driver_type"><option>modbus_tcp</option><option>modbus_serial</option><option>opcua</option></select></label>
    <label>Enabled <input name="enabled" type="checkbox" ${data.enabled ? "checked" : ""}></label>
    <label>Poll ms <input name="poll_interval_ms" type="number" min="100" value="${data.poll_interval_ms || 1000}"></label>
    <label>Connection JSON <input name="connection" value='${JSON.stringify(data.connection || {})}'></label>
    <button type="submit">Save device</button>
  `;
  form.elements.driver_type.value = data.driver_type || "modbus_tcp";
  form.onsubmit = saveDevice;
  renderTagForm();
}

async function saveDevice(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {
    device_group: form.elements.device_group.value,
    name: form.elements.name.value,
    driver_type: form.elements.driver_type.value,
    enabled: form.elements.enabled.checked,
    poll_interval_ms: Number(form.elements.poll_interval_ms.value),
    connection: JSON.parse(form.elements.connection.value || "{}")
  };
  if (state.selectedDevice && state.selectedDevice.id) {
    await api(`/api/devices/${state.selectedDevice.id}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    await api("/api/devices", { method: "POST", body: JSON.stringify(payload) });
  }
  state.devices = await api("/api/devices");
  renderDevices();
}

function renderTagForm() {
  const form = document.getElementById("tagForm");
  form.innerHTML = `
    <h2>New Tag</h2>
    <label>Name <input name="name" required></label>
    <label>NodeId <input name="node_id"></label>
    <label>Address <input name="address" type="number" value="0"></label>
    <label>Function <select name="function"><option>holding_register</option><option>input_register</option><option>coil</option><option>discrete_input</option><option>opcua_node</option></select></label>
    <label>Data type <select name="data_type"><option>auto</option><option>bool</option><option>int16</option><option>uint16</option><option>int32</option><option>uint32</option><option>float32</option><option>float64</option><option>string</option></select></label>
    <label>Scale <input name="scale" type="number" value="1"></label>
    <button type="submit">Add tag</button>
  `;
  form.onsubmit = saveTag;
}

async function saveTag(event) {
  event.preventDefault();
  if (!state.selectedDevice) return;
  const form = event.currentTarget;
  await api(`/api/devices/${state.selectedDevice.id}/tags`, {
    method: "POST",
    body: JSON.stringify({
      name: form.elements.name.value,
      node_id: form.elements.node_id.value,
      address: Number(form.elements.address.value),
      function: form.elements.function.value,
      data_type: form.elements.data_type.value,
      scale: Number(form.elements.scale.value),
      enabled: true
    })
  });
  form.reset();
}

async function loadPlugin() {
  const plugin = await api("/api/plugins/mqtt");
  const form = document.getElementById("pluginForm");
  form.innerHTML = `
    <label>Enabled <input name="enabled" type="checkbox" ${plugin.enabled ? "checked" : ""}></label>
    <label>Config JSON <input name="config" value='${JSON.stringify(plugin.config)}'></label>
    <button type="submit">Save plugin</button>
  `;
  form.onsubmit = async event => {
    event.preventDefault();
    await api("/api/plugins/mqtt", {
      method: "PUT",
      body: JSON.stringify({ enabled: form.elements.enabled.checked, config: JSON.parse(form.elements.config.value || "{}") })
    });
  };
}

async function loadRuntime() {
  renderRuntime(await api("/api/runtime/status"));
}

function renderRuntime(snapshot) {
  document.getElementById("runtimeBadge").textContent = snapshot.running ? "Running" : "Stopped";
  document.getElementById("runtimeTags").innerHTML = snapshot.runtime_tags.map(row =>
    `<tr><td>${row.device}</td><td>${row.tag}</td><td>${row.mode}</td><td>${row.timestamp || ""}</td><td>${row.error || row.quality}</td></tr>`
  ).join("");
  document.getElementById("logs").textContent = (snapshot.logs || []).join("\n");
}

function connectRuntimeEvents() {
  if (state.ws) state.ws.close();
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  state.ws = new WebSocket(`${scheme}://${location.host}/api/runtime/events`);
  state.ws.onmessage = event => {
    const message = JSON.parse(event.data);
    if (message.type === "snapshot") renderRuntime(message.payload);
    if (message.type === "log") loadRuntime();
    if (message.type === "tag_update" || message.type === "server_status") loadRuntime();
  };
}

document.getElementById("loginForm").addEventListener("submit", login);
document.getElementById("logoutButton").onclick = async () => { await api("/api/auth/logout", { method: "POST" }); showConsole(false); };
document.getElementById("newDevice").onclick = () => renderDeviceForm(null);
document.getElementById("startRuntime").onclick = async () => renderRuntime(await api("/api/runtime/start", { method: "POST", body: JSON.stringify({ health_interval_s: Number(document.getElementById("healthInterval").value) }) }));
document.getElementById("stopRuntime").onclick = async () => renderRuntime(await api("/api/runtime/stop", { method: "POST" }));
document.querySelectorAll(".tabs button").forEach(button => button.onclick = () => {
  document.querySelectorAll(".tabs button").forEach(item => item.classList.remove("active"));
  document.querySelectorAll(".tab-panel").forEach(item => item.classList.add("hidden"));
  button.classList.add("active");
  document.getElementById(`${button.dataset.tab}Tab`).classList.remove("hidden");
});
api("/api/session").then(() => loadAll().then(() => showConsole(true))).catch(() => showConsole(false));
```

- [ ] **Step 4: Serve static files from FastAPI**

Modify `src/industrial_gateway/web/api.py` imports:

```python
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
```

Inside `create_app`, before returning `app`:

```python
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")
```

- [ ] **Step 5: Run static UI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_web_static.py -q
```

Expected: `1 passed`.

- [ ] **Step 6: Commit**

```powershell
git add src\industrial_gateway\web\static src\industrial_gateway\web\api.py tests\test_web_static.py
git commit -m "feat: add web console ui"
```

---

### Task 7: End-to-End Verification

**Files:**
- Modify: `README.md`
- Test: all tests

- [ ] **Step 1: Add README web run instructions**

Modify `README.md` Run section to include:

```markdown
## Run Web Service

```powershell
$env:INDUSTRIAL_GATEWAY_ADMIN_USER="admin"
$env:INDUSTRIAL_GATEWAY_ADMIN_PASSWORD="change-me"
$env:INDUSTRIAL_GATEWAY_SESSION_SECRET="replace-with-random-secret"
industrial-gateway-web
```

The web service listens on `0.0.0.0:50137` by default. Use LAN or VPN access for the first release. Do not expose this port directly to the public internet.
```

- [ ] **Step 2: Wire CLI auth environment variables**

Modify `src/industrial_gateway/web/app.py` so `main()` reads credentials:

```python
    parser.add_argument("--admin-username", default=os.getenv("INDUSTRIAL_GATEWAY_ADMIN_USER", "admin"))
    parser.add_argument("--admin-password", default=os.getenv("INDUSTRIAL_GATEWAY_ADMIN_PASSWORD", "admin"))
```

And pass them to `create_app`:

```python
    app = create_app(
        Path(args.store),
        args.session_secret,
        admin_username=args.admin_username,
        admin_password=args.admin_password,
    )
```

- [ ] **Step 3: Run full test suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 4: Start local web server**

Run:

```powershell
$env:INDUSTRIAL_GATEWAY_ADMIN_USER="admin"
$env:INDUSTRIAL_GATEWAY_ADMIN_PASSWORD="password"
$env:INDUSTRIAL_GATEWAY_SESSION_SECRET="local-dev-secret"
Start-Process -FilePath .\.venv\Scripts\industrial-gateway-web.exe -WorkingDirectory .
```

Expected: process remains running and `http://localhost:50137` returns the web console.

- [ ] **Step 5: Manual smoke check**

Open `http://localhost:50137` and verify:

- Login with `admin` / `password`.
- Devices tab loads.
- Plugins tab loads MQTT config form.
- Runtime tab loads with `Stopped`.
- Start/Stop buttons call the API without 401 after login.

- [ ] **Step 6: Commit**

```powershell
git add README.md src\industrial_gateway\web\app.py
git commit -m "docs: add web service run instructions"
```

---

## Self-Review

Spec coverage:

- LAN/VPN bind on `0.0.0.0:50137`: Task 1 and Task 7.
- Login required: Task 4 and Task 5.
- Device/tag/plugin CRUD: Task 2 and Task 5.
- Runtime start/stop/status: Task 3 and Task 5.
- WebSocket runtime events: Task 3 and Task 5.
- Browser UI: Task 6.
- Existing PySide6 kept: no deletion tasks.
- Tests: every new boundary has focused pytest coverage and Task 7 runs the full suite.

Placeholder scan:

- No placeholder markers, hedging words, or unresolved endpoint names remain.

Type consistency:

- `ConfigService`, `RuntimeManager`, and `create_app` signatures are introduced before API tasks use them.
- Route names in tests match the design spec.
- CLI script name matches `pyproject.toml`.
