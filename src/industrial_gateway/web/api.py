from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from collections.abc import AsyncIterator

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

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
) -> FastAPI:
    store = ConfigStore(store_path)
    store.initialize()
    auth_settings = AuthSettings(admin_username, admin_password, session_secret)
    config_service = ConfigService(store)
    runtime_manager = RuntimeManager(store)

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

    @app.get("/api/devices/{device_id}/tags")
    def list_tags(device_id: int, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.list_tags(device_id)

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

    @app.get("/api/plugins/{sink_type}")
    def get_plugin(sink_type: str, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.get_sink_config(sink_type)

    @app.put("/api/plugins/{sink_type}")
    def save_plugin(sink_type: str, payload: dict, _user: dict[str, str] = Depends(session_dependency)):
        return config_service.save_sink_config({"sink_type": sink_type, **payload})

    @app.post("/api/runtime/start")
    def start_runtime(payload: dict | None = None, _user: dict[str, str] = Depends(session_dependency)):
        health_interval = None if payload is None else payload.get("health_interval_s")
        return runtime_manager.start(health_interval)

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

    return app
