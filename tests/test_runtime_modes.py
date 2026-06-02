from queue import Queue

from industrial_gateway.models import DeviceSpec
from industrial_gateway.workers import OpcUaSubscriptionWorker


class FakeSubscriptionDriver:
    instances = []

    def __init__(self, device, tags):
        self.device = device
        self.tags = tags
        self.started = False
        self.stopped = False
        self.disconnected = False
        self.pump_count = 0
        FakeSubscriptionDriver.instances.append(self)

    def connect(self):
        self.started = True

    def start_subscription(self, emit):
        self.emit = emit

    def stop_subscription(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True

    def run_subscription_once(self, timeout=0.2):
        self.pump_count += 1
        if self.pump_count >= 2:
            raise KeyboardInterrupt


def test_opcua_subscription_worker_starts_and_stops_driver_subscription():
    FakeSubscriptionDriver.instances = []
    device = DeviceSpec(
        id=1,
        name="opc",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=1000,
        connection={"mode": "subscription"},
    )
    worker = OpcUaSubscriptionWorker(FakeSubscriptionDriver, device, [], Queue())

    try:
        worker.run()
    except KeyboardInterrupt:
        pass

    driver = FakeSubscriptionDriver.instances[0]
    assert driver.started is True
    assert driver.pump_count == 2
    assert driver.stopped is True
    assert driver.disconnected is True


def test_mqtt_device_uses_subscription_worker_in_runtime_manager(tmp_path):
    from industrial_gateway.models import SinkConfig, TagSpec
    from industrial_gateway.services.runtime_manager import RuntimeManager
    from industrial_gateway.store import ConfigStore

    class FakeSink:
        def __init__(self, config):
            self.config = config

    class FakePublisher:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def stop(self):
            pass

    class FakeRuntimeWorker:
        def __init__(self, driver_factory, device, tags, outbox, **kwargs):
            self.driver_factory = driver_factory
            self.device = device
            self.tags = tags
            self.outbox = outbox
            self.kwargs = kwargs

        def start(self):
            pass

        def stop(self):
            pass

    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()
    store.save_device(
        DeviceSpec(
            id=None,
            name="mqtt-in",
            driver_type="mqtt",
            enabled=True,
            poll_interval_ms=1000,
            connection={"host": "localhost", "port": 1883, "topic_filter": "curiot/+/data"},
        )
    )
    device_id = store.list_devices()[0].id
    store.save_tag(
        TagSpec(
            device_id=device_id,
            name="r",
            address=0,
            function="json_field",
            data_type="float32",
            node_id="r",
        )
    )
    store.save_sink_config(SinkConfig(sink_type="mqtt", enabled=False, config={}))
    manager = RuntimeManager(
        store,
        driver_registry={"mqtt": FakeRuntimeWorker},
        sink_registry={"mqtt": FakeSink},
        subscription_worker_class=FakeRuntimeWorker,
        publisher_class=FakePublisher,
    )

    snapshot = manager.start()

    assert snapshot["running"] is True
    assert len(manager.subscription_workers) == 1
    assert manager.snapshot()["runtime_tags"][0]["mode"] == "Subscription"
    manager.shutdown()
