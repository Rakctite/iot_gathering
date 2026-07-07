from industrial_gateway.drivers.modbus import ModbusTcpDriver
from industrial_gateway.models import DeviceSpec, TagSpec


class FakeResponse:
    def __init__(self, registers=None, bits=None, error=False):
        self.registers = registers or []
        self.bits = bits or []
        self._error = error

    def isError(self):
        return self._error


class FakeModbusClient:
    def __init__(self):
        self.calls = []

    def read_holding_registers(self, address, *, count, device_id):
        self.calls.append(("holding", address, count, device_id))
        registers = {
            100: 25,
            101: 0x4148,
            102: 0,
            103: 0x0000,
            104: 0x4142,
            105: 0x4344,
        }
        return FakeResponse(registers=[registers[address + offset] for offset in range(count)])


class RangeModbusClient:
    def __init__(self):
        self.calls = []

    def read_holding_registers(self, address, *, count, device_id):
        self.calls.append(("holding", address, count, device_id))
        return FakeResponse(registers=list(range(address, address + count)))


class InputRegisterModbusClient:
    def __init__(self):
        self.calls = []

    def read_input_registers(self, address, *, count, device_id):
        self.calls.append(("input", address, count, device_id))
        return FakeResponse(registers=[123])


class SequentialInputRegisterModbusClient:
    def __init__(self):
        self.calls = []

    def read_input_registers(self, address, *, count, device_id):
        self.calls.append(("input", address, count, device_id))
        return FakeResponse(registers=list(range(1, count + 1)))


def test_modbus_driver_reads_contiguous_register_tags_in_one_block():
    device = DeviceSpec(
        id=1,
        name="line",
        driver_type="modbus_tcp",
        enabled=True,
        poll_interval_ms=1000,
        connection={"unit_id": 3},
    )
    tags = [
        TagSpec(name="speed", address=100, function="holding_register", data_type="uint16"),
        TagSpec(name="pressure", address=101, function="holding_register", data_type="float32"),
        TagSpec(
            name="batch_code",
            address=104,
            function="holding_register",
            data_type="string",
            word_count=2,
        ),
    ]
    driver = ModbusTcpDriver(device, tags)
    driver.client = FakeModbusClient()

    results = driver.read_tags()

    assert driver.client.calls == [("holding", 100, 6, 3)]
    assert [result.value for result in results] == [25, 12.5, "ABCD"]


def test_modbus_driver_keeps_separate_blocks_when_addresses_have_gap():
    device = DeviceSpec(
        id=1,
        name="line",
        driver_type="modbus_tcp",
        enabled=True,
        poll_interval_ms=1000,
        connection={"unit_id": 3},
    )
    tags = [
        TagSpec(name="first", address=100, function="holding_register", data_type="uint16"),
        TagSpec(name="second", address=110, function="holding_register", data_type="uint16"),
    ]
    driver = ModbusTcpDriver(device, tags)
    driver.client = FakeModbusClient()

    results = driver.read_tags()

    assert driver.client.calls == [("holding", 100, 1, 3), ("holding", 110, 1, 3)]
    assert results[0].quality == "good"
    assert results[1].quality == "bad"


def test_modbus_driver_splits_holding_register_blocks_at_125_registers():
    device = DeviceSpec(
        id=1,
        name="line",
        driver_type="modbus_tcp",
        enabled=True,
        poll_interval_ms=1000,
        connection={"unit_id": 3, "max_block_gap": 200},
    )
    tags = [
        TagSpec(name="first", address=0, function="holding_register", data_type="uint16"),
        TagSpec(name="last_in_first_read", address=124, function="holding_register", data_type="uint16"),
        TagSpec(name="first_in_second_read", address=125, function="holding_register", data_type="uint16"),
    ]
    driver = ModbusTcpDriver(device, tags)
    driver.client = RangeModbusClient()

    results = driver.read_tags()

    assert driver.client.calls == [("holding", 0, 125, 3), ("holding", 125, 1, 3)]
    assert [result.value for result in results] == [0, 124, 125]


def test_modbus_driver_passes_unit_id_as_device_id_for_input_registers():
    device = DeviceSpec(
        id=1,
        name="pressure",
        driver_type="modbus_serial",
        enabled=True,
        poll_interval_ms=1000,
        connection={"unit_id": 7},
    )
    tag = TagSpec(name="press1", address=0, function="input_register", data_type="int16", scale=0.1)
    driver = ModbusTcpDriver(device, [tag])
    driver.client = InputRegisterModbusClient()

    results = driver.read_tags()

    assert driver.client.calls == [("input", 0, 1, 7)]
    assert results[0].quality == "good"
    assert results[0].value == 12.3


def test_modbus_driver_adds_offset_after_scaling_register_value():
    device = DeviceSpec(
        id=1,
        name="pressure",
        driver_type="modbus_serial",
        enabled=True,
        poll_interval_ms=1000,
        connection={"unit_id": 7},
    )
    tag = TagSpec(
        name="press1",
        address=0,
        function="input_register",
        data_type="int16",
        scale=0.1,
        offset=-40.0,
    )
    driver = ModbusTcpDriver(device, [tag])
    driver.client = InputRegisterModbusClient()

    results = driver.read_tags()

    assert results[0].quality == "good"
    assert results[0].value == -27.7


def test_modbus_driver_uses_tag_unit_id_as_device_id_when_present():
    device = DeviceSpec(
        id=1,
        name="pressure",
        driver_type="modbus_serial",
        enabled=True,
        poll_interval_ms=1000,
        connection={"unit_id": 7},
    )
    tags = [
        TagSpec(name="slave_two", address=0, function="input_register", data_type="int16", unit_id=2),
        TagSpec(name="slave_three", address=1, function="input_register", data_type="int16", unit_id=3),
    ]
    driver = ModbusTcpDriver(device, tags)
    driver.client = InputRegisterModbusClient()

    results = driver.read_tags()

    assert driver.client.calls == [("input", 0, 1, 2), ("input", 1, 1, 3)]
    assert [result.quality for result in results] == ["good", "good"]


def test_modbus_driver_uses_value_count_to_calculate_register_count_for_serial_input_registers():
    device = DeviceSpec(
        id=1,
        name="pressure",
        driver_type="modbus_serial",
        enabled=True,
        poll_interval_ms=1000,
        connection={"unit_id": 7},
    )
    tags = [
        TagSpec(name="five_ints", address=10, function="input_register", data_type="int16", word_count=5),
        TagSpec(name="two_floats", address=20, function="input_register", data_type="float32", word_count=2),
    ]
    driver = ModbusTcpDriver(device, tags)
    driver.client = SequentialInputRegisterModbusClient()

    results = driver.read_tags()

    assert driver.client.calls == [("input", 10, 5, 7), ("input", 20, 4, 7)]
    assert results[0].value == [1, 2, 3, 4, 5]
    assert len(results[1].value) == 2
