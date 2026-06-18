# Industrial Gateway

Web-based gateway for reading industrial devices over Modbus TCP, Modbus
Serial, or OPC UA and publishing device-level batch JSON messages to MQTT or
database sinks.

## What v1 Includes

- SQLite configuration store for devices, tags, and MQTT settings.
- Built-in driver registry with `modbus_tcp`, `modbus_serial`, and `opcua`.
- Built-in sink registry with `mqtt`.
- Driver polling worker and MQTT publishing worker connected by typed queues.
- Modbus reads are grouped by function and nearby address ranges, so many tags
  can be collected with fewer device requests.
- Web UI for device/tag/output settings, start/stop, and recent runtime logs.
- Device and tag lists support add, update, and delete from the GUI. Selecting a
  device shows its tags in the adjacent list.
- Output settings are shown under a Plugins tab. The current v1 plugin is MQTT
  by default, with PostgreSQL available in the DB-enabled build.
- Runtime logging uses a separate queue-backed logger thread. Button actions,
  saved/deleted data, driver reads, publish events, and errors can be shown in
  the Runtime tab when Debug logs is enabled.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On Linux or Raspberry Pi:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run Web Service

```powershell
$env:INDUSTRIAL_GATEWAY_ADMIN_USER="admin"
$env:INDUSTRIAL_GATEWAY_ADMIN_PASSWORD="change-me"
$env:INDUSTRIAL_GATEWAY_SESSION_SECRET="replace-with-random-secret"
industrial-gateway-web
```

The web service listens on `0.0.0.0:50137` by default. Use LAN or VPN access for
the first release. Do not expose this port directly to the public internet.

The app stores its SQLite configuration at:

```text
~/.industrial_gateway/gateway.sqlite3
```

## MQTT Payload

Messages are published to:

```text
<base_topic>/<device_name>/data
```

## Modbus Tag Types

Supported v1 tag data types:

```text
auto, bool, int16, uint16, int32, uint32, float32, float64, string
```

String tags use `word_count` to decide how many Modbus registers to decode.
Register tags also support `byte_order` and `word_order` values of `big` or
`little`.

Modbus block grouping reads across small address gaps by default. Holding and
input register reads are capped at 125 registers per request. Coil and discrete
input reads are capped at 2000 bits per request. You can set lower per-request
limits with `max_registers_per_read` or `max_bits_per_read` when a device needs
smaller reads.

Set `max_block_gap` in the device connection JSON to tune how aggressively the
driver reads through unused address gaps:

```json
{
  "host": "127.0.0.1",
  "port": 502,
  "unit_id": 1,
  "max_block_gap": 4,
  "max_registers_per_read": 125,
  "max_bits_per_read": 2000
}
```

## Output Plugins

The Plugins tab supports one active output plugin:

- `mqtt`: publishes the device batch JSON to MQTT.
- `postgresql`: inserts one row per tag into a PostgreSQL table.

PostgreSQL default table:

```text
gateway_tag_values
```

Inserted columns:

```text
device_id, device_name, tag_name, tag_address, value_json, quality, error, tag_timestamp
```

`value_json` stores the tag value as JSON text, so strings, numbers, booleans,
and null values can share the same schema. If `auto_create` is enabled, the sink
creates the table when it starts.

## OPC UA Driver

Use driver type `opcua` and set the device connection JSON with an endpoint:

```json
{"endpoint":"opc.tcp://127.0.0.1:4840/freeopcua/server/"}
```

Polling mode reads all configured nodes every device poll interval:

```json
{
  "endpoint": "opc.tcp://127.0.0.1:4840/freeopcua/server/",
  "mode": "polling"
}
```

Subscription mode creates OPC UA monitored items and publishes when a subscribed
node reports a data change:

```json
{
  "endpoint": "opc.tcp://127.0.0.1:4840/freeopcua/server/",
  "mode": "subscription",
  "subscription_interval_ms": 250
}
```

If `mode` is omitted, the app uses polling mode.

OPC UA tags use `function` value `opcua_node` and a NodeId such as:

```text
ns=2;s=Machine.Speed
```

For OPC UA, `data_type` can be `auto` to publish the value returned by the
server directly, or one of the explicit types above to coerce the value before
publishing.

Example payload:

```json
{
  "device": {"id": 7, "name": "boiler-plc"},
  "timestamp": "2026-05-16T02:30:00+00:00",
  "tags": [
    {
      "name": "temperature",
      "address": 40001,
      "value": 31.5,
      "quality": "good",
      "error": null,
      "timestamp": "2026-05-16T02:30:00+00:00"
    }
  ]
}
```

## Test

```bash
python -m pytest -q
```
