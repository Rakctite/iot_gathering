from __future__ import annotations

from pathlib import Path
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse

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
    app = FastAPI(title="Industrial Gateway")
    app.state.store = store
    app.state.auth_settings = auth_settings

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request, exc: HTTPException):
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": "http_error", "message": str(exc.detail)})

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

    return app
