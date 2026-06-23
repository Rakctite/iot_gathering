# Session Notes

## Current Context
- Project path: `C:\Users\mingyu.shin\docker\0_services\iot_gathering\iot_gathering`.
- Integrated workspace root: `C:\Users\mingyu.shin\docker`.
- This project is the Industrial Gateway service for Modbus TCP, Modbus Serial, OPC UA, MQTT input, and MQTT/database outputs.
- Web service listens on port `50200` by default.
- When starting Codex here, also read the root `C:\Users\mingyu.shin\docker\SESSION.md` for integrated service context.

## Repositories
- Git remote: `https://github.com/Rakctite/iot_gathering`.
- Main branch: `main`.
- Latest pushed commit before current route-level topic sender work: `789d284 Document session update discipline`.

## Session Discipline
- When Codex changes files in this project, update this `SESSION.md` in the same work session.
- Record the purpose of the change, key files touched, verification result, commit hash, and any remaining TODO.
- If work is done from another terminal, branch, or worktree, sync this file after the commit is merged or pushed to `main`.
- If the change affects integrated deployment behavior, also update the root `C:\Users\mingyu.shin\docker\SESSION.md`.

## Docker Image
- Last recorded integrated image: `203.228.107.184:5000/btx/iot_gathering:1.0.3`.
- Project deployment doc default image tag: `203.228.107.184:5000/btx/iot_gathering:1.0.3`.
- Planned next variants:
  - Keep the existing `1.0.3` tag as-is: default/core image without DB plugins.
  - From the next release onward, publish architecture-oriented tags instead of `db-amd64`: `amd` includes PostgreSQL DB plugin support, and `arm` excludes DB plugins for hardware driver plus MQTT use.

## Latest State
- 2026-06-18: Working tree was clean and tracking `origin/main`.
- 2026-06-18: Latest change adds MQTT stale status publishing and related runtime status behavior.
- 2026-06-18: Full test suite passed with `104 passed, 13 warnings`.
- 2026-06-18: Started splitting DB plugins out of the default/core build. Default plugin profile exposes MQTT only; `INDUSTRIAL_GATEWAY_PLUGIN_PROFILE=postgres` exposes PostgreSQL in addition to MQTT.
- 2026-06-18: MSSQL support was fully removed from active code and README. The project keeps PostgreSQL as the only DB sink path.
- 2026-06-18: Topic sender integration is being added inside `iot_gathering` as an optional PostgreSQL-backed MQTT responder. It must stay disabled in the core/ARM profile.
- 2026-06-22: Route-level topic sender request work is in progress. Dynamic topic settings are moving from the MQTT plugin to output routes.

## Open TODO
- Review whether root compose image tag `btx/iot_gathering:1.0.3` should be reflected in the project deployment docs.
- Review runtime defaults for `message_stale_timeout_s` and `status_publish_interval_s` in production settings.
- Decide whether the paho MQTT callback deprecation warning needs follow-up.
- Decide whether topic responder settings should later move from environment variables into the web UI/plugin settings.
- Apply the next-release image tag policy: keep `1.0.3` unchanged, then build future releases as `amd` with PostgreSQL included and `arm` without DB plugins.

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
- Added `TopicResponder`, an optional PostgreSQL-backed MQTT responder for topic center requests.
- The responder handles `C-S/request-topic` and `C-S/request-sensor_cd`, publishing to `S-C/request-topic/{mac}` and `S-C/request-sensor_cd/{mac}`.
- Runtime starts the responder only when `INDUSTRIAL_GATEWAY_TOPIC_RESPONDER_ENABLED=true` and `INDUSTRIAL_GATEWAY_PLUGIN_PROFILE` exposes PostgreSQL.
- Verified full test suite after topic responder integration: `.venv\Scripts\python.exe -m pytest` -> `113 passed, 13 warnings`.

### 2026-06-22
- Moved `dynamic_topic_enabled` and `mac_address` ownership from MQTT plugin settings to output route config.
- Added route-level topic resolution flow: `POST /api/plugin-routes/{route_id}/resolve-topic` requests topic/sensor metadata by MAC and stores `resolved_topic`, `resolved_sensor_count`, `resolved_error`, and `resolved_at` on the route.
- Added `topic_request_client.py` for one-shot MQTT topic sender requests using `C-S/request-topic` and `C-S/request-sensor_cd`.
- Updated runtime output route selection so a dynamic route publishes to stored `resolved_topic`; manual `topic` remains the fallback.
- Simplified `MqttSink` by removing global dynamic-topic request/rewrite behavior. The sink now publishes to either the message topic supplied by a route or the plugin base topic.
- Updated plugin route CSV import/export to include route-level MAC and resolved topic fields.
- Updated plugin UI: route form now has `Request topic by MAC`, `MAC address`, a `Request topic` button, read-only topic sender result display, and route list MAC column.
- Verified focused tests: `.venv\Scripts\python.exe -m pytest tests\test_mqtt_sink.py tests\test_plugin_forms.py tests\test_config_service.py tests\test_web_api.py tests\test_runtime_manager.py -q` -> `31 passed, 8 warnings`.
- Verified full test suite: `.venv\Scripts\python.exe -m pytest -q` -> `110 passed, 13 warnings`.
- Verified frontend syntax: `node --check src\industrial_gateway\web\static\app.js`.
- Added project version source `industrial_gateway.__version__`; current app/package version is `1.0.3`.
- Added `/api/app-info` so the web UI can display the application version.
- Added small version display next to the topbar `Industrial Gateway` title.
- Added Docker image version metadata through `IOT_GATHERING_VERSION`, `INDUSTRIAL_GATEWAY_VERSION`, and `org.opencontainers.image.version` in both runtime Dockerfiles.
- Changed the default web service port from `50137` to `50200` because Windows reserved `50137` in the excluded TCP port range.
- Updated the Devices tab layout: Device and New Tag forms now share a narrow left column; the right side shows a wider Devices table with group/name/driver/endpoint/mode and a separate Tags panel.
- Removed Tags CSV import/export controls from the UI and removed Output Route CSV import/export controls from the plugin UI. Device CSV and plugin CSV controls remain.
- Added MQTT plugin settings for topic sender refresh policy: `topic_request_on_start` and `topic_refresh_interval_s`.
- Runtime now uses the MQTT plugin refresh policy to request enabled dynamic route topics from topic sender on start and periodically refresh them while running. Route MAC ownership remains on output routes.
- Updated app/package/Docker default image version to `1.0.3` for the next registry build.
- Committed and pushed `b3273f2 Add route topic refresh and release 1.0.3`.
- Built and pushed Docker image `203.228.107.184:5000/btx/iot_gathering:1.0.3`.
- Pushed registry digest: `sha256:9439276a5ecc8bc88e8dac383d0861b4dfcffebab4d99eef85370a1c7dbbc45e`.
- Built and pushed DB amd64 image `203.228.107.184:5000/btx/iot_gathering:1.0.3-db-amd64`.
- Pushed DB amd64 registry digest: `sha256:4e2de43f00cda3063df4a18ebdae10942093a54f1fb218e37a72e578435a1f44`.
- Decided not to retag or rebuild `1.0.3`: it remains the DB-free default/core image. Starting with the next version, use architecture-oriented tags where `amd` includes PostgreSQL DB plugin support and `arm` excludes DB plugins.
- Updated Modbus tag count behavior for ctm replacement testing: API/UI now use `count` as the value count alias for existing `word_count` storage, Modbus reads use `data_type` word size multiplied by `count`, and multi-value reads return lists.
- Updated the tag form so Modbus devices hide `NodeId`, show `Count`, and display data type labels with byte/word sizes.
- Verified focused tests: `.venv\Scripts\python.exe -m pytest tests\test_modbus_driver.py tests\test_config_service.py tests\test_web_static.py tests\test_web_api.py -q` -> `29 passed, 10 warnings`.
- Renamed the Modbus `unit_id` connection label to `Device ID (Slave ID)` in the UI while keeping the internal key as `unit_id` for compatibility.
- Updated the Devices tab layout so the Tag form sits beside the Devices table, with the Tags table below.
- Added a Tags view toggle: `View all` shows all tags sorted by group/name with normal paging, and `Sort by group` restores the group-by-group paging mode.
- Verified full test suite after the UI changes: `.venv\Scripts\python.exe -m pytest -q` -> `116 passed, 14 warnings`; `node --check src\industrial_gateway\web\static\app.js` passed.
- Refined the Devices tab layout again: Device and Tag forms now sit side by side, Devices and Tags lists sit to the right with the device list scrolling after five rows, and `View all` now loads tags from every device with a Device column.
- Moved Modbus `Device ID (Slave ID)` from device connection settings to tag settings by adding `TagSpec.unit_id` and `tags.unit_id`; Modbus reads now group requests by function and tag-level unit id, falling back to legacy device `unit_id` when a tag has none.
- Verified full test suite after tag-level slave id changes: `.venv\Scripts\python.exe -m pytest -q` -> `118 passed, 14 warnings`; `node --check src\industrial_gateway\web\static\app.js` passed.
- Increased the Devices tab tag list page size from 12 to 21 rows.
- Updated Runtime tab table sizing so sparse runtime tag pages keep the maximum panel height with empty space instead of stretching rows.
- Updated Plugins tab layout to mirror the Devices tab: Output Plugin and Output Routes forms sit side by side, with Route List in a narrower right panel.
- Added MQTT Output Route support for `system_heartbeat`: selecting `System Heartbeat` as the route device publishes `SYSTEM` status heartbeats to the resolved route topic plus `/status`.
- Heartbeat routes reuse existing topic sender MAC resolution/refresh, publish telegraf-compatible status timestamps, and stay excluded from normal device/tag route matching.
- Verified after heartbeat route changes: `.venv\Scripts\python.exe -m pytest -q` -> `121 passed, 14 warnings`; `node --check src\industrial_gateway\web\static\app.js` passed.
