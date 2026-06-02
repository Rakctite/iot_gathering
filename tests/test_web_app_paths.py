from pathlib import Path

from industrial_gateway.web import app as web_app


def test_default_paths_use_movable_project_root():
    root = Path(__file__).parents[2]

    assert web_app._default_root() == root
    assert web_app._default_store_path() == root / "gateway.sqlite3"
    assert web_app._default_log_root() == root / "industrial_gateway_log"
