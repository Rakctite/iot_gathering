from industrial_gateway.config_schema import default_plugin_config, plugin_fields, plugin_schema


def test_default_plugin_schema_includes_only_core_mqtt_fields():
    schema = plugin_schema()

    assert list(schema) == ["mqtt"]


def test_plugin_forms_include_mqtt_and_postgresql_fields():
    mqtt_keys = [field.key for field in plugin_fields("mqtt")]
    assert mqtt_keys[:3] == ["host", "port", "base_topic"]
    assert "dynamic_topic_enabled" not in mqtt_keys
    assert "mac_address" not in mqtt_keys
    assert "topic_request_on_start" in mqtt_keys
    assert "topic_refresh_interval_s" in mqtt_keys
    assert [field.key for field in plugin_fields("postgresql")][:4] == ["host", "port", "database", "username"]
    assert plugin_fields("mssql") == []


def test_default_plugin_config_sets_database_tables():
    assert default_plugin_config("postgresql")["table"] == "gateway_tag_values"
    assert default_plugin_config("mssql") == {}
