from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import json
from datetime import datetime
from itertools import combinations
from time import perf_counter
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
    "Average Packet Size",
    "Active Mean",
    "Active Std",
    "Idle Mean",
    "Idle Std",
]


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

        self.output_dir = Path(cfg["paths"]["output_dir"])
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
        self.learner_birth_window: Dict[str, int] = {}
        self.benign_anchor_learners: set[str] = set()
        self.uniform_learner_treatment = bool(cfg["runtime"].get("uniform_learner_treatment", False))
        self.sample_assignments: List[Dict[str, object]] = []
        self.learner_accept_trace: List[Dict[str, object]] = []
        self.feature_profile = str(cfg.get("runtime", {}).get("feature_profile", "all_numeric_no_env"))
        self.pca_n_components = int(cfg.get("runtime", {}).get("pca_n_components", 0))
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

    def _record_learner_samples(self, learner_name: str, samples: np.ndarray) -> None:
        if len(samples) == 0:
            return
        chunk = np.asarray(samples, dtype=np.float32)
        if chunk.ndim == 1:
            chunk = chunk.reshape(1, -1)
        if chunk.shape[0] == 0:
            return
        self.learner_assigned_feature_chunks.setdefault(str(learner_name), []).append(chunk)

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
        clusters: List[Tuple[np.ndarray, np.ndarray]],
        left: int,
        right: int,
        window_size: int,
        accepted_by_learner: Dict[str, List[np.ndarray]],
        accepted_labels_by_learner: Dict[str, List[str]],
        accepted_meta_by_learner: Dict[str, List[Dict[str, object]]],
        source: str,
    ) -> float:
        create_seconds = 0.0
        for cluster_x, cluster_labels in clusters:
            cluster_labels_arr = np.asarray(cluster_labels, dtype=object)
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
                            self.tmagnifier.add_unknown(cluster_x[i_rej], str(cluster_labels_arr[i_rej]))
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
            self._record_learner_samples(learner_name=name, samples=cluster_x)
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
    ) -> Tuple[np.ndarray, np.ndarray]:
        sample_chunks: List[np.ndarray] = []
        payload_labels: List[str] = []
        for learner_name in learner_names:
            tag = f"RECLUSTER|{learner_name}"
            for chunk in self.learner_assigned_feature_chunks.get(str(learner_name), []):
                arr = np.asarray(chunk, dtype=np.float32)
                if arr.ndim == 1:
                    arr = arr.reshape(1, -1)
                if len(arr) == 0:
                    continue
                sample_chunks.append(arr)
                payload_labels.extend([tag] * int(arr.shape[0]))
            pending = accepted_by_learner.get(str(learner_name), [])
            if pending:
                arr_pending = np.stack(pending, axis=0).astype(np.float32, copy=False)
                if len(arr_pending) > 0:
                    sample_chunks.append(arr_pending)
                    payload_labels.extend([tag] * int(arr_pending.shape[0]))
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
        self.learner_birth_window.pop(name, None)
        self.learner_creation_sample_count.pop(name, None)
        self.learner_cumulative_counts.pop(name, None)
        self.learner_assigned_feature_chunks.pop(name, None)
        self.debug_overlap_accept_count.pop(name, None)
        if self.debug_overlap_pair_intersections:
            drop_keys = [k for k in self.debug_overlap_pair_intersections.keys() if name in k]
            for k in drop_keys:
                self.debug_overlap_pair_intersections.pop(k, None)

    def _maybe_recluster_small_learners(
        self,
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
        )
        if len(payload_x) == 0:
            return 0.0

        for learner_name in candidate_names:
            accepted_by_learner.pop(learner_name, None)
            accepted_labels_by_learner.pop(learner_name, None)
            accepted_meta_by_learner.pop(learner_name, None)
            self._destroy_learner_for_recluster(learner_name)

        for i in range(len(payload_x)):
            self.tmagnifier.add_unknown(payload_x[i], str(payload_labels[i]))

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
        data = self._apply_attack_sampling(data)

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
        init_ratio = self.cfg["stream"]["init_ratio"]
        init_end = int(len(data) * init_ratio)
        init_end = max(init_end, 5000)
        init_end = min(init_end, len(data) - 1000)

        df_init = data.iloc[:init_end]
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
                self._record_learner_samples(learner_name=label, samples=x_init[idx])
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

    def run(self) -> None:
        self._log_hyperparameters()
        data, x_all, feature_cols = self._load_dataset()
        dataset_label_rows = self._build_dataset_label_distribution_rows(data)
        dataset_label_csv_path = self.output_dir / "dataset_label_distribution.csv"
        dataset_label_summary_path = self.output_dir / "dataset_label_distribution_summary.json"
        pd.DataFrame(dataset_label_rows).to_csv(dataset_label_csv_path, index=False)
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
        self.logger.info(
            "Done. DATASET_LABEL_DISTRIBUTION=%s | SUMMARY=%s | labels=%d",
            dataset_label_csv_path,
            dataset_label_summary_path,
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
                        "timestamp": str(chunk_df["Timestamp"].iloc[i]),
                        "assigned_learner": str(assigned_learner),
                        "phase": "stream",
                    }
                )
                if pred is None:
                    self._record_learner_samples(learner_name="UNKNOWN", samples=sample)
                    self.tmagnifier.add_unknown(sample[0], str(chunk_labels[i]))
                else:
                    accepted_by_learner.setdefault(pred, []).append(sample[0])
                    accepted_labels_by_learner.setdefault(pred, []).append(str(chunk_labels[i]))
                    accepted_meta_by_learner.setdefault(pred, []).append(
                        {
                            "row_index": int(left + i),
                            "timestamp": str(chunk_df["Timestamp"].iloc[i]),
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
                left=int(left),
                right=int(right),
                window_size=int(window_size),
                accepted_by_learner=accepted_by_learner,
                accepted_labels_by_learner=accepted_labels_by_learner,
                accepted_meta_by_learner=accepted_meta_by_learner,
                source="unknown_cluster",
            )
            create_seconds += self._maybe_recluster_small_learners(
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
                self._record_learner_samples(learner_name=name, samples=arr_all_new)
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
        cumulative_rows = self._build_cumulative_profile_rows()
        profile_df = pd.DataFrame(cumulative_rows)
        if not profile_df.empty and "attack_ratio" in profile_df.columns:
            profile_df = profile_df.sort_values(
                by="attack_ratio",
                ascending=False,
                kind="mergesort",
            )
        profile_df.to_csv(profile_path, index=False)
        learner_risk_path = self.output_dir / "learner_risk_scores.csv"
        risk_rows = self._build_unsupervised_learner_risk_rows()
        pd.DataFrame(risk_rows).to_csv(learner_risk_path, index=False)
        self.logger.info("Done. LEARNER_RISK=%s", learner_risk_path)
        metrics_path = self.output_dir / "metrics.json"
        metrics = self._compute_run_metrics(cumulative_rows)
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
        pd.DataFrame(self.sample_assignments).to_csv(assignment_path, index=False)
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
        self.logger.info("Done. FIG=%s", fig_path)
        self.logger.info("Done. SUMMARY=%s", summary_path)

