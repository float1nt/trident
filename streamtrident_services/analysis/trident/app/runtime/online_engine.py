from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

import numpy as np
import torch
from sklearn.ensemble import IsolationForest

from ..config import TridentConfig
from ..flow_loader import FlowRecord
from ..window_buffer import FlowWindow
from .model_store import ModelStore
from .learner_overlap import LearnerOverlapConfig, LearnerOverlapSnapshot, build_learner_overlap_snapshot
from .preprocessing import preprocess_records
from .quality import SESSION_BASELINE_PROFILE_KEY, build_learner_audit, feature_drift_score
from .trident_algorithms import Learner, TMagnifier, TScissors, TSieve


@dataclass(frozen=True, slots=True)
class FlowAssignment:
    flow_uid: str
    assigned_learner: str
    is_unknown: bool
    pred_loss: float
    threshold: float
    assignment_meta: dict[str, Any]
    learner_snapshot_id: str = ""
    learner_snapshot_version: int = 0


@dataclass(frozen=True, slots=True)
class WindowResult:
    window_index: int
    assignments: list[FlowAssignment]
    new_learners: list[dict[str, Any]] = field(default_factory=list)
    updated_learners: list[dict[str, Any]] = field(default_factory=list)
    snapshot_requests: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    alerts: list[dict[str, Any]] = field(default_factory=list)


class OnlineEngine:
    """Runtime Trident engine using copied tSieve/tScissors/tMagnifier logic."""

    def __init__(
        self,
        *,
        session_id: str,
        cfg: TridentConfig,
        learner_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.session_id = session_id
        self.cfg = cfg
        self.model_store = ModelStore(cfg.model_store_dir)
        self.device = torch.device("cuda" if torch.cuda.is_available() and not cfg.cpu_only else "cpu")
        self.feature_columns: list[str] = []
        self.feature_profile = cfg.feature_profile
        self.tscissors = TScissors(
            evt_quantile=cfg.evt_quantile,
            evt_risk=cfg.evt_risk,
            fallback_quantile=cfg.fallback_quantile,
        )
        self.tsieve = TSieve(
            device=self.device,
            tscissors=self.tscissors,
            batch_size=cfg.tsieve_batch_size,
            lr=cfg.tsieve_lr,
            min_class_samples=cfg.min_class_samples,
            max_train_per_class=cfg.max_train_per_class,
            benign_accept_scale=cfg.benign_accept_scale,
            classifier_backend=cfg.algorithm_backend,
            seed=cfg.seed,
        )
        self.tmagnifier = TMagnifier(
            cluster_trigger_size=cfg.cluster_trigger_size,
            max_unknown_buffer=cfg.max_unknown_buffer,
            dbscan_eps=cfg.dbscan_eps,
            dbscan_min_samples=cfg.dbscan_min_samples,
            new_class_min_size=cfg.new_learner_min_size,
        )
        self.learner_snapshot_refs: dict[str, tuple[str, int]] = {}
        self.learner_creation_windows: dict[str, int] = {}
        self.learner_last_seen_windows: dict[str, int] = {}
        self.learner_histories: dict[str, list[np.ndarray]] = defaultdict(list)
        self.learner_record_histories: dict[str, list[FlowRecord]] = defaultdict(list)
        self.increment_iforest_guards: dict[str, dict[str, Any]] = {}
        self.small_recluster_counter = 0
        self.gate_stats: dict[str, int] = defaultdict(int)
        self.learner_overlap_snapshot: LearnerOverlapSnapshot | None = None
        self.learner_overlap_config = LearnerOverlapConfig()
        self.baseline_learner_name: str | None = None
        self.cold_start_complete = False
        self._load_learners(learner_rows or [])

    def process_window(self, window: FlowWindow) -> WindowResult:
        raw_records = [item.record for item in window.items]
        records, preprocessing_report = preprocess_records(
            raw_records,
            feature_profile=self.feature_profile,
            enabled=self.cfg.preprocessing_enabled,
            drop_all_zero=self.cfg.preprocessing_drop_all_zero,
        )
        if not records:
            return WindowResult(
                window_index=window.window_index,
                assignments=[],
                metrics={"flow_count": 0, "preprocessing": preprocessing_report},
            )
        x = self._records_to_matrix(records, update_schema=not self.feature_columns)
        if not self.tsieve.learners:
            self._create_initial_learner(records, x, window_index=window.window_index)

        details = self.tsieve.classify_batch_details(x)
        accepted_by_learner: dict[str, list[np.ndarray]] = defaultdict(list)
        accepted_records_by_learner: dict[str, list[FlowRecord]] = defaultdict(list)
        unknown_count = 0
        assignments: list[FlowAssignment] = []

        for i, record in enumerate(records):
            detail = details[i] if i < len(details) else {"pred": None, "losses": {}, "thresholds": {}}
            pred = detail.get("pred")
            losses = detail.get("losses") if isinstance(detail.get("losses"), dict) else {}
            thresholds = detail.get("thresholds") if isinstance(detail.get("thresholds"), dict) else {}
            if pred is None:
                unknown_count += 1
                self.tmagnifier.add_unknown(
                    x[i],
                    "0000|UNLABELED",
                    {"flow_uid": record.flow_uid, "window_index": window.window_index},
                )
                best_name, best_loss, best_threshold = _best_loss(losses, thresholds)
                assignments.append(
                    FlowAssignment(
                        flow_uid=record.flow_uid,
                        assigned_learner="",
                        is_unknown=True,
                        pred_loss=best_loss,
                        threshold=best_threshold,
                        assignment_meta={
                            "engine": "trident-tsieve",
                            "backend": self.cfg.algorithm_backend,
                            "candidate_learner": best_name,
                            "accepted_names": detail.get("accepted_names", []),
                        },
                    )
                )
                continue

            learner_name = str(pred)
            accepted_by_learner[learner_name].append(x[i])
            accepted_records_by_learner[learner_name].append(record)
            snapshot_id, snapshot_version = self.learner_snapshot_refs.get(learner_name, ("", 0))
            assignments.append(
                FlowAssignment(
                    flow_uid=record.flow_uid,
                    assigned_learner=learner_name,
                    is_unknown=False,
                    pred_loss=float(losses.get(learner_name, 0.0)),
                    threshold=float(thresholds.get(learner_name, self.tsieve.learners[learner_name].threshold)),
                    assignment_meta={
                        "engine": "trident-tsieve",
                        "backend": self.cfg.algorithm_backend,
                        "accepted_names": detail.get("accepted_names", []),
                    },
                    learner_snapshot_id=snapshot_id,
                    learner_snapshot_version=snapshot_version,
                )
            )

        for learner_name, learner_records in accepted_records_by_learner.items():
            self.learner_record_histories[learner_name].extend(learner_records)
            self.learner_record_histories[learner_name] = self.learner_record_histories[learner_name][-10000:]

        new_learner_names = self._create_new_learners_from_unknown(window.window_index)
        updated_learner_names = self._incremental_update(accepted_by_learner, window_index=window.window_index)
        recluster_created = self._maybe_recluster_small_learners(window.window_index)
        new_learner_names.extend(recluster_created)
        self._refresh_learner_overlap_snapshot()
        self._maybe_finalize_cold_start(window_flow_count=len(records))

        snapshot_names = list(dict.fromkeys([*new_learner_names, *updated_learner_names]))
        snapshot_requests = [
            {"learner": self._learner_row(name), "reason": "new_learner" if name in new_learner_names else "window_update"}
            for name in snapshot_names
        ]
        metrics = {
            "window_index": window.window_index,
            "flow_count": len(records),
            "accepted_count": len(records) - unknown_count,
            "unknown_count": unknown_count,
            "new_learner_count": len(new_learner_names),
            "updated_learner_count": len(updated_learner_names),
            "unknown_buffer_size": len(self.tmagnifier.unknown_buffer),
            "learner_count": len(self.tsieve.learners),
            "feature_count": len(self.feature_columns),
            "device": str(self.device),
            "backend": self.cfg.algorithm_backend,
            "gate_stats": dict(self.gate_stats),
            "preprocessing": preprocessing_report,
        }
        alerts = [
            {
                "type": "unknown_cluster_promoted",
                "session_id": self.session_id,
                "window_index": window.window_index,
                "learner_name": name,
            }
            for name in new_learner_names
        ]
        return WindowResult(
            window_index=window.window_index,
            assignments=assignments,
            new_learners=[self._learner_row(name) for name in new_learner_names],
            updated_learners=[self._learner_row(name) for name in updated_learner_names],
            snapshot_requests=snapshot_requests,
            metrics=metrics,
            alerts=alerts,
        )

    def set_snapshot_ref(self, learner_name: str, snapshot_id: str, snapshot_version: int) -> None:
        self.learner_snapshot_refs[str(learner_name)] = (str(snapshot_id), int(snapshot_version))

    def _create_initial_learner(self, records: list[FlowRecord], x: np.ndarray, *, window_index: int) -> None:
        name = "0000|UNLABELED"
        if len(x) < self.cfg.min_class_samples:
            old_min = self.tsieve.min_class_samples
            self.tsieve.min_class_samples = max(1, len(x))
            try:
                self.tsieve.add_learner(name, x, epochs=self.cfg.init_epochs)
            finally:
                self.tsieve.min_class_samples = old_min
        else:
            self.tsieve.add_learner(name, x, epochs=self.cfg.init_epochs)
        if name in self.tsieve.learners:
            self.baseline_learner_name = name
            self.learner_creation_windows[name] = window_index
            self.learner_last_seen_windows[name] = window_index

    def _maybe_finalize_cold_start(self, *, window_flow_count: int) -> None:
        if self.cold_start_complete:
            return
        if window_flow_count < self.cfg.window_size and len(self.tsieve.learners) <= 1:
            return
        self.cold_start_complete = True
        if not self.tsieve.learners:
            return
        self.baseline_learner_name = max(
            self.tsieve.learners.keys(),
            key=lambda learner_name: int(self.tsieve.learners[learner_name].train_sample_count),
        )

    def _create_new_learners_from_unknown(self, window_index: int) -> list[str]:
        created: list[str] = []
        clusters = self.tmagnifier.pop_new_class_clusters()
        for cluster_x, cluster_labels, cluster_meta in clusters:
            if self.cfg.cluster_purity_gate_enabled and not self._cluster_purity_gate(cluster_x):
                self.gate_stats["cluster_purity_reject"] += 1
                if self.cfg.cluster_gate_rejected_action == "reinject_unknown":
                    for i in range(len(cluster_x)):
                        meta = cluster_meta[i] if i < len(cluster_meta) else {}
                        self.tmagnifier.add_unknown(cluster_x[i], str(cluster_labels[i]), meta)
                continue
            name = f"NEW_{len(self.tsieve.learners)}"
            ok = self.tsieve.add_learner(name, cluster_x, epochs=self.cfg.new_class_epochs)
            if ok:
                created.append(name)
                self.learner_creation_windows[name] = window_index
                self.learner_last_seen_windows[name] = window_index
                self._append_history(name, cluster_x)
                self._fit_increment_iforest_guard(name, cluster_x)
        return created

    def _incremental_update(self, accepted_by_learner: dict[str, list[np.ndarray]], *, window_index: int) -> list[str]:
        updated: list[str] = []
        for name, samples in accepted_by_learner.items():
            if not samples or name not in self.tsieve.learners:
                continue
            arr_new = np.stack(samples, axis=0)
            if self.tsieve.is_benign_learner(name):
                keep = self._filter_benign_confident_mask(arr_new)
                if not np.all(keep):
                    self.gate_stats["benign_confidence_filtered"] += int(len(keep) - int(np.sum(keep)))
                arr_new = arr_new[keep]
                if len(arr_new) == 0:
                    self.learner_last_seen_windows[name] = window_index
                    continue
            self._append_history(name, arr_new)
            if len(arr_new) < self.cfg.increment_min_samples:
                self.learner_last_seen_windows[name] = window_index
                continue
            if self.cfg.increment_drift_gate_enabled and not self._passes_drift_gate(name, arr_new):
                self.gate_stats["increment_drift_reject"] += 1
                self.learner_last_seen_windows[name] = window_index
                continue
            if self.cfg.increment_route_gate_enabled and self._route_gate_applies(name, arr_new):
                route_eval = self._compute_increment_route_confidence(name, arr_new)
                if bool(route_eval.get("valid", False)):
                    route_keep = np.asarray(route_eval.get("keep_mask"), dtype=bool)
                    if len(route_keep) == len(arr_new):
                        arr_new = arr_new[route_keep]
                        self.gate_stats["increment_route_filtered"] += int(len(route_keep) - int(np.sum(route_keep)))
                    if float(route_eval.get("confident_ratio", 1.0)) < self.cfg.increment_route_min_confident_ratio:
                        self.gate_stats["increment_route_reject"] += 1
                        self.learner_last_seen_windows[name] = window_index
                        continue
                if len(arr_new) < self.cfg.increment_min_samples:
                    self.gate_stats["increment_route_min_reject"] += 1
                    self.learner_last_seen_windows[name] = window_index
                    continue
            if self.cfg.increment_iforest_guard_enabled and self._iforest_guard_applies(name, arr_new):
                guard_eval = self._apply_increment_iforest_guard(name, arr_new)
                if bool(guard_eval.get("valid", False)):
                    guard_keep = np.asarray(guard_eval.get("keep_mask"), dtype=bool)
                    if len(guard_keep) == len(arr_new):
                        arr_new = arr_new[guard_keep]
                        self.gate_stats["increment_iforest_filtered"] += int(len(guard_keep) - int(np.sum(guard_keep)))
                if len(arr_new) < self.cfg.increment_min_samples:
                    self.gate_stats["increment_iforest_min_reject"] += 1
                    self.learner_last_seen_windows[name] = window_index
                    continue
            if len(arr_new) > self.cfg.max_increment_samples:
                arr_new = self._sample_increment_new(name, arr_new, self.cfg.max_increment_samples)
            hist = self._sample_history(name, exclude_latest=len(samples), feature_dim=arr_new.shape[1])
            arr_update = np.concatenate([hist, arr_new], axis=0) if len(hist) else arr_new
            self.tsieve.learners[name].fit_incremental(arr_update, epochs=self.cfg.increment_epochs)
            self.tsieve.refresh_threshold(name, arr_update)
            self._fit_increment_iforest_guard(name, arr_update)
            self.learner_last_seen_windows[name] = window_index
            updated.append(name)
        return updated

    def _append_history(self, name: str, samples: np.ndarray) -> None:
        if len(samples) == 0:
            return
        self.learner_histories[name].extend([row.copy() for row in samples])
        max_hist = max(1, self.cfg.max_history_samples_per_learner)
        if len(self.learner_histories[name]) > max_hist:
            idx = np.linspace(0, len(self.learner_histories[name]) - 1, num=max_hist, dtype=int)
            self.learner_histories[name] = [self.learner_histories[name][int(i)] for i in idx]

    def _sample_history(self, name: str, *, exclude_latest: int, feature_dim: int) -> np.ndarray:
        history = self.learner_histories.get(name, [])
        if exclude_latest > 0 and len(history) > exclude_latest:
            history = history[:-exclude_latest]
        if not history:
            return np.empty((0, feature_dim), dtype=np.float64)
        target = int(min(len(history), max(0, self.cfg.history_samples_per_update)))
        if target <= 0:
            target = int(max(1, round(len(history) * max(0.0, min(1.0, self.cfg.history_sample_rate)))))
        if len(history) > target:
            if self.cfg.history_time_decay_lambda > 0:
                positions = np.arange(len(history), dtype=np.float64)
                weights = np.exp(self.cfg.history_time_decay_lambda * (positions - positions.max()) / max(1.0, positions.max()))
                weights = weights / weights.sum()
                rng = np.random.default_rng(self.cfg.seed)
                idx = np.sort(rng.choice(len(history), size=target, replace=False, p=weights))
            else:
                idx = np.linspace(0, len(history) - 1, num=target, dtype=int)
            history = [history[int(i)] for i in idx]
        return np.stack(history, axis=0)

    def _records_to_matrix(self, records: list[FlowRecord], *, update_schema: bool) -> np.ndarray:
        rows = [_record_features(record) for record in records]
        if update_schema:
            keys = sorted({key for row in rows for key in row})
            self.feature_columns = keys or ["__bias"]
        matrix = np.zeros((len(rows), len(self.feature_columns)), dtype=np.float64)
        for i, row in enumerate(rows):
            for j, col in enumerate(self.feature_columns):
                matrix[i, j] = float(row.get(col, 0.0))
        matrix[~np.isfinite(matrix)] = 0.0
        return matrix

    def _learner_row(self, name: str) -> dict[str, Any]:
        learner = self.tsieve.learners[name]
        snapshot_id, snapshot_version = self.learner_snapshot_refs.get(name, ("", 0))
        recent_records = self.learner_record_histories.get(name, [])[-10000:]
        audit_metric, topology_json, rule_json, risk_score, risk_band, risk_reason = build_learner_audit(
            learner_name=name,
            records=recent_records,
            flow_count=int(learner.train_sample_count),
            unknown_buffer_size=len(self.tmagnifier.unknown_buffer),
            threshold=float(learner.threshold),
            session_baseline_learner=self.baseline_learner_name,
        )
        profile_json = {
            "algorithm": "trident_core_replicated",
            "component": "tSieve+tScissors+tMagnifier",
            "feature_profile": self.feature_profile,
            "feature_columns": self.feature_columns,
            "threshold": float(learner.threshold),
            "backend": learner.classifier_backend,
            SESSION_BASELINE_PROFILE_KEY: self.baseline_learner_name,
            "quality_gates": {
                "benign_confidence_filter": True,
                "cluster_purity_gate": self.cfg.cluster_purity_gate_enabled,
                "increment_route_gate": self.cfg.increment_route_gate_enabled,
                "increment_iforest_guard": self.cfg.increment_iforest_guard_enabled,
                "increment_drift_gate": self.cfg.increment_drift_gate_enabled,
                "small_learner_recluster": self.cfg.small_learner_recluster_enabled,
                "history_sampling": {
                    "history_sample_rate": self.cfg.history_sample_rate,
                    "history_samples_per_update": self.cfg.history_samples_per_update,
                    "max_history_samples_per_learner": self.cfg.max_history_samples_per_learner,
                },
            },
        }
        overlap_group = None
        overlap_member_count = 0
        overlap_internal_jaccard = 0.0
        overlap_meta: dict[str, Any] = {}
        if self.learner_overlap_snapshot is not None:
            overlap_group = self.learner_overlap_snapshot.mapping.get(name)
            overlap_meta = dict(self.learner_overlap_snapshot.meta)
            if overlap_group:
                aggregate = next(
                    (item for item in self.learner_overlap_snapshot.aggregates if item.aggregate_name == overlap_group),
                    None,
                )
                if aggregate is not None:
                    overlap_member_count = int(aggregate.member_count)
                    overlap_internal_jaccard = float(aggregate.avg_internal_jaccard)
                profile_json["learner_overlap"] = {
                    "aggregate_name": overlap_group,
                    "member_count": overlap_member_count,
                    "internal_avg_jaccard": overlap_internal_jaccard,
                    "selected_edge_count": int(overlap_meta.get("selected_edge_count", 0)),
                    "used_edge_count_after_algo": int(overlap_meta.get("used_edge_count_after_algo", 0)),
                }
        model_ref = self.model_store.save(
            session_id=self.session_id,
            learner_name=name,
            payload=learner.serialize(),
        )
        profile_json["model_ref"] = {
            "type": "file",
            "path": model_ref,
            "format": "trident_learner_json_v1",
        }
        metric_json = {
            **audit_metric,
            "flow_count": int(learner.train_sample_count),
            "last_seen_window_index": int(self.learner_last_seen_windows.get(name, 0)),
            "unknown_buffer_size": int(len(self.tmagnifier.unknown_buffer)),
            "gate_stats": dict(self.gate_stats),
        }
        if overlap_group is not None:
            metric_json["overlap_group_name"] = overlap_group
            metric_json["overlap_group_size"] = overlap_member_count
            metric_json["overlap_internal_avg_jaccard"] = overlap_internal_jaccard
            metric_json["overlap_accept_count"] = int(self.learner_overlap_snapshot.accept_count.get(name, 0))
        return {
            "session_id": self.session_id,
            "learner_name": name,
            "learner_status": "active",
            "creation_window_index": int(self.learner_creation_windows.get(name, 0)),
            "last_seen_window_index": int(self.learner_last_seen_windows.get(name, 0)),
            "last_seen_at": datetime.now(timezone.utc),
            "current_snapshot_id": snapshot_id,
            "current_snapshot_version": snapshot_version,
            "flow_count": int(learner.train_sample_count),
            "assignment_share": None,
            "unknown_absorb_count": 0,
            "stability_score": None,
            "drift_score": None,
            "risk_score": risk_score,
            "risk_band": risk_band,
            "risk_reason": risk_reason,
            "profile_json": profile_json,
            "metric_json": metric_json,
            "rule_json": rule_json,
            "topology_json": topology_json,
            "threshold": float(learner.threshold),
            "model_state_hash": _state_hash(profile_json),
        }

    def _refresh_learner_overlap_snapshot(self) -> None:
        if len(self.tsieve.learners) < 2:
            self.learner_overlap_snapshot = None
            return
        try:
            self.learner_overlap_snapshot = build_learner_overlap_snapshot(
                tsieve=self.tsieve,
                learner_histories=self.learner_histories,
                config=self.learner_overlap_config,
            )
        except Exception:
            self.learner_overlap_snapshot = None

    def _load_learners(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            profile = row.get("profile_json") if isinstance(row.get("profile_json"), dict) else {}
            model_payload = profile.get("trident_model") if isinstance(profile, dict) else None
            if not isinstance(model_payload, dict) and isinstance(profile, dict):
                model_ref = profile.get("model_ref")
                if isinstance(model_ref, dict) and model_ref.get("path"):
                    model_payload = self.model_store.load(str(model_ref["path"]))
            if not isinstance(model_payload, dict):
                continue
            try:
                learner = Learner.deserialize(model_payload, device=self.device)
            except Exception:
                continue
            if not learner.name:
                learner.name = str(row.get("learner_name") or "")
            if not learner.name:
                continue
            self.tsieve.learners[learner.name] = learner
            self.feature_columns = [str(x) for x in profile.get("feature_columns", [])] or self.feature_columns
            self.learner_snapshot_refs[learner.name] = (
                str(row.get("current_snapshot_id") or ""),
                int(row.get("current_snapshot_version") or 0),
            )
            self.learner_creation_windows[learner.name] = int(row.get("creation_window_index") or 0)
            self.learner_last_seen_windows[learner.name] = int(row.get("last_seen_window_index") or 0)
            profile = row.get("profile_json") if isinstance(row.get("profile_json"), dict) else {}
            stored_baseline = str(profile.get(SESSION_BASELINE_PROFILE_KEY) or "").strip()
            if stored_baseline:
                self.baseline_learner_name = stored_baseline
                self.cold_start_complete = True

    def _cluster_purity_gate(self, samples: np.ndarray) -> bool:
        benign_names = [name for name in self.tsieve.learners if self.tsieve.is_benign_learner(name)]
        if not benign_names or len(samples) == 0:
            return True
        details = self.tsieve.classify_batch_details(samples)
        benign_accept = 0
        for detail in details:
            accepted = detail.get("accepted_names", [])
            if isinstance(accepted, list) and any(str(name) in benign_names for name in accepted):
                benign_accept += 1
        rate = benign_accept / max(1, len(samples))
        return rate <= self.cfg.cluster_gate_max_benign_accept_rate

    def _filter_benign_confident_mask(self, samples: np.ndarray) -> np.ndarray:
        if len(samples) == 0:
            return np.zeros(0, dtype=bool)
        benign_names = sorted([name for name in self.tsieve.learners if self.tsieve.is_benign_learner(name)])
        if not benign_names:
            return np.ones(len(samples), dtype=bool)
        learner = self.tsieve.learners[benign_names[0]]
        losses = learner.reconstruction_loss(samples)
        threshold = learner.threshold * self.tsieve.benign_accept_scale * self.cfg.benign_history_confidence_scale
        return losses <= threshold

    def _passes_drift_gate(self, name: str, samples: np.ndarray) -> bool:
        history = self._sample_history(name, exclude_latest=len(samples), feature_dim=samples.shape[1])
        if len(history) < self.cfg.increment_drift_min_history_samples:
            return True
        score = feature_drift_score(history, samples)
        if not np.isfinite(score):
            return True
        return score >= self.cfg.increment_drift_min_score

    def _route_gate_applies(self, name: str, samples: np.ndarray) -> bool:
        if len(samples) < self.cfg.increment_route_min_samples:
            return False
        return (not self.cfg.increment_route_apply_to_new_only) or str(name).startswith("NEW_")

    def _compute_increment_route_confidence(self, learner_name: str, samples: np.ndarray) -> dict[str, Any]:
        names, losses_matrix, thresholds = self.tsieve._batch_losses_and_thresholds(samples)
        if len(names) < 2 or learner_name not in names:
            return {"valid": False, "keep_mask": np.ones(len(samples), dtype=bool), "confident_ratio": 1.0}
        idx = int(names.index(learner_name))
        margins = (thresholds[:, None] - losses_matrix) / (np.abs(thresholds[:, None]) + 1e-12)
        own_margin = margins[idx]
        other_best = np.max(np.delete(margins, idx, axis=0), axis=0)
        gap = own_margin - other_best
        keep = (own_margin >= self.cfg.increment_route_min_own_margin) & (gap >= self.cfg.increment_route_min_margin_gap)
        return {
            "valid": True,
            "keep_mask": keep.astype(bool, copy=False),
            "confident_ratio": float(np.mean(keep)),
            "own_margin_p10": float(np.quantile(own_margin, 0.10)),
            "gap_p10": float(np.quantile(gap, 0.10)),
        }

    def _iforest_guard_applies(self, name: str, samples: np.ndarray) -> bool:
        if len(samples) < self.cfg.increment_iforest_guard_min_samples:
            return False
        return (not self.cfg.increment_iforest_guard_apply_to_new_only) or str(name).startswith("NEW_")

    def _fit_increment_iforest_guard(self, name: str, samples: np.ndarray) -> bool:
        if not self.cfg.increment_iforest_guard_enabled or len(samples) < max(2, self.cfg.increment_iforest_guard_min_samples // 2):
            return False
        x = np.asarray(samples, dtype=np.float32)
        if len(x) > self.cfg.increment_iforest_guard_train_max_samples:
            idx = np.linspace(0, len(x) - 1, num=self.cfg.increment_iforest_guard_train_max_samples, dtype=int)
            x = x[idx]
        model = IsolationForest(
            n_estimators=self.cfg.increment_iforest_guard_n_estimators,
            contamination="auto",
            random_state=self.cfg.seed,
            n_jobs=-1,
        )
        model.fit(x)
        scores = model.score_samples(x)
        q = float(np.clip(1.0 - self.cfg.increment_iforest_guard_keep_quantile, 0.01, 0.50))
        self.increment_iforest_guards[name] = {
            "model": model,
            "score_cutoff": float(np.quantile(scores, q)),
            "seed_count": int(len(x)),
        }
        return True

    def _apply_increment_iforest_guard(self, name: str, samples: np.ndarray) -> dict[str, Any]:
        if name not in self.increment_iforest_guards:
            seed = self._sample_history(name, exclude_latest=0, feature_dim=samples.shape[1])
            self._fit_increment_iforest_guard(name, seed)
        guard = self.increment_iforest_guards.get(name)
        if not guard:
            return {"valid": False, "keep_mask": np.ones(len(samples), dtype=bool), "kept_ratio": 1.0}
        model = guard["model"]
        cutoff = float(guard["score_cutoff"])
        scores = model.score_samples(np.asarray(samples, dtype=np.float32))
        keep = scores >= cutoff
        return {
            "valid": True,
            "keep_mask": keep.astype(bool, copy=False),
            "kept_ratio": float(np.mean(keep)),
            "score_p10": float(np.quantile(scores, 0.10)),
            "score_p50": float(np.quantile(scores, 0.50)),
        }

    def _sample_increment_new(self, name: str, samples: np.ndarray, max_keep: int) -> np.ndarray:
        if len(samples) <= max_keep:
            return samples
        q_keep = min(1.0, max(0.05, self.cfg.increment_low_loss_quantile_keep))
        arr = samples
        if q_keep < 1.0:
            losses = self.tsieve.learners[name].reconstruction_loss(arr)
            arr = arr[losses <= float(np.quantile(losses, q_keep))]
            if len(arr) <= max_keep:
                return arr
        if self.cfg.increment_sampling_mode == "stratified_loss":
            return self.tsieve.interval_sample_by_loss(name, arr, max_keep)
        rng = np.random.default_rng(self.cfg.seed)
        idx = rng.choice(len(arr), size=max_keep, replace=False)
        return arr[idx]

    def _maybe_recluster_small_learners(self, window_index: int) -> list[str]:
        if not self.cfg.small_learner_recluster_enabled:
            return []
        self.small_recluster_counter += 1
        if self.small_recluster_counter < self.cfg.small_learner_recluster_count_trigger:
            return []
        self.small_recluster_counter = 0
        candidates = [
            name
            for name, learner in list(self.tsieve.learners.items())
            if str(name).startswith("NEW_") and int(learner.train_sample_count) < self.cfg.small_learner_sample_threshold
        ]
        if not candidates:
            return []
        for name in candidates:
            history = self.learner_histories.get(name, [])
            for sample in history:
                self.tmagnifier.add_unknown(sample, "0000|UNLABELED", {"source": "small_learner_recluster", "learner": name})
            self.tsieve.learners.pop(name, None)
            self.learner_histories.pop(name, None)
            self.learner_record_histories.pop(name, None)
            self.learner_snapshot_refs.pop(name, None)
            self.gate_stats["small_learner_recluster_destroyed"] += 1
        return self._create_new_learners_from_unknown(window_index)


def assignment_meta_json(assignment: FlowAssignment) -> str:
    return json.dumps(assignment.assignment_meta, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _record_features(record: FlowRecord) -> dict[str, float]:
    try:
        payload = json.loads(record.features_json)
    except json.JSONDecodeError:
        payload = {}
    out: dict[str, float] = {
        "src_port": _scale_port(record.src_port),
        "dst_port": _scale_port(record.dst_port),
        "protocol": min(max(record.protocol, 0), 255) / 255.0,
    }
    if isinstance(payload, dict):
        for key, value in payload.items():
            number = _to_float(value)
            if number is not None:
                out[str(key)] = _scale_number(number)
    return out or {"__bias": 1.0}


def _best_loss(losses: dict[Any, Any], thresholds: dict[Any, Any]) -> tuple[str, float, float]:
    if not losses:
        return "", 0.0, 0.0
    best_name = min(losses, key=lambda key: float(losses[key]))
    return str(best_name), float(losses[best_name]), float(thresholds.get(best_name, 0.0))


def _scale_number(value: float) -> float:
    return float(np.sign(value) * np.log1p(abs(value)) / 20.0)


def _scale_port(value: int) -> float:
    return min(max(value, 0), 65535) / 65535.0


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if np.isfinite(number) else None
    return None


def _state_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(_without_model_payload(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def _without_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    clone = dict(payload)
    return clone
