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
