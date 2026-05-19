from industrial_gateway.config_schema import default_plugin_config, plugin_fields


def test_plugin_forms_include_mqtt_postgresql_and_mssql_fields():
    assert [field.key for field in plugin_fields("mqtt")][:3] == ["host", "port", "base_topic"]
    assert [field.key for field in plugin_fields("mqtt")][-2:] == ["dynamic_topic_enabled", "mac_address"]
    assert [field.key for field in plugin_fields("postgresql")][:4] == ["host", "port", "database", "username"]
    assert [field.key for field in plugin_fields("mssql")][:4] == ["server", "port", "database", "username"]


def test_default_plugin_config_sets_database_tables():
    assert default_plugin_config("postgresql")["table"] == "gateway_tag_values"
    assert default_plugin_config("mssql")["port"] == 1433
