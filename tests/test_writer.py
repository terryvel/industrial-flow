from datetime import datetime, timezone

import pytest

from industrial_flow.config import PIConfig
from industrial_flow.pi.piapi import PIAPIError, PIAPIReader
from industrial_flow.writer import PubSubPIArchiveWriter, WriteRequest, parse_write_request


def test_parse_write_request_normalizes_tag_and_timestamp_to_utc():
    request = parse_write_request(
        {
            "site": "casa",
            "tag": "sinusoid",
            "timestamp": "2026-09-04T12:00:00-03:00",
            "value": 42.5,
        }
    )

    assert request == WriteRequest(
        site="casa",
        tag="SINUSOID",
        timestamp=datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc),
        value=42.5,
        istat=0,
        wait=True,
    )


def test_parse_write_request_rejects_non_numeric_value():
    with pytest.raises(ValueError, match="numeric"):
        parse_write_request(
            {"site": "casa", "tag": "TAG_A", "timestamp": "2026-09-04T15:00:00Z", "value": "bad"}
        )


def test_piapi_writer_calls_piar_putvalue_with_resolved_point(monkeypatch):
    class FakePIAPI:
        @staticmethod
        def piut_isconnected():
            return 1

        def __init__(self):
            self.write_args = None

        def piar_putvalue(self, point_id, value, istat, timedate, wait):
            self.write_args = (point_id.value, value.value, istat.value, timedate.value, wait.value)
            return 0

    reader = PIAPIReader(PIConfig(provider="piapi", server="PI-TEST", site="site1"))
    reader.piapi = FakePIAPI()
    reader.preload_point_cache({"TAG_A": 123})
    monkeypatch.setattr(reader, "_parse_time", lambda value: __import__("ctypes").c_int(987))

    reader.write_archive_value("tag_a", datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc), 42.5)

    assert reader.piapi.write_args == (123, 42.5, 0, 987, 1)


def test_piapi_writer_rejects_unknown_point():
    class FakePIAPI:
        @staticmethod
        def piut_isconnected():
            return 1

        @staticmethod
        def piar_putvalue(*args):
            return 0

        @staticmethod
        def pipt_findpoint(*args):
            return -1

    reader = PIAPIReader(PIConfig(provider="piapi", server="PI-TEST", site="site1"))
    reader.piapi = FakePIAPI()

    with pytest.raises(PIAPIError, match="Point not found"):
        reader.write_archive_value("TAG_A", datetime.now(timezone.utc), 1.0)


def test_pubsub_writer_logs_received_event_before_writing(monkeypatch):
    class FakePubSub:
        class SubscriberClient:
            def __init__(self, **kwargs):
                pass

            def subscription_path(self, project_id, subscription_id):
                return f"{project_id}/{subscription_id}"

            def subscribe(self, subscription, callback):
                self.callback = callback
                callback(
                    type(
                        "Message",
                        (),
                        {
                            "message_id": "message-1",
                            "data": b'{"site":"casa","tag":"tag_a","timestamp":"2026-09-04T15:00:00Z","value":1}',
                            "ack": lambda self: None,
                            "nack": lambda self: None,
                        },
                    )()
                )
                return type("Future", (), {"result": lambda self: None, "cancel": lambda self: None})()

    config = __import__("industrial_flow.config", fromlist=["AppConfig"]).AppConfig(
        writer={"type": "pubsub", "pubsub": {"project_id": "demo", "subscription_id": "writer"}}
    )
    writer = PubSubPIArchiveWriter.__new__(PubSubPIArchiveWriter)
    writer.config = config
    writer.pubsub_v1 = FakePubSub
    writer.writer = type("Writer", (), {"write": lambda self, request: None})()
    printed = []
    monkeypatch.setattr("industrial_flow.writer.console.print", lambda message: printed.append(message))

    writer.run()

    assert any("Pub/Sub event received message-1 | casa TAG_A" in message for message in printed)