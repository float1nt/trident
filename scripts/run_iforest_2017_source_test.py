#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import auc, precision_recall_curve, roc_curve
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


FILES_2017 = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]
ENV_FEATURES = {"id", "Flow ID", "Src IP", "Dst IP", "Src Port", "Dst Port", "Timestamp"}


def _norm_label(v: object) -> str:
    return str(v).strip().upper()


def _sample_df(df: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    if n <= 0 or len(df) <= n:
        return df
    idx = rng.choice(len(df), size=n, replace=False)
    return df.iloc[idx]


def load_2017_frames(data_dir: Path) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for name in FILES_2017:
        p = data_dir / name
        if not p.exists():
            raise FileNotFoundError(f"Missing source file: {p}")
        df = pd.read_csv(p, low_memory=False)
        if "Label" not in df.columns:
            raise ValueError(f"`Label` column not found in {p}")
        df["Label"] = df["Label"].map(_norm_label)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def build_features(train_df: pd.DataFrame, test_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    all_df = pd.concat([train_df, test_df], axis=0, ignore_index=True)
    numeric_cols = [c for c in all_df.columns if c != "Label" and pd.api.types.is_numeric_dtype(all_df[c])]
    if not numeric_cols:
        raise ValueError("No numeric feature columns found.")

    x_train = train_df[numeric_cols].replace([np.inf, -np.inf], np.nan)
    x_test = test_df[numeric_cols].replace([np.inf, -np.inf], np.nan)

    med = x_train.median(numeric_only=True)
    x_train = x_train.fillna(med).fillna(0.0)
    x_test = x_test.fillna(med).fillna(0.0)
    return x_train, x_test, numeric_cols


def evaluate(
    y_true: np.ndarray,
    scores_attack_higher: np.ndarray,
    benign_scores: np.ndarray,
    target_fprs: List[float],
) -> Dict[str, object]:
    fpr, tpr, thresholds = roc_curve(y_true, scores_attack_higher)
    roc_auc = float(auc(fpr, tpr))

    precision, recall, pr_thr = precision_recall_curve(y_true, scores_attack_higher)
    f1 = (2.0 * precision * recall) / np.clip(precision + recall, 1e-12, None)
    best_idx = int(np.nanargmax(f1))
    best_thr = float(pr_thr[max(0, best_idx - 1)]) if len(pr_thr) > 0 else float(np.median(scores_attack_higher))

    threshold_metrics: Dict[str, Dict[str, float]] = {}
    for fpr_target in target_fprs:
        thr = float(np.quantile(benign_scores, 1.0 - fpr_target))
        y_pred_attack = (scores_attack_higher >= thr).astype(np.int32)

        fp = int(((y_pred_attack == 1) & (y_true == 0)).sum())
        tn = int(((y_pred_attack == 0) & (y_true == 0)).sum())
        tp = int(((y_pred_attack == 1) & (y_true == 1)).sum())
        fn = int(((y_pred_attack == 0) & (y_true == 1)).sum())

        fpr_val = fp / max(1, fp + tn)
        tpr_val = tp / max(1, tp + fn)
        fnr_val = fn / max(1, tp + fn)
        precision_val = tp / max(1, tp + fp)
        threshold_metrics[f"fpr_target_{fpr_target:.3f}"] = {
            "threshold": thr,
            "fpr": float(fpr_val),
            "tpr": float(tpr_val),
            "fnr": float(fnr_val),
            "precision": float(precision_val),
        }

    return {
        "roc_auc": roc_auc,
        "best_f1_threshold": best_thr,
        "best_f1": float(np.nanmax(f1)),
        "threshold_metrics": threshold_metrics,
        "roc_curve_points": {
            "fpr": fpr.tolist(),
            "tpr": tpr.tolist(),
            "thresholds": thresholds.tolist(),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a quick IForest test on raw CICIDS2017 source files.")
    parser.add_argument("--data-dir", default="/home/data/2017")
    parser.add_argument("--train-benign-max", type=int, default=200000)
    parser.add_argument("--test-benign-max", type=int, default=120000)
    parser.add_argument("--test-attack-max", type=int, default=120000)
    parser.add_argument("--n-estimators", type=int, default=300)
    parser.add_argument("--max-samples", default="auto")
    parser.add_argument("--contamination", default="auto")
    parser.add_argument(
        "--pca-components",
        type=int,
        default=0,
        help="Set >0 to apply PCA to this many components before fitting/eval.",
    )
    parser.add_argument(
        "--keep-id-feature",
        action="store_true",
        help="Keep `id` as numeric feature (default: dropped).",
    )
    parser.add_argument(
        "--keep-env-features",
        action="store_true",
        help="Keep environment-like features such as Timestamp/IP/Port (default: dropped).",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out-json",
        default="outputs/analysis/iforest_2017_source_test_metrics.json",
    )
    parser.add_argument(
        "--fpr-start",
        type=int,
        default=1,
        help="Start FPR percent for threshold metrics (inclusive).",
    )
    parser.add_argument(
        "--fpr-end",
        type=int,
        default=10,
        help="End FPR percent for threshold metrics (inclusive).",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    print("[1/4] Loading /home/data/2017 source files ...", flush=True)
    df = load_2017_frames(data_dir)
    y_attack_all = (df["Label"] != "BENIGN").astype(np.int32).to_numpy()
    total_rows = int(len(df))
    total_attack = int(y_attack_all.sum())
    total_benign = int(total_rows - total_attack)
    print(f"      total_rows={total_rows} benign={total_benign} attack={total_attack}", flush=True)

    benign_df = df.loc[df["Label"] == "BENIGN"].copy()
    attack_df = df.loc[df["Label"] != "BENIGN"].copy()

    benign_train = _sample_df(benign_df, args.train_benign_max, rng=rng)
    benign_test_pool = benign_df.drop(index=benign_train.index)
    benign_test = _sample_df(benign_test_pool, args.test_benign_max, rng=rng)
    attack_test = _sample_df(attack_df, args.test_attack_max, rng=rng)
    test_df = pd.concat([benign_test, attack_test], ignore_index=True)
    y_test = (test_df["Label"] != "BENIGN").astype(np.int32).to_numpy()

    print(
        "[2/4] Dataset split: "
        f"train_benign={len(benign_train)} test_benign={len(benign_test)} test_attack={len(attack_test)}",
        flush=True,
    )

    x_train, x_test, numeric_cols = build_features(benign_train, test_df)
    dropped_features: List[str] = []
    if not args.keep_env_features:
        keep_cols = [c for c in numeric_cols if c not in ENV_FEATURES]
        dropped_features.extend([c for c in numeric_cols if c in ENV_FEATURES])
        numeric_cols = keep_cols
        x_train = x_train[numeric_cols]
        x_test = x_test[numeric_cols]

    if not args.keep_id_feature and "id" in numeric_cols:
        numeric_cols = [c for c in numeric_cols if c != "id"]
        x_train = x_train[numeric_cols]
        x_test = x_test[numeric_cols]
        if "id" not in dropped_features:
            dropped_features.append("id")

    feature_used = len(numeric_cols)
    if args.pca_components > 0:
        scaler = StandardScaler()
        x_train = scaler.fit_transform(x_train)
        x_test = scaler.transform(x_test)
        pca = PCA(n_components=args.pca_components, random_state=args.seed)
        x_train = pca.fit_transform(x_train)
        x_test = pca.transform(x_test)
        feature_used = int(args.pca_components)
        print(
            f"[3/4] Standardize -> PCA={args.pca_components} -> IsolationForest "
            f"(from {len(numeric_cols)} numeric features) ...",
            flush=True,
        )
    else:
        print(f"[3/4] Training IsolationForest on {len(numeric_cols)} numeric features ...", flush=True)
    clf = IsolationForest(
        n_estimators=args.n_estimators,
        max_samples=args.max_samples,
        contamination=args.contamination,
        random_state=args.seed,
        n_jobs=-1,
    )
    clf.fit(x_train)
    # sklearn score_samples: larger => more normal. We flip sign so larger => more anomalous/attack-like.
    test_scores_attack_higher = -clf.score_samples(x_test)
    benign_scores_attack_higher = test_scores_attack_higher[y_test == 0]

    print("[4/4] Evaluating ...", flush=True)
    if args.fpr_start < 1 or args.fpr_end < args.fpr_start:
        raise ValueError("Invalid FPR range. Expect 1 <= fpr-start <= fpr-end.")
    fpr_targets = [p / 100.0 for p in range(args.fpr_start, args.fpr_end + 1)]

    metrics = evaluate(
        y_true=y_test,
        scores_attack_higher=test_scores_attack_higher,
        benign_scores=benign_scores_attack_higher,
        target_fprs=fpr_targets,
    )

    report: Dict[str, object] = {
        "data_dir": str(data_dir),
        "source_files": [str(data_dir / f) for f in FILES_2017],
        "seed": args.seed,
        "iforest_params": {
            "n_estimators": args.n_estimators,
            "max_samples": args.max_samples,
            "contamination": args.contamination,
            "pca_components": int(args.pca_components),
            "drop_id_feature": bool(not args.keep_id_feature),
            "drop_env_features": bool(not args.keep_env_features),
            "standardize_before_pca": bool(args.pca_components > 0),
            "fpr_target_percent_range": [int(args.fpr_start), int(args.fpr_end)],
        },
        "dataset_stats": {
            "total_rows": total_rows,
            "total_benign": total_benign,
            "total_attack": total_attack,
            "train_benign": int(len(benign_train)),
            "test_benign": int(len(benign_test)),
            "test_attack": int(len(attack_test)),
            "feature_count": int(feature_used),
            "feature_names": numeric_cols,
            "dropped_env_features": sorted(set(dropped_features)),
        },
        "metrics": metrics,
    }

    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[DONE] metrics written: {out_json}", flush=True)
    print(f"[DONE] ROC AUC: {metrics['roc_auc']:.6f}", flush=True)


if __name__ == "__main__":
    main()
