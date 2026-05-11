#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.metrics import auc, roc_curve
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

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


class AE(nn.Module):
    def __init__(self, in_dim: int) -> None:
        super().__init__()
        h1 = max(32, in_dim // 2)
        h2 = max(16, in_dim // 4)
        self.encoder = nn.Sequential(
            nn.Linear(in_dim, h1),
            nn.ReLU(),
            nn.Linear(h1, h2),
            nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(h2, h1),
            nn.ReLU(),
            nn.Linear(h1, in_dim),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.encoder(x)
        return self.decoder(z)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare ROC: PCA+IF vs AE reconstruction.")
    parser.add_argument("--data-csv", default="data/aligned_2017_2019_sampled_year_tagged.csv")
    parser.add_argument("--train-benign", type=int, default=10000)
    parser.add_argument("--test-benign", type=int, default=5000)
    parser.add_argument("--test-attack", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--pca-var", type=float, default=0.95, help="PCA explained variance ratio.")
    parser.add_argument("--pca-components", type=int, default=0, help="Fixed PCA components; >0 overrides --pca-var.")
    parser.add_argument("--ae-epochs", type=int, default=20)
    parser.add_argument("--ae-batch-size", type=int, default=512)
    parser.add_argument("--ae-lr", type=float, default=1e-3)
    parser.add_argument(
        "--ae-score-mode",
        choices=["mean_mse", "topk_mse", "p90_error", "all"],
        default="all",
        help="AE anomaly score mode; 'all' plots all AE scoring variants.",
    )
    parser.add_argument(
        "--ae-topk-ratio",
        type=float,
        default=0.1,
        help="Top-k ratio for topk_mse score (0,1].",
    )
    parser.add_argument(
        "--roc-png",
        default="outputs/analysis/roc_compare_pca_if_vs_ae.png",
    )
    parser.add_argument(
        "--metrics-json",
        default="outputs/analysis/roc_compare_pca_if_vs_ae_metrics.json",
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
        [np.zeros(args.test_benign, dtype=np.int32), np.ones(args.test_attack, dtype=np.int32)]
    )

    train_x_df, feature_cols = preprocess_features(train_df)
    test_x_df, _ = preprocess_features(test_df)
    test_x_df = test_x_df.reindex(columns=feature_cols, fill_value=0.0)

    scaler = StandardScaler()
    x_train = scaler.fit_transform(train_x_df.values.astype(np.float32))
    x_test = scaler.transform(test_x_df.values.astype(np.float32))

    # 1) PCA + IsolationForest
    if int(args.pca_components) > 0:
        pca = PCA(n_components=int(args.pca_components), random_state=args.seed)
    else:
        pca = PCA(n_components=args.pca_var, random_state=args.seed)
    x_train_pca = pca.fit_transform(x_train)
    x_test_pca = pca.transform(x_test)
    if_clf = IsolationForest(
        n_estimators=300,
        contamination="auto",
        random_state=args.seed,
        n_jobs=-1,
    )
    if_clf.fit(x_train_pca)
    if_score = -if_clf.decision_function(x_test_pca)
    fpr_if, tpr_if, _ = roc_curve(test_y, if_score)
    auc_if = float(auc(fpr_if, tpr_if))

    # 2) AE reconstruction
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = AE(in_dim=x_train.shape[1]).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.ae_lr)
    criterion = nn.MSELoss()
    train_loader = DataLoader(
        TensorDataset(torch.from_numpy(x_train)),
        batch_size=args.ae_batch_size,
        shuffle=True,
        drop_last=False,
    )

    model.train()
    for _ in range(args.ae_epochs):
        for (xb,) in train_loader:
            xb = xb.to(device)
            optimizer.zero_grad(set_to_none=True)
            recon = model(xb)
            loss = criterion(recon, xb)
            loss.backward()
            optimizer.step()

    model.eval()
    with torch.no_grad():
        xt = torch.from_numpy(x_test).to(device)
        recon = model(xt)
        err = (recon - xt) ** 2
        mean_mse = torch.mean(err, dim=1)
        k = max(1, int(err.shape[1] * max(min(args.ae_topk_ratio, 1.0), 1e-6)))
        topk_vals, _ = torch.topk(err, k=k, dim=1, largest=True, sorted=False)
        topk_mse = torch.mean(topk_vals, dim=1)
        p90_err = torch.quantile(err, q=0.9, dim=1)

    ae_scores = {
        "mean_mse": mean_mse.detach().cpu().numpy(),
        "topk_mse": topk_mse.detach().cpu().numpy(),
        "p90_error": p90_err.detach().cpu().numpy(),
    }
    if args.ae_score_mode == "all":
        ae_modes = ["mean_mse", "topk_mse", "p90_error"]
    else:
        ae_modes = [args.ae_score_mode]

    ae_curves = {}
    for mode in ae_modes:
        fpr, tpr, _ = roc_curve(test_y, ae_scores[mode])
        ae_curves[mode] = {
            "fpr": fpr,
            "tpr": tpr,
            "auc": float(auc(fpr, tpr)),
        }

    # Plot
    roc_png = Path(args.roc_png)
    roc_png.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(7, 6))
    plt.plot(fpr_if, tpr_if, linewidth=2.0, label=f"PCA+IF (AUC={auc_if:.4f})")
    for mode in ae_modes:
        item = ae_curves[mode]
        plt.plot(
            item["fpr"],
            item["tpr"],
            linewidth=2.0,
            label=f"AE-{mode} (AUC={item['auc']:.4f})",
        )
    plt.plot([0, 1], [0, 1], "--", linewidth=1.2, color="gray", label="Random")
    plt.xlabel("False Positive Rate")
    plt.ylabel("True Positive Rate")
    plt.title("ROC Comparison: PCA+IF vs AE Reconstruction")
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
        "pca_explained_variance_ratio": float(args.pca_var),
        "pca_components_arg": int(args.pca_components),
        "pca_components": int(x_train_pca.shape[1]),
        "auc_pca_if": auc_if,
        "ae_score_mode": args.ae_score_mode,
        "ae_topk_ratio": float(args.ae_topk_ratio),
        "auc_ae_mean_mse": ae_curves.get("mean_mse", {}).get("auc"),
        "auc_ae_topk_mse": ae_curves.get("topk_mse", {}).get("auc"),
        "auc_ae_p90_error": ae_curves.get("p90_error", {}).get("auc"),
        "ae_epochs": int(args.ae_epochs),
        "ae_batch_size": int(args.ae_batch_size),
        "ae_lr": float(args.ae_lr),
        "device": str(device),
        "roc_png": str(roc_png),
    }
    metrics_json = Path(args.metrics_json)
    metrics_json.parent.mkdir(parents=True, exist_ok=True)
    metrics_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved ROC: {roc_png}")
    print(f"Saved metrics: {metrics_json}")
    print(f"AUC PCA+IF: {auc_if:.6f}")
    for mode in ae_modes:
        print(f"AUC AE-{mode}: {ae_curves[mode]['auc']:.6f}")


if __name__ == "__main__":
    main()
