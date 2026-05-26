from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from trident_demo.lib.utils import normalize_label
from trident_demo.runtime.schema import (
    BENIGN_TYPE_COLUMN,
    COMPACT_STATS_FEATURES,
    ENVIRONMENT_COLUMNS,
    FLOW_BYTES_PER_SEC_COLUMN,
    FLOW_BYTES_PER_SEC_MISSING_FLAG,
    MISSING_SENTINEL_TO_ZERO_COLUMNS,
    NON_TCP_FLAG_COLUMN,
    STABLE_STATS_FEATURES,
    TCP_PROTOCOL_NUMBER,
)


@dataclass
class RuntimePreprocessResult:
    data: pd.DataFrame
    report: Dict[str, Any]


def _runtime_cfg(cfg: Mapping[str, Any]) -> Mapping[str, Any]:
    runtime = cfg.get("runtime", {})
    return runtime if isinstance(runtime, Mapping) else {}


def apply_missing_value_strategy(
    data: pd.DataFrame,
    *,
    enabled: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Apply deployable missing-value rules without experiment sampling."""
    if data.empty or not enabled:
        return data, {"enabled": bool(enabled), "rows": int(len(data)), "rules": {}}

    df = data.copy()
    report: Dict[str, Any] = {
        "enabled": True,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "rules": {},
    }

    if "Protocol" in df.columns:
        proto = pd.to_numeric(df["Protocol"], errors="coerce")
        is_non_tcp = (proto != TCP_PROTOCOL_NUMBER) | proto.isna()
        df[NON_TCP_FLAG_COLUMN] = is_non_tcp.astype(np.int8)
        report["rules"][NON_TCP_FLAG_COLUMN] = {
            "source_column": "Protocol",
            "non_tcp_or_unknown_rows": int(is_non_tcp.sum()),
            "ratio": float(is_non_tcp.mean()),
        }

    for col, flag_col in MISSING_SENTINEL_TO_ZERO_COLUMNS.items():
        if col not in df.columns:
            continue
        s = pd.to_numeric(df[col], errors="coerce")
        sentinel_mask = s == -1
        nan_mask = s.isna()
        missing_mask = sentinel_mask | nan_mask
        df[col] = s.mask(sentinel_mask, 0.0).fillna(0.0)
        df[flag_col] = missing_mask.astype(np.int8)
        report["rules"][col] = {
            "action": "-1->0 and NaN->0",
            "missing_flag_column": flag_col,
            "sentinel_neg1_rows": int(sentinel_mask.sum()),
            "nan_rows": int(nan_mask.sum()),
            "missing_rows": int(missing_mask.sum()),
            "missing_ratio": float(missing_mask.mean()),
        }

    if FLOW_BYTES_PER_SEC_COLUMN in df.columns:
        s = pd.to_numeric(df[FLOW_BYTES_PER_SEC_COLUMN], errors="coerce")
        inf_mask = np.isinf(s.to_numpy(dtype=np.float64))
        inf_series = pd.Series(inf_mask, index=s.index)
        nan_mask = s.isna()
        bad_mask = inf_series | nan_mask
        df[FLOW_BYTES_PER_SEC_COLUMN] = s.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        df[FLOW_BYTES_PER_SEC_MISSING_FLAG] = bad_mask.astype(np.int8)
        report["rules"][FLOW_BYTES_PER_SEC_COLUMN] = {
            "action": "inf/-inf/NaN->0",
            "missing_flag_column": FLOW_BYTES_PER_SEC_MISSING_FLAG,
            "inf_rows": int(inf_series.sum()),
            "nan_rows": int(nan_mask.sum()),
            "missing_rows": int(bad_mask.sum()),
            "missing_ratio": float(bad_mask.mean()),
        }

    if BENIGN_TYPE_COLUMN in df.columns:
        before_nan = int(df[BENIGN_TYPE_COLUMN].isna().sum())
        df[BENIGN_TYPE_COLUMN] = df[BENIGN_TYPE_COLUMN].fillna("UNKNOWN").astype(str)
        report["rules"][BENIGN_TYPE_COLUMN] = {
            "action": "NaN->UNKNOWN",
            "filled_rows": before_nan,
            "filled_ratio": float(before_nan / max(1, len(df))),
        }

    return df, report


def normalize_drop_when_all_numeric_zero_rules(runtime_cfg: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rules = runtime_cfg.get("drop_when_all_numeric_zero_rules")
    if rules is None:
        legacy = runtime_cfg.get("drop_when_all_numeric_zero")
        if isinstance(legacy, Mapping):
            rules = [legacy]
        elif isinstance(legacy, list):
            rules = legacy
        else:
            rules = []
    elif isinstance(rules, Mapping):
        rules = [rules]
    if not isinstance(rules, list):
        return []

    out: List[Dict[str, Any]] = []
    for raw in rules:
        if not isinstance(raw, Mapping):
            continue
        cols = raw.get("columns")
        if isinstance(cols, (list, tuple, set)):
            col_list = [str(c).strip() for c in cols if str(c).strip()]
        elif isinstance(cols, str) and cols.strip():
            col_list = [cols.strip()]
        else:
            col_list = []
        entry = dict(raw)
        entry["columns"] = col_list
        out.append(entry)
    return out


def apply_drop_when_all_numeric_zero_rules(
    data: pd.DataFrame,
    runtime_cfg: Mapping[str, Any],
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    if data.empty:
        return data, {"rules": [], "dropped_rows": 0}
    rules = normalize_drop_when_all_numeric_zero_rules(runtime_cfg)
    if not rules:
        return data, {"rules": [], "dropped_rows": 0}

    drop_mask = pd.Series(False, index=data.index)
    reports: List[Dict[str, Any]] = []
    for rule in rules:
        if not bool(rule.get("enabled", True)):
            continue
        cols = [c for c in rule.get("columns", []) if c]
        missing = [c for c in cols if c not in data.columns]
        if not cols or missing:
            reports.append({"name": rule.get("name", ""), "skipped": True, "missing_columns": missing})
            continue
        eps = float(rule.get("eps", 0.0))
        treat_nan_as_zero = bool(rule.get("treat_nan_as_zero", True))
        mask_all = pd.Series(True, index=data.index)
        for col in cols:
            s = pd.to_numeric(data[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
            if treat_nan_as_zero:
                col_zero = s.fillna(0.0).abs() <= eps
            else:
                col_zero = s.notna() & (s.abs() <= eps)
            mask_all &= col_zero
        drop_mask |= mask_all
        reports.append(
            {
                "name": rule.get("name", ""),
                "columns": cols,
                "matching_rows": int(mask_all.sum()),
                "eps": eps,
                "treat_nan_as_zero": treat_nan_as_zero,
            }
        )

    if not drop_mask.any():
        return data, {"rules": reports, "dropped_rows": 0}
    kept = data.loc[~drop_mask].reset_index(drop=True)
    return kept, {"rules": reports, "dropped_rows": int(len(data) - len(kept))}


def preprocess_runtime_dataframe(
    data: pd.DataFrame,
    cfg: Mapping[str, Any],
    *,
    default_label: str = "0000|UNLABELED",
    apply_max_rows: bool = True,
) -> RuntimePreprocessResult:
    """Runtime-safe dataframe normalization.

    This intentionally excludes experiment-only filters and sampling.
    """
    df = data.copy()
    report: Dict[str, Any] = {"input_rows": int(len(df))}
    if "Label" not in df.columns:
        df["Label"] = default_label
        report["label_defaulted"] = True
    if "Timestamp" not in df.columns:
        base_ts = pd.Timestamp.utcnow()
        df["Timestamp"] = pd.date_range(base_ts, periods=len(df), freq="us")
        report["timestamp_defaulted"] = True

    try:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce", format="mixed")
    except TypeError:
        df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    invalid_ts = int(df["Timestamp"].isna().sum())
    df = df.dropna(subset=["Timestamp"]).sort_values("Timestamp").reset_index(drop=True)
    df["LabelNorm"] = df["Label"].map(normalize_label)
    report["invalid_timestamp_rows"] = invalid_ts

    runtime_cfg = _runtime_cfg(cfg)
    missing_enabled = bool(runtime_cfg.get("missing_value_strategy_enabled", True))
    df, missing_report = apply_missing_value_strategy(df, enabled=missing_enabled)
    df, drop_report = apply_drop_when_all_numeric_zero_rules(df, runtime_cfg)
    report["missing_value_strategy"] = missing_report
    report["drop_when_all_numeric_zero"] = drop_report

    if apply_max_rows:
        max_rows = int(runtime_cfg.get("max_rows", 0) or 0)
        if max_rows > 0 and len(df) > max_rows:
            df = df.iloc[:max_rows].reset_index(drop=True)
            report["max_rows_applied"] = max_rows

    report["output_rows"] = int(len(df))
    return RuntimePreprocessResult(data=df, report=report)


def build_feature_frame(
    df: pd.DataFrame,
    *,
    feature_profile: str = "all_numeric_no_env",
    feature_columns: Optional[List[str]] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    feat_df = df.drop(columns=[c for c in ENVIRONMENT_COLUMNS if c in df.columns], errors="ignore")
    numeric_cols = feat_df.select_dtypes(include=[np.number]).columns.tolist()

    if feature_profile == "stable_stats_no_env":
        keep_cols = [c for c in STABLE_STATS_FEATURES if c in numeric_cols]
        if keep_cols:
            numeric_cols = keep_cols
    elif feature_profile == "compact_stats_no_env":
        keep_cols = [c for c in COMPACT_STATS_FEATURES if c in numeric_cols]
        if keep_cols:
            numeric_cols = keep_cols

    if feature_columns is not None:
        feat_df = feat_df.reindex(columns=feature_columns, fill_value=0.0)
        numeric_cols = list(feature_columns)
    else:
        feat_df = feat_df[numeric_cols]
    feat_df = feat_df.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return feat_df, numeric_cols


def build_feature_matrix(
    df: pd.DataFrame,
    *,
    feature_profile: str = "all_numeric_no_env",
    feature_columns: Optional[List[str]] = None,
) -> Tuple[np.ndarray, List[str]]:
    feat_df, cols = build_feature_frame(
        df,
        feature_profile=feature_profile,
        feature_columns=feature_columns,
    )
    return feat_df.values.astype(np.float32), cols
