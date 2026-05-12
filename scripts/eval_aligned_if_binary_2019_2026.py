#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


def evaluate_year(
    clf: IsolationForest,
    scaler: StandardScaler,
    year_df: pd.DataFrame,
    feature_cols: List[str],
) -> Dict[str, float]:
    x_df, _ = preprocess_features(year_df)
    x_df = x_df.reindex(columns=feature_cols, fill_value=0.0)
    x = scaler.transform(x_df.values.astype(np.float32))
    y_true_attack = (~year_df["IsBenign"]).astype(int).values

    # decision_function: larger => more normal. convert to anomaly score.
    anomaly_score = -clf.decision_function(x)
    # sklearn默认阈值: decision_function < 0 => anomaly
    y_pred_attack = (clf.predict(x) == -1).astype(int)

    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true_attack,
        y_pred_attack,
        average="binary",
        zero_division=0,
    )
    acc = accuracy_score(y_true_attack, y_pred_attack)
    benign_accept_rate = float((y_pred_attack == 0).mean())

    out: Dict[str, float] = {
        "rows": float(len(year_df)),
        "attack_rows": float(int(y_true_attack.sum())),
        "benign_rows": float(int((1 - y_true_attack).sum())),
        "threshold_decision_fn": 0.0,
        "mean_anomaly_score": float(np.mean(anomaly_score)),
        "p95_anomaly_score": float(np.quantile(anomaly_score, 0.95)),
        "accuracy": float(acc),
        "precision_attack": float(precision),
        "recall_attack": float(recall),
        "f1_attack": float(f1),
        "benign_accept_rate": benign_accept_rate,
    }
    if len(np.unique(y_true_attack)) == 2:
        out["roc_auc_attack"] = float(roc_auc_score(y_true_attack, anomaly_score))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train IsolationForest on aligned benign data and evaluate binary performance on 2019/2026.",
    )
    parser.add_argument(
        "--data-csv",
        default="data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv",
        help="Aligned input csv.",
    )
    parser.add_argument("--train-year", default="2017", help="Benign train year tag (default: 2017).")
    parser.add_argument("--train-max-rows", type=int, default=20000, help="Max benign train rows.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument(
        "--metrics-json",
        default="outputs/analysis/if_binary_eval_2019_2026.json",
        help="Output metrics path.",
    )
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    data = pd.read_csv(args.data_csv, low_memory=False)
    if "Label" not in data.columns:
        raise ValueError("Input CSV must contain Label column.")

    data["LabelNorm"] = data["Label"].map(normalize_label)
    data["Year"] = data["LabelNorm"].map(lambda x: split_year_label(str(x))[0] or "0000")
    data["IsBenign"] = data["LabelNorm"].map(is_benign_label)

    train_pool = data[(data["Year"] == str(args.train_year)) & (data["IsBenign"])].copy()
    if len(train_pool) == 0:
        raise ValueError(
            f"No benign samples found for train-year={args.train_year}. "
            "Check year tag (e.g. 2017) and input csv."
        )

    if args.train_max_rows > 0 and len(train_pool) > args.train_max_rows:
        pick = rng.choice(train_pool.index.values, size=args.train_max_rows, replace=False)
        train_df = train_pool.loc[pick].copy()
    else:
        train_df = train_pool.copy()

    train_x_df, feature_cols = preprocess_features(train_df)
    x_train = train_x_df.values.astype(np.float32)
    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train)

    clf = IsolationForest(
        n_estimators=args.n_estimators,
        contamination="auto",
        random_state=args.seed,
        n_jobs=-1,
    )
    clf.fit(x_train_scaled)

    metrics: Dict[str, object] = {
        "data_csv": str(args.data_csv),
        "train_year": str(args.train_year),
        "train_rows_used": int(len(train_df)),
        "feature_dim": int(len(feature_cols)),
        "model": "IsolationForest",
        "n_estimators": int(args.n_estimators),
        "eval": {},
    }

    for year in ["2019", "2026"]:
        year_df = data[data["Year"] == year].copy()
        if len(year_df) == 0:
            metrics["eval"][year] = {"rows": 0, "note": "no rows for this year"}  # type: ignore[index]
            continue
        metrics["eval"][year] = evaluate_year(clf, scaler, year_df, feature_cols)  # type: ignore[index]

    out_path = Path(args.metrics_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved metrics: {out_path}")


if __name__ == "__main__":
    main()
