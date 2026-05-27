#!/usr/bin/env python3
"""Route B: UDP inject for V3-ui-2 using experiment sampling + Redis metadata inject."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import redis
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
EVAL_PATH = Path(__file__).resolve().parent / "run_accuracy_eval.py"

SESSION_ID = "trident-session-dev"
STREAM = "suricata:cic_flow"
REDIS_URL = "redis://127.0.0.1:16379/0"
CLICKHOUSE_DSN = "http://default:trident@127.0.0.1:18123/default"
API_URL = "http://127.0.0.1:8090"
DEFAULT_OUT = ROOT / "outputs" / "streamtrident_udp_ui_inject"

# Same label plan as run_accuracy_eval.py STRICT_LABEL_SPECS (user targets).
UI_LABEL_SPECS = [
    {
        "name": "BENIGN",
        "path": Path("/home/data/2017/monday.csv"),
        "labels": {"BENIGN"},
        "target": 20_000,
    },
    {
        "name": "PORTSCAN",
        "path": Path("/home/data/2017/friday.csv"),
        "labels": {"Portscan"},
        "target": 10_000,
    },
    {
        "name": "DDOS",
        "path": Path("/home/data/2017/friday.csv"),
        "labels": {"DDoS"},
        "target": 10_000,
    },
    {
        "name": "DOS_HULK",
        "path": Path("/home/data/2017/wednesday.csv"),
        "labels": {"DoS Hulk"},
        "target": 10_000,
    },
    {
        "name": "SYN",
        "path": Path("/home/data/2019/Syn.csv"),
        "labels": {"Syn"},
        "target": 10_000,
    },
    {
        "name": "DRDOS_DNS",
        "path": Path("/home/data/2019/DrDoS_DNS.csv"),
        "labels": {"DrDoS_DNS"},
        "target": 10_000,
    },
    {
        "name": "DRDOS_NTP",
        "path": Path("/home/data/2019/DrDoS_NTP.csv"),
        "labels": {"DrDoS_NTP"},
        "target": 10_000,
    },
]


def load_eval_module():
    spec = importlib.util.spec_from_file_location("accuracy_eval", EVAL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {EVAL_PATH}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["accuracy_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


def shift_metadata_times(path: Path, *, hours_back: float = 6.0) -> None:
    rows: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    if not rows:
        return
    now = datetime.now(timezone.utc)
    span = timedelta(hours=hours_back)
    n = len(rows)
    for i, row in enumerate(rows):
        offset = span * (i / max(n - 1, 1))
        ts = now - offset
        row["event_time"] = ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ch_count(sql: str) -> int:
    import subprocess

    try:
        proc = subprocess.run(
            ["docker", "exec", "streamtrident-clickhouse", "clickhouse-client", "--query", sql],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        return int(proc.stdout.strip() or "0")
    except Exception:
        eval_mod = load_eval_module()
        return eval_mod.clickhouse_count(sql)


def wait_assigned(eval_mod, *, expected: int, timeout: int) -> dict:
    start = time.time()
    last = -1
    polls = 0
    sid = SESSION_ID
    while time.time() - start < timeout:
        assigned = ch_count(
            f"SELECT count() FROM ch_flow FINAL WHERE session_id = '{sid}' AND record_stage = 'assigned'"
        )
        processed = ch_count(f"SELECT count() FROM ch_flow FINAL WHERE session_id = '{sid}'")
        polls += 1
        if processed != last:
            print(
                json.dumps(
                    {
                        "event": "processing_progress",
                        "assigned": assigned,
                        "processed": processed,
                        "expected": expected,
                        "poll": polls,
                    },
                    ensure_ascii=False,
                )
            )
            last = processed
        if assigned >= int(expected * 0.95):
            return {
                "assigned": assigned,
                "processed": processed,
                "timed_out": False,
                "polls": polls,
                "elapsed": round(time.time() - start, 1),
            }
        time.sleep(5)
    assigned = ch_count(
        f"SELECT count() FROM ch_flow FINAL WHERE session_id = '{SESSION_ID}' AND record_stage = 'assigned'"
    )
    return {
        "assigned": assigned,
        "processed": last,
        "timed_out": True,
        "polls": polls,
        "elapsed": round(time.time() - start, 1),
    }


def check_api() -> dict:
    session = requests.Session()
    session.trust_env = False
    out = {}
    for path in (
        "/overview/metrics?time_range=24h",
        "/overview/distributions?time_range=24h",
        "/risks?limit=5",
        "/api/v1/learners?limit=20",
    ):
        try:
            resp = session.get(f"{API_URL}{path}", timeout=20)
            out[path] = {"status": resp.status_code, "data": resp.json().get("data") if resp.ok else resp.text[:200]}
        except Exception as exc:
            out[path] = {"error": str(exc)}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="UDP UI inject (experiment sampler + trident-session-dev)")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--hours-back", type=float, default=6.0, help="Spread event_time over last N hours for 24h UI filter")
    parser.add_argument("--dry-run", action="store_true", help="Only build flow_labels.csv, do not inject")
    args = parser.parse_args()

    eval_mod = load_eval_module()
    run_id = f"ui-udp-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    run_dir = Path(args.out_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    for spec in UI_LABEL_SPECS:
        if not Path(spec["path"]).exists():
            print(f"Missing CSV: {spec['path']}", file=sys.stderr)
            return 1

    plan = eval_mod.ExperimentPlan("udp_ui", 17, UI_LABEL_SPECS)
    metadata_path = run_dir / "flow_labels.csv"
    print(f"[ui-inject] building UDP dataset -> {metadata_path}")
    dataset_summary = eval_mod.build_dataset(plan, metadata_path)
    eval_mod.write_json(run_dir / "dataset_summary.json", dataset_summary)

    shift_metadata_times(metadata_path, hours_back=args.hours_back)
    total_rows = int(dataset_summary["total_rows"])
    per_label = dataset_summary.get("per_label") or {}
    print(f"[ui-inject] dataset rows={total_rows} per_label={json.dumps(per_label, ensure_ascii=False)}")

    shortfall = []
    for spec in UI_LABEL_SPECS:
        name = spec["name"]
        got = int(per_label.get(name, 0))
        want = int(spec["target"])
        if got < want:
            shortfall.append(f"{name}: got {got}, wanted {want} (CICIDS2017 UDP scarce for some attack labels)")
    if shortfall:
        print("[ui-inject] WARN UDP shortfall:")
        for line in shortfall:
            print(f"  - {line}")

    manifest = {
        "run_id": run_id,
        "session_id": SESSION_ID,
        "protocol_filter": 17,
        "dataset_summary": dataset_summary,
        "shortfall": shortfall,
        "ui_url": "http://localhost:5175/",
    }
    if args.dry_run:
        eval_mod.write_json(run_dir / "manifest.json", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0

    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    print(f"[ui-inject] injecting {total_rows} rows into {STREAM} session={SESSION_ID}")
    t0 = time.perf_counter()
    injected = eval_mod.inject_metadata(metadata_path, redis_client, session_id=SESSION_ID, stream=STREAM)
    inject_seconds = round(time.perf_counter() - t0, 2)
    print(f"[ui-inject] redis injected={injected} in {inject_seconds}s")

    print(f"[ui-inject] waiting for streamtrident-worker (timeout={args.timeout}s)")
    wait_summary = wait_assigned(eval_mod, expected=injected, timeout=args.timeout)
    manifest["inject"] = {"injected": injected, "inject_seconds": inject_seconds, "wait": wait_summary}
    manifest["api"] = check_api()
    eval_mod.write_json(run_dir / "manifest.json", manifest)
    eval_mod.write_json(run_dir / "result.json", manifest)

    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    if wait_summary.get("timed_out"):
        print("[ui-inject] timed out before 95% assigned", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
