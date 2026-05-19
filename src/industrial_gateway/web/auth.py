from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Response
from itsdangerous import BadSignature, URLSafeSerializer
from pydantic import BaseModel

SESSION_COOKIE = "industrial_gateway_session"


class LoginRequest(BaseModel):
    username: str
    password: str


@dataclass(frozen=True)
class AuthSettings:
    username: str
    password: str
    session_secret: str


def create_session_token(settings: AuthSettings) -> str:
    return URLSafeSerializer(settings.session_secret, salt="industrial-gateway-session").dumps(
        {"username": settings.username}
    )


def read_session_token(token: str, settings: AuthSettings) -> dict[str, str]:
    try:
        data = URLSafeSerializer(settings.session_secret, salt="industrial-gateway-session").loads(token)
    except BadSignature as exc:
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Login required"}) from exc
    if data.get("username") != settings.username:
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Login required"})
    return {"username": settings.username}


def verify_login(request: LoginRequest, settings: AuthSettings) -> bool:
    return hmac.compare_digest(request.username, settings.username) and hmac.compare_digest(
        request.password,
        settings.password,
    )


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def require_session(settings: AuthSettings, token: str | None = None) -> dict[str, str]:
    if not token:
        raise HTTPException(status_code=401, detail={"error": "unauthorized", "message": "Login required"})
    return read_session_token(token, settings)
