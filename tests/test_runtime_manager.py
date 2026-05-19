from industrial_gateway.models import DeviceSpec, SinkConfig
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

    manager.shutdown()


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

    manager.shutdown()
