from __future__ import annotations

from app.redis_consumer import RedisStreamConsumer


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def xread(self, streams: dict[str, str], *, count: int, block: int) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        self.calls.append(("xread", {"streams": streams, "count": count, "block": block}))
        return [("suricata:cic_flow", [("1-0", {"src_ip": "10.0.0.1"})])]


def test_best_effort_read_uses_plain_xread() -> None:
    consumer = RedisStreamConsumer(
        "redis://localhost:6379/0",
        stream="suricata:cic_flow",
        group="trident-online",
        consumer="trident-01",
    )
    fake = FakeRedis()
    consumer.client = fake  # type: ignore[assignment]

    messages = consumer.read_best_effort(last_id="$", count=10, block_ms=1000)

    assert fake.calls == [
        ("xread", {"streams": {"suricata:cic_flow": "$"}, "count": 10, "block": 1000})
    ]
    assert messages[0].message_id == "1-0"
    assert messages[0].fields == {"src_ip": "10.0.0.1"}
