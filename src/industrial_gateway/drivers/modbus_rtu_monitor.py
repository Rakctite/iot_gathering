from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import Any

from industrial_gateway.drivers.modbus import _apply_scale, _decode_registers, _register_count
from industrial_gateway.models import TagResult


READ_FUNCTIONS = {
    1: "read_coils",
    2: "read_discrete_inputs",
    3: "read_holding_registers",
    4: "read_input_registers",
}
TAG_FUNCTIONS_BY_CODE = {
    1: "coil",
    2: "discrete_input",
    3: "holding_register",
    4: "input_register",
}


class ModbusRtuMonitorDriver:
    def __init__(self, device: Any, tags: list[Any]) -> None:
        self.device = device
        self.tags = tags
        self.serial_factory: Any | None = None
        self.monotonic: Any | None = None
        self.serial_port: Any | None = None

    def connect(self) -> None:
        self.serial_port = _open_serial(self.device.connection, self.serial_factory)

    def disconnect(self) -> None:
        if self.serial_port is not None:
            self.serial_port.close()
            self.serial_port = None

    def read_tags(self) -> list[Any]:
        if self.serial_port is None:
            raise RuntimeError("Modbus RTU monitor is not connected")
        pairs = _capture_request_response_pairs(
            self.serial_port,
            self.device.connection,
            monotonic=self.monotonic,
        )
        return _tag_results_from_pairs(self.device, self.tags, pairs, datetime.now(timezone.utc))


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
    result = probe_responses(connection, serial_factory=serial_factory, monotonic=monotonic)
    responses = result.get("responses")
    if result.get("status") == "ok" and isinstance(responses, list) and responses:
        return {**responses[0], **_connection_metadata(connection), "message": format_probe_result({**responses[0], **_connection_metadata(connection)})}
    return result


def probe_responses(
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
    responses_by_slave: dict[int, dict[str, Any]] = {}
    try:
        while monotonic() <= deadline:
            chunk = serial_port.read(256)
            if not chunk:
                if buffer:
                    found, error = _drain_response_frames(buffer)
                    last_error = error or last_error
                    responses_by_slave.update(found)
                if wait_s <= 0:
                    break
                continue
            buffer.extend(chunk)
            found, error = _drain_response_frames(buffer)
            last_error = error or last_error
            responses_by_slave.update(found)
        if responses_by_slave:
            return _responses_probe_result(connection, responses_by_slave)
        return timeout_probe_result(
            connection,
            bytes_seen=len(buffer),
            last_raw=bytes(buffer[-80:]),
            last_error=last_error,
        )
    finally:
        serial_port.close()


def _capture_request_response_pairs(
    serial_port: Any,
    connection: dict[str, Any],
    monotonic: Any | None = None,
) -> list[dict[str, Any]]:
    monotonic = monotonic or time.monotonic
    wait_s = float(connection.get("capture_wait_s", 5))
    deadline = monotonic() + wait_s
    buffer = bytearray()
    pending: dict[tuple[int, int], dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    while monotonic() <= deadline:
        chunk = serial_port.read(256)
        if chunk:
            buffer.extend(chunk)
        found = _drain_request_response_pairs(buffer, pending)
        pairs.extend(found)
        if not chunk and wait_s <= 0:
            break
    return pairs


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


def format_responses_probe_result(result: dict[str, Any]) -> str:
    lines = [
        f"status: {result.get('status', '')}",
        f"captured_responses: {result.get('captured_responses', 0)}",
        f"valid_slave_ids: {result.get('valid_slave_ids', [])}",
    ]
    for key in ("port", "baudrate", "parity", "stopbits", "bytesize", "captured_at"):
        if key in result:
            lines.append(f"{key}: {result[key]}")
    for response in result.get("responses", []):
        lines.extend(
            [
                "",
                f"[slave {response.get('slave_id')}]",
                f"function: {response.get('function')} {response.get('function_name')}",
            ]
        )
        for key in ("byte_count", "value", "raw_hex", "registers", "data_hex", "crc"):
            if key in response:
                lines.append(f"{key}: {response[key]}")
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


def _drain_response_frames(buffer: bytearray) -> tuple[dict[int, dict[str, Any]], str]:
    responses: dict[int, dict[str, Any]] = {}
    last_error = ""
    while buffer:
        frame, start, end, error = _first_response_frame_span(bytes(buffer))
        last_error = error or last_error
        if frame is None or start is None or end is None:
            if len(buffer) > 512:
                del buffer[:-512]
            return responses, last_error
        responses[int(frame["slave_id"])] = _with_response_value(frame)
        del buffer[:end]
    return responses, last_error


def _drain_request_response_pairs(
    buffer: bytearray,
    pending: dict[tuple[int, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    while buffer:
        frame, start, end, _error = _first_valid_frame_span(bytes(buffer))
        if frame is None or start is None or end is None:
            if len(buffer) > 512:
                del buffer[:-512]
            return pairs
        if _is_read_request(frame):
            pending[(int(frame["slave_id"]), int(frame["function"]))] = frame
        elif _is_read_response(frame):
            key = (int(frame["slave_id"]), int(frame["function"]))
            request = pending.pop(key, None)
            if request is not None:
                pairs.append({"request": request, "response": _with_response_value(frame)})
        del buffer[:end]
    return pairs


def _first_valid_frame_span(data: bytes) -> tuple[dict[str, Any] | None, int | None, int | None, str]:
    last_error = ""
    for start in range(len(data)):
        for end in range(start + 4, len(data) + 1):
            try:
                return parse_rtu_frame(data[start:end]), start, end, ""
            except ValueError as exc:
                last_error = str(exc)
                continue
    return None, None, None, last_error


def _first_response_frame_span(data: bytes) -> tuple[dict[str, Any] | None, int | None, int | None, str]:
    last_error = ""
    for start in range(len(data)):
        for end in range(start + 4, len(data) + 1):
            try:
                frame = parse_rtu_frame(data[start:end])
            except ValueError as exc:
                last_error = str(exc)
                continue
            if _is_read_response(frame):
                return frame, start, end, ""
    return None, None, None, last_error


def _is_read_response(frame: dict[str, Any]) -> bool:
    return frame.get("function") in READ_FUNCTIONS and "byte_count" in frame


def _is_read_request(frame: dict[str, Any]) -> bool:
    return frame.get("function") in READ_FUNCTIONS and "start_address" in frame and "quantity" in frame


def _with_response_value(frame: dict[str, Any]) -> dict[str, Any]:
    registers = frame.get("registers")
    if isinstance(registers, list) and len(registers) == 1:
        return {**frame, "value": registers[0]}
    return frame


def _tag_results_from_pairs(device: Any, tags: list[Any], pairs: list[dict[str, Any]], timestamp: datetime) -> list[TagResult]:
    latest_pairs: dict[tuple[int, str, int], dict[str, Any]] = {}
    for pair in pairs:
        request = pair["request"]
        function_name = TAG_FUNCTIONS_BY_CODE.get(int(request["function"]))
        if function_name is None:
            continue
        key = (int(request["slave_id"]), function_name, int(request["start_address"]))
        latest_pairs[key] = pair

    results: list[TagResult] = []
    default_unit_id = int(device.connection.get("unit_id", 1))
    for tag in tags:
        unit_id = int(tag.unit_id or default_unit_id)
        result = _tag_result_from_pairs(tag, unit_id, latest_pairs, timestamp)
        if result is None:
            result = TagResult(
                tag.name,
                tag.address,
                None,
                "bad",
                "tag was not observed in captured Modbus RTU traffic",
                timestamp,
                tag_group=tag.tag_group,
            )
        results.append(result)
    return results


def _tag_result_from_pairs(
    tag: Any,
    unit_id: int,
    latest_pairs: dict[tuple[int, str, int], dict[str, Any]],
    timestamp: datetime,
) -> TagResult | None:
    for (pair_unit_id, function_name, start_address), pair in latest_pairs.items():
        if pair_unit_id != unit_id or function_name != tag.function:
            continue
        response = pair["response"]
        registers = response.get("registers")
        if not isinstance(registers, list):
            continue
        quantity = int(pair["request"].get("quantity", len(registers)))
        if not start_address <= tag.address < start_address + quantity:
            continue
        offset = tag.address - start_address
        try:
            count = _register_count(tag)
            value = _decode_registers(registers[offset : offset + count], tag)
            value = _apply_scale(value, tag.scale, tag.offset)
            return TagResult(tag.name, tag.address, value, "good", None, timestamp, tag_group=tag.tag_group)
        except Exception as exc:
            return TagResult(tag.name, tag.address, None, "bad", str(exc), timestamp, tag_group=tag.tag_group)
    return None


def _with_probe_metadata(result: dict[str, Any], connection: dict[str, Any]) -> dict[str, Any]:
    enriched = {
        **result,
        **_connection_metadata(connection),
    }
    enriched["message"] = format_probe_result(enriched)
    return enriched


def _responses_probe_result(connection: dict[str, Any], responses_by_slave: dict[int, dict[str, Any]]) -> dict[str, Any]:
    responses = [responses_by_slave[slave_id] for slave_id in sorted(responses_by_slave)]
    result = {
        "status": "ok",
        **_connection_metadata(connection),
        "captured_responses": len(responses),
        "valid_slave_ids": [response["slave_id"] for response in responses],
        "responses": responses,
    }
    result["message"] = format_responses_probe_result(result)
    return result


def _connection_metadata(connection: dict[str, Any]) -> dict[str, Any]:
    return {
        "port": connection.get("port", "COM1"),
        "baudrate": int(connection.get("baudrate", 9600)),
        "parity": connection.get("parity", "N"),
        "stopbits": int(connection.get("stopbits", 1)),
        "bytesize": int(connection.get("bytesize", 8)),
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
