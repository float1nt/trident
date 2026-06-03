from __future__ import annotations

import redis

from app.config import TridentConfig
from app import worker


class FailingListConsumer:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def trim_to_maxlen(self, _maxlen: int) -> None:
        raise self.exc


def test_list_input_timeout_logs_and_keeps_worker_alive(monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(worker, "emit_event", lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(worker, "sleep", lambda _seconds: None)

    messages = worker._read_input_messages(
        FailingListConsumer(redis.TimeoutError("Timeout connecting to server")),
        cfg=TridentConfig(queue_type="list", redis_url="redis://192.0.2.1:16379/0"),
        reliable_consumer=False,
        last_id="$",
    )

    assert messages == ([], "$")
    assert events == [
        (
            "worker_redis_unavailable",
            {
                "session_id": "trident-session-dev",
                "input_stream": "suricata:cic_flow",
                "queue_type": "list",
                "redis_url": "redis://192.0.2.1:16379/0",
                "operation": "list_read",
                "error_type": "TimeoutError",
                "error": "Timeout connecting to server",
                "retry_delay_seconds": 5.0,
            },
        )
    ]


def test_list_input_wrong_type_logs_specific_event(monkeypatch) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(worker, "emit_event", lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(worker, "sleep", lambda _seconds: None)

    messages = worker._read_input_messages(
        FailingListConsumer(redis.ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value")),
        cfg=TridentConfig(queue_type="list"),
        reliable_consumer=False,
        last_id="$",
    )

    assert messages == ([], "$")
    assert events[0][0] == "worker_redis_wrong_type"
    assert events[0][1]["operation"] == "list_read"
    assert events[0][1]["error_type"] == "ResponseError"
