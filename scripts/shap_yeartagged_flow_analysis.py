#!/usr/bin/env python3
"""SHAP attribution for yeartagged multi-year flow CSV (attack vs benign + per-label multiclass).

Reads ``data/aligned_*_yeartagged_for_main.csv``-style files in chunks, stratified-samples
rows per ``Label``, trains XGBoost models, and writes SHAP plots plus JSON summaries.

建模时默认 **排除**：IP、时间戳、``Label``、数据集元数据（``year_tag`` / ``original_label`` / ``benign_type``）、以及 **源/目的端口**。
可用 ``--extra-exclude-features`` 再排除其它列。

Examples::

  python scripts/shap_yeartagged_flow_analysis.py \\
    --csv data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv \\
    --out-dir artifacts/shap_yeartagged_flow
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import shap
import xgboost as xgb
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

DROP_COLS = {
    # 标识与时间
    "Src IP",
    "Dst IP",
    "Timestamp",
    # 标签与目标相关
    "Label",
    # 数据集环境 / 元数据（不参与流特征建模）
    "year_tag",
    "original_label",
    "benign_type",
    # 本次实验：除去端口，避免端口强记忆特定服务
    "Src Port",
    "Dst Port",
}


def is_benign_label(label: str) -> bool:
    parts = str(label).split("|")
    return len(parts) >= 2 and parts[1] == "BENIGN"


def stratified_sample(
    path: Path,
    label_col: str,
    max_per_class: int,
    max_total: int,
    seed: int,
    chunksize: int = 250_000,
) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    counts: Dict[str, int] = defaultdict(int)
    parts: List[pd.DataFrame] = []

    for chunk in pd.read_csv(path, chunksize=chunksize, low_memory=False):
        if label_col not in chunk.columns:
            raise KeyError(f"Missing label column {label_col!r} in {path}")
        for label, grp in chunk.groupby(label_col, sort=False):
            if counts[label] >= max_per_class:
                continue
            need = min(max_per_class - counts[label], len(grp))
            if need <= 0:
                continue
            samp = grp.sample(n=need, random_state=rng)
            parts.append(samp)
            counts[label] += need

    if not parts:
        raise RuntimeError("No rows sampled (empty file or zero caps?)")

    df = pd.concat(parts, ignore_index=True)
    if len(df) > max_total:
        frac = max_total / len(df)
        chunks = []
        for _, g in df.groupby(label_col, sort=False):
            chunks.append(g.sample(frac=frac, random_state=rng))
        df = pd.concat(chunks, ignore_index=True)
        if len(df) > max_total:
            df = df.sample(n=max_total, random_state=rng).reset_index(drop=True)
    vc = df[label_col].value_counts()
    keep = vc[vc >= 2].index
    if len(keep) < len(vc):
        df = df[df[label_col].isin(keep)].reset_index(drop=True)
    return df


def feature_matrix(df: pd.DataFrame, feature_cols: Sequence[str]) -> Tuple[np.ndarray, List[str]]:
    X = df.loc[:, list(feature_cols)].apply(pd.to_numeric, errors="coerce")
    X = X.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return X.to_numpy(dtype=np.float32), list(X.columns)


def train_binary(
    X: np.ndarray,
    y: np.ndarray,
    seed: int,
    *,
    n_estimators: int,
    max_depth: int,
) -> xgb.XGBClassifier:
    clf = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=0.08,
        objective="binary:logistic",
        tree_method="hist",
        random_state=seed,
        n_jobs=-1,
        eval_metric="logloss",
        subsample=0.85,
        colsample_bytree=0.85,
    )
    clf.fit(X, y)
    return clf


def train_multiclass(
    X: np.ndarray,
    y_enc: np.ndarray,
    num_class: int,
    seed: int,
    *,
    n_estimators: int,
    max_depth: int,
) -> xgb.XGBClassifier:
    clf = xgb.XGBClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        learning_rate=0.06,
        objective="multi:softprob",
        num_class=num_class,
        tree_method="hist",
        random_state=seed,
        n_jobs=-1,
        eval_metric="mlogloss",
        subsample=0.85,
        colsample_bytree=0.85,
    )
    clf.fit(X, y_enc)
    return clf


def make_tree_explainer(model: xgb.XGBClassifier, feature_names: List[str]) -> shap.TreeExplainer:
    """Path-dependent tree SHAP (no background set) — typically much faster than interventional."""
    return shap.TreeExplainer(
        model,
        data=None,
        feature_perturbation="tree_path_dependent",
        feature_names=feature_names,
    )


def explainer_shap_values_fast(explainer: shap.TreeExplainer, X: np.ndarray, *, approximate: bool) -> object:
    return explainer.shap_values(
        X,
        approximate=approximate,
        check_additivity=False,
    )


def binary_shap_matrix(sv_bin: object) -> np.ndarray:
    if isinstance(sv_bin, list):
        return np.asarray(sv_bin[1])
    return np.asarray(sv_bin)


def multiclass_shap_per_class(sv_mc: object, num_class: int) -> List[np.ndarray]:
    if isinstance(sv_mc, list):
        return sv_mc
    arr = np.asarray(sv_mc)
    if arr.ndim == 3:
        if arr.shape[-1] == num_class:
            return [arr[:, :, k] for k in range(num_class)]
        if arr.shape[0] == num_class:
            return [arr[k] for k in range(num_class)]
    raise RuntimeError(f"Unexpected multiclass SHAP shape {arr.shape}; expected list or (N,F,K) array")


def mean_abs_shap_by_class(
    shap_list: List[np.ndarray],
    y_enc: np.ndarray,
    feature_names: List[str],
    class_names: List[str],
    top_k: int = 20,
) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    n_classes = len(shap_list)
    for k in range(n_classes):
        sv = shap_list[k]
        mask = y_enc == k
        if not np.any(mask):
            continue
        contrib = np.abs(sv[mask]).mean(axis=0)
        order = np.argsort(-contrib)[:top_k]
        name = class_names[k]
        out[name] = {feature_names[i]: float(contrib[i]) for i in order}
    return out


def multiclass_global_importance(shap_list: List[np.ndarray], feature_names: List[str]) -> List[Tuple[str, float]]:
    stacked = np.mean([np.abs(sv) for sv in shap_list], axis=0).mean(axis=0)
    order = np.argsort(-stacked)
    return [(feature_names[i], float(stacked[i])) for i in order]


def plot_multiclass_heatmap(
    shap_list: List[np.ndarray],
    y_enc: np.ndarray,
    feature_names: List[str],
    class_names: List[str],
    max_classes: int,
    top_features: int,
    out_path: Path,
) -> None:
    mean_abs = np.mean([np.abs(sv) for sv in shap_list], axis=0)
    class_scores = []
    for k in range(len(class_names)):
        mask = y_enc == k
        if not np.any(mask):
            continue
        row = mean_abs[mask].mean(axis=0)
        class_scores.append((class_names[k], int(mask.sum()), row))
    class_scores.sort(key=lambda t: -t[1])
    class_scores = class_scores[:max_classes]
    if not class_scores:
        return
    global_imp = np.stack([r for _, _, r in class_scores], axis=0).mean(axis=0)
    feat_order = np.argsort(-global_imp)[:top_features]
    mat = np.stack([row[feat_order] for _, _, row in class_scores], axis=0)
    labels_y = [f"{c} (n={n})" for c, n, _ in class_scores]
    labels_x = [feature_names[i] for i in feat_order]

    fig_h = max(6.0, 0.35 * len(labels_y))
    fig_w = max(8.0, 0.22 * len(labels_x))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(mat, aspect="auto", cmap="magma")
    ax.set_xticks(range(len(labels_x)))
    ax.set_xticklabels(labels_x, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(len(labels_y)))
    ax.set_yticklabels(labels_y, fontsize=8)
    ax.set_title("Mean |SHAP| (multiclass): top flows by label prevalence in sample")
    fig.colorbar(im, ax=ax, shrink=0.6, label="mean |SHAP|")
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csv", type=Path, required=True, help="Input yeartagged CSV path")
    p.add_argument("--out-dir", type=Path, default=Path("artifacts/shap_yeartagged_flow"))
    p.add_argument("--label-col", type=str, default="Label")
    p.add_argument("--max-per-class", type=int, default=3000)
    p.add_argument("--max-total", type=int, default=70_000)
    p.add_argument(
        "--shap-background",
        type=int,
        default=0,
        help="Ignored: fast mode uses tree_path_dependent SHAP (no background dataset).",
    )
    p.add_argument("--shap-plot-samples", type=int, default=1200)
    p.add_argument(
        "--shap-approximate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use approximate tree SHAP in shap_values() (faster).",
    )
    p.add_argument("--bin-trees", type=int, default=220, help="Binary XGBoost n_estimators")
    p.add_argument("--bin-depth", type=int, default=8)
    p.add_argument("--mc-trees", type=int, default=220, help="Multiclass XGBoost n_estimators")
    p.add_argument("--mc-depth", type=int, default=8)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--heatmap-classes", type=int, default=22)
    p.add_argument("--heatmap-features", type=int, default=18)
    p.add_argument(
        "--extra-exclude-features",
        nargs="*",
        default=[],
        metavar="COL",
        help="Extra CSV column names to drop from X (exact header spelling).",
    )
    args = p.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("Sampling (chunked stratified)...", flush=True)
    df = stratified_sample(
        args.csv,
        args.label_col,
        max_per_class=args.max_per_class,
        max_total=args.max_total,
        seed=args.seed,
    )

    label_raw = df[args.label_col].astype(str)
    exclude = set(DROP_COLS) | set(args.extra_exclude_features)
    feature_cols = [c for c in df.columns if c not in exclude and c != args.label_col]
    X, feat_names = feature_matrix(df, feature_cols)
    y_multi = label_raw.to_numpy()
    le = LabelEncoder()
    y_enc = le.fit_transform(y_multi)
    class_names = le.classes_.tolist()
    y_bin = (~pd.Series(label_raw).map(is_benign_label)).to_numpy(dtype=np.int32)

    print(f"Sample rows={len(df):,} features={X.shape[1]} classes={len(class_names)}", flush=True)

    X_tr, X_te, yb_tr, yb_te, yenc_tr, yenc_te = train_test_split(
        X,
        y_bin,
        y_enc,
        test_size=0.22,
        random_state=args.seed,
        stratify=y_enc,
    )

    print("Train binary XGBoost...", flush=True)
    clf_bin = train_binary(
        X_tr, yb_tr, args.seed, n_estimators=args.bin_trees, max_depth=args.bin_depth
    )
    prob_te = clf_bin.predict_proba(X_te)[:, 1]
    auc = roc_auc_score(yb_te, prob_te)
    y_hat = (prob_te >= 0.5).astype(np.int32)
    bin_report = classification_report(yb_te, y_hat, digits=4)
    print(bin_report)
    (args.out_dir / "binary_metrics.txt").write_text(
        f"roc_auc={auc:.6f}\n\n{classification_report(yb_te, y_hat, digits=4)}", encoding="utf-8"
    )

    print("Train multiclass XGBoost...", flush=True)
    clf_mc = train_multiclass(
        X_tr,
        yenc_tr,
        len(class_names),
        args.seed,
        n_estimators=args.mc_trees,
        max_depth=args.mc_depth,
    )
    y_mc_hat = clf_mc.predict(X_te)
    mc_report = classification_report(
        yenc_te,
        y_mc_hat,
        digits=3,
        labels=list(range(len(class_names))),
        target_names=class_names,
        zero_division=0,
    )
    (args.out_dir / "multiclass_metrics.txt").write_text(mc_report, encoding="utf-8")

    rng = np.random.RandomState(args.seed)
    plot_n = min(args.shap_plot_samples, len(X_te))
    plot_idx = rng.choice(len(X_te), size=plot_n, replace=False)

    X_exp_bin = X_te[plot_idx]
    X_exp_mc = X_te[plot_idx]
    yenc_exp = yenc_te[plot_idx]

    print(
        "SHAP TreeExplainer (binary, tree_path_dependent + approximate="
        f"{args.shap_approximate})...",
        flush=True,
    )
    expl_bin = make_tree_explainer(clf_bin, feat_names)
    sv_bin = explainer_shap_values_fast(expl_bin, X_exp_bin, approximate=args.shap_approximate)
    sv_bin_arr = binary_shap_matrix(sv_bin)

    plt.figure(figsize=(10, 8))
    shap.summary_plot(sv_bin_arr, X_exp_bin, feature_names=feat_names, show=False, max_display=25)
    plt.tight_layout()
    plt.savefig(args.out_dir / "binary_shap_summary_beeswarm.png", dpi=170, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(9, 6))
    shap.summary_plot(
        sv_bin_arr,
        X_exp_bin,
        feature_names=feat_names,
        plot_type="bar",
        show=False,
        max_display=25,
    )
    plt.tight_layout()
    plt.savefig(args.out_dir / "binary_shap_bar.png", dpi=170, bbox_inches="tight")
    plt.close()

    mean_abs_bin = np.abs(sv_bin_arr).mean(axis=0)
    bin_order = np.argsort(-mean_abs_bin)
    bin_top = {feat_names[i]: float(mean_abs_bin[i]) for i in bin_order[:30]}

    print(
        "SHAP TreeExplainer (multiclass, tree_path_dependent + approximate="
        f"{args.shap_approximate})...",
        flush=True,
    )
    expl_mc = make_tree_explainer(clf_mc, feat_names)
    sv_mc_raw = explainer_shap_values_fast(expl_mc, X_exp_mc, approximate=args.shap_approximate)
    sv_mc = multiclass_shap_per_class(sv_mc_raw, len(class_names))

    plot_multiclass_heatmap(
        sv_mc,
        yenc_exp,
        feat_names,
        class_names,
        max_classes=args.heatmap_classes,
        top_features=args.heatmap_features,
        out_path=args.out_dir / "multiclass_shap_heatmap_top_classes.png",
    )

    per_class_top = mean_abs_shap_by_class(sv_mc, yenc_exp, feat_names, class_names, top_k=18)
    global_imp = multiclass_global_importance(sv_mc, feat_names)

    meta = {
        "csv": str(args.csv.resolve()),
        "sample_rows": int(len(df)),
        "features": feat_names,
        "excluded_from_X": sorted(exclude),
        "class_count": len(class_names),
        "shap_mode": {
            "feature_perturbation": "tree_path_dependent",
            "background_samples": 0,
            "shap_values_approximate": bool(args.shap_approximate),
            "explain_rows": int(plot_n),
        },
        "binary_roc_auc": float(auc),
        "binary_top_mean_abs_shap": bin_top,
        "multiclass_global_mean_abs_shap": [{"feature": f, "score": s} for f, s in global_imp[:40]],
        "multiclass_per_class_top_mean_abs_shap_on_class_samples": per_class_top,
    }
    (args.out_dir / "shap_summary.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Wrote artifacts to {args.out_dir.resolve()}", flush=True)


if __name__ == "__main__":
    main()
