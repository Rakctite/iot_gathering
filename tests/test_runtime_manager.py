from datetime import datetime, timezone
from queue import Empty

from industrial_gateway.models import DeviceSpec, OutputRouteConfig, ReadResult, SinkConfig, TagResult, TagSpec
from industrial_gateway.services.runtime_manager import RuntimeManager, _LatestReadResultQueue, _LatestStatusQueue
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

    def join(self, timeout=None):
        self.join_timeout = timeout


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

    def join(self, timeout=None):
        self.join_timeout = timeout


class FakePublisher(FakeWorker):
    instances = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_routes = kwargs.get("output_routes") or []
        type(self).instances.append(self)


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


def make_subscription_store(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    device_id = store.save_device(
        DeviceSpec(
            id=None,
            name="opc",
            driver_type="opcua",
            enabled=True,
            poll_interval_ms=1000,
            connection={"endpoint": "opc.tcp://127.0.0.1:4840", "mode": "subscription"},
        )
    )
    store.save_tag(
        TagSpec(
            device_id=device_id,
            name="pv",
            address=0,
            function="opcua_node",
            data_type="auto",
            node_id="ns=2;s=pv",
        )
    )
    store.save_sink_config(SinkConfig(sink_type="mqtt", enabled=True, config={"host": "localhost", "port": 1883}))
    return store


def test_start_disables_subscription_datachange_logs_when_runtime_log_is_off(tmp_path):
    manager = RuntimeManager(
        make_subscription_store(tmp_path),
        driver_registry={"opcua": lambda device, tags: object()},
        sink_registry={"mqtt": FakeSink},
        poller_class=FakeWorker,
        subscription_worker_class=FakeWorker,
        publisher_class=FakeWorker,
    )

    manager.start(runtime_log_enabled=False)

    assert manager.subscription_workers[0].kwargs["datachange_log_enabled"] is False
    manager.shutdown()


def test_latest_read_result_queue_upserts_by_device_and_tag():
    queue = _LatestReadResultQueue()
    device = DeviceSpec(id=1, name="opc", driver_type="opcua", enabled=True, poll_interval_ms=1000, connection={})
    timestamp = datetime(2026, 5, 16, tzinfo=timezone.utc)

    queue.put(ReadResult(device, timestamp, [TagResult("pv", 0, 1, "good", None, timestamp, node_id="ns=2;s=pv")]))
    queue.put(ReadResult(device, timestamp, [TagResult("pv", 0, 2, "good", None, timestamp, node_id="ns=2;s=pv")]))
    queue.put(ReadResult(device, timestamp, [TagResult("sv", 0, 3, "good", None, timestamp, node_id="ns=2;s=sv")]))

    results = [queue.get_nowait(), queue.get_nowait()]

    assert [(result.tags[0].name, result.tags[0].value) for result in results] == [("pv", 2), ("sv", 3)]
    try:
        queue.get_nowait()
    except Empty:
        pass
    else:
        raise AssertionError("queue should contain only latest values per tag")


def test_latest_status_queue_upserts_tag_and_server_status_events():
    queue = _LatestStatusQueue()

    queue.put({"type": "tag_update", "device": "opc", "node_id": "ns=2;s=pv", "tag": "pv", "value": 1})
    queue.put({"type": "tag_update", "device": "opc", "node_id": "ns=2;s=pv", "tag": "pv", "value": 2})
    queue.put({"type": "server_status", "device": "opc", "status": "OK"})
    queue.put({"type": "server_status", "device": "opc", "status": "ERROR"})

    events = [queue.get_nowait(), queue.get_nowait()]

    assert events == [
        {"type": "tag_update", "device": "opc", "node_id": "ns=2;s=pv", "tag": "pv", "value": 2},
        {"type": "server_status", "device": "opc", "status": "ERROR"},
    ]


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


def test_stop_joins_workers_and_publisher(tmp_path):
    FakePublisher.instances = []
    manager = RuntimeManager(
        make_store(tmp_path),
        driver_registry={"modbus_tcp": lambda device, tags: object()},
        sink_registry={"mqtt": FakeSink},
        poller_class=FakeWorker,
        subscription_worker_class=FakeWorker,
        publisher_class=FakePublisher,
    )

    manager.start()
    poller = manager.pollers[0]
    publisher = manager.publisher

    manager.stop()

    assert poller.join_timeout == 2
    assert publisher.join_timeout == 2
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


def test_output_routes_use_resolved_topic_for_dynamic_route(tmp_path):
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
            tag_group="PHH01",
            enabled=True,
            config={
                "topic": "manual/fallback",
                "dynamic_topic_enabled": True,
                "resolved_topic": "C-S/3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/",
            },
        )
    )
    manager = RuntimeManager(store, sink_registry={"mqtt": FakeSink})

    routes = manager._output_routes()

    assert routes[0].topic == "C-S/3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/"

    manager.shutdown()


def test_output_routes_include_system_heartbeat_route_without_data_matching(tmp_path):
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
            device_id=None,
            tag_group="",
            enabled=True,
            config={
                "route_kind": "system_heartbeat",
                "dynamic_topic_enabled": True,
                "resolved_topic": "C-S/3120/PH/CTM/LO001/PH01/-/SYSTEM",
                "heartbeat_interval_s": 1,
                "sensor_code": "SYSTEM",
            },
        )
    )
    manager = RuntimeManager(store, sink_registry={"mqtt": FakeSink})

    routes = manager._output_routes()

    assert len(routes) == 1
    assert routes[0].route_kind == "system_heartbeat"
    assert routes[0].topic == "C-S/3120/PH/CTM/LO001/PH01/-/SYSTEM"
    assert routes[0].heartbeat_interval_s == 1
    assert routes[0].sensor_code == "SYSTEM"

    manager.shutdown()


def test_start_requests_dynamic_route_topics_from_plugin_setting(tmp_path):
    FakeWorker.started = 0
    FakePublisher.instances = []
    store = make_store(tmp_path)
    store.save_sink_config(
        SinkConfig(
            sink_type="mqtt",
            enabled=True,
            config={
                "host": "broker",
                "port": 1884,
                "base_topic": "plant",
                "client_id": "gw",
                "qos": 1,
                "topic_request_on_start": True,
                "topic_refresh_interval_s": 0,
            },
        )
    )
    store.save_output_route(
        OutputRouteConfig(
            device_id=store.list_devices()[0].id,
            tag_group="PHH01",
            enabled=True,
            config={"dynamic_topic_enabled": True, "mac_address": "AA:BB", "topic": "fallback"},
        )
    )
    calls = []

    manager = RuntimeManager(
        store,
        driver_registry={"modbus_tcp": lambda device, tags: object()},
        sink_registry={"mqtt": FakeSink},
        poller_class=FakeWorker,
        publisher_class=FakePublisher,
        topic_request_resolver=lambda mac, mqtt_config: calls.append((mac, mqtt_config["host"]))
        or {"topic": "3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/", "sensor_count": 12},
    )

    manager.start()

    saved_route = store.list_output_routes()[0]
    assert calls == [("AA:BB", "broker")]
    assert saved_route.config["resolved_topic"] == "C-S/3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/"
    assert FakePublisher.instances[0].output_routes[0].topic == "C-S/3120/PH/PHH/LO001/MC01/-/OPCUA:PLC/"

    manager.shutdown()


def test_start_enables_topic_refresh_thread_from_plugin_setting(tmp_path):
    store = make_store(tmp_path)
    manager = RuntimeManager(store, sink_registry={"mqtt": FakeSink})

    manager._start_topic_refresh_thread({"topic_refresh_interval_s": 60})

    assert manager.topic_refresh_thread is not None

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
