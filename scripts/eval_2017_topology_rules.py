#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List

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
        df["Label"] = df["Label"].map(_norm_label)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate topology-rule detector on CICIDS2017 flows.")
    parser.add_argument("--data-dir", default="/home/data/2017")
    parser.add_argument("--hub-threshold", type=float, default=0.25)
    parser.add_argument("--out-json", default="outputs/analysis/2017_topology_rule_eval.json")
    parser.add_argument("--out-md", default="outputs/analysis/2017_topology_rule_eval.md")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading 2017 data ...", flush=True)
    df = _load_2017(data_dir)
    y_true = (df["Label"] != "BENIGN").astype(np.int8).to_numpy()
    total = len(df)
    attack = int(y_true.sum())
    benign = int(total - attack)
    print(f"      total={total} benign={benign} attack={attack}", flush=True)

    print("[2/4] Building endpoint graph features ...", flush=True)
    src = df["SrcIP"].astype(str).str.strip() + ":" + df["SrcPort"].astype(str).str.strip()
    dst = df["DstIP"].astype(str).str.strip() + ":" + df["DstPort"].astype(str).str.strip()
    pair_df = pd.DataFrame({"src": src, "dst": dst}).drop_duplicates()
    n_nodes = int(len(pd.Index(pair_df["src"]).union(pd.Index(pair_df["dst"]))))
    denom = max(1, n_nodes - 1)

    out_deg = pair_df.groupby("src")["dst"].nunique().to_dict()
    in_deg = pair_df.groupby("dst")["src"].nunique().to_dict()

    pair_keys = set(zip(pair_df["src"].tolist(), pair_df["dst"].tolist()))
    has_reverse_pair = {(u, v): ((v, u) in pair_keys) for (u, v) in pair_keys}

    src_out_ratio = src.map(lambda x: float(out_deg.get(x, 0) / denom)).to_numpy(np.float32, copy=False)
    dst_in_ratio = dst.map(lambda x: float(in_deg.get(x, 0) / denom)).to_numpy(np.float32, copy=False)
    reverse_exists = np.fromiter((bool(has_reverse_pair.get((u, v), False)) for u, v in zip(src, dst)), dtype=bool)

    print("[3/4] Evaluating rule sets ...", flush=True)
    hub_thr = float(args.hub_threshold)
    rule_preds: Dict[str, np.ndarray] = {
        "rule_source_hub": (src_out_ratio >= hub_thr).astype(np.int8),
        "rule_sink_hub": (dst_in_ratio >= hub_thr).astype(np.int8),
        "rule_low_reciprocity": (~reverse_exists).astype(np.int8),
        "rule_sink_or_low_recip": ((dst_in_ratio >= hub_thr) | (~reverse_exists)).astype(np.int8),
        "rule_src_or_sink_or_low_recip": (
            (src_out_ratio >= hub_thr) | (dst_in_ratio >= hub_thr) | (~reverse_exists)
        ).astype(np.int8),
    }

    results = {
        "dataset": {
            "data_dir": str(data_dir),
            "total_rows": int(total),
            "benign_rows": int(benign),
            "attack_rows": int(attack),
            "node_count": int(n_nodes),
            "edge_count": int(len(pair_df)),
            "hub_threshold": hub_thr,
        },
        "rules": {},
    }

    for name, pred in rule_preds.items():
        metrics = _rates(y_true_attack=y_true, y_pred_attack=pred)
        metrics["pred_attack_rows"] = int(pred.sum())
        results["rules"][name] = metrics

    out_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[4/4] Writing markdown summary ...", flush=True)
    with out_md.open("w", encoding="utf-8") as f:
        f.write("# 2017 Topology Rule Detector Evaluation\n\n")
        f.write(
            f"- total={total}, benign={benign}, attack={attack}, nodes={n_nodes}, edges={len(pair_df)}, hub_threshold={hub_thr}\n\n"
        )
        f.write("| Rule | PredAttack | FPR | FNR | TPR | Precision |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for rule_name, m in results["rules"].items():
            f.write(
                f"| {rule_name} | {int(m['pred_attack_rows'])} | {m['fpr']:.4%} | {m['fnr']:.4%} | {m['tpr']:.4%} | {m['precision']:.4%} |\n"
            )

    print(f"      out_json={out_json}", flush=True)
    print(f"      out_md={out_md}", flush=True)


if __name__ == "__main__":
    main()

