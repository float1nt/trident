from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib import parse, request


@dataclass(frozen=True, slots=True)
class ClickHouseHTTPClient:
    dsn: str
    timeout: float = 10.0

    def execute(self, sql: str) -> str:
        req = request.Request(_query_url(self.dsn, sql), data=b"", method="POST")
        with request.urlopen(req, timeout=self.timeout) as response:
            return response.read().decode("utf-8")

    def insert_json_each_row(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        sql = f"INSERT INTO {table} FORMAT JSONEachRow"
        body = "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) for row in rows).encode("utf-8")
        req = request.Request(_query_url(self.dsn, sql), data=body, method="POST")
        req.add_header("Content-Type", "application/x-ndjson")
        with request.urlopen(req, timeout=self.timeout) as response:
            response.read()


def _query_url(dsn: str, sql: str) -> str:
    parsed = parse.urlsplit(dsn)
    params = dict(parse.parse_qsl(parsed.query, keep_blank_values=True))
    if parsed.username:
        params.setdefault("user", parse.unquote(parsed.username))
    if parsed.password:
        params.setdefault("password", parse.unquote(parsed.password))
    path = parsed.path
    if path and path != "/":
        params.setdefault("database", path.strip("/"))
        path = "/"
    params["query"] = sql
    netloc = parsed.hostname or ""
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return parse.urlunsplit(
        (
            parsed.scheme,
            netloc,
            path or "/",
            parse.urlencode(params),
            parsed.fragment,
        )
    )
