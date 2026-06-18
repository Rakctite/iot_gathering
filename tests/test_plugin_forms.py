from industrial_gateway.config_schema import default_plugin_config, plugin_fields, plugin_schema


def test_default_plugin_schema_includes_only_core_mqtt_fields():
    schema = plugin_schema()

    assert list(schema) == ["mqtt"]


def test_plugin_forms_include_mqtt_and_postgresql_fields():
    assert [field.key for field in plugin_fields("mqtt")][:3] == ["host", "port", "base_topic"]
    assert [field.key for field in plugin_fields("mqtt")][-2:] == ["dynamic_topic_enabled", "mac_address"]
    assert [field.key for field in plugin_fields("postgresql")][:4] == ["host", "port", "database", "username"]
    assert plugin_fields("mssql") == []


def test_default_plugin_config_sets_database_tables():
    assert default_plugin_config("postgresql")["table"] == "gateway_tag_values"
    assert default_plugin_config("mssql") == {}
