#!/usr/bin/env python3
"""Inject static CIC CSV rows into the Suricata Redis Stream (cic_flow EVE format).

Used for offline replay testing: static CSV → Redis Stream → Trident (input.source=redis).

Example:
  python3 scripts/inject_csv_to_suricata_redis.py --max-rows 10000
  python3 scripts/inject_csv_to_suricata_redis.py --csv /home/data/cicids2026.csv --clear-stream
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def csv_row_to_eve(row: pd.Series) -> dict:
    payload = {str(k): row[k] for k in row.index if pd.notna(row[k])}
    payload["event_type"] = "cic_flow"
    if "Timestamp" in payload:
        payload["timestamp"] = str(payload["Timestamp"])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=str, default="/home/data/live_merged_all.csv")
    parser.add_argument("--max-rows", type=int, default=10000)
    parser.add_argument("--url", type=str, default="redis://127.0.0.1:6379/0")
    parser.add_argument("--stream", type=str, default="suricata:cic_flow")
    parser.add_argument("--stream-maxlen", type=int, default=100000)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--clear-stream", action="store_true")
    args = parser.parse_args()

    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise SystemExit("Install redis: pip install redis") from exc

    csv_path = Path(args.csv).expanduser()
    if not csv_path.is_absolute():
        csv_path = (ROOT / csv_path).resolve()
    else:
        csv_path = csv_path.resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path, low_memory=False, nrows=max(0, int(args.max_rows)))
    if df.empty:
        raise SystemExit("No rows to inject.")

    client = redis.Redis.from_url(args.url, decode_responses=True)
    client.ping()

    if args.clear_stream:
        try:
            client.delete(args.stream)
        except Exception:
            pass

    t0 = time.perf_counter()
    injected = 0
    pipe = client.pipeline(transaction=False)
    for i, row in df.iterrows():
        eve = csv_row_to_eve(row)
        pipe.xadd(
            args.stream,
            {"message": json.dumps(eve, ensure_ascii=False)},
            maxlen=int(args.stream_maxlen),
            approximate=True,
        )
        injected += 1
        if injected % int(args.batch_size) == 0:
            pipe.execute()
            pipe = client.pipeline(transaction=False)
            print(f"  injected {injected}/{len(df)}", flush=True)
    if injected % int(args.batch_size) != 0:
        pipe.execute()

    elapsed = time.perf_counter() - t0
    length = client.xlen(args.stream)
    print(
        json.dumps(
            {
                "csv": str(csv_path),
                "injected_rows": injected,
                "stream": args.stream,
                "stream_length": int(length),
                "inject_seconds": round(elapsed, 4),
                "rows_per_second": round(injected / elapsed, 2) if elapsed > 0 else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
