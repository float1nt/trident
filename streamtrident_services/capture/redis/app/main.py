from __future__ import annotations

import argparse
import json
from typing import Any

import redis

from .config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Redis queue service admin")
    parser.add_argument("command", choices=["ping", "ensure-group", "status"])
    parser.add_argument("--config", default="config/redis.yaml")
    return parser.parse_args()


def _pending_count(payload: Any) -> int:
    if isinstance(payload, dict):
        return int(payload.get("pending", 0) or 0)
    if isinstance(payload, tuple) and payload:
        return int(payload[0] or 0)
    return 0


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    client = redis.Redis.from_url(cfg.url, decode_responses=True)

    if args.command == "ping":
        print(json.dumps({"redis_ok": bool(client.ping())}, separators=(",", ":")))
        return 0

    if args.command == "ensure-group":
        if cfg.queue_type == "list":
            print(json.dumps({"queue": cfg.input_stream, "queue_type": cfg.queue_type, "created": False}, separators=(",", ":")))
            return 0
        created = True
        try:
            client.xgroup_create(cfg.input_stream, cfg.consumer_group, id=cfg.start_id, mkstream=True)
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                created = False
            else:
                raise
        print(json.dumps({"stream": cfg.input_stream, "group": cfg.consumer_group, "created": created}, separators=(",", ":")))
        return 0

    if cfg.queue_type == "list":
        output = {
            "queue": cfg.input_stream,
            "queue_type": cfg.queue_type,
            "llen": int(client.llen(cfg.input_stream)),
            "pending_count": 0,
        }
    else:
        pending = None
        try:
            pending = client.xpending(cfg.input_stream, cfg.consumer_group)
        except Exception as exc:
            pending = {"error": str(exc)}
        output = {
            "stream": cfg.input_stream,
            "queue_type": cfg.queue_type,
            "xlen": int(client.xlen(cfg.input_stream)),
            "group": cfg.consumer_group,
            "pending_count": _pending_count(pending),
            "pending": pending,
        }
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
