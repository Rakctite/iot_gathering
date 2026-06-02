from industrial_gateway.config_schema import (
    connection_fields_for_driver,
    default_connection_for_driver,
    normalize_connection_for_driver,
    tag_function_choices_for_driver,
    tag_type_choices_for_driver,
)


def test_modbus_tcp_connection_form_uses_network_fields():
    fields = connection_fields_for_driver("modbus_tcp")

    assert [field.key for field in fields] == [
        "host",
        "port",
        "unit_id",
        "max_block_gap",
        "max_registers_per_read",
        "max_bits_per_read",
    ]
    assert default_connection_for_driver("modbus_tcp")["host"] == "127.0.0.1"
    assert default_connection_for_driver("modbus_tcp")["port"] == 502


def test_modbus_serial_connection_form_uses_serial_fields():
    fields = connection_fields_for_driver("modbus_serial")

    assert [field.key for field in fields][:6] == ["port", "baudrate", "parity", "stopbits", "bytesize", "timeout"]
    assert default_connection_for_driver("modbus_serial")["baudrate"] == 9600


def test_opcua_connection_form_uses_endpoint_and_mode_fields():
    fields = connection_fields_for_driver("opcua")

    assert [field.key for field in fields] == ["endpoint", "mode", "subscription_interval_ms"]
    assert default_connection_for_driver("opcua")["mode"] == "polling"


def test_mqtt_connection_form_uses_broker_and_payload_fields():
    fields = connection_fields_for_driver("mqtt")

    assert [field.key for field in fields] == [
        "host",
        "port",
        "topic_filter",
        "client_id",
        "username",
        "password",
        "qos",
        "topic_mac_index",
        "timestamp_field",
        "sensor_id_field",
    ]
    assert default_connection_for_driver("mqtt")["topic_filter"] == "curiot/+/data"


def test_connection_normalization_preserves_existing_values_and_fills_missing_defaults():
    normalized = normalize_connection_for_driver("modbus_tcp", {"host": "10.0.0.10"})

    assert normalized["host"] == "10.0.0.10"
    assert normalized["port"] == 502
    assert normalized["unit_id"] == 1


def test_tag_choices_follow_selected_driver():
    assert tag_function_choices_for_driver("modbus_serial") == [
        "holding_register",
        "input_register",
        "coil",
        "discrete_input",
    ]
    assert tag_function_choices_for_driver("opcua") == ["opcua_node"]
    assert tag_function_choices_for_driver("mqtt") == ["json_field"]
    assert "auto" not in tag_type_choices_for_driver("modbus_tcp")
    assert tag_type_choices_for_driver("opcua")[0] == "auto"
    assert tag_type_choices_for_driver("mqtt")[0] == "auto"
