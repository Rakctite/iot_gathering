from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from industrial_gateway.models import DeviceSpec, MqttConfig, SinkConfig, TagSpec, validate_tag


class ConfigStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_group TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    driver_type TEXT NOT NULL,
                    enabled INTEGER NOT NULL,
                    poll_interval_ms INTEGER NOT NULL,
                    connection_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                    tag_group TEXT NOT NULL DEFAULT '',
                    name TEXT NOT NULL,
                    address INTEGER NOT NULL,
                    function TEXT NOT NULL,
                    data_type TEXT NOT NULL,
                    scale REAL NOT NULL,
                    enabled INTEGER NOT NULL,
                    word_count INTEGER,
                    byte_order TEXT NOT NULL DEFAULT 'big',
                    word_order TEXT NOT NULL DEFAULT 'big',
                    node_id TEXT
                );
                CREATE TABLE IF NOT EXISTS mqtt_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    base_topic TEXT NOT NULL,
                    username TEXT,
                    password TEXT,
                    client_id TEXT NOT NULL,
                    qos INTEGER NOT NULL,
                    enabled INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sink_config (
                    sink_type TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL,
                    config_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sink_selection (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    sink_type TEXT NOT NULL
                );
                """
            )
            self._migrate_devices(conn)
            self._migrate_tags(conn)
            self._migrate_sink_config(conn)

    def save_device(self, device: DeviceSpec) -> int:
        self._validate_device(device)
        with self._connect() as conn:
            if device.id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO devices
                    (device_group, name, driver_type, enabled, poll_interval_ms, connection_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        device.device_group,
                        device.name,
                        device.driver_type,
                        int(device.enabled),
                        device.poll_interval_ms,
                        json.dumps(device.connection),
                    ),
                )
                return int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE devices
                SET device_group = ?, name = ?, driver_type = ?, enabled = ?, poll_interval_ms = ?, connection_json = ?
                WHERE id = ?
                """,
                (
                    device.device_group,
                    device.name,
                    device.driver_type,
                    int(device.enabled),
                    device.poll_interval_ms,
                    json.dumps(device.connection),
                    device.id,
                ),
            )
            return device.id

    def list_devices(self) -> list[DeviceSpec]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, device_group, name, driver_type, enabled, poll_interval_ms, connection_json
                FROM devices
                ORDER BY device_group, name
                """
            ).fetchall()
        return [
            DeviceSpec(
                id=row["id"],
                device_group=row["device_group"],
                name=row["name"],
                driver_type=row["driver_type"],
                enabled=bool(row["enabled"]),
                poll_interval_ms=row["poll_interval_ms"],
                connection=json.loads(row["connection_json"]),
            )
            for row in rows
        ]

    def delete_device(self, device_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM devices WHERE id = ?", (device_id,))

    def save_tag(self, tag: TagSpec) -> int:
        validate_tag(self._driver_type_for_device(tag.device_id), tag)
        if tag.device_id is None:
            raise ValueError("tag device_id is required")
        self._validate_unique_tag_name(tag)
        with self._connect() as conn:
            if tag.id is None:
                cursor = conn.execute(
                    """
                    INSERT INTO tags
                    (device_id, tag_group, name, address, function, data_type, scale, enabled, word_count, byte_order, word_order, node_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tag.device_id,
                        tag.tag_group,
                        tag.name,
                        tag.address,
                        tag.function,
                        tag.data_type,
                        tag.scale,
                        int(tag.enabled),
                        tag.word_count,
                        tag.byte_order,
                        tag.word_order,
                        tag.node_id,
                    ),
                )
                return int(cursor.lastrowid)
            conn.execute(
                """
                UPDATE tags
                SET device_id = ?, tag_group = ?, name = ?, address = ?, function = ?, data_type = ?, scale = ?, enabled = ?,
                    word_count = ?, byte_order = ?, word_order = ?
                    , node_id = ?
                WHERE id = ?
                """,
                (
                    tag.device_id,
                    tag.tag_group,
                    tag.name,
                    tag.address,
                    tag.function,
                    tag.data_type,
                    tag.scale,
                    int(tag.enabled),
                    tag.word_count,
                    tag.byte_order,
                    tag.word_order,
                    tag.node_id,
                    tag.id,
                ),
            )
            return tag.id

    def list_tags(self, device_id: int) -> list[TagSpec]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, device_id, name, address, function, data_type, scale, enabled,
                       tag_group, word_count, byte_order, word_order
                       , node_id
                FROM tags
                WHERE device_id = ?
                ORDER BY tag_group, name
                """,
                (device_id,),
            ).fetchall()
        return [
            TagSpec(
                id=row["id"],
                device_id=row["device_id"],
                tag_group=row["tag_group"],
                name=row["name"],
                address=row["address"],
                function=row["function"],
                data_type=row["data_type"],
                scale=row["scale"],
                enabled=bool(row["enabled"]),
                word_count=row["word_count"],
                byte_order=row["byte_order"],
                word_order=row["word_order"],
                node_id=row["node_id"],
            )
            for row in rows
        ]

    def delete_tag(self, tag_id: int) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))

    def save_mqtt_config(self, config: MqttConfig) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO mqtt_config
                (id, host, port, base_topic, username, password, client_id, qos, enabled)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    host = excluded.host,
                    port = excluded.port,
                    base_topic = excluded.base_topic,
                    username = excluded.username,
                    password = excluded.password,
                    client_id = excluded.client_id,
                    qos = excluded.qos,
                    enabled = excluded.enabled
                """,
                (
                    config.host,
                    config.port,
                    config.base_topic,
                    config.username,
                    config.password,
                    config.client_id,
                    config.qos,
                    int(config.enabled),
                ),
            )

    def get_mqtt_config(self) -> MqttConfig:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT host, port, base_topic, username, password, client_id, qos, enabled
                FROM mqtt_config
                WHERE id = 1
                """
            ).fetchone()
        if row is None:
            return MqttConfig()
        return MqttConfig(
            host=row["host"],
            port=row["port"],
            base_topic=row["base_topic"],
            username=row["username"],
            password=row["password"],
            client_id=row["client_id"],
            qos=row["qos"],
            enabled=bool(row["enabled"]),
        )

    def save_sink_config(self, config: SinkConfig) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sink_config (sink_type, enabled, config_json)
                VALUES (?, ?, ?)
                ON CONFLICT(sink_type) DO UPDATE SET
                    enabled = excluded.enabled,
                    config_json = excluded.config_json
                """,
                (config.sink_type, int(config.enabled), json.dumps(config.config)),
            )
            conn.execute(
                """
                INSERT INTO sink_selection (id, sink_type)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET sink_type = excluded.sink_type
                """,
                (config.sink_type,),
            )

    def get_sink_config(self, sink_type: str | None = None) -> SinkConfig:
        requested = sink_type or self.get_selected_sink_type()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT sink_type, enabled, config_json FROM sink_config WHERE sink_type = ?",
                (requested,),
            ).fetchone()
        if row is None:
            mqtt = self.get_mqtt_config()
            if requested != "mqtt":
                return SinkConfig(sink_type=requested, enabled=False, config={})
            return SinkConfig(
                sink_type="mqtt",
                enabled=mqtt.enabled,
                config={
                    "host": mqtt.host,
                    "port": mqtt.port,
                    "base_topic": mqtt.base_topic,
                    "username": mqtt.username,
                    "password": mqtt.password,
                    "client_id": mqtt.client_id,
                    "qos": mqtt.qos,
                },
            )
        return SinkConfig(
            sink_type=row["sink_type"],
            enabled=bool(row["enabled"]),
            config=json.loads(row["config_json"]),
        )

    def get_selected_sink_type(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT sink_type FROM sink_selection WHERE id = 1").fetchone()
        return row["sink_type"] if row is not None else "mqtt"

    def list_sink_configs(self) -> list[SinkConfig]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sink_type, enabled, config_json FROM sink_config ORDER BY sink_type"
            ).fetchall()
        return [
            SinkConfig(
                sink_type=row["sink_type"],
                enabled=bool(row["enabled"]),
                config=json.loads(row["config_json"]),
            )
            for row in rows
        ]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _validate_device(self, device: DeviceSpec) -> None:
        if not device.name.strip():
            raise ValueError("device name is required")
        if not device.driver_type.strip():
            raise ValueError("device driver_type is required")
        if device.poll_interval_ms < 100:
            raise ValueError("device poll_interval_ms must be at least 100")

    def _migrate_devices(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
        if "device_group" not in columns:
            conn.execute("ALTER TABLE devices ADD COLUMN device_group TEXT NOT NULL DEFAULT ''")

    def _migrate_tags(self, conn: sqlite3.Connection) -> None:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(tags)").fetchall()}
        if "word_count" not in columns:
            conn.execute("ALTER TABLE tags ADD COLUMN word_count INTEGER")
        if "byte_order" not in columns:
            conn.execute("ALTER TABLE tags ADD COLUMN byte_order TEXT NOT NULL DEFAULT 'big'")
        if "word_order" not in columns:
            conn.execute("ALTER TABLE tags ADD COLUMN word_order TEXT NOT NULL DEFAULT 'big'")
        if "node_id" not in columns:
            conn.execute("ALTER TABLE tags ADD COLUMN node_id TEXT")
        if "tag_group" not in columns:
            conn.execute("ALTER TABLE tags ADD COLUMN tag_group TEXT NOT NULL DEFAULT ''")

    def _migrate_sink_config(self, conn: sqlite3.Connection) -> None:
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(sink_config)").fetchall()]
        if "id" not in columns:
            return
        rows = conn.execute("SELECT sink_type, enabled, config_json FROM sink_config").fetchall()
        conn.execute("ALTER TABLE sink_config RENAME TO sink_config_old")
        conn.execute(
            """
            CREATE TABLE sink_config (
                sink_type TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL,
                config_json TEXT NOT NULL
            )
            """
        )
        for row in rows:
            conn.execute(
                """
                INSERT INTO sink_config (sink_type, enabled, config_json)
                VALUES (?, ?, ?)
                ON CONFLICT(sink_type) DO UPDATE SET
                    enabled = excluded.enabled,
                    config_json = excluded.config_json
                """,
                (row["sink_type"], row["enabled"], row["config_json"]),
            )
            conn.execute(
                """
                INSERT INTO sink_selection (id, sink_type)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET sink_type = excluded.sink_type
                """,
                (row["sink_type"],),
            )
        conn.execute("DROP TABLE sink_config_old")

    def _driver_type_for_device(self, device_id: int | None) -> str:
        if device_id is None:
            raise ValueError("tag device_id is required")
        with self._connect() as conn:
            row = conn.execute("SELECT driver_type FROM devices WHERE id = ?", (device_id,)).fetchone()
        if row is None:
            raise ValueError(f"device not found: {device_id}")
        return row["driver_type"]

    def _validate_unique_tag_name(self, tag: TagSpec) -> None:
        if tag.device_id is None:
            return
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id FROM tags
                WHERE device_id = ? AND tag_group = ? AND name = ?
                  AND (? IS NULL OR id != ?)
                LIMIT 1
                """,
                (tag.device_id, tag.tag_group, tag.name, tag.id, tag.id),
            ).fetchone()
        if row is not None:
            group = tag.tag_group or "default"
            raise ValueError(f"tag name already exists in group '{group}': {tag.name}")
