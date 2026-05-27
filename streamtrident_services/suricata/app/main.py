from __future__ import annotations

import argparse
import json
import sys

from .config import load_config
from .normalizer import normalize_event
from .publisher import RedisStreamPublisher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Suricata flow JSON to Redis Stream writer")
    parser.add_argument("--config", default="config/suricata.yaml")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = load_config(args.config)
    publisher = RedisStreamPublisher(cfg.redis_url, cfg.output_stream, maxlen=cfg.stream_maxlen)
    publisher.ping()

    count = 0
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        fields = normalize_event(payload, event_type=cfg.event_type, session_id=cfg.session_id)
        stream_id = publisher.publish(fields)
        count += 1
        print(json.dumps({"stream": cfg.output_stream, "id": stream_id, "count": count}, separators=(",", ":")), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

