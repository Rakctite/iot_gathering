import json

from industrial_gateway.services.topic_responder import TopicResponder, TopicResponderConfig


class FakeCursor:
    def __init__(self, rows_by_query):
        self.rows_by_query = rows_by_query
        self.description = []
        self.executed = []
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))
        normalized = " ".join(query.split())
        self.description, self.rows = self.rows_by_query.get(normalized, ([], []))

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows_by_query):
        self.rows_by_query = rows_by_query
        self.cursor_obj = FakeCursor(rows_by_query)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self.cursor_obj


class FakeMqttClient:
    def __init__(self):
        self.published = []
        self.subscribed = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))

    def subscribe(self, topic):
        self.subscribed.append(topic)


def make_responder(rows_by_query):
    connection = FakeConnection(rows_by_query)

    def connect(_config):
        return connection

    client = FakeMqttClient()
    responder = TopicResponder(TopicResponderConfig(), db_connect=connect, mqtt_client_factory=lambda: client)
    return responder, connection, client


def test_refresh_mapping_caches_mac_address_topic_parts():
    responder, connection, _client = make_responder(
        {
            "SET search_path TO core, public": ([], []),
            (
                "SELECT mac_address, process_type, line_code, equip_name, plant_bd, plant_cd "
                "FROM v_topic_mapping;"
            ): (
                [
                    ("mac_address",),
                    ("process_type",),
                    ("line_code",),
                    ("equip_name",),
                    ("plant_bd",),
                    ("plant_cd",),
                ],
                [("AA:BB", "press", "L1", "EQ01", "BD", "CD")],
            ),
        }
    )

    responder.refresh_mapping_once()

    assert responder.device_map["AA:BB"]["plant_cd"] == "CD"
    assert connection.cursor_obj.executed[0] == ("SET search_path TO core, public", None)


def test_topic_request_publishes_topic_for_known_mac():
    responder, _connection, client = make_responder({})
    responder.device_map["AA:BB"] = {
        "process_type": "press",
        "line_code": "L1",
        "equip_name": "EQ01",
        "plant_bd": "BD",
        "plant_cd": "CD",
    }

    responder.handle_payload("C-S/request-topic", b'{"mac": "AA:BB"}')

    assert client.published == [
        ("S-C/request-topic/AA:BB", json.dumps({"topic": "CD/BD/press/L1/EQ01/-/"}, ensure_ascii=False))
    ]


def test_sensor_code_request_publishes_sensor_rows_from_database():
    responder, _connection, client = make_responder(
        {
            "SET search_path TO core, public": ([], []),
            "SELECT * FROM sensor_mst WHERE mac_address = %s;": (
                [("sensor_cd",), ("mac_address",), ("sensor_name",)],
                [("S001", "AA:BB", "temperature")],
            ),
        }
    )

    responder.handle_payload("C-S/request-sensor_cd", b'{"mac": "AA:BB"}')

    assert client.published == [
        (
            "S-C/request-sensor_cd/AA:BB",
            json.dumps([{"sensor_cd": "S001", "mac_address": "AA:BB", "sensor_name": "temperature"}], ensure_ascii=False),
        )
    ]
