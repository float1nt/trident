from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Any

import yaml


@dataclass(slots=True)
class TridentConfig:
    redis_url: str = "redis://127.0.0.1:6379/0"
    queue_type: str = "list"
    input_stream: str = "suricata:cic_flow"
    consumer_group: str = "trident-online"
    consumer_name: str = "trident-01"
    consumer_mode: str = "best_effort"
    best_effort_start_id: str = "$"
    read_count: int = 512
    block_ms: int = 1000
    ack: bool = True
    list_maxlen: int = 100000
    session_id: str = "trident-session-dev"
    window_size: int = 10000
    feature_profile: str = "compact_stats_no_env"
    clickhouse_dsn: str = "http://127.0.0.1:8123/default"
    postgres_dsn: str = "postgresql://trident:trident@127.0.0.1:5432/trident"
    assignment_stream: str = "trident:assignments"
    alert_stream: str = "trident:alerts"
    metrics_stream: str = "trident:metrics"
    redis_output_enabled: bool = False
    unknown_threshold: float = 0.35
    new_learner_min_size: int = 500
    pending_idle_ms: int = 60000
    process_partial_window: bool = True
    algorithm_backend: str = "ae"
    cpu_only: bool = False
    seed: int = 42
    init_epochs: int = 5
    new_class_epochs: int = 4
    increment_epochs: int = 1
    min_class_samples: int = 300
    max_train_per_class: int = 20000
    max_increment_samples: int = 1000
    increment_min_samples: int = 1000
    tsieve_batch_size: int = 256
    tsieve_lr: float = 0.001
    evt_quantile: float = 0.97
    evt_risk: float = 0.0015
    fallback_quantile: float = 0.99
    cluster_trigger_size: int = 120
    dbscan_eps: float = 1.3
    dbscan_min_samples: int = 10
    max_unknown_buffer: int = 30000
    benign_accept_scale: float = 0.34
    benign_history_confidence_scale: float = 1.0
    cluster_purity_gate_enabled: bool = True
    cluster_gate_max_benign_accept_rate: float = 0.35
    cluster_gate_rejected_action: str = "reinject_unknown"
    increment_drift_gate_enabled: bool = True
    increment_drift_min_score: float = 0.12
    increment_drift_min_history_samples: int = 500
    increment_route_gate_enabled: bool = True
    increment_route_apply_to_new_only: bool = True
    increment_route_min_samples: int = 1000
    increment_route_min_own_margin: float = 0.02
    increment_route_min_margin_gap: float = 0.03
    increment_route_min_confident_ratio: float = 0.55
    increment_iforest_guard_enabled: bool = True
    increment_iforest_guard_apply_to_new_only: bool = True
    increment_iforest_guard_min_samples: int = 1000
    increment_iforest_guard_n_estimators: int = 200
    increment_iforest_guard_train_max_samples: int = 5000
    increment_iforest_guard_keep_quantile: float = 0.90
    increment_sampling_mode: str = "stratified_loss"
    increment_low_loss_quantile_keep: float = 1.0
    history_sample_rate: float = 0.5
    history_samples_per_update: int = 2000
    max_history_samples_per_learner: int = 10000
    history_time_decay_lambda: float = 0.0
    small_learner_recluster_enabled: bool = True
    small_learner_sample_threshold: int = 1000
    small_learner_recluster_count_trigger: int = 10
    model_store_dir: str = "/tmp/trident-model-store"
    preprocessing_enabled: bool = True
    preprocessing_drop_all_zero: bool = False


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_PATTERN.sub(
            lambda match: os.getenv(match.group(1)) or (match.group(2) or ""),
            value,
        )
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def load_config(path: str | Path | None) -> TridentConfig:
    if path is None:
        return TridentConfig()
    payload = _expand_env(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
    if not isinstance(payload, dict):
        raise ValueError(f"config must be a mapping: {path}")
    return TridentConfig(
        redis_url=str(payload.get("redis_url", "redis://127.0.0.1:6379/0")),
        queue_type=str(payload.get("queue_type", "list")).lower(),
        input_stream=str(payload.get("input_stream", "suricata:cic_flow")),
        consumer_group=str(payload.get("consumer_group", "trident-online")),
        consumer_name=str(payload.get("consumer_name", "trident-01")),
        consumer_mode=str(payload.get("consumer_mode", "best_effort")),
        best_effort_start_id=str(payload.get("best_effort_start_id", "$")),
        read_count=int(payload.get("read_count", 512)),
        block_ms=int(payload.get("block_ms", 1000)),
        ack=_bool(payload.get("ack"), True),
        list_maxlen=int(payload.get("list_maxlen", 100000)),
        session_id=str(payload.get("session_id", "trident-session-dev")),
        window_size=int(payload.get("window_size", 10000)),
        feature_profile=str(payload.get("feature_profile", "compact_stats_no_env")),
        clickhouse_dsn=str(payload.get("clickhouse_dsn", "http://127.0.0.1:8123/default")),
        postgres_dsn=str(payload.get("postgres_dsn", "postgresql://trident:trident@127.0.0.1:5432/trident")),
        assignment_stream=str(payload.get("assignment_stream", "trident:assignments")),
        alert_stream=str(payload.get("alert_stream", "trident:alerts")),
        metrics_stream=str(payload.get("metrics_stream", "trident:metrics")),
        redis_output_enabled=_bool(payload.get("redis_output_enabled"), False),
        unknown_threshold=float(payload.get("unknown_threshold", 0.35)),
        new_learner_min_size=int(payload.get("new_learner_min_size", 500)),
        pending_idle_ms=int(payload.get("pending_idle_ms", 60000)),
        process_partial_window=_bool(payload.get("process_partial_window"), True),
        algorithm_backend=str(payload.get("algorithm_backend", "ae")),
        cpu_only=_bool(payload.get("cpu_only"), False),
        seed=int(payload.get("seed", 42)),
        init_epochs=int(payload.get("init_epochs", 5)),
        new_class_epochs=int(payload.get("new_class_epochs", 4)),
        increment_epochs=int(payload.get("increment_epochs", 1)),
        min_class_samples=int(payload.get("min_class_samples", 300)),
        max_train_per_class=int(payload.get("max_train_per_class", 20000)),
        max_increment_samples=int(payload.get("max_increment_samples", 1000)),
        increment_min_samples=int(payload.get("increment_min_samples", 1000)),
        tsieve_batch_size=int(payload.get("tsieve_batch_size", 256)),
        tsieve_lr=float(payload.get("tsieve_lr", 0.001)),
        evt_quantile=float(payload.get("evt_quantile", 0.97)),
        evt_risk=float(payload.get("evt_risk", 0.0015)),
        fallback_quantile=float(payload.get("fallback_quantile", 0.99)),
        cluster_trigger_size=int(payload.get("cluster_trigger_size", 120)),
        dbscan_eps=float(payload.get("dbscan_eps", 1.3)),
        dbscan_min_samples=int(payload.get("dbscan_min_samples", 10)),
        max_unknown_buffer=int(payload.get("max_unknown_buffer", 30000)),
        benign_accept_scale=float(payload.get("benign_accept_scale", 0.34)),
        benign_history_confidence_scale=float(payload.get("benign_history_confidence_scale", 1.0)),
        cluster_purity_gate_enabled=_bool(payload.get("cluster_purity_gate_enabled"), True),
        cluster_gate_max_benign_accept_rate=float(payload.get("cluster_gate_max_benign_accept_rate", 0.35)),
        cluster_gate_rejected_action=str(payload.get("cluster_gate_rejected_action", "reinject_unknown")),
        increment_drift_gate_enabled=_bool(payload.get("increment_drift_gate_enabled"), True),
        increment_drift_min_score=float(payload.get("increment_drift_min_score", 0.12)),
        increment_drift_min_history_samples=int(payload.get("increment_drift_min_history_samples", 500)),
        increment_route_gate_enabled=_bool(payload.get("increment_route_gate_enabled"), True),
        increment_route_apply_to_new_only=_bool(payload.get("increment_route_apply_to_new_only"), True),
        increment_route_min_samples=int(payload.get("increment_route_min_samples", 1000)),
        increment_route_min_own_margin=float(payload.get("increment_route_min_own_margin", 0.02)),
        increment_route_min_margin_gap=float(payload.get("increment_route_min_margin_gap", 0.03)),
        increment_route_min_confident_ratio=float(payload.get("increment_route_min_confident_ratio", 0.55)),
        increment_iforest_guard_enabled=_bool(payload.get("increment_iforest_guard_enabled"), True),
        increment_iforest_guard_apply_to_new_only=_bool(payload.get("increment_iforest_guard_apply_to_new_only"), True),
        increment_iforest_guard_min_samples=int(payload.get("increment_iforest_guard_min_samples", 1000)),
        increment_iforest_guard_n_estimators=int(payload.get("increment_iforest_guard_n_estimators", 200)),
        increment_iforest_guard_train_max_samples=int(payload.get("increment_iforest_guard_train_max_samples", 5000)),
        increment_iforest_guard_keep_quantile=float(payload.get("increment_iforest_guard_keep_quantile", 0.90)),
        increment_sampling_mode=str(payload.get("increment_sampling_mode", "stratified_loss")),
        increment_low_loss_quantile_keep=float(payload.get("increment_low_loss_quantile_keep", 1.0)),
        history_sample_rate=float(payload.get("history_sample_rate", 0.5)),
        history_samples_per_update=int(payload.get("history_samples_per_update", 2000)),
        max_history_samples_per_learner=int(payload.get("max_history_samples_per_learner", 10000)),
        history_time_decay_lambda=float(payload.get("history_time_decay_lambda", 0.0)),
        small_learner_recluster_enabled=_bool(payload.get("small_learner_recluster_enabled"), True),
        small_learner_sample_threshold=int(payload.get("small_learner_sample_threshold", 1000)),
        small_learner_recluster_count_trigger=int(payload.get("small_learner_recluster_count_trigger", 10)),
        model_store_dir=str(payload.get("model_store_dir", "/tmp/trident-model-store")),
        preprocessing_enabled=_bool(payload.get("preprocessing_enabled"), True),
        preprocessing_drop_all_zero=_bool(payload.get("preprocessing_drop_all_zero"), False),
    )
