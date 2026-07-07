from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import AsyncIterator

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from industrial_gateway import __version__
from industrial_gateway.config_schema import driver_schema, plugin_schema
from industrial_gateway.drivers.modbus_rtu_monitor import probe_responses
from industrial_gateway.services.config_service import ConfigService
from industrial_gateway.services.runtime_manager import RuntimeManager
from industrial_gateway.store import ConfigStore
from industrial_gateway.web.auth import (
    AuthSettings,
    LoginRequest,
    clear_session_cookie,
    create_session_token,
    require_session,
    set_session_cookie,
    verify_login,
)


def create_app(
    store_path: str | Path,
    session_secret: str,
    admin_username: str = "admin",
    admin_password: str = "admin",
    log_root: str | Path | None = None,
) -> FastAPI:
    store = ConfigStore(store_path)
    store.initialize()
    auth_settings = AuthSettings(admin_username, admin_password, session_secret)
    config_service = ConfigService(store)
    runtime_manager = RuntimeManager(store, log_root=log_root)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            runtime_manager.shutdown()

    app = FastAPI(title="Industrial Gateway", lifespan=lifespan)
    app.state.store = store
    app.state.auth_settings = auth_settings
    app.state.config_service = config_service
    app.state.runtime_manager = runtime_manager

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "message": str(exc.detail)})

    @app.exception_handler(KeyError)
    async def key_error_handler(_request, exc: KeyError):
        return JSONResponse(status_code=404, content={"error": "not_found", "message": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, exc: ValueError):
        return JSONResponse(status_code=400, content={"error": "bad_request", "message": str(exc)})

    def session_dependency(industrial_gateway_session: str | None = Cookie(default=None)) -> dict[str, str]:
        return require_session(auth_settings, industrial_gateway_session)

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, object]:
        if not verify_login(payload, auth_settings):
            raise HTTPException(
                status_code=401,
                detail={"error": "invalid_credentials", "message": "Invalid username or password"},
            )
        set_session_cookie(response, create_session_token(auth_settings))
        return {"authenticated": True, "username": auth_settings.username}

    @app.post("/api/auth/logout")
    def logout(response: Response) -> dict[str, bool]:
        clear_session_cookie(response)
        return {"authenticated": False}

    @app.get("/api/session")
    def session(user: dict[str, str] = Depends(session_dependency)) -> dict[str, object]:
        return {"authenticated": True, "username": user["username"]}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/app-info")
    def app_info() -> dict[str, str]:
        return {"name": "Industrial Gateway", "version": os.getenv("INDUSTRIAL_GATEWAY_VERSION", __version__)}

    @app.get("/api/schema/drivers")
    def get_driver_schema(_user: dict[str, str] = Depends(session_dependency)):
        return driver_schema()

    @app.get("/api/schema/plugins")
    def get_plugin_schema(_user: dict[str, str] = Depends(session_dependency)):
        return plugin_schema()

    @app.get("/api/devices")
    def list_devices(_user: dict[str, str] = Depends(session_dependency)):
        return config_service.list_devices()

    @app.post("/api/devices")
    def create_device(payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.create_device(payload)

    @app.put("/api/devices/{device_id}")
    def update_device(device_id: int, payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.update_device(device_id, payload)

    @app.delete("/api/devices/{device_id}")
    def delete_device(device_id: int, _user: dict[str, str] = Depends(session_dependency)):
        config_service.delete_device(device_id)
        return {"deleted": True}

    @app.get("/api/devices.csv")
    def export_devices_csv(_user: dict[str, str] = Depends(session_dependency)):
        return Response(
            config_service.export_devices_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="devices.csv"'},
        )

    @app.post("/api/devices/import")
    async def import_devices_csv(request: Request, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.import_devices_csv((await request.body()).decode("utf-8-sig"))

    @app.get("/api/devices/{device_id}/tags")
    def list_tags(device_id: int, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.list_tags(device_id)

    @app.post("/api/devices/modbus-rtu-monitor/probe")
    def probe_modbus_rtu_monitor(payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return probe_responses(payload.get("connection") or {})

    @app.get("/api/tags")
    def list_all_tags(_user: dict[str, str] = Depends(session_dependency)):
        return config_service.list_all_tags()

    @app.get("/api/devices/{device_id}/tags.csv")
    def export_tags_csv(device_id: int, _user: dict[str, str] = Depends(session_dependency)):
        return Response(
            config_service.export_tags_csv(device_id),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="device-{device_id}-tags.csv"'},
        )

    @app.post("/api/devices/{device_id}/tags/import")
    async def import_tags_csv(device_id: int, request: Request, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.import_tags_csv(device_id, (await request.body()).decode("utf-8-sig"))

    @app.post("/api/devices/{device_id}/tags")
    def create_tag(device_id: int, payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.create_tag(device_id, payload)

    @app.put("/api/tags/{tag_id}")
    def update_tag(tag_id: int, payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.update_tag(tag_id, payload)

    @app.delete("/api/tags/{tag_id}")
    def delete_tag(tag_id: int, _user: dict[str, str] = Depends(session_dependency)):
        config_service.delete_tag(tag_id)
        return {"deleted": True}

    @app.get("/api/plugins")
    def list_plugins(_user: dict[str, str] = Depends(session_dependency)):
        return config_service.list_sink_configs()

    @app.get("/api/plugins.csv")
    def export_plugins_csv(_user: dict[str, str] = Depends(session_dependency)):
        return Response(
            config_service.export_plugins_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="plugins.csv"'},
        )

    @app.post("/api/plugins/import")
    async def import_plugins_csv(request: Request, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.import_plugins_csv((await request.body()).decode("utf-8-sig"))

    @app.get("/api/plugins/{sink_type}")
    def get_plugin(sink_type: str, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.get_sink_config(sink_type)

    @app.put("/api/plugins/{sink_type}")
    def save_plugin(sink_type: str, payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.save_sink_config({"sink_type": sink_type, **payload})

    @app.get("/api/plugin-routes")
    def list_plugin_routes(_user: dict[str, str] = Depends(session_dependency)):
        return config_service.list_output_routes()

    @app.get("/api/plugin-routes.csv")
    def export_plugin_routes_csv(_user: dict[str, str] = Depends(session_dependency)):
        return Response(
            config_service.export_plugin_routes_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="plugin-routes.csv"'},
        )

    @app.post("/api/plugin-routes/import")
    async def import_plugin_routes_csv(request: Request, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.import_plugin_routes_csv((await request.body()).decode("utf-8-sig"))

    @app.post("/api/plugin-routes")
    def save_plugin_route(payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.save_output_route(payload)

    @app.put("/api/plugin-routes/{route_id}")
    def update_plugin_route(route_id: int, payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.save_output_route({"id": route_id, **payload})

    @app.post("/api/plugin-routes/{route_id}/resolve-topic")
    def resolve_plugin_route_topic(route_id: int, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.resolve_output_route_topic(route_id)

    @app.delete("/api/plugin-routes/{route_id}")
    def delete_plugin_route(route_id: int, _user: dict[str, str] = Depends(session_dependency)):
        config_service.delete_output_route(route_id)
        return {"deleted": True}

    @app.post("/api/runtime/start")
    def start_runtime(payload: dict | None = None, _user: dict[str, str] = Depends(session_dependency)):
        health_interval = None if payload is None else payload.get("health_interval_s")
        runtime_log_enabled = None if payload is None else payload.get("runtime_log_enabled")
        return runtime_manager.start(
            health_interval,
            None if runtime_log_enabled is None else bool(runtime_log_enabled),
        )

    @app.post("/api/runtime/stop")
    def stop_runtime(_user: dict[str, str] = Depends(session_dependency)):
        return runtime_manager.stop()

    @app.get("/api/runtime/status")
    def runtime_status(_user: dict[str, str] = Depends(session_dependency)):
        runtime_manager.drain_events()
        return runtime_manager.snapshot()

    @app.websocket("/api/runtime/events")
    async def runtime_events(websocket: WebSocket):
        token = websocket.cookies.get("industrial_gateway_session")
        try:
            require_session(auth_settings, token)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        await websocket.send_json({"type": "snapshot", "payload": runtime_manager.snapshot()})
        try:
            while True:
                for event in runtime_manager.drain_events():
                    await websocket.send_json(event)
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.2)
                except TimeoutError:
                    continue
        except WebSocketDisconnect:
            return

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    runtime_manager.start()

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    return app
