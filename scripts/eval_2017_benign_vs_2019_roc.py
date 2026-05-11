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


def is_year_label(label: str, year: str) -> bool:
    y, _ = split_year_label(label)
    return y == year


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train on 2017 benign only, test on 2019 benign+attack and plot ROC.",
    )
    parser.add_argument(
        "--data-csv",
        default="data/aligned_2017_2019_sampled_year_tagged.csv",
        help="Input csv path.",
    )
    parser.add_argument("--train-benign", type=int, default=10000, help="Train size: 2017 benign.")
    parser.add_argument("--test-benign", type=int, default=5000, help="Test size: 2019 benign.")
    parser.add_argument("--test-attack", type=int, default=5000, help="Test size: 2019 attack.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument(
        "--roc-png",
        default="outputs/analysis/roc_2017benign_vs_2019_mix.png",
        help="Output ROC figure path.",
    )
    parser.add_argument(
        "--metrics-json",
        default="outputs/analysis/roc_2017benign_vs_2019_metrics.json",
        help="Output metrics json path.",
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
    test_benign_pool = data[(data["Year"] == "2019") & (data["IsBenign"])]
    test_attack_pool = data[(data["Year"] == "2019") & (~data["IsBenign"])]

    if len(train_pool) < args.train_benign:
        raise ValueError(f"Not enough 2017 benign rows: need {args.train_benign}, got {len(train_pool)}")
    if len(test_benign_pool) < args.test_benign:
        raise ValueError(f"Not enough 2019 benign rows: need {args.test_benign}, got {len(test_benign_pool)}")
    if len(test_attack_pool) < args.test_attack:
        raise ValueError(f"Not enough 2019 attack rows: need {args.test_attack}, got {len(test_attack_pool)}")

    train_idx = rng.choice(train_pool.index.values, size=args.train_benign, replace=False)
    benign_idx = rng.choice(test_benign_pool.index.values, size=args.test_benign, replace=False)
    attack_idx = rng.choice(test_attack_pool.index.values, size=args.test_attack, replace=False)

    train_df = data.loc[train_idx].copy()
    test_df = pd.concat([data.loc[benign_idx], data.loc[attack_idx]], axis=0).copy()
    test_y = np.concatenate(
        [
            np.zeros(args.test_benign, dtype=np.int32),  # benign -> negative class
            np.ones(args.test_attack, dtype=np.int32),   # attack -> positive class
        ]
    )

    train_x_df, feature_cols = preprocess_features(train_df)
    test_x_df, _ = preprocess_features(test_df)
    test_x_df = test_x_df.reindex(columns=feature_cols, fill_value=0.0)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(train_x_df.values.astype(np.float32))
    x_test = scaler.transform(test_x_df.values.astype(np.float32))

    # One-class training on benign only.
    clf = IsolationForest(
        n_estimators=300,
        contamination="auto",
        random_state=args.seed,
        n_jobs=-1,
    )
    clf.fit(x_train)

    # decision_function: higher means more normal, so invert for anomaly score.
    anomaly_score = -clf.decision_function(x_test)
    fpr, tpr, _ = roc_curve(test_y, anomaly_score)
    roc_auc = float(auc(fpr, tpr))

    roc_png = Path(args.roc_png)
    roc_png.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(7, 6))
    plt.plot(fpr, tpr, linewidth=2.0, label=f"IsolationForest (AUC={roc_auc:.4f})")
    plt.plot([0, 1], [0, 1], "--", linewidth=1.2, color="gray", label="Random")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("ROC: Train 2017 BENIGN(10k), Test 2019 BENIGN(5k)+ATTACK(5k)")
    plt.grid(alpha=0.3)
    plt.legend(loc="lower right")
    plt.tight_layout()
    plt.savefig(roc_png, dpi=180)
    plt.close()

    metrics = {
        "data_csv": str(args.data_csv),
        "train_benign_2017": int(args.train_benign),
        "test_benign_2019": int(args.test_benign),
        "test_attack_2019": int(args.test_attack),
        "feature_dim": int(len(feature_cols)),
        "roc_auc": roc_auc,
        "roc_png": str(roc_png),
    }

    metrics_json = Path(args.metrics_json)
    metrics_json.parent.mkdir(parents=True, exist_ok=True)
    metrics_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved ROC: {roc_png}")
    print(f"Saved metrics: {metrics_json}")
    print(f"AUC: {roc_auc:.6f}")


if __name__ == "__main__":
    main()
