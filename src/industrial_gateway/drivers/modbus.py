from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from industrial_gateway.models import DeviceSpec, TagResult, TagSpec

MAX_REGISTER_READ_COUNT = 125
MAX_BIT_READ_COUNT = 2000


class ModbusTcpDriver:
    def __init__(self, device: DeviceSpec, tags: list[TagSpec]) -> None:
        self.device = device
        self.tags = tags
        self.client: Any | None = None

    def connect(self) -> None:
        try:
            from pymodbus.client import ModbusTcpClient
        except ImportError as exc:
            raise RuntimeError("pymodbus is required for Modbus TCP") from exc
        host = self.device.connection.get("host", "127.0.0.1")
        port = int(self.device.connection.get("port", 502))
        self.client = ModbusTcpClient(host=host, port=port)
        if not self.client.connect():
            raise RuntimeError(f"failed to connect Modbus TCP {host}:{port}")

    def disconnect(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def read_tags(self) -> list[TagResult]:
        return _read_tags_grouped(self.client, self.device, self.tags)


class ModbusSerialDriver:
    def __init__(self, device: DeviceSpec, tags: list[TagSpec]) -> None:
        self.device = device
        self.tags = tags
        self.client: Any | None = None

    def connect(self) -> None:
        try:
            from pymodbus.client import ModbusSerialClient
        except ImportError as exc:
            raise RuntimeError("pymodbus is required for Modbus Serial") from exc
        self.client = ModbusSerialClient(
            port=self.device.connection.get("port", "COM1"),
            baudrate=int(self.device.connection.get("baudrate", 9600)),
            parity=self.device.connection.get("parity", "N"),
            stopbits=int(self.device.connection.get("stopbits", 1)),
            bytesize=int(self.device.connection.get("bytesize", 8)),
            timeout=float(self.device.connection.get("timeout", 2.0)),
        )
        if not self.client.connect():
            raise RuntimeError(f"failed to connect Modbus Serial {self.device.connection.get('port', 'COM1')}")

    def disconnect(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def read_tags(self) -> list[TagResult]:
        return _read_tags_grouped(self.client, self.device, self.tags)


@dataclass(frozen=True)
class _ReadBlock:
    function: str
    start: int
    count: int
    tags: list[TagSpec]


def _read_tags_grouped(client: Any, device: DeviceSpec, tags: list[TagSpec]) -> list[TagResult]:
    if client is None:
        timestamp = datetime.now(timezone.utc)
        return [_bad(tag, timestamp, "Modbus client is not connected") for tag in tags]
    results_by_name: dict[str, TagResult] = {}
    max_block_gap = int(device.connection.get("max_block_gap", 4))
    max_counts = _max_counts_from_connection(device.connection)
    for block in _plan_blocks(tags, max_block_gap=max_block_gap, max_counts=max_counts):
        results_by_name.update(_read_block(client, device, block))
    return [results_by_name.get(tag.name) or _bad(tag, datetime.now(timezone.utc), "tag was not read") for tag in tags]


def _read_block(client: Any, device: DeviceSpec, block: _ReadBlock) -> dict[str, TagResult]:
    timestamp = datetime.now(timezone.utc)
    try:
        unit_id = int(device.connection.get("unit_id", 1))
        if block.function == "holding_register":
            response = client.read_holding_registers(block.start, count=block.count, slave=unit_id)
            if response.isError():
                return {tag.name: _bad(tag, timestamp, str(response)) for tag in block.tags}
            return _decode_register_block(response.registers, block, timestamp)
        if block.function == "input_register":
            response = client.read_input_registers(block.start, count=block.count, slave=unit_id)
            if response.isError():
                return {tag.name: _bad(tag, timestamp, str(response)) for tag in block.tags}
            return _decode_register_block(response.registers, block, timestamp)
        if block.function == "coil":
            response = client.read_coils(block.start, count=block.count, slave=unit_id)
            if response.isError():
                return {tag.name: _bad(tag, timestamp, str(response)) for tag in block.tags}
            return _decode_bit_block(response.bits, block, timestamp)
        if block.function == "discrete_input":
            response = client.read_discrete_inputs(block.start, count=block.count, slave=unit_id)
            if response.isError():
                return {tag.name: _bad(tag, timestamp, str(response)) for tag in block.tags}
            return _decode_bit_block(response.bits, block, timestamp)
        return {tag.name: _bad(tag, timestamp, f"unsupported function {tag.function}") for tag in block.tags}
    except Exception as exc:
        return {tag.name: _bad(tag, timestamp, str(exc)) for tag in block.tags}


def _plan_blocks(
    tags: list[TagSpec],
    max_block_gap: int = 4,
    max_counts: dict[str, int] | None = None,
) -> list[_ReadBlock]:
    max_counts = max_counts or {
        "holding_register": MAX_REGISTER_READ_COUNT,
        "input_register": MAX_REGISTER_READ_COUNT,
        "coil": MAX_BIT_READ_COUNT,
        "discrete_input": MAX_BIT_READ_COUNT,
    }
    grouped: dict[str, list[TagSpec]] = defaultdict(list)
    for tag in tags:
        grouped[tag.function].append(tag)
    blocks: list[_ReadBlock] = []
    for function, function_tags in grouped.items():
        max_count = max_counts[function]
        sorted_tags = sorted(function_tags, key=lambda tag: tag.address)
        current: list[TagSpec] = []
        start = 0
        end = 0
        for tag in sorted_tags:
            tag_count = _item_count(tag)
            tag_end = tag.address + tag_count
            if not current:
                current = [tag]
                start = tag.address
                end = tag_end
                continue
            next_end = max(end, tag_end)
            if tag.address <= end + max_block_gap and next_end - start <= max_count:
                current.append(tag)
                end = next_end
                continue
            blocks.append(_ReadBlock(function, start, end - start, current))
            current = [tag]
            start = tag.address
            end = tag_end
        if current:
            blocks.append(_ReadBlock(function, start, end - start, current))
    return blocks


def _max_counts_from_connection(connection: dict[str, Any]) -> dict[str, int]:
    register_limit = min(
        _positive_int(connection.get("max_registers_per_read"), MAX_REGISTER_READ_COUNT),
        MAX_REGISTER_READ_COUNT,
    )
    bit_limit = min(
        _positive_int(connection.get("max_bits_per_read"), MAX_BIT_READ_COUNT),
        MAX_BIT_READ_COUNT,
    )
    return {
        "holding_register": register_limit,
        "input_register": register_limit,
        "coil": bit_limit,
        "discrete_input": bit_limit,
    }


def _positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    parsed = int(value)
    if parsed < 1:
        raise ValueError("Modbus read limit must be at least 1")
    return parsed


def _decode_register_block(registers: list[int], block: _ReadBlock, timestamp: datetime) -> dict[str, TagResult]:
    results = {}
    for tag in block.tags:
        offset = tag.address - block.start
        count = _register_count(tag)
        try:
            value = _decode_registers(registers[offset : offset + count], tag)
            if isinstance(value, (int, float)):
                value = value * tag.scale
            results[tag.name] = TagResult(tag.name, tag.address, value, "good", None, timestamp, tag_group=tag.tag_group)
        except Exception as exc:
            results[tag.name] = _bad(tag, timestamp, str(exc))
    return results


def _decode_bit_block(bits: list[bool], block: _ReadBlock, timestamp: datetime) -> dict[str, TagResult]:
    results = {}
    for tag in block.tags:
        offset = tag.address - block.start
        try:
            results[tag.name] = TagResult(tag.name, tag.address, bool(bits[offset]), "good", None, timestamp, tag_group=tag.tag_group)
        except Exception as exc:
            results[tag.name] = _bad(tag, timestamp, str(exc))
    return results


def _item_count(tag: TagSpec) -> int:
    if tag.function in {"coil", "discrete_input"}:
        return 1
    return _register_count(tag)


def _register_count(tag: TagSpec) -> int:
    if tag.data_type == "string":
        return tag.word_count or 1
    if tag.data_type == "float64":
        return 4
    return 2 if tag.data_type in {"int32", "uint32", "float32"} else 1


def _decode_registers(registers: list[int], tag: TagSpec) -> int | float | bool:
    if len(registers) < _register_count(tag):
        raise ValueError(f"not enough registers for {tag.name}")
    if tag.data_type == "bool":
        return bool(registers[0])
    ordered = _apply_word_order(registers, tag)
    if tag.data_type == "int16":
        value = ordered[0]
        return value - 0x10000 if value & 0x8000 else value
    if tag.data_type == "uint16":
        return ordered[0]
    if tag.data_type == "string":
        return _decode_string(ordered, tag)
    raw = _registers_to_int(ordered)
    if tag.data_type == "int32":
        return raw - 0x100000000 if raw & 0x80000000 else raw
    if tag.data_type == "uint32":
        return raw
    if tag.data_type == "float32":
        return struct.unpack(">f", raw.to_bytes(4, "big"))[0]
    if tag.data_type == "float64":
        return struct.unpack(">d", raw.to_bytes(8, "big"))[0]
    raise ValueError(f"unsupported data type {tag.data_type}")


def _apply_word_order(registers: list[int], tag: TagSpec) -> list[int]:
    if tag.word_order == "little" and len(registers) > 1:
        return list(reversed(registers))
    return registers


def _registers_to_int(registers: list[int]) -> int:
    raw = 0
    for register in registers:
        raw = (raw << 16) | (register & 0xFFFF)
    return raw


def _decode_string(registers: list[int], tag: TagSpec) -> str:
    data = bytearray()
    for register in registers:
        high = (register >> 8) & 0xFF
        low = register & 0xFF
        if tag.byte_order == "little":
            data.extend([low, high])
        else:
            data.extend([high, low])
    return bytes(data).split(b"\x00", 1)[0].decode("ascii", errors="replace")


def _bad(tag: TagSpec, timestamp: datetime, error: str) -> TagResult:
    return TagResult(tag.name, tag.address, None, "bad", error, timestamp, tag_group=tag.tag_group)
