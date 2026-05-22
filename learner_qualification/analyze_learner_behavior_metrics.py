#!/usr/bin/env python3
"""Summarize temporal/port behavior metrics from learner_label_distribution.csv."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def _spearman(df: pd.DataFrame, col: str) -> float:
    if col not in df.columns or "attack_ratio" not in df.columns:
        return float("nan")
    x = pd.to_numeric(df[col], errors="coerce")
    y = pd.to_numeric(df["attack_ratio"], errors="coerce")
    if x.notna().sum() < 2:
        return float("nan")
    return float(x.corr(y, method="spearman"))


def _rule_table(df: pd.DataFrame, pred: pd.Series, name: str) -> dict:
    audit_attack = df["attack_ratio"] >= 0.5
    audit_benign = df["attack_ratio"] < 0.1
    tp = int((pred & audit_attack).sum())
    fp = int((pred & audit_benign).sum())
    fn = int((~pred & audit_attack).sum())
    tn = int((~pred & audit_benign).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    fp_names = df.loc[pred & audit_benign, "learner_name"].astype(str).tolist()
    fn_names = df.loc[~pred & audit_attack, "learner_name"].astype(str).tolist()
    return {
        "rule": name,
        "precision_vs_audit_attack": prec,
        "recall_vs_audit_attack": rec,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "false_positive_learners": fp_names,
        "false_negative_learners": fn_names,
    }


def analyze(run_dir: Path) -> None:
    profile_path = run_dir / "learner_label_distribution.csv"
    assign_path = run_dir / "sample_learner_assignments.csv"
    if not profile_path.exists():
        raise FileNotFoundError(profile_path)

    df = pd.read_csv(profile_path)
    out_md = run_dir / "learner_behavior_metrics_report.md"
    out_json = run_dir / "learner_behavior_metrics_summary.json"

    lines = [
        "# Learner Behavior Metrics Report\n",
        f"- run_dir: `{run_dir}`\n",
        f"- learners: {len(df)}\n\n",
    ]

    metric_cols = [
        c
        for c in df.columns
        if c.startswith("temporal_") or c.startswith("dst_port_") or c in {"port_cluster_type", "temporal_cluster_type"}
    ]
    if metric_cols:
        lines.append("## Spearman vs audit attack_ratio\n\n")
        lines.append("| metric | spearman |\n|---|---:|\n")
        for c in sorted(metric_cols):
            if c.endswith("_type") or c.endswith("_count"):
                continue
            lines.append(f"| {c} | {_spearman(df, c):+.4f} |\n")
        lines.append("\n")

    if "temporal_burst_score" in df.columns:
        pred_time = df["temporal_burst_score"] >= 0.5
        rules = [_rule_table(df, pred_time, "temporal_burst_score>=0.5")]
    else:
        rules = []

    if "dst_top_port_ratio" in df.columns and "dst_port_unique" in df.columns:
        pred_scan = (df["dst_top_port_ratio"] < 0.15) & (df["dst_port_unique"] >= 200)
        pred_flood = (df["dst_top_port_ratio"] > 0.9) & (df["dst_port_unique"] <= 3)
        pred_port = pred_scan | pred_flood
        if "dst_port_norm_entropy" in df.columns:
            pred_port = pred_port | (df["dst_port_norm_entropy"] > 0.85)
        rules.extend(
            [
                _rule_table(df, pred_scan, "port_scan_like"),
                _rule_table(df, pred_flood, "port_single_port"),
                _rule_table(df, pred_port, "port_scan_or_flood_or_high_entropy"),
            ]
        )
        if "temporal_burst_score" in df.columns:
            combined = pred_time | pred_port
            rules.append(_rule_table(df, combined, "temporal_burst OR port_attack"))

    lines.append("## Heuristic rules (audit attack_ratio>=0.5)\n\n")
    for r in rules:
        lines.append(f"### {r['rule']}\n\n")
        lines.append(
            f"- precision={r['precision_vs_audit_attack']:.3f} "
            f"recall={r['recall_vs_audit_attack']:.3f} "
            f"(tp={r['tp']} fp={r['fp']} fn={r['fn']} tn={r['tn']})\n"
        )
        if r["false_positive_learners"]:
            lines.append(f"- FP (audit benign): `{', '.join(r['false_positive_learners'])}`\n")
        if r["false_negative_learners"]:
            lines.append(f"- FN (audit attack): `{', '.join(r['false_negative_learners'])}`\n")
        lines.append("\n")

    show_cols = [
        "learner_name",
        "attack_ratio",
        "dominant_label",
        "temporal_burst_score",
        "temporal_span_ratio",
        "temporal_cluster_type",
        "dst_port_unique",
        "dst_top_port_ratio",
        "dst_port_norm_entropy",
        "port_cluster_type",
    ]
    show_cols = [c for c in show_cols if c in df.columns]
    if show_cols:
        lines.append("## Learner snapshot (sorted by temporal_burst_score)\n\n")
        view = df[show_cols].sort_values(
            by=[c for c in ["temporal_burst_score", "attack_ratio"] if c in df.columns],
            ascending=[False, False],
        )
        lines.append("```\n")
        lines.append(view.to_string(index=False, float_format=lambda x: f"{x:.4f}"))
        lines.append("\n```\n\n")

    if assign_path.exists():
        assign = pd.read_csv(assign_path)
        nat_default = int(pd.to_datetime(assign["timestamp"], errors="coerce").isna().sum())
        nat_mixed = int(
            pd.to_datetime(assign["timestamp"], errors="coerce", format="mixed").isna().sum()
        )
        lines.append("## Assignment timestamp parse check\n\n")
        lines.append(f"- rows: {len(assign)}\n")
        lines.append(f"- NaT with default parse: {nat_default}\n")
        lines.append(f"- NaT with mixed parse: {nat_mixed}\n")
        ts = pd.to_datetime(assign["timestamp"], errors="coerce", format="mixed")
        if ts.notna().any():
            lines.append(f"- min/max: {ts.min()} .. {ts.max()}\n")
            lines.append(f"- span_days: {(ts.max() - ts.min()).total_seconds() / 86400:.2f}\n")
            lines.append("\n")

    out_md.write_text("".join(lines), encoding="utf-8")
    with out_json.open("w", encoding="utf-8") as f:
        json.dump({"rules": rules, "metric_cols": metric_cols}, f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, help="Path to outputs/runs/<run_id>")
    args = parser.parse_args()
    analyze(Path(args.run_dir))


if __name__ == "__main__":
    main()
