from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def resolve_display_timezone(name: str | None = None) -> ZoneInfo:
    raw = (
        (name or "").strip()
        or os.getenv("TRIDENT_DISPLAY_TIMEZONE", "").strip()
        or os.getenv("TZ", "").strip()
        or "UTC"
    )
    try:
        return ZoneInfo(raw)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def display_timezone_name(name: str | None = None) -> str:
    return str(resolve_display_timezone(name))


def to_utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def bucket_key(value: datetime, display_tz: ZoneInfo) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(display_tz).strftime("%Y-%m-%d %H:%M:%S")


def parse_bucket_start(value: Any, *, display_tz: ZoneInfo) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=display_tz)
    else:
        parsed = parsed.astimezone(display_tz)
    return parsed.replace(hour=0, minute=0, second=0, microsecond=0)


def format_display_time(value: Any, display_tz: ZoneInfo) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return ""
        if "T" in text:
            text = text.replace("T", " ")
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            if "+" in text:
                text = text.split("+", 1)[0].strip()
            if "." in text:
                text = text.split(".", 1)[0]
            return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(display_tz).strftime("%Y-%m-%d %H:%M:%S")
