#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import networkx as nx
import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold


COL_ALIASES = {
    "src_ip": ["Src IP", "Source IP", "src_ip", "source_ip", " Source IP"],
    "dst_ip": ["Dst IP", "Destination IP", "dst_ip", "destination_ip", " Destination IP"],
    "src_port": ["Src Port", "Source Port", "src_port", "source_port", " Source Port"],
    "dst_port": ["Dst Port", "Destination Port", "dst_port", "destination_port", " Destination Port"],
}

LABEL_ALIASES = ["Label", "label", " Label", "Attack", "attack", "is_attack", "target", "Target"]

NUMERIC_EXCLUDE = {
    "row_index",
    "assigned_learner",
    "phase",
    "learner_name",
    "is_attack_learner",
    "attack_ratio",
}

EXCLUDE_KEYWORDS = [
    "label",
    "attack",
    "target",
    "year_tag",
    "dataset",
    "source_file",
    "row_index",
    "index",
    "assigned_learner",
    "learner_name",
    "phase",
    "fold",
    "split",
]


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


def _detect_endpoint_cols(csv_path: Path) -> Dict[str, str]:
    cols = pd.read_csv(csv_path, nrows=0).columns.tolist()
    return {k: _resolve_col(cols, aliases) for k, aliases in COL_ALIASES.items()}


def _detect_label_col(columns: Sequence[str]) -> Optional[str]:
    norm = {str(c).strip().lower(): c for c in columns}
    for alias in LABEL_ALIASES:
        key = str(alias).strip().lower()
        if key in norm:
            return str(norm[key])
    return None


def _safe_entropy(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    s = float(np.sum(x))
    if s <= 0:
        return 0.0
    p = x / s
    p = p[p > 0]
    return float(-np.sum(p * np.log(p)))


def _safe_gini(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=np.float64)
    x = x[x >= 0]
    if len(x) == 0 or np.allclose(x, 0.0):
        return 0.0
    x = np.sort(x)
    n = len(x)
    cum = np.cumsum(x)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)


def _learner_topology_metrics(name: str, df: pd.DataFrame) -> Dict[str, object]:
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
    pair_w: Dict[Tuple[str, str], int] = {}
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

    out_deg_arr = np.asarray(list(out_deg.values()), dtype=np.float64) if out_deg else np.zeros(1, dtype=np.float64)
    in_deg_arr = np.asarray(list(in_deg.values()), dtype=np.float64) if in_deg else np.zeros(1, dtype=np.float64)
    edge_w_arr = edge_counts["weight"].to_numpy(np.float64) if n_edges else np.zeros(1, dtype=np.float64)

    top1_edge_share = float(np.max(edge_w_arr) / max(1.0, float(np.sum(edge_w_arr))))
    top5_edge_share = float(np.sum(np.sort(edge_w_arr)[-5:]) / max(1.0, float(np.sum(edge_w_arr))))
    out_deg_entropy = _safe_entropy(out_deg_arr)
    in_deg_entropy = _safe_entropy(in_deg_arr)
    edge_w_entropy = _safe_entropy(edge_w_arr)
    out_gini = _safe_gini(out_deg_arr)
    in_gini = _safe_gini(in_deg_arr)
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


@dataclass(frozen=True)
class Expr:
    op: str
    left: Optional["Expr"] = None
    right: Optional["Expr"] = None
    feature: Optional[str] = None
    const: Optional[float] = None

    def size(self) -> int:
        if self.op in {"feat", "const"}:
            return 1
        if self.op in {"abs", "sqrt", "log1p", "neg"}:
            return 1 + (self.left.size() if self.left is not None else 0)
        return 1 + (self.left.size() if self.left is not None else 0) + (self.right.size() if self.right is not None else 0)

    def to_string(self) -> str:
        if self.op == "feat":
            return str(self.feature)
        if self.op == "const":
            return f"{self.const:.6g}"
        if self.op == "abs":
            return f"abs({self.left.to_string()})"
        if self.op == "sqrt":
            return f"sqrt_abs({self.left.to_string()})"
        if self.op == "log1p":
            return f"log1p_abs({self.left.to_string()})"
        if self.op == "neg":
            return f"(-{self.left.to_string()})"
        return f"({self.left.to_string()} {self.op} {self.right.to_string()})"

    def eval(self, values: Dict[str, np.ndarray]) -> np.ndarray:
        if self.op == "feat":
            if self.feature is None:
                raise ValueError("feature node missing feature name")
            return values[self.feature]
        if self.op == "const":
            if self.const is None:
                raise ValueError("const node missing value")
            n = len(next(iter(values.values())))
            return np.full(n, float(self.const), dtype=np.float64)
        if self.op == "abs":
            return np.abs(self.left.eval(values))
        if self.op == "sqrt":
            return np.sqrt(np.abs(self.left.eval(values)) + 1e-12)
        if self.op == "log1p":
            return np.log1p(np.abs(self.left.eval(values)))
        if self.op == "neg":
            return -self.left.eval(values)

        a = self.left.eval(values)
        b = self.right.eval(values)
        if self.op == "+":
            return a + b
        if self.op == "-":
            return a - b
        if self.op == "*":
            return a * b
        if self.op == "/":
            return a / (np.abs(b) + 1e-6)
        if self.op == "max":
            return np.maximum(a, b)
        if self.op == "min":
            return np.minimum(a, b)
        raise ValueError(f"Unsupported op: {self.op}")


UNARY_OPS = ["abs", "sqrt", "log1p", "neg"]
BINARY_OPS = ["+", "-", "*", "/", "max", "min"]


def _random_terminal(features: Sequence[str], rng: random.Random) -> Expr:
    if rng.random() < 0.85:
        return Expr(op="feat", feature=str(rng.choice(features)))
    return Expr(op="const", const=rng.uniform(-2.0, 2.0))


def _random_expr(features: Sequence[str], max_depth: int, rng: random.Random) -> Expr:
    if max_depth <= 1 or rng.random() < 0.3:
        return _random_terminal(features, rng)
    if rng.random() < 0.35:
        op = rng.choice(UNARY_OPS)
        return Expr(op=op, left=_random_expr(features, max_depth - 1, rng))
    op = rng.choice(BINARY_OPS)
    return Expr(
        op=op,
        left=_random_expr(features, max_depth - 1, rng),
        right=_random_expr(features, max_depth - 1, rng),
    )


def _collect_paths(expr: Expr, base: Tuple[int, ...] = ()) -> List[Tuple[int, ...]]:
    paths = [base]
    if expr.op in {"feat", "const"}:
        return paths
    if expr.left is not None:
        paths.extend(_collect_paths(expr.left, base + (0,)))
    if expr.right is not None:
        paths.extend(_collect_paths(expr.right, base + (1,)))
    return paths


def _get_subtree(expr: Expr, path: Tuple[int, ...]) -> Expr:
    cur = expr
    for p in path:
        if p == 0:
            if cur.left is None:
                break
            cur = cur.left
        else:
            if cur.right is None:
                break
            cur = cur.right
    return cur


def _replace_subtree(expr: Expr, path: Tuple[int, ...], new_sub: Expr) -> Expr:
    if not path:
        return new_sub
    step = path[0]
    if step == 0:
        return Expr(op=expr.op, left=_replace_subtree(expr.left, path[1:], new_sub), right=expr.right, feature=expr.feature, const=expr.const)
    return Expr(op=expr.op, left=expr.left, right=_replace_subtree(expr.right, path[1:], new_sub), feature=expr.feature, const=expr.const)


def _mutate(expr: Expr, features: Sequence[str], max_depth: int, rng: random.Random) -> Expr:
    paths = _collect_paths(expr)
    path = rng.choice(paths)
    new_sub = _random_expr(features, max_depth=max(2, max_depth // 2), rng=rng)
    return _replace_subtree(expr, path, new_sub)


def _crossover(a: Expr, b: Expr, rng: random.Random) -> Expr:
    pa = rng.choice(_collect_paths(a))
    pb = rng.choice(_collect_paths(b))
    sub_b = _get_subtree(b, pb)
    return _replace_subtree(a, pa, sub_b)


def _auc_safe(y: np.ndarray, x: np.ndarray) -> float:
    if len(np.unique(y)) < 2:
        return float("nan")
    if np.allclose(x, x[0]):
        return float("nan")
    return float(roc_auc_score(y, x))


def _cv_auc(y: np.ndarray, x: np.ndarray, cv_folds: int, rng_seed: int = 42) -> float:
    if len(np.unique(y)) < 2:
        return float("nan")
    if np.allclose(x, x[0]):
        return float("nan")
    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    folds = int(max(2, min(cv_folds, pos, neg)))
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=rng_seed)
    aucs: List[float] = []
    for _, te_idx in cv.split(np.zeros(len(y)), y):
        yy = y[te_idx]
        xx = x[te_idx]
        if len(np.unique(yy)) < 2 or np.allclose(xx, xx[0]):
            continue
        aucs.append(float(roc_auc_score(yy, xx)))
    if not aucs:
        return float("nan")
    return float(np.mean(aucs))


def _feature_pool_from_source(
    source_df: pd.DataFrame,
    merged: pd.DataFrame,
    max_numeric_cols: int,
) -> Tuple[pd.DataFrame, List[str]]:
    candidate = source_df.select_dtypes(include=[np.number]).columns.tolist()
    candidate = [c for c in candidate if c not in NUMERIC_EXCLUDE and not str(c).startswith("Unnamed")]
    candidate = [
        c
        for c in candidate
        if not any(k in str(c).strip().lower() for k in EXCLUDE_KEYWORDS)
    ]
    if not candidate:
        raise RuntimeError("No numeric source features found for aggregation.")

    clean_numeric = source_df[candidate].replace([np.inf, -np.inf], np.nan)
    if len(candidate) > max_numeric_cols:
        variances = clean_numeric.var(axis=0, numeric_only=True).sort_values(ascending=False)
        candidate = list(variances.index[:max_numeric_cols])
        clean_numeric = clean_numeric[candidate]

    joined = merged[["assigned_learner", "row_index"]].merge(
        pd.concat([source_df[["row_index"]], clean_numeric], axis=1),
        on="row_index",
        how="left",
    )
    grouped = joined.groupby("assigned_learner", sort=True)

    stat_names: List[str] = []
    parts: List[pd.DataFrame] = []
    for stat, fn in [
        ("mean", lambda x: x.mean()),
        ("std", lambda x: x.std(ddof=0)),
        ("median", lambda x: x.median()),
        ("p10", lambda x: x.quantile(0.10)),
        ("p90", lambda x: x.quantile(0.90)),
        ("iqr", lambda x: x.quantile(0.75) - x.quantile(0.25)),
    ]:
        agg = grouped[candidate].apply(fn).reset_index()
        rename_map = {c: f"src_{c}_{stat}" for c in candidate}
        agg = agg.rename(columns=rename_map)
        stat_names.extend([rename_map[c] for c in candidate])
        parts.append(agg)

    out = parts[0]
    for p in parts[1:]:
        out = out.merge(p, on="assigned_learner", how="inner")
    out = out.rename(columns={"assigned_learner": "learner_name"})
    return out, stat_names


def _build_learner_dataset(
    run_dir: Path,
    min_samples_per_learner: int,
    attack_ratio_threshold: float,
    max_numeric_cols: int,
) -> Tuple[pd.DataFrame, Path]:
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

    assign_df = pd.read_csv(assign_path, usecols=["row_index", "assigned_learner", "phase"])
    assign_df = assign_df[assign_df["phase"].astype(str) == "stream"].copy()
    assign_df["row_index"] = assign_df["row_index"].astype(np.int64)
    assign_df["assigned_learner"] = assign_df["assigned_learner"].astype(str)

    ldf = pd.read_csv(learner_dist_path, usecols=["learner_name", "attack_ratio", "total_assigned_samples"])
    ldf["learner_name"] = ldf["learner_name"].astype(str)
    ldf["attack_ratio"] = pd.to_numeric(ldf["attack_ratio"], errors="coerce").fillna(0.0)
    ldf["is_attack_learner"] = (ldf["attack_ratio"] >= float(attack_ratio_threshold)).astype(np.int8)
    learner_label_df = ldf[["learner_name", "attack_ratio", "is_attack_learner"]].copy()

    endpoint_cols = _detect_endpoint_cols(source_csv)
    head_cols = pd.read_csv(source_csv, nrows=0).columns.tolist()
    label_col = _detect_label_col(head_cols)
    read_cols = list(endpoint_cols.values())
    if label_col is not None:
        read_cols.append(label_col)
    source_df = pd.read_csv(source_csv, low_memory=False)
    source_df["row_index"] = np.arange(len(source_df), dtype=np.int64)
    source_df["SrcEP"] = source_df[endpoint_cols["src_ip"]].astype(str).str.strip() + ":" + source_df[endpoint_cols["src_port"]].astype(str).str.strip()
    source_df["DstEP"] = source_df[endpoint_cols["dst_ip"]].astype(str).str.strip() + ":" + source_df[endpoint_cols["dst_port"]].astype(str).str.strip()

    merged = assign_df.merge(source_df[["row_index", "SrcEP", "DstEP"]], on="row_index", how="left")
    merged = merged.dropna(subset=["SrcEP", "DstEP"])

    topology_rows: List[Dict[str, object]] = []
    for learner, grp in merged.groupby("assigned_learner", sort=True):
        if len(grp) < int(min_samples_per_learner):
            continue
        topology_rows.append(_learner_topology_metrics(str(learner), grp[["SrcEP", "DstEP"]]))
    topo_df = pd.DataFrame(topology_rows)
    if topo_df.empty:
        raise RuntimeError("No learners satisfy min-samples filter for topology aggregation.")

    numeric_pool_df, src_stat_cols = _feature_pool_from_source(source_df, merged, max_numeric_cols=max_numeric_cols)
    all_df = topo_df.merge(numeric_pool_df, on="learner_name", how="inner").merge(learner_label_df, on="learner_name", how="inner")
    all_df = all_df[all_df["samples"] >= int(min_samples_per_learner)].copy()
    all_df = all_df.replace([np.inf, -np.inf], np.nan)
    all_df = all_df.dropna(axis=1, how="all")

    # Drop nearly constant columns.
    feature_cols = [
        c
        for c in all_df.columns
        if c not in {"learner_name", "attack_ratio", "is_attack_learner"}
    ]
    keep_cols = []
    for c in feature_cols:
        x = pd.to_numeric(all_df[c], errors="coerce").to_numpy(np.float64)
        if np.all(~np.isfinite(x)):
            continue
        if float(np.nanstd(x)) < 1e-10:
            continue
        keep_cols.append(c)
    all_df = all_df[["learner_name", "attack_ratio", "is_attack_learner"] + keep_cols].copy()

    # Ensure finite fill for GA calculation.
    for c in keep_cols:
        xc = pd.to_numeric(all_df[c], errors="coerce")
        med = float(np.nanmedian(xc.to_numpy(np.float64)))
        all_df[c] = xc.fillna(med).astype(np.float64)

    return all_df, source_csv


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Genetic-programming based synthetic feature search for learner-level separation."
    )
    parser.add_argument("--run-dir", required=True, help="Path to outputs/runs/<run_id>")
    parser.add_argument(
        "--out-prefix",
        default="outputs/analysis/learner_feature_ga",
        help="Output prefix for csv/json/md",
    )
    parser.add_argument("--min-samples-per-learner", type=int, default=200)
    parser.add_argument("--attack-ratio-threshold", type=float, default=0.5)
    parser.add_argument("--max-numeric-source-cols", type=int, default=96, help="Limit source numeric cols by variance.")
    parser.add_argument("--population-size", type=int, default=320)
    parser.add_argument("--generations", type=int, default=45)
    parser.add_argument("--elite-size", type=int, default=30)
    parser.add_argument("--mutation-rate", type=float, default=0.35)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--cv-folds", type=int, default=4)
    parser.add_argument("--hall-of-fame", type=int, default=500, help="Max retained high-score unique expressions.")
    parser.add_argument("--top-k-output", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rng = random.Random(int(args.seed))
    np.random.seed(int(args.seed))

    run_dir = Path(args.run_dir).resolve()
    print("[1/4] Building learner-level feature pool ...", flush=True)
    learner_df, source_csv = _build_learner_dataset(
        run_dir=run_dir,
        min_samples_per_learner=int(args.min_samples_per_learner),
        attack_ratio_threshold=float(args.attack_ratio_threshold),
        max_numeric_cols=int(args.max_numeric_source_cols),
    )
    y = learner_df["is_attack_learner"].astype(np.int32).to_numpy()
    base_feature_cols = [c for c in learner_df.columns if c not in {"learner_name", "attack_ratio", "is_attack_learner"}]
    values = {c: learner_df[c].to_numpy(np.float64) for c in base_feature_cols}
    print(f"      learners={len(learner_df)}, base_features={len(base_feature_cols)}", flush=True)

    def evaluate(expr: Expr) -> Optional[Dict[str, object]]:
        try:
            x = expr.eval(values)
        except Exception:
            return None
        if x is None:
            return None
        x = np.asarray(x, dtype=np.float64)
        if len(x) != len(y):
            return None
        finite_mask = np.isfinite(x)
        finite_ratio = float(np.mean(finite_mask))
        if finite_ratio < 0.95:
            return None
        if not np.all(finite_mask):
            x = np.where(finite_mask, x, np.nanmedian(x[finite_mask]))
        if np.allclose(x, x[0]):
            return None

        auc_raw = _auc_safe(y, x)
        auc_cv = _cv_auc(y, x, cv_folds=int(args.cv_folds), rng_seed=int(args.seed))
        if not np.isfinite(auc_raw):
            return None
        auc_oriented = float(max(auc_raw, 1.0 - auc_raw))
        cv_oriented = auc_oriented if not np.isfinite(auc_cv) else float(max(auc_cv, 1.0 - auc_cv))
        complexity_penalty = 0.0025 * float(max(0, expr.size() - 1))
        fitness = 0.65 * cv_oriented + 0.35 * auc_oriented - complexity_penalty
        benign = x[y == 0]
        attack = x[y == 1]
        return {
            "expr": expr,
            "expr_str": expr.to_string(),
            "fitness": float(fitness),
            "auc": float(auc_raw),
            "auc_oriented": float(auc_oriented),
            "auc_cv_oriented": float(cv_oriented),
            "complexity": int(expr.size()),
            "benign_mean": float(np.mean(benign)) if len(benign) else float("nan"),
            "attack_mean": float(np.mean(attack)) if len(attack) else float("nan"),
            "std_all": float(np.std(x)),
            "value_vector": x,
        }

    print("[2/4] Running genetic search ...", flush=True)
    pop_size = int(args.population_size)
    elite_size = int(min(max(5, args.elite_size), pop_size))
    max_depth = int(max(2, args.max_depth))
    mutation_rate = float(min(max(0.01, args.mutation_rate), 0.99))
    hall_cap = int(max(50, args.hall_of_fame))

    population: List[Expr] = [_random_expr(base_feature_cols, max_depth=max_depth, rng=rng) for _ in range(pop_size)]
    hall: Dict[str, Dict[str, object]] = {}
    best_history: List[Dict[str, object]] = []

    def tournament_select(scored_list: List[Dict[str, object]], k: int = 5) -> Expr:
        picks = rng.sample(scored_list, k=min(k, len(scored_list)))
        picks = sorted(picks, key=lambda r: float(r["fitness"]), reverse=True)
        return picks[0]["expr"]

    for gen in range(int(args.generations)):
        scored: List[Dict[str, object]] = []
        seen_gen = set()
        for expr in population:
            expr_str = expr.to_string()
            if expr_str in seen_gen:
                continue
            seen_gen.add(expr_str)
            rec = evaluate(expr)
            if rec is not None:
                scored.append(rec)
        if not scored:
            population = [_random_expr(base_feature_cols, max_depth=max_depth, rng=rng) for _ in range(pop_size)]
            continue
        scored = sorted(scored, key=lambda r: float(r["fitness"]), reverse=True)

        for rec in scored:
            expr_str = str(rec["expr_str"])
            old = hall.get(expr_str)
            if old is None or float(rec["fitness"]) > float(old["fitness"]):
                hall[expr_str] = rec
        if len(hall) > hall_cap * 2:
            hall_items = sorted(hall.values(), key=lambda r: float(r["fitness"]), reverse=True)[:hall_cap]
            hall = {str(r["expr_str"]): r for r in hall_items}

        gen_best = scored[0]
        best_history.append(
            {
                "generation": gen,
                "best_expr": str(gen_best["expr_str"]),
                "best_fitness": float(gen_best["fitness"]),
                "best_auc_oriented": float(gen_best["auc_oriented"]),
                "best_auc_cv_oriented": float(gen_best["auc_cv_oriented"]),
                "best_complexity": int(gen_best["complexity"]),
            }
        )
        print(
            f"      gen={gen:03d} best_fitness={float(gen_best['fitness']):.4f} "
            f"auc*={float(gen_best['auc_oriented']):.4f} expr={str(gen_best['expr_str'])[:120]}",
            flush=True,
        )

        elites = [r["expr"] for r in scored[:elite_size]]
        next_pop: List[Expr] = elites[:]
        while len(next_pop) < pop_size:
            if rng.random() < mutation_rate:
                parent = tournament_select(scored, k=5)
                child = _mutate(parent, features=base_feature_cols, max_depth=max_depth, rng=rng)
            else:
                p1 = tournament_select(scored, k=5)
                p2 = tournament_select(scored, k=5)
                child = _crossover(p1, p2, rng=rng)
            # guard max complexity explosion
            if child.size() > 25:
                child = _random_expr(base_feature_cols, max_depth=max_depth, rng=rng)
            next_pop.append(child)
        population = next_pop[:pop_size]

    hall_sorted = sorted(hall.values(), key=lambda r: float(r["fitness"]), reverse=True)
    if not hall_sorted:
        raise RuntimeError("GA did not produce any valid feature expression.")
    top_k = int(min(max(10, args.top_k_output), len(hall_sorted)))
    top_rows = hall_sorted[:top_k]

    print("[3/4] Preparing outputs ...", flush=True)
    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    feature_csv = out_prefix.with_suffix(".features.csv")
    matrix_csv = out_prefix.with_suffix(".feature_matrix.csv")
    history_csv = out_prefix.with_suffix(".history.csv")
    summary_json = out_prefix.with_suffix(".json")
    report_md = out_prefix.with_suffix(".md")

    export_rows = []
    matrix_df = learner_df[["learner_name", "attack_ratio", "is_attack_learner"]].copy()
    for i, rec in enumerate(top_rows):
        feature_name = f"ga_feat_{i+1:03d}"
        vec = np.asarray(rec["value_vector"], dtype=np.float64)
        matrix_df[feature_name] = vec
        export_rows.append(
            {
                "rank": i + 1,
                "feature_name": feature_name,
                "expression": rec["expr_str"],
                "fitness": rec["fitness"],
                "auc": rec["auc"],
                "auc_oriented": rec["auc_oriented"],
                "auc_cv_oriented": rec["auc_cv_oriented"],
                "complexity": rec["complexity"],
                "benign_mean": rec["benign_mean"],
                "attack_mean": rec["attack_mean"],
                "std_all": rec["std_all"],
            }
        )

    pd.DataFrame(export_rows).to_csv(feature_csv, index=False)
    matrix_df.to_csv(matrix_csv, index=False)
    pd.DataFrame(best_history).to_csv(history_csv, index=False)

    summary = {
        "run_dir": str(run_dir),
        "source_csv": str(source_csv),
        "learners_used": int(len(learner_df)),
        "attack_learners": int((learner_df["is_attack_learner"] == 1).sum()),
        "benign_learners": int((learner_df["is_attack_learner"] == 0).sum()),
        "base_feature_count": int(len(base_feature_cols)),
        "ga_config": {
            "population_size": int(pop_size),
            "generations": int(args.generations),
            "elite_size": int(elite_size),
            "mutation_rate": float(mutation_rate),
            "max_depth": int(max_depth),
            "cv_folds": int(args.cv_folds),
            "seed": int(args.seed),
        },
        "top_feature_count": int(top_k),
        "best_feature": export_rows[0] if export_rows else None,
        "outputs": {
            "feature_csv": str(feature_csv),
            "feature_matrix_csv": str(matrix_csv),
            "history_csv": str(history_csv),
            "report_md": str(report_md),
        },
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("[4/4] Writing markdown report ...", flush=True)
    with report_md.open("w", encoding="utf-8") as f:
        f.write("# Learner Feature GA Synthesis Report\n\n")
        f.write(f"- run_dir: `{run_dir}`\n")
        f.write(f"- source_csv: `{source_csv}`\n")
        f.write(
            f"- learners_used: {summary['learners_used']} (attack={summary['attack_learners']}, benign={summary['benign_learners']})\n"
        )
        f.write(f"- base_feature_count: {summary['base_feature_count']}\n")
        f.write(
            f"- GA config: population={pop_size}, generations={int(args.generations)}, elite={elite_size}, "
            f"mutation_rate={mutation_rate:.2f}, max_depth={max_depth}, cv_folds={int(args.cv_folds)}, seed={int(args.seed)}\n\n"
        )
        f.write("## Top Synthetic Features\n\n")
        f.write("| Rank | Name | AUC* | CV-AUC* | Fitness | Complexity | Expression |\n")
        f.write("|---:|---|---:|---:|---:|---:|---|\n")
        for r in export_rows:
            f.write(
                f"| {int(r['rank'])} | {r['feature_name']} | {float(r['auc_oriented']):.4f} | "
                f"{float(r['auc_cv_oriented']):.4f} | {float(r['fitness']):.4f} | {int(r['complexity'])} | "
                f"`{str(r['expression']).replace('`', '')}` |\n"
            )
        f.write("\n")
        f.write("## Notes\n\n")
        f.write("- AUC* = max(AUC, 1-AUC)，忽略方向只看区分能力。\n")
        f.write("- 由于学习器样本数较少，CV-AUC* 仅作粗略稳健性参考，建议后续用时间切分或外部数据再验证。\n")

    print(f"feature_csv={feature_csv}", flush=True)
    print(f"feature_matrix_csv={matrix_csv}", flush=True)
    print(f"history_csv={history_csv}", flush=True)
    print(f"summary_json={summary_json}", flush=True)
    print(f"report_md={report_md}", flush=True)


if __name__ == "__main__":
    main()
