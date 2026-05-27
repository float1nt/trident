from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from ..persistence.learner_repository import LearnerRepository
from ..persistence.snapshot_repository import SnapshotRepository


class SnapshotService:
    def __init__(self, learners: LearnerRepository, snapshots: SnapshotRepository) -> None:
        self.learners = learners
        self.snapshots = snapshots

    def flush_snapshot(self, learner: dict[str, Any], *, reason: str, window_index: int | None = None) -> dict[str, Any]:
        version = int(learner.get("current_snapshot_version") or 0) + 1
        session_id = str(learner["session_id"])
        learner_name = str(learner["learner_name"])
        snapshot_id = _snapshot_id(session_id, learner_name, version)
        snapshot = {
            "snapshot_id": snapshot_id,
            "session_id": session_id,
            "learner_name": learner_name,
            "snapshot_version": version,
            "window_index": window_index,
            "snapshot_reason": reason,
            "profile_json": learner.get("profile_json"),
            "metric_json": learner.get("metric_json"),
            "rule_json": learner.get("rule_json"),
            "topology_json": learner.get("topology_json"),
            "risk_score": learner.get("risk_score"),
            "risk_band": learner.get("risk_band"),
            "risk_reason": learner.get("risk_reason"),
            "threshold": learner.get("threshold"),
            "model_state_hash": learner.get("model_state_hash"),
        }
        self.snapshots.insert_snapshot(snapshot)
        updated = dict(learner)
        updated["current_snapshot_id"] = snapshot_id
        updated["current_snapshot_version"] = version
        updated.setdefault("learner_status", "active")
        updated.setdefault("last_seen_at", datetime.now(timezone.utc))
        self.learners.upsert_current_learner(updated)
        return snapshot


def _snapshot_id(session_id: str, learner_name: str, version: int) -> str:
    digest = sha256(f"{session_id}|{learner_name}|{version}".encode("utf-8")).hexdigest()[:16]
    return f"{session_id}:{learner_name}:{version}:{digest}"
