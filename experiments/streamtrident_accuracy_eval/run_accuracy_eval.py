#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from urllib import parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import redis
import requests
import yaml


ROOT = Path(__file__).resolve().parents[2]
SERVICE_ROOT = ROOT / "streamtrident_services"
TRIDENT_ROOT = SERVICE_ROOT / "analysis" / "trident"
DOCKER_TRIDENT_CONFIG = SERVICE_ROOT / "analysis" / "docker" / "trident.yaml"
DEFAULT_OUT_ROOT = ROOT / "outputs" / "streamtrident_accuracy_eval"

STREAM = "suricata:cic_flow"
REDIS_URL = "redis://127.0.0.1:16379/0"
CLICKHOUSE_DSN = "http://default:trident@127.0.0.1:18123/default"
POSTGRES_DSN = "postgresql://trident:trident@127.0.0.1:15432/trident"

DATA2019 = ROOT / "data" / "cicids2019"

STRICT_LABEL_SPECS = [
    {
        "name": "BENIGN",
        "path": ROOT / "data" / "cic2017" / "monday.csv",
        "labels": {"BENIGN"},
        "target": 20000,
    },
    {
        "name": "PORTSCAN",
        "path": ROOT / "data" / "cic2017" / "friday.csv",
        "labels": {"Portscan"},
        "target": 10000,
    },
    {
        "name": "DDOS",
        "path": ROOT / "data" / "cic2017" / "friday.csv",
        "labels": {"DDoS"},
        "target": 10000,
    },
    {
        "name": "DOS_HULK",
        "path": ROOT / "data" / "cic2017" / "wednesday.csv",
        "labels": {"DoS Hulk"},
        "target": 10000,
    },
    {
        "name": "SYN",
        "path": ROOT / "data" / "cicids2019" / "Syn.csv",
        "labels": {"Syn"},
        "target": 10000,
    },
    {
        "name": "DRDOS_DNS",
        "path": ROOT / "data" / "cicids2019" / "DrDoS_DNS.csv",
        "labels": {"DrDoS_DNS"},
        "target": 10000,
    },
    {
        "name": "DRDOS_NTP",
        "path": ROOT / "data" / "cicids2019" / "DrDoS_NTP.csv",
        "labels": {"DrDoS_NTP"},
        "target": 10000,
    },
]

# UDP-only plan: 50k BENIGN warmup + TFTP + full DrDoS family (10k each).
UDP_DRDOS_TFTP_SPECS = [
    {
        "name": "TFTP",
        "path": DATA2019 / "TFTP.csv",
        "labels": {"TFTP"},
        "target": 10000,
    },
    {
        "name": "DRDOS_DNS",
        "path": DATA2019 / "DrDoS_DNS.csv",
        "labels": {"DrDoS_DNS"},
        "target": 10000,
    },
    {
        "name": "DRDOS_LDAP",
        "path": DATA2019 / "DrDoS_LDAP.csv",
        "labels": {"DrDoS_LDAP"},
        "target": 10000,
    },
    {
        "name": "DRDOS_MSSQL",
        "path": DATA2019 / "DrDoS_MSSQL.csv",
        "labels": {"DrDoS_MSSQL"},
        "target": 10000,
    },
    {
        "name": "DRDOS_NETBIOS",
        "path": DATA2019 / "DrDoS_NetBIOS.csv",
        "labels": {"DrDoS_NetBIOS"},
        "target": 10000,
    },
    {
        "name": "DRDOS_NTP",
        "path": DATA2019 / "DrDoS_NTP.csv",
        "labels": {"DrDoS_NTP"},
        "target": 10000,
    },
    {
        "name": "DRDOS_SNMP",
        "path": DATA2019 / "DrDoS_SNMP.csv",
        "labels": {"DrDoS_SNMP"},
        "target": 10000,
    },
    {
        "name": "DRDOS_SSDP",
        "path": DATA2019 / "DrDoS_SSDP.csv",
        "labels": {"DrDoS_SSDP"},
        "target": 10000,
    },
    {
        "name": "DRDOS_UDP",
        "path": DATA2019 / "DrDoS_UDP.csv",
        "labels": {"DrDoS_UDP"},
        "target": 10000,
    },
]

LABEL_PLANS: dict[str, list[dict[str, Any]]] = {
    "legacy_mixed": STRICT_LABEL_SPECS,
    "udp_drdos_tftp": UDP_DRDOS_TFTP_SPECS,
}

BENIGN_EVAL_SPEC = {
    "name": "BENIGN",
    "path": ROOT / "data" / "cic2017" / "monday.csv",
    "labels": {"BENIGN"},
    "target": 0,
}

BASELINE_LEARNER = "0000|UNLABELED"

COARSE_MAP = {
    "BENIGN": "BENIGN",
    "PORTSCAN": "PORTSCAN",
    "DDOS": "DOS_DDOS",
    "DOS_HULK": "DOS_DDOS",
    "SYN": "SYN_FLOOD",
    "DRDOS_DNS": "DRDOS_UDP_FAMILY",
    "DRDOS_NTP": "DRDOS_UDP_FAMILY",
    "DRDOS_LDAP": "DRDOS_UDP_FAMILY",
    "DRDOS_MSSQL": "DRDOS_UDP_FAMILY",
    "DRDOS_NETBIOS": "DRDOS_UDP_FAMILY",
    "DRDOS_SNMP": "DRDOS_UDP_FAMILY",
    "DRDOS_SSDP": "DRDOS_UDP_FAMILY",
    "DRDOS_UDP": "DRDOS_UDP_FAMILY",
    "TFTP": "TFTP",
}

CANONICAL_COLUMNS = {
    "flow id": "Flow ID",
    "source ip": "Src IP",
    "src ip": "Src IP",
    "source port": "Src Port",
    "src port": "Src Port",
    "destination ip": "Dst IP",
    "dst ip": "Dst IP",
    "destination port": "Dst Port",
    "dst port": "Dst Port",
    "protocol": "Protocol",
    "timestamp": "Timestamp",
    "total fwd packets": "Total Fwd Packet",
    "total fwd packet": "Total Fwd Packet",
    "total backward packets": "Total Bwd packets",
    "total bwd packets": "Total Bwd packets",
    "total length of fwd packets": "Total Length of Fwd Packet",
    "total length of fwd packet": "Total Length of Fwd Packet",
    "total length of bwd packets": "Total Length of Bwd Packet",
    "total length of bwd packet": "Total Length of Bwd Packet",
    "min packet length": "Packet Length Min",
    "packet length min": "Packet Length Min",
    "max packet length": "Packet Length Max",
    "packet length max": "Packet Length Max",
    "avg fwd segment size": "Fwd Segment Size Avg",
    "fwd segment size avg": "Fwd Segment Size Avg",
    "avg bwd segment size": "Bwd Segment Size Avg",
    "bwd segment size avg": "Bwd Segment Size Avg",
    "init_win_bytes_forward": "FWD Init Win Bytes",
    "fwd init win bytes": "FWD Init Win Bytes",
    "init_win_bytes_backward": "Bwd Init Win Bytes",
    "bwd init win bytes": "Bwd Init Win Bytes",
    "act_data_pkt_fwd": "Fwd Act Data Pkts",
    "fwd act data pkts": "Fwd Act Data Pkts",
    "min_seg_size_forward": "Fwd Seg Size Min",
    "fwd seg size min": "Fwd Seg Size Min",
    "fwd avg bulk rate": "Fwd Bulk Rate Avg",
    "fwd bulk rate avg": "Fwd Bulk Rate Avg",
    "bwd avg bulk rate": "Bwd Bulk Rate Avg",
    "bwd bulk rate avg": "Bwd Bulk Rate Avg",
}

ALWAYS_KEEP = {
    "Flow ID",
    "Src IP",
    "Src Port",
    "Dst IP",
    "Dst Port",
    "Protocol",
    "Timestamp",
    "Label",
}


@dataclass(frozen=True)
class ExperimentPlan:
    name: str
    protocol_filter: int | None
    specs: list[dict[str, Any]]


def main() -> int:
    parser = argparse.ArgumentParser(description="Black-box StreamTrident learner clustering accuracy evaluation")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT))
    parser.add_argument("--skip-deps", action="store_true", help="Do not run docker compose up for Redis/ClickHouse/Postgres")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--force-split", action="store_true", help="Always run tcp-only and udp-only after mixed")
    parser.add_argument("--benign-warmup", type=int, default=50000, help="BENIGN rows injected before evaluation and excluded from scoring")
    parser.add_argument(
        "--plan",
        choices=sorted(LABEL_PLANS),
        default="legacy_mixed",
        help="legacy_mixed: mixed/tcp/udp split on CIC2017+2019 labels; udp_drdos_tftp: UDP-only TFTP + DrDoS family",
    )
    parser.add_argument(
        "--eval-benign",
        type=int,
        default=0,
        help="BENIGN rows mixed into eval injection (scored); e.g. 20000 probes baseline during attack phase",
    )
    parser.add_argument(
        "--interleave-eval",
        action="store_true",
        help="Round-robin interleave eval rows by label instead of label-block injection order",
    )
    parser.add_argument(
        "--hours-back",
        type=float,
        default=24.0,
        help="Spread injected event_time over the last N hours (0 disables time shift)",
    )
    parser.add_argument(
        "--sync-docker-config",
        action="store_true",
        help="After the run, write session_id into streamtrident_services/analysis/docker/trident.yaml",
    )
    args = parser.parse_args()
    label_specs = eval_specs_for_plan(args.plan, LABEL_PLANS[args.plan], args.eval_benign)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    run_root = Path(args.out_root) / run_id
    run_root.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, Any] = {
        "run_id": run_id,
        "created_at": utc_now(),
        "project": "streamtrident_services",
        "method": "learner majority-label backfill accuracy",
        "plan": args.plan,
        "benign_warmup": args.benign_warmup,
        "eval_benign": args.eval_benign,
        "interleave_eval": args.interleave_eval,
        "hours_back": args.hours_back,
        "sync_docker_config": args.sync_docker_config,
        "outputs": {},
    }
    write_json(run_root / "manifest.json", manifest)

    if not args.skip_deps:
        run(["docker", "compose", "-f", str(SERVICE_ROOT / "compose.yaml"), "up", "-d", "redis", "clickhouse", "postgres"], cwd=ROOT)
    wait_for_deps()

    summaries: list[dict[str, Any]] = []
    if args.plan == "udp_drdos_tftp":
        summary = run_one(
            ExperimentPlan("udp_drdos_tftp", 17, label_specs),
            run_root=run_root,
            timeout=args.timeout,
            benign_warmup=args.benign_warmup,
            interleave_eval=args.interleave_eval,
            hours_back=args.hours_back,
        )
        summaries = [summary]
        manifest["udp_drdos_tftp_summary"] = summary
        write_json(run_root / "manifest.json", manifest)
        if args.sync_docker_config and summary.get("session_id"):
            sync_docker_session_id(str(summary["session_id"]))
            manifest["docker_session_id"] = summary["session_id"]
            write_json(run_root / "manifest.json", manifest)
    else:
        plans = [ExperimentPlan("mixed_tcp_udp", None, label_specs)]
        mixed_summary = run_one(plans[0], run_root=run_root, timeout=args.timeout, benign_warmup=args.benign_warmup)
        split_needed = args.force_split or should_run_split(mixed_summary)
        manifest["mixed_summary"] = mixed_summary
        manifest["split_decision"] = {
            "run_split": split_needed,
            "reason": mixed_summary.get("split_decision_reason", ""),
        }
        write_json(run_root / "manifest.json", manifest)

        summaries = [mixed_summary]
        if split_needed:
            tcp_summary = run_one(ExperimentPlan("tcp_only", 6, label_specs), run_root=run_root, timeout=args.timeout, benign_warmup=args.benign_warmup)
            udp_summary = run_one(ExperimentPlan("udp_only", 17, label_specs), run_root=run_root, timeout=args.timeout, benign_warmup=args.benign_warmup)
            summaries.extend([tcp_summary, udp_summary])

    write_json(run_root / "all_summaries.json", {"run_id": run_id, "summaries": summaries})
    write_markdown_report(run_root / "REPORT.md", summaries, manifest)
    print(json.dumps({"run_root": str(run_root), "summaries": summaries}, ensure_ascii=False, indent=2))
    return 0


def eval_specs_for_plan(plan: str, base_specs: list[dict[str, Any]], eval_benign: int) -> list[dict[str, Any]]:
    specs = [dict(spec) for spec in base_specs]
    if int(eval_benign) <= 0:
        return specs
    benign = dict(BENIGN_EVAL_SPEC)
    benign["target"] = int(eval_benign)
    if plan == "udp_drdos_tftp":
        return specs + [benign]
    return [benign] + specs


def run_one(
    plan: ExperimentPlan,
    *,
    run_root: Path,
    timeout: int,
    benign_warmup: int,
    interleave_eval: bool = False,
    hours_back: float = 0.0,
) -> dict[str, Any]:
    exp_root = run_root / plan.name
    exp_root.mkdir(parents=True, exist_ok=True)
    session_id = f"accuracy-{plan.name}-{uuid.uuid4().hex[:10]}"
    config_path = exp_root / "trident_eval_config.yaml"
    model_store = exp_root / "models"
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    before_id = redis_client.xinfo_stream(STREAM)["last-generated-id"] if redis_client.exists(STREAM) else "0-0"
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

    warmup_path = exp_root / "warmup_benign.csv"
    warmup_summary = build_warmup_dataset(plan, warmup_path, target=benign_warmup)
    metadata_path = exp_root / "flow_labels.csv"
    dataset_summary = build_dataset(plan, metadata_path, interleave=interleave_eval)
    if interleave_eval:
        dataset_summary["interleave"] = "round_robin_by_label"
    time_shift_summary: dict[str, Any] | None = None
    if float(hours_back) > 0:
        time_shift_summary = shift_injection_times(
            warmup_path,
            metadata_path,
            hours_back=float(hours_back),
        )
    expected = int(dataset_summary["total_rows"])
    if expected == 0:
        summary = {
            "experiment": plan.name,
            "session_id": session_id,
            "status": "skipped_empty_dataset",
            "dataset": dataset_summary,
        }
        write_json(exp_root / "summary.json", summary)
        return summary

    worker_log = (exp_root / "worker.log").open("w", encoding="utf-8")
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.worker", "--config", str(config_path)],
        cwd=TRIDENT_ROOT,
        env=python_env(),
        stdout=worker_log,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        time.sleep(2.0)
        warmup_injected = 0
        if int(warmup_summary["total_rows"]) > 0:
            warmup_injected = inject_metadata(warmup_path, redis_client, session_id=session_id, stream=STREAM)
            wait_for_processing(session_id=session_id, expected=warmup_injected, timeout=timeout, stage="warmup")
        injected = inject_metadata(metadata_path, redis_client, session_id=session_id, stream=STREAM)
        wait_for_processing(session_id=session_id, expected=warmup_injected + injected, timeout=timeout, stage="eval")
    finally:
        terminate(worker)
        worker_log.close()

    assignments_path = exp_root / "assignments.csv"
    assignments = fetch_assignments(session_id=session_id, out_path=assignments_path, flow_prefix=f"{plan.name}:")
    summary = evaluate(
        plan=plan,
        session_id=session_id,
        dataset_summary=dataset_summary,
        warmup_summary=warmup_summary,
        metadata_path=metadata_path,
        assignments=assignments,
        exp_root=exp_root,
        redis_before_id=before_id,
    )
    if time_shift_summary is not None:
        summary["time_shift"] = time_shift_summary
    write_json(exp_root / "summary.json", summary)
    return summary


def build_warmup_dataset(plan: ExperimentPlan, out_path: Path, *, target: int) -> dict[str, Any]:
    spec = {
        "name": "BENIGN_WARMUP",
        "path": ROOT / "data" / "cic2017" / "monday.csv",
        "labels": {"BENIGN"},
        "target": int(target),
    }
    rows_written = 0
    per_protocol: dict[str, int] = {}
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "flow_uid",
                "strict_label",
                "coarse_label",
                "protocol",
                "event_time",
                "src_ip",
                "src_port",
                "dst_ip",
                "dst_port",
                "source_flow_id",
                "features_json",
                "raw_event_json",
            ],
        )
        writer.writeheader()
        for _, raw in iter_matching_rows(Path(spec["path"]), labels=set(spec["labels"]), protocol_filter=plan.protocol_filter):
            canonical = canonicalize_row(raw)
            flow_uid = f"warmup:{plan.name}:BENIGN:{rows_written}:{uuid.uuid4().hex[:12]}"
            event_time = normalize_event_time(canonical.get("Timestamp", ""))
            protocol = int(to_int(canonical.get("Protocol", 0)))
            source_flow_id = str(canonical.get("Flow ID") or flow_uid)
            writer.writerow(
                {
                    "flow_uid": flow_uid,
                    "strict_label": "BENIGN_WARMUP",
                    "coarse_label": "BENIGN",
                    "protocol": protocol,
                    "event_time": event_time,
                    "src_ip": str(canonical.get("Src IP") or ""),
                    "src_port": int(to_int(canonical.get("Src Port", 0))),
                    "dst_ip": str(canonical.get("Dst IP") or ""),
                    "dst_port": int(to_int(canonical.get("Dst Port", 0))),
                    "source_flow_id": source_flow_id,
                    "features_json": json.dumps(features_from_row(canonical), ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                    "raw_event_json": json.dumps(
                        {
                            "flow_uid": flow_uid,
                            "source_flow_id": source_flow_id,
                            "strict_label": "BENIGN_WARMUP",
                            "coarse_label": "BENIGN",
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                }
            )
            rows_written += 1
            per_protocol[str(protocol)] = per_protocol.get(str(protocol), 0) + 1
            if rows_written >= int(target):
                break
    return {
        "experiment": plan.name,
        "protocol_filter": plan.protocol_filter,
        "total_rows": rows_written,
        "per_label": {"BENIGN_WARMUP": rows_written},
        "per_protocol": per_protocol,
        "target": int(target),
    }


def build_dataset(plan: ExperimentPlan, out_path: Path, *, interleave: bool = False) -> dict[str, Any]:
    fieldnames = [
        "flow_uid",
        "strict_label",
        "coarse_label",
        "protocol",
        "event_time",
        "src_ip",
        "src_port",
        "dst_ip",
        "dst_port",
        "source_flow_id",
        "features_json",
        "raw_event_json",
    ]
    per_label: dict[str, int] = {}
    per_protocol: dict[str, int] = {}
    buckets: list[list[dict[str, str]]] = []
    for spec in plan.specs:
        label_name = str(spec["name"])
        target = int(spec["target"])
        label_rows: list[dict[str, str]] = []
        count = 0
        for _, raw in iter_matching_rows(Path(spec["path"]), labels=set(spec["labels"]), protocol_filter=plan.protocol_filter):
            canonical = canonicalize_row(raw)
            flow_uid = f"{plan.name}:{label_name}:{count}:{uuid.uuid4().hex[:12]}"
            event_time = normalize_event_time(canonical.get("Timestamp", ""))
            protocol = int(to_int(canonical.get("Protocol", 0)))
            source_flow_id = str(canonical.get("Flow ID") or flow_uid)
            label_rows.append(
                {
                    "flow_uid": flow_uid,
                    "strict_label": label_name,
                    "coarse_label": COARSE_MAP[label_name],
                    "protocol": str(protocol),
                    "event_time": event_time,
                    "src_ip": str(canonical.get("Src IP") or ""),
                    "src_port": str(int(to_int(canonical.get("Src Port", 0)))),
                    "dst_ip": str(canonical.get("Dst IP") or ""),
                    "dst_port": str(int(to_int(canonical.get("Dst Port", 0)))),
                    "source_flow_id": source_flow_id,
                    "features_json": json.dumps(features_from_row(canonical), ensure_ascii=False, separators=(",", ":"), sort_keys=True),
                    "raw_event_json": json.dumps(
                        {
                            "flow_uid": flow_uid,
                            "source_flow_id": source_flow_id,
                            "strict_label": label_name,
                            "coarse_label": COARSE_MAP[label_name],
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                }
            )
            count += 1
            per_label[label_name] = per_label.get(label_name, 0) + 1
            per_protocol[str(protocol)] = per_protocol.get(str(protocol), 0) + 1
            if count >= target:
                break
        if label_rows:
            buckets.append(label_rows)

    ordered_rows = interleave_rows(buckets) if interleave and len(buckets) > 1 else [row for bucket in buckets for row in bucket]
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ordered_rows)
    return {
        "experiment": plan.name,
        "protocol_filter": plan.protocol_filter,
        "total_rows": len(ordered_rows),
        "per_label": per_label,
        "per_protocol": per_protocol,
        "targets": {str(spec["name"]): int(spec["target"]) for spec in plan.specs},
    }


def interleave_rows(buckets: list[list[dict[str, str]]]) -> list[dict[str, str]]:
    """Round-robin merge label buckets so eval injection mimics mixed live traffic."""
    indices = [0] * len(buckets)
    out: list[dict[str, str]] = []
    remaining = sum(len(bucket) for bucket in buckets)
    cursor = 0
    while remaining > 0:
        bucket_idx = cursor % len(buckets)
        pos = indices[bucket_idx]
        if pos < len(buckets[bucket_idx]):
            out.append(buckets[bucket_idx][pos])
            indices[bucket_idx] += 1
            remaining -= 1
        cursor += 1
    return out


def iter_matching_rows(path: Path, *, labels: set[str], protocol_filter: int | None):
    usecols = None
    chunks = pd.read_csv(path, chunksize=20000, low_memory=False, usecols=usecols)
    for chunk in chunks:
        chunk.columns = [str(col).strip() for col in chunk.columns]
        if "Label" not in chunk.columns:
            continue
        mask = chunk["Label"].isin(labels)
        if protocol_filter is not None and "Protocol" in chunk.columns:
            mask &= pd.to_numeric(chunk["Protocol"], errors="coerce").fillna(-1).astype(int).eq(protocol_filter)
        elif protocol_filter is not None:
            continue
        selected = chunk.loc[mask]
        for idx, row in selected.iterrows():
            yield int(idx), row.to_dict()


def canonicalize_row(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in raw.items():
        clean = str(key).strip()
        norm = " ".join(clean.lower().split())
        canonical = CANONICAL_COLUMNS.get(norm, clean)
        out[canonical] = clean_value(value)
    return out


def features_from_row(row: dict[str, Any]) -> dict[str, float]:
    features: dict[str, float] = {}
    for key, value in row.items():
        if key in ALWAYS_KEEP or key in {"Attempted Category", "year_tag", "original_label", "benign_type"}:
            continue
        number = to_float(value)
        if number is not None:
            features[key] = number
    return features


def inject_metadata(path: Path, client: redis.Redis, *, session_id: str, stream: str) -> int:
    injected = 0
    pipe = client.pipeline(transaction=False)
    batch = 0
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            fields = {
                "event_type": "cic_flow",
                "session_id": session_id,
                "flow_uid": row["flow_uid"],
                "event_time": row["event_time"],
                "src_ip": row["src_ip"],
                "dst_ip": row["dst_ip"],
                "src_port": row["src_port"],
                "dst_port": row["dst_port"],
                "protocol": row["protocol"],
                "source_flow_id": row["source_flow_id"],
                "features_json": row["features_json"],
                "raw_event_json": row["raw_event_json"],
            }
            pipe.xadd(stream, fields, maxlen=2_000_000, approximate=True)
            injected += 1
            batch += 1
            if batch >= 1000:
                pipe.execute()
                batch = 0
        if batch:
            pipe.execute()
    return injected


def wait_for_processing(*, session_id: str, expected: int, timeout: int, stage: str) -> None:
    start = time.time()
    last = -1
    while time.time() - start < timeout:
        assigned = clickhouse_count(
            f"SELECT count() FROM ch_flow FINAL WHERE session_id = {quote(session_id)} AND record_stage = 'assigned'"
        )
        processed = clickhouse_count(f"SELECT count() FROM ch_flow FINAL WHERE session_id = {quote(session_id)}")
        if processed != last:
            print(
                json.dumps(
                    {
                        "event": "processing_progress",
                        "stage": stage,
                        "session_id": session_id,
                        "processed_final_rows": processed,
                        "assigned": assigned,
                        "expected": expected,
                    }
                )
            )
            last = processed
        if processed >= expected:
            return
        time.sleep(5)
    raise TimeoutError(f"timeout waiting for processing: session={session_id} processed={last} expected={expected}")


def fetch_assignments(*, session_id: str, out_path: Path, flow_prefix: str | None = None) -> list[dict[str, Any]]:
    prefix_filter = f"AND startsWith(flow_uid, {quote(flow_prefix)})" if flow_prefix else ""
    sql = f"""
SELECT
  flow_uid,
  assigned_learner,
  is_unknown,
  window_index,
  pred_loss,
  threshold
FROM ch_flow FINAL
WHERE session_id = {quote(session_id)}
  AND record_stage = 'assigned'
  {prefix_filter}
ORDER BY flow_uid ASC
FORMAT JSONEachRow
"""
    rows = clickhouse_json_each_row(sql)
    with out_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["flow_uid", "assigned_learner", "is_unknown", "window_index", "pred_loss", "threshold"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def evaluate(
    *,
    plan: ExperimentPlan,
    session_id: str,
    dataset_summary: dict[str, Any],
    warmup_summary: dict[str, Any],
    metadata_path: Path,
    assignments: list[dict[str, Any]],
    exp_root: Path,
    redis_before_id: str,
) -> dict[str, Any]:
    labels: dict[str, dict[str, Any]] = {}
    with metadata_path.open("r", newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            labels[row["flow_uid"]] = row
    assignment_by_uid = {str(row["flow_uid"]): row for row in assignments}
    joined: list[dict[str, Any]] = []
    for uid, meta in labels.items():
        assigned = assignment_by_uid.get(uid)
        learner = str(assigned.get("assigned_learner") or "") if assigned else ""
        is_unknown = int(assigned.get("is_unknown") or 0) if assigned else 1
        joined.append(
            {
                "flow_uid": uid,
                "strict_label": meta["strict_label"],
                "coarse_label": meta["coarse_label"],
                "protocol": int(meta["protocol"]),
                "assigned_learner": learner,
                "is_unknown": is_unknown,
            }
        )

    strict_majority = majority_by_learner(joined, "strict_label")
    coarse_majority = majority_by_learner(joined, "coarse_label")
    for row in joined:
        learner = row["assigned_learner"]
        row["pred_strict_label"] = strict_majority.get(learner, "__UNKNOWN__") if learner else "__UNKNOWN__"
        row["pred_coarse_label"] = coarse_majority.get(learner, "__UNKNOWN__") if learner else "__UNKNOWN__"
        row["strict_correct"] = int(row["pred_strict_label"] == row["strict_label"])
        row["coarse_correct"] = int(row["pred_coarse_label"] == row["coarse_label"])

    write_csv(exp_root / "joined_predictions.csv", joined)
    learner_summary = build_learner_summary(joined)
    write_csv(exp_root / "learner_summary.csv", learner_summary)

    strict_metrics = metrics(joined, true_key="strict_label", pred_key="pred_strict_label")
    coarse_metrics = metrics(joined, true_key="coarse_label", pred_key="pred_coarse_label")
    protocol_metrics = {
        str(proto): {
            "strict": metrics([r for r in joined if int(r["protocol"]) == proto], true_key="strict_label", pred_key="pred_strict_label"),
            "coarse": metrics([r for r in joined if int(r["protocol"]) == proto], true_key="coarse_label", pred_key="pred_coarse_label"),
        }
        for proto in sorted({int(r["protocol"]) for r in joined})
    }
    confusion_strict = confusion(joined, true_key="strict_label", pred_key="pred_strict_label")
    confusion_coarse = confusion(joined, true_key="coarse_label", pred_key="pred_coarse_label")
    write_json(exp_root / "confusion_strict.json", confusion_strict)
    write_json(exp_root / "confusion_coarse.json", confusion_coarse)

    baseline = baseline_metrics(joined)

    return {
        "experiment": plan.name,
        "session_id": session_id,
        "redis_before_id": redis_before_id,
        "dataset": dataset_summary,
        "warmup": warmup_summary,
        "baseline": baseline,
        "assigned_rows": len(assignments),
        "expected_rows": len(labels),
        "learner_count": len({r["assigned_learner"] for r in joined if r["assigned_learner"]}),
        "unknown_rows": sum(1 for r in joined if int(r["is_unknown"]) == 1 or not r["assigned_learner"]),
        "strict": strict_metrics,
        "coarse": coarse_metrics,
        "protocol_metrics": protocol_metrics,
        "split_decision_reason": split_reason(protocol_metrics),
    }


def majority_by_learner(rows: list[dict[str, Any]], label_key: str) -> dict[str, str]:
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        learner = str(row["assigned_learner"])
        if not learner or int(row["is_unknown"]) == 1:
            continue
        counts[learner][str(row[label_key])] += 1
    return {learner: counter.most_common(1)[0][0] for learner, counter in counts.items() if counter}


def baseline_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    benign_eval = [r for r in rows if str(r.get("strict_label")) == "BENIGN"]
    if not benign_eval:
        return {"eval_benign_rows": 0}
    on_baseline = [r for r in benign_eval if str(r.get("assigned_learner")) == BASELINE_LEARNER and int(r.get("is_unknown") or 0) == 0]
    assigned = [r for r in benign_eval if r.get("assigned_learner") and int(r.get("is_unknown") or 0) == 0]
    coarse_ok = [r for r in benign_eval if str(r.get("pred_coarse_label")) == "BENIGN"]
    return {
        "eval_benign_rows": len(benign_eval),
        "assigned_to_baseline": len(on_baseline),
        "baseline_recall": safe_div(len(on_baseline), len(benign_eval)),
        "benign_coarse_accuracy": safe_div(len(coarse_ok), len(benign_eval)),
        "benign_coverage": safe_div(len(assigned), len(benign_eval)),
        "baseline_absorb_attack_rows": sum(
            1
            for r in rows
            if str(r.get("strict_label")) != "BENIGN"
            and str(r.get("assigned_learner")) == BASELINE_LEARNER
            and int(r.get("is_unknown") or 0) == 0
        ),
    }


def build_learner_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["assigned_learner"] or "__UNKNOWN__")].append(row)
    out = []
    for learner, items in sorted(grouped.items()):
        strict = Counter(str(r["strict_label"]) for r in items)
        coarse = Counter(str(r["coarse_label"]) for r in items)
        protocol = Counter(str(r["protocol"]) for r in items)
        strict_top, strict_count = strict.most_common(1)[0]
        coarse_top, coarse_count = coarse.most_common(1)[0]
        out.append(
            {
                "assigned_learner": learner,
                "flow_count": len(items),
                "strict_majority": strict_top,
                "strict_purity": strict_count / len(items),
                "coarse_majority": coarse_top,
                "coarse_purity": coarse_count / len(items),
                "protocol_counts": json.dumps(dict(protocol), ensure_ascii=False, sort_keys=True),
                "strict_counts": json.dumps(dict(strict), ensure_ascii=False, sort_keys=True),
                "coarse_counts": json.dumps(dict(coarse), ensure_ascii=False, sort_keys=True),
            }
        )
    return out


def metrics(rows: list[dict[str, Any]], *, true_key: str, pred_key: str) -> dict[str, Any]:
    if not rows:
        return {"total": 0, "accuracy_including_unknown": None, "assigned_only_accuracy": None, "coverage": 0.0}
    assigned = [r for r in rows if r["assigned_learner"] and int(r["is_unknown"]) == 0]
    correct_all = sum(1 for r in rows if r[true_key] == r[pred_key])
    correct_assigned = sum(1 for r in assigned if r[true_key] == r[pred_key])
    per_label = {}
    for label in sorted({str(r[true_key]) for r in rows}):
        label_rows = [r for r in rows if str(r[true_key]) == label]
        label_assigned = [r for r in label_rows if r["assigned_learner"] and int(r["is_unknown"]) == 0]
        per_label[label] = {
            "total": len(label_rows),
            "accuracy_including_unknown": safe_div(sum(1 for r in label_rows if r[true_key] == r[pred_key]), len(label_rows)),
            "assigned_only_accuracy": safe_div(sum(1 for r in label_assigned if r[true_key] == r[pred_key]), len(label_assigned)),
            "coverage": safe_div(len(label_assigned), len(label_rows)),
        }
    return {
        "total": len(rows),
        "accuracy_including_unknown": correct_all / len(rows),
        "assigned_only_accuracy": safe_div(correct_assigned, len(assigned)),
        "coverage": len(assigned) / len(rows),
        "unknown_rate": 1.0 - len(assigned) / len(rows),
        "per_label": per_label,
    }


def confusion(rows: list[dict[str, Any]], *, true_key: str, pred_key: str) -> dict[str, dict[str, int]]:
    matrix: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        matrix[str(row[true_key])][str(row[pred_key])] += 1
    return {label: dict(counter) for label, counter in sorted(matrix.items())}


def should_run_split(summary: dict[str, Any]) -> bool:
    protocol_metrics = summary.get("protocol_metrics") or {}
    reason = split_reason(protocol_metrics)
    summary["split_decision_reason"] = reason
    return reason != "mixed_protocol_gap_within_threshold"


def split_reason(protocol_metrics: dict[str, Any]) -> str:
    tcp = protocol_metrics.get("6", {}).get("coarse", {}).get("assigned_only_accuracy")
    udp = protocol_metrics.get("17", {}).get("coarse", {}).get("assigned_only_accuracy")
    if tcp is None or udp is None:
        return "missing_tcp_or_udp_metric"
    if abs(float(tcp) - float(udp)) >= 0.10:
        return "tcp_udp_coarse_accuracy_gap_ge_10pp"
    if float(tcp) < 0.75 or float(udp) < 0.75:
        return "tcp_or_udp_coarse_accuracy_below_75pct"
    return "mixed_protocol_gap_within_threshold"


def write_config(path: Path, *, session_id: str, model_store: Path, best_effort_start_id: str) -> None:
    payload = {
        "redis_url": REDIS_URL,
        "input_stream": STREAM,
        "consumer_group": "trident-online",
        "consumer_name": f"accuracy-{uuid.uuid4().hex[:8]}",
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


def wait_for_deps() -> None:
    deadline = time.time() + 240
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    while time.time() < deadline:
        try:
            redis_client.ping()
            clickhouse_count("SELECT 1")
            return
        except Exception:
            time.sleep(2)
    raise TimeoutError("dependencies did not become ready")


def clickhouse_count(sql: str) -> int:
    text = clickhouse_execute(sql)
    try:
        return int(str(text).strip().splitlines()[0])
    except Exception:
        return 0


def clickhouse_json_each_row(sql: str) -> list[dict[str, Any]]:
    text = clickhouse_execute(sql)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def clickhouse_execute(sql: str) -> str:
    # Local ClickHouse must bypass HTTP_PROXY; otherwise localhost requests get 502.
    session = requests.Session()
    session.trust_env = False
    response = session.post(clickhouse_query_url(sql), data=b"", timeout=120)
    response.raise_for_status()
    return response.text


def clickhouse_query_url(sql: str) -> str:
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
    return parse.urlunsplit((parsed.scheme, netloc, path or "/", parse.urlencode(params), parsed.fragment))


def run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    print(json.dumps({"event": "run", "cmd": cmd, "cwd": str(cwd)}, ensure_ascii=False))
    subprocess.run(cmd, cwd=str(cwd), env=env, check=True)


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


def terminate(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown_report(path: Path, summaries: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    lines = [
        "# StreamTrident Accuracy Evaluation",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- created_at: `{manifest['created_at']}`",
        f"- method: learner majority-label backfill accuracy",
        "",
        "| experiment | rows | learners | unknown_rate | strict_acc | coarse_acc | assigned_strict_acc | assigned_coarse_acc |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        strict = summary.get("strict") or {}
        coarse = summary.get("coarse") or {}
        lines.append(
            "| {experiment} | {rows} | {learners} | {unknown:.4f} | {sa:.4f} | {ca:.4f} | {saa:.4f} | {caa:.4f} |".format(
                experiment=summary.get("experiment"),
                rows=summary.get("expected_rows", 0),
                learners=summary.get("learner_count", 0),
                unknown=float(coarse.get("unknown_rate") or 0),
                sa=float(strict.get("accuracy_including_unknown") or 0),
                ca=float(coarse.get("accuracy_including_unknown") or 0),
                saa=float(strict.get("assigned_only_accuracy") or 0),
                caa=float(coarse.get("assigned_only_accuracy") or 0),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def quote(value: str) -> str:
    return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _read_metadata_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    return fieldnames, rows


def _write_metadata_csv(path: Path, *, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def shift_injection_times(
    warmup_path: Path,
    eval_path: Path,
    *,
    hours_back: float,
) -> dict[str, Any]:
    """Spread warmup+eval rows across [now-hours_back, now], preserving injection order."""
    warmup_fields, warmup_rows = _read_metadata_csv(warmup_path)
    eval_fields, eval_rows = _read_metadata_csv(eval_path)
    combined = warmup_rows + eval_rows
    if not combined:
        return {
            "hours_back": float(hours_back),
            "warmup_rows": len(warmup_rows),
            "eval_rows": len(eval_rows),
            "total_rows": 0,
        }
    now = datetime.now(timezone.utc)
    span = timedelta(hours=float(hours_back))
    total = len(combined)
    for index, row in enumerate(combined):
        offset = span * ((total - 1 - index) / max(total - 1, 1))
        ts = now - offset
        row["event_time"] = ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    _write_metadata_csv(warmup_path, fieldnames=warmup_fields, rows=combined[: len(warmup_rows)])
    _write_metadata_csv(eval_path, fieldnames=eval_fields, rows=combined[len(warmup_rows) :])
    return {
        "hours_back": float(hours_back),
        "warmup_rows": len(warmup_rows),
        "eval_rows": len(eval_rows),
        "total_rows": total,
        "event_time_min": combined[0]["event_time"],
        "event_time_max": combined[-1]["event_time"],
    }


def sync_docker_session_id(session_id: str) -> None:
    if not DOCKER_TRIDENT_CONFIG.exists():
        raise FileNotFoundError(f"docker trident config not found: {DOCKER_TRIDENT_CONFIG}")
    text = DOCKER_TRIDENT_CONFIG.read_text(encoding="utf-8")
    updated, count = re.subn(
        r"(?m)^session_id:\s*.+$",
        f"session_id: {session_id}",
        text,
        count=1,
    )
    if count == 0:
        payload = yaml.safe_load(text) or {}
        payload["session_id"] = str(session_id)
        updated = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    DOCKER_TRIDENT_CONFIG.write_text(updated, encoding="utf-8")
    print(json.dumps({"event": "sync_docker_session_id", "path": str(DOCKER_TRIDENT_CONFIG), "session_id": session_id}, ensure_ascii=False))


def normalize_event_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return utc_now()
    parsed = pd.to_datetime(text, errors="coerce", utc=True)
    if pd.isna(parsed):
        return utc_now()
    return parsed.isoformat().replace("+00:00", "Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clean_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return value


def to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def to_int(value: Any) -> int:
    number = to_float(value)
    return int(number or 0)


def safe_div(a: int, b: int) -> float | None:
    return None if b == 0 else a / b


if __name__ == "__main__":
    raise SystemExit(main())
