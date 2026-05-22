from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import json
from datetime import datetime
from itertools import combinations
from time import perf_counter

import matplotlib

matplotlib.use("Agg")  # headless / nohup: avoid macOS NSApplication crash on plt.figure
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import yaml
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.ensemble import IsolationForest

from .tmagnifier import TMagnifier
from .tscissors import TScissors
from .tsieve import TSieve
from .utils import (
    has_year_prefix,
    infer_year_tag,
    is_benign_label,
    normalize_base_label,
    normalize_label,
    ordered_data_files,
    set_seed,
    split_year_label,
)


ENVIRONMENT_COLUMNS = {
    "id",
    "Flow ID",
    "Src IP",
    "Dst IP",
    "Src Port",
    "Dst Port",
    "Protocol",
    "Timestamp",
    "Label",
    "Attempted Category",
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

IMPORTANT_LEARNER_CLUSTER_FEATURES = [
    "ACK Flag Count",
    "PSH Flag Count",
    "Fwd Packet Length Std",
    "Bwd Header Length",
    "Active Max",
    "Idle Mean",
    # 包/字节统计
    "Total Fwd Packet",  # 前向包数
    "Total Bwd packets", # 后向包数
    "Total Length of Fwd Packet", # 前向总字节数
    "Total Length of Bwd Packet", # 后向总字节数

    # 包长分布
    "Bwd Packet Length Min",
    "FWD Init Win Bytes",
    "Bwd Bulk Rate Avg",
    "Fwd Bulk Rate Avg",
    "Flow IAT Mean",
    "Bwd Packet Length Mean",
    "Bwd Packet Length Max",
]

LEARNER_CREATION_PREVIEW_FLOW_COUNT = 10

TCP_PROTOCOL_NUMBER = 6
UDP_PROTOCOL_NUMBER = 17
LEARNER_GLOBAL_TIME_BINS = 256
MISSING_SENTINEL_TO_ZERO_COLUMNS = {
    "FWD Init Win Bytes": "fwd_init_win_missing_flag",
    "Bwd Init Win Bytes": "bwd_init_win_missing_flag",
}
FLOW_BYTES_PER_SEC_COLUMN = "Flow Bytes/s"
FLOW_BYTES_PER_SEC_MISSING_FLAG = "flow_bytes_s_missing_flag"
NON_TCP_FLAG_COLUMN = "is_non_tcp"
BENIGN_TYPE_COLUMN = "benign_type"


def preprocess_features(df: pd.DataFrame, feature_profile: str = "all_numeric_no_env") -> Tuple[pd.DataFrame, List[str]]:
    """
    Feature profile presets:
      - all_numeric_no_env: all numeric columns excluding environment/leakage fields.
      - stable_stats_no_env: curated CIC stable statistical features (numeric only), no env fields.
      - compact_stats_no_env: smaller robust subset for stronger regularization.
    """
    drop_cols = [c for c in ENVIRONMENT_COLUMNS if c in df.columns]
    feat_df = df.drop(columns=drop_cols, errors="ignore")
    numeric_cols = feat_df.select_dtypes(include=[np.number]).columns.tolist()

    if feature_profile == "stable_stats_no_env":
        keep_cols = [c for c in STABLE_STATS_FEATURES if c in numeric_cols]
        if keep_cols:
            numeric_cols = keep_cols
    elif feature_profile == "compact_stats_no_env":
        keep_cols = [c for c in COMPACT_STATS_FEATURES if c in numeric_cols]
        if keep_cols:
            numeric_cols = keep_cols

    feat_df = feat_df[numeric_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return feat_df, numeric_cols


class TridentStreamingExperiment:
    def __init__(self, cfg: Dict, logger):
        self.cfg = cfg
        self.logger = logger
        set_seed(cfg["runtime"]["seed"])

        self.output_dir = Path(cfg["paths"]["output_dir"]).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

        cpu_only = cfg["runtime"]["cpu_only"]
        self.device = torch.device("cuda" if torch.cuda.is_available() and not cpu_only else "cpu")
        self.logger.info("Device: %s", self.device)

        self.tscissors = TScissors(**cfg["tscissors"])
        self.tsieve = TSieve(
            device=self.device,
            tscissors=self.tscissors,
            batch_size=cfg["tsieve"]["batch_size"],
            lr=cfg["tsieve"]["lr"],
            min_class_samples=cfg["tsieve"]["min_class_samples"],
            max_train_per_class=cfg["tsieve"]["max_train_per_class"],
            benign_accept_scale=cfg["runtime"].get("benign_accept_scale", 1.0),
            prefer_non_benign_first=cfg["runtime"].get("prefer_non_benign_first", True),
            classifier_backend=cfg["tsieve"].get("classifier_backend", "ae"),
            iforest_n_estimators=cfg["tsieve"].get("iforest_n_estimators", 200),
            seed=cfg["runtime"]["seed"],
            use_name_based_benign_logic=cfg["runtime"].get("use_name_based_benign_logic", False),
            uniform_learner_treatment=cfg["runtime"].get("uniform_learner_treatment", False),
        )
        tm_cfg = cfg.get("tmagnifier", {})
        self.tmagnifier = TMagnifier(
            cluster_trigger_size=int(tm_cfg["cluster_trigger_size"]),
            max_unknown_buffer=int(tm_cfg["max_unknown_buffer"]),
            dbscan_eps=float(tm_cfg["dbscan_eps"]),
            dbscan_min_samples=int(tm_cfg["dbscan_min_samples"]),
            new_class_min_size=int(tm_cfg["new_class_min_size"]),
        )
        self.cluster_purity_gate_enabled = bool(tm_cfg.get("cluster_purity_gate_enabled", False))
        self.cluster_gate_max_benign_accept_rate = float(
            tm_cfg.get("cluster_gate_max_benign_accept_rate", 1.0)
        )
        self.cluster_gate_max_benign_prob_mean = float(
            tm_cfg.get("cluster_gate_max_benign_prob_mean", 1.0)
        )
        self.cluster_gate_max_benign_prob_p90 = float(
            tm_cfg.get("cluster_gate_max_benign_prob_p90", 1.0)
        )
        self.cluster_gate_soft_k = float(tm_cfg.get("cluster_gate_soft_k", 4.0))
        self.cluster_gate_mixed_check_enabled = bool(
            tm_cfg.get("cluster_gate_mixed_check_enabled", False)
        )
        # If enabled, reject clusters with very broad BENIGN-probability band:
        # p10 < low and p90 > high -> likely mixed cluster.
        self.cluster_gate_mixed_prob_low = float(tm_cfg.get("cluster_gate_mixed_prob_low", 0.2))
        self.cluster_gate_mixed_prob_high = float(tm_cfg.get("cluster_gate_mixed_prob_high", 0.8))
        # Structure-based mixed-cluster gate (label-free):
        # if a cluster can be cleanly split into two sizeable sub-clusters, treat it as mixed.
        self.cluster_gate_structure_check_enabled = bool(
            tm_cfg.get("cluster_gate_structure_check_enabled", False)
        )
        self.cluster_gate_structure_min_samples = int(
            tm_cfg.get("cluster_gate_structure_min_samples", 600)
        )
        self.cluster_gate_structure_min_child_ratio = float(
            tm_cfg.get("cluster_gate_structure_min_child_ratio", 0.20)
        )
        self.cluster_gate_structure_min_silhouette = float(
            tm_cfg.get("cluster_gate_structure_min_silhouette", 0.18)
        )
        self.cluster_gate_structure_min_split_gain = float(
            tm_cfg.get("cluster_gate_structure_min_split_gain", 0.45)
        )
        # Route-consistency mixed gate (label-free):
        # if samples in one candidate cluster are routed to many existing learners
        # with high multi-accept ratio, treat as mixed and reject.
        self.cluster_gate_route_consistency_enabled = bool(
            tm_cfg.get("cluster_gate_route_consistency_enabled", False)
        )
        self.cluster_gate_route_min_samples = int(
            tm_cfg.get("cluster_gate_route_min_samples", 500)
        )
        self.cluster_gate_route_min_multi_accept_ratio = float(
            tm_cfg.get("cluster_gate_route_min_multi_accept_ratio", 0.30)
        )
        self.cluster_gate_route_max_top1_share = float(
            tm_cfg.get("cluster_gate_route_max_top1_share", 0.70)
        )
        self.cluster_gate_rejected_action = str(
            tm_cfg.get(
                "cluster_gate_rejected_action",
                "reinject_unknown"
                if bool(tm_cfg.get("cluster_gate_return_rejected_to_unknown", True))
                else "drop",
            )
        ).strip().lower()
        if self.cluster_gate_rejected_action not in {"reinject_unknown", "drop"}:
            self.cluster_gate_rejected_action = "reinject_unknown"
        self.cluster_gate_stats: Dict[str, float] = {
            "cluster_gate_checked_count": 0.0,
            "cluster_gate_pass_count": 0.0,
            "cluster_gate_reject_count": 0.0,
            "cluster_gate_reinject_unknown_samples": 0.0,
            "cluster_gate_drop_samples": 0.0,
        }
        self.next_new_id = 1
        self.learner_creation_profiles: List[Dict[str, object]] = []
        self.learner_train_batch_profiles: List[Dict[str, object]] = []
        self.learner_update_loss_profiles: List[Dict[str, object]] = []
        self.learner_fit_loss_profiles: List[Dict[str, object]] = []
        self.learner_creation_sample_count: Dict[str, int] = {}
        self.learner_cumulative_counts: Dict[str, Dict[str, int]] = {}
        self.learner_assigned_feature_chunks: Dict[str, List[np.ndarray]] = {}
        self.learner_assigned_label_chunks: Dict[str, List[np.ndarray]] = {}
        self.freeze_benign_incremental = bool(cfg["runtime"].get("freeze_benign_incremental", False))
        self.run_id = str(cfg["runtime"].get("run_id", datetime.now().strftime("%Y%m%d_%H%M%S")))
        self.history_sample_rate = float(cfg["tsieve"].get("historical_sample_rate", 0.5))
        self.max_history_samples_per_learner = int(cfg["tsieve"].get("max_history_samples_per_learner", 10000))
        self.history_pool_compress_enabled = bool(
            cfg["tsieve"].get("history_pool_compress_enabled", True)
        )
        self.history_samples_per_update = int(cfg["tsieve"].get("history_samples_per_update", 2000))
        self.history_time_decay_lambda = float(cfg["tsieve"].get("history_time_decay_lambda", 0.0))
        self.benign_history_confidence_scale = float(cfg["tsieve"].get("benign_history_confidence_scale", 0.6))
        self.increment_sampling_mode = str(cfg["tsieve"].get("increment_sampling_mode", "random")).strip().lower()
        self.increment_low_loss_quantile_keep = float(cfg["tsieve"].get("increment_low_loss_quantile_keep", 1.0))
        self.increment_gate_enabled = bool(cfg["tsieve"].get("increment_gate_enabled", False))
        self.increment_gate_min_benign_prob_mean = float(
            cfg["tsieve"].get("increment_gate_min_benign_prob_mean", 0.02)
        )
        self.increment_gate_max_own_exceed_rate = float(
            cfg["tsieve"].get("increment_gate_max_own_exceed_rate", 0.90)
        )
        # Increment trigger mode:
        # if enabled, trigger by row-index gap from last training event instead of per-window sample count.
        self.increment_use_last_train_gap = bool(
            cfg["tsieve"].get("increment_use_last_train_gap", False)
        )
        # 0 means unlimited; >0 caps per-learner incremental retraining count.
        self.max_retrain_per_learner = int(cfg["tsieve"].get("max_retrain_per_learner", 0))
        # Retrain only when feature drift is detected between new samples and learner history.
        self.increment_drift_gate_enabled = bool(
            cfg["tsieve"].get("increment_drift_gate_enabled", False)
        )
        self.increment_drift_min_score = float(
            cfg["tsieve"].get("increment_drift_min_score", 0.12)
        )
        self.increment_drift_min_history_samples = int(
            cfg["tsieve"].get("increment_drift_min_history_samples", 500)
        )
        # Incremental route-consistency gate (label-free) for anti-pollution updates.
        self.increment_route_gate_enabled = bool(cfg["tsieve"].get("increment_route_gate_enabled", False))
        self.increment_route_apply_to_new_only = bool(
            cfg["tsieve"].get("increment_route_apply_to_new_only", True)
        )
        self.increment_route_min_samples = int(cfg["tsieve"].get("increment_route_min_samples", 300))
        self.increment_route_min_own_margin = float(
            cfg["tsieve"].get("increment_route_min_own_margin", 0.02)
        )
        self.increment_route_min_margin_gap = float(
            cfg["tsieve"].get("increment_route_min_margin_gap", 0.03)
        )
        self.increment_route_min_confident_ratio = float(
            cfg["tsieve"].get("increment_route_min_confident_ratio", 0.55)
        )
        # IsolationForest guard for NEW learner incremental anti-pollution.
        self.increment_iforest_guard_enabled = bool(
            cfg["tsieve"].get("increment_iforest_guard_enabled", False)
        )
        self.increment_iforest_guard_apply_to_new_only = bool(
            cfg["tsieve"].get("increment_iforest_guard_apply_to_new_only", True)
        )
        self.increment_iforest_guard_min_samples = int(
            cfg["tsieve"].get("increment_iforest_guard_min_samples", 300)
        )
        self.increment_iforest_guard_n_estimators = int(
            cfg["tsieve"].get("increment_iforest_guard_n_estimators", 200)
        )
        self.increment_iforest_guard_train_max_samples = int(
            cfg["tsieve"].get("increment_iforest_guard_train_max_samples", 5000)
        )
        self.increment_iforest_guard_keep_quantile = float(
            cfg["tsieve"].get("increment_iforest_guard_keep_quantile", 0.90)
        )
        self.threshold_refresh_use_anchor = bool(cfg["tsieve"].get("threshold_refresh_use_anchor", False))
        self.threshold_refresh_new_ratio = float(cfg["tsieve"].get("threshold_refresh_new_ratio", 0.2))
        self.new_learner_cooldown_windows = int(cfg["tsieve"].get("new_learner_cooldown_windows", 0))
        self.small_learner_recluster_enabled = bool(
            cfg["tsieve"].get("small_learner_recluster_enabled", True)
        )
        self.small_learner_sample_threshold = int(
            cfg["tsieve"].get("small_learner_sample_threshold", 1000)
        )
        self.small_learner_recluster_count_trigger = int(
            cfg["tsieve"].get("small_learner_recluster_count_trigger", 10)
        )
        self.learner_history_pool: Dict[str, np.ndarray] = {}
        self.increment_iforest_guards: Dict[str, Dict[str, object]] = {}
        self.learner_last_trained_row_index: Dict[str, int] = {}
        self.learner_retrain_counts: Dict[str, int] = {}
        self.learner_birth_window: Dict[str, int] = {}
        self.benign_anchor_learners: set[str] = set()
        self.uniform_learner_treatment = bool(cfg["runtime"].get("uniform_learner_treatment", False))
        self.sample_assignments: List[Dict[str, object]] = []
        self._learner_creation_flow_previews: List[Dict[str, Any]] = []
        # Row indices of samples used when each learner was created (init or NEW_*).
        # Profile aggregates = these ∪ rows whose stream ``pred`` is that learner.
        self._learner_creation_row_indices: Dict[str, Set[int]] = {}
        self.learner_accept_trace: List[Dict[str, object]] = []
        self.feature_profile = str(cfg.get("runtime", {}).get("feature_profile", "all_numeric_no_env"))
        self.pca_n_components = int(cfg.get("runtime", {}).get("pca_n_components", 0))
        self.missing_value_strategy_enabled = bool(
            cfg.get("runtime", {}).get("missing_value_strategy_enabled", True)
        )
        self.missing_value_report_enabled = bool(
            cfg.get("runtime", {}).get("missing_value_report_enabled", True)
        )
        self.missing_value_report_path = self.output_dir / "missing_value_strategy_report.json"
        self.debug_overlap_enabled = bool(cfg["runtime"].get("debug_overlap_enabled", False))
        self.debug_overlap_accept_count: Dict[str, int] = {}
        self.debug_overlap_pair_intersections: Dict[Tuple[str, str], int] = {}
        self.debug_overlap_stream_samples: int = 0
        self.aggregate_overlap_enabled = bool(cfg["runtime"].get("aggregate_overlap_enabled", False))
        self.aggregate_min_jaccard = float(
            cfg["runtime"].get(
                "aggregate_min_jaccard",
                cfg["runtime"].get("debug_overlap_min_jaccard", 0.10),
            )
        )
        self.aggregate_top_k_edges = int(
            cfg["runtime"].get(
                "aggregate_top_k_edges",
                cfg["runtime"].get("debug_overlap_top_k_edges", 80),
            )
        )
        self.aggregate_max_edges = int(
            cfg["runtime"].get(
                "aggregate_max_edges",
                cfg["runtime"].get("debug_overlap_max_edges", 80),
            )
        )
        # overlap graph aggregation strategy:
        # - connected_components: legacy behavior
        # - mutual_knn_components: keep mutual top-k neighbors, then connected components
        self.aggregate_graph_algo = str(cfg["runtime"].get("aggregate_graph_algo", "connected_components"))
        self.aggregate_mutual_top_k = int(cfg["runtime"].get("aggregate_mutual_top_k", 3))
        self.aggregate_init_benign_label = str(
            cfg["runtime"].get(
                "aggregate_init_benign_label",
                f"{str(cfg['stream'].get('init_benign_year', '2017'))}|BENIGN",
            )
        )
        self.aggregate_init_benign_ratio_threshold = float(
            cfg["runtime"].get("aggregate_init_benign_ratio_threshold", 0.50)
        )
        self.risk_soft_k = float(cfg["runtime"].get("risk_soft_k", 4.0))
        self.perf_stats: Dict[str, float] = {
            "detect_seconds_total": 0.0,
            "cluster_seconds_total": 0.0,
            "create_learner_seconds_total": 0.0,
            "retrain_seconds_total": 0.0,
            "init_create_learner_seconds_total": 0.0,
            "window_total_seconds_total": 0.0,
            "windows_count": 0.0,
            "new_learner_count": 0.0,
            "incremental_update_count": 0.0,
        }

    def _log_hyperparameters(self) -> None:
        self.logger.info("[RunID] %s", self.run_id)
        self.logger.info(
            "[HyperParams] %s",
            json.dumps(self.cfg, ensure_ascii=False, sort_keys=True),
        )
        config_snapshot_path = self.output_dir / "config_snapshot.yaml"
        with open(config_snapshot_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.cfg, f, allow_unicode=True, sort_keys=False)
        self.logger.info("[ConfigSnapshot] %s", config_snapshot_path)

    def _apply_missing_value_strategy(self, data: pd.DataFrame) -> pd.DataFrame:
        if data.empty or not self.missing_value_strategy_enabled:
            return data

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
            cleaned = s.mask(sentinel_mask, 0.0).fillna(0.0)
            df[col] = cleaned
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

        if self.missing_value_report_enabled:
            with open(self.missing_value_report_path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            self.logger.info("[MissingValueStrategy] report=%s", self.missing_value_report_path)

        if MISSING_SENTINEL_TO_ZERO_COLUMNS["FWD Init Win Bytes"] in df.columns:
            fwd_missing = float(df[MISSING_SENTINEL_TO_ZERO_COLUMNS["FWD Init Win Bytes"]].mean())
            self.logger.info("[MissingValueStrategy] fwd_init_missing_ratio=%.4f", fwd_missing)
        if MISSING_SENTINEL_TO_ZERO_COLUMNS["Bwd Init Win Bytes"] in df.columns:
            bwd_missing = float(df[MISSING_SENTINEL_TO_ZERO_COLUMNS["Bwd Init Win Bytes"]].mean())
            self.logger.info("[MissingValueStrategy] bwd_init_missing_ratio=%.4f", bwd_missing)
        if FLOW_BYTES_PER_SEC_MISSING_FLAG in df.columns:
            flow_bad = float(df[FLOW_BYTES_PER_SEC_MISSING_FLAG].mean())
            self.logger.info("[MissingValueStrategy] flow_bytes_s_missing_ratio=%.4f", flow_bad)

        return df

    @staticmethod
    def _normalize_drop_when_all_numeric_zero_rules(runtime_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Support ``drop_when_all_numeric_zero_rules`` list plus legacy single-object form."""
        rules = runtime_cfg.get("drop_when_all_numeric_zero_rules")
        if rules is None:
            legacy = runtime_cfg.get("drop_when_all_numeric_zero")
            if isinstance(legacy, dict):
                rules = [legacy]
            elif isinstance(legacy, list):
                rules = legacy
            else:
                rules = []
        elif isinstance(rules, dict):
            rules = [rules]
        if not isinstance(rules, list):
            return []
        out: List[Dict[str, Any]] = []
        for raw in rules:
            if raw is None or not isinstance(raw, dict):
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

    def _apply_drop_when_all_numeric_zero_rules(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        For each enabled rule: drop rows where ALL listed numeric columns read as zero.

        If multiple rules are enabled, a row is dropped when it matches ANY rule (OR across rules).
        Each rule is an AND over its ``columns``.

        Per-rule keys: ``enabled`` (default True), ``columns``, ``eps`` (default 0.0),
        ``treat_nan_as_zero`` (default True), optional ``name`` for logs.
        """
        if data.empty:
            return data
        runtime_cfg = self.cfg.get("runtime", {}) if isinstance(self.cfg.get("runtime"), dict) else {}
        rules = self._normalize_drop_when_all_numeric_zero_rules(runtime_cfg)
        if not rules:
            return data

        drop_mask = pd.Series(False, index=data.index)
        applied = 0
        for rule in rules:
            if not bool(rule.get("enabled", True)):
                continue
            cols = [c for c in rule.get("columns", []) if c]
            if not cols:
                continue
            missing = [c for c in cols if c not in data.columns]
            if missing:
                self.logger.warning(
                    "[DropWhenAllNumericZero] skip rule name=%r (missing columns=%s) need=%s",
                    rule.get("name", ""),
                    missing,
                    cols,
                )
                continue
            eps = float(rule.get("eps", 0.0))
            treat_nan_as_zero = bool(rule.get("treat_nan_as_zero", True))

            mask_all = pd.Series(True, index=data.index)
            for c in cols:
                s = pd.to_numeric(data[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
                if treat_nan_as_zero:
                    s = s.fillna(0.0)
                    col_zero = s.abs() <= eps
                else:
                    col_zero = s.notna() & (s.abs() <= eps)
                mask_all &= col_zero

            n_hit = int(mask_all.sum())
            drop_mask |= mask_all
            applied += 1
            self.logger.info(
                "[DropWhenAllNumericZero] name=%r cols=%s matching_rows=%d eps=%.6f treat_nan_as_zero=%s",
                rule.get("name", ""),
                cols,
                n_hit,
                eps,
                treat_nan_as_zero,
            )

        if not drop_mask.any():
            if applied:
                self.logger.info("[DropWhenAllNumericZero] no rows dropped (rules applied=%d)", applied)
            return data

        before = int(len(data))
        kept = data.loc[~drop_mask].reset_index(drop=True)
        after = int(len(kept))
        self.logger.info(
            "[DropWhenAllNumericZero] dropped=%d kept=%d (before=%d)",
            before - after,
            after,
            before,
        )
        return kept

    def _label_distribution(self, labels: np.ndarray) -> Dict[str, int]:
        if len(labels) == 0:
            return {}
        series = pd.Series(labels.astype(str))
        counts = series.value_counts().sort_values(ascending=False)
        return {str(k): int(v) for k, v in counts.items()}

    def _build_dataset_label_distribution_rows(self, data: pd.DataFrame) -> List[Dict[str, object]]:
        if data.empty or "LabelNorm" not in data.columns:
            return []
        label_series = data["LabelNorm"].astype(str)
        counts = label_series.value_counts().sort_values(ascending=False)
        total = int(len(label_series))
        rows: List[Dict[str, object]] = []
        for label, count in counts.items():
            label_s = str(label)
            year_tag, base_label = split_year_label(label_s)
            rows.append(
                {
                    "label": label_s,
                    "count": int(count),
                    "ratio": float(self._safe_div(int(count), total)),
                    "is_benign": bool(is_benign_label(label_s)),
                    "year_tag": str(year_tag),
                    "base_label": str(base_label),
                }
            )
        return rows

    def _build_dataset_label_feature_stats_df(
        self,
        data: pd.DataFrame,
        feature_names: List[str],
    ) -> pd.DataFrame:
        if data.empty or "LabelNorm" not in data.columns:
            return pd.DataFrame(columns=["label"])
        cols = [str(c) for c in feature_names if str(c) in data.columns]
        if not cols:
            return pd.DataFrame(columns=["label"])
        df = data[["LabelNorm", *cols]].copy()
        df["LabelNorm"] = df["LabelNorm"].astype(str)
        for c in cols:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.replace([np.inf, -np.inf], np.nan)
        agg_spec = {c: ["mean", "std"] for c in cols}
        grouped = df.groupby("LabelNorm", dropna=False).agg(agg_spec)
        grouped.columns = [f"{name}__{stat}" for name, stat in grouped.columns]
        grouped = grouped.reset_index().rename(columns={"LabelNorm": "label"})
        for c in cols:
            mean_col = f"{c}__mean"
            std_col = f"{c}__std"
            cv_col = f"{c}__cv"
            if mean_col not in grouped.columns or std_col not in grouped.columns:
                continue
            denom = pd.to_numeric(grouped[mean_col], errors="coerce").abs().replace(0.0, np.nan)
            std_vals = pd.to_numeric(grouped[std_col], errors="coerce").abs()
            grouped[cv_col] = (std_vals / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        grouped = grouped.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return grouped

    def _build_dataset_label_protocol_stats_df(self, data: pd.DataFrame) -> pd.DataFrame:
        if data.empty or "LabelNorm" not in data.columns or "Protocol" not in data.columns:
            return pd.DataFrame(columns=["label"])
        df = data[["LabelNorm", "Protocol"]].copy()
        df["LabelNorm"] = df["LabelNorm"].astype(str)
        df["Protocol"] = pd.to_numeric(df["Protocol"], errors="coerce")
        rows: List[Dict[str, object]] = []
        for label, g in df.groupby("LabelNorm", dropna=False):
            proto = pd.to_numeric(g["Protocol"], errors="coerce").dropna()
            total = int(len(proto))
            if total <= 0:
                rows.append(
                    {
                        "label": str(label),
                        "protocol_tcp_ratio": 0.0,
                        "protocol_udp_ratio": 0.0,
                        "protocol_other_ratio": 0.0,
                        "protocol_concentration": 0.0,
                        "protocol_cluster_type": "UNKNOWN",
                    }
                )
                continue
            p_int = proto.round().astype(int)
            tcp = int((p_int == TCP_PROTOCOL_NUMBER).sum())
            udp = int((p_int == UDP_PROTOCOL_NUMBER).sum())
            other = int(max(total - tcp - udp, 0))
            tcp_ratio = float(tcp / total)
            udp_ratio = float(udp / total)
            other_ratio = float(other / total)
            concentration = float(max(tcp_ratio, udp_ratio))
            if tcp_ratio >= 0.8:
                cluster_type = "TCP_CLUSTER"
            elif udp_ratio >= 0.8:
                cluster_type = "UDP_CLUSTER"
            elif concentration >= 0.6:
                cluster_type = "TCP_UDP_BIASED"
            else:
                cluster_type = "MIXED"
            rows.append(
                {
                    "label": str(label),
                    "protocol_tcp_ratio": tcp_ratio,
                    "protocol_udp_ratio": udp_ratio,
                    "protocol_other_ratio": other_ratio,
                    "protocol_concentration": concentration,
                    "protocol_cluster_type": cluster_type,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _build_dataset_label_feature_correlation_rows(
        dataset_label_profile_df: pd.DataFrame,
    ) -> List[Dict[str, float | str]]:
        if dataset_label_profile_df.empty or "is_benign" not in dataset_label_profile_df.columns:
            return []
        y = (~dataset_label_profile_df["is_benign"].astype(bool)).astype(int)
        rows: List[Dict[str, float | str]] = []
        for col in dataset_label_profile_df.columns:
            if col in {
                "label",
                "is_benign",
                "year_tag",
                "base_label",
                "protocol_cluster_type",
            }:
                continue
            x = pd.to_numeric(dataset_label_profile_df[col], errors="coerce")
            if x.notna().sum() < 2:
                continue
            if float(x.max() - x.min()) == 0.0:
                continue
            pearson = x.corr(y, method="pearson")
            spearman = x.corr(y, method="spearman")
            if not np.isfinite(float(pearson)) and not np.isfinite(float(spearman)):
                continue
            rows.append(
                {
                    "feature": str(col),
                    "pearson_corr": float(pearson) if np.isfinite(float(pearson)) else 0.0,
                    "spearman_corr": float(spearman) if np.isfinite(float(spearman)) else 0.0,
                    "abs_pearson_corr": abs(float(pearson)) if np.isfinite(float(pearson)) else 0.0,
                    "abs_spearman_corr": abs(float(spearman)) if np.isfinite(float(spearman)) else 0.0,
                }
            )
        rows = sorted(
            rows,
            key=lambda r: (
                float(r.get("abs_pearson_corr", 0.0)),
                float(r.get("abs_spearman_corr", 0.0)),
            ),
            reverse=True,
        )
        return rows

    @staticmethod
    def _save_dataset_label_feature_correlation_figure(
        rows: List[Dict[str, float | str]],
        out_path: Path,
        top_k: int = 24,
    ) -> None:
        if not rows:
            return
        top = rows[: max(1, int(top_k))]
        labels = [str(r["feature"]) for r in top][::-1]
        values = [float(r["pearson_corr"]) for r in top][::-1]
        colors = ["#dc2626" if v > 0 else "#16a34a" for v in values]
        plt.figure(figsize=(12, 9))
        plt.barh(labels, values, color=colors, alpha=0.9)
        plt.axvline(0.0, color="#64748b", linewidth=1.0)
        plt.xlim(-1.0, 1.0)
        plt.xlabel("Pearson correlation with attack_label(1=attack)")
        plt.ylabel("Label-level feature")
        plt.title("Top label-level feature correlations")
        plt.tight_layout()
        plt.savefig(out_path, dpi=180)
        plt.close()

    def _log_learner_distribution(self, stage: str, learner_name: str, labels: np.ndarray) -> None:
        dist = self._label_distribution(labels)
        total = int(len(labels))
        if stage in {"init", "new"}:
            # Record one-time creation sample count per learner.
            self.learner_creation_sample_count.setdefault(learner_name, total)
        self.learner_creation_profiles.append(
            {
                "stage": stage,
                "learner_name": learner_name,
                "sample_count": total,
                "label_distribution_json": json.dumps(dist, ensure_ascii=False),
            }
        )
        self.logger.info(
            "[LearnerDist][%s] learner=%s, samples=%d, label_distribution=%s",
            stage,
            learner_name,
            total,
            dist,
        )

    @staticmethod
    def _format_stream_timestamp(value: Any) -> str:
        """Emit fixed microsecond precision so assignment CSV parses reliably."""
        ts = pd.Timestamp(value)
        if bool(pd.isna(ts)):
            return ""
        return ts.strftime("%Y-%m-%d %H:%M:%S.%f")

    @staticmethod
    def _json_scalar(value: Any) -> Any:
        if value is None or isinstance(value, (bool, str)):
            return value
        if isinstance(value, pd.Timestamp):
            return value.isoformat()
        try:
            if pd.isna(value):
                return None
        except TypeError:
            pass
        except ValueError:
            pass
        if isinstance(value, (np.integer,)):
            return int(value)
        if isinstance(value, (np.floating,)):
            x = float(value)
            if np.isnan(x) or np.isinf(x):
                return None
            return x
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            x = float(value)
            if np.isnan(x) or np.isinf(x):
                return None
            if isinstance(value, int):
                return int(value)
            return float(value)
        return value

    def _flow_preview_record(self, data: pd.DataFrame, row_index: int) -> Dict[str, Any]:
        row = data.iloc[int(row_index)]
        rec: Dict[str, Any] = {"row_index": int(row_index)}
        for col in ("Timestamp", "Protocol", "LabelNorm", "Flow Duration"):
            if col in data.columns:
                rec[str(col)] = self._json_scalar(row[col])
        for col in IMPORTANT_LEARNER_CLUSTER_FEATURES:
            if col in data.columns:
                rec[str(col)] = self._json_scalar(row[col])
        return rec

    def _register_learner_creation_row_indices_from_metas(
        self,
        learner_name: str,
        cluster_metas: List[Dict[str, Any]],
        *,
        data_len: int,
    ) -> None:
        if data_len <= 0:
            return
        bn = str(learner_name)
        bucket = self._learner_creation_row_indices.setdefault(bn, set())
        for meta in cluster_metas:
            if not isinstance(meta, dict):
                continue
            ri = meta.get("row_index")
            try:
                row_i = int(ri) if ri is not None else -1
            except (TypeError, ValueError):
                row_i = -1
            if 0 <= row_i < int(data_len):
                bucket.add(row_i)

    def _register_learner_creation_row_indices(
        self, learner_name: str, row_indices: Any, *, data_len: int
    ) -> None:
        if data_len <= 0:
            return
        bn = str(learner_name)
        bucket = self._learner_creation_row_indices.setdefault(bn, set())
        flat = np.asarray(row_indices, dtype=np.int64).ravel()
        for ri in flat:
            row_i = int(ri)
            if 0 <= row_i < int(data_len):
                bucket.add(row_i)

    def _record_learner_creation_flow_preview(
        self,
        *,
        data: pd.DataFrame,
        learner_name: str,
        creation_source: str,
        window_left: int,
        window_right: int,
        cluster_size: int,
        cluster_metas: List[Dict[str, Any]],
        cluster_labels: np.ndarray,
        binding_metas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        bind_src = binding_metas if binding_metas is not None else cluster_metas
        self._register_learner_creation_row_indices_from_metas(
            learner_name,
            bind_src,
            data_len=int(len(data)),
        )
        flows: List[Dict[str, Any]] = []
        seen_rows: set = set()
        max_n = int(LEARNER_CREATION_PREVIEW_FLOW_COUNT)
        for i, meta in enumerate(cluster_metas):
            if len(flows) >= max_n:
                break
            raw_ri = meta.get("row_index") if isinstance(meta, dict) else None
            try:
                ri = int(raw_ri) if raw_ri is not None else -1
            except (TypeError, ValueError):
                ri = -1
            lbl = ""
            try:
                lbl = str(cluster_labels[i])
            except Exception:
                lbl = ""
            if ri < 0:
                flows.append(
                    {
                        "row_index": raw_ri,
                        "cluster_position": int(i),
                        "cluster_label_norm": lbl,
                        "meta": meta,
                        "note": "missing_row_binding",
                    }
                )
                continue
            if ri in seen_rows:
                continue
            if 0 <= ri < len(data):
                flows.append(self._flow_preview_record(data, ri))
                seen_rows.add(ri)
            else:
                flows.append(
                    {
                        "row_index": int(ri),
                        "cluster_position": int(i),
                        "cluster_label_norm": lbl,
                        "error": "row_index_out_of_range",
                    }
                )
        self._learner_creation_flow_previews.append(
            {
                "learner_name": str(learner_name),
                "creation_source": str(creation_source),
                "window_left": int(window_left),
                "window_right": int(window_right),
                "cluster_size": int(cluster_size),
                "flows_preview": flows,
            }
        )

    def _accumulate_learner_distribution(self, learner_name: str, labels: np.ndarray) -> None:
        if len(labels) == 0:
            return
        counts = self.learner_cumulative_counts.setdefault(learner_name, {})
        dist = self._label_distribution(labels)
        for label, n in dist.items():
            counts[label] = int(counts.get(label, 0) + n)

    def _append_train_batch_profile(
        self,
        stage: str,
        learner_name: str,
        labels: np.ndarray,
        window_left: int = -1,
        window_right: int = -1,
        hist_sample_count: int = 0,
        new_sample_count: int = 0,
        update_total_count: int = 0,
    ) -> None:
        labels_arr = np.asarray(labels, dtype=object)
        dist = self._label_distribution(labels_arr)
        total = int(len(labels_arr))
        benign_count = int(sum(int(v) for k, v in dist.items() if is_benign_label(str(k))))
        attack_count = int(max(total - benign_count, 0))
        attack_ratio = self._safe_div(attack_count, total)
        dominant_label = max(dist, key=dist.get) if total > 0 else ""
        dominant_count = int(dist.get(dominant_label, 0)) if total > 0 else 0
        dominant_ratio = self._safe_div(dominant_count, total)
        row = {
            "stage": str(stage),
            "learner_name": str(learner_name),
            "window_left": int(window_left),
            "window_right": int(window_right),
            "hist_sample_count": int(hist_sample_count),
            "new_sample_count": int(new_sample_count),
            "update_total_count": int(update_total_count),
            "label_sample_count": total,
            "benign_count": benign_count,
            "attack_count": attack_count,
            "attack_ratio": attack_ratio,
            "dominant_label": str(dominant_label),
            "dominant_count": dominant_count,
            "dominant_ratio": dominant_ratio,
            "label_distribution_json": json.dumps(dist, ensure_ascii=False),
        }
        self.learner_train_batch_profiles.append(row)
        self.logger.info(
            "[TrainBatch][%s] learner=%s window=%d-%d labels=%d attack_ratio=%.4f dominant=%s(%.4f) hist=%d new=%d update_total=%d",
            stage,
            learner_name,
            int(window_left),
            int(window_right),
            total,
            attack_ratio,
            dominant_label,
            dominant_ratio,
            int(hist_sample_count),
            int(new_sample_count),
            int(update_total_count),
        )

    def _append_fit_loss_profile(
        self,
        stage: str,
        learner_name: str,
        window_left: int,
        window_right: int,
        sample_count: int,
        epoch_losses: List[float],
        epoch_val_losses: Optional[List[float]] = None,
    ) -> None:
        clean = [float(x) for x in epoch_losses if np.isfinite(float(x))]
        val_list = epoch_val_losses or []
        val_clean = [float(x) for x in val_list if np.isfinite(float(x))]
        train_last = float(clean[-1]) if clean else float("nan")
        val_last = float(val_clean[-1]) if val_clean else float("nan")
        row = {
            "stage": str(stage),
            "learner_name": str(learner_name),
            "window_left": int(window_left),
            "window_right": int(window_right),
            "sample_count": int(sample_count),
            "epoch_count": int(len(epoch_losses)),
            "epoch_loss_first": float(clean[0]) if clean else float("nan"),
            "epoch_loss_last": train_last,
            "epoch_loss_min": float(min(clean)) if clean else float("nan"),
            "epoch_loss_max": float(max(clean)) if clean else float("nan"),
            "epoch_val_count": int(len(val_list)),
            "epoch_val_first": float(val_clean[0]) if val_clean else float("nan"),
            "epoch_val_last": val_last,
            "epoch_val_min": float(min(val_clean)) if val_clean else float("nan"),
            "epoch_val_max": float(max(val_clean)) if val_clean else float("nan"),
            "overfit_gap_last": float(val_last - train_last)
            if np.isfinite(train_last) and np.isfinite(val_last)
            else float("nan"),
            "epoch_losses_json": json.dumps([float(x) for x in epoch_losses], ensure_ascii=False),
            "epoch_val_losses_json": json.dumps([float(x) for x in val_list], ensure_ascii=False),
        }
        self.learner_fit_loss_profiles.append(row)

    def _record_learner_samples(
        self,
        learner_name: str,
        samples: np.ndarray,
        labels: np.ndarray | None = None,
    ) -> None:
        if len(samples) == 0:
            return
        chunk = np.asarray(samples, dtype=np.float32)
        if chunk.ndim == 1:
            chunk = chunk.reshape(1, -1)
        if chunk.shape[0] == 0:
            return
        lname = str(learner_name)
        self.learner_assigned_feature_chunks.setdefault(lname, []).append(chunk)
        if labels is not None:
            label_chunk = np.asarray(labels, dtype=object).reshape(-1)
            if len(label_chunk) != int(chunk.shape[0]):
                raise ValueError(
                    f"label count {len(label_chunk)} != sample count {chunk.shape[0]} "
                    f"for learner {lname}"
                )
            self.learner_assigned_label_chunks.setdefault(lname, []).append(label_chunk)

    def _accumulate_learner_distribution_from_counts(
        self, learner_name: str, dist: Dict[str, int]
    ) -> None:
        if not dist:
            return
        counts = self.learner_cumulative_counts.setdefault(learner_name, {})
        for label, n in dist.items():
            if int(n) <= 0:
                continue
            counts[str(label)] = int(counts.get(str(label), 0) + int(n))

    @staticmethod
    def _learner_order_key(learner_name: str) -> Tuple[int, int, str]:
        if is_benign_label(learner_name):
            return (0, 0, learner_name)
        if learner_name.startswith("NEW_"):
            suffix = learner_name[4:]
            if suffix.isdigit():
                return (1, int(suffix), learner_name)
            return (1, 10**9, learner_name)
        if learner_name == "UNKNOWN":
            return (3, 0, learner_name)
        return (2, 0, learner_name)

    def _build_cumulative_profile_rows(self) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        ordered_learners = sorted(self.learner_cumulative_counts.keys(), key=self._learner_order_key)
        for learner_name in ordered_learners:
            dist = self.learner_cumulative_counts[learner_name]
            total = int(sum(dist.values()))
            benign_count = int(
                sum(int(n) for label, n in dist.items() if is_benign_label(str(label)))
            )
            attack_count = int(max(total - benign_count, 0))
            attack_ratio = float(attack_count / total) if total > 0 else 0.0
            creation_sample_count = int(self.learner_creation_sample_count.get(learner_name, 0))
            post_creation_added_samples = int(max(total - creation_sample_count, 0))
            if total == 0:
                dominant_label = ""
                dominant_count = 0
                dominant_ratio = 0.0
            else:
                dominant_label = max(dist, key=dist.get)
                dominant_count = int(dist[dominant_label])
                dominant_ratio = float(dominant_count / total)
            rows.append(
                {
                    "attack_ratio": attack_ratio,
                    "learner_name": learner_name,
                    "total_assigned_samples": total,
                    "creation_sample_count": creation_sample_count,
                    "post_creation_added_samples": post_creation_added_samples,
                    "dominant_label": dominant_label,
                    "dominant_count": dominant_count,
                    "dominant_ratio": dominant_ratio,
                    "label_distribution_json": json.dumps(dist, ensure_ascii=False),
                }
            )
        return rows

    def _build_assignment_index_df(self, data_len: int) -> pd.DataFrame:
        if not self.sample_assignments:
            return pd.DataFrame(columns=["row_index", "assigned_learner"])
        assign_df = pd.DataFrame(self.sample_assignments)
        if assign_df.empty or "row_index" not in assign_df.columns or "assigned_learner" not in assign_df.columns:
            return pd.DataFrame(columns=["row_index", "assigned_learner"])
        assign_df = assign_df[["row_index", "assigned_learner"]].copy()
        assign_df["row_index"] = pd.to_numeric(assign_df["row_index"], errors="coerce")
        assign_df = assign_df.dropna(subset=["row_index", "assigned_learner"])
        assign_df["row_index"] = assign_df["row_index"].astype(int)
        assign_df["assigned_learner"] = assign_df["assigned_learner"].astype(str)
        valid_mask = (assign_df["row_index"] >= 0) & (assign_df["row_index"] < int(data_len))
        assign_df = assign_df.loc[valid_mask]
        return assign_df

    def _build_extended_assignment_index_df(self, data_len: int) -> pd.DataFrame:
        """
        One row_index → one learner for feature/protocol aggregates.

        Take stream ``pred`` from ``sample_assignments``. Union each learner's creation
        row set (``_learner_creation_row_indices``): those indices count toward that
        learner unless the stream already routed the row to another concrete learner.
        """
        base = self._build_assignment_index_df(data_len)
        row_owner: Dict[int, str] = {}
        if not base.empty:
            for _, row in base.iterrows():
                row_owner[int(row["row_index"])] = str(row["assigned_learner"])

        for learner_name, creation_rows in self._learner_creation_row_indices.items():
            ln = str(learner_name)
            for ri in creation_rows:
                row_i = int(ri)
                if not (0 <= row_i < int(data_len)):
                    continue
                cur = row_owner.get(row_i)
                if cur is None or cur == "UNKNOWN":
                    row_owner[row_i] = ln

        if not row_owner:
            return pd.DataFrame(columns=["row_index", "assigned_learner"])
        out_rows = [{"row_index": ri, "assigned_learner": row_owner[ri]} for ri in sorted(row_owner)]
        return pd.DataFrame(out_rows)

    def _build_assignment_export_df(self, data_len: int) -> pd.DataFrame:
        """
        Canonical row→learner map for artifacts: stream preds plus creation-row fills.
        """
        extended = self._build_extended_assignment_index_df(data_len)
        if extended.empty:
            return pd.DataFrame(
                columns=["row_index", "assigned_learner", "phase", "timestamp"],
            )

        stream_owner: Dict[int, str] = {}
        stream_ts: Dict[int, str] = {}
        for rec in self.sample_assignments:
            if str(rec.get("phase", "")) != "stream":
                continue
            try:
                ri = int(rec["row_index"])
            except (TypeError, ValueError):
                continue
            stream_owner[ri] = str(rec["assigned_learner"])
            stream_ts[ri] = str(rec.get("timestamp", "") or "")

        phases: List[str] = []
        timestamps: List[str] = []
        for _, row in extended.iterrows():
            ri = int(row["row_index"])
            ln = str(row["assigned_learner"])
            if stream_owner.get(ri) == ln:
                phases.append("stream")
                timestamps.append(stream_ts.get(ri, ""))
            else:
                phases.append("creation_fill")
                timestamps.append("")
        out = extended.copy()
        out["phase"] = phases
        out["timestamp"] = timestamps
        return out

    def _build_profile_rows_from_assignment_df(
        self,
        data: pd.DataFrame,
        assign_df: pd.DataFrame,
    ) -> List[Dict[str, object]]:
        """Build learner_label_distribution rows from canonical assignments + labels."""
        if assign_df.empty or data.empty:
            return []

        flow = data.copy()
        flow["row_index"] = np.arange(len(flow), dtype=np.int64)
        label_col = "LabelNorm" if "LabelNorm" in flow.columns else "Label"
        merged = assign_df.merge(
            flow[["row_index", label_col]],
            on="row_index",
            how="inner",
        )
        if merged.empty:
            return []

        rows: List[Dict[str, object]] = []
        for learner_name, grp in merged.groupby("assigned_learner", sort=False):
            ln = str(learner_name)
            labels = grp[label_col].astype(str).to_numpy()
            dist = self._label_distribution(labels)
            total = int(len(labels))
            benign_count = int(
                sum(int(n) for label, n in dist.items() if is_benign_label(str(label)))
            )
            attack_count = int(max(total - benign_count, 0))
            attack_ratio = float(attack_count / total) if total > 0 else 0.0
            if "phase" in grp.columns:
                creation_sample_count = int(
                    (grp["phase"].astype(str) == "creation_fill").sum()
                )
            else:
                creation_sample_count = int(
                    len(self._learner_creation_row_indices.get(ln, set()))
                )
            post_creation_added_samples = int(max(total - creation_sample_count, 0))
            if total == 0:
                dominant_label = ""
                dominant_count = 0
                dominant_ratio = 0.0
            else:
                dominant_label = max(dist, key=dist.get)
                dominant_count = int(dist[dominant_label])
                dominant_ratio = float(dominant_count / total)
            rows.append(
                {
                    "attack_ratio": attack_ratio,
                    "learner_name": ln,
                    "total_assigned_samples": total,
                    "creation_sample_count": creation_sample_count,
                    "post_creation_added_samples": post_creation_added_samples,
                    "dominant_label": dominant_label,
                    "dominant_count": dominant_count,
                    "dominant_ratio": dominant_ratio,
                    "label_distribution_json": json.dumps(dist, ensure_ascii=False),
                }
            )
        rows.sort(
            key=lambda r: (
                -float(r.get("attack_ratio", 0.0)),
                -int(r.get("total_assigned_samples", 0)),
            )
        )
        return rows

    def _log_assignment_consistency(self, data_len: int, assign_export_df: pd.DataFrame) -> None:
        """Warn when legacy cumulative counts diverge from canonical assignment rows."""
        if assign_export_df.empty:
            return
        canonical_counts = (
            assign_export_df.groupby("assigned_learner").size().astype(int).to_dict()
        )
        mismatches: List[str] = []
        for learner_name, dist in self.learner_cumulative_counts.items():
            legacy_total = int(sum(dist.values()))
            canonical_total = int(canonical_counts.get(str(learner_name), 0))
            if legacy_total != canonical_total:
                mismatches.append(
                    f"{learner_name}: legacy={legacy_total} canonical={canonical_total}"
                )
        if mismatches:
            self.logger.warning(
                "[AssignmentConsistency] %d learner(s) differ (using canonical for export): %s",
                len(mismatches),
                "; ".join(mismatches[:8]),
            )

    def _build_learner_feature_stats_df(
        self,
        data: pd.DataFrame,
        feature_names: List[str],
    ) -> pd.DataFrame:
        cols = [str(c) for c in feature_names if str(c) in data.columns]
        if not cols:
            return pd.DataFrame(columns=["learner_name"])
        assign_df = self._build_extended_assignment_index_df(len(data))
        if assign_df.empty:
            return pd.DataFrame(columns=["learner_name"])

        flow_df = data.loc[:, cols].copy()
        flow_df = flow_df.replace([np.inf, -np.inf], np.nan)
        for c in cols:
            flow_df[c] = pd.to_numeric(flow_df[c], errors="coerce")
        flow_df = flow_df.reset_index(drop=True)
        flow_df["row_index"] = np.arange(len(flow_df), dtype=np.int64)

        merged = assign_df.merge(flow_df, on="row_index", how="left")
        if merged.empty:
            return pd.DataFrame(columns=["learner_name"])

        agg_spec = {c: ["mean", "std"] for c in cols}
        grouped = merged.groupby("assigned_learner", dropna=False).agg(agg_spec)
        grouped.columns = [f"{name}__{stat}" for name, stat in grouped.columns]
        grouped = grouped.reset_index().rename(columns={"assigned_learner": "learner_name"})
        for c in cols:
            mean_col = f"{c}__mean"
            std_col = f"{c}__std"
            cv_col = f"{c}__cv"
            if mean_col not in grouped.columns or std_col not in grouped.columns:
                continue
            denom = pd.to_numeric(grouped[mean_col], errors="coerce").abs().replace(0.0, np.nan)
            std_vals = pd.to_numeric(grouped[std_col], errors="coerce").abs()
            grouped[cv_col] = (std_vals / denom).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        grouped = grouped.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        return grouped

    def _build_learner_protocol_stats_df(self, data: pd.DataFrame) -> pd.DataFrame:
        if "Protocol" not in data.columns:
            return pd.DataFrame(columns=["learner_name"])
        assign_df = self._build_extended_assignment_index_df(len(data))
        if assign_df.empty:
            return pd.DataFrame(columns=["learner_name"])
        proto_series = pd.to_numeric(data["Protocol"], errors="coerce").reset_index(drop=True)
        proto_df = pd.DataFrame(
            {
                "row_index": np.arange(len(proto_series), dtype=np.int64),
                "Protocol": proto_series,
            }
        )
        merged = assign_df.merge(proto_df, on="row_index", how="left")
        if merged.empty:
            return pd.DataFrame(columns=["learner_name"])

        rows: List[Dict[str, object]] = []
        for learner_name, g in merged.groupby("assigned_learner"):
            p = pd.to_numeric(g["Protocol"], errors="coerce").dropna()
            total = int(len(p))
            if total <= 0:
                rows.append(
                    {
                        "learner_name": str(learner_name),
                        "protocol_tcp_ratio": 0.0,
                        "protocol_udp_ratio": 0.0,
                        "protocol_other_ratio": 0.0,
                        "protocol_concentration": 0.0,
                        "protocol_cluster_type": "UNKNOWN",
                    }
                )
                continue
            p_int = p.round().astype(int)
            tcp = int((p_int == TCP_PROTOCOL_NUMBER).sum())
            udp = int((p_int == UDP_PROTOCOL_NUMBER).sum())
            other = int(max(total - tcp - udp, 0))
            tcp_ratio = float(tcp / total)
            udp_ratio = float(udp / total)
            other_ratio = float(other / total)
            concentration = float(max(tcp_ratio, udp_ratio))
            if tcp_ratio >= 0.8:
                cluster_type = "TCP_CLUSTER"
            elif udp_ratio >= 0.8:
                cluster_type = "UDP_CLUSTER"
            elif concentration >= 0.6:
                cluster_type = "TCP_UDP_BIASED"
            else:
                cluster_type = "MIXED"
            rows.append(
                {
                    "learner_name": str(learner_name),
                    "protocol_tcp_ratio": tcp_ratio,
                    "protocol_udp_ratio": udp_ratio,
                    "protocol_other_ratio": other_ratio,
                    "protocol_concentration": concentration,
                    "protocol_cluster_type": cluster_type,
                }
            )
        return pd.DataFrame(rows)

    def _build_learner_temporal_stats_df(self, data: pd.DataFrame) -> pd.DataFrame:
        if data.empty or "Timestamp" not in data.columns:
            return pd.DataFrame(columns=["learner_name"])
        assign_df = self._build_extended_assignment_index_df(len(data))
        if assign_df.empty:
            return pd.DataFrame(columns=["learner_name"])

        ts_all = pd.to_datetime(data["Timestamp"], errors="coerce")
        if not bool(ts_all.notna().any()):
            return pd.DataFrame(columns=["learner_name"])
        global_min = ts_all[ts_all.notna()].min()
        global_max = ts_all[ts_all.notna()].max()
        global_span_sec = float((global_max - global_min).total_seconds())
        n_bins = int(LEARNER_GLOBAL_TIME_BINS)
        edges = np.linspace(global_min.value, global_max.value, n_bins + 1)

        ts_df = pd.DataFrame(
            {
                "row_index": np.arange(len(data), dtype=np.int64),
                "Timestamp": ts_all,
            }
        )
        merged = assign_df.merge(ts_df, on="row_index", how="left")
        if merged.empty:
            return pd.DataFrame(columns=["learner_name"])

        rows: List[Dict[str, object]] = []
        for learner_name, g in merged.groupby("assigned_learner", dropna=False):
            ts = pd.to_datetime(g["Timestamp"], errors="coerce").dropna().sort_values()
            n = int(len(ts))
            if n <= 0:
                rows.append(
                    {
                        "learner_name": str(learner_name),
                        "temporal_sample_count": 0,
                        "temporal_span_sec": 0.0,
                        "temporal_span_ratio": 0.0,
                        "temporal_global_hhi": 0.0,
                        "temporal_norm_entropy": 0.0,
                        "temporal_concentration": 0.0,
                        "temporal_burst_score": 0.0,
                        "temporal_cluster_type": "EMPTY",
                    }
                )
                continue
            span_sec = float((ts.iloc[-1] - ts.iloc[0]).total_seconds()) if n > 1 else 0.0
            span_ratio = float(span_sec / global_span_sec) if global_span_sec > 0.0 else 0.0
            counts, _ = np.histogram(ts.astype("int64"), bins=edges)
            counts = counts.astype(float)
            mass = counts / max(float(n), 1.0)
            global_hhi = float(np.sum(mass**2))
            occupied = counts[counts > 0]
            if len(occupied) <= 1:
                norm_entropy = 0.0
            else:
                p = occupied / float(n)
                ent = float(-np.sum(p * np.log(p + 1e-15)))
                norm_entropy = float(ent / np.log(len(occupied)))
            concentration = float(1.0 - norm_entropy)
            burst_score = float(0.5 * (1.0 - min(span_ratio, 1.0)) + 0.5 * global_hhi)
            if span_ratio < 1e-3 and global_hhi >= 0.5:
                cluster_type = "SHORT_BURST"
            elif span_ratio >= 0.01:
                cluster_type = "LONG_SPAN"
            else:
                cluster_type = "MEDIUM_SPAN"
            rows.append(
                {
                    "learner_name": str(learner_name),
                    "temporal_sample_count": n,
                    "temporal_span_sec": span_sec,
                    "temporal_span_ratio": span_ratio,
                    "temporal_global_hhi": global_hhi,
                    "temporal_norm_entropy": norm_entropy,
                    "temporal_concentration": concentration,
                    "temporal_burst_score": burst_score,
                    "temporal_cluster_type": cluster_type,
                }
            )
        return pd.DataFrame(rows)

    def _build_learner_port_stats_df(self, data: pd.DataFrame) -> pd.DataFrame:
        if "Dst Port" not in data.columns:
            return pd.DataFrame(columns=["learner_name"])
        assign_df = self._build_extended_assignment_index_df(len(data))
        if assign_df.empty:
            return pd.DataFrame(columns=["learner_name"])

        port_df = pd.DataFrame(
            {
                "row_index": np.arange(len(data), dtype=np.int64),
                "Dst Port": pd.to_numeric(data["Dst Port"], errors="coerce"),
                "Src Port": pd.to_numeric(data["Src Port"], errors="coerce")
                if "Src Port" in data.columns
                else np.nan,
            }
        )
        merged = assign_df.merge(port_df, on="row_index", how="left")
        if merged.empty:
            return pd.DataFrame(columns=["learner_name"])

        def _port_metrics(ports: pd.Series) -> Dict[str, object]:
            p = pd.to_numeric(ports, errors="coerce").dropna().astype(int)
            n = int(len(p))
            if n <= 0:
                return {
                    "n": 0,
                    "unique": 0,
                    "norm_entropy": 0.0,
                    "concentration": 0.0,
                    "hhi": 0.0,
                    "top_port": 0,
                    "top_ratio": 0.0,
                }
            vc = p.value_counts()
            k = int(len(vc))
            mass = (vc / n).values.astype(float)
            ent = float(-np.sum(mass * np.log(mass + 1e-15)))
            norm_entropy = float(ent / np.log(k)) if k > 1 else 0.0
            return {
                "n": n,
                "unique": k,
                "norm_entropy": norm_entropy,
                "concentration": float(1.0 - norm_entropy),
                "hhi": float(np.sum(mass**2)),
                "top_port": int(vc.index[0]),
                "top_ratio": float(mass[0]),
            }

        rows: List[Dict[str, object]] = []
        for learner_name, g in merged.groupby("assigned_learner", dropna=False):
            dst = _port_metrics(g["Dst Port"])
            src = _port_metrics(g["Src Port"])
            if int(dst["unique"]) <= 0:
                cluster_type = "UNKNOWN"
            elif float(dst["top_ratio"]) < 0.15 and int(dst["unique"]) >= 200:
                cluster_type = "PORT_SCAN_LIKE"
            elif float(dst["top_ratio"]) > 0.9 and int(dst["unique"]) <= 3:
                cluster_type = "SINGLE_PORT"
            else:
                cluster_type = "SERVICE_LIKE"
            rows.append(
                {
                    "learner_name": str(learner_name),
                    "dst_port_sample_count": int(dst["n"]),
                    "dst_port_unique": int(dst["unique"]),
                    "dst_port_norm_entropy": float(dst["norm_entropy"]),
                    "dst_port_concentration": float(dst["concentration"]),
                    "dst_port_hhi": float(dst["hhi"]),
                    "dst_top_port": int(dst["top_port"]),
                    "dst_top_port_ratio": float(dst["top_ratio"]),
                    "src_port_norm_entropy": float(src["norm_entropy"]),
                    "src_port_unique": int(src["unique"]),
                    "port_cluster_type": cluster_type,
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _build_attack_ratio_feature_correlation_rows(
        profile_df: pd.DataFrame,
    ) -> List[Dict[str, float | str]]:
        if profile_df.empty or "attack_ratio" not in profile_df.columns:
            return []
        y = pd.to_numeric(profile_df["attack_ratio"], errors="coerce")
        rows: List[Dict[str, float | str]] = []
        for col in profile_df.columns:
            if col in {
                "learner_name",
                "attack_ratio",
                "dominant_label",
                "label_distribution_json",
                "is_attack_learner",
                "protocol_cluster_type",
                "temporal_cluster_type",
                "port_cluster_type",
            }:
                continue
            x = pd.to_numeric(profile_df[col], errors="coerce")
            if x.notna().sum() < 2:
                continue
            if float(x.max() - x.min()) == 0.0:
                continue
            pearson = x.corr(y, method="pearson")
            spearman = x.corr(y, method="spearman")
            if not np.isfinite(float(pearson)) and not np.isfinite(float(spearman)):
                continue
            rows.append(
                {
                    "feature": str(col),
                    "pearson_corr": float(pearson) if np.isfinite(float(pearson)) else 0.0,
                    "spearman_corr": float(spearman) if np.isfinite(float(spearman)) else 0.0,
                    "abs_pearson_corr": abs(float(pearson)) if np.isfinite(float(pearson)) else 0.0,
                    "abs_spearman_corr": abs(float(spearman)) if np.isfinite(float(spearman)) else 0.0,
                }
            )
        rows = sorted(
            rows,
            key=lambda r: (
                float(r.get("abs_pearson_corr", 0.0)),
                float(r.get("abs_spearman_corr", 0.0)),
            ),
            reverse=True,
        )
        return rows

    @staticmethod
    def _build_protocol_cluster_summary(profile_df: pd.DataFrame) -> Dict[str, object]:
        if profile_df.empty or "protocol_cluster_type" not in profile_df.columns:
            return {
                "learner_count": 0,
                "sample_total": 0,
                "by_type": {},
            }
        df = profile_df.copy()
        df["protocol_cluster_type"] = df["protocol_cluster_type"].fillna("UNKNOWN").astype(str)
        if "total_assigned_samples" in df.columns:
            df["total_assigned_samples"] = pd.to_numeric(
                df["total_assigned_samples"], errors="coerce"
            ).fillna(0.0)
        else:
            df["total_assigned_samples"] = 0.0
        sample_total = float(df["total_assigned_samples"].sum())

        by_type: Dict[str, object] = {}
        for t, g in df.groupby("protocol_cluster_type"):
            learner_count = int(len(g))
            samples = float(g["total_assigned_samples"].sum())
            by_type[str(t)] = {
                "learner_count": learner_count,
                "learner_ratio": float(learner_count / max(1, len(df))),
                "sample_count": int(samples),
                "sample_ratio": float(samples / max(1.0, sample_total)),
            }
        return {
            "learner_count": int(len(df)),
            "sample_total": int(sample_total),
            "by_type": by_type,
        }

    @staticmethod
    def _save_attack_ratio_correlation_figure(
        rows: List[Dict[str, float | str]],
        out_path: Path,
        top_k: int = 24,
    ) -> None:
        if not rows:
            return
        top = rows[: max(1, int(top_k))]
        labels = [str(r["feature"]) for r in top][::-1]
        values = [float(r["pearson_corr"]) for r in top][::-1]
        colors = ["#dc2626" if v > 0 else "#16a34a" for v in values]
        plt.figure(figsize=(12, 9))
        plt.barh(labels, values, color=colors, alpha=0.9)
        plt.axvline(0.0, color="#64748b", linewidth=1.0)
        plt.xlim(-1.0, 1.0)
        plt.xlabel("Pearson correlation with attack_ratio")
        plt.ylabel("Cluster feature")
        plt.title("Top cluster-feature correlations with attack_ratio")
        plt.tight_layout()
        plt.savefig(out_path, dpi=180)
        plt.close()

    def _learner_display_name(self, learner_name: str) -> str:
        """
        Render learner name as: learnerName_dominantLabel(share)
        Example: NEW_98_2019|DRDOS_NETBIOS(22.6%)
        """
        dist = self.learner_cumulative_counts.get(learner_name, {})
        total = int(sum(int(v) for v in dist.values()))
        if total <= 0:
            return f"{learner_name}_UNKNOWN(0.0%)"
        dominant_label = max(dist, key=dist.get)
        dominant_count = int(dist[dominant_label])
        ratio = float(dominant_count / total)
        return f"{learner_name}_{dominant_label}({ratio:.1%})"

    def _save_overlap_association_figure(
        self,
        overlap_df: pd.DataFrame,
        learner_names: List[str],
        out_path: Path,
        top_k_edges: int = 80,
        min_jaccard: float = 0.10,
        max_edges: int = 80,
    ) -> None:
        """
        Save a network-style association figure for top-K edges.
        Edge width is proportional to Jaccard overlap.
        """
        if overlap_df.empty or not learner_names:
            return

        learner_set = set(learner_names)
        edges: List[Tuple[str, str, float]] = []
        for _, row in overlap_df.iterrows():
            a = str(row["learner_a_raw"]) if "learner_a_raw" in overlap_df.columns else str(row["learner_a"])
            b = str(row["learner_b_raw"]) if "learner_b_raw" in overlap_df.columns else str(row["learner_b"])
            if a not in learner_set or b not in learner_set:
                continue
            jaccard = float(row.get("jaccard_acceptance", 0.0))
            if jaccard <= 0.0:
                continue
            edges.append((a, b, jaccard))

        # Edge-first selection: threshold first, then top-K edges.
        edges = sorted(edges, key=lambda x: x[2], reverse=True)
        edges = [e for e in edges if e[2] >= float(min_jaccard)]
        if top_k_edges > 0:
            edges = edges[: int(top_k_edges)]
        if max_edges > 0:
            edges = edges[: int(max_edges)]
        if not edges:
            return

        connected_nodes = sorted({a for a, _, _ in edges} | {b for _, b, _ in edges})
        selected = connected_nodes
        if len(selected) < 2:
            return

        labels = {n: self._learner_display_name(n) for n in selected}
        max_count = max(int(self.debug_overlap_accept_count.get(n, 0)) for n in selected)
        max_count = max(max_count, 1)

        # Circular layout for deterministic readability.
        angles = np.linspace(0, 2 * np.pi, num=len(selected), endpoint=False)
        pos = {
            n: (float(np.cos(ang)), float(np.sin(ang)))
            for n, ang in zip(selected, angles)
        }

        def _node_color(name: str) -> str:
            dist = self.learner_cumulative_counts.get(name, {})
            if not dist:
                return "#9E9E9E"
            dominant_label = str(max(dist, key=dist.get))
            if dominant_label.startswith("2017|"):
                return "#FFB74D"
            if dominant_label.startswith("2019|"):
                return "#64B5F6"
            if dominant_label.startswith("2026|"):
                return "#81C784"
            return "#B0BEC5"

        plt.figure(figsize=(14, 12))
        ax = plt.gca()

        for a, b, j in edges:
            x1, y1 = pos[a]
            x2, y2 = pos[b]
            lw = 0.8 + 10.0 * j
            alpha = min(0.85, 0.2 + 2.0 * j)
            ax.plot([x1, x2], [y1, y2], color="#546E7A", linewidth=lw, alpha=alpha, zorder=1)

        for n in selected:
            x, y = pos[n]
            count = int(self.debug_overlap_accept_count.get(n, 0))
            size = 160.0 + 2200.0 * (count / max_count)
            ax.scatter([x], [y], s=size, c=_node_color(n), edgecolors="black", linewidths=0.8, zorder=2)
            ax.text(x, y, labels[n], fontsize=8, ha="center", va="center", zorder=3)

        ax.set_title(
            f"Learner True Overlap Network (Jaccard >= {float(min_jaccard):.2f}, edges={len(edges)})"
        )
        ax.set_xlim(-1.35, 1.35)
        ax.set_ylim(-1.35, 1.35)
        ax.set_aspect("equal", adjustable="box")
        ax.axis("off")

        legend_handles = [
            plt.Line2D([0], [0], marker="o", color="w", label="2017-dominant", markerfacecolor="#FFB74D", markeredgecolor="black", markersize=8),
            plt.Line2D([0], [0], marker="o", color="w", label="2019-dominant", markerfacecolor="#64B5F6", markeredgecolor="black", markersize=8),
            plt.Line2D([0], [0], marker="o", color="w", label="2026-dominant", markerfacecolor="#81C784", markeredgecolor="black", markersize=8),
        ]
        ax.legend(handles=legend_handles, loc="upper right", frameon=True)
        plt.tight_layout()
        plt.savefig(out_path, dpi=180)
        plt.close()

    @staticmethod
    def _select_overlap_edges(
        overlap_df: pd.DataFrame,
        min_jaccard: float,
        top_k_edges: int,
        max_edges: int,
    ) -> List[Tuple[str, str, float, float]]:
        if overlap_df.empty:
            return []
        edges: List[Tuple[str, str, float, float]] = []
        for _, row in overlap_df.iterrows():
            a = str(row["learner_a_raw"]) if "learner_a_raw" in overlap_df.columns else str(row["learner_a"])
            b = str(row["learner_b_raw"]) if "learner_b_raw" in overlap_df.columns else str(row["learner_b"])
            jaccard = float(row.get("jaccard_acceptance", 0.0))
            if jaccard <= 0.0:
                continue
            if jaccard < float(min_jaccard):
                continue
            score = float(jaccard)
            edges.append((a, b, jaccard, score))
        edges = sorted(edges, key=lambda x: (x[3], x[2]), reverse=True)
        if top_k_edges > 0:
            edges = edges[: int(top_k_edges)]
        if max_edges > 0:
            edges = edges[: int(max_edges)]
        return edges

    def _components_by_connected(self, learner_names: List[str], edges: List[Tuple[str, str, float, float]]) -> Tuple[List[List[str]], Dict[Tuple[str, str], float], int]:
        learner_set = set(learner_names)
        adj: Dict[str, set] = {name: set() for name in learner_names}
        edge_weights: Dict[Tuple[str, str], float] = {}
        used_edges = 0
        for a, b, w, _ in edges:
            if a not in learner_set or b not in learner_set:
                continue
            adj[a].add(b)
            adj[b].add(a)
            key = tuple(sorted((a, b)))
            edge_weights[key] = float(w)
            used_edges += 1
        components: List[List[str]] = []
        visited: set = set()
        for name in sorted(learner_names, key=self._learner_order_key):
            if name in visited:
                continue
            stack = [name]
            comp: List[str] = []
            while stack:
                cur = stack.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                comp.append(cur)
                for nxt in sorted(adj.get(cur, set()), key=self._learner_order_key):
                    if nxt not in visited:
                        stack.append(nxt)
            components.append(sorted(comp, key=self._learner_order_key))
        return components, edge_weights, int(used_edges)

    def _components_by_mutual_knn(
        self,
        learner_names: List[str],
        edges: List[Tuple[str, str, float, float]],
        mutual_top_k: int,
    ) -> Tuple[List[List[str]], Dict[Tuple[str, str], float], int]:
        learner_set = set(learner_names)
        neighbors: Dict[str, List[Tuple[str, float]]] = {name: [] for name in learner_names}
        jaccard_by_edge: Dict[Tuple[str, str], float] = {}
        for a, b, jaccard, score in edges:
            if a not in learner_set or b not in learner_set:
                continue
            neighbors[a].append((b, float(score)))
            neighbors[b].append((a, float(score)))
            jaccard_by_edge[tuple(sorted((a, b)))] = float(jaccard)
        top_k_sets: Dict[str, set] = {}
        k = max(1, int(mutual_top_k))
        for name, nbrs in neighbors.items():
            nbrs_sorted = sorted(nbrs, key=lambda x: x[1], reverse=True)
            top_k_sets[name] = {n for n, _ in nbrs_sorted[:k]}

        kept_edges: List[Tuple[str, str, float]] = []
        for a, b, _, _ in edges:
            if b in top_k_sets.get(a, set()) and a in top_k_sets.get(b, set()):
                key = tuple(sorted((a, b)))
                kept_edges.append((a, b, float(jaccard_by_edge.get(key, 0.0))))

        dedup: Dict[Tuple[str, str], float] = {}
        for a, b, w in kept_edges:
            key = tuple(sorted((a, b)))
            dedup[key] = max(float(dedup.get(key, 0.0)), float(w))
        reduced_edges = [(a, b, w) for (a, b), w in dedup.items()]
        # Reuse connected component building.
        reduced_for_common = [(a, b, w, w) for a, b, w in reduced_edges]
        return self._components_by_connected(learner_names, reduced_for_common)

    def _aggregate_learners_by_overlap(
        self,
        cumulative_rows: List[Dict[str, object]],
        overlap_df: pd.DataFrame,
    ) -> Tuple[List[Dict[str, object]], List[Dict[str, object]], Dict[str, object]]:
        learner_names = [str(row["learner_name"]) for row in cumulative_rows]
        if not learner_names:
            return [], [], {}

        edges = self._select_overlap_edges(
            overlap_df=overlap_df,
            min_jaccard=self.aggregate_min_jaccard,
            top_k_edges=self.aggregate_top_k_edges,
            max_edges=self.aggregate_max_edges,
        )
        algo = self.aggregate_graph_algo.strip().lower()
        if algo == "mutual_knn_components":
            components, edge_weights, used_edges = self._components_by_mutual_knn(
                learner_names=learner_names,
                edges=edges,
                mutual_top_k=self.aggregate_mutual_top_k,
            )
        else:
            components, edge_weights, used_edges = self._components_by_connected(
                learner_names=learner_names,
                edges=edges,
            )

        agg_rows: List[Dict[str, object]] = []
        mapping_rows: List[Dict[str, object]] = []
        for idx, comp in enumerate(components, start=1):
            agg_name = f"AGG_{idx:03d}"
            agg_dist: Dict[str, int] = {}
            agg_creation = 0
            agg_total = 0
            for learner_name in comp:
                dist = self.learner_cumulative_counts.get(learner_name, {})
                agg_creation += int(self.learner_creation_sample_count.get(learner_name, 0))
                for label, n in dist.items():
                    agg_dist[str(label)] = int(agg_dist.get(str(label), 0) + int(n))
                agg_total += int(sum(int(v) for v in dist.values()))

            dominant_label = ""
            dominant_count = 0
            dominant_ratio = 0.0
            benign_count = 0
            attack_count = 0
            attack_ratio = 0.0
            learner_polarity = "UNKNOWN"
            init_benign_label_count = 0
            init_benign_label_ratio = 0.0
            init_benign_overlap_count = 0
            init_benign_overlap_ratio = 0.0
            member_accept_total = 0
            learner_polarity_by_init = "UNKNOWN"
            if agg_total > 0 and agg_dist:
                dominant_label = str(max(agg_dist, key=agg_dist.get))
                dominant_count = int(agg_dist[dominant_label])
                dominant_ratio = float(dominant_count / agg_total)
                benign_count = int(
                    sum(int(v) for k, v in agg_dist.items() if is_benign_label(str(k)))
                )
                attack_count = int(max(0, agg_total - benign_count))
                attack_ratio = self._safe_div(float(attack_count), float(agg_total))
                learner_polarity = "MALICIOUS" if attack_ratio >= 0.5 else "BENIGN"
                init_benign_label_count = int(agg_dist.get(self.aggregate_init_benign_label, 0))
                init_benign_label_ratio = self._safe_div(float(init_benign_label_count), float(agg_total))
                for learner_name in comp:
                    accept_cnt = int(self.debug_overlap_accept_count.get(learner_name, 0))
                    member_accept_total += accept_cnt
                    if learner_name == self.aggregate_init_benign_label:
                        init_benign_overlap_count += accept_cnt
                    else:
                        key = tuple(sorted((learner_name, self.aggregate_init_benign_label)))
                        init_benign_overlap_count += int(
                            self.debug_overlap_pair_intersections.get(key, 0)
                        )
                init_benign_overlap_ratio = self._safe_div(
                    float(init_benign_overlap_count),
                    float(max(member_accept_total, 1)),
                )
                learner_polarity_by_init = (
                    "BENIGN"
                    if init_benign_label_ratio >= self.aggregate_init_benign_ratio_threshold
                    else "MALICIOUS"
                )

            internal_edges = 0
            internal_jaccard_sum = 0.0
            for i in range(len(comp)):
                for j in range(i + 1, len(comp)):
                    key = tuple(sorted((comp[i], comp[j])))
                    if key in edge_weights:
                        internal_edges += 1
                        internal_jaccard_sum += float(edge_weights[key])
            avg_internal_jaccard = (internal_jaccard_sum / internal_edges) if internal_edges > 0 else 0.0

            agg_rows.append(
                {
                    "attack_ratio": float(attack_ratio),
                    "aggregate_name": agg_name,
                    "member_count": int(len(comp)),
                    "members_json": json.dumps(comp, ensure_ascii=False),
                    "total_assigned_samples": int(agg_total),
                    "creation_sample_count": int(agg_creation),
                    "post_creation_added_samples": int(max(agg_total - agg_creation, 0)),
                    "dominant_label": dominant_label,
                    "dominant_count": int(dominant_count),
                    "dominant_ratio": float(dominant_ratio),
                    "benign_count": int(benign_count),
                    "attack_count": int(attack_count),
                    "learner_polarity": str(learner_polarity),
                    "init_benign_label": str(self.aggregate_init_benign_label),
                    "init_benign_label_count": int(init_benign_label_count),
                    "init_benign_label_ratio": float(init_benign_label_ratio),
                    "init_benign_overlap_count": int(init_benign_overlap_count),
                    "init_benign_overlap_ratio": float(init_benign_overlap_ratio),
                    "member_accept_total": int(member_accept_total),
                    "learner_polarity_by_init_benign": str(learner_polarity_by_init),
                    "internal_edge_count": int(internal_edges),
                    "avg_internal_jaccard": float(avg_internal_jaccard),
                    "label_distribution_json": json.dumps(agg_dist, ensure_ascii=False),
                }
            )
            for learner_name in comp:
                mapping_rows.append(
                    {
                        "learner_name": learner_name,
                        "aggregate_name": agg_name,
                        "component_size": int(len(comp)),
                    }
                )

        agg_rows = sorted(
            agg_rows,
            key=lambda x: (float(x.get("attack_ratio", 0.0)), int(x["total_assigned_samples"])),
            reverse=True,
        )
        meta = {
            "aggregate_overlap_enabled": bool(self.aggregate_overlap_enabled),
            "aggregate_min_jaccard": float(self.aggregate_min_jaccard),
            "aggregate_top_k_edges": int(self.aggregate_top_k_edges),
            "aggregate_max_edges": int(self.aggregate_max_edges),
            "aggregate_graph_algo": self.aggregate_graph_algo,
            "aggregate_mutual_top_k": int(self.aggregate_mutual_top_k),
            "aggregate_init_benign_label": str(self.aggregate_init_benign_label),
            "aggregate_init_benign_ratio_threshold": float(self.aggregate_init_benign_ratio_threshold),
            "selected_edge_count": int(len(edges)),
            "used_edge_count_after_algo": int(used_edges),
            "aggregate_count": int(len(agg_rows)),
            "learner_count": int(len(learner_names)),
        }
        return agg_rows, mapping_rows, meta

    @staticmethod
    def _safe_div(x: float, y: float) -> float:
        return float(x / y) if y else 0.0

    @staticmethod
    def _to_builtin_float(v: Any) -> float:
        if v is None:
            return float("nan")
        try:
            return float(v)
        except Exception:
            return float("nan")

    @staticmethod
    def _risk_band(risk_score: float) -> str:
        if not np.isfinite(risk_score):
            return "UNKNOWN"
        if risk_score >= 0.75:
            return "HIGH"
        if risk_score >= 0.45:
            return "MEDIUM"
        return "LOW"

    def _build_overlap_risk_map(self) -> Dict[str, float]:
        learner_names = sorted(self.tsieve.learners.keys(), key=self._learner_order_key)
        if not learner_names:
            return {}
        score_map: Dict[str, float] = {str(n): 0.0 for n in learner_names}
        if not self.debug_overlap_accept_count:
            return score_map

        for name in learner_names:
            a = str(name)
            count_a = int(self.debug_overlap_accept_count.get(a, 0))
            if count_a <= 0:
                score_map[a] = 0.0
                continue
            jaccards: List[float] = []
            for b in learner_names:
                b = str(b)
                if b == a:
                    continue
                count_b = int(self.debug_overlap_accept_count.get(b, 0))
                if count_b <= 0:
                    continue
                key = (a, b) if (a, b) in self.debug_overlap_pair_intersections else (b, a)
                inter = int(self.debug_overlap_pair_intersections.get(key, 0))
                if inter <= 0:
                    continue
                union = count_a + count_b - inter
                if union <= 0:
                    continue
                jaccards.append(float(inter / union))
            if not jaccards:
                score_map[a] = 0.0
                continue
            jacc_sorted = sorted(jaccards, reverse=True)
            topk = jacc_sorted[: min(3, len(jacc_sorted))]
            dense_overlap = float(np.mean(topk))
            degree_ratio = float(np.mean(np.asarray(jaccards) >= 0.10))
            score_map[a] = float(min(1.0, max(0.0, 0.7 * dense_overlap + 0.3 * degree_ratio)))
        return score_map

    def _build_stability_risk_map(self) -> Dict[str, float]:
        """
        Build learner-level stability risk from window-wise assignment counts.
        Higher score means more unstable / bursty across windows.
        """
        stream_rows = [r for r in self.sample_assignments if str(r.get("phase", "")) == "stream"]
        if not stream_rows:
            return {}
        window_size = int(self.cfg["stream"]["window_size"])
        if window_size <= 0:
            return {}
        rows = []
        for r in stream_rows:
            learner = str(r.get("assigned_learner", "UNKNOWN"))
            idx = int(r.get("row_index", -1))
            if idx < 0:
                continue
            rows.append({"learner_name": learner, "window_id": int(idx // window_size)})
        if not rows:
            return {}

        df = pd.DataFrame(rows)
        total_windows = int(df["window_id"].max()) + 1
        grouped = df.groupby(["learner_name", "window_id"]).size().reset_index(name="n")
        stability_map: Dict[str, float] = {}
        eps = 1e-9
        for learner_name, g in grouped.groupby("learner_name"):
            vec = np.zeros(total_windows, dtype=np.float64)
            widx = g["window_id"].to_numpy(dtype=int)
            counts = g["n"].to_numpy(dtype=np.float64)
            vec[widx] = counts
            mean_v = float(np.mean(vec))
            std_v = float(np.std(vec))
            cv = std_v / (mean_v + eps)
            p95 = float(np.quantile(vec, 0.95))
            burst = p95 / (mean_v + eps)
            cv_risk = float(1.0 - np.exp(-max(cv, 0.0)))
            burst_risk = float(1.0 - np.exp(-max(burst - 1.0, 0.0)))
            stability_map[str(learner_name)] = float(
                min(1.0, max(0.0, 0.6 * cv_risk + 0.4 * burst_risk))
            )
        return stability_map

    def _build_unsupervised_learner_risk_rows(self) -> List[Dict[str, object]]:
        """
        Label-free learner risk evaluation.
        Risk is computed from model acceptance behavior only, without using traffic labels.
        """
        rows: List[Dict[str, object]] = []
        if not self.learner_assigned_feature_chunks:
            return rows

        overlap_risk_map = self._build_overlap_risk_map()
        stability_risk_map = self._build_stability_risk_map()
        total_samples = int(
            sum(
                int(sum(chunk.shape[0] for chunk in chunks))
                for chunks in self.learner_assigned_feature_chunks.values()
            )
        )
        benign_names = sorted([name for name in self.tsieve.learners if self.tsieve.is_benign_learner(name)])
        ordered_learners = sorted(self.learner_assigned_feature_chunks.keys(), key=self._learner_order_key)
        eps = 1e-12

        for learner_name in ordered_learners:
            chunks = self.learner_assigned_feature_chunks.get(learner_name, [])
            if not chunks:
                continue
            samples = chunks[0] if len(chunks) == 1 else np.concatenate(chunks, axis=0)
            n_samples = int(samples.shape[0])
            assignment_share = self._safe_div(n_samples, total_samples)

            own_threshold = float("nan")
            own_loss_mean = float("nan")
            own_loss_median = float("nan")
            own_loss_p95 = float("nan")
            own_exceed_rate = float("nan")

            learner_obj = self.tsieve.learners.get(learner_name)
            if learner_obj is not None:
                own_losses = learner_obj.reconstruction_loss(samples)
                own_threshold = float(learner_obj.threshold)
                if self.tsieve.is_benign_learner(learner_name):
                    own_threshold = own_threshold * self.tsieve.benign_accept_scale
                own_loss_mean = float(np.mean(own_losses))
                own_loss_median = float(np.median(own_losses))
                own_loss_p95 = float(np.quantile(own_losses, 0.95))
                own_exceed_rate = float(np.mean(own_losses > own_threshold))

            benign_accept_rate = float("nan")
            benign_prob_mean = float("nan")
            benign_prob_p10 = float("nan")
            benign_margin_median = float("nan")
            benign_margin_p10 = float("nan")
            if benign_names:
                margins: List[np.ndarray] = []
                accepts: List[np.ndarray] = []
                probs: List[np.ndarray] = []
                for bn in benign_names:
                    bl = self.tsieve.learners[bn]
                    bth = float(bl.threshold) * self.tsieve.benign_accept_scale
                    bloss = bl.reconstruction_loss(samples)
                    margin = (bth - bloss) / (abs(bth) + eps)
                    margins.append(margin)
                    accepts.append(bloss <= bth)
                    probs.append(1.0 / (1.0 + np.exp(-self.risk_soft_k * margin)))
                margin_mat = np.vstack(margins)
                accept_mat = np.vstack(accepts)
                prob_mat = np.vstack(probs)
                best_margin = np.max(margin_mat, axis=0)
                any_accept = np.any(accept_mat, axis=0)
                best_prob = np.max(prob_mat, axis=0)
                benign_accept_rate = float(np.mean(any_accept))
                benign_prob_mean = float(np.mean(best_prob))
                benign_prob_p10 = float(np.quantile(best_prob, 0.10))
                benign_margin_median = float(np.median(best_margin))
                benign_margin_p10 = float(np.quantile(best_margin, 0.10))

            risk_from_benign_reject = (
                0.5 if not np.isfinite(benign_accept_rate) else (1.0 - benign_accept_rate)
            )
            risk_from_own_exceed = 1.0 if not np.isfinite(own_exceed_rate) else own_exceed_rate
            margin_risk = 0.5
            if np.isfinite(benign_margin_median):
                # Positive margin means safer (inside BENIGN boundary); negative means risky.
                margin_risk = float(1.0 / (1.0 + np.exp(4.0 * benign_margin_median)))

            risk_score = float(
                0.55 * risk_from_benign_reject
                + 0.30 * risk_from_own_exceed
                + 0.15 * margin_risk
            )
            risk_from_benign_prob = (
                0.5 if not np.isfinite(benign_prob_mean) else (1.0 - benign_prob_mean)
            )
            risk_score_v2 = float(
                0.70 * risk_from_benign_prob
                + 0.20 * risk_from_own_exceed
                + 0.10 * margin_risk
            )

            tail_heaviness = float("nan")
            if learner_obj is not None:
                p50 = float(np.quantile(own_losses, 0.50))
                p90 = float(np.quantile(own_losses, 0.90))
                p99 = float(np.quantile(own_losses, 0.99))
                tail_heaviness = float((p99 - p90) / (abs(p90 - p50) + eps))
            tail_risk = 0.5 if not np.isfinite(tail_heaviness) else float(
                1.0 / (1.0 + np.exp(-1.5 * (tail_heaviness - 2.0)))
            )
            risk_benign_v3 = float(
                0.65 * (0.5 if not np.isfinite(benign_prob_mean) else (1.0 - benign_prob_mean))
                + 0.35 * (0.5 if not np.isfinite(benign_prob_p10) else (1.0 - benign_prob_p10))
            )
            risk_self_v3 = float(0.60 * risk_from_own_exceed + 0.40 * tail_risk)
            risk_overlap_v3 = float(overlap_risk_map.get(learner_name, 0.0))
            risk_stability_v3 = float(stability_risk_map.get(learner_name, 0.0))
            size_confidence = float(1.0 - np.exp(-n_samples / 5000.0))
            risk_size_v3 = float(1.0 - size_confidence)
            risk_score_v3_raw = float(
                0.35 * risk_benign_v3
                + 0.25 * risk_self_v3
                + 0.20 * risk_overlap_v3
                + 0.15 * risk_stability_v3
                + 0.05 * risk_size_v3
            )
            # Confidence shrinkage: small-sample learners are pulled toward neutral 0.5.
            risk_score_v3 = float(0.5 + size_confidence * (risk_score_v3_raw - 0.5))

            rows.append(
                {
                    "learner_name": learner_name,
                    "total_assigned_samples": n_samples,
                    "assignment_share": assignment_share,
                    "own_threshold": self._to_builtin_float(own_threshold),
                    "own_loss_mean": self._to_builtin_float(own_loss_mean),
                    "own_loss_median": self._to_builtin_float(own_loss_median),
                    "own_loss_p95": self._to_builtin_float(own_loss_p95),
                    "own_exceed_rate": self._to_builtin_float(own_exceed_rate),
                    "benign_accept_rate": self._to_builtin_float(benign_accept_rate),
                    "benign_prob_mean": self._to_builtin_float(benign_prob_mean),
                    "benign_prob_p10": self._to_builtin_float(benign_prob_p10),
                    "benign_margin_median": self._to_builtin_float(benign_margin_median),
                    "benign_margin_p10": self._to_builtin_float(benign_margin_p10),
                    "risk_score": risk_score,
                    "risk_band": self._risk_band(risk_score),
                    "risk_score_v2": risk_score_v2,
                    "risk_band_v2": self._risk_band(risk_score_v2),
                    "risk_benign_v3": risk_benign_v3,
                    "risk_self_v3": risk_self_v3,
                    "risk_overlap_v3": risk_overlap_v3,
                    "risk_stability_v3": risk_stability_v3,
                    "risk_size_v3": risk_size_v3,
                    "tail_heaviness": self._to_builtin_float(tail_heaviness),
                    "size_confidence": size_confidence,
                    "risk_score_v3_raw": risk_score_v3_raw,
                    "risk_score_v3": risk_score_v3,
                    "risk_band_v3": self._risk_band(risk_score_v3),
                    "risk_score_version": "unsupervised_v1_v2_v3",
                }
            )

        v3_scores = np.asarray(
            [self._to_builtin_float(r.get("risk_score_v3", float("nan"))) for r in rows],
            dtype=np.float64,
        )
        finite_scores = v3_scores[np.isfinite(v3_scores)]
        if finite_scores.size > 0:
            q_high = float(np.quantile(finite_scores, 0.80))
            q_mid = float(np.quantile(finite_scores, 0.50))
            for r in rows:
                s = self._to_builtin_float(r.get("risk_score_v3", float("nan")))
                if not np.isfinite(s):
                    band_q = "UNKNOWN"
                elif s >= q_high:
                    band_q = "HIGH"
                elif s >= q_mid:
                    band_q = "MEDIUM"
                else:
                    band_q = "LOW"
                r["risk_band_v3_quantile"] = band_q

        rows.sort(
            key=lambda r: (
                -self._to_builtin_float(r.get("risk_score_v3", float("nan"))),
                -int(r.get("total_assigned_samples", 0)),
            )
        )
        return rows

    def _append_history_pool(self, learner_name: str, samples: np.ndarray) -> None:
        if len(samples) == 0:
            return
        prev = self.learner_history_pool.get(learner_name)
        merged = samples.copy() if prev is None or len(prev) == 0 else np.concatenate([prev, samples], axis=0)
        if (
            self.history_pool_compress_enabled
            and self.max_history_samples_per_learner > 0
            and len(merged) > self.max_history_samples_per_learner
        ):
            merged = self.tsieve.interval_sample_by_loss(
                learner_name,
                merged,
                keep_count=self.max_history_samples_per_learner,
            )
        self.learner_history_pool[learner_name] = merged.astype(np.float32, copy=False)

    def _sample_history_for_update(self, learner_name: str, feature_dim: int) -> np.ndarray:
        hist = self.learner_history_pool.get(learner_name)
        if hist is None or len(hist) == 0:
            return np.empty((0, feature_dim), dtype=np.float32)
        keep_count = int(len(hist) * self.history_sample_rate)
        keep_count = max(1, keep_count)
        keep_count = min(keep_count, self.history_samples_per_update, len(hist))
        if keep_count <= 0:
            return np.empty((0, feature_dim), dtype=np.float32)
        if keep_count >= len(hist):
            return hist.astype(np.float32, copy=False)
        if self.history_time_decay_lambda > 0.0:
            # Recency-weighted sampling without replacement:
            # newer samples (near tail of history pool) have higher probability.
            n = len(hist)
            age = np.arange(n - 1, -1, -1, dtype=np.float64)  # newest age=0, oldest age=n-1
            weights = np.exp(-self.history_time_decay_lambda * age)
            weights_sum = float(np.sum(weights))
            if np.isfinite(weights_sum) and weights_sum > 0.0:
                probs = weights / weights_sum
                idx = np.random.choice(n, size=keep_count, replace=False, p=probs)
                sampled = hist[idx]
                return sampled.astype(np.float32, copy=False)
        sampled = self.tsieve.interval_sample_by_loss(learner_name, hist, keep_count=keep_count)
        return sampled.astype(np.float32, copy=False)

    def _estimate_benign_prob_mean(self, samples: np.ndarray, soft_k: float = 4.0) -> float:
        if len(samples) == 0:
            return float("nan")
        benign_names = sorted([name for name in self.tsieve.learners if self.tsieve.is_benign_learner(name)])
        if not benign_names:
            return float("nan")
        probs: List[np.ndarray] = []
        eps = 1e-12
        for bn in benign_names:
            bl = self.tsieve.learners[bn]
            bth = float(bl.threshold) * self.tsieve.benign_accept_scale
            bloss = bl.reconstruction_loss(samples)
            margin = (bth - bloss) / (abs(bth) + eps)
            probs.append(1.0 / (1.0 + np.exp(-soft_k * margin)))
        prob_mat = np.vstack(probs)
        best_prob = np.max(prob_mat, axis=0)
        return float(np.mean(best_prob))

    def _compute_feature_drift_score(self, learner_name: str, new_samples: np.ndarray) -> float:
        """
        Compare new samples against learner history distribution.
        Returns a non-negative drift score. Larger means stronger drift.
        """
        if len(new_samples) == 0:
            return float("nan")
        hist = self.learner_history_pool.get(str(learner_name))
        if hist is None or len(hist) < self.increment_drift_min_history_samples:
            return float("nan")
        hist_arr = np.asarray(hist, dtype=np.float32)
        new_arr = np.asarray(new_samples, dtype=np.float32)
        if hist_arr.ndim != 2 or new_arr.ndim != 2 or hist_arr.shape[1] != new_arr.shape[1]:
            return float("nan")
        eps = 1e-6
        mu_hist = np.mean(hist_arr, axis=0)
        mu_new = np.mean(new_arr, axis=0)
        std_hist = np.std(hist_arr, axis=0)
        std_new = np.std(new_arr, axis=0)
        z_mean_shift = np.abs(mu_new - mu_hist) / (std_hist + eps)
        z_std_shift = np.abs(std_new - std_hist) / (std_hist + eps)
        score = 0.7 * float(np.mean(z_mean_shift)) + 0.3 * float(np.mean(z_std_shift))
        if not np.isfinite(score):
            return float("nan")
        return float(max(0.0, score))

    def _evaluate_cluster_purity_gate(self, samples: np.ndarray) -> Dict[str, object]:
        """
        Evaluate whether a candidate new-class cluster is too BENIGN-like.
        If gate is disabled or BENIGN anchors are unavailable, pass-through by default.
        """
        if len(samples) == 0:
            return {
                "passed": False,
                "reason_codes": ["empty_cluster"],
                "benign_accept_rate": float("nan"),
                "benign_prob_mean": float("nan"),
                "benign_prob_p90": float("nan"),
                "benign_prob_p10": float("nan"),
                "structure_silhouette": float("nan"),
                "structure_split_gain": float("nan"),
                "structure_child_ratio": float("nan"),
                "route_multi_accept_ratio": float("nan"),
                "route_top1_share": float("nan"),
            }

        benign_names = sorted(
            [name for name in self.tsieve.learners if self.tsieve.is_benign_learner(name)]
        )
        if not benign_names:
            return {
                "passed": True,
                "reason_codes": ["no_benign_anchor_skip"],
                "benign_accept_rate": float("nan"),
                "benign_prob_mean": float("nan"),
                "benign_prob_p90": float("nan"),
                "benign_prob_p10": float("nan"),
                "structure_silhouette": float("nan"),
                "structure_split_gain": float("nan"),
                "structure_child_ratio": float("nan"),
                "route_multi_accept_ratio": float("nan"),
                "route_top1_share": float("nan"),
            }

        probs: List[np.ndarray] = []
        accepts: List[np.ndarray] = []
        eps = 1e-12
        for bn in benign_names:
            bl = self.tsieve.learners[bn]
            bth = float(bl.threshold) * self.tsieve.benign_accept_scale
            bloss = bl.reconstruction_loss(samples)
            margin = (bth - bloss) / (abs(bth) + eps)
            probs.append(1.0 / (1.0 + np.exp(-self.cluster_gate_soft_k * margin)))
            accepts.append(bloss <= bth)

        prob_mat = np.vstack(probs)
        accept_mat = np.vstack(accepts)
        best_prob = np.max(prob_mat, axis=0)
        any_accept = np.any(accept_mat, axis=0)

        benign_accept_rate = float(np.mean(any_accept))
        benign_prob_mean = float(np.mean(best_prob))
        benign_prob_p90 = float(np.quantile(best_prob, 0.90))
        benign_prob_p10 = float(np.quantile(best_prob, 0.10))

        reason_codes: List[str] = []
        if benign_accept_rate > self.cluster_gate_max_benign_accept_rate:
            reason_codes.append("benign_accept_rate_exceed")
        if benign_prob_mean > self.cluster_gate_max_benign_prob_mean:
            reason_codes.append("benign_prob_mean_exceed")
        if benign_prob_p90 > self.cluster_gate_max_benign_prob_p90:
            reason_codes.append("benign_prob_p90_exceed")
        if self.cluster_gate_mixed_check_enabled:
            if (
                benign_prob_p10 < self.cluster_gate_mixed_prob_low
                and benign_prob_p90 > self.cluster_gate_mixed_prob_high
            ):
                reason_codes.append("mixed_benign_prob_band")

        structure_silhouette = float("nan")
        structure_split_gain = float("nan")
        structure_child_ratio = float("nan")
        if self.cluster_gate_structure_check_enabled and len(samples) >= self.cluster_gate_structure_min_samples:
            x = np.asarray(samples, dtype=np.float32)
            # normalize per-feature for stable geometry check
            mu = np.mean(x, axis=0, keepdims=True)
            sd = np.std(x, axis=0, keepdims=True)
            z = (x - mu) / (sd + 1e-6)
            # one-cluster inertia
            c1 = np.mean(z, axis=0, keepdims=True)
            inertia1 = float(np.sum((z - c1) ** 2))
            if np.isfinite(inertia1) and inertia1 > 1e-9:
                km = KMeans(n_clusters=2, random_state=int(self.cfg["runtime"]["seed"]), n_init=10)
                cid = km.fit_predict(z)
                n0 = int(np.sum(cid == 0))
                n1 = int(np.sum(cid == 1))
                structure_child_ratio = float(min(n0, n1) / max(1, len(cid)))
                inertia2 = float(km.inertia_)
                structure_split_gain = float(1.0 - (inertia2 / inertia1))
                if n0 > 1 and n1 > 1:
                    structure_silhouette = float(silhouette_score(z, cid))
                else:
                    structure_silhouette = 0.0
                if (
                    structure_child_ratio >= self.cluster_gate_structure_min_child_ratio
                    and structure_silhouette >= self.cluster_gate_structure_min_silhouette
                    and structure_split_gain >= self.cluster_gate_structure_min_split_gain
                ):
                    reason_codes.append("mixed_structure_splitable")

        route_multi_accept_ratio = float("nan")
        route_top1_share = float("nan")
        if (
            self.cluster_gate_route_consistency_enabled
            and len(samples) >= self.cluster_gate_route_min_samples
            and len(self.tsieve.learners) >= 2
        ):
            margins: List[np.ndarray] = []
            eps = 1e-12
            learner_names = sorted(self.tsieve.learners.keys())
            for lname in learner_names:
                learner = self.tsieve.learners[lname]
                threshold = float(learner.threshold)
                if self.tsieve.is_benign_learner(lname):
                    threshold = threshold * self.tsieve.benign_accept_scale
                losses = learner.reconstruction_loss(samples)
                margin = (threshold - losses) / (abs(threshold) + eps)
                margins.append(margin)
            margin_mat = np.vstack(margins)  # [n_learners, n_samples]
            accept_mat = margin_mat >= 0.0
            accept_count = np.sum(accept_mat, axis=0)
            route_multi_accept_ratio = float(np.mean(accept_count >= 2))
            winners = np.argmax(margin_mat, axis=0)
            if winners.size > 0:
                binc = np.bincount(winners, minlength=margin_mat.shape[0])
                route_top1_share = float(np.max(binc) / len(winners))
            if (
                route_multi_accept_ratio >= self.cluster_gate_route_min_multi_accept_ratio
                and route_top1_share <= self.cluster_gate_route_max_top1_share
            ):
                reason_codes.append("mixed_route_inconsistent")

        return {
            "passed": len(reason_codes) == 0,
            "reason_codes": reason_codes,
            "benign_accept_rate": benign_accept_rate,
            "benign_prob_mean": benign_prob_mean,
            "benign_prob_p90": benign_prob_p90,
            "benign_prob_p10": benign_prob_p10,
            "structure_silhouette": structure_silhouette,
            "structure_split_gain": structure_split_gain,
            "structure_child_ratio": structure_child_ratio,
            "route_multi_accept_ratio": route_multi_accept_ratio,
            "route_top1_share": route_top1_share,
        }

    def _create_new_learners_from_clusters(
        self,
        clusters: List[Tuple[np.ndarray, np.ndarray, List[Dict[str, Any]]]],
        data: pd.DataFrame,
        left: int,
        right: int,
        window_size: int,
        accepted_by_learner: Dict[str, List[np.ndarray]],
        accepted_labels_by_learner: Dict[str, List[str]],
        accepted_meta_by_learner: Dict[str, List[Dict[str, object]]],
        source: str,
    ) -> float:
        create_seconds = 0.0
        for cluster_x, cluster_labels, cluster_metas in clusters:
            cluster_labels_arr = np.asarray(cluster_labels, dtype=object)
            meta_list_cast: List[Dict[str, Any]] = [dict(m) for m in cluster_metas]
            if self.cluster_purity_gate_enabled:
                self.cluster_gate_stats["cluster_gate_checked_count"] += 1
                gate = self._evaluate_cluster_purity_gate(cluster_x)
                if not bool(gate.get("passed", True)):
                    self.cluster_gate_stats["cluster_gate_reject_count"] += 1
                    label_dist = self._label_distribution(cluster_labels_arr)
                    self.logger.info(
                        "[NewLearnerGateReject][%s] cluster_size=%d reasons=%s label_dist=%s",
                        str(source),
                        int(len(cluster_x)),
                        ",".join([str(x) for x in gate.get("reason_codes", [])]),
                        label_dist,
                    )
                    if self.cluster_gate_rejected_action == "reinject_unknown":
                        for i_rej in range(len(cluster_x)):
                            reinj_meta = meta_list_cast[i_rej] if i_rej < len(meta_list_cast) else {}
                            self.tmagnifier.add_unknown(
                                cluster_x[i_rej],
                                str(cluster_labels_arr[i_rej]),
                                reinj_meta,
                            )
                        self.cluster_gate_stats["cluster_gate_reinject_unknown_samples"] += float(
                            len(cluster_x)
                        )
                    else:
                        self.cluster_gate_stats["cluster_gate_drop_samples"] += float(len(cluster_x))
                    continue
                self.cluster_gate_stats["cluster_gate_pass_count"] += 1

            name = f"NEW_{self.next_new_id}"
            self.next_new_id += 1
            t_create_start = perf_counter()
            ok = self.tsieve.add_learner(name, cluster_x, epochs=self.cfg["tsieve"]["new_class_epochs"])
            t_create_end = perf_counter()
            create_seconds += t_create_end - t_create_start
            if not ok:
                continue

            self.debug_overlap_accept_count.setdefault(name, 0)
            current_window_id = int(left // max(1, window_size))
            self.learner_birth_window[str(name)] = current_window_id
            self.learner_last_trained_row_index[str(name)] = int(max(0, right - 1))
            self.learner_retrain_counts[str(name)] = 0
            self.perf_stats["new_learner_count"] += 1
            accepted_by_learner.setdefault(name, [])
            accepted_labels_by_learner.setdefault(name, [])
            accepted_meta_by_learner.setdefault(name, [])
            self._log_learner_distribution(stage="new", learner_name=name, labels=cluster_labels_arr)
            self._append_train_batch_profile(
                stage="new",
                learner_name=name,
                labels=cluster_labels_arr,
                window_left=int(left),
                window_right=int(right),
                hist_sample_count=0,
                new_sample_count=int(len(cluster_labels_arr)),
                update_total_count=int(len(cluster_labels_arr)),
            )
            self._append_fit_loss_profile(
                stage="new",
                learner_name=name,
                window_left=int(left),
                window_right=int(right),
                sample_count=int(len(cluster_labels_arr)),
                epoch_losses=[float(x) for x in self.tsieve.last_add_train_trace.get("epoch_losses", [])],
                epoch_val_losses=[
                    float(x) for x in self.tsieve.last_add_train_trace.get("epoch_val_losses", [])
                ],
            )
            self._accumulate_learner_distribution(learner_name=name, labels=cluster_labels_arr)
            self._record_learner_samples(
                learner_name=name, samples=cluster_x, labels=cluster_labels_arr
            )
            self._record_learner_creation_flow_preview(
                data=data,
                learner_name=name,
                creation_source=str(source),
                window_left=int(left),
                window_right=int(right),
                cluster_size=int(len(cluster_labels_arr)),
                cluster_metas=meta_list_cast,
                cluster_labels=cluster_labels_arr,
            )
            self._append_history_pool(name, cluster_x)
            if self.increment_iforest_guard_enabled:
                self._fit_increment_iforest_guard(str(name), cluster_x)
            self.logger.info(
                "[NewLearner][%s] %s, samples=%d, total_learners=%d",
                str(source),
                name,
                len(cluster_x),
                len(self.tsieve.learners),
            )
        return create_seconds

    def _collect_recluster_payload(
        self,
        learner_names: List[str],
        accepted_by_learner: Dict[str, List[np.ndarray]],
        accepted_labels_by_learner: Dict[str, List[str]],
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Gather samples for small-learner recluster; keep original LabelNorm per row."""
        sample_chunks: List[np.ndarray] = []
        payload_labels: List[str] = []
        for learner_name in learner_names:
            lname = str(learner_name)
            feat_chunks = self.learner_assigned_feature_chunks.get(lname, [])
            label_chunks = self.learner_assigned_label_chunks.get(lname, [])
            if len(label_chunks) != len(feat_chunks):
                self.logger.warning(
                    "[SmallLearnerRecluster] learner=%s missing per-sample labels for %d/%d "
                    "feature chunks; those chunks are skipped",
                    lname,
                    len(feat_chunks) - len(label_chunks),
                    len(feat_chunks),
                )
            for chunk_idx, chunk in enumerate(feat_chunks):
                if chunk_idx >= len(label_chunks):
                    continue
                arr = np.asarray(chunk, dtype=np.float32)
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                if len(arr) == 0:
                    continue
                lbls = np.asarray(label_chunks[chunk_idx], dtype=object).reshape(-1)
                if len(lbls) != int(arr.shape[0]):
                    self.logger.warning(
                        "[SmallLearnerRecluster] learner=%s chunk %d label/sample mismatch "
                        "(%d vs %d); skip chunk",
                        lname,
                        chunk_idx,
                        len(lbls),
                        int(arr.shape[0]),
                    )
                    continue
                sample_chunks.append(arr)
                payload_labels.extend(str(x) for x in lbls)
            pending = accepted_by_learner.get(lname, [])
            pending_labels = accepted_labels_by_learner.get(lname, [])
            if pending:
                arr_pending = np.stack(pending, axis=0).astype(np.float32, copy=False)
                if len(arr_pending) > 0:
                    if len(pending_labels) != int(arr_pending.shape[0]):
                        raise ValueError(
                            f"pending label count {len(pending_labels)} != "
                            f"pending sample count {arr_pending.shape[0]} for learner {lname}"
                        )
                    sample_chunks.append(arr_pending)
                    payload_labels.extend(str(x) for x in pending_labels)
        if not sample_chunks:
            return np.empty((0, 0), dtype=np.float32), np.empty((0,), dtype=object)
        merged = np.concatenate(sample_chunks, axis=0).astype(np.float32, copy=False)
        labels = np.asarray(payload_labels, dtype=object)
        return merged, labels

    def _destroy_learner_for_recluster(self, learner_name: str) -> None:
        name = str(learner_name)
        self.tsieve.learners.pop(name, None)
        self.tsieve.benign_anchor_names.discard(name)
        self.benign_anchor_learners.discard(name)
        self.learner_history_pool.pop(name, None)
        self.increment_iforest_guards.pop(name, None)
        self.learner_last_trained_row_index.pop(name, None)
        self.learner_retrain_counts.pop(name, None)
        self.learner_birth_window.pop(name, None)
        self.learner_creation_sample_count.pop(name, None)
        self.learner_cumulative_counts.pop(name, None)
        self.learner_assigned_feature_chunks.pop(name, None)
        self.learner_assigned_label_chunks.pop(name, None)
        self._learner_creation_row_indices.pop(name, None)
        self.debug_overlap_accept_count.pop(name, None)
        if self.debug_overlap_pair_intersections:
            drop_keys = [k for k in self.debug_overlap_pair_intersections.keys() if name in k]
            for k in drop_keys:
                self.debug_overlap_pair_intersections.pop(k, None)

    def _maybe_recluster_small_learners(
        self,
        data: pd.DataFrame,
        left: int,
        right: int,
        window_size: int,
        accepted_by_learner: Dict[str, List[np.ndarray]],
        accepted_labels_by_learner: Dict[str, List[str]],
        accepted_meta_by_learner: Dict[str, List[Dict[str, object]]],
    ) -> float:
        if not self.small_learner_recluster_enabled:
            return 0.0
        if self.small_learner_sample_threshold <= 0:
            return 0.0

        candidates: List[Tuple[str, int]] = []
        for learner_name in list(self.tsieve.learners.keys()):
            lname = str(learner_name)
            if not lname.startswith("NEW_"):
                continue
            base_total = int(sum(self.learner_cumulative_counts.get(lname, {}).values()))
            pending_total = int(len(accepted_labels_by_learner.get(lname, [])))
            total = int(base_total + pending_total)
            if 0 < total < self.small_learner_sample_threshold:
                candidates.append((lname, total))

        if len(candidates) <= self.small_learner_recluster_count_trigger:
            return 0.0

        candidate_names = [x[0] for x in sorted(candidates, key=lambda t: (t[1], t[0]))]
        payload_x, payload_labels = self._collect_recluster_payload(
            learner_names=candidate_names,
            accepted_by_learner=accepted_by_learner,
            accepted_labels_by_learner=accepted_labels_by_learner,
        )
        if len(payload_x) == 0:
            return 0.0

        for learner_name in candidate_names:
            accepted_by_learner.pop(learner_name, None)
            accepted_labels_by_learner.pop(learner_name, None)
            accepted_meta_by_learner.pop(learner_name, None)
            self._destroy_learner_for_recluster(learner_name)

        for i in range(len(payload_x)):
            self.tmagnifier.add_unknown(
                payload_x[i],
                str(payload_labels[i]),
                {"note": "small_learner_recluster_payload"},
            )

        self.logger.info(
            (
                "[SmallLearnerRecluster] destroyed=%d sample_threshold=%d trigger=%d "
                "reinjected_samples=%d remaining_learners=%d"
            ),
            int(len(candidate_names)),
            int(self.small_learner_sample_threshold),
            int(self.small_learner_recluster_count_trigger),
            int(len(payload_x)),
            int(len(self.tsieve.learners)),
        )

        recluster_clusters = self.tmagnifier.pop_new_class_clusters()
        if not recluster_clusters:
            return 0.0
        return self._create_new_learners_from_clusters(
            clusters=recluster_clusters,
            data=data,
            left=left,
            right=right,
            window_size=window_size,
            accepted_by_learner=accepted_by_learner,
            accepted_labels_by_learner=accepted_labels_by_learner,
            accepted_meta_by_learner=accepted_meta_by_learner,
            source="small_learner_recluster",
        )

    def _compute_own_exceed_rate(self, learner_name: str, samples: np.ndarray) -> float:
        if len(samples) == 0:
            return float("nan")
        learner = self.tsieve.learners.get(learner_name)
        if learner is None:
            return float("nan")
        losses = learner.reconstruction_loss(samples)
        threshold = float(learner.threshold)
        if self.tsieve.is_benign_learner(learner_name):
            threshold = threshold * self.tsieve.benign_accept_scale
        return float(np.mean(losses > threshold))

    def _compute_increment_route_confidence(
        self, learner_name: str, samples: np.ndarray
    ) -> Dict[str, object]:
        if len(samples) == 0:
            return {
                "valid": False,
                "keep_mask": np.zeros(0, dtype=bool),
                "confident_ratio": float("nan"),
                "own_margin_p10": float("nan"),
                "gap_p10": float("nan"),
            }
        names, losses_matrix, thresholds = self.tsieve._batch_losses_and_thresholds(samples)
        if len(names) < 2 or learner_name not in names:
            return {
                "valid": False,
                "keep_mask": np.ones(len(samples), dtype=bool),
                "confident_ratio": float("nan"),
                "own_margin_p10": float("nan"),
                "gap_p10": float("nan"),
            }
        idx = int(names.index(learner_name))
        eps = 1e-12
        margins = (thresholds[:, None] - losses_matrix) / (np.abs(thresholds[:, None]) + eps)
        own_margin = margins[idx]
        if len(names) > 1:
            other_margins = np.delete(margins, idx, axis=0)
            other_best_margin = np.max(other_margins, axis=0)
        else:
            other_best_margin = np.full(len(samples), -np.inf, dtype=np.float64)
        gap = own_margin - other_best_margin
        keep_mask = (own_margin >= self.increment_route_min_own_margin) & (
            gap >= self.increment_route_min_margin_gap
        )
        return {
            "valid": True,
            "keep_mask": keep_mask.astype(bool, copy=False),
            "confident_ratio": float(np.mean(keep_mask)),
            "own_margin_p10": float(np.quantile(own_margin, 0.10)),
            "gap_p10": float(np.quantile(gap, 0.10)),
        }

    def _fit_increment_iforest_guard(self, learner_name: str, seed_samples: np.ndarray) -> bool:
        x = np.asarray(seed_samples, dtype=np.float32)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        if len(x) < max(32, self.increment_iforest_guard_min_samples // 2):
            return False
        if len(x) > self.increment_iforest_guard_train_max_samples:
            idx = np.random.choice(
                len(x),
                size=self.increment_iforest_guard_train_max_samples,
                replace=False,
            )
            x = x[idx]
        model = IsolationForest(
            n_estimators=int(self.increment_iforest_guard_n_estimators),
            random_state=int(self.cfg["runtime"]["seed"]),
            contamination="auto",
            n_jobs=-1,
        )
        model.fit(x)
        scores = model.score_samples(x)
        # Keep high-score (inlier-like) portion at inference time.
        q = float(np.clip(1.0 - self.increment_iforest_guard_keep_quantile, 0.01, 0.50))
        cutoff = float(np.quantile(scores, q))
        self.increment_iforest_guards[str(learner_name)] = {
            "model": model,
            "score_cutoff": cutoff,
            "seed_count": int(len(x)),
        }
        return True

    def _ensure_increment_iforest_guard(self, learner_name: str) -> bool:
        if str(learner_name) in self.increment_iforest_guards:
            return True
        seed = self.learner_history_pool.get(str(learner_name))
        if seed is None or len(seed) == 0:
            chunks = self.learner_assigned_feature_chunks.get(str(learner_name), [])
            if chunks:
                seed = np.concatenate(chunks, axis=0).astype(np.float32, copy=False)
        if seed is None or len(seed) == 0:
            return False
        ok = self._fit_increment_iforest_guard(str(learner_name), seed)
        if ok:
            self.logger.info(
                "[IncrementIForestGuardInit] learner=%s seed=%d keep_q=%.3f",
                str(learner_name),
                int(len(seed)),
                float(self.increment_iforest_guard_keep_quantile),
            )
        return ok

    def _apply_increment_iforest_guard(
        self, learner_name: str, samples: np.ndarray
    ) -> Dict[str, object]:
        if len(samples) == 0:
            return {
                "valid": False,
                "keep_mask": np.zeros(0, dtype=bool),
                "kept_ratio": float("nan"),
                "score_p10": float("nan"),
                "score_p50": float("nan"),
            }
        if not self._ensure_increment_iforest_guard(str(learner_name)):
            return {
                "valid": False,
                "keep_mask": np.ones(len(samples), dtype=bool),
                "kept_ratio": float("nan"),
                "score_p10": float("nan"),
                "score_p50": float("nan"),
            }
        guard = self.increment_iforest_guards.get(str(learner_name), {})
        model = guard.get("model")
        cutoff = float(guard.get("score_cutoff", float("-inf")))
        if model is None:
            return {
                "valid": False,
                "keep_mask": np.ones(len(samples), dtype=bool),
                "kept_ratio": float("nan"),
                "score_p10": float("nan"),
                "score_p50": float("nan"),
            }
        x = np.asarray(samples, dtype=np.float32)
        scores = model.score_samples(x)  # type: ignore[attr-defined]
        keep_mask = scores >= cutoff
        return {
            "valid": True,
            "keep_mask": keep_mask.astype(bool, copy=False),
            "kept_ratio": float(np.mean(keep_mask)),
            "score_p10": float(np.quantile(scores, 0.10)),
            "score_p50": float(np.quantile(scores, 0.50)),
        }

    def _sample_increment_new(
        self, learner_name: str, samples: np.ndarray, max_keep: int
    ) -> Tuple[np.ndarray, np.ndarray]:
        if len(samples) == 0:
            return samples, np.zeros(0, dtype=int)
        arr = samples
        selected_idx = np.arange(len(arr), dtype=int)
        q_keep = float(self.increment_low_loss_quantile_keep)
        q_keep = min(1.0, max(0.05, q_keep))
        if q_keep < 1.0:
            losses = self.tsieve.learners[learner_name].reconstruction_loss(arr)
            q_val = float(np.quantile(losses, q_keep))
            keep_mask = losses <= q_val
            arr_q = arr[keep_mask]
            if len(arr_q) > 0:
                selected_idx = selected_idx[keep_mask]
                arr = arr_q
        if len(arr) <= max_keep:
            return arr, selected_idx
        if self.increment_sampling_mode == "stratified_loss":
            losses = self.tsieve.learners[learner_name].reconstruction_loss(arr)
            sorted_idx = np.argsort(losses)
            n = len(sorted_idx)
            b1 = n // 3
            b2 = 2 * n // 3
            groups = [sorted_idx[:b1], sorted_idx[b1:b2], sorted_idx[b2:]]
            per = max(1, max_keep // 3)
            keep_parts: List[np.ndarray] = []
            for g in groups:
                if len(g) == 0:
                    continue
                k = min(len(g), per)
                pick = np.linspace(0, len(g) - 1, num=k, dtype=int)
                keep_parts.append(g[pick])
            keep_idx = np.concatenate(keep_parts) if keep_parts else sorted_idx[:max_keep]
            if len(keep_idx) > max_keep:
                keep_idx = keep_idx[:max_keep]
            return arr[keep_idx], selected_idx[keep_idx]
        idx = np.random.choice(len(arr), size=max_keep, replace=False)
        return arr[idx], selected_idx[idx]

    def _filter_benign_confident_mask(self, samples: np.ndarray) -> np.ndarray:
        """
        Keep mask of high-confidence BENIGN samples.
        Criterion: reconstruction_loss <= benign_history_confidence_scale * BENIGN threshold.
        """
        if len(samples) == 0:
            return np.zeros(0, dtype=bool)
        benign_names = sorted([name for name in self.tsieve.learners if self.tsieve.is_benign_learner(name)])
        if not benign_names:
            return np.ones(len(samples), dtype=bool)
        benign_learner = self.tsieve.learners[benign_names[0]]
        losses = benign_learner.reconstruction_loss(samples)
        # Use effective BENIGN acceptance threshold as baseline, then apply confidence scale.
        conf_th = float(
            benign_learner.threshold
            * self.tsieve.benign_accept_scale
            * self.benign_history_confidence_scale
        )
        return losses <= conf_th

    def _filter_benign_confident_samples(self, samples: np.ndarray) -> np.ndarray:
        if len(samples) == 0:
            return samples
        keep_mask = self._filter_benign_confident_mask(samples)
        return samples[keep_mask]

    def _compute_run_metrics(self, rows: List[Dict[str, object]]) -> Dict[str, Any]:
        actual_benign = 0
        actual_non_benign = 0
        unknown_benign = 0
        unknown_non_benign = 0
        benign_fp_risk = 0
        non_benign_to_benign = 0

        for row in rows:
            dist_raw = row.get("label_distribution_json")
            if not dist_raw:
                continue
            dist = json.loads(str(dist_raw))
            benign_count = int(sum(int(v) for k, v in dist.items() if is_benign_label(str(k))))
            total_count = int(sum(int(v) for v in dist.values()))
            non_benign_count = int(total_count - benign_count)
            learner_name = str(row.get("learner_name", ""))
            dominant_label = normalize_base_label(str(row.get("dominant_label", "")))

            actual_benign += benign_count
            actual_non_benign += non_benign_count

            if learner_name == "UNKNOWN":
                # UNKNOWN contributes to risk miss only, not risk false alarm.
                unknown_benign += benign_count
                unknown_non_benign += non_benign_count
                continue

            if dominant_label == "BENIGN":
                # Cluster is BENIGN-family by dominant label:
                # non-benign mixed into this cluster are risk misses.
                non_benign_to_benign += non_benign_count
            else:
                # Cluster is attack-family by dominant label:
                # benign mixed into this cluster are risk false alarms.
                benign_fp_risk += benign_count

        benign_base_for_fpr = int(max(actual_benign - unknown_benign, 0))
        risk_false_positive_rate = self._safe_div(benign_fp_risk, benign_base_for_fpr)
        risk_false_negative_rate = self._safe_div(
            non_benign_to_benign + unknown_non_benign,
            actual_non_benign,
        )

        return {
            "risk_false_positive_rate": risk_false_positive_rate,
            "risk_false_negative_rate": risk_false_negative_rate,
        }

    def _finalize_unknown_assignments(self) -> None:
        """
        Ensure all unknown traffic has an explicit destination in final statistics.
        All unknown samples are merged into one learner bucket: UNKNOWN.
        """
        merged_unknown_counts: Dict[str, int] = {}

        if self.tmagnifier.unknown_labels:
            remain_labels = np.asarray(self.tmagnifier.unknown_labels, dtype=object)
            remain_dist = self._label_distribution(remain_labels)
            for label, n in remain_dist.items():
                merged_unknown_counts[label] = int(merged_unknown_counts.get(label, 0) + int(n))
            self.logger.info(
                "[UnknownFinalize] remainder_unknown=%d",
                len(remain_labels),
            )

        dropped = self.tmagnifier.dropped_unknown_label_counts
        if dropped:
            for label, n in dropped.items():
                merged_unknown_counts[str(label)] = int(
                    merged_unknown_counts.get(str(label), 0) + int(n)
                )
            self.logger.info(
                "[UnknownFinalize] dropped_unknown=%d",
                int(sum(int(v) for v in dropped.values())),
            )

        if merged_unknown_counts:
            self._accumulate_learner_distribution_from_counts("UNKNOWN", merged_unknown_counts)
            self.logger.info(
                "[UnknownFinalize] merged_unknown_total=%d",
                int(sum(merged_unknown_counts.values())),
            )

    def _apply_attack_sampling(self, data: pd.DataFrame) -> pd.DataFrame:
        attack_sample_per_type = int(self.cfg["runtime"].get("attack_sample_per_type", 0))
        benign_sample_max_rows = int(self.cfg["runtime"].get("benign_sample_max_rows", 0))
        if attack_sample_per_type <= 0 and benign_sample_max_rows <= 0:
            return data

        sampled_frames: List[pd.DataFrame] = []
        benign_mask = data["LabelNorm"].map(is_benign_label)
        benign_df = data[benign_mask]
        attack_df = data[~benign_mask]
        rng_seed = int(self.cfg["runtime"]["seed"])

        if benign_sample_max_rows > 0 and len(benign_df) > benign_sample_max_rows:
            benign_df = benign_df.sample(n=benign_sample_max_rows, random_state=rng_seed)
        sampled_frames.append(benign_df)

        if attack_sample_per_type > 0:
            for attack_label, group in attack_df.groupby("LabelNorm", sort=True):
                if len(group) > attack_sample_per_type:
                    sampled_group = group.sample(n=attack_sample_per_type, random_state=rng_seed)
                else:
                    sampled_group = group
                sampled_frames.append(sampled_group)
                self.logger.info(
                    "[AttackSampling] label=%s, kept=%d, original=%d",
                    attack_label,
                    len(sampled_group),
                    len(group),
                )
        else:
            sampled_frames.append(attack_df)

        sampled = pd.concat(sampled_frames, ignore_index=True)
        sampled = sampled.sort_values("Timestamp").reset_index(drop=True)
        self.logger.info(
            "[AttackSampling] rows_before=%d, rows_after=%d, benign_after=%d",
            len(data),
            len(sampled),
            int(sampled["LabelNorm"].map(is_benign_label).sum()),
        )
        return sampled

    @staticmethod
    def _normalize_runtime_list(raw: Any) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, (list, tuple, set)):
            values = list(raw)
        else:
            values = [raw]
        normalized: List[str] = []
        for v in values:
            s = str(v).strip()
            if s:
                normalized.append(s)
        return normalized

    @staticmethod
    def _normalize_protocol_filter_tokens(values: List[str]) -> tuple[set[int], set[str]]:
        numeric: set[int] = set()
        symbolic: set[str] = set()
        for raw in values:
            token = str(raw).strip().lower()
            if not token:
                continue
            try:
                numeric.add(int(token))
                continue
            except ValueError:
                pass
            if token == "tcp":
                numeric.add(TCP_PROTOCOL_NUMBER)
                symbolic.add("tcp")
            elif token == "udp":
                numeric.add(UDP_PROTOCOL_NUMBER)
                symbolic.add("udp")
            elif token in {"other", "non_tcp", "non-tcp"}:
                symbolic.add("other")
            elif token in {"non_udp", "non-udp"}:
                symbolic.add("non_udp")
            else:
                symbolic.add(token)
        return numeric, symbolic

    def _apply_runtime_filters(self, data: pd.DataFrame) -> pd.DataFrame:
        if data.empty:
            return data

        filtered = data
        runtime_cfg = self.cfg.get("runtime", {})

        year_include_cfg = self._normalize_runtime_list(runtime_cfg.get("year_include"))
        if year_include_cfg:
            year_include = {str(y).strip() for y in year_include_cfg if str(y).strip()}
            if year_include:
                before_rows = int(len(filtered))
                year_series = filtered["LabelNorm"].map(lambda x: split_year_label(str(x))[0])
                filtered = filtered.loc[year_series.isin(year_include)].reset_index(drop=True)
                self.logger.info(
                    "[YearFilter] include=%s kept=%d/%d",
                    sorted(year_include),
                    int(len(filtered)),
                    before_rows,
                )

        year_benign_exclude_cfg = self._normalize_runtime_list(
            runtime_cfg.get("year_benign_exclude")
        )
        if year_benign_exclude_cfg:
            exclude_years = {str(y).strip() for y in year_benign_exclude_cfg if str(y).strip()}
            if exclude_years:
                before_rows = int(len(filtered))
                year_series = filtered["LabelNorm"].map(lambda x: split_year_label(str(x))[0])
                benign_mask = filtered["LabelNorm"].map(is_benign_label)
                drop_mask = year_series.isin(exclude_years) & benign_mask
                filtered = filtered.loc[~drop_mask].reset_index(drop=True)
                self.logger.info(
                    "[YearBenignFilter] exclude_years=%s dropped=%d kept=%d/%d",
                    sorted(exclude_years),
                    int(drop_mask.sum()),
                    int(len(filtered)),
                    before_rows,
                )

        attack_include_cfg = self._normalize_runtime_list(runtime_cfg.get("attack_type_include"))
        if attack_include_cfg:
            include_set = {
                normalize_base_label(v)
                for v in attack_include_cfg
                if str(v).strip()
            }
            if include_set:
                before_rows = int(len(filtered))
                base_series = filtered["LabelNorm"].map(lambda x: normalize_base_label(str(x)))
                benign_mask = base_series == "BENIGN"
                # Keep BENIGN by default; include list only gates attack classes.
                if "BENIGN" in include_set:
                    keep_mask = base_series.isin(include_set)
                else:
                    keep_mask = benign_mask | base_series.isin(include_set)
                filtered = filtered.loc[keep_mask].reset_index(drop=True)
                self.logger.info(
                    "[AttackTypeFilterInclude] include=%s kept=%d/%d",
                    sorted(include_set),
                    int(len(filtered)),
                    before_rows,
                )

        attack_exclude_cfg = self._normalize_runtime_list(runtime_cfg.get("attack_type_exclude"))
        if attack_exclude_cfg:
            exclude_set = {
                normalize_base_label(v)
                for v in attack_exclude_cfg
                if str(v).strip()
            }
            if exclude_set:
                before_rows = int(len(filtered))
                base_series = filtered["LabelNorm"].map(lambda x: normalize_base_label(str(x)))
                if "BENIGN" in exclude_set:
                    keep_mask = ~base_series.isin(exclude_set)
                else:
                    keep_mask = (base_series == "BENIGN") | (~base_series.isin(exclude_set))
                filtered = filtered.loc[keep_mask].reset_index(drop=True)
                self.logger.info(
                    "[AttackTypeFilterExclude] exclude=%s kept=%d/%d",
                    sorted(exclude_set),
                    int(len(filtered)),
                    before_rows,
                )

        protocol_include_cfg = self._normalize_runtime_list(runtime_cfg.get("protocol_include"))
        if protocol_include_cfg:
            if "Protocol" not in filtered.columns:
                self.logger.warning(
                    "[ProtocolFilterSkip] protocol_include configured but Protocol column missing"
                )
            else:
                proto_numeric, proto_symbolic = self._normalize_protocol_filter_tokens(protocol_include_cfg)
                known_symbolic = {"tcp", "udp", "other", "non_udp"}
                unknown_symbolic = sorted(proto_symbolic - known_symbolic)
                if unknown_symbolic:
                    self.logger.warning(
                        "[ProtocolFilterWarn] ignore unsupported symbolic tokens=%s",
                        unknown_symbolic,
                    )
                if proto_numeric or (proto_symbolic & {"other", "non_udp"}):
                    before_rows = int(len(filtered))
                    proto = pd.to_numeric(filtered["Protocol"], errors="coerce")
                    proto_round = proto.round()
                    keep_mask = pd.Series(False, index=filtered.index)
                    if proto_numeric:
                        keep_mask = keep_mask | proto_round.isin(proto_numeric)
                    if "other" in proto_symbolic:
                        keep_mask = keep_mask | (
                            proto_round.notna()
                            & (~proto_round.isin([TCP_PROTOCOL_NUMBER, UDP_PROTOCOL_NUMBER]))
                        )
                    if "non_udp" in proto_symbolic:
                        keep_mask = keep_mask | (
                            proto_round.notna()
                            & (proto_round != UDP_PROTOCOL_NUMBER)
                        )
                    filtered = filtered.loc[keep_mask].reset_index(drop=True)
                    self.logger.info(
                        "[ProtocolFilterInclude] include=%s kept=%d/%d",
                        protocol_include_cfg,
                        int(len(filtered)),
                        before_rows,
                    )
                else:
                    self.logger.warning(
                        "[ProtocolFilterSkip] no valid protocol_include tokens=%s",
                        protocol_include_cfg,
                    )

        return filtered

    def _load_dataset(self) -> Tuple[pd.DataFrame, np.ndarray, List[str]]:
        data_dir = Path(self.cfg["paths"]["data_dir"])
        input_files = self.cfg["paths"].get("input_files")
        files = ordered_data_files(data_dir, input_files=input_files)
        if not files:
            raise FileNotFoundError(f"No CIC2017 files found in {data_dir}")
        if input_files:
            self.logger.info("Configured input files: %s", ", ".join(input_files))
        dfs = []
        for f in files:
            self.logger.info("Load %s", f.name)
            chunk = pd.read_csv(f, low_memory=False)
            if "Label" not in chunk.columns:
                raise ValueError(f"Input file missing required column: Label ({f})")

            year_tag = infer_year_tag(f)
            raw_labels = chunk["Label"].astype(str).str.strip()
            missing_year_mask = ~raw_labels.map(has_year_prefix)

            if missing_year_mask.any():
                if year_tag != "0000":
                    chunk.loc[missing_year_mask, "Label"] = (
                        year_tag + "|" + raw_labels[missing_year_mask]
                    )
                    self.logger.info(
                        "[YearTag] file=%s year=%s tagged_rows=%d",
                        f.name,
                        year_tag,
                        int(missing_year_mask.sum()),
                    )
                else:
                    self.logger.warning(
                        "[YearTagSkip] file=%s unknown year, keep raw labels for %d rows",
                        f.name,
                        int(missing_year_mask.sum()),
                    )
            dfs.append(chunk)
        data = pd.concat(dfs, ignore_index=True)
        ts_raw = data["Timestamp"]
        try:
            # pandas >= 2.0: mixed can parse heterogeneous timestamp formats safely.
            data["Timestamp"] = pd.to_datetime(ts_raw, errors="coerce", format="mixed")
        except TypeError:
            # pandas < 2.0 fallback.
            data["Timestamp"] = pd.to_datetime(ts_raw, errors="coerce")
        ts_invalid = int(data["Timestamp"].isna().sum())
        if ts_invalid > 0:
            self.logger.warning(
                "[TimestampParse] invalid_timestamp_rows=%d (dropped after parse)",
                ts_invalid,
            )
        data = data.dropna(subset=["Timestamp"]).sort_values("Timestamp").reset_index(drop=True)
        data["LabelNorm"] = data["Label"].map(normalize_label)
        data = self._apply_runtime_filters(data)
        data = self._apply_attack_sampling(data)
        data = self._apply_missing_value_strategy(data)
        data = self._apply_drop_when_all_numeric_zero_rules(data)

        max_rows = self.cfg["runtime"]["max_rows"]
        if max_rows > 0 and len(data) > max_rows:
            data = data.iloc[:max_rows].reset_index(drop=True)

        feat_df, feature_cols = preprocess_features(data, feature_profile=self.feature_profile)
        x_all = feat_df.values.astype(np.float32)
        if self.pca_n_components > 0 and self.pca_n_components < x_all.shape[1]:
            pca = PCA(n_components=self.pca_n_components, random_state=int(self.cfg["runtime"]["seed"]))
            x_all = pca.fit_transform(x_all).astype(np.float32)
            feature_cols = [f"pca_{i:03d}" for i in range(x_all.shape[1])]
            self.logger.info(
                "[PCA] enabled n_components=%d explained_variance_ratio_sum=%.6f",
                self.pca_n_components,
                float(np.sum(pca.explained_variance_ratio_)),
            )
        self.logger.info(
            "Rows=%d, FeatureDim=%d, FeatureProfile=%s",
            len(data),
            len(feature_cols),
            self.feature_profile,
        )
        return data, x_all, feature_cols

    def _build_initial_learners(self, data: pd.DataFrame, x_all: np.ndarray) -> int:
        init_ratio = float(self.cfg["stream"]["init_ratio"])
        init_end = int(len(data) * init_ratio)
        init_end = max(init_end, 5000)
        init_end = min(init_end, len(data) - 1)
        init_benign_count_cfg = int(self.cfg["stream"].get("init_benign_count", 0) or 0)

        if self.cfg["stream"]["init_known_mode"] == "benign_only" and init_benign_count_cfg > 0:
            full_mask = data["LabelNorm"].map(is_benign_label).values
            init_benign_year = str(self.cfg["stream"].get("init_benign_year", "")).strip()
            if init_benign_year:
                year_mask = data["LabelNorm"].map(
                    lambda x: split_year_label(str(x))[0] == init_benign_year
                ).values
                full_mask = full_mask & year_mask
            eligible_idx = np.flatnonzero(full_mask)
            if len(eligible_idx) > 0:
                target_n = min(init_benign_count_cfg, int(len(eligible_idx)))
                required_end = int(eligible_idx[target_n - 1] + 1)
                init_end = max(init_end, required_end)
                init_end = min(init_end, len(data) - 1)

        df_init = data.iloc[:init_end].copy()
        df_init["_creation_row_index"] = np.arange(init_end, dtype=np.int64)
        x_init = x_all[:init_end]

        if self.cfg["stream"]["init_known_mode"] == "benign_only":
            mask = df_init["LabelNorm"].map(is_benign_label).values
            init_benign_year = str(self.cfg["stream"].get("init_benign_year", "")).strip()
            if init_benign_year:
                year_mask = df_init["LabelNorm"].map(
                    lambda x: split_year_label(str(x))[0] == init_benign_year
                ).values
                mask = mask & year_mask
                self.logger.info(
                    "[InitFilter] benign_only year=%s kept=%d/%d",
                    init_benign_year,
                    int(mask.sum()),
                    len(mask),
                )
            df_init = df_init[mask].reset_index(drop=True)
            x_init = x_init[mask]
            if init_benign_count_cfg > 0:
                keep_n = min(init_benign_count_cfg, len(df_init))
                df_init = df_init.iloc[:keep_n].reset_index(drop=True)
                x_init = x_init[:keep_n]
                self.logger.info(
                    "[InitBenignCount] requested=%d used=%d",
                    init_benign_count_cfg,
                    keep_n,
                )

        init_epochs = self.cfg["tsieve"]["init_epochs"]
        for label in df_init["LabelNorm"].unique().tolist():
            idx = np.where(df_init["LabelNorm"].values == label)[0]
            if len(idx) < self.cfg["tsieve"]["min_class_samples"]:
                continue
            t_create_start = perf_counter()
            ok = self.tsieve.add_learner(label, x_init[idx], epochs=init_epochs)
            t_create_end = perf_counter()
            self.perf_stats["init_create_learner_seconds_total"] += t_create_end - t_create_start
            if ok:
                self.debug_overlap_accept_count.setdefault(label, 0)
                self.learner_birth_window[str(label)] = 0
                if is_benign_label(str(label)):
                    self.benign_anchor_learners.add(str(label))
                learner_labels = df_init["LabelNorm"].values[idx]
                self._log_learner_distribution(stage="init", learner_name=label, labels=learner_labels)
                self._append_train_batch_profile(
                    stage="init",
                    learner_name=label,
                    labels=np.asarray(learner_labels, dtype=object),
                    window_left=0,
                    window_right=int(init_end),
                    hist_sample_count=0,
                    new_sample_count=int(len(learner_labels)),
                    update_total_count=int(len(learner_labels)),
                )
                self._append_fit_loss_profile(
                    stage="init",
                    learner_name=label,
                    window_left=0,
                    window_right=int(init_end),
                    sample_count=int(len(learner_labels)),
                    epoch_losses=[
                        float(x)
                        for x in self.tsieve.last_add_train_trace.get("epoch_losses", [])
                    ],
                    epoch_val_losses=[
                        float(x)
                        for x in self.tsieve.last_add_train_trace.get("epoch_val_losses", [])
                    ],
                )
                self._accumulate_learner_distribution(learner_name=label, labels=learner_labels)
                preview_k = min(int(len(idx)), int(LEARNER_CREATION_PREVIEW_FLOW_COUNT))
                sub_positions = idx[:preview_k]
                metas_preview = [{"row_index": int(df_init["_creation_row_index"].iloc[int(j)])} for j in sub_positions]
                labels_preview = df_init["LabelNorm"].values[sub_positions]
                metas_full_binding = [{"row_index": int(df_init["_creation_row_index"].iloc[int(j)])} for j in idx]
                self._record_learner_creation_flow_preview(
                    data=data,
                    learner_name=str(label),
                    creation_source="init",
                    window_left=0,
                    window_right=int(init_end),
                    cluster_size=int(len(idx)),
                    cluster_metas=metas_preview,
                    cluster_labels=np.asarray(labels_preview, dtype=object),
                    binding_metas=metas_full_binding,
                )
                self._record_learner_samples(
                    learner_name=label, samples=x_init[idx], labels=learner_labels
                )
                self._append_history_pool(label, x_init[idx])
                self.learner_last_trained_row_index[str(label)] = int(max(0, init_end - 1))
                if self.increment_iforest_guard_enabled:
                    self._fit_increment_iforest_guard(str(label), x_init[idx])
                self.logger.info(
                    "[Init] learner=%s, samples=%d, threshold=%.6f",
                    label,
                    len(idx),
                    self.tsieve.learners[label].threshold,
                )
        if not self.tsieve.learners:
            raise RuntimeError("No initial learners created")
        self.tsieve.set_benign_anchor_names(sorted(self.benign_anchor_learners))
        return init_end

    def _run_decision_tree_analysis(
        self,
        *,
        profile_df: pd.DataFrame,
        label_df: pd.DataFrame,
    ) -> None:
        from trident_stream.decision_tree_analysis import run_pipeline_decision_tree_analysis

        try:
            run_pipeline_decision_tree_analysis(
                self.output_dir,
                profile_df,
                label_df,
                self.cfg,
                logger=self.logger,
            )
        except Exception:
            self.logger.exception("Decision tree analysis failed (non-fatal).")

    def run(self) -> None:
        self._log_hyperparameters()
        self._learner_creation_flow_previews.clear()
        self._learner_creation_row_indices.clear()
        data, x_all, feature_cols = self._load_dataset()
        dataset_label_rows = self._build_dataset_label_distribution_rows(data)
        dataset_label_csv_path = self.output_dir / "dataset_label_distribution.csv"
        dataset_label_summary_path = self.output_dir / "dataset_label_distribution_summary.json"
        dataset_label_profile_df = pd.DataFrame(dataset_label_rows)
        dataset_label_feature_stats_df = self._build_dataset_label_feature_stats_df(
            data=data,
            feature_names=IMPORTANT_LEARNER_CLUSTER_FEATURES,
        )
        dataset_label_protocol_df = self._build_dataset_label_protocol_stats_df(data=data)
        if not dataset_label_feature_stats_df.empty:
            dataset_label_profile_df = dataset_label_profile_df.merge(
                dataset_label_feature_stats_df,
                on="label",
                how="left",
            )
        if not dataset_label_protocol_df.empty:
            dataset_label_profile_df = dataset_label_profile_df.merge(
                dataset_label_protocol_df,
                on="label",
                how="left",
            )
        if not dataset_label_profile_df.empty:
            numeric_cols = [
                c
                for c in dataset_label_profile_df.columns
                if c
                not in {
                    "label",
                    "is_benign",
                    "year_tag",
                    "base_label",
                    "protocol_cluster_type",
                }
            ]
            if numeric_cols:
                dataset_label_profile_df[numeric_cols] = (
                    dataset_label_profile_df[numeric_cols]
                    .replace([np.inf, -np.inf], np.nan)
                    .fillna(0.0)
                )
            if "protocol_cluster_type" in dataset_label_profile_df.columns:
                dataset_label_profile_df["protocol_cluster_type"] = (
                    dataset_label_profile_df["protocol_cluster_type"].fillna("UNKNOWN").astype(str)
                )
        dataset_label_profile_df.to_csv(dataset_label_csv_path, index=False)
        dataset_label_rows = dataset_label_profile_df.to_dict(orient="records")
        dataset_label_corr_rows = self._build_dataset_label_feature_correlation_rows(
            dataset_label_profile_df
        )
        dataset_label_corr_json_path = (
            self.output_dir / "dataset_label_feature_attack_correlation.json"
        )
        dataset_label_corr_fig_path = (
            self.output_dir / "dataset_label_feature_attack_correlation.png"
        )
        with open(dataset_label_corr_json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "feature_family": "important_label_features",
                    "feature_count": int(len(dataset_label_corr_rows)),
                    "top_k_default": 24,
                    "rows": dataset_label_corr_rows,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        self._save_dataset_label_feature_correlation_figure(
            rows=dataset_label_corr_rows,
            out_path=dataset_label_corr_fig_path,
            top_k=24,
        )
        benign_rows = int(sum(int(r["count"]) for r in dataset_label_rows if bool(r["is_benign"])))
        attack_rows = int(max(len(data) - benign_rows, 0))
        dataset_label_summary = {
            "total_rows": int(len(data)),
            "label_count": int(len(dataset_label_rows)),
            "benign_rows": benign_rows,
            "attack_rows": attack_rows,
            "benign_ratio": float(self._safe_div(benign_rows, len(data))),
            "attack_ratio": float(self._safe_div(attack_rows, len(data))),
            "top20_labels": dataset_label_rows[:20],
        }
        with open(dataset_label_summary_path, "w", encoding="utf-8") as f:
            json.dump(dataset_label_summary, f, ensure_ascii=False, indent=2)
        dataset_topology_path = self.output_dir / "dataset_network_topology.json"
        try:
            from trident_stream.dataset_topology import save_dataset_network_topology

            if save_dataset_network_topology(data, dataset_topology_path):
                self.logger.info("Done. DATASET_NETWORK_TOPOLOGY=%s", dataset_topology_path)
        except Exception:
            self.logger.exception("Dataset network topology export failed (non-fatal).")
        self.logger.info(
            "Done. DATASET_LABEL_DISTRIBUTION=%s | SUMMARY=%s | LABEL_CORR_JSON=%s | LABEL_CORR_FIG=%s | labels=%d",
            dataset_label_csv_path,
            dataset_label_summary_path,
            dataset_label_corr_json_path,
            dataset_label_corr_fig_path,
            len(dataset_label_rows),
        )
        start_idx = self._build_initial_learners(data, x_all)
        window_size = self.cfg["stream"]["window_size"]

        time_series = []

        for left in range(start_idx, len(data), window_size):
            t_window_start = perf_counter()
            right = min(left + window_size, len(data))
            chunk_df = data.iloc[left:right]
            chunk_x = x_all[left:right]
            chunk_labels = chunk_df["LabelNorm"].values
            accepted_by_learner: Dict[str, List[np.ndarray]] = {k: [] for k in self.tsieve.learners}
            accepted_labels_by_learner: Dict[str, List[str]] = {k: [] for k in self.tsieve.learners}
            accepted_meta_by_learner: Dict[str, List[Dict[str, object]]] = {k: [] for k in self.tsieve.learners}

            t_detect_start = perf_counter()
            if self.debug_overlap_enabled:
                debug_rows = self.tsieve.classify_batch_debug(chunk_x)
                self.debug_overlap_stream_samples += len(debug_rows)
                preds: List[Any] = []
                accepted_names_rows: List[List[str]] = []
                for debug_row in debug_rows:
                    preds.append(debug_row.get("pred"))
                    accepted_names = debug_row.get("accepted_names", [])
                    if isinstance(accepted_names, list):
                        accepted_names_casted = [str(x) for x in accepted_names]
                    else:
                        accepted_names_casted = []
                    accepted_names_rows.append(accepted_names_casted)
            else:
                preds = self.tsieve.classify_batch(chunk_x)
                accepted_names_rows = []

            for i in range(len(chunk_df)):
                sample = chunk_x[i : i + 1]
                pred = preds[i]
                if self.debug_overlap_enabled:
                    accepted_names = accepted_names_rows[i]
                    for n in accepted_names:
                        self.debug_overlap_accept_count[n] = int(self.debug_overlap_accept_count.get(n, 0) + 1)
                    if len(accepted_names) >= 2:
                        for a, b in combinations(sorted(accepted_names), 2):
                            key = (str(a), str(b))
                            self.debug_overlap_pair_intersections[key] = int(
                                self.debug_overlap_pair_intersections.get(key, 0) + 1
                            )
                assigned_learner = pred if pred is not None else "UNKNOWN"
                self.sample_assignments.append(
                    {
                        "row_index": int(left + i),
                        "timestamp": self._format_stream_timestamp(chunk_df["Timestamp"].iloc[i]),
                        "assigned_learner": str(assigned_learner),
                        "phase": "stream",
                    }
                )
                if pred is None:
                    self._record_learner_samples(learner_name="UNKNOWN", samples=sample)
                    self.tmagnifier.add_unknown(
                        sample[0],
                        str(chunk_labels[i]),
                        {
                            "row_index": int(left + i),
                            "timestamp": self._format_stream_timestamp(chunk_df["Timestamp"].iloc[i]),
                        },
                    )
                else:
                    accepted_by_learner.setdefault(pred, []).append(sample[0])
                    accepted_labels_by_learner.setdefault(pred, []).append(str(chunk_labels[i]))
                    accepted_meta_by_learner.setdefault(pred, []).append(
                        {
                            "row_index": int(left + i),
                            "timestamp": self._format_stream_timestamp(chunk_df["Timestamp"].iloc[i]),
                            "label_norm": str(chunk_labels[i]),
                            "window_left": int(left),
                            "window_right": int(right),
                        }
                    )
            t_detect_end = perf_counter()
            detect_seconds = t_detect_end - t_detect_start

            t_cluster_start = perf_counter()
            clusters = self.tmagnifier.pop_new_class_clusters()
            t_cluster_end = perf_counter()
            cluster_seconds = t_cluster_end - t_cluster_start
            create_seconds = 0.0
            retrain_seconds_window = 0.0
            create_seconds += self._create_new_learners_from_clusters(
                clusters=clusters,
                data=data,
                left=int(left),
                right=int(right),
                window_size=int(window_size),
                accepted_by_learner=accepted_by_learner,
                accepted_labels_by_learner=accepted_labels_by_learner,
                accepted_meta_by_learner=accepted_meta_by_learner,
                source="unknown_cluster",
            )
            create_seconds += self._maybe_recluster_small_learners(
                data=data,
                left=int(left),
                right=int(right),
                window_size=int(window_size),
                accepted_by_learner=accepted_by_learner,
                accepted_labels_by_learner=accepted_labels_by_learner,
                accepted_meta_by_learner=accepted_meta_by_learner,
            )

            for name, accepted_labels in accepted_labels_by_learner.items():
                if not accepted_labels:
                    continue
                self._accumulate_learner_distribution(learner_name=name, labels=np.asarray(accepted_labels, dtype=object))

            current_window_id = int(left // max(1, window_size))
            for name, samples in accepted_by_learner.items():
                if len(samples) == 0:
                    continue
                arr_all_new = np.stack(samples, axis=0)
                pending_labels = accepted_labels_by_learner.get(name, [])
                self._record_learner_samples(
                    learner_name=name,
                    samples=arr_all_new,
                    labels=np.asarray(pending_labels, dtype=object),
                )
                meta_rows = accepted_meta_by_learner.get(name, [])
                keep_mask = np.ones(len(arr_all_new), dtype=bool)
                if (not self.uniform_learner_treatment) and self.tsieve.is_benign_learner(name):
                    keep_mask = self._filter_benign_confident_mask(arr_all_new)
                    filtered = arr_all_new[keep_mask]
                    self.logger.info(
                        "[BenignConfidenceFilter] kept=%d dropped=%d scale=%.3f",
                        len(filtered),
                        len(arr_all_new) - len(filtered),
                        self.benign_history_confidence_scale,
                    )
                    arr_all_new = filtered
                    if len(arr_all_new) == 0:
                        for i_meta, meta in enumerate(meta_rows):
                            self.learner_accept_trace.append(
                                {
                                    "learner_name": str(name),
                                    "row_index": int(meta["row_index"]),
                                    "timestamp": str(meta["timestamp"]),
                                    "label_norm": str(meta["label_norm"]),
                                    "window_left": int(meta["window_left"]),
                                    "window_right": int(meta["window_right"]),
                                    "accepted_by_learner": True,
                                    "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                    "used_for_increment_train": False,
                                    "drop_reason": "benign_conf_filter",
                                }
                            )
                        continue

                self._append_history_pool(name, arr_all_new)

                selected_for_train_mask = np.zeros(len(keep_mask), dtype=bool)
                if (
                    (not self.uniform_learner_treatment)
                    and self.freeze_benign_incremental
                    and self.tsieve.is_benign_learner(name)
                ):
                    for i_meta, meta in enumerate(meta_rows):
                        self.learner_accept_trace.append(
                            {
                                "learner_name": str(name),
                                "row_index": int(meta["row_index"]),
                                "timestamp": str(meta["timestamp"]),
                                "label_norm": str(meta["label_norm"]),
                                "window_left": int(meta["window_left"]),
                                "window_right": int(meta["window_right"]),
                                "accepted_by_learner": True,
                                "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                "used_for_increment_train": False,
                                "drop_reason": "freeze_benign_incremental",
                            }
                        )
                    continue
                birth_w = int(self.learner_birth_window.get(str(name), 0))
                if (
                    str(name).startswith("NEW_")
                    and self.new_learner_cooldown_windows > 0
                    and (current_window_id - birth_w) < self.new_learner_cooldown_windows
                ):
                    for i_meta, meta in enumerate(meta_rows):
                        self.learner_accept_trace.append(
                            {
                                "learner_name": str(name),
                                "row_index": int(meta["row_index"]),
                                "timestamp": str(meta["timestamp"]),
                                "label_norm": str(meta["label_norm"]),
                                "window_left": int(meta["window_left"]),
                                "window_right": int(meta["window_right"]),
                                "accepted_by_learner": True,
                                "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                "used_for_increment_train": False,
                                "drop_reason": "new_learner_cooldown",
                            }
                        )
                    continue
                latest_row_index = max([int(m["row_index"]) for m in meta_rows]) if meta_rows else int(right - 1)
                last_trained_idx = int(
                    self.learner_last_trained_row_index.get(
                        str(name),
                        int(max(0, latest_row_index - int(self.cfg["tsieve"]["increment_min_samples"]))),
                    )
                )
                if self.increment_use_last_train_gap:
                    if (latest_row_index - last_trained_idx) < int(
                        self.cfg["tsieve"]["increment_min_samples"]
                    ):
                        for i_meta, meta in enumerate(meta_rows):
                            self.learner_accept_trace.append(
                                {
                                    "learner_name": str(name),
                                    "row_index": int(meta["row_index"]),
                                    "timestamp": str(meta["timestamp"]),
                                    "label_norm": str(meta["label_norm"]),
                                    "window_left": int(meta["window_left"]),
                                    "window_right": int(meta["window_right"]),
                                    "accepted_by_learner": True,
                                    "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                    "used_for_increment_train": False,
                                    "drop_reason": "increment_gap_not_met",
                                }
                            )
                        continue
                else:
                    if len(arr_all_new) < self.cfg["tsieve"]["increment_min_samples"]:
                        for i_meta, meta in enumerate(meta_rows):
                            self.learner_accept_trace.append(
                                {
                                    "learner_name": str(name),
                                    "row_index": int(meta["row_index"]),
                                    "timestamp": str(meta["timestamp"]),
                                    "label_norm": str(meta["label_norm"]),
                                    "window_left": int(meta["window_left"]),
                                    "window_right": int(meta["window_right"]),
                                    "accepted_by_learner": True,
                                    "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                    "used_for_increment_train": False,
                                    "drop_reason": "increment_min_samples",
                                }
                            )
                        continue
                retrain_count_now = int(self.learner_retrain_counts.get(str(name), 0))
                if self.max_retrain_per_learner > 0 and retrain_count_now >= self.max_retrain_per_learner:
                    for i_meta, meta in enumerate(meta_rows):
                        self.learner_accept_trace.append(
                            {
                                "learner_name": str(name),
                                "row_index": int(meta["row_index"]),
                                "timestamp": str(meta["timestamp"]),
                                "label_norm": str(meta["label_norm"]),
                                "window_left": int(meta["window_left"]),
                                "window_right": int(meta["window_right"]),
                                "accepted_by_learner": True,
                                "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                "used_for_increment_train": False,
                                "drop_reason": "max_retrain_per_learner",
                            }
                        )
                    continue
                if self.increment_drift_gate_enabled:
                    drift_score = self._compute_feature_drift_score(str(name), arr_all_new)
                    if np.isfinite(drift_score) and drift_score < self.increment_drift_min_score:
                        self.logger.info(
                            "[IncrementDriftGate] learner=%s drift_score=%.6f < min=%.6f, skip retrain",
                            str(name),
                            float(drift_score),
                            float(self.increment_drift_min_score),
                        )
                        for i_meta, meta in enumerate(meta_rows):
                            self.learner_accept_trace.append(
                                {
                                    "learner_name": str(name),
                                    "row_index": int(meta["row_index"]),
                                    "timestamp": str(meta["timestamp"]),
                                    "label_norm": str(meta["label_norm"]),
                                    "window_left": int(meta["window_left"]),
                                    "window_right": int(meta["window_right"]),
                                    "accepted_by_learner": True,
                                    "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                    "used_for_increment_train": False,
                                    "drop_reason": "increment_no_feature_drift",
                                }
                            )
                        continue
                if self.increment_gate_enabled:
                    benign_prob_mean = self._estimate_benign_prob_mean(arr_all_new)
                    own_exceed_rate = self._compute_own_exceed_rate(str(name), arr_all_new)
                    if (
                        np.isfinite(benign_prob_mean)
                        and np.isfinite(own_exceed_rate)
                        and benign_prob_mean < self.increment_gate_min_benign_prob_mean
                        and own_exceed_rate > self.increment_gate_max_own_exceed_rate
                    ):
                        for i_meta, meta in enumerate(meta_rows):
                            self.learner_accept_trace.append(
                                {
                                    "learner_name": str(name),
                                    "row_index": int(meta["row_index"]),
                                    "timestamp": str(meta["timestamp"]),
                                    "label_norm": str(meta["label_norm"]),
                                    "window_left": int(meta["window_left"]),
                                    "window_right": int(meta["window_right"]),
                                    "accepted_by_learner": True,
                                    "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                    "used_for_increment_train": False,
                                    "drop_reason": "increment_quality_gate",
                                }
                            )
                        continue

                arr_new = arr_all_new
                max_inc = self.cfg["tsieve"]["max_increment_samples"]
                kept_indices = np.where(keep_mask)[0]
                selected_original_indices = kept_indices.copy()
                current_indices = kept_indices.copy()
                route_kept_indices: Optional[np.ndarray] = None
                iforest_kept_indices: Optional[np.ndarray] = None
                if (
                    self.increment_route_gate_enabled
                    and len(arr_new) >= self.increment_route_min_samples
                    and (
                        (not self.increment_route_apply_to_new_only)
                        or str(name).startswith("NEW_")
                    )
                ):
                    route_eval = self._compute_increment_route_confidence(str(name), arr_new)
                    route_conf = float(route_eval.get("confident_ratio", float("nan")))
                    own_margin_p10 = float(route_eval.get("own_margin_p10", float("nan")))
                    gap_p10 = float(route_eval.get("gap_p10", float("nan")))
                    if bool(route_eval.get("valid", False)):
                        route_mask_rel = np.asarray(route_eval.get("keep_mask"), dtype=bool)
                        if len(route_mask_rel) == len(arr_new):
                            arr_new = arr_new[route_mask_rel]
                            selected_original_indices = current_indices[route_mask_rel]
                            current_indices = selected_original_indices.copy()
                            route_kept_indices = selected_original_indices.copy()
                            self.logger.info(
                                (
                                    "[IncrementRouteGate] learner=%s total=%d kept=%d conf_ratio=%.4f "
                                    "own_margin_p10=%.4f gap_p10=%.4f thresholds=(own>=%.4f,gap>=%.4f,conf>=%.4f)"
                                ),
                                str(name),
                                int(len(kept_indices)),
                                int(len(selected_original_indices)),
                                route_conf,
                                own_margin_p10,
                                gap_p10,
                                float(self.increment_route_min_own_margin),
                                float(self.increment_route_min_margin_gap),
                                float(self.increment_route_min_confident_ratio),
                            )
                        if route_conf < self.increment_route_min_confident_ratio:
                            for i_meta, meta in enumerate(meta_rows):
                                self.learner_accept_trace.append(
                                    {
                                        "learner_name": str(name),
                                        "row_index": int(meta["row_index"]),
                                        "timestamp": str(meta["timestamp"]),
                                        "label_norm": str(meta["label_norm"]),
                                        "window_left": int(meta["window_left"]),
                                        "window_right": int(meta["window_right"]),
                                        "accepted_by_learner": True,
                                        "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                        "used_for_increment_train": False,
                                        "drop_reason": "increment_route_gate_batch_reject",
                                    }
                                )
                            continue
                        if len(arr_new) < self.cfg["tsieve"]["increment_min_samples"]:
                            for i_meta, meta in enumerate(meta_rows):
                                self.learner_accept_trace.append(
                                    {
                                        "learner_name": str(name),
                                        "row_index": int(meta["row_index"]),
                                        "timestamp": str(meta["timestamp"]),
                                        "label_norm": str(meta["label_norm"]),
                                        "window_left": int(meta["window_left"]),
                                        "window_right": int(meta["window_right"]),
                                        "accepted_by_learner": True,
                                        "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                        "used_for_increment_train": False,
                                        "drop_reason": "increment_route_gate_min_samples",
                                    }
                                )
                            continue
                if (
                    self.increment_iforest_guard_enabled
                    and len(arr_new) >= self.increment_iforest_guard_min_samples
                    and (
                        (not self.increment_iforest_guard_apply_to_new_only)
                        or str(name).startswith("NEW_")
                    )
                ):
                    if_eval = self._apply_increment_iforest_guard(str(name), arr_new)
                    if bool(if_eval.get("valid", False)):
                        if_mask_rel = np.asarray(if_eval.get("keep_mask"), dtype=bool)
                        if len(if_mask_rel) == len(arr_new):
                            arr_new = arr_new[if_mask_rel]
                            selected_original_indices = current_indices[if_mask_rel]
                            current_indices = selected_original_indices.copy()
                            iforest_kept_indices = selected_original_indices.copy()
                            self.logger.info(
                                (
                                    "[IncrementIForestGuard] learner=%s total=%d kept=%d kept_ratio=%.4f "
                                    "score_p10=%.4f score_p50=%.4f keep_q=%.3f"
                                ),
                                str(name),
                                int(len(if_mask_rel)),
                                int(len(arr_new)),
                                float(if_eval.get("kept_ratio", float("nan"))),
                                float(if_eval.get("score_p10", float("nan"))),
                                float(if_eval.get("score_p50", float("nan"))),
                                float(self.increment_iforest_guard_keep_quantile),
                            )
                        if len(arr_new) < self.cfg["tsieve"]["increment_min_samples"]:
                            for i_meta, meta in enumerate(meta_rows):
                                self.learner_accept_trace.append(
                                    {
                                        "learner_name": str(name),
                                        "row_index": int(meta["row_index"]),
                                        "timestamp": str(meta["timestamp"]),
                                        "label_norm": str(meta["label_norm"]),
                                        "window_left": int(meta["window_left"]),
                                        "window_right": int(meta["window_right"]),
                                        "accepted_by_learner": True,
                                        "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                                        "used_for_increment_train": False,
                                        "drop_reason": "increment_iforest_guard_min_samples",
                                    }
                                )
                            continue
                if len(arr_new) > max_inc or self.increment_low_loss_quantile_keep < 1.0:
                    arr_new, idx_rel = self._sample_increment_new(str(name), arr_new, max_keep=max_inc)
                    selected_original_indices = current_indices[idx_rel]
                    if route_kept_indices is not None:
                        route_kept_indices = selected_original_indices.copy()
                    if iforest_kept_indices is not None:
                        iforest_kept_indices = selected_original_indices.copy()
                selected_for_train_mask[selected_original_indices] = True

                hist_sample = self._sample_history_for_update(name, feature_dim=arr_new.shape[1])
                arr_update = np.concatenate([hist_sample, arr_new], axis=0) if len(hist_sample) > 0 else arr_new
                selected_labels = np.asarray(
                    [str(meta_rows[i]["label_norm"]) for i in range(len(meta_rows)) if bool(selected_for_train_mask[i])],
                    dtype=object,
                )
                self._append_train_batch_profile(
                    stage="increment",
                    learner_name=name,
                    labels=selected_labels,
                    window_left=int(left),
                    window_right=int(right),
                    hist_sample_count=int(len(hist_sample)),
                    new_sample_count=int(len(arr_new)),
                    update_total_count=int(len(arr_update)),
                )
                before_losses = self.tsieve.learners[name].reconstruction_loss(arr_update)
                before_loss_mean = float(np.mean(before_losses)) if len(before_losses) > 0 else float("nan")
                before_loss_median = (
                    float(np.median(before_losses)) if len(before_losses) > 0 else float("nan")
                )
                before_loss_p95 = (
                    float(np.quantile(before_losses, 0.95)) if len(before_losses) > 0 else float("nan")
                )
                t_retrain_start = perf_counter()
                increment_epoch_losses = self.tsieve.learners[name].fit_incremental(
                    arr_update,
                    epochs=self.cfg["tsieve"]["increment_epochs"],
                )
                after_losses = self.tsieve.learners[name].reconstruction_loss(arr_update)
                after_loss_mean = float(np.mean(after_losses)) if len(after_losses) > 0 else float("nan")
                after_loss_median = (
                    float(np.median(after_losses)) if len(after_losses) > 0 else float("nan")
                )
                after_loss_p95 = (
                    float(np.quantile(after_losses, 0.95)) if len(after_losses) > 0 else float("nan")
                )
                if self.threshold_refresh_use_anchor:
                    refresh_new_keep = int(max(1, round(len(arr_new) * self.threshold_refresh_new_ratio)))
                    refresh_new = self.tsieve.interval_sample_by_loss(
                        str(name),
                        arr_new,
                        keep_count=min(refresh_new_keep, len(arr_new)),
                    )
                    if len(hist_sample) > 0:
                        arr_refresh = np.concatenate([hist_sample, refresh_new], axis=0)
                    else:
                        arr_refresh = refresh_new
                    self.tsieve.refresh_threshold(name, arr_refresh)
                else:
                    self.tsieve.refresh_threshold(name, arr_update)
                t_retrain_end = perf_counter()
                retrain_seconds = t_retrain_end - t_retrain_start
                retrain_seconds_window += retrain_seconds
                self.perf_stats["retrain_seconds_total"] += retrain_seconds
                self.perf_stats["incremental_update_count"] += 1
                self.learner_last_trained_row_index[str(name)] = int(latest_row_index)
                self.learner_retrain_counts[str(name)] = int(
                    self.learner_retrain_counts.get(str(name), 0) + 1
                )
                self.learner_update_loss_profiles.append(
                    {
                        "learner_name": str(name),
                        "window_left": int(left),
                        "window_right": int(right),
                        "latest_row_index": int(latest_row_index),
                        "hist_sample_count": int(len(hist_sample)),
                        "new_sample_count": int(len(arr_new)),
                        "update_total_count": int(len(arr_update)),
                        "before_loss_mean": before_loss_mean,
                        "before_loss_median": before_loss_median,
                        "before_loss_p95": before_loss_p95,
                        "after_loss_mean": after_loss_mean,
                        "after_loss_median": after_loss_median,
                        "after_loss_p95": after_loss_p95,
                        "delta_loss_mean": float(after_loss_mean - before_loss_mean)
                        if np.isfinite(before_loss_mean) and np.isfinite(after_loss_mean)
                        else float("nan"),
                        "delta_loss_p95": float(after_loss_p95 - before_loss_p95)
                        if np.isfinite(before_loss_p95) and np.isfinite(after_loss_p95)
                        else float("nan"),
                        "retrain_seconds": float(retrain_seconds),
                        "epoch_count": int(len(increment_epoch_losses.get("train", []))),
                        "epoch_loss_first": float(increment_epoch_losses.get("train", [])[0])
                        if len(increment_epoch_losses.get("train", [])) > 0
                        else float("nan"),
                        "epoch_loss_last": float(increment_epoch_losses.get("train", [])[-1])
                        if len(increment_epoch_losses.get("train", [])) > 0
                        else float("nan"),
                        "epoch_val_first": float(increment_epoch_losses.get("val", [])[0])
                        if len(increment_epoch_losses.get("val", [])) > 0
                        else float("nan"),
                        "epoch_val_last": float(increment_epoch_losses.get("val", [])[-1])
                        if len(increment_epoch_losses.get("val", [])) > 0
                        else float("nan"),
                        "epoch_losses_json": json.dumps(
                            [float(x) for x in increment_epoch_losses.get("train", [])], ensure_ascii=False
                        ),
                        "epoch_val_losses_json": json.dumps(
                            [float(x) for x in increment_epoch_losses.get("val", [])], ensure_ascii=False
                        ),
                    }
                )
                self._append_fit_loss_profile(
                    stage="increment",
                    learner_name=str(name),
                    window_left=int(left),
                    window_right=int(right),
                    sample_count=int(len(arr_update)),
                    epoch_losses=[float(x) for x in increment_epoch_losses.get("train", [])],
                    epoch_val_losses=[float(x) for x in increment_epoch_losses.get("val", [])],
                )
                self.logger.info(
                    (
                        "[IncrementalLossTrack] learner=%s update=%d "
                        "before(mean=%.6f,p95=%.6f) after(mean=%.6f,p95=%.6f) delta(mean=%.6f,p95=%.6f)"
                    ),
                    str(name),
                    int(len(arr_update)),
                    before_loss_mean,
                    before_loss_p95,
                    after_loss_mean,
                    after_loss_p95,
                    (after_loss_mean - before_loss_mean),
                    (after_loss_p95 - before_loss_p95),
                )
                self.logger.info(
                    "[IncrementalUpdate] learner=%s new=%d hist_sample=%d update_total=%d",
                    name,
                    len(arr_new),
                    len(hist_sample),
                    len(arr_update),
                )
                route_kept_index_set: Optional[set[int]] = None
                if route_kept_indices is not None:
                    route_kept_index_set = {int(x) for x in route_kept_indices.tolist()}
                iforest_kept_index_set: Optional[set[int]] = None
                if iforest_kept_indices is not None:
                    iforest_kept_index_set = {int(x) for x in iforest_kept_indices.tolist()}
                for i_meta, meta in enumerate(meta_rows):
                    if not bool(keep_mask[i_meta]):
                        reason = "benign_conf_filter"
                    elif iforest_kept_index_set is not None and int(i_meta) not in iforest_kept_index_set:
                        reason = "increment_iforest_guard_filtered"
                    elif route_kept_index_set is not None and int(i_meta) not in route_kept_index_set:
                        reason = "increment_route_gate_filtered"
                    elif not bool(selected_for_train_mask[i_meta]):
                        reason = "max_increment_samples_subsampled"
                    else:
                        reason = ""
                    self.learner_accept_trace.append(
                        {
                            "learner_name": str(name),
                            "row_index": int(meta["row_index"]),
                            "timestamp": str(meta["timestamp"]),
                            "label_norm": str(meta["label_norm"]),
                            "window_left": int(meta["window_left"]),
                            "window_right": int(meta["window_right"]),
                            "accepted_by_learner": True,
                            "passed_benign_conf_filter": bool(keep_mask[i_meta]),
                            "used_for_increment_train": bool(selected_for_train_mask[i_meta]),
                            "drop_reason": reason,
                        }
                    )

            t_end = chunk_df["Timestamp"].iloc[-1]
            entry = {
                "window_end_time": t_end,
                "window_left": int(left),
                "window_right": int(right),
                "learner_count": int(len(self.tsieve.learners)),
                "unknown_buffer_size": int(len(self.tmagnifier.unknown_buffer)),
            }
            time_series.append(entry)
            self.logger.info(
                "[Window] %d-%d time=%s learners=%d unknown_buffer=%d",
                left,
                right,
                t_end,
                entry["learner_count"],
                entry["unknown_buffer_size"],
            )
            t_window_end = perf_counter()
            window_seconds = t_window_end - t_window_start
            self.perf_stats["detect_seconds_total"] += detect_seconds
            self.perf_stats["cluster_seconds_total"] += cluster_seconds
            self.perf_stats["create_learner_seconds_total"] += create_seconds
            self.perf_stats["window_total_seconds_total"] += window_seconds
            self.perf_stats["windows_count"] += 1
            self.logger.info(
                "[PerfWindow] %d-%d detect=%.4fs cluster=%.4fs create=%.4fs retrain_total=%.4fs window_total=%.4fs",
                left,
                right,
                detect_seconds,
                cluster_seconds,
                create_seconds,
                retrain_seconds_window,
                window_seconds,
            )

        ts_df = pd.DataFrame(time_series)
        self._finalize_unknown_assignments()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        csv_path = self.output_dir / "learner_count_over_time.csv"
        ts_df.to_csv(csv_path, index=False)
        creation_profile_path = self.output_dir / "learner_creation_distribution.csv"
        pd.DataFrame(self.learner_creation_profiles).to_csv(creation_profile_path, index=False)
        train_batch_profile_path = self.output_dir / "learner_train_batch_label_distribution.csv"
        train_batch_df = pd.DataFrame(self.learner_train_batch_profiles)
        if not train_batch_df.empty:
            stage_rank = {"init": 0, "new": 1, "increment": 2}
            train_batch_df["stage_rank"] = train_batch_df["stage"].map(stage_rank).fillna(9).astype(int)
            train_batch_df = train_batch_df.sort_values(
                by=["learner_name", "stage_rank", "window_left", "window_right"],
                ascending=[True, True, True, True],
                kind="mergesort",
            ).drop(columns=["stage_rank"])
        train_batch_df.to_csv(train_batch_profile_path, index=False)
        update_loss_profile_path = self.output_dir / "learner_increment_loss_trace.csv"
        update_loss_df = pd.DataFrame(self.learner_update_loss_profiles)
        if not update_loss_df.empty:
            update_loss_df = update_loss_df.sort_values(
                by=["learner_name", "window_left", "window_right"],
                ascending=[True, True, True],
                kind="mergesort",
            )
        update_loss_df.to_csv(update_loss_profile_path, index=False)
        fit_loss_profile_path = self.output_dir / "learner_fit_loss_trace.csv"
        fit_loss_df = pd.DataFrame(self.learner_fit_loss_profiles)
        if not fit_loss_df.empty:
            stage_rank = {"init": 0, "new": 1, "increment": 2}
            fit_loss_df["stage_rank"] = fit_loss_df["stage"].map(stage_rank).fillna(9).astype(int)
            fit_loss_df = fit_loss_df.sort_values(
                by=["learner_name", "stage_rank", "window_left", "window_right"],
                ascending=[True, True, True, True],
                kind="mergesort",
            ).drop(columns=["stage_rank"])
        fit_loss_df.to_csv(fit_loss_profile_path, index=False)
        profile_path = self.output_dir / "learner_label_distribution.csv"
        assign_export_df = self._build_assignment_export_df(len(data))
        self._log_assignment_consistency(len(data), assign_export_df)
        cumulative_rows = self._build_profile_rows_from_assignment_df(data, assign_export_df)
        profile_df = pd.DataFrame(cumulative_rows)
        learner_feature_stats_df = self._build_learner_feature_stats_df(
            data=data,
            feature_names=IMPORTANT_LEARNER_CLUSTER_FEATURES,
        )
        learner_protocol_stats_df = self._build_learner_protocol_stats_df(data=data)
        learner_temporal_stats_df = self._build_learner_temporal_stats_df(data=data)
        learner_port_stats_df = self._build_learner_port_stats_df(data=data)
        if not learner_feature_stats_df.empty:
            profile_df = profile_df.merge(learner_feature_stats_df, on="learner_name", how="left")
            stats_feature_cols = [c for c in learner_feature_stats_df.columns if c != "learner_name"]
            if stats_feature_cols:
                profile_df[stats_feature_cols] = (
                    profile_df[stats_feature_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
                )
        if not learner_protocol_stats_df.empty:
            profile_df = profile_df.merge(learner_protocol_stats_df, on="learner_name", how="left")
            for c in [
                "protocol_tcp_ratio",
                "protocol_udp_ratio",
                "protocol_other_ratio",
                "protocol_concentration",
            ]:
                if c in profile_df.columns:
                    profile_df[c] = pd.to_numeric(profile_df[c], errors="coerce").fillna(0.0)
            if "protocol_cluster_type" in profile_df.columns:
                profile_df["protocol_cluster_type"] = (
                    profile_df["protocol_cluster_type"].fillna("UNKNOWN").astype(str)
                )
        if not learner_temporal_stats_df.empty:
            profile_df = profile_df.merge(learner_temporal_stats_df, on="learner_name", how="left")
            for c in [
                "temporal_span_sec",
                "temporal_span_ratio",
                "temporal_global_hhi",
                "temporal_norm_entropy",
                "temporal_concentration",
                "temporal_burst_score",
            ]:
                if c in profile_df.columns:
                    profile_df[c] = pd.to_numeric(profile_df[c], errors="coerce").fillna(0.0)
            if "temporal_cluster_type" in profile_df.columns:
                profile_df["temporal_cluster_type"] = (
                    profile_df["temporal_cluster_type"].fillna("UNKNOWN").astype(str)
                )
        if not learner_port_stats_df.empty:
            profile_df = profile_df.merge(learner_port_stats_df, on="learner_name", how="left")
            for c in [
                "dst_port_norm_entropy",
                "dst_port_concentration",
                "dst_port_hhi",
                "dst_top_port_ratio",
                "src_port_norm_entropy",
            ]:
                if c in profile_df.columns:
                    profile_df[c] = pd.to_numeric(profile_df[c], errors="coerce").fillna(0.0)
            for c in ["dst_port_sample_count", "dst_port_unique", "dst_top_port", "src_port_unique"]:
                if c in profile_df.columns:
                    profile_df[c] = pd.to_numeric(profile_df[c], errors="coerce").fillna(0).astype(int)
            if "port_cluster_type" in profile_df.columns:
                profile_df["port_cluster_type"] = (
                    profile_df["port_cluster_type"].fillna("UNKNOWN").astype(str)
                )
        if not profile_df.empty and "attack_ratio" in profile_df.columns:
            profile_df = profile_df.sort_values(
                by="attack_ratio",
                ascending=False,
                kind="mergesort",
            )
        profile_df.to_csv(profile_path, index=False)
        creation_preview_path = self.output_dir / "learner_creation_flow_previews.json"
        with open(creation_preview_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "preview_flow_count": int(LEARNER_CREATION_PREVIEW_FLOW_COUNT),
                    "entries": list(self._learner_creation_flow_previews),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        self.logger.info("Done. LEARNER_CREATION_FLOW_PREVIEWS=%s", creation_preview_path)
        feature_corr_rows = self._build_attack_ratio_feature_correlation_rows(profile_df)
        feature_corr_json_path = self.output_dir / "learner_feature_attack_ratio_correlation.json"
        feature_corr_fig_path = self.output_dir / "learner_feature_attack_ratio_correlation.png"
        with open(feature_corr_json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "feature_family": "important_cluster_features",
                    "feature_count": int(len(feature_corr_rows)),
                    "top_k_default": 24,
                    "rows": feature_corr_rows,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        self._save_attack_ratio_correlation_figure(
            rows=feature_corr_rows,
            out_path=feature_corr_fig_path,
            top_k=24,
        )
        learner_risk_path = self.output_dir / "learner_risk_scores.csv"
        risk_rows = self._build_unsupervised_learner_risk_rows()
        pd.DataFrame(risk_rows).to_csv(learner_risk_path, index=False)
        self.logger.info("Done. LEARNER_RISK=%s", learner_risk_path)
        self._run_decision_tree_analysis(profile_df=profile_df, label_df=dataset_label_profile_df)
        metrics_path = self.output_dir / "metrics.json"
        metrics = self._compute_run_metrics(cumulative_rows)
        metrics["protocol_cluster_summary"] = self._build_protocol_cluster_summary(profile_df)
        metric_catalog_items: List[Dict[str, str]] = [
            {
                "name": "risk_false_positive_rate",
                "formula": "FP / (FP + TN)",
                "safety": "误报率，越低越好。高FPR会导致告警噪声过大，影响研判效率。",
            },
            {
                "name": "risk_false_negative_rate",
                "formula": "FN / (FN + TP)",
                "safety": "漏报率，越低越好。高FNR意味着真实攻击漏检，带来直接风险。",
            },
            {
                "name": "protocol_cluster_summary.by_type.*.learner_ratio",
                "formula": "type_learner_count / total_learner_count",
                "safety": "协议簇类型在学习器层面的占比，可判断系统当前偏向TCP/UDP/混合场景。",
            },
            {
                "name": "protocol_cluster_summary.by_type.*.sample_ratio",
                "formula": "type_sample_count / sample_total",
                "safety": "协议簇类型在样本层面的占比，可识别是否出现大体量单协议攻击流量。",
            },
        ]
        known_names = {x["name"] for x in metric_catalog_items}

        # 1) 自动覆盖 learner 画像表中的所有字段
        for col in profile_df.columns:
            col_s = str(col)
            if col_s in known_names:
                continue
            if col_s.endswith("__mean"):
                base = col_s[: -len("__mean")]
                formula = f"mean({base}) over samples assigned to one learner"
                safety = f"{base} 的学习器级均值画像，用于判断该学习器的行为中心。"
            elif col_s.endswith("__std"):
                base = col_s[: -len("__std")]
                formula = f"std({base}) over samples assigned to one learner"
                safety = f"{base} 的学习器级波动画像。值越大表示簇内异质性越强，稳定性越低。"
            elif col_s.endswith("__cv"):
                base = col_s[: -len("__cv")]
                formula = f"abs(std({base}) / mean({base})) over samples assigned to one learner"
                safety = f"{base} 的学习器级相对波动率。比 std 更可比，能弱化量纲影响。"
            elif col_s.endswith("__min"):
                base = col_s[: -len("__min")]
                formula = f"min({base}) over samples assigned to one learner"
                safety = f"{base} 的学习器级下界画像，可辅助识别异常低值与哨兵值影响。"
            elif col_s.endswith("__max"):
                base = col_s[: -len("__max")]
                formula = f"max({base}) over samples assigned to one learner"
                safety = f"{base} 的学习器级上界画像，可辅助识别峰值突发与放大行为。"
            elif col_s == "attack_ratio":
                formula = "attack_count / total_assigned_samples"
                safety = "学习器攻击占比。高值学习器优先排查，低值学习器偏基线。"
            elif col_s == "dominant_ratio":
                formula = "dominant_count / total_assigned_samples"
                safety = "主导标签纯度。低纯度表示簇混杂，建议结合协议与拓扑继续细分。"
            elif col_s == "creation_sample_count":
                formula = "samples used when learner was first created"
                safety = "创建样本量。过小会导致初始模型不稳，后续重训更敏感。"
            elif col_s == "post_creation_added_samples":
                formula = "total_assigned_samples - creation_sample_count"
                safety = "增量吸收量。高值表示该学习器持续吸收新流量，需关注概念漂移。"
            elif col_s == "protocol_tcp_ratio":
                formula = "count(Protocol==6) / total_protocol_samples"
                safety = "TCP占比。高值常见于TCP主导行为（Web/扫描/慢速攻击等）。"
            elif col_s == "protocol_udp_ratio":
                formula = "count(Protocol==17) / total_protocol_samples"
                safety = "UDP占比。高值常见于UDP主导行为（反射/放大类攻击等）。"
            elif col_s == "protocol_other_ratio":
                formula = "count(Protocol not in {6,17}) / total_protocol_samples"
                safety = "其他协议占比。异常升高需检查非常规协议或特征解析质量。"
            elif col_s == "protocol_concentration":
                formula = "max(protocol_tcp_ratio, protocol_udp_ratio)"
                safety = "协议聚集性。越接近1表示协议越单一，越低表示混合流量更强。"
            elif col_s == "protocol_cluster_type":
                formula = "if tcp>=0.8 then TCP_CLUSTER; elif udp>=0.8 then UDP_CLUSTER; elif concentration>=0.6 then TCP_UDP_BIASED; else MIXED/UNKNOWN"
                safety = "协议簇标签。用于快速分流研判路径（TCP行为侧/UDP放大型/混合异常）。"
            elif col_s in {"learner_name", "dominant_label", "label_distribution_json"}:
                formula = "metadata"
                safety = "描述性元信息，用于定位学习器与标签结构。"
            elif col_s in {"total_assigned_samples", "dominant_count"}:
                formula = "count(*) in learner scope"
                safety = "样本计数类指标，用于评估规模与主导性。"
            else:
                formula = "derived in run pipeline"
                safety = "运行期派生指标，用于补充学习器行为画像。"
            metric_catalog_items.append(
                {
                    "name": col_s,
                    "formula": formula,
                    "safety": safety,
                }
            )
            known_names.add(col_s)

        # 2) 自动覆盖 label 画像表中的所有字段（你提到的 dataset_label_distribution 全量字段）
        for col in dataset_label_profile_df.columns:
            col_s = str(col)
            key = f"dataset_label_distribution.{col_s}"
            if key in known_names:
                continue
            if col_s.endswith("__mean"):
                base = col_s[: -len("__mean")]
                formula = f"mean({base}) over samples with same label"
                safety = f"标签级均值画像。用于刻画该攻击/良性标签的中心行为特征。"
            elif col_s.endswith("__std"):
                base = col_s[: -len("__std")]
                formula = f"std({base}) over samples with same label"
                safety = f"标签级波动画像。用于刻画该标签内部稳定性与异质性。"
            elif col_s.endswith("__cv"):
                base = col_s[: -len("__cv")]
                formula = f"abs(std({base}) / mean({base})) over samples with same label"
                safety = f"标签级相对波动率。可跨特征比较波动强弱，降低量纲影响。"
            elif col_s.endswith("__min"):
                base = col_s[: -len("__min")]
                formula = f"min({base}) over samples with same label"
                safety = f"标签级下界画像。用于发现该攻击标签的极端低值模式。"
            elif col_s.endswith("__max"):
                base = col_s[: -len("__max")]
                formula = f"max({base}) over samples with same label"
                safety = f"标签级上界画像。用于发现该攻击标签的峰值与突发模式。"
            elif col_s == "ratio":
                formula = "label_count / total_rows"
                safety = "标签基线占比。用于评估类别偏斜并指导阈值与采样策略。"
            elif col_s == "is_benign":
                formula = "boolean(is_benign_label(label))"
                safety = "标签安全属性。用于区分攻击标签与良性标签。"
            elif col_s == "protocol_cluster_type":
                formula = "same as learner protocol_cluster_type, computed on label scope"
                safety = "标签协议簇类型。用于区分该标签偏TCP、偏UDP或混合。"
            elif col_s in {"protocol_tcp_ratio", "protocol_udp_ratio", "protocol_other_ratio", "protocol_concentration"}:
                formula = "same as learner protocol ratios, computed on label scope"
                safety = "标签协议分布与聚集性，可直观看到每种攻击的协议特征。"
            elif col_s in {"label", "year_tag", "base_label"}:
                formula = "metadata"
                safety = "标签元信息，用于按年份/基础类别组织安全研判。"
            elif col_s == "count":
                formula = "count(*) with this label"
                safety = "标签样本量。用于判断攻击族规模与优先级。"
            else:
                formula = "derived in run pipeline (label scope)"
                safety = "标签级派生指标，用于补充攻击画像。"
            metric_catalog_items.append(
                {
                    "name": key,
                    "formula": formula,
                    "safety": safety,
                }
            )
            known_names.add(key)

        # 3) 相关性输出字段说明
        corr_metric_defs = [
            (
                "learner_feature_attack_ratio_correlation.pearson_corr",
                "cov(X,Y)/(std(X)*std(Y))",
                "学习器特征与attack_ratio线性相关强度，便于定位高影响指标。",
            ),
            (
                "learner_feature_attack_ratio_correlation.spearman_corr",
                "Pearson(rank(X), rank(Y))",
                "学习器特征与attack_ratio单调相关强度，对非线性更稳健。",
            ),
            (
                "dataset_label_feature_attack_correlation.pearson_corr",
                "cov(X,Y)/(std(X)*std(Y)), Y=attack_label(1=attack)",
                "标签级特征对攻击属性的线性相关强度，用于识别攻击共性特征。",
            ),
            (
                "dataset_label_feature_attack_correlation.spearman_corr",
                "Pearson(rank(X), rank(Y)), Y=attack_label(1=attack)",
                "标签级特征对攻击属性的单调相关强度，用于稳健排序特征筛选。",
            ),
        ]
        for name, formula, safety in corr_metric_defs:
            if name not in known_names:
                metric_catalog_items.append({"name": name, "formula": formula, "safety": safety})
                known_names.add(name)

        metric_catalog = {"metric": metric_catalog_items}
        metrics["metric_catalog"] = metric_catalog
        metric_catalog_path = self.output_dir / "metric_catalog.json"
        with open(metric_catalog_path, "w", encoding="utf-8") as f:
            json.dump(metric_catalog, f, ensure_ascii=False, indent=2)
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        overlap_pairs_path = self.output_dir / "debug_true_overlap_pairs.csv"
        overlap_summary_path = self.output_dir / "debug_true_overlap_summary.json"
        overlap_df = pd.DataFrame()
        if self.debug_overlap_enabled:
            learner_names = sorted([str(name) for name in self.tsieve.learners.keys()])
            rows: List[Dict[str, object]] = []
            for a, b in combinations(learner_names, 2):
                key = (a, b) if (a, b) in self.debug_overlap_pair_intersections else (b, a)
                inter = int(self.debug_overlap_pair_intersections.get(key, 0))
                count_a = int(self.debug_overlap_accept_count.get(a, 0))
                count_b = int(self.debug_overlap_accept_count.get(b, 0))
                union = int(count_a + count_b - inter)
                jaccard = self._safe_div(inter, union)
                rows.append(
                    {
                        "learner_a_raw": a,
                        "learner_b_raw": b,
                        "learner_a": self._learner_display_name(a),
                        "learner_b": self._learner_display_name(b),
                        "accept_count_a": count_a,
                        "accept_count_b": count_b,
                        "intersection_count": inter,
                        "union_count": union,
                        "jaccard_acceptance": jaccard,
                        "accept_rate_a_to_b": self._safe_div(inter, count_a),
                        "accept_rate_b_to_a": self._safe_div(inter, count_b),
                    }
                )
            overlap_df = pd.DataFrame(rows).sort_values(
                by=["jaccard_acceptance", "intersection_count"],
                ascending=False,
            )
            overlap_df.to_csv(overlap_pairs_path, index=False)
            overlap_fig_path = self.output_dir / "learner_true_overlap_network.png"
            overlap_min_jaccard = float(self.cfg["runtime"].get("debug_overlap_min_jaccard", 0.10))
            overlap_top_k_edges = int(
                self.cfg["runtime"].get(
                    "debug_overlap_top_k_edges",
                    self.cfg["runtime"].get("debug_overlap_top_k", 80),
                )
            )
            overlap_max_edges = int(self.cfg["runtime"].get("debug_overlap_max_edges", 80))
            self._save_overlap_association_figure(
                overlap_df=overlap_df,
                learner_names=learner_names,
                out_path=overlap_fig_path,
                top_k_edges=overlap_top_k_edges,
                min_jaccard=overlap_min_jaccard,
                max_edges=overlap_max_edges,
            )
            overlap_summary = {
                "debug_overlap_enabled": True,
                "stream_sample_count": int(self.debug_overlap_stream_samples),
                "learner_count": int(len(learner_names)),
                "pair_count": int(len(overlap_df)),
                "plot_min_jaccard": overlap_min_jaccard,
                "plot_top_k_edges": overlap_top_k_edges,
                "plot_max_edges": overlap_max_edges,
                "top_pairs": overlap_df.head(20).to_dict(orient="records"),
            }
            with open(overlap_summary_path, "w", encoding="utf-8") as f:
                json.dump(overlap_summary, f, ensure_ascii=False, indent=2)

        if self.aggregate_overlap_enabled:
            agg_rows, mapping_rows, agg_meta = self._aggregate_learners_by_overlap(
                cumulative_rows=cumulative_rows,
                overlap_df=overlap_df,
            )
            agg_profile_path = self.output_dir / "learner_aggregated_distribution.csv"
            agg_map_path = self.output_dir / "learner_aggregation_mapping.csv"
            agg_summary_path = self.output_dir / "learner_aggregation_summary.json"
            pd.DataFrame(agg_rows).to_csv(agg_profile_path, index=False)
            pd.DataFrame(mapping_rows).to_csv(agg_map_path, index=False)
            with open(agg_summary_path, "w", encoding="utf-8") as f:
                json.dump(agg_meta, f, ensure_ascii=False, indent=2)
            self.logger.info(
                "Done. AGG_PROFILE=%s | AGG_MAP=%s | AGG_SUMMARY=%s | aggregates=%d",
                agg_profile_path,
                agg_map_path,
                agg_summary_path,
                int(agg_meta.get("aggregate_count", 0)),
            )
        perf_path = self.output_dir / "performance_metrics.json"
        windows_count = int(self.perf_stats["windows_count"])
        perf_summary = {
            **self.perf_stats,
            **self.cluster_gate_stats,
            "avg_detect_seconds_per_window": (
                self.perf_stats["detect_seconds_total"] / windows_count if windows_count else 0.0
            ),
            "avg_cluster_seconds_per_window": (
                self.perf_stats["cluster_seconds_total"] / windows_count if windows_count else 0.0
            ),
            "avg_create_learner_seconds_per_window": (
                self.perf_stats["create_learner_seconds_total"] / windows_count if windows_count else 0.0
            ),
            "avg_window_seconds": (
                self.perf_stats["window_total_seconds_total"] / windows_count if windows_count else 0.0
            ),
        }
        with open(perf_path, "w", encoding="utf-8") as f:
            json.dump(perf_summary, f, ensure_ascii=False, indent=2)
        assignment_path = self.output_dir / "sample_learner_assignments.csv"
        if assign_export_df.empty:
            pd.DataFrame(
                columns=["row_index", "assigned_learner", "phase", "timestamp"],
            ).to_csv(assignment_path, index=False)
        else:
            assign_export_df.to_csv(assignment_path, index=False)
        creation_idx_path = self.output_dir / "learner_creation_row_indices.json"
        with open(creation_idx_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    str(k): sorted(int(x) for x in v)
                    for k, v in self._learner_creation_row_indices.items()
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        learner_topology_path = self.output_dir / "learner_network_topology.json"
        try:
            from trident_stream.dataset_topology import save_learner_network_topology

            assign_index_df = assign_export_df[["row_index", "assigned_learner"]].copy()
            if save_learner_network_topology(data, assign_index_df, learner_topology_path):
                self.logger.info("Done. LEARNER_NETWORK_TOPOLOGY=%s", learner_topology_path)
        except Exception:
            self.logger.exception("Learner network topology export failed (non-fatal).")
        accept_trace_path = self.output_dir / "learner_accept_trace.csv"
        pd.DataFrame(self.learner_accept_trace).to_csv(accept_trace_path, index=False)

        plt.figure(figsize=(12, 5))
        plt.plot(ts_df["window_end_time"], ts_df["learner_count"], marker="o", linewidth=1.5)
        plt.xlabel("Time")
        plt.ylabel("Number of tSieve learners")
        plt.title("Streaming Trident-AE: Learner Count vs Time (CICIDS2017)")
        plt.grid(alpha=0.3)
        plt.tight_layout()
        fig_path = self.output_dir / "learner_count_over_time.png"
        plt.savefig(fig_path, dpi=180)
        plt.close()

        summary = {
            "total_windows": len(ts_df),
            "initial_learner_count": int(ts_df["learner_count"].iloc[0]) if len(ts_df) else len(self.tsieve.learners),
            "final_learner_count": int(ts_df["learner_count"].iloc[-1]) if len(ts_df) else len(self.tsieve.learners),
            "max_learner_count": int(ts_df["learner_count"].max()) if len(ts_df) else len(self.tsieve.learners),
            "feature_dim": len(feature_cols),
            "rows_used": len(data),
        }
        summary_path = self.output_dir / "run_summary.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            for k, v in summary.items():
                f.write(f"{k}: {v}\n")

        self.logger.info("Done. CSV=%s", csv_path)
        self.logger.info("Done. LEARNER_CREATION_PROFILE=%s", creation_profile_path)
        self.logger.info("Done. LEARNER_TRAIN_BATCH_PROFILE=%s", train_batch_profile_path)
        self.logger.info("Done. LEARNER_INCREMENT_LOSS_TRACE=%s", update_loss_profile_path)
        self.logger.info("Done. LEARNER_FIT_LOSS_TRACE=%s", fit_loss_profile_path)
        self.logger.info("Done. LEARNER_PROFILE=%s", profile_path)
        self.logger.info("Done. LEARNER_FEATURE_CORR_JSON=%s", feature_corr_json_path)
        self.logger.info("Done. LEARNER_FEATURE_CORR_FIG=%s", feature_corr_fig_path)
        self.logger.info("Done. SAMPLE_ASSIGNMENTS=%s", assignment_path)
        self.logger.info("Done. LEARNER_ACCEPT_TRACE=%s", accept_trace_path)
        self.logger.info(
            "Done. PERF_JSON=%s | detect=%.4fs cluster=%.4fs create=%.4fs retrain=%.4fs init_create=%.4fs",
            perf_path,
            self.perf_stats["detect_seconds_total"],
            self.perf_stats["cluster_seconds_total"],
            self.perf_stats["create_learner_seconds_total"],
            self.perf_stats["retrain_seconds_total"],
            self.perf_stats["init_create_learner_seconds_total"],
        )
        if self.debug_overlap_enabled:
            self.logger.info(
                "Done. TRUE_OVERLAP=%s | summary=%s | fig=%s | stream_samples=%d",
                overlap_pairs_path,
                overlap_summary_path,
                overlap_fig_path,
                self.debug_overlap_stream_samples,
            )
        self.logger.info(
            "Done. METRICS_JSON=%s | risk_fpr=%.4f%% risk_fnr=%.4f%%",
            metrics_path,
            metrics["risk_false_positive_rate"] * 100.0,
            metrics["risk_false_negative_rate"] * 100.0,
        )
        self.logger.info("Done. METRIC_CATALOG_JSON=%s", metric_catalog_path)
        self.logger.info("Done. FIG=%s", fig_path)
        self.logger.info("Done. SUMMARY=%s", summary_path)

