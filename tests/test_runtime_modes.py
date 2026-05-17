from queue import Queue

from industrial_gateway.models import DeviceSpec, MqttConfig
from industrial_gateway.workers import OpcUaSubscriptionWorker


class FakeSubscriptionDriver:
    def __init__(self, device, tags):
        self.device = device
        self.tags = tags
        self.started = False
        self.stopped = False
        self.disconnected = False

    def connect(self):
        self.started = True

    def start_subscription(self, emit):
        self.emit = emit

    def stop_subscription(self):
        self.stopped = True

    def disconnect(self):
        self.disconnected = True


def test_opcua_subscription_worker_starts_and_stops_driver_subscription():
    device = DeviceSpec(
        id=1,
        name="opc",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=1000,
        connection={"mode": "subscription"},
    )
    worker = OpcUaSubscriptionWorker(FakeSubscriptionDriver, device, [], Queue())

    worker.start_once()
    worker.stop()

    assert worker.driver.started is True
    assert worker.driver.stopped is True
    assert worker.driver.disconnected is True
