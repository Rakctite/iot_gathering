from industrial_gateway.web.api import create_app


def test_create_app_returns_fastapi_app(tmp_path):
    app = create_app(store_path=tmp_path / "gateway.sqlite3", session_secret="secret")

    assert app.title == "Industrial Gateway"
