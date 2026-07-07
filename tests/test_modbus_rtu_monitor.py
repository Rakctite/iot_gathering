import pytest

from industrial_gateway.drivers.modbus_rtu_monitor import (
    ModbusRtuMonitorDriver,
    crc16_modbus,
    format_probe_result,
    parse_rtu_frame,
    probe_first_frame,
    timeout_probe_result,
)


def test_crc16_modbus_matches_known_read_response():
    frame_without_crc = bytes.fromhex("01 03 04 00 7B 00 2D")

    assert crc16_modbus(frame_without_crc) == 0x374A


def test_parse_rtu_read_holding_registers_response():
    result = parse_rtu_frame(bytes.fromhex("01 03 04 00 7B 00 2D 4A 37"))

    assert result["status"] == "ok"
    assert result["slave_id"] == 1
    assert result["function"] == 3
    assert result["function_name"] == "read_holding_registers_response"
    assert result["byte_count"] == 4
    assert result["registers"] == [123, 45]
    assert result["raw_hex"] == "01 03 04 00 7B 00 2D 4A 37"
    assert result["crc"] == "ok"


def test_parse_rtu_rejects_long_exception_like_noise_frame():
    frame = bytes.fromhex(
        "06 EA 3A C9 02 03 41 1B 08 50 60 DC F9 02 03 09 4B 16 1A 06 FF "
        "01 03 41 1B 08 50 60 DC CA 01 03 09 43 04 3B 07 F5 02 03 41 1B "
        "08 50 60 DC F9 02 03 09 4B 76 9E 3A F4 01 03 41 1B 08 50 60 DC "
        "CA 01 03 09 3B E4 68 32 FF 02 03 41 1B 08 50 60 DC F9 02 03 04 "
        "53 16 22 81 FF 01 03 41 1B"
    )

    with pytest.raises(ValueError, match="exception response"):
        parse_rtu_frame(frame)


def test_format_probe_result_includes_raw_and_decoded_values():
    text = format_probe_result(
        {
            "status": "ok",
            "port": "COM3",
            "baudrate": 9600,
            "parity": "N",
            "stopbits": 1,
            "bytesize": 8,
            "slave_id": 1,
            "function": 3,
            "function_name": "read_holding_registers_response",
            "byte_count": 4,
            "raw_hex": "01 03 04 00 7B 00 2D 4A 37",
            "registers": [123, 45],
            "crc": "ok",
            "captured_at": "2026-07-07T00:00:00+00:00",
        }
    )

    assert "status: ok" in text
    assert "raw_hex: 01 03 04 00 7B 00 2D 4A 37" in text
    assert "registers: [123, 45]" in text


def test_timeout_probe_result_contains_troubleshooting_hint():
    result = timeout_probe_result({"port": "COM3", "capture_wait_s": 5})

    assert result["status"] == "timeout"
    assert "no valid Modbus RTU frame" in result["message"]
    assert "baudrate/parity/RS485 A-B polarity/GND" in result["message"]


def test_timeout_probe_result_includes_rejected_raw_diagnostics():
    result = timeout_probe_result(
        {"port": "COM3", "capture_wait_s": 5},
        bytes_seen=4,
        last_raw=b"\x01\x03\x02\x2A",
        last_error="CRC mismatch",
    )

    assert result["bytes_seen"] == 4
    assert result["last_raw_hex"] == "01 03 02 2A"
    assert result["last_error"] == "CRC mismatch"
    assert "bytes_seen: 4" in result["message"]
    assert "last_raw_hex: 01 03 02 2A" in result["message"]
    assert "last_error: CRC mismatch" in result["message"]


def test_probe_first_frame_reads_without_writing():
    class FakeSerial:
        writes = []

        def __init__(self, *args, **kwargs):
            self.chunks = [b"\x01\x03\x04\x00\x7B\x00\x2D\x4A\x37"]

        def read(self, size=1):
            return self.chunks.pop(0) if self.chunks else b""

        def write(self, data):
            self.writes.append(data)
            return len(data)

        def close(self):
            pass

    result = probe_first_frame(
        {"port": "COM3", "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8, "capture_wait_s": 1},
        serial_factory=FakeSerial,
        monotonic=lambda: 0,
    )

    assert result["status"] == "ok"
    assert result["registers"] == [123, 45]
    assert result["port"] == "COM3"
    assert FakeSerial.writes == []


def test_monitor_driver_runtime_is_noop_until_continuous_collection_exists():
    driver = ModbusRtuMonitorDriver(device=None, tags=[])

    driver.connect()

    assert driver.read_tags() == []
