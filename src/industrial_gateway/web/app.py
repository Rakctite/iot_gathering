from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from industrial_gateway.web.api import create_app


def _default_store_path() -> Path:
    return Path.home() / ".industrial_gateway" / "gateway.sqlite3"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Industrial Gateway web service")
    parser.add_argument("--host", default=os.getenv("INDUSTRIAL_GATEWAY_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("INDUSTRIAL_GATEWAY_PORT", "50137")))
    parser.add_argument("--store", default=os.getenv("INDUSTRIAL_GATEWAY_STORE", str(_default_store_path())))
    parser.add_argument("--session-secret", default=os.getenv("INDUSTRIAL_GATEWAY_SESSION_SECRET", "dev-session-secret"))
    parser.add_argument("--admin-username", default=os.getenv("INDUSTRIAL_GATEWAY_ADMIN_USER", "admin"))
    parser.add_argument("--admin-password", default=os.getenv("INDUSTRIAL_GATEWAY_ADMIN_PASSWORD", "admin"))
    args = parser.parse_args()

    app = create_app(
        Path(args.store),
        args.session_secret,
        admin_username=args.admin_username,
        admin_password=args.admin_password,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
