from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from industrial_gateway.store import ConfigStore


def create_app(store_path: str | Path, session_secret: str) -> FastAPI:
    store = ConfigStore(store_path)
    store.initialize()
    app = FastAPI(title="Industrial Gateway")
    app.state.store = store
    app.state.session_secret = session_secret

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
