import time
from datetime import datetime, timezone
from queue import Queue

from industrial_gateway.models import DeviceSpec, MqttConfig, ReadResult, TagResult
from industrial_gateway.workers import DriverPoller, OpcUaSubscriptionWorker, OutputRoute, SinkPublisher


class FakeDriver:
    def __init__(self, device, tags):
        self.device = device
        self.tags = tags
        self.connected = False

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.connected = False

    def read_tags(self):
        return [
            TagResult(
                name="flow",
                address=1,
                value=42,
                quality="good",
                error=None,
                timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
            )
        ]


class FakeSink:
    def __init__(self):
        self.messages = []
        self.started = False

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def publish_batch(self, message):
        self.messages.append(message)


class FailingConnectDriver(FakeDriver):
    def connect(self):
        raise RuntimeError("connect boom")


class FailingHealthDriver(FakeDriver):
    def read_server_status(self):
        raise RuntimeError("server down")


class FailingSubscriptionDriver:
    def __init__(self, device, tags):
        self.device = device
        self.tags = tags
        self.stopped = False
        self.disconnected = False

    def connect(self):
        pass

    def start_subscription(self, emit):
        self.emit = emit

    def stop_subscription(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True

    def run_subscription_once(self, timeout=0.2):
        raise RuntimeError("subscription boom")

    def read_server_status(self):
        return {"ok": True}


class EmptyMessageSubscriptionDriver(FailingSubscriptionDriver):
    def connect(self):
        raise RuntimeError()


class EventuallyConnectedSubscriptionDriver(FailingSubscriptionDriver):
    attempts = 0
    instances = []

    def __init__(self, device, tags):
        super().__init__(device, tags)
        self.connected = False
        self.started = False
        self.run_count = 0
        EventuallyConnectedSubscriptionDriver.instances.append(self)

    def connect(self):
        EventuallyConnectedSubscriptionDriver.attempts += 1
        if EventuallyConnectedSubscriptionDriver.attempts == 1:
            raise OSError(113, "No route to host")
        self.connected = True

    def start_subscription(self, emit):
        self.started = True
        self.emit = emit

    def run_subscription_once(self, timeout=0.2):
        self.run_count += 1
        time.sleep(0.01)


def test_driver_poller_puts_read_result_on_queue():
    outbox = Queue()
    logs = Queue()
    device = DeviceSpec(
        id=1,
        name="meter",
        driver_type="fake",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    poller = DriverPoller(lambda d, tags: FakeDriver(d, tags), device, [], outbox, log_queue=logs)

    poller.poll_once()

    result = outbox.get_nowait()
    assert isinstance(result, ReadResult)
    assert result.device.name == "meter"
    assert result.tags[0].value == 42
    assert logs.get_nowait()["message"] == "driver read completed"


def test_driver_poller_logs_connect_or_read_failure():
    outbox = Queue()
    logs = Queue()
    device = DeviceSpec(
        id=1,
        name="meter",
        driver_type="fake",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    poller = DriverPoller(lambda d, tags: FailingConnectDriver(d, tags), device, [], outbox, log_queue=logs)

    poller.poll_once()

    result = outbox.get_nowait()
    record = logs.get_nowait()
    assert result.error == "connect boom"
    assert record["level"] == "ERROR"
    assert record["message"] == "driver read failed"
    assert record["data"]["driver"] == "fake"
    assert record["data"]["error"] == "connect boom"


def test_driver_poller_logs_server_health_check_failure():
    outbox = Queue()
    logs = Queue()
    status = Queue()
    device = DeviceSpec(
        id=1,
        name="opc",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    poller = DriverPoller(
        lambda d, tags: FailingHealthDriver(d, tags),
        device,
        [],
        outbox,
        log_queue=logs,
        status_outbox=status,
        health_interval_s=0,
    )

    poller.poll_once()

    status_item = status.get_nowait()
    records = [logs.get_nowait(), logs.get_nowait()]
    assert status_item["status"] == "ERROR"
    assert any(record["message"] == "server health check failed" for record in records)


def test_sink_publisher_converts_results_to_batch_message():
    inbox = Queue()
    logs = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="fake",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    inbox.put(
        ReadResult(
            device=device,
            timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=12.3,
                    quality="good",
                    error=None,
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                )
            ],
            error=None,
        )
    )

    publisher = SinkPublisher(sink, MqttConfig(base_topic="plant"), inbox, log_queue=logs)
    publisher.publish_once()
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 1, tzinfo=timezone.utc))

    assert sink.messages[0].topic == "plant/press/data"
    assert sink.messages[0].payload["tags"][0]["value"] == 12.3
    assert sink.messages[1].topic == "plant/press/data/status"
    assert sink.messages[1].payload["timestamp"] == "2026-05-16T00:00:01.000+00:00"
    assert sink.messages[1].payload["sensors"] == [
        {
            "sensor_code": "bar",
            "conn_status": "on",
            "last_seen": "2026-05-16T00:00:00.000+00:00",
            "health_score": 100.0,
            "error_msg": None,
            "update_time": "2026-05-16T00:00:01.000+00:00",
        }
    ]
    assert logs.empty()


def test_sink_publisher_uses_output_route_for_device_and_tag_group():
    inbox = Queue()
    default_sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="fake",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    inbox.put(
        ReadResult(
            device=device,
            timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=12.3,
                    quality="good",
                    error=None,
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                    tag_group="temp",
                )
            ],
        )
    )
    publisher = SinkPublisher(
        default_sink,
        MqttConfig(base_topic="default"),
        inbox,
        output_routes=[
            OutputRoute(
                device_id=2,
                tag_group="temp",
                sink_type="mqtt",
                mqtt_config=MqttConfig(base_topic="routed"),
                topic="route/exact/current",
            )
        ],
    )

    publisher.publish_once()
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 1, tzinfo=timezone.utc))

    assert default_sink.messages[0].topic == "route/exact/current"
    assert default_sink.messages[0].use_message_topic is True
    assert default_sink.messages[0].payload["tags"][0]["tag_group"] == "temp"


def test_sink_publisher_publishes_system_heartbeat_route():
    inbox = Queue()
    sink = FakeSink()
    route = OutputRoute(
        device_id=None,
        tag_group="",
        sink_type="mqtt",
        mqtt_config=MqttConfig(base_topic="plant", qos=1),
        topic="C-S/3120/PH/CTM/LO001/PH01/-/SYSTEM",
        route_kind="system_heartbeat",
        heartbeat_interval_s=1,
        sensor_code="SYSTEM",
    )
    publisher = SinkPublisher(
        sink,
        MqttConfig(base_topic="plant"),
        inbox,
        output_routes=[route],
    )

    publisher.publish_cached(datetime(2026, 6, 23, 4, 30, 0, tzinfo=timezone.utc))

    assert len(sink.messages) == 1
    assert sink.messages[0].topic == "C-S/3120/PH/CTM/LO001/PH01/-/SYSTEM/status"
    assert sink.messages[0].qos == 1
    assert sink.messages[0].use_message_topic is True
    assert sink.messages[0].payload == {
        "timestamp": "2026-06-23 04:30:00.000+00",
        "sensors": [
            {
                "sensor_code": "SYSTEM",
                "conn_status": "on",
                "last_seen": "2026-06-23 04:30:00.000+00",
                "health_score": 100.0,
                "error_msg": None,
                "update_time": "2026-06-23 04:30:00.000+00",
            }
        ],
    }


def test_sink_publisher_emits_tag_update_status():
    inbox = Queue()
    status = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=100,
        connection={"mode": "subscription"},
    )
    inbox.put(
        ReadResult(
            device=device,
            timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=12.3,
                    quality="good",
                    error=None,
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                    node_id="ns=2;s=PHH01.MC01.bar",
                )
            ],
        )
    )
    publisher = SinkPublisher(sink, MqttConfig(base_topic="plant"), inbox, status_outbox=status)

    publisher.publish_once()

    item = status.get_nowait()
    assert item["type"] == "tag_update"
    assert item["tag"] == "bar"
    assert item["node_id"] == "ns=2;s=PHH01.MC01.bar"
    assert item["mode"] == "Subscription"


def test_sink_publisher_logs_bad_tag_result():
    inbox = Queue()
    logs = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="fake",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    inbox.put(
        ReadResult(
            device=device,
            timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=None,
                    quality="bad",
                    error="read timeout",
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                )
            ],
        )
    )
    publisher = SinkPublisher(sink, MqttConfig(base_topic="plant"), inbox, log_queue=logs)

    publisher.publish_once()

    record = logs.get_nowait()
    assert record["level"] == "ERROR"
    assert record["message"] == "tag read failed"
    assert record["data"]["driver"] == "fake"
    assert record["data"]["tag"] == "bar"
    assert record["data"]["error"] == "read timeout"


def test_sink_publisher_logs_plugin_type_on_sink_failure():
    class FailingStartSink(FakeSink):
        def start(self):
            raise RuntimeError("refused")

    inbox = Queue()
    logs = Queue()
    status = Queue()
    publisher = SinkPublisher(
        FailingStartSink(),
        MqttConfig(base_topic="plant"),
        inbox,
        status_outbox=status,
        log_queue=logs,
        plugin_type="mqtt",
    )

    publisher.run()

    record = logs.get_nowait()
    assert status.get_nowait() == "plugin mqtt start failed: refused"
    assert record["source"] == "plugin"
    assert record["message"] == "sink start failed"
    assert record["data"]["plugin"] == "mqtt"
    assert record["data"]["error"] == "refused"


def test_opcua_subscription_worker_logs_runtime_failure():
    outbox = Queue()
    logs = Queue()
    device = DeviceSpec(
        id=1,
        name="opc",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=1000,
        connection={"mode": "subscription"},
    )
    worker = OpcUaSubscriptionWorker(FailingSubscriptionDriver, device, [], outbox, log_queue=logs, retry_interval_s=0)

    worker.start()
    result = outbox.get(timeout=1)
    worker.stop()
    worker.join(timeout=1)

    record = logs.get_nowait()
    assert result.error == "subscription boom"
    assert record["level"] == "INFO"
    record = logs.get_nowait()
    assert record["level"] == "ERROR"
    assert record["message"] == "subscription failed"


def test_opcua_subscription_start_failure_logs_exception_details():
    outbox = Queue()
    logs = Queue()
    device = DeviceSpec(
        id=1,
        name="opc",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=1000,
        connection={"mode": "subscription", "endpoint": "opc.tcp://127.0.0.1:4840"},
    )
    worker = OpcUaSubscriptionWorker(EmptyMessageSubscriptionDriver, device, [], outbox, log_queue=logs, retry_interval_s=0)

    worker.start()
    record = logs.get(timeout=1)
    worker.stop()
    worker.join(timeout=1)

    assert record["message"] == "subscription start failed"
    assert record["data"]["error"] == ""
    assert record["data"]["exception_type"] == "RuntimeError"
    assert record["data"]["exception_repr"] == "RuntimeError()"
    assert "test_workers.py" in record["data"]["traceback"]
    assert "connect" in record["data"]["traceback"]
    assert "D:\\" not in record["data"]["traceback"]
    assert record["data"]["endpoint"] == "opc.tcp://127.0.0.1:4840"


def test_subscription_worker_retries_start_failure_until_broker_recovers():
    EventuallyConnectedSubscriptionDriver.attempts = 0
    EventuallyConnectedSubscriptionDriver.instances = []
    outbox = Queue()
    logs = Queue()
    device = DeviceSpec(
        id=1,
        name="RollGap",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=1000,
        connection={"host": "10.10.49.7", "port": 1883, "topic_filter": "rollgap/+/data"},
    )
    worker = OpcUaSubscriptionWorker(
        EventuallyConnectedSubscriptionDriver,
        device,
        [],
        outbox,
        log_queue=logs,
        retry_interval_s=0,
    )

    worker.start()
    records = []
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        while not logs.empty():
            records.append(logs.get_nowait())
        if any(record["message"] == "subscription started" for record in records):
            break
        time.sleep(0.01)
    worker.stop()
    worker.join(timeout=1)

    assert EventuallyConnectedSubscriptionDriver.attempts >= 2
    assert any(record["message"] == "subscription start failed" for record in records)
    assert any(record["message"] == "subscription retrying" for record in records)
    assert any(record["message"] == "subscription started" for record in records)
    start_failure = next(record for record in records if record["message"] == "subscription start failed")
    assert start_failure["data"]["driver"] == "mqtt"
    assert start_failure["data"]["host"] == "10.10.49.7"
    assert start_failure["data"]["port"] == 1883


def test_sink_publisher_republishes_cached_values_without_new_results():
    inbox = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="fake",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    inbox.put(
        ReadResult(
            device=device,
            timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=12.3,
                    quality="good",
                    error=None,
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                    node_id="ns=2;s=bar",
                ),
                TagResult(
                    name="bar",
                    address=2,
                    value=45.6,
                    quality="good",
                    error=None,
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                    node_id="ns=2;s=bar2",
                ),
            ],
            error=None,
        )
    )
    publisher = SinkPublisher(sink, MqttConfig(base_topic="plant"), inbox, stale_timeout_s=15)

    publisher.publish_once()
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 1, tzinfo=timezone.utc))
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 2, tzinfo=timezone.utc))

    data_messages = [message for message in sink.messages if message.topic == "plant/press/data"]
    status_messages = [message for message in sink.messages if message.topic == "plant/press/data/status"]
    assert len(data_messages) == 2
    assert len(status_messages) == 2
    assert [tag["value"] for tag in data_messages[0].payload["tags"]] == [12.3, 45.6]
    assert [tag["value"] for tag in data_messages[1].payload["tags"]] == [12.3, 45.6]
    assert [sensor["conn_status"] for sensor in status_messages[0].payload["sensors"]] == ["on", "on"]


def test_sink_publisher_publishes_stale_status_and_stops_cached_data_after_timeout():
    inbox = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    source_time = datetime(2026, 5, 16, tzinfo=timezone.utc)
    received_at = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
    inbox.put(
        ReadResult(
            device=device,
            timestamp=source_time,
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=12.3,
                    quality="good",
                    error=None,
                    timestamp=source_time,
                    node_id="bar",
                )
            ],
        )
    )
    publisher = SinkPublisher(
        sink,
        MqttConfig(base_topic="plant"),
        inbox,
        stale_timeout_s=5,
        status_publish_interval_s=60,
    )

    publisher.publish_once(now=received_at)
    publisher.publish_cached(received_at)
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 6, tzinfo=timezone.utc))

    assert [message.topic for message in sink.messages] == [
        "plant/press/data",
        "plant/press/data/status",
        "plant/press/data/status",
    ]
    status_payload = sink.messages[2].payload
    assert status_payload["sensors"] == [
        {
            "sensor_code": "bar",
            "conn_status": "off",
            "last_seen": "2026-05-16T00:00:00.000+00:00",
            "health_score": 0.0,
            "error_msg": "message timeout",
            "update_time": "2026-05-16T00:00:06.000+00:00",
        }
    ]


def test_sink_publisher_emits_stale_tag_update_for_runtime_ui():
    inbox = Queue()
    status = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    received_at = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
    inbox.put(
        ReadResult(
            device=device,
            timestamp=received_at,
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=12.3,
                    quality="good",
                    error=None,
                    timestamp=received_at,
                    node_id="bar",
                )
            ],
        )
    )
    publisher = SinkPublisher(
        sink,
        MqttConfig(base_topic="plant"),
        inbox,
        status_outbox=status,
        stale_timeout_s=5,
        status_publish_interval_s=60,
    )

    publisher.publish_once(now=received_at)
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 6, tzinfo=timezone.utc))

    events = [status.get_nowait(), status.get_nowait()]
    assert events[-1]["type"] == "tag_update"
    assert events[-1]["tag"] == "bar"
    assert events[-1]["quality"] == "stale"
    assert events[-1]["error"] == "message timeout"


def test_sink_publisher_republishes_status_on_configured_interval():
    inbox = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    received_at = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
    inbox.put(
        ReadResult(
            device=device,
            timestamp=received_at,
            tags=[
                TagResult(
                    name="bar",
                    address=2,
                    value=12.3,
                    quality="good",
                    error=None,
                    timestamp=received_at,
                    node_id="bar",
                )
            ],
        )
    )
    publisher = SinkPublisher(
        sink,
        MqttConfig(base_topic="plant"),
        inbox,
        stale_timeout_s=5,
        status_publish_interval_s=10,
    )

    publisher.publish_once(now=received_at)
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 6, tzinfo=timezone.utc))
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 12, tzinfo=timezone.utc))
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 16, tzinfo=timezone.utc))

    status_messages = [message for message in sink.messages if message.topic == "plant/press/data/status"]
    assert len(status_messages) == 2
    assert all(message.payload["sensors"][0]["conn_status"] == "off" for message in status_messages)


def test_sink_publisher_publishes_good_status_on_configured_interval():
    inbox = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    received_at = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
    inbox.put(
        ReadResult(
            device=device,
            timestamp=received_at,
            tags=[
                TagResult("bar", 2, 12.3, "good", None, received_at, node_id="bar"),
            ],
        )
    )
    publisher = SinkPublisher(
        sink,
        MqttConfig(base_topic="plant"),
        inbox,
        stale_timeout_s=30,
        status_publish_interval_s=10,
    )

    publisher.publish_once(now=received_at)
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 9, tzinfo=timezone.utc))
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 10, tzinfo=timezone.utc))
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 20, tzinfo=timezone.utc))

    status_messages = [message for message in sink.messages if message.topic == "plant/press/data/status"]
    assert [message.payload["sensors"][0]["conn_status"] for message in status_messages] == ["on", "on", "on"]


def test_sink_publisher_publishes_good_status_when_device_recovers_from_stale():
    inbox = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="press",
        driver_type="mqtt",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    first_time = datetime(2026, 5, 16, 0, 0, 0, tzinfo=timezone.utc)
    second_time = datetime(2026, 5, 16, 0, 0, 7, tzinfo=timezone.utc)
    publisher = SinkPublisher(
        sink,
        MqttConfig(base_topic="plant"),
        inbox,
        stale_timeout_s=5,
        status_publish_interval_s=60,
    )

    inbox.put(
        ReadResult(
            device=device,
            timestamp=first_time,
            tags=[
                TagResult("bar", 2, 12.3, "good", None, first_time, node_id="bar"),
            ],
        )
    )
    publisher.publish_once(now=first_time)
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 6, tzinfo=timezone.utc))
    inbox.put(
        ReadResult(
            device=device,
            timestamp=second_time,
            tags=[
                TagResult("bar", 2, 45.6, "good", None, second_time, node_id="bar"),
            ],
        )
    )
    publisher.publish_once(now=second_time)

    status_messages = [message for message in sink.messages if message.topic == "plant/press/data/status"]
    assert [message.payload["sensors"][0]["conn_status"] for message in status_messages] == ["off", "on"]
    assert status_messages[-1].payload["sensors"][0]["error_msg"] is None


def test_sink_publisher_splits_opcua_cached_values_by_phh_node_prefix():
    inbox = Queue()
    sink = FakeSink()
    device = DeviceSpec(
        id=2,
        name="opc",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=100,
        connection={},
    )
    inbox.put(
        ReadResult(
            device=device,
            timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
            tags=[
                TagResult(
                    name="PV_CUR_MOLD_N11",
                    address=0,
                    value=11,
                    quality="good",
                    error=None,
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                    node_id="ns=2;s=PHH01.MC01.PV_CUR_MOLD_N11",
                ),
                TagResult(
                    name="PV_CUR_MOLD_N11",
                    address=0,
                    value=88,
                    quality="good",
                    error=None,
                    timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
                    node_id="ns=2;s=PHH08.MC01.PV_CUR_MOLD_N11",
                ),
            ],
            error=None,
        )
    )
    publisher = SinkPublisher(sink, MqttConfig(base_topic="plant"), inbox)

    publisher.publish_once()
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 1, tzinfo=timezone.utc))

    assert [message.topic for message in sink.messages] == [
        "plant/opc/PHH01/data",
        "plant/opc/PHH01/data/status",
        "plant/opc/PHH08/data",
        "plant/opc/PHH08/data/status",
    ]
    data_messages = [message for message in sink.messages if not message.topic.endswith("/status")]
    status_messages = [message for message in sink.messages if message.topic.endswith("/status")]
    assert [message.payload["tags"][0]["value"] for message in data_messages] == [11, 88]
    assert [message.payload["sensors"][0]["sensor_code"] for message in status_messages] == [
        "PV_CUR_MOLD_N11",
        "PV_CUR_MOLD_N11",
    ]
