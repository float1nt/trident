from __future__ import annotations

import argparse
import json
from typing import Any

from .config import load_config
from .flow_loader import FlowRecord
from .logging_utils import configure_logging, emit_event
from .persistence.ch_flow_repository import ChFlowRepository, _parse_json, _quote
from .persistence.learner_repository import LearnerRepository
from .runtime.quality import build_learner_audit, resolve_session_baseline_learner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild learner rule_json and risk fields from assigned flows")
    parser.add_argument("--config", default="config/trident.yaml")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--learner-name", default="", help="Optional single learner to rebuild")
    parser.add_argument("--sample-limit", type=int, default=10000)
    return parser.parse_args()


def _flow_record_from_row(row: dict[str, Any]) -> FlowRecord:
    return FlowRecord(
        session_id=str(row.get("session_id") or ""),
        flow_uid=str(row.get("flow_uid") or ""),
        event_time=str(row.get("event_time") or ""),
        src_ip=str(row.get("src_ip") or ""),
        dst_ip=str(row.get("dst_ip") or ""),
        src_port=int(row.get("src_port") or 0),
        dst_port=int(row.get("dst_port") or 0),
        protocol=int(row.get("protocol") or 0),
        app_proto=str(row.get("app_proto") or ""),
        total_bytes=int(row.get("total_bytes") or 0),
        feature_profile=str(row.get("feature_profile") or ""),
        features_json=str(row.get("features_json") or "{}"),
        mq_type=str(row.get("mq_type") or ""),
        mq_topic=str(row.get("mq_topic") or ""),
        mq_message_id=str(row.get("mq_message_id") or ""),
        source_flow_id=str(row.get("source_flow_id") or ""),
        raw_event=str(row.get("raw_event") or ""),
        record_version=int(row.get("record_version") or 0),
        record_stage=str(row.get("record_stage") or "assigned"),
        window_index=int(row.get("window_index") or 0),
    )


def _fetch_assigned_records(
    flows: ChFlowRepository,
    *,
    session_id: str,
    learner_name: str,
    sample_limit: int,
) -> list[FlowRecord]:
    capped = max(1, min(int(sample_limit), 10000))
    sql = f"""
SELECT
    session_id,
    flow_uid,
    event_time,
    src_ip,
    dst_ip,
    src_port,
    dst_port,
    protocol,
    app_proto,
    total_bytes,
    feature_profile,
    features_json,
    mq_type,
    mq_topic,
    mq_message_id,
    source_flow_id,
    raw_event,
    record_version,
    record_stage,
    window_index
FROM ch_flow FINAL
WHERE session_id = {_quote(session_id)}
  AND assigned_learner = {_quote(learner_name)}
  AND is_unknown = 0
ORDER BY event_time DESC, flow_uid ASC
LIMIT {capped}
FORMAT JSONEachRow
"""
    text = flows.client.execute(sql)
    rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
    return [_flow_record_from_row(row) for row in rows]


def _threshold_for_learner(learner: dict[str, Any]) -> float:
    profile = learner.get("profile_json")
    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            profile = {}
    if isinstance(profile, dict):
        try:
            return float(profile.get("threshold") or 0.0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _fetch_learner_flow_counts(
    flows: ChFlowRepository,
    *,
    session_id: str,
) -> dict[str, int]:
    sql = f"""
SELECT assigned_learner, count() AS flow_count
FROM ch_flow FINAL
WHERE session_id = {_quote(session_id)}
  AND assigned_learner != ''
GROUP BY assigned_learner
FORMAT JSONEachRow
"""
    text = flows.client.execute(sql)
    rows = [_parse_json(line) for line in text.splitlines() if line.strip()]
    counts: dict[str, int] = {}
    for row in rows:
        name = str(row.get("assigned_learner") or "").strip()
        if not name:
            continue
        counts[name] = int(row.get("flow_count") or 0)
    return counts


def rebuild_learner_rules(
    *,
    cfg,
    session_id: str,
    learner_name: str = "",
    sample_limit: int = 10000,
) -> list[dict[str, Any]]:
    learner_repo = LearnerRepository(cfg.postgres_dsn)
    flows = ChFlowRepository(cfg.clickhouse_dsn)
    learners = learner_repo.list_learners(session_id=session_id)
    if learner_name:
        learners = [row for row in learners if str(row.get("learner_name") or "") == learner_name]
    flow_counts = _fetch_learner_flow_counts(flows, session_id=session_id)
    session_baseline_learner = resolve_session_baseline_learner(learners, flow_counts=flow_counts)
    results: list[dict[str, Any]] = []
    for learner in learners:
        name = str(learner.get("learner_name") or "")
        if not name:
            continue
        records = _fetch_assigned_records(
            flows,
            session_id=session_id,
            learner_name=name,
            sample_limit=sample_limit,
        )
        flow_count = int(learner.get("flow_count") or len(records))
        threshold = _threshold_for_learner(learner)
        metrics, topology_json, rule_json, risk_score, risk_band, risk_reason = build_learner_audit(
            learner_name=name,
            records=records,
            flow_count=flow_count,
            unknown_buffer_size=0,
            threshold=threshold,
            session_baseline_learner=session_baseline_learner,
        )
        metric_json = dict(learner.get("metric_json") or {})
        if isinstance(metric_json, str):
            try:
                metric_json = json.loads(metric_json)
            except json.JSONDecodeError:
                metric_json = {}
        metric_json.update(metrics)
        metric_json["flow_count"] = flow_count
        metric_json["last_seen_window_index"] = int(learner.get("last_seen_window_index") or 0)
        metric_json["unknown_buffer_size"] = 0
        updated = dict(learner)
        updated.update(
            {
                "metric_json": metric_json,
                "topology_json": topology_json,
                "rule_json": rule_json,
                "risk_score": risk_score,
                "risk_band": risk_band,
                "risk_reason": risk_reason,
            }
        )
        learner_repo.upsert_current_learner(updated)
        primary_attack = ""
        attack_types = rule_json.get("attack_types") if isinstance(rule_json, dict) else None
        if isinstance(attack_types, list) and attack_types:
            primary_attack = str(attack_types[0].get("attack_type") or "")
        item = {
            "learner_name": name,
            "sample_count": len(records),
            "primary_attack_type": primary_attack,
            "risk_score": risk_score,
            "risk_band": risk_band,
        }
        results.append(item)
        emit_event("rebuild_learner_rules_item", **item)
    return results


def main() -> int:
    args = parse_args()
    configure_logging(service_name="trident-rebuild-rules")
    cfg = load_config(args.config)
    session_id = str(args.session_id or cfg.session_id)
    emit_event(
        "rebuild_learner_rules_started",
        session_id=session_id,
        learner_name=args.learner_name or None,
        sample_limit=args.sample_limit,
    )
    results = rebuild_learner_rules(
        cfg=cfg,
        session_id=session_id,
        learner_name=str(args.learner_name or ""),
        sample_limit=args.sample_limit,
    )
    emit_event("rebuild_learner_rules_finished", rebuilt_count=len(results), results=results)
    for item in results:
        print(
            f"{item['learner_name']}\t{item['primary_attack_type']}\t"
            f"{item['risk_band']}\t{item['risk_score']:.3f}\t{item['sample_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
