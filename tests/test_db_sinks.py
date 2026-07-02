from datetime import datetime, timezone

from industrial_gateway.models import BatchMessage
from industrial_gateway.sinks.database import PostgresSink


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.closed = False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.cursors = []
        self.commits = 0
        self.closed = False

    def cursor(self):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        self.cursor_obj = cursor
        return cursor

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _message():
    return BatchMessage(
        topic="industrial/press/data",
        payload={
            "device": {"id": 7, "name": "press"},
            "timestamp": "2026-05-16T02:30:00+00:00",
            "tags": [
                {
                    "name": "temperature",
                    "address": 100,
                    "value": 31.5,
                    "quality": "good",
                    "error": None,
                    "timestamp": "2026-05-16T02:30:01+00:00",
                }
            ],
        },
    )


def test_postgres_sink_inserts_one_row_per_tag_with_json_value():
    conn = FakeConnection()
    sink = PostgresSink({"table": "gateway_tag_values", "auto_create": True}, connect=lambda config: conn)

    sink.start()
    sink.publish_batch(_message())
    sink.stop()

    assert "CREATE TABLE IF NOT EXISTS gateway_tag_values" in conn.cursors[0].statements[0][0]
    insert_sql, params = conn.cursors[1].statements[0]
    assert "INSERT INTO gateway_tag_values" in insert_sql
    assert params[:4] == (7, "press", "temperature", 100)
    assert params[4] == "31.5"
    assert params[5:] == ("good", None, "2026-05-16T02:30:01+00:00")
    assert conn.commits == 2
    assert conn.closed is True
    assert all(cursor.closed for cursor in conn.cursors)
