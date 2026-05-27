from __future__ import annotations

from typing import Mapping

import redis


class RedisStreamPublisher:
    def __init__(self, redis_url: str, stream: str, *, maxlen: int) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._stream = stream
        self._maxlen = maxlen

    def ping(self) -> bool:
        return bool(self._client.ping())

    def publish(self, fields: Mapping[str, str]) -> str:
        return str(self._client.xadd(self._stream, dict(fields), maxlen=self._maxlen, approximate=True))

