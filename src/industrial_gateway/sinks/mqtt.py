from __future__ import annotations

import json
from typing import Any

from industrial_gateway.models import BatchMessage, MqttConfig


class MqttSink:
    def __init__(self, config: MqttConfig | dict[str, Any]) -> None:
        self.config = _mqtt_config(config)
        self.client: Any | None = None

    def start(self) -> None:
        if not self.config.enabled:
            return
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise RuntimeError("paho-mqtt is required for MQTT publishing") from exc
        self.client = mqtt.Client(client_id=self.config.client_id)
        if self.config.username:
            self.client.username_pw_set(self.config.username, self.config.password)
        self.client.connect(self.config.host, self.config.port)
        self.client.loop_start()

    def stop(self) -> None:
        if self.client is not None:
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None

    def publish_batch(self, message: BatchMessage) -> None:
        if self.client is None:
            raise RuntimeError("MQTT sink is not started")
        payload = json.dumps(message.payload, ensure_ascii=False, separators=(",", ":"))
        result = self.client.publish(message.topic, payload, qos=message.qos)
        if getattr(result, "rc", 0) != 0:
            raise RuntimeError(f"MQTT publish failed with rc={result.rc}")


def _mqtt_config(config: MqttConfig | dict[str, Any]) -> MqttConfig:
    if isinstance(config, MqttConfig):
        return config
    return MqttConfig(
        host=config.get("host", "localhost"),
        port=int(config.get("port", 1883)),
        base_topic=config.get("base_topic", "industrial"),
        username=config.get("username") or None,
        password=config.get("password") or None,
        client_id=config.get("client_id", "industrial-gateway"),
        qos=int(config.get("qos", 0)),
        enabled=bool(config.get("enabled", True)),
    )
