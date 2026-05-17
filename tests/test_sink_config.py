from industrial_gateway.models import SinkConfig
from industrial_gateway.store import ConfigStore


def test_sqlite_store_round_trips_selected_sink_config(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()

    store.save_sink_config(
        SinkConfig(
            sink_type="postgresql",
            enabled=True,
            config={
                "host": "db.local",
                "port": 5432,
                "database": "gateway",
                "username": "writer",
                "password": "secret",
            },
        )
    )

    config = store.get_sink_config()

    assert config.sink_type == "postgresql"
    assert config.enabled is True
    assert config.config["host"] == "db.local"


def test_sqlite_store_keeps_sink_config_per_plugin(tmp_path):
    store = ConfigStore(tmp_path / "gateway.sqlite3")
    store.initialize()

    store.save_sink_config(SinkConfig(sink_type="mqtt", enabled=True, config={"host": "broker"}))
    store.save_sink_config(SinkConfig(sink_type="postgresql", enabled=False, config={"host": "pg"}))

    mqtt = store.get_sink_config("mqtt")
    postgres = store.get_sink_config("postgresql")

    assert mqtt.enabled is True
    assert mqtt.config["host"] == "broker"
    assert postgres.enabled is False
    assert postgres.config["host"] == "pg"
