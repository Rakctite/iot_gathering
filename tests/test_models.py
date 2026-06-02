from datetime import datetime, timezone

import pytest

from industrial_gateway.models import (
    BatchMessage,
    DeviceSpec,
    MqttConfig,
    TagResult,
    TagSpec,
    validate_modbus_tag,
)


def test_modbus_tag_validation_rejects_negative_address():
    tag = TagSpec(name="pressure", address=-1, function="holding_register", data_type="int16")

    with pytest.raises(ValueError, match="address"):
        validate_modbus_tag(tag)


def test_batch_message_contains_device_timestamp_and_tag_quality():
    timestamp = datetime(2026, 5, 16, 2, 30, 0, 123456, tzinfo=timezone.utc)
    device = DeviceSpec(
        id=7,
        name="boiler-plc",
        driver_type="modbus_tcp",
        enabled=True,
        poll_interval_ms=1000,
        connection={"host": "192.168.0.10", "port": 502, "unit_id": 1},
    )
    tag = TagResult(
        name="temperature",
        address=40001,
        value=31.5,
        quality="good",
        error=None,
        timestamp=timestamp,
    )

    message = BatchMessage.from_results(device, [tag], timestamp, MqttConfig())

    assert message.topic == "industrial/boiler-plc/data"
    assert message.payload == {
        "device": {"id": 7, "name": "boiler-plc"},
        "timestamp": "2026-05-16T02:30:00.123+00:00",
        "tags": [
            {
                "name": "temperature",
                "address": 40001,
                "value": 31.5,
                "quality": "good",
                "error": None,
                "timestamp": "2026-05-16T02:30:00.123+00:00",
            }
        ],
    }
