from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd


def csv_row_to_eve(row: pd.Series) -> dict:
    payload = {str(k): row[k] for k in row.index if pd.notna(row[k])}
    payload["event_type"] = "cic_flow"
    if "Timestamp" in payload:
        payload["timestamp"] = str(payload["Timestamp"])
    return payload


def inject_csv_to_redis(
    *,
    repo_root: Path,
    csv: str = "data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv",
    max_rows: int = 10000,
    url: str = "redis://127.0.0.1:6379/0",
    stream: str = "suricata:cic_flow",
    stream_maxlen: int = 100000,
    batch_size: int = 500,
    clear_stream: bool = True,
    logger: Optional[Any] = None,
) -> Dict[str, Any]:
    try:
        import redis  # type: ignore
    except ImportError as exc:
        raise SystemExit("Install redis: pip install redis") from exc

    csv_path = Path(csv).expanduser()
    if not csv_path.is_absolute():
        csv_path = (repo_root / csv_path).resolve()
    else:
        csv_path = csv_path.resolve()
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    df = pd.read_csv(csv_path, low_memory=False, nrows=max(0, int(max_rows)))
    if df.empty:
        raise SystemExit("No rows to inject.")

    client = redis.Redis.from_url(url, decode_responses=True)
    client.ping()

    if clear_stream:
        try:
            client.delete(stream)
        except Exception:
            pass

    t0 = time.perf_counter()
    injected = 0
    pipe = client.pipeline(transaction=False)
    for _, row in df.iterrows():
        eve = csv_row_to_eve(row)
        pipe.xadd(
            stream,
            {"message": json.dumps(eve, ensure_ascii=False)},
            maxlen=int(stream_maxlen),
            approximate=True,
        )
        injected += 1
        if injected % int(batch_size) == 0:
            pipe.execute()
            pipe = client.pipeline(transaction=False)
            msg = f"  injected {injected}/{len(df)}"
            if logger:
                logger.info(msg)
            else:
                print(msg, flush=True)
    if injected % int(batch_size) != 0:
        pipe.execute()

    elapsed = time.perf_counter() - t0
    length = client.xlen(stream)
    summary = {
        "csv": str(csv_path),
        "injected_rows": injected,
        "stream": stream,
        "stream_length": int(length),
        "inject_seconds": round(elapsed, 4),
        "rows_per_second": round(injected / elapsed, 2) if elapsed > 0 else None,
    }
    if logger:
        logger.info("Inject complete: %s", json.dumps(summary, ensure_ascii=False))
    return summary
