# Industrial Gateway Web UI and Daemon Design

## Goal

Split the current PySide6-only Industrial Gateway into a background gateway service with a browser-based admin UI. The first usable target is LAN/VPN operation, not direct public internet exposure. The web UI must let an operator remotely change device, tag, and output settings, start and stop collection, and watch runtime status.

## Chosen Approach

Use one Python service process that owns:

- FastAPI HTTP API.
- Browser UI static assets.
- WebSocket runtime event stream.
- Gateway runtime manager for pollers, OPC UA subscription workers, sink publishing, status queues, and logging.

This keeps the first migration small because the existing code already has reusable runtime pieces (`DriverPoller`, `OpcUaSubscriptionWorker`, `SinkPublisher`, `ConfigStore`). The main refactor is to move business logic out of `MainWindow` into service-layer modules that both tests and the API can call.

## Initial Network Model

The service will bind to `0.0.0.0:50137` so machines on the same LAN or VPN can connect. Direct internet exposure is out of scope for the first implementation. Public access later requires a separate deployment pass for HTTPS, reverse proxy, firewall rules, and stronger account management.

## Authentication

The first version will require login before any settings or runtime controls are available.

- One administrator account is enough for the first release.
- Credentials are configured locally, preferably through environment variables or a local config file outside git.
- Passwords are not stored in plaintext if persisted.
- Auth protects REST APIs, WebSocket connections, and static UI routes that expose the admin app.
- No unauthenticated setting mutation or runtime control endpoint is allowed.

## Service Boundaries

### Runtime Manager

Add a `RuntimeManager` service that replaces the runtime ownership currently inside `MainWindow`.

Responsibilities:

- Start and stop gateway collection.
- Own result, status, and log queues.
- Start `DriverPoller`, `OpcUaSubscriptionWorker`, and `SinkPublisher`.
- Track whether runtime is running.
- Track current device count, runtime tag status, OPC UA server status, and recent log lines.
- Apply health-check interval changes.
- Provide snapshots for HTTP status endpoints.
- Publish status/log/tag events to WebSocket subscribers.

The runtime manager must guard start/stop with a lock so concurrent API calls cannot create duplicate worker sets.

### Config Service

Add a service layer over `ConfigStore`.

Responsibilities:

- Device CRUD.
- Tag CRUD.
- Sink plugin get/save/select.
- Driver-specific connection normalization and validation.
- Plugin config normalization.
- CSV import/export behavior currently embedded in the Qt window.

The API should not reach into Qt form helpers directly. Any shared normalization currently in `gui.connection_forms` or `gui.plugin_forms` should move to UI-independent modules before the web API depends on it.

### Web API

Add FastAPI endpoints for:

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/session`
- `GET /api/devices`
- `POST /api/devices`
- `PUT /api/devices/{device_id}`
- `DELETE /api/devices/{device_id}`
- `GET /api/devices/{device_id}/tags`
- `POST /api/devices/{device_id}/tags`
- `PUT /api/tags/{tag_id}`
- `DELETE /api/tags/{tag_id}`
- `GET /api/plugins`
- `GET /api/plugins/{sink_type}`
- `PUT /api/plugins/{sink_type}`
- `POST /api/runtime/start`
- `POST /api/runtime/stop`
- `GET /api/runtime/status`
- `WS /api/runtime/events`

The API should return structured JSON errors with a stable `error` string and human-readable `message`.

## Web UI Scope

The first web UI should replace the operational parts of the current desktop UI:

- Login page.
- Devices list.
- Device editor with driver-specific connection fields.
- Tags table for the selected device.
- Tag editor with driver-specific function/type choices.
- Output plugin settings for MQTT, PostgreSQL, and MSSQL.
- Runtime page with start/stop, health interval, collection status, OPC UA server status, recent logs, and live tag status.

The first UI should be a practical operations console, not a marketing page. It should be dense, predictable, and usable repeatedly on desktop and tablet widths.

## Data Flow

1. Operator logs in through the browser UI.
2. Browser calls REST APIs to load and save configuration in SQLite.
3. Operator starts runtime through `POST /api/runtime/start`.
4. Runtime manager reads the latest SQLite config, starts workers, and pushes events to queues.
5. Runtime manager updates in-memory status snapshots and broadcasts events through WebSocket.
6. Browser updates runtime tables and logs from WebSocket events.
7. Operator stops runtime through `POST /api/runtime/stop`.

Configuration changes while runtime is running are saved immediately, but they do not silently mutate running workers. The UI should show that restart is required for runtime changes to take effect unless a later implementation adds hot reload explicitly.

## Error Handling

- API validation errors return HTTP 400 with field-specific messages where possible.
- Missing records return HTTP 404.
- Unauthorized requests return HTTP 401.
- Forbidden or invalid session state returns HTTP 403.
- Runtime start fails as a single operation if sink startup fails or no enabled devices can be started.
- Worker-level read/publish errors do not crash the service; they appear in logs, runtime status, and WebSocket events.
- Runtime stop should be idempotent.

## Compatibility

Keep the existing PySide6 app during the first web migration. It can continue using `ConfigStore` while service-layer extraction happens. After the web UI reaches feature parity, remove or deprecate the desktop entry point in a later step.

The existing SQLite database path remains:

```text
~/.industrial_gateway/gateway.sqlite3
```

## Packaging and Run Commands

Add a new console script:

```text
industrial-gateway-web = industrial_gateway.web.app:main
```

The service should default to:

```text
host: 0.0.0.0
port: 50137
```

Host, port, database path, and auth configuration must be overridable through environment variables or command-line options.

## Testing

Tests should cover:

- `RuntimeManager` start/stop idempotency.
- Runtime status snapshots.
- Device/tag/plugin service behavior.
- Auth success and failure.
- Protected API endpoints reject unauthenticated requests.
- API CRUD endpoints persist data through `ConfigStore`.
- WebSocket event broadcast path with a fake runtime event.
- Existing worker and store tests continue passing.

## Out of Scope for First Implementation

- Direct internet exposure.
- TLS certificate automation.
- Multi-user role management.
- Mobile-native UI.
- Hot reloading running device workers after every config edit.
- Replacing SQLite with a client/server database.
- Removing PySide6.
