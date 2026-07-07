# Modbus RTU Monitor First Frame Probe Design

## Goal

Add a receive-only Modbus RTU monitor driver option for authorized RS-485 lines. The initial scope is a single UI probe action: using the device form's current serial settings, capture the first valid Modbus RTU frame, verify CRC, parse basic frame details, and show the raw and decoded result in a message box.

## Scope

The feature adds a new driver type named `modbus_rtu_monitor`. It does not transmit any bytes and does not poll slaves. The probe opens the configured serial port in read-only behavior at the application layer, reads incoming bytes for a bounded wait period, finds the first CRC-valid RTU frame, and returns a human-readable result.

Continuous passive tag collection and request/response matching are intentionally out of scope for this first implementation. The existing `modbus_serial` driver remains the active polling driver.

## UI

The device editor shows the same serial fields used by Modbus serial devices, plus `Capture wait sec`. For `modbus_rtu_monitor` devices it also shows:

- `Read first frame` button
- `First frame result` readonly textarea

Clicking the button sends the current form values to a probe API without requiring the user to save the device first. The textarea is updated with the returned text. Errors are also shown in the textarea so field technicians can diagnose baudrate, parity, wiring, or line activity issues.

## API

Add `POST /api/devices/modbus-rtu-monitor/probe`.

Request body:

```json
{
  "connection": {
    "port": "COM3",
    "baudrate": 9600,
    "parity": "N",
    "stopbits": 1,
    "bytesize": 8,
    "timeout": 0.1,
    "capture_wait_s": 5
  }
}
```

Response body contains structured values and a preformatted `message` string for the UI textarea.

## Parser

The parser validates Modbus RTU CRC16 and classifies common frame shapes:

- read request for function `01`, `02`, `03`, `04`
- read response for function `01`, `02`, `03`, `04`
- write single request/response for function `05`, `06`
- write multiple request/response for function `15`, `16`
- Modbus exception response

Unknown CRC-valid frames still return `status: ok` with raw hex, slave id, function code, length, and CRC state.

## Capture

The capture loop uses `pyserial` to read bytes only. It groups bytes by RTU silent interval derived from baudrate and framing bits, while also tolerating serial adapters that deliver chunks unevenly. Each candidate frame is checked for minimum length and CRC validity. The first valid frame wins.

If no valid frame arrives before `capture_wait_s`, the API returns a timeout result with a troubleshooting hint.

## Errors

Expected errors include missing `pyserial`, serial open failure, timeout, invalid serial settings, or no CRC-valid frame. These return clear messages to the UI. The feature must never send data to the serial port.

## Testing

Unit tests cover CRC, frame parsing, timeout formatting, connection schema, API authentication, and UI wiring. Serial hardware is abstracted behind an injectable serial factory so tests do not need a physical port.
