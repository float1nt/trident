#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import accuracy_score, precision_recall_fscore_support, roc_auc_score

# Ensure project root is importable when running via `python scripts/...`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trident_stream.tscissors import TScissors
from trident_stream.tsieve import TSieve
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
    learner_name: str,
    tsieve: TSieve,
    year_df: pd.DataFrame,
    feature_cols: List[str],
) -> Dict[str, float]:
    x_df, _ = preprocess_features(year_df)
    x_df = x_df.reindex(columns=feature_cols, fill_value=0.0)
    x = x_df.values.astype(np.float32)
    y_true_attack = (~year_df["IsBenign"]).astype(int).values

    learner = tsieve.learners[learner_name]
    losses = learner.reconstruction_loss(x)
    threshold = float(learner.threshold * tsieve.benign_accept_scale)
    y_pred_attack = (losses > threshold).astype(int)

    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true_attack,
        y_pred_attack,
        average="binary",
        zero_division=0,
    )
    acc = accuracy_score(y_true_attack, y_pred_attack)
    benign_accept_rate = float((losses <= threshold).mean())

    out: Dict[str, float] = {
        "rows": float(len(year_df)),
        "attack_rows": float(int(y_true_attack.sum())),
        "benign_rows": float(int((1 - y_true_attack).sum())),
        "threshold": threshold,
        "mean_loss": float(np.mean(losses)),
        "p95_loss": float(np.quantile(losses, 0.95)),
        "accuracy": float(acc),
        "precision_attack": float(precision),
        "recall_attack": float(recall),
        "f1_attack": float(f1),
        "benign_accept_rate": benign_accept_rate,
    }
    if len(np.unique(y_true_attack)) == 2:
        out["roc_auc_attack"] = float(roc_auc_score(y_true_attack, losses))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train AE on aligned benign data and evaluate binary performance on 2019/2026.",
    )
    parser.add_argument(
        "--data-csv",
        default="data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv",
        help="Aligned input csv.",
    )
    parser.add_argument("--train-year", default="2017", help="Benign train year tag (default: 2017).")
    parser.add_argument("--train-max-rows", type=int, default=20000, help="Max benign train rows.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--init-epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument(
        "--metrics-json",
        default="outputs/analysis/ae_binary_eval_2019_2026.json",
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

    device = torch.device("cpu" if args.cpu_only or not torch.cuda.is_available() else "cuda")
    tscissors = TScissors(evt_quantile=0.95, evt_risk=1e-3, fallback_quantile=0.99)
    tsieve = TSieve(
        device=device,
        tscissors=tscissors,
        batch_size=args.batch_size,
        lr=args.lr,
        min_class_samples=300,
        max_train_per_class=max(1000, args.train_max_rows),
        benign_accept_scale=1.0,
    )

    ok = tsieve.add_learner("BENIGN", x_train, epochs=args.init_epochs)
    if not ok:
        raise RuntimeError("Failed to create BENIGN AE learner. Not enough training samples.")

    metrics: Dict[str, object] = {
        "data_csv": str(args.data_csv),
        "train_year": str(args.train_year),
        "train_rows_used": int(len(train_df)),
        "feature_dim": int(len(feature_cols)),
        "device": str(device),
        "benign_threshold": float(tsieve.learners["BENIGN"].threshold),
        "eval": {},
    }

    for year in ["2019", "2026"]:
        year_df = data[data["Year"] == year].copy()
        if len(year_df) == 0:
            metrics["eval"][year] = {"rows": 0, "note": "no rows for this year"}  # type: ignore[index]
            continue
        metrics["eval"][year] = evaluate_year("BENIGN", tsieve, year_df, feature_cols)  # type: ignore[index]

    out_path = Path(args.metrics_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved metrics: {out_path}")


if __name__ == "__main__":
    main()
