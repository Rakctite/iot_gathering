from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any


READ_FUNCTIONS = {
    1: "read_coils",
    2: "read_discrete_inputs",
    3: "read_holding_registers",
    4: "read_input_registers",
}


class ModbusRtuMonitorDriver:
    def __init__(self, device: Any, tags: list[Any]) -> None:
        self.device = device
        self.tags = tags

    def connect(self) -> None:
        return None

    def disconnect(self) -> None:
        return None

    def read_tags(self) -> list[Any]:
        return []


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def parse_rtu_frame(frame: bytes) -> dict[str, Any]:
    if len(frame) < 4:
        raise ValueError("Modbus RTU frame must be at least 4 bytes")
    expected_crc = crc16_modbus(frame[:-2])
    actual_crc = frame[-2] | (frame[-1] << 8)
    if expected_crc != actual_crc:
        raise ValueError(f"CRC mismatch: expected 0x{expected_crc:04X}, got 0x{actual_crc:04X}")

    slave_id = frame[0]
    function = frame[1]
    result: dict[str, Any] = {
        "status": "ok",
        "slave_id": slave_id,
        "function": function,
        "function_name": _function_name(function, frame),
        "raw_hex": _hex(frame),
        "length": len(frame),
        "crc": "ok",
    }
    if function & 0x80:
        if len(frame) != 5:
            raise ValueError("Modbus exception response must be exactly 5 bytes")
        result["exception_code"] = frame[2]
        return result
    if function in READ_FUNCTIONS and len(frame) >= 5:
        if len(frame) == 8:
            result.update(
                {
                    "start_address": _u16(frame[2], frame[3]),
                    "quantity": _u16(frame[4], frame[5]),
                }
            )
            return result
        byte_count = frame[2]
        data = frame[3:-2]
        if len(frame) != byte_count + 5:
            raise ValueError("Modbus read response length does not match byte count")
        result["byte_count"] = byte_count
        if len(data) == byte_count and function in {3, 4} and byte_count % 2 == 0:
            result["registers"] = [_u16(data[index], data[index + 1]) for index in range(0, len(data), 2)]
        elif len(data) == byte_count:
            result["data_hex"] = _hex(data)
        return result
    if function in {5, 6, 15, 16} and len(frame) >= 8:
        if len(frame) != 8:
            raise ValueError("Modbus write acknowledgement must be exactly 8 bytes")
        result["start_address"] = _u16(frame[2], frame[3])
        result["value"] = _u16(frame[4], frame[5])
        return result
    if function not in READ_FUNCTIONS:
        raise ValueError(f"unsupported Modbus function {function}")
    return result


def timeout_probe_result(
    connection: dict[str, Any],
    *,
    bytes_seen: int = 0,
    last_raw: bytes = b"",
    last_error: str = "",
) -> dict[str, Any]:
    wait_s = float(connection.get("capture_wait_s", 5))
    result = {
        "status": "timeout",
        "port": connection.get("port", "COM1"),
        "capture_wait_s": wait_s,
        "bytes_seen": bytes_seen,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    lines = [
        "status: timeout",
        f"message: no valid Modbus RTU frame captured within {wait_s:g} sec",
        f"bytes_seen: {bytes_seen}",
    ]
    if last_raw:
        result["last_raw_hex"] = _hex(last_raw)
        lines.append(f"last_raw_hex: {result['last_raw_hex']}")
    if last_error:
        result["last_error"] = last_error
        lines.append(f"last_error: {last_error}")
    lines.append("hint: check baudrate/parity/RS485 A-B polarity/GND/common line activity")
    result["message"] = "\n".join(lines)
    return result


def probe_first_frame(
    connection: dict[str, Any],
    serial_factory: Any | None = None,
    monotonic: Any | None = None,
) -> dict[str, Any]:
    monotonic = monotonic or time.monotonic
    wait_s = float(connection.get("capture_wait_s", 5))
    deadline = monotonic() + wait_s
    serial_port = _open_serial(connection, serial_factory)
    buffer = bytearray()
    last_error = ""
    try:
        while monotonic() <= deadline:
            chunk = serial_port.read(256)
            if not chunk:
                if buffer:
                    candidate, error = _first_response_frame(bytes(buffer))
                    last_error = error or last_error
                    if candidate is not None:
                        return _with_probe_metadata(candidate, connection)
                if wait_s <= 0:
                    break
                continue
            buffer.extend(chunk)
            candidate, error = _first_response_frame(bytes(buffer))
            last_error = error or last_error
            if candidate is not None:
                return _with_probe_metadata(candidate, connection)
        return timeout_probe_result(
            connection,
            bytes_seen=len(buffer),
            last_raw=bytes(buffer[-80:]),
            last_error=last_error,
        )
    finally:
        serial_port.close()


def format_probe_result(result: dict[str, Any]) -> str:
    lines = [
        f"status: {result.get('status', '')}",
    ]
    for key in ("port", "baudrate", "parity", "stopbits", "bytesize"):
        if key in result:
            lines.append(f"{key}: {result[key]}")
    for key in (
        "slave_id",
        "function",
        "function_name",
        "byte_count",
        "start_address",
        "quantity",
        "value",
        "raw_hex",
        "registers",
        "data_hex",
        "crc",
        "captured_at",
    ):
        if key in result:
            lines.append(f"{key}: {result[key]}")
    if result.get("message") and result.get("status") != "ok":
        lines.append(f"message: {result['message']}")
    return "\n".join(lines)


def _function_name(function: int, frame: bytes) -> str:
    if function & 0x80:
        return "exception_response"
    base = READ_FUNCTIONS.get(function)
    if base:
        return f"{base}_request" if len(frame) == 8 else f"{base}_response"
    return {
        5: "write_single_coil",
        6: "write_single_register",
        15: "write_multiple_coils",
        16: "write_multiple_registers",
    }.get(function, "unknown")


def _u16(high: int, low: int) -> int:
    return (high << 8) | low


def _hex(data: bytes) -> str:
    return " ".join(f"{byte:02X}" for byte in data)


def _open_serial(connection: dict[str, Any], serial_factory: Any | None) -> Any:
    if serial_factory is None:
        try:
            from serial import Serial
        except ImportError as exc:
            raise RuntimeError("pyserial is required for Modbus RTU monitor") from exc
        serial_factory = Serial
    return serial_factory(
        port=connection.get("port", "COM1"),
        baudrate=int(connection.get("baudrate", 9600)),
        parity=connection.get("parity", "N"),
        stopbits=int(connection.get("stopbits", 1)),
        bytesize=int(connection.get("bytesize", 8)),
        timeout=float(connection.get("timeout", 0.1)),
    )


def _first_valid_frame(data: bytes) -> tuple[dict[str, Any] | None, str]:
    last_error = ""
    for start in range(len(data)):
        for end in range(start + 4, len(data) + 1):
            try:
                return parse_rtu_frame(data[start:end]), ""
            except ValueError as exc:
                last_error = str(exc)
                continue
    return None, last_error


def _first_response_frame(data: bytes) -> tuple[dict[str, Any] | None, str]:
    last_error = ""
    for start in range(len(data)):
        for end in range(start + 4, len(data) + 1):
            try:
                frame = parse_rtu_frame(data[start:end])
            except ValueError as exc:
                last_error = str(exc)
                continue
            if _is_read_response(frame):
                return _with_response_value(frame), ""
    return None, last_error


def _is_read_response(frame: dict[str, Any]) -> bool:
    return frame.get("function") in READ_FUNCTIONS and "byte_count" in frame


def _with_response_value(frame: dict[str, Any]) -> dict[str, Any]:
    registers = frame.get("registers")
    if isinstance(registers, list) and len(registers) == 1:
        return {**frame, "value": registers[0]}
    return frame


def _with_probe_metadata(result: dict[str, Any], connection: dict[str, Any]) -> dict[str, Any]:
    enriched = {
        **result,
        "port": connection.get("port", "COM1"),
        "baudrate": int(connection.get("baudrate", 9600)),
        "parity": connection.get("parity", "N"),
        "stopbits": int(connection.get("stopbits", 1)),
        "bytesize": int(connection.get("bytesize", 8)),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    enriched["message"] = format_probe_result(enriched)
    return enriched
