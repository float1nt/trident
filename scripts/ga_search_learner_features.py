#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

ENV_LIKE_FEATURES = {"id", "Flow ID", "Src Port", "Dst Port", "Timestamp"}


@dataclass
class Node:
    op: str
    value: Optional[str] = None
    left: Optional["Node"] = None
    right: Optional["Node"] = None


def _safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return a / np.where(np.abs(b) < 1e-8, 1e-8, b)


def _eval_tree(node: Node, x: np.ndarray, feat_map: Dict[str, int]) -> np.ndarray:
    if node.op == "feat":
        return x[:, feat_map[node.value]]
    if node.op == "const":
        return np.full((x.shape[0],), float(node.value), dtype=np.float64)
    if node.op == "abs":
        return np.abs(_eval_tree(node.left, x, feat_map))
    if node.op == "log1p":
        return np.log1p(np.abs(_eval_tree(node.left, x, feat_map)))
    if node.op == "sqrt":
        return np.sqrt(np.abs(_eval_tree(node.left, x, feat_map)))
    if node.op == "neg":
        return -_eval_tree(node.left, x, feat_map)
    a = _eval_tree(node.left, x, feat_map)
    b = _eval_tree(node.right, x, feat_map)
    if node.op == "add":
        return a + b
    if node.op == "sub":
        return a - b
    if node.op == "mul":
        return a * b
    if node.op == "div":
        return _safe_div(a, b)
    raise ValueError(f"Unknown op: {node.op}")


def _tree_to_str(node: Node) -> str:
    if node.op in {"feat", "const"}:
        return str(node.value)
    if node.op in {"abs", "log1p", "sqrt", "neg"}:
        return f"{node.op}({_tree_to_str(node.left)})"
    return f"({_tree_to_str(node.left)} {node.op} {_tree_to_str(node.right)})"


def _clone(node: Node) -> Node:
    return Node(
        op=node.op,
        value=node.value,
        left=_clone(node.left) if node.left is not None else None,
        right=_clone(node.right) if node.right is not None else None,
    )


def _collect_nodes_with_parent(root: Node) -> List[Tuple[Optional[Node], str, Node]]:
    out: List[Tuple[Optional[Node], str, Node]] = [(None, "root", root)]
    stack: List[Tuple[Optional[Node], str, Node]] = [(None, "root", root)]
    while stack:
        _, _, n = stack.pop()
        if n.left is not None:
            out.append((n, "left", n.left))
            stack.append((n, "left", n.left))
        if n.right is not None:
            out.append((n, "right", n.right))
            stack.append((n, "right", n.right))
    return out


def _random_terminal(features: List[str], rng: random.Random) -> Node:
    if rng.random() < 0.8:
        return Node(op="feat", value=rng.choice(features))
    return Node(op="const", value=str(rng.choice([0.1, 0.2, 0.5, 1.0, 2.0, 5.0])))


def _random_tree(features: List[str], rng: random.Random, depth: int) -> Node:
    if depth <= 0 or rng.random() < 0.35:
        return _random_terminal(features, rng)
    if rng.random() < 0.35:
        op = rng.choice(["abs", "log1p", "sqrt", "neg"])
        return Node(op=op, left=_random_tree(features, rng, depth - 1))
    op = rng.choice(["add", "sub", "mul", "div"])
    return Node(op=op, left=_random_tree(features, rng, depth - 1), right=_random_tree(features, rng, depth - 1))


def _mutate(tree: Node, features: List[str], rng: random.Random, max_depth: int = 3) -> Node:
    root = _clone(tree)
    nodes = _collect_nodes_with_parent(root)
    parent, side, _ = rng.choice(nodes)
    new_sub = _random_tree(features, rng, max_depth)
    if parent is None:
        return new_sub
    if side == "left":
        parent.left = new_sub
    elif side == "right":
        parent.right = new_sub
    return root


def _crossover(a: Node, b: Node, rng: random.Random) -> Node:
    a2 = _clone(a)
    b2 = _clone(b)
    nodes_a = _collect_nodes_with_parent(a2)
    nodes_b = _collect_nodes_with_parent(b2)
    pa, side_a, _ = rng.choice(nodes_a)
    _, _, sub_b = rng.choice(nodes_b)
    repl = _clone(sub_b)
    if pa is None:
        return repl
    if side_a == "left":
        pa.left = repl
    elif side_a == "right":
        pa.right = repl
    return a2


def _fit_auc(y: np.ndarray, score: np.ndarray) -> float:
    if np.allclose(score, score[0]):
        return 0.5
    s = np.nan_to_num(score.astype(np.float64), nan=0.0, posinf=1e6, neginf=-1e6)
    auc = float(roc_auc_score(y, s))
    return max(auc, 1.0 - auc)


def _discover_numeric_features(source_csv: Path, preview_rows: int, drop_env_like: bool) -> List[str]:
    preview = pd.read_csv(source_csv, nrows=preview_rows, low_memory=False)
    cols = []
    for c in preview.columns:
        if pd.api.types.is_numeric_dtype(preview[c]):
            if c.lower() in {"label", "labelnorm"}:
                continue
            if drop_env_like and c in ENV_LIKE_FEATURES:
                continue
            cols.append(str(c))
    return cols


def _load_run_source_csv(run_dir: Path) -> Path:
    cfg_files = list(run_dir.glob("*_config_*.yaml")) or list(run_dir.glob("*.yaml"))
    if not cfg_files:
        raise FileNotFoundError(f"No config yaml found in {run_dir}")
    cfg_path = sorted(cfg_files)[0]
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    input_files = []
    if isinstance(cfg.get("data", {}), dict):
        input_files = cfg.get("data", {}).get("input_files", []) or []
    if not input_files and isinstance(cfg.get("paths", {}), dict):
        input_files = cfg.get("paths", {}).get("input_files", []) or []
    if not input_files:
        raise ValueError(f"No data.input_files in {cfg_path}")
    data_dir = ""
    if isinstance(cfg.get("data", {}), dict):
        data_dir = str(cfg.get("data", {}).get("data_dir", "") or "")
    if (not data_dir) and isinstance(cfg.get("paths", {}), dict):
        data_dir = str(cfg.get("paths", {}).get("data_dir", "") or "")

    p = Path(str(input_files[0]))
    if p.is_absolute():
        return p.resolve()

    repo_root = run_dir.parent.parent.parent
    if data_dir:
        cand = (repo_root / data_dir / p).resolve()
        if cand.exists():
            return cand
    return (repo_root / p).resolve()
    return p


def _aggregate_numeric_by_learner(
    source_csv: Path,
    assignments_csv: Path,
    numeric_cols: List[str],
    chunksize: int,
) -> pd.DataFrame:
    assign = pd.read_csv(assignments_csv, usecols=["row_index", "assigned_learner"])
    assign = assign.dropna(subset=["assigned_learner"])
    assign["row_index"] = assign["row_index"].astype(np.int64)
    assign["assigned_learner"] = assign["assigned_learner"].astype(str)
    assign_map = assign.set_index("row_index")["assigned_learner"]

    states: Dict[str, Dict[str, np.ndarray | float]] = {}
    feat_n = len(numeric_cols)
    start = 0
    usecols = numeric_cols
    for chunk in pd.read_csv(source_csv, usecols=usecols, chunksize=chunksize, low_memory=False):
        end = start + len(chunk)
        idx = np.arange(start, end, dtype=np.int64)
        start = end
        learner = assign_map.reindex(idx).to_numpy()
        mask = pd.notna(learner)
        if not mask.any():
            continue
        df = chunk.loc[mask, :].copy()
        df["assigned_learner"] = learner[mask].astype(str)
        for name, g in df.groupby("assigned_learner"):
            arr = np.nan_to_num(g[numeric_cols].to_numpy(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
            cnt = float(arr.shape[0])
            s = arr.sum(axis=0)
            ss = (arr * arr).sum(axis=0)
            mn = arr.min(axis=0)
            mx = arr.max(axis=0)
            if name not in states:
                states[name] = {"count": cnt, "sum": s, "sumsq": ss, "min": mn, "max": mx}
            else:
                st = states[name]
                st["count"] = float(st["count"]) + cnt
                st["sum"] = st["sum"] + s
                st["sumsq"] = st["sumsq"] + ss
                st["min"] = np.minimum(st["min"], mn)
                st["max"] = np.maximum(st["max"], mx)

    rows = []
    for learner_name, st in states.items():
        c = max(1.0, float(st["count"]))
        mean = st["sum"] / c
        var = np.maximum(st["sumsq"] / c - mean * mean, 0.0)
        std = np.sqrt(var)
        row = {"learner_name": learner_name, "sample_count": int(c)}
        for i, col in enumerate(numeric_cols):
            row[f"{col}__mean"] = float(mean[i])
            row[f"{col}__std"] = float(std[i])
            row[f"{col}__min"] = float(st["min"][i])
            row[f"{col}__max"] = float(st["max"][i])
        rows.append(row)
    return pd.DataFrame(rows)


def _build_label_df(learner_dist_csv: Path, attack_threshold: float) -> pd.DataFrame:
    ld = pd.read_csv(learner_dist_csv)
    needed = ["learner_name", "attack_ratio", "total_assigned_samples", "creation_sample_count", "dominant_ratio"]
    for c in needed:
        if c not in ld.columns:
            raise ValueError(f"Missing column {c} in {learner_dist_csv}")
    out = ld[needed].copy()
    out["learner_name"] = out["learner_name"].astype(str)
    out["is_attack_learner"] = (out["attack_ratio"].astype(float) >= attack_threshold).astype(int)
    out = out.rename(columns={"total_assigned_samples": "cluster_total_samples"})
    out = out.rename(columns={"creation_sample_count": "cluster_creation_samples"})
    out = out.rename(columns={"dominant_ratio": "cluster_dominant_ratio"})
    return out


def run_ga(
    df: pd.DataFrame,
    label_col: str,
    feature_cols: List[str],
    out_prefix: Path,
    seed: int,
    population_size: int,
    generations: int,
    elite_size: int,
    mutation_rate: float,
    crossover_rate: float,
    top_k: int,
) -> None:
    rng = random.Random(seed)
    x = df[feature_cols].to_numpy(np.float64)
    y = df[label_col].astype(int).to_numpy()
    x_train, x_test, y_train, y_test = train_test_split(
        x, y, test_size=0.30, random_state=seed, stratify=y
    )
    feat_map = {c: i for i, c in enumerate(feature_cols)}

    pop = [_random_tree(feature_cols, rng, depth=3) for _ in range(population_size)]
    score_cache: Dict[str, Tuple[float, float, float, float]] = {}
    archive: Dict[str, Dict[str, float | str]] = {}

    for _ in range(generations):
        scored = []
        for tree in pop:
            expr = _tree_to_str(tree)
            if expr in score_cache:
                auc_train, auc_abs_train, auc_test, auc_abs_test = score_cache[expr]
            else:
                raw_train = _eval_tree(tree, x_train, feat_map)
                raw_test = _eval_tree(tree, x_test, feat_map)
                auc_train = float(roc_auc_score(y_train, np.nan_to_num(raw_train, nan=0.0, posinf=1e6, neginf=-1e6)))
                auc_abs_train = _fit_auc(y_train, raw_train)
                auc_test = float(roc_auc_score(y_test, np.nan_to_num(raw_test, nan=0.0, posinf=1e6, neginf=-1e6)))
                auc_abs_test = _fit_auc(y_test, raw_test)
                score_cache[expr] = (auc_train, auc_abs_train, auc_test, auc_abs_test)
            scored.append((tree, auc_train, auc_abs_train, auc_test, auc_abs_test, expr))
            prev = archive.get(expr)
            if prev is None or auc_abs_test > float(prev["auc_abs_test"]):
                archive[expr] = {
                    "expr": expr,
                    "auc_train": auc_train,
                    "auc_abs_train": auc_abs_train,
                    "auc_test": auc_test,
                    "auc_abs_test": auc_abs_test,
                }
        scored.sort(key=lambda x_: x_[2], reverse=True)
        elites = [s[0] for s in scored[:elite_size]]
        parent_pool = [s[0] for s in scored[: max(2, population_size // 4)]]
        new_pop = elites[:]
        while len(new_pop) < population_size:
            p1 = rng.choice(parent_pool)
            child = _clone(p1)
            if rng.random() < crossover_rate:
                p2 = rng.choice(parent_pool)
                child = _crossover(child, p2, rng)
            if rng.random() < mutation_rate:
                child = _mutate(child, feature_cols, rng, max_depth=3)
            new_pop.append(child)
        pop = new_pop

    rank = (
        pd.DataFrame(list(archive.values()))
        .sort_values(["auc_abs_test", "auc_abs_train"], ascending=False)
        .head(top_k)
        .copy()
    )
    rank.insert(0, "rank", np.arange(1, len(rank) + 1))
    out_csv = out_prefix.with_suffix(".top_features.csv")
    out_json = out_prefix.with_suffix(".summary.json")
    rank.to_csv(out_csv, index=False)
    summary = {
        "rows": int(len(df)),
        "attack_learners": int((df[label_col] == 1).sum()),
        "benign_learners": int((df[label_col] == 0).sum()),
        "base_feature_count": int(len(feature_cols)),
        "population_size": int(population_size),
        "generations": int(generations),
        "elite_size": int(elite_size),
        "mutation_rate": float(mutation_rate),
        "crossover_rate": float(crossover_rate),
        "top_k": int(top_k),
        "output_top_features_csv": str(out_csv),
    }
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"top_features_csv={out_csv}")
    print(f"summary_json={out_json}")


def main() -> None:
    p = argparse.ArgumentParser(description="GA search for learner-level composite features.")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--source-csv", default="")
    p.add_argument("--out-prefix", required=True)
    p.add_argument("--attack-threshold", type=float, default=0.5)
    p.add_argument("--preview-rows", type=int, default=5000)
    p.add_argument("--chunksize", type=int, default=120000)
    p.add_argument("--drop-env-like", action="store_true")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--population-size", type=int, default=600)
    p.add_argument("--generations", type=int, default=24)
    p.add_argument("--elite-size", type=int, default=80)
    p.add_argument("--mutation-rate", type=float, default=0.40)
    p.add_argument("--crossover-rate", type=float, default=0.70)
    p.add_argument("--top-k", type=int, default=300)
    args = p.parse_args()

    run_dir = Path(args.run_dir).resolve()
    source_csv = Path(args.source_csv).resolve() if args.source_csv else _load_run_source_csv(run_dir)
    assignments_csv = run_dir / "sample_learner_assignments.csv"
    learner_dist_csv = run_dir / "learner_label_distribution.csv"
    if not assignments_csv.exists():
        raise FileNotFoundError(assignments_csv)
    if not learner_dist_csv.exists():
        raise FileNotFoundError(learner_dist_csv)

    numeric_cols = _discover_numeric_features(source_csv, preview_rows=args.preview_rows, drop_env_like=args.drop_env_like)
    if not numeric_cols:
        raise RuntimeError(f"No numeric columns discovered from {source_csv}")
    print(f"[INFO] discovered numeric columns: {len(numeric_cols)}")

    agg = _aggregate_numeric_by_learner(source_csv, assignments_csv, numeric_cols, chunksize=args.chunksize)
    label_df = _build_label_df(learner_dist_csv, attack_threshold=args.attack_threshold)
    all_df = agg.merge(label_df, on="learner_name", how="inner")
    feature_cols = [c for c in all_df.columns if c not in {"learner_name", "is_attack_learner", "attack_ratio"}]
    all_df[feature_cols] = all_df[feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    out_prefix = Path(args.out_prefix).resolve()
    out_prefix.parent.mkdir(parents=True, exist_ok=True)
    base_csv = out_prefix.with_suffix(".base_features.csv")
    all_df.to_csv(base_csv, index=False)
    print(f"[INFO] base features table: {base_csv}")

    run_ga(
        df=all_df,
        label_col="is_attack_learner",
        feature_cols=feature_cols,
        out_prefix=out_prefix,
        seed=args.seed,
        population_size=args.population_size,
        generations=args.generations,
        elite_size=args.elite_size,
        mutation_rate=args.mutation_rate,
        crossover_rate=args.crossover_rate,
        top_k=args.top_k,
    )


if __name__ == "__main__":
    main()
