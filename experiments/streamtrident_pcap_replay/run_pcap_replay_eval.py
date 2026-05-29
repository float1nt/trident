#!/usr/bin/env python3
"""PCAP replay E2E: tcpreplay -> Suricata (live) -> Redis -> Trident worker."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import parse

import redis
import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = ROOT / "streamtrident_services"
TRIDENT_ROOT = SERVICE_ROOT / "analysis" / "trident"
DOCKER_TRIDENT_CONFIG = SERVICE_ROOT / "analysis" / "docker" / "trident.yaml"
DEFAULT_OUT_ROOT = ROOT / "outputs" / "streamtrident_pcap_replay"

DEFAULT_MONDAY_SRC = Path("/home/sr/HyperVision-main/test_file/Monday-WorkingHours.pcap")
DEFAULT_TUESDAY_SRC = Path("/home/sr/HyperVision-main/test_file/Tuesday-WorkingHours.pcap")
PCAP_OUT_DIR = ROOT / "experiments" / "streamtrident_pcap_replay" / "pcaps"
DEFAULT_MONDAY_PCAP = PCAP_OUT_DIR / "Monday-WorkingHours.mtu1500.pcap"
DEFAULT_TUESDAY_PCAP = PCAP_OUT_DIR / "Tuesday-WorkingHours.mtu1500.pcap"

STREAM = "suricata:cic_flow"
REDIS_URL = "redis://127.0.0.1:16379/0"
CLICKHOUSE_DSN = "http://default:trident@127.0.0.1:18123/default"
POSTGRES_DSN = "postgresql://trident:trident@127.0.0.1:15432/trident"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def quote(value: str) -> str:
    return "'" + str(value).replace("'", "\\'") + "'"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def python_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(TRIDENT_ROOT) + (os.pathsep + current if current else "")
    log_dir = DEFAULT_OUT_ROOT / ".logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    env["TRIDENT_LOG_DIR"] = str(log_dir)
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)
    return env


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    print(json.dumps({"event": "run", "cmd": cmd, "cwd": str(cwd)}, ensure_ascii=False))
    return subprocess.run(cmd, cwd=str(cwd), env=env, check=check, text=True)


def terminate(proc: subprocess.Popen[Any]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def clickhouse_execute(sql: str) -> str:
    session = requests.Session()
    session.trust_env = False
    parsed = parse.urlsplit(CLICKHOUSE_DSN)
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
    url = parse.urlunsplit((parsed.scheme, netloc, path or "/", parse.urlencode(params), parsed.fragment))
    response = session.post(url, data=b"", timeout=120)
    response.raise_for_status()
    return response.text


def clickhouse_count(sql: str) -> int:
    text = clickhouse_execute(sql)
    try:
        return int(str(text).strip().splitlines()[0])
    except Exception:
        return 0


def count_session_flows(session_id: str) -> dict[str, int]:
    sid = quote(session_id)
    processed = clickhouse_count(f"SELECT count() FROM ch_flow FINAL WHERE session_id = {sid}")
    assigned = clickhouse_count(
        f"SELECT count() FROM ch_flow FINAL WHERE session_id = {sid} AND record_stage = 'assigned'"
    )
    unknown = clickhouse_count(
        f"SELECT count() FROM ch_flow FINAL WHERE session_id = {sid} AND is_unknown = 1"
    )
    return {"processed": processed, "assigned": assigned, "unknown": unknown}


def wait_for_processing(*, session_id: str, expected: int, timeout: int, stage: str) -> dict[str, int]:
    start = time.time()
    last = -1
    while time.time() - start < timeout:
        stats = count_session_flows(session_id)
        processed = stats["processed"]
        if processed != last:
            print(
                json.dumps(
                    {
                        "event": "processing_progress",
                        "stage": stage,
                        "session_id": session_id,
                        **stats,
                        "expected": expected,
                    },
                    ensure_ascii=False,
                )
            )
            last = processed
        if processed >= expected:
            return stats
        time.sleep(5)
    raise TimeoutError(f"timeout stage={stage} session={session_id} processed={last} expected={expected}")


def wait_for_idle(*, session_id: str, timeout: int, stage: str, stable_seconds: float = 30.0) -> dict[str, int]:
    start = time.time()
    stable_start: float | None = None
    last_processed = -1
    while time.time() - start < timeout:
        stats = count_session_flows(session_id)
        processed = stats["processed"]
        if processed == last_processed:
            if stable_start is None:
                stable_start = time.time()
            elif time.time() - stable_start >= stable_seconds:
                print(json.dumps({"event": "processing_idle", "stage": stage, "session_id": session_id, **stats}))
                return stats
        else:
            stable_start = None
            print(json.dumps({"event": "processing_progress", "stage": stage, "session_id": session_id, **stats}))
            last_processed = processed
        time.sleep(5)
    raise TimeoutError(f"timeout waiting for idle stage={stage} session={session_id}")


def wait_for_deps() -> None:
    deadline = time.time() + 240
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    while time.time() < deadline:
        try:
            client.ping()
            clickhouse_count("SELECT 1")
            return
        except Exception:
            time.sleep(2)
    raise TimeoutError("dependencies did not become ready")


def write_config(path: Path, *, session_id: str, model_store: Path, best_effort_start_id: str) -> None:
    payload = {
        "redis_url": REDIS_URL,
        "input_stream": STREAM,
        "consumer_group": "trident-online",
        "consumer_name": f"pcap-replay-{uuid.uuid4().hex[:8]}",
        "consumer_mode": "best_effort",
        "best_effort_start_id": best_effort_start_id,
        "read_count": 2048,
        "block_ms": 1000,
        "ack": True,
        "session_id": session_id,
        "window_size": 10000,
        "feature_profile": "compact_stats_no_env",
        "clickhouse_dsn": CLICKHOUSE_DSN,
        "postgres_dsn": POSTGRES_DSN,
        "assignment_stream": "trident:assignments",
        "alert_stream": "trident:alerts",
        "metrics_stream": "trident:metrics",
        "redis_output_enabled": False,
        "process_partial_window": True,
        "algorithm_backend": "ae",
        "cpu_only": True,
        "seed": 42,
        "init_epochs": 5,
        "new_class_epochs": 4,
        "increment_epochs": 1,
        "min_class_samples": 300,
        "max_train_per_class": 20000,
        "max_increment_samples": 1000,
        "increment_min_samples": 1000,
        "new_learner_min_size": 500,
        "cluster_trigger_size": 120,
        "dbscan_eps": 1.3,
        "dbscan_min_samples": 10,
        "max_unknown_buffer": 30000,
        "benign_accept_scale": 0.34,
        "benign_history_confidence_scale": 1.0,
        "increment_drift_min_history_samples": 500,
        "increment_route_min_samples": 1000,
        "increment_iforest_guard_min_samples": 1000,
        "model_store_dir": str(model_store),
        "preprocessing_enabled": True,
        "preprocessing_drop_all_zero": False,
        "small_learner_recluster_enabled": False,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def sync_docker_session(session_id: str) -> None:
    if not DOCKER_TRIDENT_CONFIG.is_file():
        return
    lines = DOCKER_TRIDENT_CONFIG.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.startswith("session_id:"):
            out.append(f"session_id: {session_id}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.insert(0, f"session_id: {session_id}")
    DOCKER_TRIDENT_CONFIG.write_text("\n".join(out) + "\n", encoding="utf-8")


def build_tcpreplay_cmd(*, pcap: Path, iface: str, mbps: float, loop: int = 1, use_docker: bool = True) -> list[str]:
    inner = ["tcpreplay", "-i", iface]
    if mbps > 0:
        inner.extend(["--mbps", str(mbps)])
    if loop > 1:
        inner.extend(["--loop", str(loop)])
    inner.append(str(pcap))

    if not use_docker:
        return inner

    mount_dir = str(pcap.parent.resolve())
    container_pcap = f"/pcap/{pcap.name}"
    inner[-1] = container_pcap
    return [
        "docker",
        "run",
        "--rm",
        "--net=host",
        "--cap-add=NET_RAW",
        "--cap-add=NET_ADMIN",
        "-v",
        f"{mount_dir}:/pcap:ro",
        "trident-tcpreplay:local",
        *inner,
    ]


def replay_until_flow_target(
    *,
    pcap: Path,
    iface: str,
    mbps: float,
    session_id: str,
    target_flows: int,
    log_path: Path,
    poll_seconds: float = 2.0,
) -> dict[str, Any]:
    cmd = build_tcpreplay_cmd(pcap=pcap, iface=iface, mbps=mbps, loop=1000)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.Popen(
            cmd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            while proc.poll() is None:
                stats = count_session_flows(session_id)
                if stats["processed"] >= target_flows:
                    print(
                        json.dumps(
                            {
                                "event": "replay_target_reached",
                                "pcap": str(pcap),
                                "target_flows": target_flows,
                                **stats,
                            },
                            ensure_ascii=False,
                        )
                    )
                    break
                time.sleep(poll_seconds)
        finally:
            terminate(proc)
    elapsed = time.perf_counter() - started
    stats = count_session_flows(session_id)
    return {
        "pcap": str(pcap),
        "target_flows": target_flows,
        "elapsed_seconds": round(elapsed, 3),
        "processed_after": stats["processed"],
        "stopped_early": stats["processed"] >= target_flows,
    }


def replay_once(*, pcap: Path, iface: str, mbps: float, log_path: Path) -> dict[str, Any]:
    cmd = build_tcpreplay_cmd(pcap=pcap, iface=iface, mbps=mbps, loop=1)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log_handle:
        proc = subprocess.run(cmd, stdout=log_handle, stderr=subprocess.STDOUT, check=False, text=True)
    return {
        "pcap": str(pcap),
        "exit_code": proc.returncode,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def postgres_learner_rows(session_id: str) -> list[dict[str, Any]]:
    cmd = [
        "docker",
        "exec",
        "streamtrident-postgres",
        "psql",
        "-U",
        "trident",
        "-d",
        "trident",
        "-t",
        "-A",
        "-F",
        ",",
        "-c",
        f"SELECT learner_name, flow_count, risk_band, risk_score FROM pg_learner "
        f"WHERE session_id='{session_id}' ORDER BY flow_count DESC;",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    rows: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(",")
        if len(parts) != 4:
            continue
        rows.append(
            {
                "learner_name": parts[0],
                "flow_count": int(parts[1] or 0),
                "risk_band": parts[2],
                "risk_score": float(parts[3] or 0),
            }
        )
    return rows


def prepare_mtu1500_pcap(*, src: Path, dst: Path, mtu: int = 1500) -> dict[str, Any]:
    """Truncate oversize frames with tcprewrite so tcpreplay avoids Message too long."""
    if dst.is_file() and dst.stat().st_size > 0 and dst.stat().st_mtime >= src.stat().st_mtime:
        return {"src": str(src), "dst": str(dst), "skipped": True, "reason": "up_to_date"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    if tmp.is_file():
        tmp.unlink()
    started = time.perf_counter()
    proc = subprocess.run(
        [
            "tcprewrite",
            f"--mtu={mtu}",
            "--mtu-trunc",
            "--fixcsum",
            "-i",
            str(src),
            "-o",
            str(tmp),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"tcprewrite failed for {src}: {proc.stderr or proc.stdout}")
    tmp.replace(dst)
    return {
        "src": str(src),
        "dst": str(dst),
        "skipped": False,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "bytes": dst.stat().st_size,
    }


def ensure_capture_stack(*, iface: str) -> None:
    env = os.environ.copy()
    env["SURICATA_IFACE"] = iface
    run(
        [
            "docker",
            "compose",
            "-f",
            str(SERVICE_ROOT / "compose.yaml"),
            "up",
            "-d",
            "redis",
            "clickhouse",
            "postgres",
            "suricata-cic",
            "suricata-agent",
        ],
        cwd=SERVICE_ROOT,
        env=env,
    )
    run(
        ["docker", "compose", "-f", str(SERVICE_ROOT / "compose.yaml"), "stop", "trident-worker"],
        cwd=SERVICE_ROOT,
        check=False,
    )


def redis_stream_len(client: redis.Redis) -> int:
    try:
        return int(client.xlen(STREAM))
    except Exception:
        return 0


def measure_redis_ingress_rate(*, before_id: str, sample_seconds: float = 10.0) -> float:
    """Count new Redis stream entries after before_id over sample window."""
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    start_len = 0
    try:
        start_len = len(list(client.xrange(STREAM, min=before_id, count=1000000)))
    except Exception:
        start_len = 0
    time.sleep(max(1.0, sample_seconds))
    try:
        end_len = len(list(client.xrange(STREAM, min=before_id, count=1000000)))
    except Exception:
        end_len = start_len
    return max(0.0, (end_len - start_len) / sample_seconds)


def run_preflight(*, iface: str, pcap: Path) -> dict[str, Any]:
    report: dict[str, Any] = {"iface": iface}
    proc = subprocess.run(["ip", "link", "show", iface], capture_output=True, text=True, check=False)
    report["iface_ok"] = proc.returncode == 0
    proc = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", "streamtrident-suricata-cic"],
        capture_output=True,
        text=True,
        check=False,
    )
    report["suricata_running"] = proc.stdout.strip() == "true"
    if "mtu1500" not in pcap.name.lower():
        report["pcap_mtu_warning"] = "PCAP 未标注 mtu1500，建议先运行 --prepare-pcaps"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="PCAP replay E2E experiment (Monday warmup + Tuesday eval)")
    parser.add_argument("--monday-pcap", type=Path, default=DEFAULT_MONDAY_PCAP)
    parser.add_argument("--tuesday-pcap", type=Path, default=DEFAULT_TUESDAY_PCAP)
    parser.add_argument("--monday-src", type=Path, default=DEFAULT_MONDAY_SRC, help="Raw Monday PCAP for --prepare-pcaps")
    parser.add_argument("--tuesday-src", type=Path, default=DEFAULT_TUESDAY_SRC, help="Raw Tuesday PCAP for --prepare-pcaps")
    parser.add_argument("--prepare-pcaps", action="store_true", help="Run tcprewrite MTU1500 truncate and exit")
    parser.add_argument("--skip-prepare-pcaps", action="store_true", help="Do not auto-prepare mtu1500 pcaps before run")
    parser.add_argument("--iface", default="eno1", help="NIC shared by tcpreplay and suricata-cic (host network)")
    parser.add_argument("--warmup-flows", type=int, default=50000, help="Stop Monday replay after this many processed flows")
    parser.add_argument("--warmup-mbps", type=float, default=500.0)
    parser.add_argument("--eval-mbps", type=float, default=500.0)
    parser.add_argument("--settle-seconds", type=float, default=45.0, help="Idle seconds after Tuesday replay before finish")
    parser.add_argument("--timeout", type=int, default=7200)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--skip-deps", action="store_true")
    parser.add_argument("--sync-docker-config", action="store_true", help="Write session_id into analysis/docker/trident.yaml")
    args = parser.parse_args()

    if args.prepare_pcaps:
        results = {
            "monday": prepare_mtu1500_pcap(src=args.monday_src, dst=args.monday_pcap),
            "tuesday": prepare_mtu1500_pcap(src=args.tuesday_src, dst=args.tuesday_pcap),
        }
        print(json.dumps({"event": "prepare_pcaps_done", "results": results}, ensure_ascii=False, indent=2))
        return 0

    if not args.skip_prepare_pcaps:
        for label, src, dst in (
            ("monday", args.monday_src, args.monday_pcap),
            ("tuesday", args.tuesday_src, args.tuesday_pcap),
        ):
            if not src.is_file():
                print(json.dumps({"event": "error", "message": f"{label} src pcap not found", "path": str(src)}))
                return 2
            info = prepare_mtu1500_pcap(src=src, dst=dst)
            print(json.dumps({"event": "prepare_pcap", "label": label, **info}, ensure_ascii=False))

    for label, path in (("monday", args.monday_pcap), ("tuesday", args.tuesday_pcap)):
        if not path.is_file():
            print(json.dumps({"event": "error", "message": f"{label} pcap not found", "path": str(path)}))
            return 2

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    run_root = args.out_root / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    session_id = f"pcap-replay-{uuid.uuid4().hex[:10]}"
    exp_root = run_root / "pcap_monday_tuesday"
    exp_root.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "created_at": utc_now(),
        "session_id": session_id,
        "monday_pcap": str(args.monday_pcap),
        "tuesday_pcap": str(args.tuesday_pcap),
        "iface": args.iface,
        "warmup_flows": args.warmup_flows,
    }
    write_json(run_root / "manifest.json", manifest)

    preflight = run_preflight(iface=args.iface, pcap=args.monday_pcap)
    manifest["preflight"] = preflight
    write_json(run_root / "manifest.json", manifest)
    print(json.dumps({"event": "preflight", **preflight}, ensure_ascii=False))
    if not preflight.get("iface_ok"):
        print(json.dumps({"event": "error", "message": f"interface not found: {args.iface}"}))
        return 2
    if not preflight.get("suricata_running"):
        print(json.dumps({"event": "error", "message": "streamtrident-suricata-cic is not running"}))
        return 2

    if not args.skip_deps:
        ensure_capture_stack(iface=args.iface)
    wait_for_deps()

    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    before_id = redis_client.xinfo_stream(STREAM)["last-generated-id"] if redis_client.exists(STREAM) else "0-0"

    config_path = exp_root / "trident_eval_config.yaml"
    model_store = exp_root / "models"
    write_config(config_path, session_id=session_id, model_store=model_store, best_effort_start_id=before_id)
    run(
        [
            sys.executable,
            "-m",
            "app.migrate",
            "--config",
            str(config_path),
            "--migrations-dir",
            str(TRIDENT_ROOT / "migrations"),
        ],
        cwd=TRIDENT_ROOT,
        env=python_env(),
    )

    worker_log = (exp_root / "worker.log").open("w", encoding="utf-8")
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.worker", "--config", str(config_path)],
        cwd=TRIDENT_ROOT,
        env=python_env(),
        stdout=worker_log,
        stderr=subprocess.STDOUT,
        text=True,
    )

    summary: dict[str, Any] = {"session_id": session_id, "redis_before_id": before_id}
    try:
        time.sleep(3.0)
        print(json.dumps({"event": "phase_start", "phase": "warmup_monday"}, ensure_ascii=False))
        summary["warmup_replay"] = replay_until_flow_target(
            pcap=args.monday_pcap,
            iface=args.iface,
            mbps=args.warmup_mbps,
            session_id=session_id,
            target_flows=args.warmup_flows,
            log_path=exp_root / "warmup_replay.log",
        )
        summary["warmup_replay"]["redis_ingress_rate"] = round(
            measure_redis_ingress_rate(before_id=before_id, sample_seconds=10.0),
            3,
        )
        warmup_stats = wait_for_processing(
            session_id=session_id,
            expected=args.warmup_flows,
            timeout=args.timeout,
            stage="warmup",
        )
        summary["warmup_stats"] = warmup_stats
        warmup_processed = warmup_stats["processed"]

        print(json.dumps({"event": "phase_start", "phase": "eval_tuesday"}, ensure_ascii=False))
        summary["eval_replay"] = replay_once(
            pcap=args.tuesday_pcap,
            iface=args.iface,
            mbps=args.eval_mbps,
            log_path=exp_root / "eval_replay.log",
        )
        if summary["eval_replay"]["exit_code"] != 0:
            raise RuntimeError(f"Tuesday tcpreplay failed: exit={summary['eval_replay']['exit_code']}")

        time.sleep(max(0.0, args.settle_seconds))
        eval_stats = wait_for_idle(
            session_id=session_id,
            timeout=args.timeout,
            stage="eval",
            stable_seconds=min(30.0, args.settle_seconds),
        )
        summary["eval_stats"] = eval_stats
        summary["eval_flows"] = max(0, eval_stats["processed"] - warmup_processed)
        summary["learner_rows"] = postgres_learner_rows(session_id)
        summary["learner_count"] = len(summary["learner_rows"])
        if eval_stats["processed"] > 0:
            summary["unknown_rate"] = round(eval_stats["unknown"] / eval_stats["processed"], 4)
    finally:
        terminate(worker)
        worker_log.close()

    write_json(exp_root / "summary.json", summary)
    write_json(run_root / "summary.json", summary)
    if args.sync_docker_config:
        sync_docker_session(session_id)

    print(json.dumps({"run_root": str(run_root), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
