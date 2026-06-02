from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.timezone_utils import (
    bucket_key,
    format_display_time,
    resolve_display_timezone,
    to_utc_iso,
)


def test_resolve_display_timezone_defaults_to_utc() -> None:
    assert str(resolve_display_timezone(None)) == "UTC"
    assert str(resolve_display_timezone("")) == "UTC"


def test_to_utc_iso_converts_local_instant() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    local = datetime(2026, 6, 1, 16, 30, tzinfo=shanghai)
    assert to_utc_iso(local) == "2026-06-01T08:30:00Z"


def test_bucket_key_uses_display_timezone() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    utc = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    assert bucket_key(utc, shanghai) == "2026-06-01 16:00:00"


def test_format_display_time_from_utc_storage() -> None:
    shanghai = ZoneInfo("Asia/Shanghai")
    assert format_display_time("2026-06-01T08:00:00Z", shanghai) == "2026-06-01 16:00:00"


@patch("app.page_queries.datetime")
def test_time_range_bounds_24h_in_shanghai(mock_datetime) -> None:
    from app.page_queries import _time_range_bounds

    shanghai = ZoneInfo("Asia/Shanghai")
    fixed = datetime(2026, 6, 1, 15, 30, tzinfo=shanghai)
    mock_datetime.now.side_effect = lambda tz=None: fixed

    bounds = _time_range_bounds("24h", display_tz=shanghai)

    assert bounds["time_to"] == "2026-06-01T07:30:00Z"
    assert bounds["time_from"] == "2026-05-31T08:00:00Z"
