from __future__ import annotations

from dataclasses import dataclass
from time import time_ns
from typing import Any, Mapping

import redis


@dataclass(frozen=True, slots=True)
class RedisStreamMessage:
    stream: str
    message_id: str
    fields: dict[str, Any]


class RedisStreamConsumer:
    def __init__(
        self,
        redis_url: str,
        *,
        stream: str,
        group: str,
        consumer: str,
        decode_responses: bool = True,
    ) -> None:
        self.stream = stream
        self.group = group
        self.consumer = consumer
        self.client = redis.Redis.from_url(redis_url, decode_responses=decode_responses)

    def ensure_group(self) -> None:
        try:
            self.client.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def read_new(self, *, count: int, block_ms: int) -> list[RedisStreamMessage]:
        batch = self.client.xreadgroup(
            self.group,
            self.consumer,
            {self.stream: ">"},
            count=count,
            block=block_ms,
        )
        return _flatten_messages(batch)

    def read_best_effort(self, *, last_id: str, count: int, block_ms: int) -> list[RedisStreamMessage]:
        batch = self.client.xread(
            {self.stream: last_id},
            count=count,
            block=block_ms,
        )
        return _flatten_messages(batch)

    def read_pending(self, *, count: int) -> list[RedisStreamMessage]:
        batch = self.client.xreadgroup(
            self.group,
            self.consumer,
            {self.stream: "0"},
            count=count,
        )
        return _flatten_messages(batch)

    def autoclaim(self, *, min_idle_ms: int, start_id: str = "0-0", count: int = 100) -> list[RedisStreamMessage]:
        result = self.client.xautoclaim(
            self.stream,
            self.group,
            self.consumer,
            min_idle_time=min_idle_ms,
            start_id=start_id,
            count=count,
        )
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            return _flatten_messages([(self.stream, result[1])])
        return []

    def ack(self, messages: list[RedisStreamMessage]) -> int:
        ids_by_stream: dict[str, list[str]] = {}
        for message in messages:
            ids_by_stream.setdefault(message.stream, []).append(message.message_id)

        acked = 0
        for stream, ids in ids_by_stream.items():
            if ids:
                acked += int(self.client.xack(stream, self.group, *ids))
        return acked

    def xlen(self) -> int:
        return int(self.client.xlen(self.stream))

    def pending_count(self) -> int:
        pending = self.client.xpending(self.stream, self.group)
        if isinstance(pending, Mapping):
            return int(pending.get("pending", 0))
        if isinstance(pending, (list, tuple)) and pending:
            return int(pending[0])
        return 0

    def ping(self) -> bool:
        return bool(self.client.ping())


class RedisListConsumer:
    def __init__(
        self,
        redis_url: str,
        *,
        key: str,
        decode_responses: bool = True,
    ) -> None:
        self.key = key
        self.client = redis.Redis.from_url(redis_url, decode_responses=decode_responses)
        self._sequence = 0

    def read_pop(self, *, count: int, block_ms: int) -> list[RedisStreamMessage]:
        timeout = max(1, int((block_ms + 999) / 1000))
        first = self.client.brpop(self.key, timeout=timeout)
        if not first:
            return []
        values = [_list_value(first)]
        while len(values) < count:
            value = self.client.rpop(self.key)
            if value is None:
                break
            values.append(str(value))
        return [self._message(value) for value in values]

    def trim_to_maxlen(self, maxlen: int) -> None:
        if maxlen <= 0:
            return
        self.client.ltrim(self.key, 0, maxlen - 1)

    def xlen(self) -> int:
        return int(self.client.llen(self.key))

    def pending_count(self) -> int:
        return 0

    def ping(self) -> bool:
        return bool(self.client.ping())

    def _message(self, value: str) -> RedisStreamMessage:
        self._sequence += 1
        message_id = f"{time_ns() // 1_000_000}-{self._sequence}"
        return RedisStreamMessage(
            stream=self.key,
            message_id=message_id,
            fields={"eve": value},
        )


def _flatten_messages(batch: Any) -> list[RedisStreamMessage]:
    messages: list[RedisStreamMessage] = []
    for stream, stream_messages in batch or []:
        for message_id, fields in stream_messages:
            messages.append(
                RedisStreamMessage(
                    stream=str(stream),
                    message_id=str(message_id),
                    fields=dict(fields or {}),
                )
            )
    return messages


def _list_value(item: Any) -> str:
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return str(item[1])
    return str(item)
