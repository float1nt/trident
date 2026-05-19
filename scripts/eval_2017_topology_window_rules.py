#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List

import networkx as nx
import numpy as np
import pandas as pd


FILES_2017 = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]

COL_ALIASES = {
    "label": ["Label", "label"],
    "src_ip": ["Src IP", "Source IP", "src_ip", "source_ip", " Source IP"],
    "dst_ip": ["Dst IP", "Destination IP", "dst_ip", "destination_ip", " Destination IP"],
    "src_port": ["Src Port", "Source Port", "src_port", "source_port", " Source Port"],
    "dst_port": ["Dst Port", "Destination Port", "dst_port", "destination_port", " Destination Port"],
}


def _norm_label(v: object) -> str:
    return str(v).strip().upper()


def _resolve_col(columns: Iterable[str], aliases: List[str]) -> str:
    col_set = set(columns)
    for a in aliases:
        if a in col_set:
            return a
    normalized = {str(c).strip().lower(): c for c in columns}
    for a in aliases:
        key = str(a).strip().lower()
        if key in normalized:
            return str(normalized[key])
    raise KeyError(f"Cannot resolve any column from aliases={aliases}")


def _detect_columns(sample_csv: Path) -> Dict[str, str]:
    cols = pd.read_csv(sample_csv, nrows=0).columns.tolist()
    return {k: _resolve_col(cols, aliases) for k, aliases in COL_ALIASES.items()}


def _load_2017(data_dir: Path) -> pd.DataFrame:
    col_map = _detect_columns(data_dir / FILES_2017[0])
    read_cols = [col_map["label"], col_map["src_ip"], col_map["dst_ip"], col_map["src_port"], col_map["dst_port"]]
    frames: List[pd.DataFrame] = []
    for name in FILES_2017:
        p = data_dir / name
        if not p.exists():
            raise FileNotFoundError(f"Missing source file: {p}")
        df = pd.read_csv(p, low_memory=False, usecols=lambda c: c in read_cols)
        df = df.rename(
            columns={
                col_map["label"]: "Label",
                col_map["src_ip"]: "SrcIP",
                col_map["dst_ip"]: "DstIP",
                col_map["src_port"]: "SrcPort",
                col_map["dst_port"]: "DstPort",
            }
        )
        frames.append(df)
    all_df = pd.concat(frames, ignore_index=True)
    all_df["Label"] = all_df["Label"].map(_norm_label)
    all_df["is_attack"] = (all_df["Label"] != "BENIGN").astype(np.int8)
    return all_df


def _rates(y_true_attack: np.ndarray, y_pred_attack: np.ndarray) -> Dict[str, float]:
    tp = int(((y_pred_attack == 1) & (y_true_attack == 1)).sum())
    tn = int(((y_pred_attack == 0) & (y_true_attack == 0)).sum())
    fp = int(((y_pred_attack == 1) & (y_true_attack == 0)).sum())
    fn = int(((y_pred_attack == 0) & (y_true_attack == 1)).sum())
    fpr = fp / max(1, fp + tn)
    fnr = fn / max(1, fn + tp)
    tpr = tp / max(1, fn + tp)
    precision = tp / max(1, tp + fp)
    return {
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "fpr": float(fpr),
        "fnr": float(fnr),
        "tpr": float(tpr),
        "precision": float(precision),
    }


def _window_metrics(win_df: pd.DataFrame) -> Dict[str, float]:
    src = win_df["SrcIP"].astype(str).str.strip() + ":" + win_df["SrcPort"].astype(str).str.strip()
    dst = win_df["DstIP"].astype(str).str.strip() + ":" + win_df["DstPort"].astype(str).str.strip()
    pairs = pd.DataFrame({"src": src, "dst": dst}).drop_duplicates()
    n_edges = int(len(pairs))
    if n_edges == 0:
        return {
            "nodes": 0.0,
            "edges": 0.0,
            "reciprocity": 0.0,
            "hub_out_ratio": 0.0,
            "hub_in_ratio": 0.0,
            "frag_ratio": 0.0,
            "largest_cc_ratio": 0.0,
        }

    nodes = pd.Index(pairs["src"]).union(pd.Index(pairs["dst"]))
    n_nodes = int(len(nodes))
    denom = max(1, n_nodes - 1)

    out_deg = pairs.groupby("src")["dst"].nunique()
    in_deg = pairs.groupby("dst")["src"].nunique()
    hub_out_ratio = float(out_deg.max() / denom) if len(out_deg) else 0.0
    hub_in_ratio = float(in_deg.max() / denom) if len(in_deg) else 0.0

    pair_set = set(zip(pairs["src"].tolist(), pairs["dst"].tolist()))
    rev_count = sum(1 for u, v in pair_set if (v, u) in pair_set)
    reciprocity = float(rev_count / max(1, len(pair_set)))

    g = nx.Graph()
    g.add_nodes_from(nodes.tolist())
    g.add_edges_from(pair_set)
    comps = list(nx.connected_components(g))
    largest_cc = max((len(c) for c in comps), default=0)
    frag_ratio = float(len(comps) / max(1, n_nodes))
    largest_cc_ratio = float(largest_cc / max(1, n_nodes))

    return {
        "nodes": float(n_nodes),
        "edges": float(n_edges),
        "reciprocity": reciprocity,
        "hub_out_ratio": hub_out_ratio,
        "hub_in_ratio": hub_in_ratio,
        "frag_ratio": frag_ratio,
        "largest_cc_ratio": largest_cc_ratio,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate window-based topology rules on CICIDS2017.")
    parser.add_argument("--data-dir", default="/home/data/2017")
    parser.add_argument("--window-size", type=int, default=5000)
    parser.add_argument("--benign-window-attack-max-ratio", type=float, default=0.001)
    parser.add_argument("--out-prefix", default="outputs/analysis/2017_topology_window_rules")
    args = parser.parse_args()

    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading data ...", flush=True)
    df = _load_2017(Path(args.data_dir))
    df["window_id"] = (np.arange(len(df)) // int(args.window_size)).astype(np.int32)

    print("[2/4] Computing per-window topology metrics ...", flush=True)
    win_rows: List[Dict[str, float]] = []
    for win_id, grp in df.groupby("window_id", sort=True):
        m = _window_metrics(grp)
        attack_ratio = float(grp["is_attack"].mean())
        row: Dict[str, float] = {
            "window_id": float(win_id),
            "rows": float(len(grp)),
            "attack_ratio": attack_ratio,
            "is_attack_window": float(1.0 if attack_ratio > 0.0 else 0.0),
        }
        row.update(m)
        win_rows.append(row)
    win_df = pd.DataFrame(win_rows)

    benign_win_df = win_df[win_df["attack_ratio"] <= float(args.benign_window_attack_max_ratio)].copy()
    if benign_win_df.empty:
        raise RuntimeError("No benign baseline windows found. Consider increasing benign-window-attack-max-ratio.")

    recip_low = float(np.quantile(benign_win_df["reciprocity"], 0.10))
    hub_in_high = float(np.quantile(benign_win_df["hub_in_ratio"], 0.95))
    hub_out_high = float(np.quantile(benign_win_df["hub_out_ratio"], 0.95))
    frag_high = float(np.quantile(benign_win_df["frag_ratio"], 0.95))
    lcc_low = float(np.quantile(benign_win_df["largest_cc_ratio"], 0.05))

    print("[3/4] Applying window-level rules and mapping to flows ...", flush=True)
    pred_map = pd.DataFrame(
        {
            "window_id": win_df["window_id"].astype(np.int32),
            "rule_win_sink_lowrecip": (
                (win_df["hub_in_ratio"] >= hub_in_high) & (win_df["reciprocity"] <= recip_low)
            ).astype(np.int8),
            "rule_win_src_lowrecip": (
                (win_df["hub_out_ratio"] >= hub_out_high) & (win_df["reciprocity"] <= recip_low)
            ).astype(np.int8),
            "rule_win_frag_lcc": (
                (win_df["frag_ratio"] >= frag_high) & (win_df["largest_cc_ratio"] <= lcc_low)
            ).astype(np.int8),
        }
    )
    pred_map["rule_win_combo"] = (
        (pred_map["rule_win_sink_lowrecip"] == 1)
        | (pred_map["rule_win_src_lowrecip"] == 1)
        | (pred_map["rule_win_frag_lcc"] == 1)
    ).astype(np.int8)

    merged = df[["is_attack", "window_id"]].merge(pred_map, on="window_id", how="left")
    y_true = merged["is_attack"].to_numpy(np.int8, copy=False)
    rule_cols = [c for c in pred_map.columns if c.startswith("rule_")]

    results = {
        "dataset": {
            "total_rows": int(len(df)),
            "attack_rows": int(df["is_attack"].sum()),
            "benign_rows": int(len(df) - int(df["is_attack"].sum())),
            "window_size": int(args.window_size),
            "window_count": int(win_df.shape[0]),
            "benign_baseline_window_count": int(benign_win_df.shape[0]),
            "benign_window_attack_max_ratio": float(args.benign_window_attack_max_ratio),
        },
        "thresholds_from_benign_windows": {
            "reciprocity_q10_low": recip_low,
            "hub_in_ratio_q95_high": hub_in_high,
            "hub_out_ratio_q95_high": hub_out_high,
            "frag_ratio_q95_high": frag_high,
            "largest_cc_ratio_q05_low": lcc_low,
        },
        "rules": {},
    }

    for col in rule_cols:
        y_pred = merged[col].to_numpy(np.int8, copy=False)
        metrics = _rates(y_true_attack=y_true, y_pred_attack=y_pred)
        metrics["pred_attack_rows"] = int(y_pred.sum())
        results["rules"][col] = metrics

    win_csv = out_prefix.with_suffix(".window_metrics.csv")
    win_df.to_csv(win_csv, index=False)
    json_path = out_prefix.with_suffix(".json")
    md_path = out_prefix.with_suffix(".md")
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[4/4] Writing reports ...", flush=True)
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# 2017 Window-Based Topology Rule Evaluation\n\n")
        f.write(
            f"- rows={results['dataset']['total_rows']}, benign={results['dataset']['benign_rows']}, attack={results['dataset']['attack_rows']}\n"
        )
        f.write(
            f"- window_size={results['dataset']['window_size']}, windows={results['dataset']['window_count']}, "
            f"benign_baseline_windows={results['dataset']['benign_baseline_window_count']}\n\n"
        )
        f.write("## Benign Baseline Thresholds\n\n")
        for k, v in results["thresholds_from_benign_windows"].items():
            f.write(f"- {k}: {float(v):.6f}\n")
        f.write("\n## Rule Metrics (flow-level)\n\n")
        f.write("| Rule | PredAttack | FPR | FNR | TPR | Precision |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for rule_name, m in results["rules"].items():
            f.write(
                f"| {rule_name} | {int(m['pred_attack_rows'])} | {m['fpr']:.4%} | {m['fnr']:.4%} | {m['tpr']:.4%} | {m['precision']:.4%} |\n"
            )

    print(f"      window_metrics_csv={win_csv}", flush=True)
    print(f"      result_json={json_path}", flush=True)
    print(f"      result_md={md_path}", flush=True)


if __name__ == "__main__":
    main()

