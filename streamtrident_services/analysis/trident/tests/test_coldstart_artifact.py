from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.coldstart_artifact import (
    MODEL_FORMAT,
    build_manifest,
    build_snapshot_id_map,
    collect_model_entries,
    install_artifact_models,
    remap_learner_row,
    remap_runtime,
    remap_snapshot_row,
)
from app.config import TridentConfig
from app.runtime.model_store import ModelStore


def _learner_row(model_path: Path) -> dict[str, object]:
    return {
        "session_id": "source-session",
        "learner_name": "COLD_0|BENIGN",
        "flow_count": 123,
        "current_snapshot_id": "source-session:COLD_0|BENIGN:1:old",
        "current_snapshot_version": 1,
        "profile_json": {
            "feature_columns": ["bytes", "dst_port"],
            "model_ref": {
                "type": "file",
                "path": str(model_path),
                "format": MODEL_FORMAT,
            },
        },
    }


def test_collect_model_entries_and_manifest_include_model_hash(tmp_path: Path) -> None:
    model_path = tmp_path / "COLD_0_BENIGN.json"
    model_path.write_text("{\"name\":\"COLD_0|BENIGN\"}", encoding="utf-8")
    row = _learner_row(model_path)

    entries = collect_model_entries([row])
    manifest = build_manifest(
        cfg=replace(TridentConfig(), feature_profile="compact_stats_no_env", algorithm_backend="iforest"),
        session_id="source-session",
        learner_rows=[row],
        model_entries=entries,
        snapshot_count=1,
    )

    assert entries[0]["artifact_path"] == "models/COLD_0_BENIGN.json"
    assert entries[0]["sha256"]
    assert manifest["artifact_version"] == 1
    assert manifest["learners"][0]["model"]["sha256"] == entries[0]["sha256"]


def test_install_models_and_remap_rows_rewrite_session_snapshot_and_model_path(tmp_path: Path) -> None:
    unpacked = tmp_path / "unpacked"
    artifact_model = unpacked / "models" / "COLD_0_BENIGN.json"
    artifact_model.parent.mkdir(parents=True)
    artifact_model.write_text(json.dumps({"name": "COLD_0|BENIGN"}), encoding="utf-8")
    model_store = ModelStore(tmp_path / "store")
    row = _learner_row(tmp_path / "old.json")
    snapshot = {
        "snapshot_id": "source-session:COLD_0|BENIGN:1:old",
        "session_id": "source-session",
        "learner_name": "COLD_0|BENIGN",
        "snapshot_version": 1,
        "profile_json": row["profile_json"],
    }
    entries = [
        {
            "learner_name": "COLD_0|BENIGN",
            "artifact_path": "models/COLD_0_BENIGN.json",
            "sha256": __import__("hashlib").sha256(artifact_model.read_bytes()).hexdigest(),
        }
    ]
    manifest = {"artifact_version": 1, "session_id": "source-session", "learners": [{"learner_name": "COLD_0|BENIGN", "model": entries[0]}]}

    model_map = install_artifact_models(
        model_store=model_store,
        unpacked_root=unpacked,
        manifest=manifest,
        target_session_id="target-session",
    )
    snapshot_map = build_snapshot_id_map([snapshot], target_session_id="target-session")
    remapped = remap_learner_row(
        row,
        target_session_id="target-session",
        model_path_map=model_map,
        snapshot_id_map=snapshot_map,
    )
    remapped_snapshot = remap_snapshot_row(
        snapshot,
        target_session_id="target-session",
        model_path_map=model_map,
        snapshot_id_map=snapshot_map,
    )

    assert Path(model_map["COLD_0|BENIGN"]).exists()
    assert remapped["session_id"] == "target-session"
    assert remapped["current_snapshot_id"] == remapped_snapshot["snapshot_id"]
    assert remapped["profile_json"]["model_ref"]["path"] == model_map["COLD_0|BENIGN"]
    assert remapped_snapshot["profile_json"]["model_ref"]["path"] == model_map["COLD_0|BENIGN"]


def test_remap_runtime_marks_imported_session_finalized() -> None:
    runtime = {"session_id": "source-session", "runtime_mode": "inference", "cold_start_finalized": False}

    remapped = remap_runtime(runtime, target_session_id="target-session")

    assert remapped["session_id"] == "target-session"
    assert remapped["runtime_mode"] == "cold_start"
    assert remapped["cold_start_finalized"] is True
