#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import auc, roc_curve
from sklearn.preprocessing import StandardScaler

from trident_stream.utils import is_benign_label, normalize_label, split_year_label


def preprocess_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
    drop_cols = [
        "id",
        "Flow ID",
        "Src IP",
        "Dst IP",
        "Timestamp",
        "Label",
        "Attempted Category",
    ]
    feat_df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    numeric_cols = feat_df.select_dtypes(include=[np.number]).columns.tolist()
    feat_df = feat_df[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return feat_df, numeric_cols


def ecdf(x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    xs = np.sort(x)
    ys = np.arange(1, len(xs) + 1) / float(len(xs))
    return xs, ys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare test compositions: benign-only / balanced / attack-only.",
    )
    parser.add_argument("--data-csv", default="data/aligned_2017_2019_sampled_year_tagged.csv")
    parser.add_argument("--train-benign", type=int, default=50000)
    parser.add_argument("--benign-n", type=int, default=10000, help="Test benign sample count.")
    parser.add_argument("--attack-n", type=int, default=10000, help="Test attack sample count.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out-png",
        default="outputs/analysis/test_composition_comparison.png",
    )
    parser.add_argument(
        "--out-json",
        default="outputs/analysis/test_composition_comparison_metrics.json",
    )
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    data = pd.read_csv(args.data_csv, low_memory=False)
    if "Label" not in data.columns:
        raise ValueError("Input CSV must contain Label column.")
    data["LabelNorm"] = data["Label"].map(normalize_label)
    data["Year"] = data["LabelNorm"].map(lambda x: split_year_label(str(x))[0])
    data["IsBenign"] = data["LabelNorm"].map(is_benign_label)

    train_pool = data[(data["Year"] == "2017") & (data["IsBenign"])]
    benign_pool = data[(data["Year"] == "2019") & (data["IsBenign"])]
    attack_pool = data[(data["Year"] == "2019") & (~data["IsBenign"])]

    if len(train_pool) < args.train_benign:
        raise ValueError(f"Not enough 2017 benign rows: need {args.train_benign}, got {len(train_pool)}")
    if len(benign_pool) < args.benign_n:
        raise ValueError(f"Not enough 2019 benign rows: need {args.benign_n}, got {len(benign_pool)}")
    if len(attack_pool) < args.attack_n:
        raise ValueError(f"Not enough 2019 attack rows: need {args.attack_n}, got {len(attack_pool)}")

    train_idx = rng.choice(train_pool.index.values, size=args.train_benign, replace=False)
    benign_idx = rng.choice(benign_pool.index.values, size=args.benign_n, replace=False)
    attack_idx = rng.choice(attack_pool.index.values, size=args.attack_n, replace=False)

    train_df = data.loc[train_idx]
    benign_df = data.loc[benign_idx]
    attack_df = data.loc[attack_idx]
    mixed_df = pd.concat([benign_df, attack_df], axis=0).copy()
    mixed_y = np.concatenate([np.zeros(len(benign_df), dtype=np.int32), np.ones(len(attack_df), dtype=np.int32)])

    train_x_df, feature_cols = preprocess_features(train_df)
    benign_x_df, _ = preprocess_features(benign_df)
    attack_x_df, _ = preprocess_features(attack_df)
    mixed_x_df, _ = preprocess_features(mixed_df)
    benign_x_df = benign_x_df.reindex(columns=feature_cols, fill_value=0.0)
    attack_x_df = attack_x_df.reindex(columns=feature_cols, fill_value=0.0)
    mixed_x_df = mixed_x_df.reindex(columns=feature_cols, fill_value=0.0)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(train_x_df.values.astype(np.float32))
    x_benign = scaler.transform(benign_x_df.values.astype(np.float32))
    x_attack = scaler.transform(attack_x_df.values.astype(np.float32))
    x_mixed = scaler.transform(mixed_x_df.values.astype(np.float32))

    clf = IsolationForest(
        n_estimators=300,
        contamination="auto",
        random_state=args.seed,
        n_jobs=-1,
    )
    clf.fit(x_train)

    score_benign = -clf.decision_function(x_benign)
    score_attack = -clf.decision_function(x_attack)
    score_mixed = -clf.decision_function(x_mixed)

    fpr_mixed, tpr_mixed, _ = roc_curve(mixed_y, score_mixed)
    auc_mixed = float(auc(fpr_mixed, tpr_mixed))

    # Plot: 3 panels for requested compositions
    out_png = Path(args.out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.8))

    # Benign-only (ROC undefined): show ECDF
    xb, yb = ecdf(score_benign)
    axes[0].plot(xb, yb, linewidth=2.0, color="#1f77b4")
    axes[0].set_title("Test: Benign Only (ROC undefined)")
    axes[0].set_xlabel("Anomaly Score")
    axes[0].set_ylabel("ECDF")
    axes[0].grid(alpha=0.3)

    # Mixed: true ROC
    axes[1].plot(fpr_mixed, tpr_mixed, linewidth=2.0, label=f"AUC={auc_mixed:.4f}", color="#ff7f0e")
    axes[1].plot([0, 1], [0, 1], "--", color="gray", linewidth=1.0)
    axes[1].set_title("Test: 50% Benign + 50% Attack")
    axes[1].set_xlabel("False Positive Rate")
    axes[1].set_ylabel("True Positive Rate")
    axes[1].legend(loc="lower right")
    axes[1].grid(alpha=0.3)

    # Attack-only (ROC undefined): show ECDF
    xa, ya = ecdf(score_attack)
    axes[2].plot(xa, ya, linewidth=2.0, color="#d62728")
    axes[2].set_title("Test: Attack Only (ROC undefined)")
    axes[2].set_xlabel("Anomaly Score")
    axes[2].set_ylabel("ECDF")
    axes[2].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_png, dpi=180)
    plt.close(fig)

    metrics = {
        "data_csv": str(args.data_csv),
        "train_benign_2017": int(args.train_benign),
        "test_benign_only_n": int(args.benign_n),
        "test_attack_only_n": int(args.attack_n),
        "test_mixed_benign_n": int(args.benign_n),
        "test_mixed_attack_n": int(args.attack_n),
        "feature_dim": int(len(feature_cols)),
        "roc_auc_mixed_only": auc_mixed,
        "benign_only_score_mean": float(np.mean(score_benign)),
        "attack_only_score_mean": float(np.mean(score_attack)),
        "benign_only_score_p90": float(np.quantile(score_benign, 0.9)),
        "attack_only_score_p90": float(np.quantile(score_attack, 0.9)),
        "note": "ROC is undefined for single-class test sets; ECDF shown instead.",
        "figure": str(out_png),
    }
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved figure: {out_png}")
    print(f"Saved metrics: {out_json}")
    print(f"Mixed ROC AUC: {auc_mixed:.6f}")
    print("Benign-only / Attack-only: ROC undefined, ECDF used.")


if __name__ == "__main__":
    main()
