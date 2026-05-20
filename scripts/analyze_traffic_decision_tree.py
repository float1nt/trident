#!/usr/bin/env python3
"""Decision-tree analysis for traffic / learner cluster discrimination."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from sklearn.model_selection import (
    StratifiedKFold,
    cross_val_predict,
    cross_val_score,
    train_test_split,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier, export_text

from trident_stream.experiment import ENVIRONMENT_COLUMNS, preprocess_features
from trident_stream.utils import is_benign_label, split_year_label

META_COLS = {
    "learner_name",
    "label",
    "dominant_label",
    "label_distribution_json",
    "protocol_cluster_type",
    "attack_ratio",
    "count",
    "ratio",
    "is_benign",
    "year_tag",
    "base_label",
    "Label",
    "original_label",
    "benign_type",
    "is_attack",
}


def _flow_numeric_cols(df: pd.DataFrame, feature_profile: str = "all_numeric_no_env") -> List[str]:
    _, cols = preprocess_features(df, feature_profile=feature_profile)
    return cols


def _sanitize_numeric(df: pd.DataFrame, numeric_cols: List[str]) -> None:
    if not numeric_cols:
        return
    block = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
    block = block.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df[numeric_cols] = block


def _stratified_sample(
    df: pd.DataFrame,
    label_col: str,
    *,
    per_label: int,
    seed: int,
    min_class_count: int = 1,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    parts: List[pd.DataFrame] = []
    for label, g in df.groupby(label_col, sort=False):
        if len(g) < min_class_count:
            continue
        n = min(per_label, len(g))
        idx = rng.choice(g.index.to_numpy(), size=n, replace=False)
        parts.append(df.loc[idx])
    if not parts:
        return df.iloc[0:0].copy()
    return pd.concat(parts, ignore_index=True)


def _numeric_feature_cols(df: pd.DataFrame) -> List[str]:
    out: List[str] = []
    for c in df.columns:
        if c in META_COLS:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            out.append(c)
    return out


def _cat_feature_cols(df: pd.DataFrame) -> List[str]:
    if "protocol_cluster_type" not in df.columns:
        return []
    return ["protocol_cluster_type"]


def _attack_class(y_ratio: pd.Series, threshold: float) -> pd.Series:
    return (pd.to_numeric(y_ratio, errors="coerce").fillna(0.0) >= threshold).astype(int)


def _polarity_3way(y_ratio: pd.Series, pure_eps: float = 0.02) -> pd.Series:
    r = pd.to_numeric(y_ratio, errors="coerce").fillna(0.0)
    labels = np.full(len(r), "MIXED", dtype=object)
    labels[r <= pure_eps] = "BENIGN"
    labels[r >= 1.0 - pure_eps] = "ATTACK"
    return pd.Series(labels, index=r.index)


def _build_xy(
    df: pd.DataFrame,
    label_col: str,
    numeric_cols: List[str],
    cat_cols: List[str],
) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
    y = df[label_col].values
    X_num = df[numeric_cols].copy() if numeric_cols else pd.DataFrame(index=df.index)
    parts: List[Tuple[str, Any]] = []
    if len(numeric_cols) > 0:
        parts.append(
            (
                "num",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                    ]
                ),
                numeric_cols,
            )
        )
    if len(cat_cols) > 0:
        parts.append(
            (
                "cat",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="most_frequent")),
                        (
                            "onehot",
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                        ),
                    ]
                ),
                cat_cols,
            )
        )
    preprocess = ColumnTransformer(parts, remainder="drop")
    pipe = Pipeline([("prep", preprocess)])
    X_mat = pipe.fit_transform(df[numeric_cols + cat_cols])
    feat_names: List[str] = []
    if len(numeric_cols) > 0:
        feat_names.extend(numeric_cols)
    if len(cat_cols) > 0:
        ohe: OneHotEncoder = pipe.named_steps["prep"].named_transformers_["cat"].named_steps["onehot"]
        feat_names.extend(list(ohe.get_feature_names_out(cat_cols)))
    return pd.DataFrame(X_mat, columns=feat_names), y, feat_names


def _attack_detection_rates(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, Any]:
    """Rates with positive class = attack (1)."""
    yt = np.asarray(y_true).astype(int)
    yp = np.asarray(y_pred).astype(int)
    tp = int(np.sum((yt == 1) & (yp == 1)))
    fn = int(np.sum((yt == 1) & (yp == 0)))
    tn = int(np.sum((yt == 0) & (yp == 0)))
    fp = int(np.sum((yt == 0) & (yp == 1)))
    n_attack = tp + fn
    n_benign = tn + fp
    return {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "n_attack": n_attack,
        "n_benign": n_benign,
        "fpr": float(fp / n_benign) if n_benign else None,
        "fnr": float(fn / n_attack) if n_attack else None,
        "tpr": float(tp / n_attack) if n_attack else None,
        "tnr": float(tn / n_benign) if n_benign else None,
        "accuracy": float((tp + tn) / (n_attack + n_benign)) if (n_attack + n_benign) else None,
    }


def _fit_tree_report(
    X: pd.DataFrame,
    y: np.ndarray,
    feat_names: List[str],
    *,
    max_depth: int,
    min_samples_leaf: int,
    random_state: int,
    task_name: str,
) -> Dict[str, Any]:
    classes, counts = np.unique(y, return_counts=True)
    dist = {str(c): int(n) for c, n in zip(classes, counts)}
    n_splits = min(5, int(min(counts))) if len(counts) > 1 else 0
    clf = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        class_weight="balanced",
        random_state=random_state,
    )

    cv_acc: List[float] = []
    cv_f1: List[float] = []
    cv_auc: Optional[float] = None
    y_pred_cv: Optional[np.ndarray] = None

    if n_splits >= 2 and len(np.unique(y)) > 1:
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=random_state)
        cv_acc = cross_val_score(clf, X, y, cv=skf, scoring="accuracy").tolist()
        cv_f1 = cross_val_score(clf, X, y, cv=skf, scoring="f1_macro").tolist()
        y_pred_cv = cross_val_predict(clf, X, y, cv=skf)
        if len(np.unique(y)) == 2:
            try:
                proba = cross_val_predict(clf, X, y, cv=skf, method="predict_proba")[:, 1]
                cv_auc = float(roc_auc_score(y, proba))
            except Exception:
                cv_auc = None

    clf.fit(X, y)
    importances = sorted(
        zip(feat_names, clf.feature_importances_.tolist()),
        key=lambda t: t[1],
        reverse=True,
    )
    top_importance = [
        {"feature": str(f), "importance": float(v)} for f, v in importances if v > 1e-9
    ][:30]

    rules = export_text(
        clf,
        feature_names=list(X.columns),
        max_depth=max_depth,
        spacing=2,
    )

    train_pred = clf.predict(X)
    report = {
        "task": task_name,
        "n_samples": int(len(y)),
        "class_distribution": dist,
        "cv_folds": int(n_splits),
        "cv_accuracy_mean": float(np.mean(cv_acc)) if cv_acc else None,
        "cv_accuracy_std": float(np.std(cv_acc)) if cv_acc else None,
        "cv_f1_macro_mean": float(np.mean(cv_f1)) if cv_f1 else None,
        "cv_f1_macro_std": float(np.std(cv_f1)) if cv_f1 else None,
        "cv_roc_auc": cv_auc,
        "train_accuracy": float(accuracy_score(y, train_pred)),
        "train_f1_macro": float(f1_score(y, train_pred, average="macro", zero_division=0)),
        "top_feature_importance": top_importance,
        "tree_rules": rules,
    }
    if y_pred_cv is not None:
        report["cv_classification_report"] = classification_report(
            y, y_pred_cv, zero_division=0, output_dict=True
        )
        labels_sorted = sorted(np.unique(y), key=lambda x: str(x))
        report["cv_confusion_matrix"] = {
            "labels": [str(x) for x in labels_sorted],
            "matrix": confusion_matrix(y, y_pred_cv, labels=labels_sorted).tolist(),
        }
    return report


def _load_learner_table(run_dir: Path) -> pd.DataFrame:
    dist = pd.read_csv(run_dir / "learner_label_distribution.csv")
    risk_path = run_dir / "learner_risk_scores.csv"
    if risk_path.exists():
        risk = pd.read_csv(risk_path)
        extra = [
            c
            for c in risk.columns
            if c not in dist.columns and c not in {"learner_name"}
        ]
        if extra:
            dist = dist.merge(risk[["learner_name"] + extra], on="learner_name", how="left")
    return dist


def analyze_learner_level(
    df: pd.DataFrame,
    *,
    attack_threshold: float,
    max_depth: int,
    min_samples_leaf: int,
    random_state: int,
) -> List[Dict[str, Any]]:
    numeric_cols = _numeric_feature_cols(df)
    cat_cols = _cat_feature_cols(df)
    reports: List[Dict[str, Any]] = []

    df = df.copy()
    df["is_attack_learner"] = _attack_class(df["attack_ratio"], attack_threshold)
    X, y, feats = _build_xy(df, "is_attack_learner", numeric_cols, cat_cols)
    reports.append(
        _fit_tree_report(
            X,
            y,
            feats,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            random_state=random_state,
            task_name=f"learner_benign_vs_attack(threshold={attack_threshold})",
        )
    )

    df["polarity_3way"] = _polarity_3way(df["attack_ratio"])
    if df["polarity_3way"].nunique() >= 2:
        X3, y3, f3 = _build_xy(df, "polarity_3way", numeric_cols, cat_cols)
        reports.append(
            _fit_tree_report(
                X3,
                y3,
                f3,
                max_depth=max_depth,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
                task_name="learner_polarity_3way(BENIGN/MIXED/ATTACK)",
            )
        )

    if "protocol_cluster_type" in df.columns and df["protocol_cluster_type"].nunique() >= 2:
        vc = df["protocol_cluster_type"].value_counts()
        keep = vc[vc >= 3].index.tolist()
        sub = df[df["protocol_cluster_type"].isin(keep)].copy()
        if len(sub) >= 6 and sub["protocol_cluster_type"].nunique() >= 2:
            Xp, yp, fp = _build_xy(sub, "protocol_cluster_type", numeric_cols, [])
            reports.append(
                _fit_tree_report(
                    Xp,
                    yp,
                    fp,
                    max_depth=max_depth,
                    min_samples_leaf=min_samples_leaf,
                    random_state=random_state,
                    task_name="learner_protocol_cluster_type",
                )
            )

    return reports


def analyze_label_level(
    label_csv: Path,
    *,
    max_depth: int,
    min_samples_leaf: int,
    random_state: int,
    min_label_count: int,
) -> List[Dict[str, Any]]:
    df = pd.read_csv(label_csv)
    numeric_cols = _numeric_feature_cols(df)
    reports: List[Dict[str, Any]] = []

    df["is_attack"] = (~df["is_benign"].astype(bool)).astype(int)
    X, y, feats = _build_xy(df, "is_attack", numeric_cols, _cat_feature_cols(df))
    reports.append(
        _fit_tree_report(
            X,
            y,
            feats,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            random_state=random_state,
            task_name="label_benign_vs_attack",
        )
    )

    if "count" in df.columns:
        label_mass = df.groupby("base_label", as_index=False)["count"].sum()
        top_labels = label_mass.loc[
            label_mass["count"] >= min_label_count, "base_label"
        ].astype(str).tolist()
    else:
        vc = df["base_label"].value_counts()
        top_labels = vc[vc >= min_label_count].index.astype(str).tolist()
    if len(top_labels) >= 3:
        sub = df[df["base_label"].isin(top_labels)].copy()
        if "count" in sub.columns and len(sub) > len(top_labels):
            w = pd.to_numeric(sub["count"], errors="coerce").fillna(1.0).clip(lower=1.0)
            agg_rows: List[Dict[str, Any]] = []
            for bl, g in sub.groupby("base_label", sort=False):
                wg = g.copy()
                ww = pd.to_numeric(wg["count"], errors="coerce").fillna(1.0).clip(lower=1.0)
                row: Dict[str, Any] = {"base_label": str(bl)}
                for c in numeric_cols:
                    v = pd.to_numeric(wg[c], errors="coerce")
                    row[c] = float(np.average(v.fillna(0.0), weights=ww))
                if "protocol_cluster_type" in wg.columns:
                    row["protocol_cluster_type"] = str(
                        wg["protocol_cluster_type"].mode(dropna=True).iloc[0]
                    )
                row["count"] = float(ww.sum())
                agg_rows.append(row)
            sub = pd.DataFrame(agg_rows)
        Xb, yb, fb = _build_xy(sub, "base_label", numeric_cols, _cat_feature_cols(sub))
        reports.append(
            _fit_tree_report(
                Xb,
                yb,
                fb,
                max_depth=max(max_depth, 3),
                min_samples_leaf=max(1, min_samples_leaf),
                random_state=random_state,
                task_name=f"label_base_label(top_count>={min_label_count}, n_classes={len(top_labels)})",
            )
        )
    return reports


def analyze_flow_csv(
    csv_path: Path,
    *,
    sample_per_label: int,
    max_depth: int,
    min_samples_leaf: int,
    random_state: int,
    feature_profile: str,
    min_label_count: int,
    chunksize: int = 200_000,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Stratified flow-level decision trees on a raw aligned CSV."""
    label_col = "Label"
    meta = {"source_csv": str(csv_path), "sample_per_label": sample_per_label}

    label_chunks: List[pd.Series] = []
    for chunk in pd.read_csv(csv_path, usecols=[label_col], chunksize=chunksize):
        label_chunks.append(chunk[label_col].astype(str))
    all_labels = pd.concat(label_chunks, ignore_index=True)
    meta["total_rows"] = int(len(all_labels))
    meta["label_counts"] = all_labels.value_counts().astype(int).to_dict()

    rng = np.random.default_rng(random_state)
    picked_idx: List[int] = []
    for label, count in meta["label_counts"].items():
        if int(count) < min_label_count:
            continue
        pos = np.flatnonzero(all_labels.to_numpy() == label)
        n = min(sample_per_label, len(pos))
        picked_idx.extend(rng.choice(pos, size=n, replace=False).tolist())

    if not picked_idx:
        raise ValueError("No rows selected; check min_label_count / sample_per_label.")

    picked_idx = sorted(set(picked_idx))
    meta["sampled_rows"] = len(picked_idx)
    idx_set = set(picked_idx)
    rows: List[pd.DataFrame] = []
    offset = 0
    for chunk in pd.read_csv(csv_path, chunksize=chunksize, low_memory=False):
        take = [i - offset for i in picked_idx if offset <= i < offset + len(chunk)]
        if take:
            rows.append(chunk.iloc[take].copy())
        offset += len(chunk)
    df = pd.concat(rows, ignore_index=True)
    meta["sampled_label_counts"] = df[label_col].astype(str).value_counts().astype(int).to_dict()

    df["is_attack"] = (~df[label_col].map(is_benign_label)).astype(int)
    df["base_label"] = df[label_col].map(lambda x: split_year_label(str(x))[1])
    if "year_tag" not in df.columns:
        df["year_tag"] = df[label_col].map(lambda x: split_year_label(str(x))[0])

    numeric_cols = _flow_numeric_cols(df, feature_profile=feature_profile)
    _sanitize_numeric(df, numeric_cols)
    reports: List[Dict[str, Any]] = []

    X, y, feats = _build_xy(df, "is_attack", numeric_cols, [])
    reports.append(
        _fit_tree_report(
            X,
            y,
            feats,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            random_state=random_state,
            task_name="flow_benign_vs_attack",
        )
    )

    if df["year_tag"].nunique() >= 2:
        Xy, yy, fy = _build_xy(df, "year_tag", numeric_cols, [])
        reports.append(
            _fit_tree_report(
                Xy,
                yy,
                fy,
                max_depth=max_depth,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
                task_name="flow_year_tag(2017/2019/2026)",
            )
        )

    top_labels = [
        str(lbl)
        for lbl, cnt in meta["label_counts"].items()
        if int(cnt) >= min_label_count
    ]
    if len(top_labels) >= 3:
        sub = df[df[label_col].isin(top_labels)].copy()
        Xl, yl, fl = _build_xy(sub, label_col, numeric_cols, [])
        reports.append(
            _fit_tree_report(
                Xl,
                yl,
                fl,
                max_depth=max(max_depth, 5),
                min_samples_leaf=max(min_samples_leaf, 20),
                random_state=random_state,
                task_name=f"flow_full_label(n_classes={len(top_labels)}, min_count>={min_label_count})",
            )
        )

    attack_only = df[df["is_attack"] == 1].copy()
    atk_labels = [
        str(lbl)
        for lbl, cnt in meta["label_counts"].items()
        if int(cnt) >= min_label_count and not is_benign_label(lbl)
    ]
    if len(atk_labels) >= 3:
        sub_a = attack_only[attack_only[label_col].isin(atk_labels)].copy()
        Xa, ya, fa = _build_xy(sub_a, label_col, numeric_cols, [])
        reports.append(
            _fit_tree_report(
                Xa,
                ya,
                fa,
                max_depth=max(max_depth, 5),
                min_samples_leaf=max(min_samples_leaf, 15),
                random_state=random_state,
                task_name=f"flow_attack_subtypes_only(n_classes={len(atk_labels)})",
            )
        )

    benign_sub = df[df["is_attack"] == 0].copy()
    if "benign_type" in benign_sub.columns:
        benign_sub["benign_type"] = (
            benign_sub["benign_type"].astype("string").fillna("UNKNOWN").astype(str)
        )
    if "benign_type" in benign_sub.columns and benign_sub["benign_type"].nunique() >= 2:
        Xb, yb, fb = _build_xy(benign_sub, "benign_type", numeric_cols, [])
        reports.append(
            _fit_tree_report(
                Xb,
                yb,
                fb,
                max_depth=max_depth,
                min_samples_leaf=min_samples_leaf,
                random_state=random_state,
                task_name="flow_benign_subtype(DNS/SSH/...)",
            )
        )

    return reports, meta


def _load_flow_csv(
    csv_path: Path,
    *,
    feature_profile: str,
    chunksize: int = 200_000,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Any]]:
    """Load full CSV with only model feature columns + labels."""
    head = pd.read_csv(csv_path, nrows=2000, low_memory=False)
    numeric_cols = _flow_numeric_cols(head, feature_profile=feature_profile)
    label_col = "Label"
    extra = [c for c in ("year_tag", "benign_type") if c in head.columns]
    usecols = list(dict.fromkeys([label_col] + extra + numeric_cols))

    parts: List[pd.DataFrame] = []
    for chunk in pd.read_csv(csv_path, usecols=usecols, chunksize=chunksize, low_memory=False):
        parts.append(chunk)
    df = pd.concat(parts, ignore_index=True)
    _sanitize_numeric(df, numeric_cols)
    meta = {
        "source_csv": str(csv_path),
        "total_rows": int(len(df)),
        "label_counts": df[label_col].astype(str).value_counts().astype(int).to_dict(),
        "feature_columns": numeric_cols,
    }
    return df, numeric_cols, meta


def analyze_flow_full_benign_vs_attack(
    csv_path: Path,
    *,
    val_ratio: float,
    max_depth: int,
    min_samples_leaf: int,
    random_state: int,
    feature_profile: str,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Train/test on all rows: stratified hold-out validation + optional in-sample train metrics."""
    label_col = "Label"
    df, numeric_cols, meta = _load_flow_csv(csv_path, feature_profile=feature_profile)
    meta["val_ratio"] = val_ratio
    meta["mode"] = "full_rows_holdout"

    df["is_attack"] = (~df[label_col].map(is_benign_label)).astype(int)
    X, y, _ = _build_xy(df, "is_attack", numeric_cols, [])

    X_train, X_val, y_train, y_val = train_test_split(
        X,
        y,
        test_size=val_ratio,
        random_state=random_state,
        stratify=y,
    )
    meta["train_rows"] = int(len(y_train))
    meta["val_rows"] = int(len(y_val))
    meta["train_class_distribution"] = {
        str(k): int(v) for k, v in zip(*np.unique(y_train, return_counts=True))
    }
    meta["val_class_distribution"] = {
        str(k): int(v) for k, v in zip(*np.unique(y_val, return_counts=True))
    }

    clf = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        class_weight="balanced",
        random_state=random_state,
    )
    clf.fit(X_train, y_train)
    y_train_pred = clf.predict(X_train)
    y_val_pred = clf.predict(X_val)

    val_rates = _attack_detection_rates(y_val, y_val_pred)
    train_rates = _attack_detection_rates(y_train, y_train_pred)
    labels_sorted = ["0", "1"]

    report: Dict[str, Any] = {
        "task": "flow_benign_vs_attack_full_holdout",
        "n_samples_total": int(len(y)),
        "n_train": int(len(y_train)),
        "n_val": int(len(y_val)),
        "val_ratio": val_ratio,
        "class_distribution_total": {
            str(k): int(v) for k, v in zip(*np.unique(y, return_counts=True))
        },
        "train_accuracy": float(accuracy_score(y_train, y_train_pred)),
        "val_accuracy": float(accuracy_score(y_val, y_val_pred)),
        "train_attack_detection_rates": train_rates,
        "val_attack_detection_rates": val_rates,
        "val_confusion_matrix": {
            "labels": labels_sorted,
            "matrix": confusion_matrix(y_val, y_val_pred, labels=[0, 1]).tolist(),
        },
        "val_classification_report": classification_report(
            y_val, y_val_pred, zero_division=0, output_dict=True
        ),
        "tree_rules": export_text(
            clf,
            feature_names=list(X.columns),
            max_depth=max_depth,
            spacing=2,
        ),
        "top_feature_importance": [
            {"feature": str(f), "importance": float(v)}
            for f, v in sorted(
                zip(X.columns, clf.feature_importances_.tolist()),
                key=lambda t: t[1],
                reverse=True,
            )
            if v > 1e-9
        ][:30],
    }
    return report, meta


def _print_summary(reports: List[Dict[str, Any]]) -> None:
    for r in reports:
        print("\n" + "=" * 72)
        print(f"Task: {r['task']}")
        if "n_samples" in r:
            print(f"Samples: {r['n_samples']}  class_dist: {r['class_distribution']}")
        elif "n_samples_total" in r:
            print(
                f"Total: {r['n_samples_total']}  train: {r.get('n_train')}  val: {r.get('n_val')}  "
                f"class_dist: {r.get('class_distribution_total')}"
            )
        if r.get("cv_folds", 0) >= 2:
            print(
                f"CV accuracy: {r.get('cv_accuracy_mean'):.4f} ± {r.get('cv_accuracy_std'):.4f}  "
                f"F1_macro: {r.get('cv_f1_macro_mean'):.4f}  "
                f"AUC: {r.get('cv_roc_auc')}"
            )
        print(f"Train accuracy: {r.get('train_accuracy'):.4f}  F1_macro: {r.get('train_f1_macro'):.4f}")
        vr = r.get("val_attack_detection_rates")
        if vr:
            print(
                f"Hold-out val: acc={r.get('val_accuracy'):.4f}  "
                f"FPR={vr.get('fpr'):.4%}  FNR={vr.get('fnr'):.4%}  "
                f"(n_val={r.get('n_val')})"
            )
        tr = r.get("train_attack_detection_rates")
        if tr and vr:
            print(f"Train (in-sample): FPR={tr.get('fpr'):.4%}  FNR={tr.get('fnr'):.4%}")
        print("\nTop features (importance):")
        for row in r.get("top_feature_importance", [])[:12]:
            print(f"  {row['importance']:.4f}  {row['feature']}")
        print("\nDecision rules (truncated):")
        rules = str(r.get("tree_rules", ""))
        lines = rules.splitlines()[:25]
        print("\n".join(lines))
        if len(rules.splitlines()) > 25:
            print("  ...")


def main() -> None:
    p = argparse.ArgumentParser(description="Decision tree traffic / cluster discrimination.")
    p.add_argument("--run-dir", default="", help="Run output directory with learner CSVs")
    p.add_argument("--csv", default="", help="Raw aligned flow CSV (e.g. yeartagged_for_main)")
    p.add_argument("--out-dir", default="", help="Output directory for JSON / rule files")
    p.add_argument("--attack-threshold", type=float, default=0.5)
    p.add_argument("--max-depth", type=int, default=4)
    p.add_argument("--min-samples-leaf", type=int, default=2)
    p.add_argument("--min-label-count", type=int, default=5000, help="Min rows for multiclass label tasks")
    p.add_argument("--sample-per-label", type=int, default=1500, help="Stratified cap per Label (flow CSV)")
    p.add_argument(
        "--feature-profile",
        default="stable_stats_no_env",
        choices=["all_numeric_no_env", "stable_stats_no_env", "compact_stats_no_env"],
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--full-rows",
        action="store_true",
        help="Use all CSV rows with train/val hold-out (benign vs attack only)",
    )
    p.add_argument(
        "--val-ratio",
        type=float,
        default=0.2,
        help="Validation fraction for --full-rows (default 0.2)",
    )
    args = p.parse_args()

    if not args.run_dir and not args.csv:
        p.error("Provide --csv for flow-level analysis or --run-dir for learner-level analysis.")

    if args.csv:
        csv_path = Path(args.csv).resolve()
        if args.full_rows:
            out_dir = (
                Path(args.out_dir).resolve()
                if args.out_dir
                else csv_path.parent / f"{csv_path.stem}_decision_tree_full"
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            full_report, flow_meta = analyze_flow_full_benign_vs_attack(
                csv_path,
                val_ratio=args.val_ratio,
                max_depth=args.max_depth,
                min_samples_leaf=max(args.min_samples_leaf, 100),
                random_state=args.seed,
                feature_profile=args.feature_profile,
            )
            all_reports = [full_report]
            (out_dir / "flow_full_meta.json").write_text(
                json.dumps(flow_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (out_dir / "flow_full_benign_vs_attack_rates.json").write_text(
                json.dumps(
                    {
                        "val": full_report["val_attack_detection_rates"],
                        "train": full_report["train_attack_detection_rates"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        else:
            out_dir = (
                Path(args.out_dir).resolve()
                if args.out_dir
                else csv_path.parent / f"{csv_path.stem}_decision_tree"
            )
            out_dir.mkdir(parents=True, exist_ok=True)
            flow_reports, flow_meta = analyze_flow_csv(
                csv_path,
                sample_per_label=args.sample_per_label,
                max_depth=args.max_depth,
                min_samples_leaf=max(args.min_samples_leaf, 30),
                random_state=args.seed,
                feature_profile=args.feature_profile,
                min_label_count=args.min_label_count,
            )
            all_reports = flow_reports
            (out_dir / "flow_sampling_meta.json").write_text(
                json.dumps(flow_meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    else:
        run_dir = Path(args.run_dir).resolve()
        out_dir = Path(args.out_dir).resolve() if args.out_dir else run_dir / "decision_tree_analysis"
        out_dir.mkdir(parents=True, exist_ok=True)

        learner_df = _load_learner_table(run_dir)
        learner_reports = analyze_learner_level(
            learner_df,
            attack_threshold=args.attack_threshold,
            max_depth=args.max_depth,
            min_samples_leaf=args.min_samples_leaf,
            random_state=args.seed,
        )

        label_reports: List[Dict[str, Any]] = []
        label_csv = run_dir / "dataset_label_distribution.csv"
        if label_csv.exists():
            label_reports = analyze_label_level(
                label_csv,
                max_depth=args.max_depth,
                min_samples_leaf=args.min_samples_leaf,
                random_state=args.seed,
                min_label_count=args.min_label_count,
            )
        all_reports = learner_reports + label_reports

    summary_path = out_dir / "decision_tree_summary.json"
    summary_path.write_text(json.dumps(all_reports, ensure_ascii=False, indent=2), encoding="utf-8")

    for i, r in enumerate(all_reports):
        rules_path = out_dir / f"tree_rules_{i:02d}_{r['task'].replace('/', '_')[:60]}.txt"
        rules_path.write_text(str(r.get("tree_rules", "")), encoding="utf-8")

    _print_summary(all_reports)
    print(f"\n[Wrote] {summary_path}")
    print(f"[Wrote] per-task rule files under {out_dir}")


if __name__ == "__main__":
    main()
