from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .persistence.ch_flow_repository import ChFlowRepository
from .persistence.learner_repository import LearnerRepository
from .redis_consumer import RedisStreamConsumer


RISK_BANDS = {"medium", "high"}


class PageQueryService:
    def __init__(
        self,
        *,
        session_id: str,
        flows: ChFlowRepository,
        learners: LearnerRepository,
        redis: RedisStreamConsumer | None = None,
    ) -> None:
        self.session_id = session_id
        self.flows = flows
        self.learners = learners
        self.redis = redis

    def dashboard_overview(
        self,
        *,
        session_id: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        learner_rows = self.learners.list_learners(session_id=sid)
        risk_names = _risk_learner_names(learner_rows)
        summary = self.flows.dashboard_summary(
            session_id=sid,
            risk_learners=risk_names,
            time_from=time_from,
            time_to=time_to,
        )
        protocol_rows = self.flows.protocol_distribution(
            session_id=sid,
            time_from=time_from,
            time_to=time_to,
            limit=100,
        )
        protocol_distribution = _compact_protocol_distribution(protocol_rows)

        return {
            "metrics": {
                "total_flows": int(summary.get("total_flows") or 0),
                "protocol_count": int(summary.get("protocol_count") or 0),
                "risk_learner_count": len(risk_names),
                "risk_ip_count": int(summary.get("risk_ip_count") or 0),
            },
            "traffic_distribution": [
                {"name": "正常流量", "value": int(summary.get("normal_flows") or 0)},
                {"name": "疑似异常流量", "value": int(summary.get("risk_flows") or 0)},
            ],
            "protocol_distribution": protocol_distribution,
            "runtime": {
                "session_id": sid,
                "current_window_index": int(summary.get("current_window_index") or 0),
                "redis_pending": _safe_int(lambda: self.redis.pending_count()) if self.redis else 0,
                "consumed_flow_count": int(summary.get("total_flows") or 0),
            },
        }

    def overview_metrics(self, *, time_range: str = "24h") -> dict[str, Any]:
        time_from = _time_range_start(time_range)
        overview = self.dashboard_overview(time_from=time_from)
        metrics = overview["metrics"]
        return {
            "totalTraffic": int(metrics["total_flows"]),
            "protocolCount": int(metrics["protocol_count"]),
            "riskTypeCount": int(metrics["risk_learner_count"]),
            "suspiciousIpCount": int(metrics["risk_ip_count"]),
        }

    def overview_distributions(self, *, time_range: str = "24h") -> dict[str, Any]:
        time_from = _time_range_start(time_range)
        overview = self.dashboard_overview(time_from=time_from)
        return {
            "traffic": overview["traffic_distribution"],
            "protocol": overview["protocol_distribution"],
        }

    def risk_events(
        self,
        *,
        session_id: str | None = None,
        name: str | None = None,
        risk_band: str | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        rows = self.learners.list_learners(session_id=sid)
        items = [
            _learner_event_item(index, row)
            for index, row in enumerate(_filter_learner_rows(rows, name=name, risk_band=risk_band, time_from=time_from, time_to=time_to), start=1)
        ]
        top_ips = self.flows.top_subject_ips_by_learner(
            session_id=sid,
            learner_names=[str(item["learner_name"]) for item in items],
            limit_per_learner=5,
        )
        for item in items:
            item["subject_ips"] = top_ips.get(str(item["learner_name"]), [])
        return {"items": items, "total": len(items)}

    def risk_ip_view(
        self,
        *,
        session_id: str | None = None,
        limit: int = 10,
        offset: int = 0,
        name: str | None = None,
        subject_ip: str | None = None,
        trigger_time: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        learner_rows = self.learners.list_learners(session_id=sid)
        learner_by_name = {str(row.get("learner_name") or ""): row for row in learner_rows}
        risk_names = _risk_learner_names(learner_rows)
        result = self.flows.risk_ip_view(
            session_id=sid,
            risk_learners=risk_names,
            limit=limit,
            offset=offset,
            learner_name_like=name,
            subject_ip_like=subject_ip,
            trigger_time_prefix=trigger_time,
        )
        items = [_risk_ip_item(row, learner_by_name.get(str(row.get("assigned_learner") or ""))) for row in result["items"]]
        return {"items": items, "total": int(result["total"])}

    def dashboard_topology(
        self,
        *,
        session_id: str | None = None,
        top_n: int = 50,
        time_from: str | None = None,
        time_to: str | None = None,
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        learner_rows = self.learners.list_learners(session_id=sid)
        risk_names = _risk_learner_names(learner_rows)
        views = {
            "__combined__": _topology_view(
                label="总流量",
                host=self.flows.topology_graph(
                    session_id=sid,
                    node_mode="host",
                    risk_learners=risk_names,
                    traffic_kind="combined",
                    time_from=time_from,
                    time_to=time_to,
                    top_n=top_n,
                ),
                endpoint=self.flows.topology_graph(
                    session_id=sid,
                    node_mode="endpoint",
                    risk_learners=risk_names,
                    traffic_kind="combined",
                    time_from=time_from,
                    time_to=time_to,
                    top_n=top_n,
                ),
                is_benign=None,
            ),
            "__benign__": _topology_view(
                label="良性流量",
                host=self.flows.topology_graph(
                    session_id=sid,
                    node_mode="host",
                    risk_learners=risk_names,
                    traffic_kind="benign",
                    time_from=time_from,
                    time_to=time_to,
                    top_n=top_n,
                ),
                endpoint=self.flows.topology_graph(
                    session_id=sid,
                    node_mode="endpoint",
                    risk_learners=risk_names,
                    traffic_kind="benign",
                    time_from=time_from,
                    time_to=time_to,
                    top_n=top_n,
                ),
                is_benign=True,
            ),
            "__attack__": _topology_view(
                label="攻击流量",
                host=self.flows.topology_graph(
                    session_id=sid,
                    node_mode="host",
                    risk_learners=risk_names,
                    traffic_kind="attack",
                    time_from=time_from,
                    time_to=time_to,
                    top_n=top_n,
                ),
                endpoint=self.flows.topology_graph(
                    session_id=sid,
                    node_mode="endpoint",
                    risk_learners=risk_names,
                    traffic_kind="attack",
                    time_from=time_from,
                    time_to=time_to,
                    top_n=top_n,
                ),
                is_benign=False,
            ),
        }
        return {
            "version": 1,
            "total_flows": int(views["__combined__"]["host"].get("flow_count") or 0),
            "labels": ["__combined__", "__benign__", "__attack__"],
            "default_label": "__combined__",
            "default_node_mode": "host",
            "aggregate_views": ["__combined__", "__benign__", "__attack__"],
            "views": views,
        }

    def learner_topology(
        self,
        *,
        learner_name: str,
        session_id: str | None = None,
        subject_ip: str | None = None,
        top_n: int = 50,
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        learner = self.learners.get_learner(session_id=sid, learner_name=learner_name) or {}
        event = _learner_event_item(1, learner) if learner else _empty_event_item(learner_name)
        view = {
            "learner": learner_name,
            "risk_id": event["risk_id"],
            "risk_name": event["risk_name"],
            "risk_description": event["risk_description"],
            "trigger_time": event["trigger_time"],
            "attack_ratio": event["attack_ratio"],
            "dominant_label": event["dominant_label"],
            "dominant_ratio": event["risk_score"],
            "is_benign": event["risk_band"] == "low",
            "host": self.flows.topology_graph(
                session_id=sid,
                node_mode="host",
                learner_name=learner_name,
                subject_ip=subject_ip,
                top_n=top_n,
            ),
            "endpoint": self.flows.topology_graph(
                session_id=sid,
                node_mode="endpoint",
                learner_name=learner_name,
                subject_ip=subject_ip,
                top_n=top_n,
            ),
        }
        return {
            "version": 1,
            "learners": [learner_name],
            "default_learner": learner_name,
            "views": {learner_name: view},
        }

    def risk_list(
        self,
        *,
        limit: int = 10,
        offset: int = 0,
        name: str | None = None,
        subject_ip: str | None = None,
    ) -> dict[str, Any]:
        sid = self.session_id
        learner_rows = self.learners.list_learners(session_id=sid)
        risk_names = _risk_learner_names(learner_rows)
        raw = self.flows.risk_ip_view(
            session_id=sid,
            risk_learners=risk_names,
            limit=10000,
            offset=0,
            learner_name_like=name,
            subject_ip_like=subject_ip,
        )
        grouped: dict[str, dict[str, int]] = {}
        for row in raw["items"]:
            ip = str(row.get("subject_ip") or "")
            learner = str(row.get("assigned_learner") or "") or "UNKNOWN"
            if not ip:
                continue
            grouped.setdefault(ip, {})
            grouped[ip][learner] = grouped[ip].get(learner, 0) + int(row.get("flow_count") or 0)

        ip_rows: list[dict[str, Any]] = []
        for seq, (ip, name_counts) in enumerate(
            sorted(grouped.items(), key=lambda item: (-sum(item[1].values()), item[0])),
            start=1,
        ):
            risks = [
                {"name": risk_name, "triggerCount": count}
                for risk_name, count in sorted(name_counts.items(), key=lambda item: (-item[1], item[0]))
            ]
            ip_rows.append(
                {
                    "id": seq,
                    "subjectIp": ip,
                    "riskCount": len(risks),
                    "risks": risks,
                }
            )
        total = len(ip_rows)
        return {"total": total, "risks": ip_rows[offset : offset + limit]}

    def risk_events_topology(
        self,
        *,
        name: str | None = None,
        trigger_start: str | None = None,
        trigger_end: str | None = None,
        top_n: int = 50,
    ) -> dict[str, Any]:
        sid = self.session_id
        rows = _filter_learner_rows(
            self.learners.list_learners(session_id=sid),
            name=name,
            risk_band=None,
            time_from=trigger_start,
            time_to=trigger_end,
        )
        views: dict[str, Any] = {}
        learners: list[str] = []
        for row in rows:
            learner_name = str(row.get("learner_name") or "")
            if not learner_name:
                continue
            topology = self.learner_topology(learner_name=learner_name, top_n=top_n)
            view = topology["views"][learner_name]
            learners.append(learner_name)
            views[learner_name] = view
        return {
            "version": 1,
            "learners": learners,
            "default_learner": learners[0] if learners else "",
            "views": views,
        }

    def risk_by_id(self, *, risk_id: int) -> dict[str, Any]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        item = _risk_item_from_learner(learner, subject_ip=_first_subject_ip(self, learner))
        item["riskIpCount"] = len(self.risk_ips(risk_id=risk_id, limit=1000))
        return item

    def risk_network_topology(self, *, risk_id: int, top_n: int = 50) -> dict[str, Any]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        learner_name = str(learner.get("learner_name") or "")
        if not learner_name:
            return _empty_dataset_topology()
        topology = self.learner_topology(learner_name=learner_name, top_n=top_n)
        view = topology["views"][learner_name]
        return {
            "version": 1,
            "total_flows": int(view["host"].get("flow_count") or 0),
            "labels": ["__combined__"],
            "default_label": "__combined__",
            "default_node_mode": "host",
            "aggregate_views": ["__combined__"],
            "views": {
                "__combined__": {
                    "label": "__combined__",
                    "view_kind": "aggregate",
                    "is_benign": None,
                    "host": view["host"],
                    "endpoint": view["endpoint"],
                }
            },
        }

    def risk_ips(self, *, risk_id: int, limit: int = 100) -> list[dict[str, Any]]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        learner_name = str(learner.get("learner_name") or "")
        if not learner_name:
            return []
        return self.flows.top_subject_ip_counts_by_learner(session_id=self.session_id, learner_name=learner_name, limit=limit)

    def risk_traffic_logs(self, *, risk_id: int, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        learner_name = str(learner.get("learner_name") or "")
        if not learner_name:
            return []
        flows = self.flows.list_flows(session_id=self.session_id, learner_name=learner_name, limit=limit, offset=offset)
        return [_traffic_log_item(row) for row in flows["items"]]

    def risk_protocol_distribution(self, *, risk_id: int) -> list[dict[str, Any]]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        learner_name = str(learner.get("learner_name") or "")
        if not learner_name:
            return []
        return _compact_protocol_distribution(
            self.flows.protocol_distribution(session_id=self.session_id, learner_name=learner_name)
        )

    def ip_summary(self, *, ip: str) -> dict[str, Any]:
        events = self.ip_events(ip=ip)
        latest = events[0]["triggerTime"] if events else "-"
        features = "、".join(sorted({item["features"] for item in events if item.get("features")})[:3])
        return {
            "ip": ip,
            "description": f"{ip} 作为风险主体共关联 {len(events)} 次风险事件。",
            "features": features or "暂无风险特征",
            "riskEventCount": len(events),
            "latestTriggerTime": latest,
            "isInternal": _is_internal_ip(ip),
        }

    def ip_events(self, *, ip: str, limit: int = 100) -> list[dict[str, Any]]:
        data = self.risk_ip_view(limit=limit, offset=0, subject_ip=ip)
        return [
            {
                "id": item["id"],
                "name": item["name"],
                "triggerTime": item["triggerTime"],
                "description": item["description"],
                "features": item["features"],
            }
            for item in data["items"]
        ]

    def ip_events_topology(self, *, ip: str, top_n: int = 50, limit: int = 6) -> dict[str, Any]:
        data = self.risk_ip_view(limit=limit, offset=0, subject_ip=ip)
        learners: list[str] = []
        views: dict[str, Any] = {}
        for item in data["items"]:
            learner_name = str(item["learnerName"] or "")
            if not learner_name:
                continue
            key = f"ip_risk_{item['id']}"
            topology = self.learner_topology(learner_name=learner_name, subject_ip=ip, top_n=top_n)
            view = topology["views"][learner_name]
            view["learner"] = key
            learners.append(key)
            views[key] = view
        return {
            "version": 1,
            "learners": learners,
            "default_learner": learners[0] if learners else "",
            "views": views,
        }

    def ip_traffic_logs(self, *, ip: str, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        flows = self.flows.list_flows(session_id=self.session_id, src_ip=ip, limit=limit, offset=offset)
        return [_traffic_log_item(row, subject_ip=ip) for row in flows["items"]]

    def learner_detail(
        self,
        *,
        learner_name: str,
        session_id: str | None = None,
        flow_limit: int = 100,
        flow_offset: int = 0,
        include_topology: bool = True,
        top_n: int = 50,
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        learner = self.learners.get_learner(session_id=sid, learner_name=learner_name) or {}
        flows = self.flows.list_flows(
            session_id=sid,
            learner_name=learner_name,
            limit=flow_limit,
            offset=flow_offset,
        )
        top_ips = self.flows.top_subject_ips_by_learner(
            session_id=sid,
            learner_names=[learner_name],
            limit_per_learner=10,
        )
        return {
            "learner": learner,
            "top_subject_ips": top_ips.get(learner_name, []),
            "recent_flows": flows,
            "topology": self.learner_topology(session_id=sid, learner_name=learner_name, top_n=top_n) if include_topology else None,
        }


def _risk_learner_names(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for row in rows:
        band = str(row.get("risk_band") or "").lower()
        name = str(row.get("learner_name") or "")
        if name and band in RISK_BANDS:
            names.append(name)
    return names


def _filter_learner_rows(
    rows: list[dict[str, Any]],
    *,
    name: str | None,
    risk_band: str | None,
    time_from: str | None,
    time_to: str | None,
) -> list[dict[str, Any]]:
    filtered = []
    name_text = (name or "").strip().lower()
    band_text = (risk_band or "").strip().lower()
    for row in rows:
        row_band = str(row.get("risk_band") or "").lower()
        if band_text:
            if row_band != band_text:
                continue
        elif row_band not in RISK_BANDS:
            continue
        learner_name = str(row.get("learner_name") or "").lower()
        if name_text and name_text not in learner_name:
            continue
        seen = row.get("last_seen_at")
        seen_text = _format_time(seen)
        if time_from and seen_text and seen_text < time_from:
            continue
        if time_to and seen_text and seen_text > time_to:
            continue
        filtered.append(row)
    return sorted(
        filtered,
        key=lambda row: (
            -_float(row.get("risk_score")),
            _format_time(row.get("last_seen_at")),
            str(row.get("learner_name") or ""),
        ),
    )


def _learner_event_item(index: int, row: dict[str, Any]) -> dict[str, Any]:
    learner_name = str(row.get("learner_name") or "")
    risk_score = _float(row.get("risk_score"))
    risk_band = str(row.get("risk_band") or "low").lower()
    return {
        "learner_name": learner_name,
        "risk_id": int(row.get("id") or index),
        "risk_name": learner_name,
        "risk_description": str(row.get("risk_reason") or "暂无风险说明"),
        "trigger_time": _format_time(row.get("last_seen_at")) or "-",
        "attack_ratio": risk_score,
        "dominant_label": risk_band,
        "flow_count": int(row.get("flow_count") or 0),
        "risk_score": risk_score,
        "risk_band": risk_band,
        "subject_ips": [],
    }


def _empty_event_item(learner_name: str) -> dict[str, Any]:
    return {
        "learner_name": learner_name,
        "risk_id": 0,
        "risk_name": learner_name,
        "risk_description": "暂无风险说明",
        "trigger_time": "-",
        "attack_ratio": 0.0,
        "dominant_label": "low",
        "flow_count": 0,
        "risk_score": 0.0,
        "risk_band": "low",
        "subject_ips": [],
    }


def _topology_view(
    *,
    label: str,
    host: dict[str, Any],
    endpoint: dict[str, Any],
    is_benign: bool | None,
) -> dict[str, Any]:
    return {
        "label": label,
        "view_kind": "aggregate",
        "is_benign": is_benign,
        "host": host,
        "endpoint": endpoint,
    }


def _risk_ip_item(row: dict[str, Any], learner: dict[str, Any] | None) -> dict[str, Any]:
    learner_name = str(row.get("assigned_learner") or "")
    risk_score = _float(learner.get("risk_score") if learner else None)
    risk_band = str((learner or {}).get("risk_band") or "low").lower()
    protocol = _protocol_name(row.get("top_protocol"))
    top_dst_port = int(row.get("top_dst_port") or 0)
    top_dst_ip = str(row.get("top_dst_ip") or "-")
    flow_count = int(row.get("flow_count") or 0)
    unknown_count = int(row.get("unknown_count") or 0)
    return {
        "id": int((learner or {}).get("id") or 0),
        "subjectIp": str(row.get("subject_ip") or ""),
        "name": learner_name or "UNKNOWN",
        "triggerTime": _format_time(row.get("trigger_time")) or "-",
        "description": f"risk_band={risk_band}; learner={learner_name or 'UNKNOWN'}; top_protocol={protocol}; top_dst_port={top_dst_port}",
        "features": f"flows={flow_count}; unknown={unknown_count}; top_dst_ip={top_dst_ip}",
        "riskScore": risk_score,
        "riskBand": risk_band,
        "learnerName": learner_name,
    }


def _compact_protocol_distribution(rows: list[dict[str, Any]], *, visible: int = 11) -> list[dict[str, Any]]:
    items = [
        {"name": _protocol_name(row.get("protocol")), "value": int(row.get("value") or 0)}
        for row in rows
        if int(row.get("value") or 0) > 0
    ]
    if len(items) <= visible + 1:
        return items
    head = items[:visible]
    other = sum(int(item["value"]) for item in items[visible:])
    return [*head, {"name": "其他", "value": other}]


def _protocol_name(value: Any) -> str:
    try:
        proto = int(value)
    except (TypeError, ValueError):
        return str(value or "UNKNOWN")
    return {1: "ICMP", 6: "TCP", 17: "UDP"}.get(proto, str(proto))


def _format_time(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value)
    if "T" in text:
        text = text.replace("T", " ").replace("Z", "")
    if "." in text:
        text = text.split(".", 1)[0]
    if "+" in text:
        text = text.split("+", 1)[0].strip()
    return text


def _float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number) or math.isinf(number):
        return 0.0
    return number


def _safe_int(call: Any) -> int:
    try:
        return int(call())
    except Exception:
        return 0


def _time_range_start(value: str) -> str | None:
    now = datetime.now(timezone.utc)
    if value == "7d":
        start = now - timedelta(days=7)
    elif value == "30d":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(hours=24)
    return start.isoformat(timespec="seconds").replace("+00:00", "Z")


def _risk_item_from_learner(
    learner: dict[str, Any],
    *,
    subject_ip: str = "",
    include_count: bool = False,
) -> dict[str, Any]:
    item = {
        "id": int(learner.get("id") or 0),
        "subjectIp": subject_ip or "-",
        "name": str(learner.get("learner_name") or "UNKNOWN"),
        "triggerTime": _format_time(learner.get("last_seen_at")) or "-",
        "description": str(learner.get("risk_reason") or "暂无风险说明"),
        "features": _learner_features(learner),
    }
    if include_count:
        item["riskIpCount"] = int(learner.get("flow_count") or 0)
    return item


def _first_subject_ip(service: PageQueryService, learner: dict[str, Any]) -> str:
    learner_name = str(learner.get("learner_name") or "")
    if not learner_name:
        return ""
    ips = service.flows.top_subject_ips_by_learner(
        session_id=service.session_id,
        learner_names=[learner_name],
        limit_per_learner=1,
    )
    return (ips.get(learner_name) or [""])[0]


def _learner_features(learner: dict[str, Any]) -> str:
    metric = learner.get("metric_json") if isinstance(learner.get("metric_json"), dict) else {}
    parts = [
        f"risk_band={learner.get('risk_band') or 'low'}",
        f"flow_count={learner.get('flow_count') or 0}",
    ]
    if metric.get("top1_protocol_share") is not None:
        parts.append(f"top1_protocol_share={float(metric.get('top1_protocol_share') or 0):.3f}")
    return "、".join(parts)


def _traffic_log_item(row: dict[str, Any], *, subject_ip: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row.get("flow_uid") or row.get("mq_message_id") or ""),
        "time": _format_time(row.get("event_time")) or "-",
        "ip": str(row.get("dst_ip") if subject_ip else row.get("src_ip") or ""),
        "protocol": _protocol_name(row.get("protocol")),
    }


def _empty_graph(node_mode: str = "host") -> dict[str, Any]:
    return {"flow_count": 0, "node_mode": node_mode, "nodes": [], "links": [], "stats": {}}


def _empty_dataset_topology() -> dict[str, Any]:
    return {
        "version": 1,
        "total_flows": 0,
        "labels": ["__combined__"],
        "default_label": "__combined__",
        "default_node_mode": "host",
        "aggregate_views": ["__combined__"],
        "views": {
            "__combined__": {
                "label": "__combined__",
                "view_kind": "aggregate",
                "is_benign": None,
                "host": _empty_graph("host"),
                "endpoint": _empty_graph("endpoint"),
            }
        },
    }


def _is_internal_ip(ip: str) -> bool:
    return (
        ip.startswith("10.")
        or ip.startswith("192.168.")
        or ip.startswith("172.16.")
        or ip.startswith("172.17.")
        or ip.startswith("172.18.")
        or ip.startswith("172.19.")
        or ip.startswith("172.2")
        or ip.startswith("172.30.")
        or ip.startswith("172.31.")
    )
