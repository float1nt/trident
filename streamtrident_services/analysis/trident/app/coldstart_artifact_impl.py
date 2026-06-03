from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import tarfile
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import TridentConfig, load_config
from .logging_utils import configure_logging, emit_event
from .persistence.learner_repository import LearnerRepository
from .persistence.session_runtime_repository import SessionRuntimeRepository
from .persistence.snapshot_repository import SnapshotRepository
from .runtime.model_store import ModelStore


ARTIFACT_VERSION = 1
MODEL_FORMAT = "trident_learner_json_v1"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export or import finalized Trident cold-start artifacts")
    parser.add_argument("command", choices=["export", "import"])
    parser.add_argument("--config", default="config/trident.yaml")
    parser.add_argument("--session-id", default="", help="Source session for export, or target session for import")
    parser.add_argument("--target-session-id", default="", help="Optional import session remap")
    parser.add_argument("--artifact", default="", help="Artifact path for import")
    parser.add_argument("--output", default="", help="Artifact path for export")
    parser.add_argument("--skip-snapshots", action="store_true", help="Do not export/import pg_learner_snapshot rows")
    return parser.parse_args()


def main() -> int:
    log_dir = Path(os.getenv("TRIDENT_LOG_DIR", "/var/log/trident"))
    log_file = os.getenv("TRIDENT_LOG_FILE", "coldstart-artifact.log")
    configure_logging(service_name="trident-coldstart-artifact", log_path=log_dir / log_file)
    args = parse_args()
    cfg = load_config(args.config)
    if args.command == "export":
        output = Path(args.output or f"coldstart-{args.session_id or cfg.session_id}.tar.gz")
        summary = export_coldstart_artifact(
            cfg,
            output,
            session_id=args.session_id or cfg.session_id,
            include_snapshots=not args.skip_snapshots,
        )
    else:
        artifact_arg = args.artifact or args.output
        if not artifact_arg:
            raise ValueError("import requires --artifact")
        artifact = Path(artifact_arg)
        summary = import_coldstart_artifact(
            cfg,
            artifact,
            target_session_id=args.target_session_id or args.session_id or "",
            include_snapshots=not args.skip_snapshots,
        )
    emit_event("coldstart_artifact_finished", **summary)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def export_coldstart_artifact(
    cfg: TridentConfig,
    output: Path,
    *,
    session_id: str,
    include_snapshots: bool = True,
) -> dict[str, Any]:
    learners = LearnerRepository(cfg.postgres_dsn)
    runtime_repo = SessionRuntimeRepository(cfg.postgres_dsn)
    snapshot_repo = SnapshotRepository(cfg.postgres_dsn)
    runtime = runtime_repo.get(session_id=session_id)
    if not runtime or not bool(runtime.get("cold_start_finalized")):
        raise RuntimeError(f"session is not finalized for cold-start export: {session_id}")

    learner_rows = [
        row
        for row in learners.list_learners(session_id=session_id)
        if str(row.get("learner_name") or "").startswith("COLD_")
    ]
    if not learner_rows:
        raise RuntimeError(f"no COLD_* learners found for session: {session_id}")

    model_entries = collect_model_entries(learner_rows)
    if not model_entries:
        raise RuntimeError(f"no model_ref files found for cold-start learners: {session_id}")
    for entry in model_entries:
        if not Path(entry["source_path"]).exists():
            raise FileNotFoundError(f"model_ref path not found: {entry['source_path']}")

    snapshots = []
    if include_snapshots:
        snapshots = snapshot_repo.list_snapshots(
            session_id=session_id,
            learner_names=[str(row.get("learner_name") or "") for row in learner_rows],
        )

    manifest = build_manifest(
        cfg=cfg,
        session_id=session_id,
        learner_rows=learner_rows,
        model_entries=model_entries,
        snapshot_count=len(snapshots),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w:gz") as tar:
        _add_json(tar, "manifest.json", manifest)
        _add_json(tar, "postgres/pg_session_runtime.json", _jsonable(runtime))
        _add_json(tar, "postgres/pg_learner.json", _jsonable(learner_rows))
        _add_json(tar, "postgres/pg_learner_snapshot.json", _jsonable(snapshots))
        _add_json(
            tar,
            "config/trident-model-profile.json",
            {
                "session_id": session_id,
                "feature_profile": cfg.feature_profile,
                "algorithm_backend": cfg.algorithm_backend,
                "model_store_dir": cfg.model_store_dir,
            },
        )
        for entry in model_entries:
            tar.add(entry["source_path"], arcname=entry["artifact_path"], recursive=False)

    return {
        "command": "export",
        "artifact": str(output),
        "session_id": session_id,
        "learner_count": len(learner_rows),
        "snapshot_count": len(snapshots),
        "model_count": len(model_entries),
    }


def import_coldstart_artifact(
    cfg: TridentConfig,
    artifact: Path,
    *,
    target_session_id: str = "",
    include_snapshots: bool = True,
) -> dict[str, Any]:
    if not artifact.exists():
        raise FileNotFoundError(f"cold-start artifact not found: {artifact}")
    learners = LearnerRepository(cfg.postgres_dsn)
    runtime_repo = SessionRuntimeRepository(cfg.postgres_dsn)
    snapshot_repo = SnapshotRepository(cfg.postgres_dsn)
    model_store = ModelStore(cfg.model_store_dir)

    with tempfile.TemporaryDirectory(prefix="trident-coldstart-import-") as tmp_name:
        tmp_dir = Path(tmp_name)
        with tarfile.open(artifact, "r:gz") as tar:
            _safe_extract(tar, tmp_dir)
        manifest = _read_json(tmp_dir / "manifest.json")
        if int(manifest.get("artifact_version", 0)) != ARTIFACT_VERSION:
            raise RuntimeError(f"unsupported cold-start artifact version: {manifest.get('artifact_version')}")
        source_session_id = str(manifest.get("session_id") or "")
        session_id = target_session_id or source_session_id
        if not session_id:
            raise RuntimeError("artifact is missing session_id")
        model_path_map = install_artifact_models(
            model_store=model_store,
            unpacked_root=tmp_dir,
            manifest=manifest,
            target_session_id=session_id,
        )
        runtime = _read_json(tmp_dir / "postgres/pg_session_runtime.json")
        learner_rows = _read_json(tmp_dir / "postgres/pg_learner.json")
        snapshot_rows = _read_json(tmp_dir / "postgres/pg_learner_snapshot.json")
        if not isinstance(learner_rows, list):
            raise RuntimeError("artifact pg_learner.json must contain a list")
        if not bool(runtime.get("cold_start_finalized")):
            raise RuntimeError("artifact runtime is not cold_start_finalized")

        snapshot_id_map = build_snapshot_id_map(snapshot_rows, target_session_id=session_id)
        runtime = remap_runtime(runtime, target_session_id=session_id)
        runtime_repo.upsert_runtime(runtime)
        imported_learners = []
        for row in learner_rows:
            if not isinstance(row, dict):
                continue
            row = remap_learner_row(
                row,
                target_session_id=session_id,
                model_path_map=model_path_map,
                snapshot_id_map=snapshot_id_map,
            )
            learners.upsert_current_learner(row)
            imported_learners.append(row)
        imported_snapshots = 0
        if include_snapshots and isinstance(snapshot_rows, list):
            for row in snapshot_rows:
                if not isinstance(row, dict):
                    continue
                row = remap_snapshot_row(
                    row,
                    target_session_id=session_id,
                    model_path_map=model_path_map,
                    snapshot_id_map=snapshot_id_map,
                )
                snapshot_repo.insert_snapshot(row)
                imported_snapshots += 1

    return {
        "command": "import",
        "artifact": str(artifact),
        "source_session_id": source_session_id,
        "session_id": session_id,
        "learner_count": len(imported_learners),
        "snapshot_count": imported_snapshots,
        "model_count": len(model_path_map),
    }


def build_manifest(
    *,
    cfg: TridentConfig,
    session_id: str,
    learner_rows: list[dict[str, Any]],
    model_entries: list[dict[str, str]],
    snapshot_count: int,
) -> dict[str, Any]:
    model_by_learner = {entry["learner_name"]: entry for entry in model_entries}
    return {
        "artifact_version": ARTIFACT_VERSION,
        "session_id": session_id,
        "feature_profile": cfg.feature_profile,
        "algorithm_backend": cfg.algorithm_backend,
        "model_format": MODEL_FORMAT,
        "snapshot_count": int(snapshot_count),
        "learners": [
            {
                "learner_name": str(row.get("learner_name") or ""),
                "flow_count": int(row.get("flow_count") or 0),
                "current_snapshot_id": str(row.get("current_snapshot_id") or ""),
                "current_snapshot_version": int(row.get("current_snapshot_version") or 0),
                "model": {
                    "artifact_path": model_by_learner[str(row.get("learner_name") or "")]["artifact_path"],
                    "sha256": model_by_learner[str(row.get("learner_name") or "")]["sha256"],
                },
            }
            for row in learner_rows
        ],
    }


def collect_model_entries(learner_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in learner_rows:
        learner_name = str(row.get("learner_name") or "")
        profile = row.get("profile_json") if isinstance(row.get("profile_json"), dict) else {}
        model_ref = profile.get("model_ref") if isinstance(profile, dict) else None
        if not isinstance(model_ref, dict) or model_ref.get("format") != MODEL_FORMAT:
            continue
        source_path = str(model_ref.get("path") or "")
        if not source_path or source_path in seen:
            continue
        seen.add(source_path)
        artifact_path = f"models/{_safe_path_component(learner_name)}.json"
        sha = _sha256_file(Path(source_path)) if Path(source_path).exists() else ""
        entries.append(
            {
                "learner_name": learner_name,
                "source_path": source_path,
                "artifact_path": artifact_path,
                "sha256": sha,
            }
        )
    return entries


def install_artifact_models(
    *,
    model_store: ModelStore,
    unpacked_root: Path,
    manifest: dict[str, Any],
    target_session_id: str,
) -> dict[str, str]:
    dest_dir = model_store.root / _safe_path_component(target_session_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    model_path_map: dict[str, str] = {}
    for learner in manifest.get("learners", []):
        if not isinstance(learner, dict):
            continue
        learner_name = str(learner.get("learner_name") or "")
        model = learner.get("model") if isinstance(learner.get("model"), dict) else {}
        artifact_path = str(model.get("artifact_path") or "")
        expected_sha = str(model.get("sha256") or "")
        source = unpacked_root / artifact_path
        if not source.exists():
            raise FileNotFoundError(f"artifact model file missing: {artifact_path}")
        actual_sha = _sha256_file(source)
        if expected_sha and actual_sha != expected_sha:
            raise RuntimeError(f"model sha256 mismatch for {learner_name}: {artifact_path}")
        dest = dest_dir / f"{_safe_path_component(learner_name)}.json"
        dest.write_bytes(source.read_bytes())
        model_path_map[learner_name] = str(dest)
    return model_path_map


def remap_runtime(row: dict[str, Any], *, target_session_id: str) -> dict[str, Any]:
    out = dict(row)
    out["session_id"] = target_session_id
    out["runtime_mode"] = "cold_start"
    out["cold_start_finalized"] = True
    return out


def remap_learner_row(
    row: dict[str, Any],
    *,
    target_session_id: str,
    model_path_map: dict[str, str],
    snapshot_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    out = dict(row)
    out["session_id"] = target_session_id
    if snapshot_id_map and out.get("current_snapshot_id") in snapshot_id_map:
        out["current_snapshot_id"] = snapshot_id_map[str(out["current_snapshot_id"])]
    profile = dict(out.get("profile_json") or {})
    learner_name = str(out.get("learner_name") or "")
    if learner_name in model_path_map:
        model_ref = dict(profile.get("model_ref") or {})
        model_ref["type"] = "file"
        model_ref["path"] = model_path_map[learner_name]
        model_ref["format"] = MODEL_FORMAT
        profile["model_ref"] = model_ref
    out["profile_json"] = profile
    return out


def remap_snapshot_row(
    row: dict[str, Any],
    *,
    target_session_id: str,
    model_path_map: dict[str, str],
    snapshot_id_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    out = remap_learner_row(
        row,
        target_session_id=target_session_id,
        model_path_map=model_path_map,
        snapshot_id_map=snapshot_id_map,
    )
    snapshot_id = str(out.get("snapshot_id") or "")
    if snapshot_id and snapshot_id_map:
        out["snapshot_id"] = snapshot_id_map.get(snapshot_id, snapshot_id)
    return out


def build_snapshot_id_map(snapshot_rows: Any, *, target_session_id: str) -> dict[str, str]:
    if not isinstance(snapshot_rows, list):
        return {}
    out: dict[str, str] = {}
    for row in snapshot_rows:
        if not isinstance(row, dict):
            continue
        snapshot_id = str(row.get("snapshot_id") or "")
        if snapshot_id:
            learner_name = str(row.get("learner_name") or "")
            version = int(row.get("snapshot_version") or 0)
            out[snapshot_id] = _snapshot_id(target_session_id, learner_name, version)
    return out


def _add_json(tar: tarfile.TarFile, name: str, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, fileobj=io.BytesIO(data))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _safe_extract(tar: tarfile.TarFile, target: Path) -> None:
    target_resolved = target.resolve()
    for member in tar.getmembers():
        if member.issym() or member.islnk():
            raise RuntimeError(f"unsafe artifact link member: {member.name}")
        member_path = (target / member.name).resolve()
        try:
            member_path.relative_to(target_resolved)
        except ValueError as exc:
            raise RuntimeError(f"unsafe artifact member path: {member.name}") from exc
    tar.extractall(target)


def _safe_path_component(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(value))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_id(session_id: str, learner_name: str, version: int) -> str:
    digest = hashlib.sha256(f"{session_id}|{learner_name}|{version}".encode("utf-8")).hexdigest()[:16]
    return f"{session_id}:{learner_name}:{version}:{digest}"

