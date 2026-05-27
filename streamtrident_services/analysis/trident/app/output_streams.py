from __future__ import annotations

import json
from typing import Any

import redis


class TridentOutputStreams:
    def __init__(self, redis_url: str, *, assignment_stream: str, alert_stream: str, metrics_stream: str) -> None:
        self.assignment_stream = assignment_stream
        self.alert_stream = alert_stream
        self.metrics_stream = metrics_stream
        self.client = redis.Redis.from_url(redis_url, decode_responses=True)

    def publish_assignments(self, assignments: list[dict[str, Any]]) -> int:
        return self._publish_many(self.assignment_stream, assignments)

    def publish_alerts(self, alerts: list[dict[str, Any]]) -> int:
        return self._publish_many(self.alert_stream, alerts)

    def publish_metrics(self, metrics: dict[str, Any]) -> int:
        if not metrics:
            return 0
        self.client.xadd(self.metrics_stream, _fields(metrics))
        return 1

    def _publish_many(self, stream: str, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self.client.xadd(stream, _fields(row))
        return len(rows)


def _fields(payload: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            fields[key] = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        elif value is None:
            fields[key] = ""
        else:
            fields[key] = str(value)
    return fields
