"""Flush Trident run artifacts to disk for live visualization consumption."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import pandas as pd

LIVE_RUN_STATUS_FILE = "live_run_status.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_live_flush_settings(cfg: Mapping[str, Any]) -> Dict[str, Any]:
    viz_cfg = cfg.get("visualization", {}) if isinstance(cfg.get("visualization"), dict) else {}
    input_cfg = cfg.get("input", {}) if isinstance(cfg.get("input"), dict) else {}
    input_source = str(input_cfg.get("source", input_cfg.get("type", "csv"))).strip().lower()
    redis_input = input_source in {"redis", "redis_list", "redis_stream"}

    enabled = viz_cfg.get("live_flush_enabled", "auto")
    if isinstance(enabled, str) and enabled.strip().lower() == "auto":
        enabled = redis_input
    else:
        enabled = bool(enabled)

    return {
        "enabled": enabled,
        "interval_windows": max(1, int(viz_cfg.get("live_flush_interval_windows", 1) or 1)),
        "flush_window_csv": bool(viz_cfg.get("live_flush_window_csv", True)),
        "flush_metric_audit": bool(viz_cfg.get("live_flush_metric_audit", True)),
    }


def write_live_run_status(
    output_dir: Path,
    *,
    run_id: str,
    status: str,
    windows_count: int = 0,
    rows_used: int = 0,
    learner_count: int = 0,
) -> Path:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / LIVE_RUN_STATUS_FILE
    payload = {
        "run_id": str(run_id),
        "status": str(status),
        "windows_count": int(windows_count),
        "rows_used": int(rows_used),
        "learner_count": int(learner_count),
        "updated_at": _utc_now_iso(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def flush_learner_count_csv(output_dir: Path, time_series: list[Dict[str, Any]]) -> Optional[Path]:
    if not time_series:
        return None
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "learner_count_over_time.csv"
    rows = []
    for entry in time_series:
        row = dict(entry)
        ts = row.get("window_end_time")
        if ts is not None and not isinstance(ts, str):
            row["window_end_time"] = str(ts)
        rows.append(row)
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def flush_qualification_artifacts(
    output_dir: Path,
    data: pd.DataFrame,
    assignments: pd.DataFrame,
    label_distribution: pd.DataFrame,
    *,
    min_samples: int,
    max_learners: int,
    partial: bool = True,
    windows_processed: int = 0,
) -> Dict[str, Path]:
    from trident_demo.export.visualization import build_learner_metric_audit_payload

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_payload = build_learner_metric_audit_payload(
        data,
        assignments,
        label_distribution,
        min_samples=min_samples,
        max_learners=max_learners,
        generated_from={
            "assignments": "live stream assignments",
            "label_distribution": "live learner label distribution",
            "dataset_loader": "run dataframe",
        },
    )
    if partial:
        audit_payload["live_partial"] = True
        audit_payload["windows_processed"] = int(windows_processed)

    audit_path = output_dir / "learner_topology_metric_audit.json"
    audit_path.write_text(json.dumps(audit_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    profile_path = output_dir / "learner_label_distribution.csv"
    label_distribution.to_csv(profile_path, index=False)

    return {
        "learner_topology_metric_audit": audit_path,
        "learner_label_distribution": profile_path,
    }
