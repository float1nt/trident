#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split


def preprocess_features(df: pd.DataFrame, extra_drop_cols: List[str] | None = None) -> Tuple[pd.DataFrame, List[str]]:
    drop_cols = [
        "id",
        "Flow ID",
        "Src IP",
        "Src Port",
        "Dst IP",
        "Dst Port",
        "Timestamp",
        "Label",
        "Attempted Category",
    ]
    if extra_drop_cols:
        drop_cols.extend(extra_drop_cols)
    drop_cols = sorted(set(drop_cols))
    feat_df = df.drop(columns=[c for c in drop_cols if c in df.columns])
    numeric_cols = feat_df.select_dtypes(include=[np.number]).columns.tolist()
    feat_df = feat_df[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return feat_df, numeric_cols


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train one-vs-rest RandomForest for each learner and export feature importances.",
    )
    parser.add_argument("--data-csv", required=True, help="Path to sampled data csv.")
    parser.add_argument("--assignments-csv", required=True, help="Path to sample_learner_assignments.csv.")
    parser.add_argument(
        "--output-json",
        default="outputs/rf_learner_explainability.json",
        help="Output json path.",
    )
    parser.add_argument("--min-positive-samples", type=int, default=200, help="Minimum positives per learner.")
    parser.add_argument("--top-k", type=int, default=15, help="Top K features to keep per learner.")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test size ratio.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--n-estimators", type=int, default=400, help="RandomForest n_estimators.")
    parser.add_argument(
        "--extra-drop-cols",
        default="",
        help="Comma-separated additional sensitive columns to drop before RF training.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data_csv = Path(args.data_csv)
    assignments_csv = Path(args.assignments_csv)
    output_json = Path(args.output_json)

    data = pd.read_csv(data_csv, low_memory=False)
    extra_drop_cols = [c.strip() for c in str(args.extra_drop_cols).split(",") if c.strip()]
    feat_df, feature_cols = preprocess_features(data, extra_drop_cols=extra_drop_cols)

    assignments = pd.read_csv(assignments_csv, low_memory=False)
    if "row_index" not in assignments.columns or "assigned_learner" not in assignments.columns:
        raise ValueError("assignments csv must contain row_index and assigned_learner columns")
    assignments = assignments.dropna(subset=["row_index", "assigned_learner"]).copy()
    assignments["row_index"] = assignments["row_index"].astype(int)
    assignments = assignments[
        (assignments["row_index"] >= 0) & (assignments["row_index"] < len(feat_df))
    ].reset_index(drop=True)
    if assignments.empty:
        raise ValueError("No valid assignment rows after filtering by row_index")

    X_all = feat_df.iloc[assignments["row_index"].values].values.astype(np.float32)
    learner_series = assignments["assigned_learner"].astype(str)
    learner_counts = learner_series.value_counts().to_dict()

    learners = sorted([k for k in learner_counts.keys() if k != "UNKNOWN"])
    results: List[Dict] = []
    skipped: List[Dict] = []

    for learner in learners:
        y = (learner_series == learner).astype(int).values
        pos = int(y.sum())
        neg = int(len(y) - pos)
        if pos < args.min_positive_samples or neg < args.min_positive_samples:
            skipped.append(
                {
                    "learner_name": learner,
                    "reason": "insufficient_samples",
                    "positive_samples": pos,
                    "negative_samples": neg,
                }
            )
            continue

        X_train, X_test, y_train, y_test = train_test_split(
            X_all,
            y,
            test_size=args.test_size,
            random_state=args.seed,
            stratify=y,
        )
        clf = RandomForestClassifier(
            n_estimators=args.n_estimators,
            random_state=args.seed,
            n_jobs=-1,
            class_weight="balanced_subsample",
        )
        clf.fit(X_train, y_train)
        y_score = clf.predict_proba(X_test)[:, 1]
        auc = float(roc_auc_score(y_test, y_score))

        importances = clf.feature_importances_
        top_idx = np.argsort(importances)[::-1][: args.top_k]
        top_features = [
            {"feature": str(feature_cols[i]), "importance": float(importances[i])}
            for i in top_idx
        ]
        results.append(
            {
                "learner_name": learner,
                "positive_samples": pos,
                "negative_samples": neg,
                "auc": auc,
                "top_features": top_features,
            }
        )

    output = {
        "data_csv": str(data_csv),
        "assignments_csv": str(assignments_csv),
        "feature_count": len(feature_cols),
        "assignment_count": int(len(assignments)),
        "learners_total": int(len(learners)),
        "learners_explained": int(len(results)),
        "learners_skipped": int(len(skipped)),
        "params": {
            "min_positive_samples": int(args.min_positive_samples),
            "top_k": int(args.top_k),
            "test_size": float(args.test_size),
            "seed": int(args.seed),
            "n_estimators": int(args.n_estimators),
            "extra_drop_cols": extra_drop_cols,
        },
        "results": sorted(results, key=lambda x: x["auc"], reverse=True),
        "skipped": skipped,
    }

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {output_json}")
    print(f"Explained learners: {len(results)} | Skipped: {len(skipped)}")


if __name__ == "__main__":
    main()
