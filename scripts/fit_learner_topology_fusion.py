#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


DEFAULT_FEATURES = [
    "in_deg_entropy",
    "out_deg_gini",
    "dst_endpoint_ratio",
    "max_out_strength",
    "edge_w_entropy",
]


def _eval_at_threshold(y_true: np.ndarray, score: np.ndarray, thr: float) -> dict:
    y_pred = (score >= thr).astype(np.int32)
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    fpr = fp / max(1, fp + tn)
    fnr = fn / max(1, tp + fn)
    tpr = tp / max(1, tp + fn)
    precision = tp / max(1, tp + fp)
    return {
        "threshold": float(thr),
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
    parser = argparse.ArgumentParser(description="Fit learner-level topology fusion score.")
    parser.add_argument("--per-learner-csv", required=True)
    parser.add_argument("--out-prefix", required=True)
    parser.add_argument("--label-col", default="is_attack_learner")
    parser.add_argument("--feature-cols", default=",".join(DEFAULT_FEATURES))
    parser.add_argument("--cv-folds", type=int, default=5)
    args = parser.parse_args()

    in_csv = Path(args.per_learner_csv)
    out_prefix = Path(args.out_prefix)
    out_prefix.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(in_csv)
    feature_cols: List[str] = [x.strip() for x in str(args.feature_cols).split(",") if x.strip()]
    missing = [c for c in feature_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing feature columns: {missing}")
    if args.label_col not in df.columns:
        raise ValueError(f"Missing label column: {args.label_col}")

    x = df[feature_cols].to_numpy(np.float64)
    y = df[args.label_col].astype(np.int32).to_numpy()
    if len(np.unique(y)) < 2:
        raise RuntimeError("Need both benign and attack learners.")

    pos = int((y == 1).sum())
    neg = int((y == 0).sum())
    folds = int(max(2, min(args.cv_folds, pos, neg)))

    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("lr", LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)),
        ]
    )
    cv = StratifiedKFold(n_splits=folds, shuffle=True, random_state=42)
    score_cv = cross_val_predict(model, x, y, cv=cv, method="predict_proba")[:, 1]
    auc_cv = float(roc_auc_score(y, score_cv))

    model.fit(x, y)
    score_fit = model.predict_proba(x)[:, 1]
    auc_fit = float(roc_auc_score(y, score_fit))
    fpr_arr, tpr_arr, thr_arr = roc_curve(y, score_cv)

    threshold_rows = []
    for target_fpr in [0.01, 0.02, 0.05, 0.10, 0.20]:
        idx = int(np.argmin(np.abs(fpr_arr - target_fpr)))
        thr = float(thr_arr[idx])
        row = _eval_at_threshold(y, score_cv, thr)
        row["target_fpr"] = float(target_fpr)
        threshold_rows.append(row)

    # best Youden on CV scores
    best_idx = int(np.argmax(tpr_arr - fpr_arr))
    best_thr = float(thr_arr[best_idx])
    best_row = _eval_at_threshold(y, score_cv, best_thr)
    best_row["target_fpr"] = float("nan")
    best_row["note"] = "best_youden"
    threshold_rows.append(best_row)

    score_df = df.copy()
    score_df["fusion_score_cv"] = score_cv
    score_df["fusion_score_fit"] = score_fit
    score_df = score_df.sort_values(by="fusion_score_cv", ascending=False)

    thr_df = pd.DataFrame(threshold_rows)
    coef = model.named_steps["lr"].coef_[0]
    coef_df = pd.DataFrame({"feature": feature_cols, "coef": coef}).sort_values(by="coef", ascending=False)

    score_csv = out_prefix.with_suffix(".scores.csv")
    thr_csv = out_prefix.with_suffix(".thresholds.csv")
    coef_csv = out_prefix.with_suffix(".coefs.csv")
    summary_json = out_prefix.with_suffix(".json")
    report_md = out_prefix.with_suffix(".md")

    score_df.to_csv(score_csv, index=False)
    thr_df.to_csv(thr_csv, index=False)
    coef_df.to_csv(coef_csv, index=False)

    summary = {
        "input_csv": str(in_csv),
        "samples": int(len(df)),
        "attack_learners": int(pos),
        "benign_learners": int(neg),
        "feature_cols": feature_cols,
        "cv_folds": int(folds),
        "auc_cv": auc_cv,
        "auc_fit": auc_fit,
        "outputs": {
            "scores_csv": str(score_csv),
            "thresholds_csv": str(thr_csv),
            "coefs_csv": str(coef_csv),
        },
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    with report_md.open("w", encoding="utf-8") as f:
        f.write("# Learner Topology Fusion Score Report\n\n")
        f.write(f"- input: `{in_csv}`\n")
        f.write(f"- samples: {len(df)} (attack={pos}, benign={neg})\n")
        f.write(f"- features: {', '.join(feature_cols)}\n")
        f.write(f"- CV folds: {folds}\n")
        f.write(f"- AUC(CV): **{auc_cv:.4f}**\n")
        f.write(f"- AUC(Fit): {auc_fit:.4f}\n\n")
        f.write("## Threshold Table (based on CV scores)\n\n")
        f.write("| TargetFPR | Threshold | FPR | FNR | TPR | Precision |\n")
        f.write("|---:|---:|---:|---:|---:|---:|\n")
        for r in threshold_rows:
            tf = r.get("target_fpr")
            tf_text = "-" if tf is None or (isinstance(tf, float) and np.isnan(tf)) else f"{float(tf):.2%}"
            f.write(
                f"| {tf_text} | {float(r['threshold']):.6f} | {float(r['fpr']):.2%} | {float(r['fnr']):.2%} | {float(r['tpr']):.2%} | {float(r['precision']):.2%} |\n"
            )

    print(f"scores_csv={score_csv}")
    print(f"thresholds_csv={thr_csv}")
    print(f"coefs_csv={coef_csv}")
    print(f"summary_json={summary_json}")
    print(f"report_md={report_md}")


if __name__ == "__main__":
    main()

