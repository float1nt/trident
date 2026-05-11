from pathlib import Path
from typing import Any, Dict, List, Tuple

import json
from datetime import datetime
from itertools import combinations
from time import perf_counter
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
import yaml

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
        )
        self.tmagnifier = TMagnifier(**cfg["tmagnifier"])
        self.next_new_id = 1
        self.learner_creation_profiles: List[Dict[str, object]] = []
        self.learner_cumulative_counts: Dict[str, Dict[str, int]] = {}
        self.freeze_benign_incremental = bool(cfg["runtime"].get("freeze_benign_incremental", False))
        self.run_id = str(cfg["runtime"].get("run_id", datetime.now().strftime("%Y%m%d_%H%M%S")))
        self.history_sample_rate = float(cfg["tsieve"].get("historical_sample_rate", 0.5))
        self.max_history_samples_per_learner = int(cfg["tsieve"].get("max_history_samples_per_learner", 10000))
        self.history_samples_per_update = int(cfg["tsieve"].get("history_samples_per_update", 2000))
        self.benign_history_confidence_scale = float(cfg["tsieve"].get("benign_history_confidence_scale", 0.6))
        self.learner_history_pool: Dict[str, np.ndarray] = {}
        self.sample_assignments: List[Dict[str, object]] = []
        self.debug_overlap_enabled = bool(cfg["runtime"].get("debug_overlap_enabled", False))
        self.debug_overlap_accept_count: Dict[str, int] = {}
        self.debug_overlap_pair_intersections: Dict[Tuple[str, str], int] = {}
        self.debug_overlap_stream_samples: int = 0
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

    def _log_learner_distribution(self, stage: str, learner_name: str, labels: np.ndarray) -> None:
        dist = self._label_distribution(labels)
        total = int(len(labels))
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
                    "learner_name": learner_name,
                    "total_assigned_samples": total,
                    "dominant_label": dominant_label,
                    "dominant_count": dominant_count,
                    "dominant_ratio": dominant_ratio,
                    "label_distribution_json": json.dumps(dist, ensure_ascii=False),
                }
            )
        return rows

    @staticmethod
    def _safe_div(x: float, y: float) -> float:
        return float(x / y) if y else 0.0

    def _append_history_pool(self, learner_name: str, samples: np.ndarray) -> None:
        if len(samples) == 0:
            return
        prev = self.learner_history_pool.get(learner_name)
        merged = samples.copy() if prev is None or len(prev) == 0 else np.concatenate([prev, samples], axis=0)
        if len(merged) > self.max_history_samples_per_learner:
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
        sampled = self.tsieve.interval_sample_by_loss(learner_name, hist, keep_count=keep_count)
        return sampled.astype(np.float32, copy=False)

    def _filter_benign_confident_samples(self, samples: np.ndarray) -> np.ndarray:
        """
        Keep only high-confidence BENIGN samples.
        Criterion: reconstruction_loss <= benign_history_confidence_scale * BENIGN threshold.
        """
        if len(samples) == 0:
            return samples
        benign_names = sorted([name for name in self.tsieve.learners if is_benign_label(name)])
        if not benign_names:
            return samples
        benign_learner = self.tsieve.learners[benign_names[0]]
        losses = benign_learner.reconstruction_loss(samples)
        # Use effective BENIGN acceptance threshold as baseline, then apply confidence scale.
        conf_th = float(
            benign_learner.threshold
            * self.tsieve.benign_accept_scale
            * self.benign_history_confidence_scale
        )
        keep_mask = losses <= conf_th
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

            if is_benign_label(learner_name):
                # Non-benign accepted by BENIGN learner are risk misses.
                non_benign_to_benign += non_benign_count
                continue

            # For risk false alarm, exclude learners dominated by BENIGN.
            if dominant_label != "BENIGN":
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
        data["Timestamp"] = pd.to_datetime(data["Timestamp"], errors="coerce")
        data = data.dropna(subset=["Timestamp"]).sort_values("Timestamp").reset_index(drop=True)
        data["LabelNorm"] = data["Label"].map(normalize_label)
        data = self._apply_attack_sampling(data)

        max_rows = self.cfg["runtime"]["max_rows"]
        if max_rows > 0 and len(data) > max_rows:
            data = data.iloc[:max_rows].reset_index(drop=True)

        feat_df, feature_cols = preprocess_features(data)
        x_all = feat_df.values.astype(np.float32)
        self.logger.info("Rows=%d, FeatureDim=%d", len(data), len(feature_cols))
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
                learner_labels = df_init["LabelNorm"].values[idx]
                self._log_learner_distribution(stage="init", learner_name=label, labels=learner_labels)
                self._accumulate_learner_distribution(learner_name=label, labels=learner_labels)
                self._append_history_pool(label, x_init[idx])
                self.logger.info(
                    "[Init] learner=%s, samples=%d, threshold=%.6f",
                    label,
                    len(idx),
                    self.tsieve.learners[label].threshold,
                )
        if not self.tsieve.learners:
            raise RuntimeError("No initial learners created")
        return init_end

    def run(self) -> None:
        self._log_hyperparameters()
        data, x_all, feature_cols = self._load_dataset()
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
                    self.tmagnifier.add_unknown(sample[0], str(chunk_labels[i]))
                else:
                    accepted_by_learner.setdefault(pred, []).append(sample[0])
                    accepted_labels_by_learner.setdefault(pred, []).append(str(chunk_labels[i]))
            t_detect_end = perf_counter()
            detect_seconds = t_detect_end - t_detect_start

            t_cluster_start = perf_counter()
            clusters = self.tmagnifier.pop_new_class_clusters()
            t_cluster_end = perf_counter()
            cluster_seconds = t_cluster_end - t_cluster_start
            create_seconds = 0.0
            retrain_seconds_window = 0.0
            for cluster_x, cluster_labels in clusters:
                name = f"NEW_{self.next_new_id}"
                self.next_new_id += 1
                t_create_start = perf_counter()
                ok = self.tsieve.add_learner(name, cluster_x, epochs=self.cfg["tsieve"]["new_class_epochs"])
                t_create_end = perf_counter()
                create_seconds += t_create_end - t_create_start
                if ok:
                    self.debug_overlap_accept_count.setdefault(name, 0)
                    self.perf_stats["new_learner_count"] += 1
                    accepted_by_learner.setdefault(name, [])
                    accepted_labels_by_learner.setdefault(name, [])
                    self._log_learner_distribution(stage="new", learner_name=name, labels=cluster_labels)
                    self._accumulate_learner_distribution(learner_name=name, labels=cluster_labels)
                    self._append_history_pool(name, cluster_x)
                    self.logger.info(
                        "[NewLearner] %s, samples=%d, total_learners=%d",
                        name,
                        len(cluster_x),
                        len(self.tsieve.learners),
                    )

            for name, accepted_labels in accepted_labels_by_learner.items():
                if not accepted_labels:
                    continue
                self._accumulate_learner_distribution(learner_name=name, labels=np.asarray(accepted_labels, dtype=object))

            for name, samples in accepted_by_learner.items():
                if len(samples) == 0:
                    continue
                arr_all_new = np.stack(samples, axis=0)
                if is_benign_label(name):
                    filtered = self._filter_benign_confident_samples(arr_all_new)
                    self.logger.info(
                        "[BenignConfidenceFilter] kept=%d dropped=%d scale=%.3f",
                        len(filtered),
                        len(arr_all_new) - len(filtered),
                        self.benign_history_confidence_scale,
                    )
                    arr_all_new = filtered
                    if len(arr_all_new) == 0:
                        continue

                self._append_history_pool(name, arr_all_new)

                if self.freeze_benign_incremental and is_benign_label(name):
                    continue
                if len(arr_all_new) < self.cfg["tsieve"]["increment_min_samples"]:
                    continue

                arr_new = arr_all_new
                max_inc = self.cfg["tsieve"]["max_increment_samples"]
                if len(arr_new) > max_inc:
                    idx = np.random.choice(len(arr_new), size=max_inc, replace=False)
                    arr_new = arr_new[idx]

                hist_sample = self._sample_history_for_update(name, feature_dim=arr_new.shape[1])
                arr_update = np.concatenate([hist_sample, arr_new], axis=0) if len(hist_sample) > 0 else arr_new
                t_retrain_start = perf_counter()
                self.tsieve.learners[name].fit_incremental(arr_update, epochs=self.cfg["tsieve"]["increment_epochs"])
                self.tsieve.refresh_threshold(name, arr_update)
                t_retrain_end = perf_counter()
                retrain_seconds = t_retrain_end - t_retrain_start
                retrain_seconds_window += retrain_seconds
                self.perf_stats["retrain_seconds_total"] += retrain_seconds
                self.perf_stats["incremental_update_count"] += 1
                self.logger.info(
                    "[IncrementalUpdate] learner=%s new=%d hist_sample=%d update_total=%d",
                    name,
                    len(arr_new),
                    len(hist_sample),
                    len(arr_update),
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
        profile_path = self.output_dir / "learner_label_distribution.csv"
        cumulative_rows = self._build_cumulative_profile_rows()
        pd.DataFrame(cumulative_rows).to_csv(profile_path, index=False)
        metrics_path = self.output_dir / "metrics.json"
        metrics = self._compute_run_metrics(cumulative_rows)
        with open(metrics_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        overlap_pairs_path = self.output_dir / "debug_true_overlap_pairs.csv"
        overlap_summary_path = self.output_dir / "debug_true_overlap_summary.json"
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
                        "learner_a": a,
                        "learner_b": b,
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
            overlap_summary = {
                "debug_overlap_enabled": True,
                "stream_sample_count": int(self.debug_overlap_stream_samples),
                "learner_count": int(len(learner_names)),
                "pair_count": int(len(overlap_df)),
                "top_pairs": overlap_df.head(20).to_dict(orient="records"),
            }
            with open(overlap_summary_path, "w", encoding="utf-8") as f:
                json.dump(overlap_summary, f, ensure_ascii=False, indent=2)
        perf_path = self.output_dir / "performance_metrics.json"
        windows_count = int(self.perf_stats["windows_count"])
        perf_summary = {
            **self.perf_stats,
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
        self.logger.info("Done. LEARNER_PROFILE=%s", profile_path)
        self.logger.info("Done. SAMPLE_ASSIGNMENTS=%s", assignment_path)
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
                "Done. TRUE_OVERLAP=%s | summary=%s | stream_samples=%d",
                overlap_pairs_path,
                overlap_summary_path,
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

