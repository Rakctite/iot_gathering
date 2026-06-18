import importlib


def test_default_sink_registry_exposes_only_core_mqtt_sink(monkeypatch):
    monkeypatch.delenv("INDUSTRIAL_GATEWAY_PLUGIN_PROFILE", raising=False)

    import industrial_gateway.defaults as defaults

    defaults = importlib.reload(defaults)

    assert defaults.sink_registry.keys() == ["mqtt"]


def test_postgres_profile_exposes_postgresql_but_not_mssql(monkeypatch):
    monkeypatch.setenv("INDUSTRIAL_GATEWAY_PLUGIN_PROFILE", "postgres")

    import industrial_gateway.defaults as defaults

    defaults = importlib.reload(defaults)

    assert defaults.sink_registry.keys() == ["mqtt", "postgresql"]
