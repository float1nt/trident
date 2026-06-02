from __future__ import annotations

from urllib import parse

from app.persistence.clickhouse_http import _query_url


def test_clickhouse_dsn_path_becomes_database_parameter() -> None:
    url = _query_url("http://127.0.0.1:8123/default", "SELECT 1")
    parsed = parse.urlsplit(url)
    params = dict(parse.parse_qsl(parsed.query))

    assert parsed.path == "/"
    assert params["database"] == "default"
    assert params["session_timezone"] == "UTC"
    assert params["date_time_input_format"] == "best_effort"
    assert params["query"] == "SELECT 1"


def test_clickhouse_dsn_credentials_become_query_parameters() -> None:
    url = _query_url("http://default:trident@clickhouse:8123/default", "SELECT 1")
    parsed = parse.urlsplit(url)
    params = dict(parse.parse_qsl(parsed.query))

    assert parsed.netloc == "clickhouse:8123"
    assert params["user"] == "default"
    assert params["password"] == "trident"
    assert params["database"] == "default"


def test_clickhouse_client_uses_display_timezone() -> None:
    from app.persistence.clickhouse_http import ClickHouseHTTPClient

    client = ClickHouseHTTPClient("http://127.0.0.1:8123/default", session_timezone="Asia/Shanghai")
    url = _query_url(client.dsn, "SELECT 1", session_timezone=client.session_timezone)
    parsed = parse.urlsplit(url)
    params = dict(parse.parse_qsl(parsed.query))

    assert params["session_timezone"] == "Asia/Shanghai"


def test_clickhouse_dsn_can_override_time_settings() -> None:
    url = _query_url("http://127.0.0.1:8123/default?session_timezone=Asia%2FShanghai", "SELECT 1")
    parsed = parse.urlsplit(url)
    params = dict(parse.parse_qsl(parsed.query))

    assert params["session_timezone"] == "Asia/Shanghai"
    assert params["date_time_input_format"] == "best_effort"
