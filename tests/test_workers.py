from datetime import datetime, timezone
from queue import Queue

from industrial_gateway.models import DeviceSpec, MqttConfig, ReadResult, TagResult
from industrial_gateway.workers import DriverPoller, SinkPublisher


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
    assert logs.empty()


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
    publisher = SinkPublisher(sink, MqttConfig(base_topic="plant"), inbox)

    publisher.publish_once()
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 1, tzinfo=timezone.utc))
    publisher.publish_cached(datetime(2026, 5, 16, 0, 0, 2, tzinfo=timezone.utc))

    assert len(sink.messages) == 2
    assert [tag["value"] for tag in sink.messages[0].payload["tags"]] == [12.3, 45.6]
    assert [tag["value"] for tag in sink.messages[1].payload["tags"]] == [12.3, 45.6]


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

    assert [message.topic for message in sink.messages] == ["plant/opc/PHH01/data", "plant/opc/PHH08/data"]
    assert [message.payload["tags"][0]["value"] for message in sink.messages] == [11, 88]
