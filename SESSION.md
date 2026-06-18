# Session Notes

## Current Context
- Project path: `C:\Users\mingyu.shin\docker\0_services\iot_gathering\iot_gathering`.
- Integrated workspace root: `C:\Users\mingyu.shin\docker`.
- This project is the Industrial Gateway service for Modbus TCP, Modbus Serial, OPC UA, MQTT input, and MQTT/database outputs.
- Web service listens on port `50137` by default.
- When starting Codex here, also read the root `C:\Users\mingyu.shin\docker\SESSION.md` for integrated service context.

## Repositories
- Git remote: `https://github.com/Rakctite/iot_gathering`.
- Main branch: `main`.
- Latest pushed commit: `08db5a5 Add MQTT stale status publishing`.

## Docker Image
- Last recorded integrated image: `203.228.107.184:5000/btx/iot_gathering:1.0.2`.
- Project deployment doc default image tag: `203.228.107.184:5000/btx/iot_gathering:1.0.0`.
- Planned next variants:
  - DB environment: PostgreSQL plugin enabled, topic sender later.
  - ARM/core environment: DB plugins excluded, hardware drivers and MQTT only.

## Latest State
- 2026-06-18: Working tree was clean and tracking `origin/main`.
- 2026-06-18: Latest change adds MQTT stale status publishing and related runtime status behavior.
- 2026-06-18: Full test suite passed with `104 passed, 13 warnings`.
- 2026-06-18: Started splitting DB plugins out of the default/core build. Default plugin profile exposes MQTT only; `INDUSTRIAL_GATEWAY_PLUGIN_PROFILE=postgres` exposes PostgreSQL in addition to MQTT.
- 2026-06-18: MSSQL support was fully removed from active code and README. The project keeps PostgreSQL as the only DB sink path.

## Open TODO
- Review whether root compose image tag `btx/iot_gathering:1.0.2` should be reflected in the project deployment docs.
- Review runtime defaults for `message_stale_timeout_s` and `status_publish_interval_s` in production settings.
- Decide whether the paho MQTT callback deprecation warning needs follow-up.
- Add topic sender as an optional PostgreSQL-backed feature after the plugin dependency split is stable.
- Decide final image tags for DB amd64 and ARM/core builds before registry push.

## Work Log

### 2026-06-18
- Compared uncommitted changes against previous commit `b2d69b1 Improve runtime resilience and CSV export`.
- Added MQTT plugin config fields: `message_stale_timeout_s` and `status_publish_interval_s`.
- Updated Modbus calls from `slave=unit_id` to `device_id=unit_id`.
- Added MQTT input connect/disconnect state handling.
- Added stale device detection, status topic publishing, status heartbeat publishing, and recovery status publishing in `SinkPublisher`.
- Updated MQTT sink handling so status payloads can publish directly to their message topic.
- Added tests for Modbus `device_id`, MQTT disconnect handling, MQTT status publishing, stale timeout, heartbeat, UI status updates, and recovery.
- Verified focused tests: `38 passed`.
- Verified full test suite: `104 passed, 13 warnings`.
- Committed and pushed `08db5a5 Add MQTT stale status publishing`.
- Recorded Docker image tags from root compose and project deployment docs.
- Removed `psycopg` and `pyodbc` from base runtime dependencies.
- Added `postgres` optional dependency extra with `psycopg[binary]`.
- Updated default plugin schema/registry to expose MQTT only.
- Added PostgreSQL plugin exposure when `INDUSTRIAL_GATEWAY_PLUGIN_PROFILE=postgres`.
- Removed MSSQL plugin exposure from schema/registry path.
- Removed MSSQL sink class, pyodbc connection path, SQL Server table DDL, and README MSSQL references.
- Added `Dockerfile.db-amd64` for PostgreSQL-enabled amd64 builds.
- Simplified default `Dockerfile` by removing DB/ODBC OS packages.
- Verified full test suite after plugin split: `108 passed, 13 warnings`.
- Verified full test suite after MSSQL removal: `108 passed, 13 warnings`.
- Cleaned the parent `0_services\iot_gathering` folder and removed legacy/runtime artifacts outside this Git repository: logs, docker test stores, copied SQLite DB files, SQL seed file, screenshots/images, `Roll`, and `publish_dummy`.
- Updated MQTT status publishing to follow the `ctm_modbus_gathering` contract: publish status to `<measurement_topic>/status` with payload `{"timestamp": ..., "sensors": [...]}` containing `sensor_code`, `conn_status`, `last_seen`, `health_score`, `error_msg`, and `update_time`.
- Verified full test suite after CTM-style status publishing: `108 passed, 13 warnings`.
