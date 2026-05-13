#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.decomposition import PCA
from sklearn.metrics import auc, precision_recall_curve, roc_curve
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset


FILES_2017 = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]
ENV_FEATURES = {"id", "Flow ID", "Src IP", "Dst IP", "Src Port", "Dst Port", "Timestamp"}


class AutoEncoderUNet(nn.Module):
    """Paper-aligned AE with U-Net-like skip additions."""

    def __init__(self, in_dim: int):
        super().__init__()
        self.enc1 = nn.Linear(in_dim, 256)
        self.enc2 = nn.Linear(256, 128)
        self.enc3 = nn.Linear(128, 64)
        self.enc4 = nn.Linear(64, 32)

        self.dec3 = nn.Linear(32, 64)
        self.dec2 = nn.Linear(64, 128)
        self.dec1 = nn.Linear(128, 256)
        self.reconstruct = nn.Linear(256, in_dim)
        self.act = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        e1 = self.act(self.enc1(x))
        e2 = self.act(self.enc2(e1))
        e3 = self.act(self.enc3(e2))
        e4 = self.act(self.enc4(e3))
        d3 = self.act(self.dec3(e4) + e3)
        d2 = self.act(self.dec2(d3) + e2)
        d1 = self.act(self.dec1(d2) + e1)
        return self.reconstruct(d1)


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
    parser = argparse.ArgumentParser(description="Standalone AE-UNet evaluation on raw CICIDS2017 source files.")
    parser.add_argument("--data-dir", default="/home/data/2017")
    parser.add_argument("--train-benign-max", type=int, default=200000)
    parser.add_argument("--test-benign-max", type=int, default=120000)
    parser.add_argument("--test-attack-max", type=int, default=120000)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--pca-components", type=int, default=0, help="Set >0 to apply PCA after standardization.")
    parser.add_argument("--fpr-start", type=int, default=1)
    parser.add_argument("--fpr-end", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--out-json",
        default="outputs/analysis/ae_unet_2017_source_test_metrics.json",
    )
    args = parser.parse_args()

    if args.fpr_start < 1 or args.fpr_end < args.fpr_start:
        raise ValueError("Invalid FPR range. Expect 1 <= fpr-start <= fpr-end.")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)

    data_dir = Path(args.data_dir)
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    print("[1/5] Loading /home/data/2017 source files ...", flush=True)
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
        "[2/5] Dataset split: "
        f"train_benign={len(benign_train)} test_benign={len(benign_test)} test_attack={len(attack_test)}",
        flush=True,
    )

    numeric_cols = [c for c in df.columns if c != "Label" and pd.api.types.is_numeric_dtype(df[c])]
    keep_cols = [c for c in numeric_cols if c not in ENV_FEATURES]
    dropped_cols = [c for c in numeric_cols if c in ENV_FEATURES]
    x_train = benign_train[keep_cols].replace([np.inf, -np.inf], np.nan)
    x_test = test_df[keep_cols].replace([np.inf, -np.inf], np.nan)
    med = x_train.median(numeric_only=True)
    x_train = x_train.fillna(med).fillna(0.0)
    x_test = x_test.fillna(med).fillna(0.0)

    scaler = StandardScaler()
    x_train_np = scaler.fit_transform(x_train)
    x_test_np = scaler.transform(x_test)

    feature_count_before_pca = x_train_np.shape[1]
    if args.pca_components > 0:
        pca = PCA(n_components=args.pca_components, random_state=args.seed)
        x_train_np = pca.fit_transform(x_train_np)
        x_test_np = pca.transform(x_test_np)
        explained = float(pca.explained_variance_ratio_.sum())
    else:
        explained = float("nan")

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(
        "[3/5] Training AE-UNet: "
        f"features={x_train_np.shape[1]} (before_pca={feature_count_before_pca}) device={device.type}",
        flush=True,
    )
    model = AutoEncoderUNet(x_train_np.shape[1]).to(device)
    ds = TensorDataset(torch.as_tensor(x_train_np, dtype=torch.float32))
    dl = DataLoader(ds, batch_size=args.batch_size, shuffle=True, drop_last=False)
    optimizer = optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.MSELoss()

    model.train()
    epoch_losses: List[float] = []
    for _ in range(args.epochs):
        batch_losses: List[float] = []
        for (batch,) in dl:
            batch = batch.to(device)
            pred = model(batch)
            loss = criterion(pred, batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            batch_losses.append(float(loss.item()))
        epoch_losses.append(float(np.mean(batch_losses)) if batch_losses else float("nan"))

    print("[4/5] Computing reconstruction losses ...", flush=True)
    model.eval()
    with torch.no_grad():
        t_test = torch.as_tensor(x_test_np, dtype=torch.float32, device=device)
        pred = model(t_test)
        mse = torch.mean((pred - t_test) ** 2, dim=1).detach().cpu().numpy()
    scores_attack_higher = mse.astype(np.float64, copy=False)
    benign_scores = scores_attack_higher[y_test == 0]

    print("[5/5] Evaluating ...", flush=True)
    fpr_targets = [p / 100.0 for p in range(args.fpr_start, args.fpr_end + 1)]
    metrics = evaluate(
        y_true=y_test,
        scores_attack_higher=scores_attack_higher,
        benign_scores=benign_scores,
        target_fprs=fpr_targets,
    )

    report: Dict[str, object] = {
        "data_dir": str(data_dir),
        "source_files": [str(data_dir / f) for f in FILES_2017],
        "seed": int(args.seed),
        "ae_unet_params": {
            "epochs": int(args.epochs),
            "batch_size": int(args.batch_size),
            "lr": float(args.lr),
            "pca_components": int(args.pca_components),
            "fpr_target_percent_range": [int(args.fpr_start), int(args.fpr_end)],
        },
        "dataset_stats": {
            "total_rows": total_rows,
            "total_benign": total_benign,
            "total_attack": total_attack,
            "train_benign": int(len(benign_train)),
            "test_benign": int(len(benign_test)),
            "test_attack": int(len(attack_test)),
            "feature_count": int(x_train_np.shape[1]),
            "feature_count_before_pca": int(feature_count_before_pca),
            "dropped_env_features": sorted(set(dropped_cols)),
            "feature_names_before_pca": keep_cols,
            "pca_explained_variance_ratio_sum": explained,
        },
        "train_trace": {
            "epoch_losses": epoch_losses,
        },
        "metrics": metrics,
    }
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[DONE] metrics written: {out_json}", flush=True)
    print(f"[DONE] ROC AUC: {metrics['roc_auc']:.6f}", flush=True)


if __name__ == "__main__":
    main()
