from industrial_gateway.models import DeviceSpec, OutputRouteConfig, SinkConfig, TagSpec
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


class FakeTopicResponder:
    started = 0
    stopped = 0

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        type(self).started += 1

    def stop(self):
        type(self).stopped += 1


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

    first = manager.start(runtime_log_enabled=False)
    second = manager.start()

    assert first["running"] is True
    assert first["runtime_log_enabled"] is False
    assert second["running"] is True
    assert second["runtime_log_enabled"] is False
    assert FakeWorker.started == 2

    manager.stop()
    manager.stop()

    assert FakeWorker.stopped == 2
    assert manager.snapshot()["running"] is False
    assert manager.snapshot()["runtime_log_enabled"] is False

    manager.shutdown()


def test_drain_status_records_tag_and_log_events(tmp_path):
    store = make_store(tmp_path)
    device_id = store.list_devices()[0].id
    store.save_tag(
        TagSpec(
            device_id=device_id,
            tag_group="group-a",
            name="temperature",
            address=100,
            function="holding_register",
            data_type="float32",
        )
    )
    manager = RuntimeManager(store, driver_registry={}, sink_registry={})
    manager.runtime_tags = manager._initial_runtime_tags()

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
    assert manager.snapshot()["runtime_tags"][0]["tag_group"] == "group-a"
    assert manager.snapshot()["logs"] == ["log line"]

    manager.shutdown()


def test_output_routes_inherit_selected_mqtt_plugin_config(tmp_path):
    store = make_store(tmp_path)
    store.save_sink_config(
        SinkConfig(
            sink_type="mqtt",
            enabled=True,
            config={"host": "broker", "port": 1884, "base_topic": "plant", "client_id": "gw", "qos": 1},
        )
    )
    store.save_output_route(
        OutputRouteConfig(
            device_id=store.list_devices()[0].id,
            tag_group="temp",
            enabled=True,
            config={
                "topic": "temp/current",
                "host": "stale-broker",
                "base_topic": "stale",
                "client_id": "stale-client",
                "qos": 0,
            },
        )
    )
    manager = RuntimeManager(store, sink_registry={"mqtt": FakeSink})

    routes = manager._output_routes()

    assert len(routes) == 1
    assert routes[0].mqtt_config.base_topic == "plant"
    assert routes[0].mqtt_config.qos == 1
    assert routes[0].topic == "plant/temp/current"

    manager.shutdown()


def test_output_routes_are_hidden_when_selected_plugin_is_not_mqtt(tmp_path):
    store = make_store(tmp_path)
    store.save_sink_config(SinkConfig(sink_type="database", enabled=True, config={}))
    store.save_output_route(OutputRouteConfig(device_id=store.list_devices()[0].id, tag_group="temp", enabled=True))
    manager = RuntimeManager(store, sink_registry={"mqtt": FakeSink, "database": FakeSink})

    assert manager._output_routes() == []

    manager.shutdown()


def test_topic_responder_starts_only_when_enabled_for_postgres_profile(tmp_path, monkeypatch):
    FakeWorker.started = 0
    FakeWorker.stopped = 0
    FakeTopicResponder.started = 0
    FakeTopicResponder.stopped = 0
    monkeypatch.setenv("INDUSTRIAL_GATEWAY_PLUGIN_PROFILE", "postgres")
    monkeypatch.setenv("INDUSTRIAL_GATEWAY_TOPIC_RESPONDER_ENABLED", "true")
    manager = RuntimeManager(
        make_store(tmp_path),
        driver_registry={"modbus_tcp": lambda device, tags: object()},
        sink_registry={"mqtt": FakeSink},
        poller_class=FakeWorker,
        subscription_worker_class=FakeWorker,
        publisher_class=FakeWorker,
        topic_responder_class=FakeTopicResponder,
    )

    manager.start()

    assert FakeTopicResponder.started == 1

    manager.stop()

    assert FakeTopicResponder.stopped == 1

    manager.shutdown()


def test_topic_responder_does_not_start_for_core_profile(tmp_path, monkeypatch):
    FakeTopicResponder.started = 0
    monkeypatch.setenv("INDUSTRIAL_GATEWAY_PLUGIN_PROFILE", "core")
    monkeypatch.setenv("INDUSTRIAL_GATEWAY_TOPIC_RESPONDER_ENABLED", "true")
    manager = RuntimeManager(
        make_store(tmp_path),
        driver_registry={"modbus_tcp": lambda device, tags: object()},
        sink_registry={"mqtt": FakeSink},
        poller_class=FakeWorker,
        subscription_worker_class=FakeWorker,
        publisher_class=FakeWorker,
        topic_responder_class=FakeTopicResponder,
    )

    manager.start()

    assert FakeTopicResponder.started == 0

    manager.shutdown()
