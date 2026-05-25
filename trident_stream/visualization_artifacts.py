"""Visualization artifact exports shared by runs and repair scripts.

The experiment runner hands plain dataframes to this module. Existing-run scripts
can load the same dataframes from run outputs and call the same functions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from .dataset_topology import save_dataset_network_topology, save_learner_network_topology
from .learner_metric_audit import compute_learner_metrics, compute_qualitative_hints
from .learner_reference_rules import evaluate_learner_reference_rules
from .metric_audit_catalog import CORE_METRIC_KEYS, METRIC_AUDIT_VERSION, REMOVED_METRICS


DEFAULT_METRIC_AUDIT_MIN_SAMPLES = 50
DEFAULT_METRIC_AUDIT_MAX_LEARNERS = 60


def flows_for_metric_audit(data: pd.DataFrame) -> pd.DataFrame:
    """Align experiment flow columns with topology metric audit columns."""
    out = data.copy()
    out["row_index"] = np.arange(len(out), dtype=np.int64)
    for src, dst in {
        "Src IP": "SrcIP",
        "Dst IP": "DstIP",
        "Src Port": "SrcPort",
        "Dst Port": "DstPort",
    }.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    return out


def _label_info_map(label_distribution: Optional[pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
    if label_distribution is None or label_distribution.empty:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for _, row in label_distribution.iterrows():
        name = str(row.get("learner_name", ""))
        if not name:
            continue
        out[name] = {
            "attack_ratio": _float_or_none(row.get("attack_ratio")),
            "dominant_label": str(row.get("dominant_label", "")),
            "dominant_ratio": _float_or_none(row.get("dominant_ratio")),
            "total_assigned_samples": _int_or_none(row.get("total_assigned_samples")),
        }
    return out


def _float_or_none(value: object) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _int_or_none(value: object) -> Optional[int]:
    parsed = _float_or_none(value)
    return int(parsed) if parsed is not None else None


def _audit_join(data: pd.DataFrame, assignments: pd.DataFrame) -> pd.DataFrame:
    flow_df = flows_for_metric_audit(data)
    if assignments.empty or {"row_index", "assigned_learner"} - set(assignments.columns):
        return pd.DataFrame(columns=["row_index", "assigned_learner"])

    assign_df = assignments[["row_index", "assigned_learner"]].copy()
    assign_df["row_index"] = pd.to_numeric(assign_df["row_index"], errors="coerce")
    assign_df = assign_df.dropna(subset=["row_index", "assigned_learner"])
    assign_df["row_index"] = assign_df["row_index"].astype(np.int64)
    assign_df["assigned_learner"] = assign_df["assigned_learner"].astype(str)
    merged = assign_df.merge(flow_df, on="row_index", how="inner")
    needed_cols = {"SrcIP", "DstIP", "SrcPort", "DstPort"}
    return merged.dropna(subset=list(needed_cols & set(merged.columns)))


def build_learner_metric_audit_payload(
    data: pd.DataFrame,
    assignments: pd.DataFrame,
    label_distribution: Optional[pd.DataFrame] = None,
    *,
    min_samples: int = DEFAULT_METRIC_AUDIT_MIN_SAMPLES,
    max_learners: int = DEFAULT_METRIC_AUDIT_MAX_LEARNERS,
    generated_from: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Build `learner_topology_metric_audit.json` from run dataframes."""
    merged = _audit_join(data, assignments)
    label_map = _label_info_map(label_distribution)

    global_time_span: Optional[float] = None
    global_time_origin: Optional[pd.Timestamp] = None
    if "Timestamp" in merged.columns:
        ts = pd.to_datetime(merged["Timestamp"], errors="coerce").dropna()
        if len(ts) >= 2:
            global_time_origin = ts.min()
            global_time_span = float((ts.max() - ts.min()).total_seconds())

    learners_out: List[Dict[str, Any]] = []
    learners_skipped: List[Dict[str, Any]] = []
    grouped: List[Tuple[str, pd.DataFrame]] = [
        (str(learner), group)
        for learner, group in merged.groupby("assigned_learner", sort=False)
    ]
    grouped.sort(key=lambda item: len(item[1]), reverse=True)
    joined_learners = {name for name, _ in grouped}

    for learner, group in grouped:
        flow_count = int(len(group))
        if flow_count < min_samples:
            learners_skipped.append(
                {
                    "learner_name": learner,
                    "reason": f"flows_below_min_samples({min_samples})",
                    "flow_count_joined": flow_count,
                }
            )
            continue

        metrics = compute_learner_metrics(
            learner,
            group,
            global_time_span,
            global_time_origin=global_time_origin,
        )
        info = label_map.get(learner, {})
        learners_out.append(
            {
                "learner_name": learner,
                "flow_count": flow_count,
                "attack_ratio": info.get("attack_ratio"),
                "dominant_label": info.get("dominant_label"),
                "dominant_ratio": info.get("dominant_ratio"),
                "metrics": metrics,
                "qualitative_hints": compute_qualitative_hints(metrics),
                "reference_rules": evaluate_learner_reference_rules(metrics),
            }
        )
        if max_learners and len(learners_out) >= max_learners:
            break

    for learner, info in label_map.items():
        if learner in joined_learners:
            continue
        learners_skipped.append(
            {
                "learner_name": learner,
                "reason": "no_stream_assignment_join",
                "flow_count_joined": 0,
                "label_distribution_samples": info.get("total_assigned_samples"),
            }
        )

    return {
        "version": METRIC_AUDIT_VERSION,
        "metric_count": len(CORE_METRIC_KEYS),
        "core_metric_keys": list(CORE_METRIC_KEYS),
        "removed_metrics": REMOVED_METRICS,
        "generated_from": generated_from
        or {
            "assignments": "run assignments dataframe",
            "label_distribution": "learner label distribution dataframe",
            "dataset_loader": "run dataframe",
        },
        "export_filters": {
            "min_samples": int(min_samples),
            "max_learners": int(max_learners),
            "assignment_phase": "canonical (stream + creation_fill)",
        },
        "learners": learners_out,
        "learners_skipped": learners_skipped,
    }


def save_learner_metric_audit(
    data: pd.DataFrame,
    assignments: pd.DataFrame,
    label_distribution: Optional[pd.DataFrame],
    output_path: Path,
    *,
    min_samples: int = DEFAULT_METRIC_AUDIT_MIN_SAMPLES,
    max_learners: int = DEFAULT_METRIC_AUDIT_MAX_LEARNERS,
    generated_from: Optional[Dict[str, str]] = None,
) -> Path:
    payload = build_learner_metric_audit_payload(
        data,
        assignments,
        label_distribution,
        min_samples=min_samples,
        max_learners=max_learners,
        generated_from=generated_from,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def export_visualization_artifacts(
    data: pd.DataFrame,
    assignments: pd.DataFrame,
    label_distribution: Optional[pd.DataFrame],
    output_dir: Path,
    *,
    export_dataset_topology: bool = True,
    metric_audit_min_samples: int = DEFAULT_METRIC_AUDIT_MIN_SAMPLES,
    metric_audit_max_learners: int = DEFAULT_METRIC_AUDIT_MAX_LEARNERS,
) -> Dict[str, Path]:
    """Write visualization-facing artifacts from one run context."""
    output_dir = output_dir.resolve()
    written: Dict[str, Path] = {}

    if export_dataset_topology:
        path = output_dir / "dataset_network_topology.json"
        if save_dataset_network_topology(data, path):
            written["dataset_network_topology"] = path

    learner_topology_path = output_dir / "learner_network_topology.json"
    assign_index = (
        assignments[["row_index", "assigned_learner"]].copy()
        if not assignments.empty and {"row_index", "assigned_learner"} <= set(assignments.columns)
        else pd.DataFrame(columns=["row_index", "assigned_learner"])
    )
    if save_learner_network_topology(data, assign_index, learner_topology_path):
        written["learner_network_topology"] = learner_topology_path

    audit_path = save_learner_metric_audit(
        data,
        assign_index,
        label_distribution,
        output_dir / "learner_topology_metric_audit.json",
        min_samples=metric_audit_min_samples,
        max_learners=metric_audit_max_learners,
    )
    written["learner_topology_metric_audit"] = audit_path
    return written
