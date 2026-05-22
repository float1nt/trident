#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import networkx as nx
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import roc_auc_score


COL_ALIASES = {
    "src_ip": ["Src IP", "Source IP", "src_ip", "source_ip", " Source IP"],
    "dst_ip": ["Dst IP", "Destination IP", "dst_ip", "destination_ip", " Destination IP"],
    "src_port": ["Src Port", "Source Port", "src_port", "source_port", " Source Port"],
    "dst_port": ["Dst Port", "Destination Port", "dst_port", "destination_port", " Destination Port"],
}


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


def _detect_columns(csv_path: Path) -> Dict[str, str]:
    cols = pd.read_csv(csv_path, nrows=0).columns.tolist()
    return {k: _resolve_col(cols, aliases) for k, aliases in COL_ALIASES.items()}


def _learner_metrics(name: str, df: pd.DataFrame) -> Dict[str, object]:
    n_samples = len(df)
    if n_samples == 0:
        return {
            "learner_name": name,
            "samples": 0,
            "nodes": 0,
            "edges": 0,
            "density": 0.0,
            "components_weak": 0,
            "largest_component_ratio": 0.0,
            "reciprocity": 0.0,
            "max_out_degree": 0,
            "max_in_degree": 0,
            "hub_out_ratio": 0.0,
            "hub_in_ratio": 0.0,
        }

    src = df["SrcEP"].astype(str)
    dst = df["DstEP"].astype(str)
    edge_counts = (
        pd.DataFrame({"src": src, "dst": dst})
        .groupby(["src", "dst"], as_index=False)
        .size()
        .rename(columns={"size": "weight"})
    )
    n_edges = int(len(edge_counts))
    nodes = pd.Index(edge_counts["src"]).union(pd.Index(edge_counts["dst"]))
    n_nodes = int(len(nodes))

    if n_nodes == 0:
        return {
            "learner_name": name,
            "samples": int(n_samples),
            "nodes": 0,
            "edges": 0,
            "density": 0.0,
            "components_weak": 0,
            "largest_component_ratio": 0.0,
            "reciprocity": 0.0,
            "max_out_degree": 0,
            "max_in_degree": 0,
            "hub_out_ratio": 0.0,
            "hub_in_ratio": 0.0,
        }

    out_deg = edge_counts.groupby("src")["dst"].nunique().to_dict()
    in_deg = edge_counts.groupby("dst")["src"].nunique().to_dict()
    out_strength = edge_counts.groupby("src")["weight"].sum().to_dict()
    in_strength = edge_counts.groupby("dst")["weight"].sum().to_dict()
    max_out = int(max(out_deg.values(), default=0))
    max_in = int(max(in_deg.values(), default=0))
    max_out_strength = int(max(out_strength.values(), default=0))
    max_in_strength = int(max(in_strength.values(), default=0))
    denom = max(1, n_nodes - 1)
    hub_out_ratio = float(max_out / denom)
    hub_in_ratio = float(max_in / denom)
    hub_out_strength_ratio = float(max_out_strength / max(1, n_samples))
    hub_in_strength_ratio = float(max_in_strength / max(1, n_samples))

    g = nx.DiGraph()
    pair_w = {}
    for r in edge_counts.itertuples(index=False):
        g.add_edge(r.src, r.dst, weight=int(r.weight))
        pair_w[(str(r.src), str(r.dst))] = int(r.weight)
    reciprocity = float(nx.reciprocity(g) or 0.0)
    density = float(nx.density(g))

    recip_weight_num = 0.0
    recip_weight_den = float(sum(pair_w.values()))
    for (u, v), w in pair_w.items():
        rv = pair_w.get((v, u), 0)
        if rv > 0:
            recip_weight_num += min(float(w), float(rv))
    weighted_reciprocity = float(recip_weight_num / max(1e-12, recip_weight_den))

    ug = g.to_undirected()
    comps = list(nx.connected_components(ug))
    cnum = len(comps)
    largest_cc = max((len(c) for c in comps), default=0)
    largest_cc_ratio = float(largest_cc / max(1, n_nodes))

    # Distribution / concentration features
    out_deg_arr = np.asarray(list(out_deg.values()), dtype=np.float64) if out_deg else np.zeros(1, dtype=np.float64)
    in_deg_arr = np.asarray(list(in_deg.values()), dtype=np.float64) if in_deg else np.zeros(1, dtype=np.float64)
    edge_w_arr = edge_counts["weight"].to_numpy(np.float64) if n_edges else np.zeros(1, dtype=np.float64)

    def _entropy(x: np.ndarray) -> float:
        x = np.asarray(x, dtype=np.float64)
        s = float(np.sum(x))
        if s <= 0:
            return 0.0
        p = x / s
        p = p[p > 0]
        return float(-np.sum(p * np.log(p)))

    def _gini(x: np.ndarray) -> float:
        x = np.asarray(x, dtype=np.float64)
        x = x[x >= 0]
        if len(x) == 0:
            return 0.0
        if np.allclose(x, 0.0):
            return 0.0
        x = np.sort(x)
        n = len(x)
        cum = np.cumsum(x)
        return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)

    top1_edge_share = float(np.max(edge_w_arr) / max(1.0, float(np.sum(edge_w_arr))))
    top5_edge_share = float(np.sum(np.sort(edge_w_arr)[-5:]) / max(1.0, float(np.sum(edge_w_arr))))
    out_deg_entropy = _entropy(out_deg_arr)
    in_deg_entropy = _entropy(in_deg_arr)
    edge_w_entropy = _entropy(edge_w_arr)
    out_gini = _gini(out_deg_arr)
    in_gini = _gini(in_deg_arr)
    unique_src = int(edge_counts["src"].nunique())
    unique_dst = int(edge_counts["dst"].nunique())
    src_ratio = float(unique_src / max(1, n_nodes))
    dst_ratio = float(unique_dst / max(1, n_nodes))
    src_dst_asymmetry = float(abs(unique_src - unique_dst) / max(1, n_nodes))
    edge_reuse_ratio = float(n_samples / max(1, n_edges))
    edge_per_node = float(n_edges / max(1, n_nodes))
    ug_deg = np.asarray([d for _, d in ug.degree()], dtype=np.float64) if n_nodes > 0 else np.zeros(1, dtype=np.float64)
    leaf_ratio = float(np.mean(ug_deg <= 1.0)) if len(ug_deg) else 0.0
    high_deg_tail_ratio = float(np.mean(ug_deg >= 10.0)) if len(ug_deg) else 0.0

    return {
        "learner_name": name,
        "samples": int(n_samples),
        "nodes": int(n_nodes),
        "edges": int(n_edges),
        "density": density,
        "components_weak": int(cnum),
        "largest_component_ratio": largest_cc_ratio,
        "reciprocity": reciprocity,
        "max_out_degree": int(max_out),
        "max_in_degree": int(max_in),
        "hub_out_ratio": hub_out_ratio,
        "hub_in_ratio": hub_in_ratio,
        "max_out_strength": int(max_out_strength),
        "max_in_strength": int(max_in_strength),
        "hub_out_strength_ratio": hub_out_strength_ratio,
        "hub_in_strength_ratio": hub_in_strength_ratio,
        "weighted_reciprocity": weighted_reciprocity,
        "top1_edge_share": top1_edge_share,
        "top5_edge_share": top5_edge_share,
        "out_deg_entropy": out_deg_entropy,
        "in_deg_entropy": in_deg_entropy,
        "edge_w_entropy": edge_w_entropy,
        "out_deg_gini": out_gini,
        "in_deg_gini": in_gini,
        "edge_reuse_ratio": edge_reuse_ratio,
        "edge_per_node": edge_per_node,
        "src_endpoint_ratio": src_ratio,
        "dst_endpoint_ratio": dst_ratio,
        "src_dst_asymmetry": src_dst_asymmetry,
        "leaf_ratio": leaf_ratio,
        "high_deg_tail_ratio": high_deg_tail_ratio,
    }


def _auc_safe(y: np.ndarray, x: np.ndarray) -> float:
    yv = np.asarray(y, dtype=np.int32)
    xv = np.asarray(x, dtype=np.float64)
    if len(np.unique(yv)) < 2:
        return float("nan")
    if np.allclose(xv, xv[0]):
        return float("nan")
    return float(roc_auc_score(yv, xv))


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze per-learner internal topology distinguishability.")
    parser.add_argument("--run-dir", required=True, help="Path to outputs/runs/<run_id>")
    parser.add_argument(
        "--out-prefix",
        default="outputs/analysis/learner_internal_topology",
        help="Output prefix for csv/json/md",
    )
    parser.add_argument("--min-samples-per-learner", type=int, default=200)
    parser.add_argument("--attack-ratio-threshold", type=float, default=0.5)
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    cfg_path = run_dir / "config_snapshot.yaml"
    assign_path = run_dir / "sample_learner_assignments.csv"
    learner_dist_path = run_dir / "learner_label_distribution.csv"
    if not cfg_path.exists() or not assign_path.exists() or not learner_dist_path.exists():
        raise FileNotFoundError("Missing required files in run dir.")

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    data_dir = Path("/home/sr/97/trident") / str(cfg.get("paths", {}).get("data_dir", "data"))
    input_files = list(cfg.get("paths", {}).get("input_files", []))
    if not input_files:
        raise ValueError("config_snapshot.yaml does not contain paths.input_files")
    source_csv = data_dir / str(input_files[0])
    if not source_csv.exists():
        raise FileNotFoundError(f"Source csv not found: {source_csv}")

    print("[1/5] Loading learner assignment and labels ...", flush=True)
    assign_df = pd.read_csv(assign_path, usecols=["row_index", "assigned_learner", "phase"])
    assign_df = assign_df[assign_df["phase"].astype(str) == "stream"].copy()
    assign_df["row_index"] = assign_df["row_index"].astype(np.int64)
    assign_df["assigned_learner"] = assign_df["assigned_learner"].astype(str)

    ldf = pd.read_csv(learner_dist_path, usecols=["learner_name", "attack_ratio", "total_assigned_samples"])
    ldf["learner_name"] = ldf["learner_name"].astype(str)
    ldf["attack_ratio"] = pd.to_numeric(ldf["attack_ratio"], errors="coerce").fillna(0.0)
    ldf["is_attack_learner"] = (ldf["attack_ratio"] >= float(args.attack_ratio_threshold)).astype(np.int8)
    learner_label_map = ldf.set_index("learner_name")[["attack_ratio", "is_attack_learner"]].to_dict(orient="index")

    print("[2/5] Loading source flow endpoints ...", flush=True)
    col_map = _detect_columns(source_csv)
    usecols = [col_map["src_ip"], col_map["dst_ip"], col_map["src_port"], col_map["dst_port"]]
    flow_df = pd.read_csv(source_csv, low_memory=False, usecols=lambda c: c in usecols)
    flow_df = flow_df.rename(
        columns={
            col_map["src_ip"]: "SrcIP",
            col_map["dst_ip"]: "DstIP",
            col_map["src_port"]: "SrcPort",
            col_map["dst_port"]: "DstPort",
        }
    )
    flow_df["row_index"] = np.arange(len(flow_df), dtype=np.int64)
    flow_df["SrcEP"] = flow_df["SrcIP"].astype(str).str.strip() + ":" + flow_df["SrcPort"].astype(str).str.strip()
    flow_df["DstEP"] = flow_df["DstIP"].astype(str).str.strip() + ":" + flow_df["DstPort"].astype(str).str.strip()
    flow_df = flow_df[["row_index", "SrcEP", "DstEP"]]

    print("[3/5] Joining assignments with flows ...", flush=True)
    merged = assign_df.merge(flow_df, on="row_index", how="left")
    merged = merged.dropna(subset=["SrcEP", "DstEP"])

    print("[4/5] Computing per-learner topology metrics ...", flush=True)
    rows: List[Dict[str, object]] = []
    for learner, grp in merged.groupby("assigned_learner", sort=True):
        if learner not in learner_label_map:
            continue
        if len(grp) < int(args.min_samples_per_learner):
            continue
        m = _learner_metrics(str(learner), grp[["SrcEP", "DstEP"]])
        m["attack_ratio"] = float(learner_label_map[learner]["attack_ratio"])
        m["is_attack_learner"] = int(learner_label_map[learner]["is_attack_learner"])
        rows.append(m)
    metric_df = pd.DataFrame(rows)
    if metric_df.empty:
        raise RuntimeError("No learners satisfy min-samples filter for topology analysis.")

    feature_cols = [
        c
        for c in metric_df.columns
        if c
        not in {
            "learner_name",
            "attack_ratio",
            "is_attack_learner",
        }
    ]

    benign_df = metric_df[metric_df["is_attack_learner"] == 0]
    attack_df = metric_df[metric_df["is_attack_learner"] == 1]
    sep_rows: List[Dict[str, object]] = []
    y = metric_df["is_attack_learner"].to_numpy(np.int32)
    for c in feature_cols:
        x = metric_df[c].to_numpy(np.float64)
        auc = _auc_safe(y, x)
        sep_rows.append(
            {
                "feature": c,
                "auc_attack_vs_benign": auc,
                "benign_mean": float(np.mean(benign_df[c])) if len(benign_df) else float("nan"),
                "attack_mean": float(np.mean(attack_df[c])) if len(attack_df) else float("nan"),
                "benign_median": float(np.median(benign_df[c])) if len(benign_df) else float("nan"),
                "attack_median": float(np.median(attack_df[c])) if len(attack_df) else float("nan"),
            }
        )
    sep_df = pd.DataFrame(sep_rows).sort_values(
        by="auc_attack_vs_benign", ascending=False, na_position="last"
    )

    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    learner_csv = out_prefix.with_suffix(".per_learner.csv")
    sep_csv = out_prefix.with_suffix(".separation.csv")
    out_json = out_prefix.with_suffix(".json")
    out_md = out_prefix.with_suffix(".md")

    metric_df.sort_values(by=["is_attack_learner", "attack_ratio", "samples"], ascending=[False, False, False]).to_csv(
        learner_csv, index=False
    )
    sep_df.to_csv(sep_csv, index=False)

    summary = {
        "run_dir": str(run_dir),
        "source_csv": str(source_csv),
        "min_samples_per_learner": int(args.min_samples_per_learner),
        "attack_ratio_threshold": float(args.attack_ratio_threshold),
        "learner_count_used": int(len(metric_df)),
        "attack_learner_count": int((metric_df["is_attack_learner"] == 1).sum()),
        "benign_learner_count": int((metric_df["is_attack_learner"] == 0).sum()),
        "best_separating_features": sep_df.head(5).to_dict(orient="records"),
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[5/5] Writing markdown report ...", flush=True)
    with out_md.open("w", encoding="utf-8") as f:
        f.write("# Learner Internal Topology Distinguishability Report\n\n")
        f.write(f"- run_dir: `{run_dir}`\n")
        f.write(f"- source_csv: `{source_csv}`\n")
        f.write(f"- learners_used: {summary['learner_count_used']} (attack={summary['attack_learner_count']}, benign={summary['benign_learner_count']})\n")
        f.write(
            f"- min_samples_per_learner: {summary['min_samples_per_learner']}, attack_ratio_threshold: {summary['attack_ratio_threshold']}\n\n"
        )
        f.write("## Feature Separability (AUC attack-learner vs benign-learner)\n\n")
        f.write("| Feature | AUC | BenignMean | AttackMean | BenignMedian | AttackMedian |\n")
        f.write("|---|---:|---:|---:|---:|---:|\n")
        for r in sep_df.to_dict(orient="records"):
            auc = r["auc_attack_vs_benign"]
            auc_text = "nan" if not np.isfinite(auc) else f"{float(auc):.4f}"
            f.write(
                f"| {r['feature']} | {auc_text} | {float(r['benign_mean']):.6f} | {float(r['attack_mean']):.6f} "
                f"| {float(r['benign_median']):.6f} | {float(r['attack_median']):.6f} |\n"
            )
        f.write("\n")
        f.write("## Interpretation Guide\n\n")
        f.write("- AUC 越接近 1.0：该拓扑指标越能区分异常学习器与正常学习器。\n")
        f.write("- AUC 约 0.5：几乎无区分度。\n")
        f.write("- 若大多数指标 AUC 接近 0.5，说明仅靠簇内拓扑结构不足以区分。\n")

    print(f"      per_learner_csv={learner_csv}", flush=True)
    print(f"      separation_csv={sep_csv}", flush=True)
    print(f"      summary_json={out_json}", flush=True)
    print(f"      report_md={out_md}", flush=True)


if __name__ == "__main__":
    main()

