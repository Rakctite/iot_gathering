from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Any, Callable


REQUEST_TOPIC = "C-S/request-topic"
REQUEST_SENSOR_CODE = "C-S/request-sensor_cd"


@dataclass(frozen=True)
class TopicResponderConfig:
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "edge_hmi"
    db_user: str = "admin"
    db_password: str = "1q2w3e4r"
    db_connect_timeout: int = 5
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_keepalive: int = 60
    mapping_refresh_s: float = 60.0

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "TopicResponderConfig":
        values = os.environ if environ is None else environ
        return cls(
            db_host=values.get("DB_HOST", cls.db_host),
            db_port=_int_env(values, "DB_PORT", cls.db_port),
            db_name=values.get("DB_NAME", cls.db_name),
            db_user=values.get("DB_USER", cls.db_user),
            db_password=values.get("DB_PASSWORD", cls.db_password),
            db_connect_timeout=_int_env(values, "DB_CONNECT_TIMEOUT", cls.db_connect_timeout),
            mqtt_host=values.get("MQTT_HOST", cls.mqtt_host),
            mqtt_port=_int_env(values, "MQTT_PORT", cls.mqtt_port),
            mqtt_keepalive=_int_env(values, "MQTT_KEEPALIVE", cls.mqtt_keepalive),
            mapping_refresh_s=_float_env(values, "TOPIC_RESPONDER_MAPPING_REFRESH_S", cls.mapping_refresh_s),
        )


class TopicResponder(threading.Thread):
    def __init__(
        self,
        config: TopicResponderConfig | None = None,
        *,
        db_connect: Callable[[TopicResponderConfig], Any] | None = None,
        mqtt_client_factory: Callable[[], Any] | None = None,
        log_queue: Any | None = None,
    ) -> None:
        super().__init__(daemon=True)
        self.config = config or TopicResponderConfig.from_env()
        self.db_connect = db_connect or _default_db_connect
        self.mqtt_client_factory = mqtt_client_factory or _default_mqtt_client
        self.log_queue = log_queue
        self.device_map: dict[str, dict[str, Any]] = {}
        self.client: Any | None = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def run(self) -> None:
        self.refresh_mapping_once()
        self.client = self.mqtt_client_factory()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.connect(self.config.mqtt_host, self.config.mqtt_port, self.config.mqtt_keepalive)
        self.client.loop_start()
        try:
            while not self._stop_event.wait(self.config.mapping_refresh_s):
                self.refresh_mapping_once()
        finally:
            if self.client is not None:
                self.client.loop_stop()
                self.client.disconnect()

    def stop(self) -> None:
        self._stop_event.set()

    def refresh_mapping_once(self) -> None:
        rows = self._fetch_mapping_rows()
        with self._lock:
            self.device_map = {str(row["mac_address"]): row for row in rows if row.get("mac_address")}

    def handle_payload(self, topic: str, payload: bytes | str) -> None:
        try:
            data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return
        mac = str(data.get("mac") or "").strip()
        if not mac:
            return
        if topic == REQUEST_TOPIC:
            self._publish_topic_response(mac)
        elif topic == REQUEST_SENSOR_CODE:
            self._publish_sensor_code_response(mac)

    def _fetch_mapping_rows(self) -> list[dict[str, Any]]:
        with self.db_connect(self.config) as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO core, public")
                cur.execute(
                    "SELECT mac_address, process_type, line_code, equip_name, plant_bd, plant_cd "
                    "FROM v_topic_mapping;"
                )
                return _rows_to_dicts(cur.description, cur.fetchall())

    def _fetch_sensor_rows(self, mac: str) -> list[dict[str, Any]]:
        with self.db_connect(self.config) as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO core, public")
                cur.execute("SELECT * FROM sensor_mst WHERE mac_address = %s;", (mac,))
                return _rows_to_dicts(cur.description, cur.fetchall())

    def _publish_topic_response(self, mac: str) -> None:
        with self._lock:
            mapping = dict(self.device_map.get(mac, {}))
        if mapping:
            topic_value = (
                f"{mapping.get('plant_cd')}/{mapping.get('plant_bd')}/{mapping.get('process_type')}/"
                f"{mapping.get('line_code')}/{mapping.get('equip_name')}/-/"
            )
        else:
            topic_value = "Unknown MAC"
        self._publish(f"S-C/request-topic/{mac}", {"topic": topic_value})

    def _publish_sensor_code_response(self, mac: str) -> None:
        self._publish(f"S-C/request-sensor_cd/{mac}", self._fetch_sensor_rows(mac))

    def _publish(self, topic: str, payload: Any) -> None:
        client = self.client
        if client is None:
            client = self.mqtt_client_factory()
            self.client = client
        client.publish(topic, json.dumps(payload, ensure_ascii=False))

    def _on_connect(self, client: Any, _userdata: Any, _flags: Any, rc: int, *args: Any) -> None:
        if rc == 0:
            client.subscribe(REQUEST_TOPIC)
            client.subscribe(REQUEST_SENSOR_CODE)

    def _on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        self.handle_payload(str(msg.topic), msg.payload)


def _rows_to_dicts(description: Any, rows: list[Any]) -> list[dict[str, Any]]:
    columns = [_column_name(column) for column in description]
    return [dict(zip(columns, row)) for row in rows]


def _column_name(column: Any) -> str:
    name = getattr(column, "name", None)
    if name:
        return str(name)
    return str(column[0])


def _default_db_connect(config: TopicResponderConfig) -> Any:
    import psycopg

    return psycopg.connect(
        host=config.db_host,
        port=config.db_port,
        dbname=config.db_name,
        user=config.db_user,
        password=config.db_password,
        connect_timeout=config.db_connect_timeout,
    )


def _default_mqtt_client() -> Any:
    import paho.mqtt.client as mqtt

    return mqtt.Client()


def _int_env(values: dict[str, str], key: str, default: int) -> int:
    try:
        return int(values.get(key, default))
    except (TypeError, ValueError):
        return default


def _float_env(values: dict[str, str], key: str, default: float) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return default
