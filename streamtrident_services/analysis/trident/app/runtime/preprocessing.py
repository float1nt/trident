from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from ..flow_loader import FlowRecord


TCP_PROTOCOL_NUMBER = 6
FLOW_BYTES_PER_SEC_COLUMN = "Flow Bytes/s"
FLOW_BYTES_PER_SEC_MISSING_FLAG = "flow_bytes_s_missing_flag"
NON_TCP_FLAG_COLUMN = "is_non_tcp"
MISSING_SENTINEL_TO_ZERO_COLUMNS = {
    "FWD Init Win Bytes": "fwd_init_win_missing_flag",
    "Bwd Init Win Bytes": "bwd_init_win_missing_flag",
}
STABLE_STATS_FEATURES = [
    "Flow Duration",
    "Total Fwd Packet",
    "Total Bwd packets",
    "Total Length of Fwd Packet",
    "Total Length of Bwd Packet",
    "Fwd Packet Length Max",
    "Fwd Packet Length Min",
    "Fwd Packet Length Mean",
    "Fwd Packet Length Std",
    "Bwd Packet Length Max",
    "Bwd Packet Length Min",
    "Bwd Packet Length Mean",
    "Bwd Packet Length Std",
    "Flow Bytes/s",
    "Flow Packets/s",
    "Flow IAT Mean",
    "Flow IAT Std",
    "Flow IAT Max",
    "Flow IAT Min",
    "Fwd IAT Total",
    "Fwd IAT Mean",
    "Fwd IAT Std",
    "Fwd IAT Max",
    "Fwd IAT Min",
    "Bwd IAT Total",
    "Bwd IAT Mean",
    "Bwd IAT Std",
    "Bwd IAT Max",
    "Bwd IAT Min",
    "Fwd Header Length",
    "Bwd Header Length",
    "Fwd Packets/s",
    "Bwd Packets/s",
    "Packet Length Min",
    "Packet Length Max",
    "Packet Length Mean",
    "Packet Length Std",
    "Packet Length Variance",
    "FIN Flag Count",
    "SYN Flag Count",
    "RST Flag Count",
    "PSH Flag Count",
    "ACK Flag Count",
    "URG Flag Count",
    "ECE Flag Count",
    "Down/Up Ratio",
    "Average Packet Size",
    "Fwd Segment Size Avg",
    "Bwd Segment Size Avg",
    "Subflow Fwd Packets",
    "Subflow Fwd Bytes",
    "Subflow Bwd Packets",
    "Subflow Bwd Bytes",
    "FWD Init Win Bytes",
    "Bwd Init Win Bytes",
    "fwd_init_win_missing_flag",
    "bwd_init_win_missing_flag",
    "is_non_tcp",
    "flow_bytes_s_missing_flag",
    "Fwd Act Data Pkts",
    "Fwd Seg Size Min",
    "Active Mean",
    "Active Std",
    "Active Max",
    "Active Min",
    "Idle Mean",
    "Idle Std",
    "Idle Max",
    "Idle Min",
]
COMPACT_STATS_FEATURES = [
    "Flow Duration",
    "Total Fwd Packet",
    "Total Bwd packets",
    "Total Length of Fwd Packet",
    "Total Length of Bwd Packet",
    "Fwd Packet Length Mean",
    "Fwd Packet Length Std",
    "Bwd Packet Length Min",
    "Bwd Packet Length Max",
    "Bwd Packet Length Mean",
    "Bwd Packet Length Std",
    "Flow Bytes/s",
    "Flow Packets/s",
    "Flow IAT Mean",
    "Flow IAT Std",
    "Fwd IAT Mean",
    "Fwd IAT Std",
    "Bwd IAT Mean",
    "Bwd IAT Std",
    "Packet Length Mean",
    "Packet Length Std",
    "SYN Flag Count",
    "ACK Flag Count",
    "PSH Flag Count",
    "Average Packet Size",
    "FWD Init Win Bytes",
    "Bwd Header Length",
    "Fwd Bulk Rate Avg",
    "Bwd Bulk Rate Avg",
    "flow_bytes_s_missing_flag",
    "Active Mean",
    "Active Std",
    "Active Max",
    "Idle Mean",
    "Idle Std",
]


def preprocess_records(
    records: list[FlowRecord],
    *,
    feature_profile: str,
    enabled: bool = True,
    drop_all_zero: bool = False,
) -> tuple[list[FlowRecord], dict[str, Any]]:
    if not enabled:
        return records, {"enabled": False, "rows": len(records)}
    out: list[FlowRecord] = []
    report: dict[str, Any] = {
        "enabled": True,
        "input_rows": len(records),
        "dropped_rows": 0,
        "rules": {},
    }
    for record in records:
        features = _loads(record.features_json)
        features, row_report = _normalize_features(features, protocol=record.protocol, feature_profile=feature_profile)
        for key, value in row_report.items():
            rule = report["rules"].setdefault(key, 0)
            report["rules"][key] = int(rule) + int(value)
        if drop_all_zero and _drop_all_numeric_zero(features):
            report["dropped_rows"] += 1
            continue
        out.append(replace(record, features_json=json.dumps(features, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
    report["output_rows"] = len(out)
    return out, report


def _normalize_features(features: dict[str, Any], *, protocol: int, feature_profile: str) -> tuple[dict[str, float], dict[str, int]]:
    normalized: dict[str, float] = {}
    report: dict[str, int] = {}
    for key, value in features.items():
        number = _to_float(value)
        if number is not None:
            normalized[str(key)] = number
    normalized[NON_TCP_FLAG_COLUMN] = 0.0 if int(protocol) == TCP_PROTOCOL_NUMBER else 1.0
    report[NON_TCP_FLAG_COLUMN] = int(normalized[NON_TCP_FLAG_COLUMN])
    for col, flag_col in MISSING_SENTINEL_TO_ZERO_COLUMNS.items():
        value = normalized.get(col)
        missing = value is None or value == -1.0
        if missing:
            normalized[col] = 0.0
            report[flag_col] = 1
        else:
            report[flag_col] = 0
        normalized[flag_col] = 1.0 if missing else 0.0
    value = normalized.get(FLOW_BYTES_PER_SEC_COLUMN)
    bad = value is None or not _finite(value)
    if bad:
        normalized[FLOW_BYTES_PER_SEC_COLUMN] = 0.0
        report[FLOW_BYTES_PER_SEC_MISSING_FLAG] = 1
    else:
        report[FLOW_BYTES_PER_SEC_MISSING_FLAG] = 0
    normalized[FLOW_BYTES_PER_SEC_MISSING_FLAG] = 1.0 if bad else 0.0
    keep = _feature_profile_columns(feature_profile)
    if keep:
        normalized = {key: normalized.get(key, 0.0) for key in keep}
    return normalized, report


def _feature_profile_columns(feature_profile: str) -> list[str]:
    if feature_profile == "compact_stats_no_env":
        return COMPACT_STATS_FEATURES
    if feature_profile == "stable_stats_no_env":
        return STABLE_STATS_FEATURES
    return []


def _drop_all_numeric_zero(features: dict[str, float]) -> bool:
    if not features:
        return False
    signal_values = [abs(value) for key, value in features.items() if not key.endswith("_missing_flag") and key != NON_TCP_FLAG_COLUMN]
    return bool(signal_values) and all(value == 0.0 for value in signal_values)


def _loads(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if _finite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if _finite(number) else None
    return None


def _finite(value: float) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
