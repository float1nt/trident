from __future__ import annotations

from app.redis_consumer import RedisListConsumer, RedisStreamConsumer


class FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def xread(self, streams: dict[str, str], *, count: int, block: int) -> list[tuple[str, list[tuple[str, dict[str, str]]]]]:
        self.calls.append(("xread", {"streams": streams, "count": count, "block": block}))
        return [("suricata:cic_flow", [("1-0", {"src_ip": "10.0.0.1"})])]


class FakeListRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.values = ["newer", "older"]

    def brpop(self, key: str, *, timeout: int) -> tuple[str, str] | None:
        self.calls.append(("brpop", {"key": key, "timeout": timeout}))
        return (key, self.values.pop())

    def rpop(self, key: str) -> str | None:
        self.calls.append(("rpop", {"key": key}))
        if not self.values:
            return None
        return self.values.pop()

    def ltrim(self, key: str, start: int, end: int) -> None:
        self.calls.append(("ltrim", {"key": key, "start": start, "end": end}))


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


def test_list_read_pops_from_right_and_wraps_raw_event() -> None:
    consumer = RedisListConsumer("redis://localhost:6379/0", key="suricata:cic_flow")
    fake = FakeListRedis()
    consumer.client = fake  # type: ignore[assignment]

    messages = consumer.read_pop(count=10, block_ms=1000)

    assert fake.calls == [
        ("brpop", {"key": "suricata:cic_flow", "timeout": 1}),
        ("rpop", {"key": "suricata:cic_flow"}),
        ("rpop", {"key": "suricata:cic_flow"}),
    ]
    assert [message.fields for message in messages] == [{"eve": "older"}, {"eve": "newer"}]


def test_list_trim_keeps_newest_left_side_items() -> None:
    consumer = RedisListConsumer("redis://localhost:6379/0", key="suricata:cic_flow")
    fake = FakeListRedis()
    consumer.client = fake  # type: ignore[assignment]

    consumer.trim_to_maxlen(100)

    assert fake.calls == [
        ("ltrim", {"key": "suricata:cic_flow", "start": 0, "end": 99})
    ]
