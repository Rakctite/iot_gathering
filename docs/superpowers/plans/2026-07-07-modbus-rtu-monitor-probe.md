# Modbus RTU Monitor Probe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a receive-only Modbus RTU monitor probe that captures the first CRC-valid frame using the device form's current serial settings and displays raw plus decoded details.

**Architecture:** Create a focused `industrial_gateway.drivers.modbus_rtu_monitor` module for CRC, parsing, formatting, and receive-only capture. Expose the driver type through config schema, add one authenticated probe API endpoint, and add device-form UI controls only for `modbus_rtu_monitor`.

**Tech Stack:** Python 3.11, FastAPI, pyserial, pytest, vanilla JavaScript.

---

## File Structure

- Create `src/industrial_gateway/drivers/modbus_rtu_monitor.py`: CRC, frame parser, message formatter, and serial capture loop.
- Modify `src/industrial_gateway/config_schema.py`: add `modbus_rtu_monitor` connection fields.
- Modify `src/industrial_gateway/drivers/__init__.py`: export `ModbusRtuMonitorDriver`.
- Modify `src/industrial_gateway/web/api.py`: add `POST /api/devices/modbus-rtu-monitor/probe`.
- Modify `src/industrial_gateway/web/static/app.js`: render result textarea and probe button for monitor devices, post current form values.
- Modify tests in `tests/test_modbus_rtu_monitor.py`, `tests/test_connection_forms.py`, `tests/test_web_api.py`, and `tests/test_web_static.py`.

### Task 1: Parser and Formatter

**Files:**
- Create: `src/industrial_gateway/drivers/modbus_rtu_monitor.py`
- Test: `tests/test_modbus_rtu_monitor.py`

- [ ] **Step 1: Write failing tests for CRC, read response parsing, and timeout formatting**

```python
from industrial_gateway.drivers.modbus_rtu_monitor import (
    crc16_modbus,
    format_probe_result,
    parse_rtu_frame,
    timeout_probe_result,
)


def test_crc16_modbus_matches_known_read_response():
    frame_without_crc = bytes.fromhex("01 03 04 00 7B 00 2D")

    assert crc16_modbus(frame_without_crc) == 0x31CA


def test_parse_rtu_read_holding_registers_response():
    result = parse_rtu_frame(bytes.fromhex("01 03 04 00 7B 00 2D CA 31"))

    assert result["status"] == "ok"
    assert result["slave_id"] == 1
    assert result["function"] == 3
    assert result["function_name"] == "read_holding_registers_response"
    assert result["byte_count"] == 4
    assert result["registers"] == [123, 45]
    assert result["raw_hex"] == "01 03 04 00 7B 00 2D CA 31"
    assert result["crc"] == "ok"


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
            "raw_hex": "01 03 04 00 7B 00 2D CA 31",
            "registers": [123, 45],
            "crc": "ok",
            "captured_at": "2026-07-07T00:00:00+00:00",
        }
    )

    assert "status: ok" in text
    assert "raw_hex: 01 03 04 00 7B 00 2D CA 31" in text
    assert "registers: [123, 45]" in text


def test_timeout_probe_result_contains_troubleshooting_hint():
    result = timeout_probe_result({"port": "COM3", "capture_wait_s": 5})

    assert result["status"] == "timeout"
    assert "no valid Modbus RTU frame" in result["message"]
    assert "baudrate/parity/RS485 A-B polarity/GND" in result["message"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/test_modbus_rtu_monitor.py -v`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement parser and formatter**

Add `crc16_modbus(frame: bytes) -> int`, `parse_rtu_frame(frame: bytes) -> dict`, `format_probe_result(result: dict) -> str`, and `timeout_probe_result(connection: dict) -> dict`. Reject frames shorter than 4 bytes, verify CRC little-endian trailer, parse common read responses, requests, write responses, and exceptions.

- [ ] **Step 4: Run tests and verify pass**

Run: `pytest tests/test_modbus_rtu_monitor.py -v`

Expected: PASS.

### Task 2: Receive-Only Serial Capture

**Files:**
- Modify: `src/industrial_gateway/drivers/modbus_rtu_monitor.py`
- Test: `tests/test_modbus_rtu_monitor.py`

- [ ] **Step 1: Write failing tests for injected serial capture**

```python
from industrial_gateway.drivers.modbus_rtu_monitor import probe_first_frame


class FakeSerial:
    writes = []

    def __init__(self, *args, **kwargs):
        self.chunks = [b"\x01\x03\x04\x00\x7B\x00\x2D\xCA\x31"]
        self.closed = False

    def read(self, size=1):
        return self.chunks.pop(0) if self.chunks else b""

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def close(self):
        self.closed = True


def test_probe_first_frame_reads_without_writing():
    result = probe_first_frame(
        {"port": "COM3", "baudrate": 9600, "parity": "N", "stopbits": 1, "bytesize": 8, "capture_wait_s": 1},
        serial_factory=FakeSerial,
        monotonic=lambda: 0,
    )

    assert result["status"] == "ok"
    assert result["registers"] == [123, 45]
    assert FakeSerial.writes == []
```

- [ ] **Step 2: Run targeted test and verify failure**

Run: `pytest tests/test_modbus_rtu_monitor.py::test_probe_first_frame_reads_without_writing -v`

Expected: FAIL because `probe_first_frame` is missing.

- [ ] **Step 3: Implement capture loop**

Implement `probe_first_frame(connection, serial_factory=None, monotonic=None)`. Import `serial.Serial` only inside the function when no factory is injected. Open the port with configured `baudrate`, `parity`, `stopbits`, `bytesize`, and small read timeout. Read bytes until `capture_wait_s`, parse accumulated candidates, and return the first CRC-valid parsed result with connection metadata and `captured_at`.

- [ ] **Step 4: Run tests and verify pass**

Run: `pytest tests/test_modbus_rtu_monitor.py -v`

Expected: PASS.

### Task 3: Schema and API

**Files:**
- Modify: `src/industrial_gateway/config_schema.py`
- Modify: `src/industrial_gateway/web/api.py`
- Test: `tests/test_connection_forms.py`
- Test: `tests/test_web_api.py`

- [ ] **Step 1: Write failing schema and API tests**

Add to `tests/test_connection_forms.py`:

```python
def test_modbus_rtu_monitor_connection_form_uses_serial_probe_fields():
    fields = connection_fields_for_driver("modbus_rtu_monitor")

    assert [field.key for field in fields] == [
        "port",
        "baudrate",
        "parity",
        "stopbits",
        "bytesize",
        "timeout",
        "capture_wait_s",
    ]
    assert default_connection_for_driver("modbus_rtu_monitor")["capture_wait_s"] == 5
```

Add to `tests/test_web_api.py`:

```python
def test_modbus_rtu_monitor_probe_endpoint_is_protected(tmp_path):
    app = create_app(tmp_path / "gateway.sqlite3", session_secret="secret")
    client = TestClient(app)

    response = client.post("/api/devices/modbus-rtu-monitor/probe", json={"connection": {}})

    assert response.status_code == 401
```

- [ ] **Step 2: Run targeted tests and verify failure**

Run: `pytest tests/test_connection_forms.py::test_modbus_rtu_monitor_connection_form_uses_serial_probe_fields tests/test_web_api.py::test_modbus_rtu_monitor_probe_endpoint_is_protected -v`

Expected: schema test FAIL, API test may FAIL with 404.

- [ ] **Step 3: Implement schema and API route**

Add `_SERIAL_FIELDS` shared tuple in `config_schema.py`, define `modbus_rtu_monitor` fields with capture wait and without active polling limits. In `api.py`, import `probe_first_frame` and add an authenticated endpoint returning `probe_first_frame(payload.get("connection") or {})`.

- [ ] **Step 4: Run targeted tests and verify pass**

Run: `pytest tests/test_connection_forms.py tests/test_web_api.py -v`

Expected: PASS.

### Task 4: UI Wiring

**Files:**
- Modify: `src/industrial_gateway/web/static/app.js`
- Test: `tests/test_web_static.py`

- [ ] **Step 1: Write failing static UI test**

Add to `tests/test_web_static.py`:

```python
def test_modbus_rtu_monitor_device_form_has_probe_controls():
    script = (Path(__file__).parents[1] / "src" / "industrial_gateway" / "web" / "static" / "app.js").read_text()

    assert "isModbusDriver(driverType)" in script
    assert "isModbusRtuMonitorDriver" in script
    assert "Read first frame" in script
    assert "First frame result" in script
    assert "/api/devices/modbus-rtu-monitor/probe" in script
    assert "probeModbusRtuMonitor" in script
```

- [ ] **Step 2: Run targeted test and verify failure**

Run: `pytest tests/test_web_static.py::test_modbus_rtu_monitor_device_form_has_probe_controls -v`

Expected: FAIL because UI helpers are missing.

- [ ] **Step 3: Implement UI controls**

Add `isModbusRtuMonitorDriver(driverType)`, include it in `isModbusDriver`, render textarea and button only for `modbus_rtu_monitor`, and implement `probeModbusRtuMonitor(form)` to read current connection fields, call the probe endpoint, and put `result.message` into `connection_probe_result`.

- [ ] **Step 4: Run static tests and verify pass**

Run: `pytest tests/test_web_static.py -v`

Expected: PASS.

### Task 5: Final Verification

**Files:**
- All modified files

- [ ] **Step 1: Run complete test suite**

Run: `pytest -q`

Expected: PASS.

- [ ] **Step 2: Inspect git diff**

Run: `git diff --stat && git diff -- docs/superpowers/plans/2026-07-07-modbus-rtu-monitor-probe.md src/industrial_gateway/drivers/modbus_rtu_monitor.py src/industrial_gateway/config_schema.py src/industrial_gateway/web/api.py src/industrial_gateway/web/static/app.js tests/test_modbus_rtu_monitor.py tests/test_connection_forms.py tests/test_web_api.py tests/test_web_static.py`

Expected: only intended files changed.

- [ ] **Step 3: Commit implementation**

Run:

```bash
git add docs/superpowers/plans/2026-07-07-modbus-rtu-monitor-probe.md src/industrial_gateway/drivers/modbus_rtu_monitor.py src/industrial_gateway/config_schema.py src/industrial_gateway/web/api.py src/industrial_gateway/web/static/app.js tests/test_modbus_rtu_monitor.py tests/test_connection_forms.py tests/test_web_api.py tests/test_web_static.py
git commit -m "feat: add modbus rtu monitor probe"
```
