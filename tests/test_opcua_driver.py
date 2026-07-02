from industrial_gateway.drivers.opcua import OpcUaDriver
from industrial_gateway.models import DeviceSpec, TagSpec


class FakeOpcUaNode:
    def __init__(self, node_id, value):
        self.nodeid = node_id
        self.value = value

    async def read_value(self):
        return self.value


class FakeOpcUaClient:
    def __init__(self):
        self.connected = False
        self.node_ids = []
        self.subscription = None

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    def get_node(self, node_id):
        self.node_ids.append(node_id)
        values = {
            "ns=2;s=Machine.Speed": 123.4,
            "ns=2;s=Machine.State": "RUN",
        }
        return FakeOpcUaNode(node_id, values[node_id])

    async def create_subscription(self, publishing_interval_ms, handler):
        self.subscription = FakeSubscription(publishing_interval_ms, handler)
        return self.subscription


class DisconnectFailingOpcUaClient(FakeOpcUaClient):
    async def disconnect(self):
        raise RuntimeError("session already gone")


class FakeSubscription:
    def __init__(self, publishing_interval_ms, handler):
        self.publishing_interval_ms = publishing_interval_ms
        self.handler = handler
        self.nodes = []
        self.deleted = False

    async def subscribe_data_change(self, nodes):
        self.nodes = nodes
        return list(range(len(nodes)))

    async def delete(self):
        self.deleted = True


def test_opcua_driver_reads_tags_by_node_id():
    device = DeviceSpec(
        id=1,
        name="opc-server",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=1000,
        connection={"endpoint": "opc.tcp://127.0.0.1:4840/freeopcua/server/"},
    )
    tags = [
        TagSpec(name="speed", address=0, function="opcua_node", data_type="auto", node_id="ns=2;s=Machine.Speed"),
        TagSpec(name="state", address=0, function="opcua_node", data_type="string", node_id="ns=2;s=Machine.State"),
    ]
    driver = OpcUaDriver(device, tags)
    driver.client = FakeOpcUaClient()

    driver.connect()
    results = driver.read_tags()
    driver.disconnect()

    assert driver.client.node_ids == ["ns=2;s=Machine.Speed", "ns=2;s=Machine.State"]
    assert [result.value for result in results] == [123.4, "RUN"]
    assert all(result.quality == "good" for result in results)


def test_opcua_subscription_handler_emits_changed_tag_result():
    device = DeviceSpec(
        id=1,
        name="opc-server",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=1000,
        connection={"endpoint": "opc.tcp://127.0.0.1:4840/freeopcua/server/", "subscription_interval_ms": 250},
    )
    tags = [
        TagSpec(name="speed", address=0, function="opcua_node", data_type="float32", node_id="ns=2;s=Machine.Speed"),
        TagSpec(name="state", address=0, function="opcua_node", data_type="string", node_id="ns=2;s=Machine.State"),
    ]
    driver = OpcUaDriver(device, tags)
    driver.client = FakeOpcUaClient()
    emitted = []

    driver.connect()
    driver.start_subscription(lambda result: emitted.append(result))
    driver.client.subscription.handler.datachange_notification(
        FakeOpcUaNode("ns=2;s=Machine.Speed", 456.7),
        456.7,
        None,
    )
    driver.stop_subscription()
    driver.disconnect()

    assert driver.client.subscription.publishing_interval_ms == 250
    assert emitted[0].device.name == "opc-server"
    assert emitted[0].tags[0].name == "speed"
    assert emitted[0].tags[0].value == 456.7
    assert driver.client.subscription.deleted is True


def test_opcua_disconnect_closes_loop_even_when_client_disconnect_fails():
    device = DeviceSpec(
        id=1,
        name="opc-server",
        driver_type="opcua",
        enabled=True,
        poll_interval_ms=1000,
        connection={"endpoint": "opc.tcp://127.0.0.1:4840/freeopcua/server/"},
    )
    driver = OpcUaDriver(device, [])
    driver.client = DisconnectFailingOpcUaClient()

    driver.connect()
    loop = driver._loop

    driver.disconnect()

    assert loop.is_closed() is True
    assert driver._loop is None
    assert driver._subscription is None
