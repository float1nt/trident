#!/usr/bin/env python3
"""Export per-learner topology metric audit JSON.

Usage:
  python3 scripts/export_learner_topology_metric_audit.py outputs/runs/<run_id>
  python3 scripts/export_learner_topology_metric_audit.py --raw-csvs cic2017/*.csv --label-csv labels.csv
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trident_stream.experiment import TridentStreamingExperiment
from trident_stream.learner_metric_audit import (
    compute_learner_metrics,
    compute_qualitative_hints,
)

COL_ALIASES = {
    "src_ip": ["Src IP", "Source IP", " Source IP", "src_ip", "source_ip", " Src IP", " Src IP"],
    "dst_ip": ["Dst IP", "Destination IP", " Destination IP", "dst_ip", "destination_ip", " Dst IP", " Dst IP"],
    "src_port": ["Src Port", "Source Port", " Source Port", "src_port", "source_port", " Src Port", " Src Port"],
    "dst_port": ["Dst Port", "Destination Port", " Destination Port", "dst_port", "destination_port", " Dst Port", " Dst Port"],
    "timestamp": ["Timestamp", "timestamp", " Timestamp"],
    "label": ["Label", "LabelNorm", "label", " Label"],
    "protocol": ["Protocol", "protocol", " Protocol"],
}


def _resolve_col(columns: list, aliases: list) -> Optional[str]:
    col_set = set(columns)
    for a in aliases:
        if a in col_set:
            return a
    normalized = {str(c).strip().lower(): c for c in columns}
    for a in aliases:
        if str(a).strip().lower() in normalized:
            return normalized[str(a).strip().lower()]
    return None


def _flows_for_audit(data: pd.DataFrame) -> pd.DataFrame:
    """Align experiment dataframe columns with metric audit expectations."""
    out = data.copy()
    out["row_index"] = np.arange(len(out), dtype=np.int64)
    rename = {
        "Src IP": "SrcIP",
        "Dst IP": "DstIP",
        "Src Port": "SrcPort",
        "Dst Port": "DstPort",
    }
    for src, dst in rename.items():
        if src in out.columns and dst not in out.columns:
            out[dst] = out[src]
    return out


def _detect_columns(cols: list) -> dict:
    out = {}
    for k, aliases in COL_ALIASES.items():
        c = _resolve_col(list(cols), aliases)
        if c:
            out[k] = c
    return out


def _load_and_rename(csv_path: Path, col_map: dict) -> pd.DataFrame:
    usecols = [c for c in col_map.values() if c != "__placeholder__"]
    df = pd.read_csv(csv_path, low_memory=False, usecols=usecols)
    rename = {}
    for key, col in col_map.items():
        if col == "__placeholder__":
            continue
        if key == "src_ip":
            rename[col] = "SrcIP"
        elif key == "dst_ip":
            rename[col] = "DstIP"
        elif key == "src_port":
            rename[col] = "SrcPort"
        elif key == "dst_port":
            rename[col] = "DstPort"
        elif key == "timestamp":
            rename[col] = "Timestamp"
        elif key == "label":
            rename[col] = "Label"
        elif key == "protocol":
            rename[col] = "Protocol"
    df = df.rename(columns=rename)
    # Ensure required columns exist
    for col in ["SrcIP", "DstIP"]:
        if col not in df.columns:
            raise ValueError(f"Missing required column after rename: {col} in {csv_path}")
    if "SrcPort" not in df.columns:
        df["SrcPort"] = "0"
    if "DstPort" not in df.columns:
        df["DstPort"] = "0"
    return df


def _load_from_raw_csvs(csv_paths: List[Path]) -> pd.DataFrame:
    """Load flows directly from raw CIC CSV files, assign learners by src_ip."""
    dfs = []
    for p in csv_paths:
        if not p.exists():
            continue
        cols = pd.read_csv(p, nrows=0).columns.tolist()
        col_map = _detect_columns(cols)
        if not all(k in col_map for k in ["src_ip", "dst_ip", "src_port", "dst_port"]):
            # Some 2019 CSVs lack src_port/dst_port columns — fill with 0
            for key in ["src_port", "dst_port"]:
                if key not in col_map:
                    col_map[key] = "__placeholder__"
            # Still require src_ip and dst_ip
            if "src_ip" not in col_map or "dst_ip" not in col_map:
                print(f"  SKIP {p.name}: missing src_ip or dst_ip", flush=True)
                continue
        df = _load_and_rename(p, col_map)
        dfs.append(df)
    if not dfs:
        raise FileNotFoundError("No CSV files found")
    merged = pd.concat(dfs, ignore_index=True)
    # Assign learner by source IP
    merged["assigned_learner"] = merged["SrcIP"].astype(str).apply(
        lambda ip: f"SRC_{ip.replace('.', '_')}"
    )
    return merged


def _load_label_distribution(label_csv: Optional[Path], merged: pd.DataFrame) -> Dict[str, dict]:
    """Build label info map from label CSV or from the merged data itself."""
    label_map: Dict[str, dict] = {}
    if label_csv and label_csv.exists():
        ldf = pd.read_csv(label_csv)
        for _, r in ldf.iterrows():
            name = str(r.get("learner_name", ""))
            if name:
                label_map[name] = {
                    "attack_ratio": float(r.get("attack_ratio", 0) or 0),
                    "dominant_label": str(r.get("dominant_label", "")),
                    "dominant_ratio": float(r.get("dominant_ratio", 0) or 0),
                }
    else:
        # Build from the data itself when no label file
        by_learner = merged.groupby("assigned_learner")
        for learner, grp in by_learner:
            n = len(grp)
            if "Label" in merged.columns:
                attack_ratio = float((grp["Label"].astype(str).str.lower() != "benign").mean())
                label_counts = grp["Label"].astype(str).value_counts()
                dominant_label = str(label_counts.index[0]) if len(label_counts) else ""
                dominant_ratio = float(label_counts.iloc[0] / n) if len(label_counts) else 0.0
            else:
                attack_ratio = 0.0
                dominant_label = ""
                dominant_ratio = 0.0
            label_map[str(learner)] = {
                "attack_ratio": attack_ratio,
                "dominant_label": dominant_label,
                "dominant_ratio": dominant_ratio,
            }
    return label_map


def main() -> None:
    parser = argparse.ArgumentParser(description="Export per-learner metric audit JSON")
    parser.add_argument("run_dir", nargs="?", default=None, help="Path to outputs/runs/<run_id>")
    parser.add_argument("--output", default=None, help="Output JSON path")
    parser.add_argument("--min-samples", type=int, default=50, help="Min flows per learner")
    parser.add_argument("--max-learners", type=int, default=60, help="Max learners to process")
    parser.add_argument("--raw-csvs", nargs="*", default=None, help="Raw CSV files to use directly")
    parser.add_argument("--label-csv", default=None, help="Label distribution CSV")
    args = parser.parse_args()

    merged: pd.DataFrame

    if args.raw_csvs:
        # Direct mode: use raw CSVs, assign learners by src_ip
        csv_paths = [Path(p) for p in args.raw_csvs]
        print(f"[1/3] Loading {len(csv_paths)} raw CSV(s) ...", flush=True)
        merged = _load_from_raw_csvs(csv_paths)
        label_map = _load_label_distribution(
            Path(args.label_csv) if args.label_csv else None, merged
        )
        output_path = Path(args.output) if args.output else Path("learner_topology_metric_audit.json")
    elif args.run_dir:
        run_dir = Path(args.run_dir).resolve()
        cfg_path = run_dir / "config_snapshot.yaml"
        assign_path = run_dir / "sample_learner_assignments.csv"
        label_dist_path = run_dir / "learner_label_distribution.csv"

        if not cfg_path.exists():
            raise FileNotFoundError(f"config_snapshot.yaml not found: {cfg_path}")
        if not assign_path.exists():
            raise FileNotFoundError(f"sample_learner_assignments.csv not found: {assign_path}")

        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        logger = logging.getLogger("export_learner_metric_audit")
        logging.basicConfig(level=logging.INFO, format="%(message)s")

        print(f"[1/3] Loading filtered dataset + canonical assignments ...", flush=True)
        exp = TridentStreamingExperiment(cfg, logger)
        data, _, _ = exp._load_dataset()
        flow_df = _flows_for_audit(data)

        # Prefer canonical export written at end of run (stream + creation_fill).
        if assign_path.exists():
            assign_df = pd.read_csv(assign_path)
            assign_df = assign_df[["row_index", "assigned_learner"]].copy()
        else:
            assign_df = pd.DataFrame(columns=["row_index", "assigned_learner"])

        label_map: Dict[str, dict] = {}
        if label_dist_path.exists():
            ldf = pd.read_csv(label_dist_path)
            for _, r in ldf.iterrows():
                name = str(r.get("learner_name", ""))
                if name:
                    label_map[name] = {
                        "attack_ratio": float(r.get("attack_ratio", 0) or 0),
                        "dominant_label": str(r.get("dominant_label", "")),
                        "dominant_ratio": float(r.get("dominant_ratio", 0) or 0),
                        "total_assigned_samples": int(r.get("total_assigned_samples", 0) or 0),
                    }

        assign_df["row_index"] = assign_df["row_index"].astype(np.int64)
        assign_df["assigned_learner"] = assign_df["assigned_learner"].astype(str)

        print(f"[2/3] Joining and computing metrics ...", flush=True)
        merged = assign_df.merge(flow_df, on="row_index", how="inner")
        needed_cols = {"SrcIP", "DstIP", "SrcPort", "DstPort"}
        merged = merged.dropna(subset=list(needed_cols & set(merged.columns)))
        output_path = Path(args.output) if args.output else run_dir / "learner_topology_metric_audit.json"
    else:
        parser.error("Either --run-dir or --raw-csvs is required")

    # Global timeline for temporal metrics (aligned to filtered dataset)
    global_time_span = None
    global_time_origin = None
    if "Timestamp" in merged.columns:
        ts = pd.to_datetime(merged["Timestamp"], errors="coerce").dropna()
        if len(ts) >= 2:
            global_time_origin = ts.min()
            global_time_span = (ts.max() - ts.min()).total_seconds()

    print(f"[N] Computing metrics ({len(merged)} flows, {merged['assigned_learner'].nunique()} learners) ...", flush=True)

    learners_out: List[Dict[str, Any]] = []
    learners_skipped: List[Dict[str, Any]] = []
    processed = 0

    grouped: List[Tuple[str, pd.DataFrame]] = [
        (str(learner), grp)
        for learner, grp in merged.groupby("assigned_learner", sort=False)
    ]
    grouped.sort(key=lambda item: len(item[1]), reverse=True)

    joined_learners = {name for name, _ in grouped}

    for learner, grp in grouped:
        n_flows = len(grp)
        if n_flows < args.min_samples:
            learners_skipped.append({
                "learner_name": learner,
                "reason": f"flows_below_min_samples({args.min_samples})",
                "flow_count_joined": int(n_flows),
            })
            continue

        metrics = compute_learner_metrics(
            str(learner),
            grp,
            global_time_span,
            global_time_origin=global_time_origin,
        )
        hints = compute_qualitative_hints(metrics)

        label_info = label_map.get(str(learner), {})
        learners_out.append({
            "learner_name": str(learner),
            "flow_count": int(n_flows),
            "attack_ratio": label_info.get("attack_ratio"),
            "dominant_label": label_info.get("dominant_label"),
            "dominant_ratio": label_info.get("dominant_ratio"),
            "metrics": metrics,
            "qualitative_hints": hints,
        })

        processed += 1
        if args.max_learners and processed >= args.max_learners:
            break

    for name, info in label_map.items():
        if name in joined_learners:
            continue
        learners_skipped.append({
            "learner_name": name,
            "reason": "no_stream_assignment_join",
            "flow_count_joined": 0,
            "label_distribution_samples": info.get("total_assigned_samples"),
        })

    print(f"[Final] Writing output ({len(learners_out)} learners, {len(learners_skipped)} skipped) ...", flush=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": 1,
        "generated_from": {
            "assignments": "raw_csv" if args.raw_csvs else "sample_learner_assignments.csv",
            "label_distribution": "inferred" if args.raw_csvs else "learner_label_distribution.csv",
            "dataset_loader": "TridentStreamingExperiment._load_dataset"
            if args.run_dir
            else "raw_csvs",
        },
        "export_filters": {
            "min_samples": int(args.min_samples),
            "max_learners": int(args.max_learners),
            "assignment_phase": "canonical (stream + creation_fill)",
        },
        "learners": learners_out,
        "learners_skipped": learners_skipped,
    }

    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {output_path}")


if __name__ == "__main__":
    main()
