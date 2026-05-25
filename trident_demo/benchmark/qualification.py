"""Profiled learner qualification: metrics + hints + reference rules."""
from __future__ import annotations

from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from trident_demo.qualification.metric_audit import compute_learner_metrics, compute_qualitative_hints
from trident_demo.qualification.reference_rules import evaluate_learner_reference_rules
from trident_demo.qualification.metric_catalog import CORE_METRIC_KEYS, METRIC_AUDIT_VERSION, REMOVED_METRICS
from trident_demo.export.visualization import _audit_join, _label_info_map


def profile_learner_qualification(
    data: pd.DataFrame,
    assignments: pd.DataFrame,
    label_distribution: Optional[pd.DataFrame] = None,
    *,
    min_samples: int = 50,
    max_learners: int = 60,
    generated_from: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build audit payload while recording per-stage qualification timings."""
    merged = _audit_join(data, assignments)
    label_map = _label_info_map(label_distribution)

    global_time_span: Optional[float] = None
    global_time_origin: Optional[pd.Timestamp] = None
    if "Timestamp" in merged.columns:
        ts = pd.to_datetime(merged["Timestamp"], errors="coerce").dropna()
        if len(ts) >= 2:
            global_time_origin = ts.min()
            global_time_span = float((ts.max() - ts.min()).total_seconds())

    grouped: List[Tuple[str, pd.DataFrame]] = [
        (str(learner), group)
        for learner, group in merged.groupby("assigned_learner", sort=False)
    ]
    grouped.sort(key=lambda item: len(item[1]), reverse=True)

    metric_seconds = 0.0
    hints_seconds = 0.0
    rules_seconds = 0.0
    audited_flow_count = 0
    learner_count = 0

    learners_out: List[Dict[str, Any]] = []
    learners_skipped: List[Dict[str, Any]] = []
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

        t0 = perf_counter()
        metrics = compute_learner_metrics(
            learner,
            group,
            global_time_span,
            global_time_origin=global_time_origin,
        )
        metric_seconds += perf_counter() - t0

        t1 = perf_counter()
        hints = compute_qualitative_hints(metrics)
        hints_seconds += perf_counter() - t1

        t2 = perf_counter()
        reference_rules = evaluate_learner_reference_rules(metrics)
        rules_seconds += perf_counter() - t2

        info = label_map.get(learner, {})
        learners_out.append(
            {
                "learner_name": learner,
                "flow_count": flow_count,
                "attack_ratio": info.get("attack_ratio"),
                "dominant_label": info.get("dominant_label"),
                "dominant_ratio": info.get("dominant_ratio"),
                "metrics": metrics,
                "qualitative_hints": hints,
                "reference_rules": reference_rules,
            }
        )
        audited_flow_count += flow_count
        learner_count += 1
        if max_learners and learner_count >= max_learners:
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

    from trident_demo.qualification.metric_catalog import CORE_METRIC_KEYS, METRIC_AUDIT_VERSION, REMOVED_METRICS

    qual_total = metric_seconds + hints_seconds + rules_seconds
    profile = {
        "learner_count_audited": learner_count,
        "audited_flow_count": audited_flow_count,
        "qualification_metrics_seconds": metric_seconds,
        "qualification_hints_seconds": hints_seconds,
        "qualification_reference_rules_seconds": rules_seconds,
        "qualification_total_seconds": qual_total,
        "reference_rules_total_matches": sum(
            len(l.get("reference_rules") or []) for l in learners_out
        ),
    }

    payload: Dict[str, Any] = {
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
    return payload, profile
