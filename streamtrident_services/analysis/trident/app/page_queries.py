from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from .persistence.ch_flow_repository import ChFlowRepository
from .persistence.learner_repository import LearnerRepository
from .protocol_utils import (
    is_meaningful_app_proto,
    resolve_flow_protocol_from_row,
    resolve_flow_protocol_name,
    transport_protocol_name,
)
from .redis_consumer import RedisListConsumer, RedisStreamConsumer
from .runtime.quality import is_baseline_learner, resolve_session_baseline_learner


ATTACK_TYPE_DISPLAY: dict[str, dict[str, str]] = {
    "PORT_SCAN": {"name": "端口扫描", "desc": "攻击源针对少量固定目标主机，批量试探大量不同端口，探测开放服务，为后续渗透做铺垫，整体端口分散、无固定访问服务。"},
    "HOST_SCAN": {"name": "主机扫描/横向探测", "desc": "攻击源依托固定常用服务端口，批量访问内网大量不同目标主机，探测存活资产，是典型的内网横向渗透前置行为。"},
    "DDOS_VICTIM": {"name": "DDoS攻击", "desc": "海量分布式源IP集中冲击单一或少量目标主机的固定服务端口，通过流量洪泛消耗目标带宽与算力，可能造成服务瘫痪。"},
    "DOS_ATTACKER": {"name": "DoS攻击", "desc": "攻击源高频重复连接固定目标服务，依托高复用连接路径持续施压，耗尽目标资源实现单点打击。"},
    "DRDOS_REFLECTION_FAMILY": {"name": "反射放大/高分散单向冲击", "desc": "攻击者伪造受害者地址利用第三方服务放大流量，具备端口极度分散、连接一次性、流量单向失衡的特征，对目标形成无差别洪泛冲击。"},
    "SLOW_DOS_SUSPECTED": {"name": "慢速DoS攻击", "desc": "不依靠大流量洪泛，通过低速请求、长效弱连接持续占用目标Web及固定服务资源，缓慢耗尽服务端会话与算力导致服务失效。"},
    "WEB_DDOS_SUSPECTED": {"name": "Web DDoS攻击", "desc": "海量访问源集中针对80、443等Web端口及业务接口发起复杂高频请求，依托多样业务访问路径施压，专门打击Web业务服务。"},
    "BRUTE_FORCE_SUSPECTED": {"name": "暴力破解", "desc": "攻击源反复高频访问SSH、Web等固定登录端口，持续尝试账号密码组合，流量重复度高。"},
    "BENIGN_NORMAL": {"name": "正常流量", "desc": "当前窗口未命中攻击规则，行为接近正常业务。"},
    "UNKNOWN_SUSPECTED": {"name": "未命名攻击", "desc": "当前流量存在异常迹象，但尚未匹配到已命名攻击类型。"},
}


class PageQueryService:
    def __init__(
        self,
        *,
        session_id: str,
        flows: ChFlowRepository,
        learners: LearnerRepository,
        redis: RedisListConsumer | RedisStreamConsumer | None = None,
    ) -> None:
        self.session_id = session_id
        self.flows = flows
        self.learners = learners
        self.redis = redis

    def _session_baseline_learner(self, session_id: str | None = None) -> str | None:
        sid = session_id or self.session_id
        rows = self.learners.list_learners(session_id=sid)
        flow_counts = {
            str(row.get("learner_name") or ""): int(row.get("flow_count") or 0)
            for row in rows
            if str(row.get("learner_name") or "")
        }
        return resolve_session_baseline_learner(rows, flow_counts=flow_counts or None)

    def _learner_display_sequence_map(
        self,
        learner_rows: list[dict[str, Any]] | None = None,
        *,
        session_id: str | None = None,
    ) -> dict[str, int]:
        sid = session_id or self.session_id
        rows = learner_rows if learner_rows is not None else self.learners.list_learners(session_id=sid)
        return _learner_display_sequence_map(rows)

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
                "total_bytes": int(summary.get("total_bytes") or 0),
                "protocol_count": int(summary.get("protocol_count") or 0),
                "risk_learner_count": len(risk_names),
                "risk_ip_count": int(summary.get("risk_ip_count") or 0),
            },
            "traffic_distribution": [
                {"name": "正常流量", "value": int(summary.get("normal_bytes") or 0)},
                {"name": "疑似异常流量", "value": int(summary.get("risk_bytes") or 0)},
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
            "totalTraffic": int(metrics["total_bytes"]),
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

    def overview_traffic_trend(self, *, time_range: str = "24h") -> list[dict[str, Any]]:
        sid = self.session_id
        spec = _traffic_trend_spec(time_range)
        learner_rows = self.learners.list_learners(session_id=sid)
        risk_names = _risk_learner_names(learner_rows)
        rows = self.flows.traffic_trend(
            session_id=sid,
            risk_learners=risk_names,
            bucket=spec["bucket"],
            time_from=spec["time_from"],
            time_to=spec["time_to"],
        )
        by_bucket = {
            str(row.get("bucket_start") or ""): {
                "normal": int(row.get("normal") or 0),
                "abnormal": int(row.get("abnormal") or 0),
            }
            for row in rows
        }
        return [
            {
                "label": item["label"],
                "normal": by_bucket.get(item["key"], {}).get("normal", 0),
                "abnormal": by_bucket.get(item["key"], {}).get("abnormal", 0),
            }
            for item in spec["buckets"]
        ]

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
        session_baseline = self._session_baseline_learner(session_id=sid)
        display_sequence_by_name = self._learner_display_sequence_map(rows, session_id=sid)
        items = [
            _learner_event_item(
                index,
                row,
                session_baseline_learner=session_baseline,
                display_sequence_by_name=display_sequence_by_name,
            )
            for index, row in enumerate(
                _filter_learner_rows(
                    rows,
                    name=name,
                    risk_band=risk_band,
                    time_from=time_from,
                    time_to=time_to,
                    display_sequence_by_name=display_sequence_by_name,
                    session_baseline_learner=session_baseline,
                ),
                start=1,
            )
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
        learner_names: list[str] | None = None,
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        learner_rows = self.learners.list_learners(session_id=sid)
        learner_by_name = {str(row.get("learner_name") or ""): row for row in learner_rows}
        session_baseline = self._session_baseline_learner(session_id=sid)
        display_sequence_by_name = self._learner_display_sequence_map(learner_rows, session_id=sid)
        risk_names = learner_names if learner_names is not None else _risk_learner_names(learner_rows)
        risk_name_set = set(risk_names)
        query_learners = _learner_names_matching_display_name(
            learner_rows,
            name,
            risk_name_set=risk_name_set,
            display_sequence_by_name=display_sequence_by_name,
            session_baseline_learner=session_baseline,
        )
        if query_learners is not None and not query_learners:
            return {"items": [], "total": 0}
        result = self.flows.risk_ip_view(
            session_id=sid,
            risk_learners=query_learners or risk_names,
            limit=limit,
            offset=offset,
            subject_ip_like=subject_ip,
            trigger_time_prefix=trigger_time,
        )
        items = []
        for row in result["items"]:
            learner_name = str(row.get("assigned_learner") or "")
            if learner_name not in risk_name_set:
                continue
            items.append(
                _risk_ip_item(
                    row,
                    learner_by_name.get(learner_name),
                    is_risk_learner=True,
                    display_sequence_by_name=display_sequence_by_name,
                )
            )
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
        session_baseline = self._session_baseline_learner(session_id=sid)
        display_sequence_by_name = self._learner_display_sequence_map(session_id=sid)
        event = (
            _learner_event_item(
                1,
                learner,
                session_baseline_learner=session_baseline,
                display_sequence_by_name=display_sequence_by_name,
            )
            if learner
            else _empty_event_item(learner_name)
        )
        primary_attack = _primary_attack_type(learner, session_baseline_learner=session_baseline)
        is_benign = primary_attack == "BENIGN_NORMAL"
        traffic_kind = "benign" if is_benign else "attack"
        topology_risk_learners = [] if is_benign else [learner_name]
        view = {
            "learner": learner_name,
            "risk_id": event["risk_id"],
            "risk_name": event["risk_name"],
            "risk_description": event["risk_description"],
            "trigger_time": event["trigger_time"],
            "attack_ratio": event["attack_ratio"],
            "dominant_label": event["dominant_label"],
            "dominant_ratio": event["risk_score"],
            "is_benign": is_benign,
            "host": self.flows.topology_graph(
                session_id=sid,
                node_mode="host",
                risk_learners=topology_risk_learners,
                learner_name=learner_name,
                subject_ip=subject_ip,
                traffic_kind=traffic_kind,
                top_n=top_n,
            ),
            "endpoint": self.flows.topology_graph(
                session_id=sid,
                node_mode="endpoint",
                risk_learners=topology_risk_learners,
                learner_name=learner_name,
                subject_ip=subject_ip,
                traffic_kind=traffic_kind,
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
        learner_by_name = {str(row.get("learner_name") or ""): row for row in learner_rows}
        session_baseline = self._session_baseline_learner(session_id=sid)
        risk_names = _risk_learner_names(learner_rows)
        risk_name_set = set(risk_names)
        display_sequence_by_name = self._learner_display_sequence_map(learner_rows, session_id=sid)
        query_learners = _learner_names_matching_display_name(
            learner_rows,
            name,
            risk_name_set=risk_name_set,
            display_sequence_by_name=display_sequence_by_name,
            session_baseline_learner=session_baseline,
        )
        if query_learners is not None and not query_learners:
            return {"total": 0, "risks": []}
        raw = self.flows.risk_ip_view(
            session_id=sid,
            risk_learners=query_learners or risk_names,
            limit=10000,
            offset=0,
            subject_ip_like=subject_ip,
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in raw["items"]:
            ip = str(row.get("subject_ip") or "")
            learner = str(row.get("assigned_learner") or "") or "UNKNOWN"
            if learner not in risk_name_set:
                continue
            learner_row = learner_by_name.get(learner) or {}
            display_name = _display_for_learner(
                learner_row,
                display_sequence_by_name=display_sequence_by_name,
            )["name"]
            if not display_name:
                display_name = learner
            if not ip:
                continue
            grouped.setdefault(ip, []).append(
                {
                    "name": display_name,
                    "learnerName": learner,
                    "triggerCount": int(row.get("flow_count") or 0),
                }
            )

        ip_rows: list[dict[str, Any]] = []
        for seq, (ip, learner_risks) in enumerate(
            sorted(grouped.items(), key=lambda item: (-sum(risk["triggerCount"] for risk in item[1]), item[0])),
            start=1,
        ):
            risks = sorted(learner_risks, key=lambda item: (-item["triggerCount"], item["name"], item["learnerName"]))
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
        limit: int = 6,
        offset: int = 0,
    ) -> dict[str, Any]:
        sid = self.session_id
        time_from = _clean_trigger_bound(trigger_start)
        time_to = _clean_trigger_bound(trigger_end)
        all_rows = self.learners.list_learners(session_id=sid)
        session_baseline = self._session_baseline_learner(session_id=sid)
        display_sequence_by_name = self._learner_display_sequence_map(all_rows, session_id=sid)
        rows = _filter_learner_rows(
            all_rows,
            name=name,
            risk_band=None,
            time_from=time_from,
            time_to=time_to,
            include_all_bands=False,
            display_sequence_by_name=display_sequence_by_name,
            session_baseline_learner=session_baseline,
        )
        rows = [row for row in rows if int(row.get("flow_count") or 0) > 0]
        event_total = len(rows)
        risk_type_total = len(
            _distinct_risk_type_names(rows)
        )
        risk_names = _risk_learner_names(rows)
        risk_ip_result = self.flows.risk_ip_view(
            session_id=sid,
            risk_learners=risk_names,
            limit=1,
            offset=0,
        )
        risk_ip_count = int(risk_ip_result.get("total") or 0)
        safe_offset = max(0, int(offset or 0))
        capped = max(1, min(int(limit), 50))
        page_rows = rows[safe_offset : safe_offset + capped]
        views: dict[str, Any] = {}
        learners: list[str] = []
        for row in page_rows:
            learner_name = str(row.get("learner_name") or "")
            if not learner_name:
                continue
            topology = self.learner_topology(learner_name=learner_name, top_n=top_n)
            view = topology["views"][learner_name]
            learners.append(learner_name)
            views[learner_name] = view
        return {
            "version": 1,
            "total": event_total,
            "risk_type_total": risk_type_total,
            "risk_ip_count": risk_ip_count,
            "learners": learners,
            "default_learner": learners[0] if learners else "",
            "views": views,
        }

    def risk_by_id(self, *, risk_id: int) -> dict[str, Any]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        display_sequence_by_name = self._learner_display_sequence_map(session_id=self.session_id)
        item = _risk_item_from_learner(
            learner,
            subject_ip=_first_subject_ip(self, learner),
            display_sequence_by_name=display_sequence_by_name,
        )
        learner_name = str(learner.get("learner_name") or "")
        item["riskIpCount"] = (
            self.flows.unique_src_ip_count_by_learner(
                session_id=self.session_id,
                learner_name=learner_name,
            )
            if learner_name
            else 0
        )
        item["riskPortCount"] = (
            self.flows.unique_dst_port_count_by_learner(
                session_id=self.session_id,
                learner_name=learner_name,
            )
            if learner_name
            else 0
        )
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

    def risk_traffic_logs(self, *, risk_id: int, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        learner_name = str(learner.get("learner_name") or "")
        if not learner_name:
            return _traffic_logs_page(items=[], total=0, limit=limit, offset=offset)
        flows = self.flows.list_flows(session_id=self.session_id, learner_name=learner_name, limit=limit, offset=offset)
        items = [_traffic_log_item(row) for row in flows["items"]]
        return _traffic_logs_page(
            items=items,
            total=flows.get("total"),
            limit=flows.get("limit", limit),
            offset=flows.get("offset", offset),
        )

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
                "learnerName": item["learnerName"],
                "triggerTime": item["triggerTime"],
                "description": item["description"],
                "features": item["features"],
                "riskScore": item["riskScore"],
                "riskBand": item["riskBand"],
            }
            for item in data["items"]
        ]

    def ip_events_topology(
        self, *, ip: str, top_n: int = 50, limit: int = 6, offset: int = 0
    ) -> dict[str, Any]:
        safe_offset = max(0, int(offset or 0))
        capped = max(1, min(int(limit), 50))
        data = self.risk_ip_view(
            limit=capped,
            offset=safe_offset,
            subject_ip=ip,
        )
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
            "total": int(data["total"]),
            "learners": learners,
            "default_learner": learners[0] if learners else "",
            "views": views,
        }

    def ip_traffic_logs(self, *, ip: str, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        flows = self.flows.list_flows(session_id=self.session_id, src_ip=ip, limit=limit, offset=offset)
        items = [_traffic_log_item(row) for row in flows["items"]]
        return _traffic_logs_page(
            items=items,
            total=flows.get("total"),
            limit=flows.get("limit", limit),
            offset=flows.get("offset", offset),
        )

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
        name = str(row.get("learner_name") or "")
        if name and _is_attack_learner(row):
            names.append(name)
    return names


def _is_attack_learner(row: dict[str, Any]) -> bool:
    return _primary_attack_type(row) != "BENIGN_NORMAL"


def _distinct_risk_type_names(
    rows: list[dict[str, Any]],
) -> set[str]:
    names: set[str] = set()
    for row in rows:
        attack_type = _rule_attack_type(row)
        if not attack_type or attack_type == "BENIGN_NORMAL":
            continue
        display = _attack_display(attack_type)
        name = str(display.get("name") or row.get("learner_name") or "").strip()
        if name:
            names.add(name)
    return names


def _clean_trigger_bound(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"undefined", "null", "invalid date"}:
        return None
    return text


def _filter_learner_rows(
    rows: list[dict[str, Any]],
    *,
    name: str | None,
    risk_band: str | None,
    time_from: str | None,
    time_to: str | None,
    include_all_bands: bool = False,
    display_sequence_by_name: dict[str, int] | None = None,
    session_baseline_learner: str | None = None,
) -> list[dict[str, Any]]:
    time_from = _clean_trigger_bound(time_from)
    time_to = _clean_trigger_bound(time_to)
    filtered = []
    name_text = (name or "").strip().lower()
    band_text = (risk_band or "").strip().lower()
    for row in rows:
        row_band = str(row.get("risk_band") or "").lower()
        if band_text:
            if row_band != band_text:
                continue
        elif not include_all_bands and not _is_attack_learner(row):
            continue
        if name_text:
            display_name = _learner_risk_display_name(
                row,
                session_baseline_learner=session_baseline_learner,
                display_sequence_by_name=display_sequence_by_name,
            ).lower()
            if name_text not in display_name:
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


def _learner_risk_display_name(
    row: dict[str, Any],
    *,
    session_baseline_learner: str | None = None,
    display_sequence_by_name: dict[str, int] | None = None,
) -> str:
    primary_attack = _primary_attack_type(row, session_baseline_learner=session_baseline_learner)
    if primary_attack == "BENIGN_NORMAL":
        return str(row.get("learner_name") or "")
    return _display_for_learner(
        row,
        session_baseline_learner=session_baseline_learner,
        display_sequence_by_name=display_sequence_by_name,
    )["name"]


def _learner_names_matching_display_name(
    rows: list[dict[str, Any]],
    name: str | None,
    *,
    risk_name_set: set[str],
    display_sequence_by_name: dict[str, int] | None = None,
    session_baseline_learner: str | None = None,
) -> list[str] | None:
    name_text = (name or "").strip()
    if not name_text:
        return None
    needle = name_text.lower()
    matched: list[str] = []
    for row in rows:
        learner_name = str(row.get("learner_name") or "")
        if learner_name not in risk_name_set:
            continue
        display_name = _learner_risk_display_name(
            row,
            session_baseline_learner=session_baseline_learner,
            display_sequence_by_name=display_sequence_by_name,
        ).lower()
        if needle in display_name:
            matched.append(learner_name)
    return matched


def _learner_event_item(
    index: int,
    row: dict[str, Any],
    *,
    session_baseline_learner: str | None = None,
    display_sequence_by_name: dict[str, int] | None = None,
) -> dict[str, Any]:
    learner_name = str(row.get("learner_name") or "")
    risk_score = _float(row.get("risk_score"))
    risk_band = str(row.get("risk_band") or "low").lower()
    primary_attack = _primary_attack_type(row, session_baseline_learner=session_baseline_learner)
    display = _display_for_learner(
        row,
        session_baseline_learner=session_baseline_learner,
        display_sequence_by_name=display_sequence_by_name,
    )
    risk_name = display["name"] if primary_attack else learner_name
    base_desc = str(row.get("risk_reason") or "暂无风险说明")
    risk_description = display["desc"] if primary_attack and display.get("desc") else base_desc
    return {
        "learner_name": learner_name,
        "risk_id": int(row.get("id") or index),
        "risk_name": risk_name,
        "risk_description": risk_description,
        "trigger_time": _format_time(row.get("last_seen_at")) or "-",
        "attack_ratio": risk_score,
        "dominant_label": display["name"] if primary_attack else risk_band,
        "flow_count": int(row.get("flow_count") or 0),
        "risk_score": risk_score,
        "risk_band": risk_band,
        "subject_ips": [],
    }


def _empty_event_item(learner_name: str) -> dict[str, Any]:
    benign_display = _attack_display("BENIGN_NORMAL")
    return {
        "learner_name": learner_name,
        "risk_id": 0,
        "risk_name": benign_display["name"],
        "risk_description": benign_display["desc"],
        "trigger_time": "-",
        "attack_ratio": 0.0,
        "dominant_label": benign_display["name"],
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


def _risk_ip_item(
    row: dict[str, Any],
    learner: dict[str, Any] | None,
    *,
    is_risk_learner: bool,
    display_sequence_by_name: dict[str, int] | None = None,
) -> dict[str, Any]:
    learner_name = str(row.get("assigned_learner") or "")
    attack_type = _primary_attack_type(learner or {})
    display = _display_for_learner(learner or {}, display_sequence_by_name=display_sequence_by_name)
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
        "name": display["name"] if attack_type else learner_name or "UNKNOWN",
        "triggerTime": _format_time(row.get("trigger_time")) or "-",
        "description": f"risk_band={risk_band}; learner={learner_name or 'UNKNOWN'}; 风险类型={display['name'] if attack_type else '未知'}; 说明={display['desc'] if attack_type else '-'}; top_protocol={protocol}; top_dst_port={top_dst_port}",
        "features": f"flows={flow_count}; unknown={unknown_count}; top_dst_ip={top_dst_ip}",
        "riskScore": risk_score,
        "riskBand": risk_band,
        "learnerName": learner_name,
    }


def _compact_protocol_distribution(rows: list[dict[str, Any]], *, visible: int = 11) -> list[dict[str, Any]]:
    del visible
    totals = {"TCP": 0, "UDP": 0, "其他": 0}
    for row in rows:
        count = int(row.get("value") or 0)
        if count <= 0:
            continue
        bucket = _protocol_distribution_bucket(row.get("protocol"))
        totals[bucket] += count
    return [
        {"name": name, "value": totals[name]}
        for name in ("TCP", "UDP", "其他")
        if totals[name] > 0
    ]


def _protocol_distribution_bucket(value: Any) -> str:
    if value is None:
        return "其他"
    text = str(value).strip()
    if not text:
        return "其他"
    try:
        proto = int(text)
    except (TypeError, ValueError):
        upper = text.upper()
        if upper in {"TCP"}:
            return "TCP"
        if upper in {"UDP"}:
            return "UDP"
        return "其他"
    if proto == 6:
        return "TCP"
    if proto == 17:
        return "UDP"
    return "其他"


def _protocol_name(value: Any, *, protocol: Any = None) -> str:
    if protocol is not None:
        return resolve_flow_protocol_name(app_proto=value, protocol=protocol)
    if is_meaningful_app_proto(value):
        return str(value).strip().upper()
    try:
        proto = int(value)
    except (TypeError, ValueError):
        text = str(value or "").strip()
        if not text:
            return "UNKNOWN"
        lowered = text.lower()
        if lowered in {"unknown", "none", "-"}:
            return "UNKNOWN"
        return text.upper()
    return transport_protocol_name(proto) or "UNKNOWN"


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


def _traffic_trend_spec(value: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if value == "7d":
        start = today - timedelta(days=6)
        buckets = [
            {
                "key": _bucket_key(start + timedelta(days=index)),
                "label": (start + timedelta(days=index)).strftime("%m-%d"),
            }
            for index in range(7)
        ]
        return {
            "bucket": "day",
            "time_from": _iso_z(start),
            "time_to": _iso_z(now),
            "buckets": buckets,
        }

    if value == "30d":
        first_day = today - timedelta(days=29)
        start = first_day - timedelta(days=first_day.weekday())
        bucket_count = int(((today - start).days // 7) + 1)
        buckets = []
        for index in range(bucket_count):
            bucket_start = start + timedelta(days=index * 7)
            bucket_end = min(bucket_start + timedelta(days=6), today)
            buckets.append(
                {
                    "key": _bucket_key(bucket_start),
                    "label": _format_chart_date_range(bucket_start, bucket_end),
                }
            )
        return {
            "bucket": "week",
            "time_from": _iso_z(start),
            "time_to": _iso_z(now),
            "buckets": buckets,
        }

    start = current_hour - timedelta(hours=23)
    buckets = [
        {
            "key": _bucket_key(start + timedelta(hours=index)),
            "label": (start + timedelta(hours=index)).strftime("%H:00"),
        }
        for index in range(24)
    ]
    return {
        "bucket": "hour",
        "time_from": _iso_z(start),
        "time_to": _iso_z(now),
        "buckets": buckets,
    }


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _bucket_key(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _format_chart_date_range(start: datetime, end: datetime) -> str:
    """Chart x-axis label for weekly buckets, e.g. 05-01~05-07."""
    start_day = start.astimezone(timezone.utc)
    end_day = end.astimezone(timezone.utc)
    return f"{start_day.strftime('%m-%d')}~{end_day.strftime('%m-%d')}"


def _risk_item_from_learner(
    learner: dict[str, Any],
    *,
    subject_ip: str = "",
    include_count: bool = False,
    display_sequence_by_name: dict[str, int] | None = None,
) -> dict[str, Any]:
    display = _display_for_learner(learner, display_sequence_by_name=display_sequence_by_name)
    item = {
        "id": int(learner.get("id") or 0),
        "subjectIp": subject_ip or "-",
        "name": display["name"],
        "triggerTime": _format_time(learner.get("last_seen_at")) or "-",
        "description": display["desc"],
        "features": _learner_features(learner),
    }
    if include_count:
        item["riskIpCount"] = int(learner.get("flow_count") or 0)
    return item


def _rule_attack_type(learner: dict[str, Any]) -> str:
    rule_json = learner.get("rule_json")
    if isinstance(rule_json, dict):
        attack_types = rule_json.get("attack_types")
        if isinstance(attack_types, list):
            for item in attack_types:
                if isinstance(item, dict):
                    attack_type = str(item.get("attack_type") or "").strip()
                    if attack_type:
                        return attack_type
    return ""


def _primary_attack_type(
    learner: dict[str, Any],
    *,
    session_baseline_learner: str | None = None,
) -> str:
    learner_name = str(learner.get("learner_name") or "").strip()
    if is_baseline_learner(learner_name, session_baseline_learner=session_baseline_learner):
        return "BENIGN_NORMAL"
    rule_json = learner.get("rule_json")
    if isinstance(rule_json, dict):
        attack_types = rule_json.get("attack_types")
        if isinstance(attack_types, list):
            for item in attack_types:
                if isinstance(item, dict):
                    attack_type = str(item.get("attack_type") or "").strip()
                    if attack_type:
                        return attack_type
    return "BENIGN_NORMAL"


def _primary_attack_confidence(learner: dict[str, Any]) -> float:
    rule_json = learner.get("rule_json")
    if isinstance(rule_json, dict):
        attack_types = rule_json.get("attack_types")
        if isinstance(attack_types, list):
            for item in attack_types:
                if isinstance(item, dict):
                    return _float(item.get("confidence"))
    if _primary_attack_type(learner) == "BENIGN_NORMAL":
        return 0.35
    return 0.0


def _attack_display(attack_type: str, *, sequence: int | None = None) -> dict[str, str]:
    key = str(attack_type or "").strip().upper()
    if key in ATTACK_TYPE_DISPLAY:
        display = dict(ATTACK_TYPE_DISPLAY[key])
        if sequence is not None and sequence > 0:
            display["name"] = f"{display['name']}{sequence}"
        return display
    base_name = key or "未知类型"
    if sequence is not None and sequence > 0:
        base_name = f"{base_name}{sequence}"
    return {"name": base_name, "desc": "暂无该类型的语义化说明。"}


def _display_for_learner(
    learner: dict[str, Any],
    *,
    session_baseline_learner: str | None = None,
    display_sequence_by_name: dict[str, int] | None = None,
) -> dict[str, str]:
    rule_attack = _rule_attack_type(learner)
    primary_attack = _primary_attack_type(learner, session_baseline_learner=session_baseline_learner)
    display_type = rule_attack if rule_attack and rule_attack != "BENIGN_NORMAL" else primary_attack
    sequence = None
    if display_sequence_by_name:
        sequence = display_sequence_by_name.get(str(learner.get("learner_name") or ""))
    return _attack_display(display_type, sequence=sequence)


def _learner_display_sequence_map(rows: list[dict[str, Any]]) -> dict[str, int]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        attack_type = _rule_attack_type(row)
        if not attack_type or attack_type == "BENIGN_NORMAL":
            continue
        base_name = _attack_display(attack_type)["name"]
        grouped.setdefault(base_name, []).append(row)
    sequences: dict[str, int] = {}
    for items in grouped.values():
        if len(items) <= 1:
            continue
        items.sort(
            key=lambda row: (
                int(row.get("creation_window_index") or 0),
                int(row.get("id") or 0),
                str(row.get("learner_name") or ""),
            )
        )
        for index, row in enumerate(items, start=1):
            sequences[str(row.get("learner_name") or "")] = index
    return sequences


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
    parts: list[str] = []
    if metric.get("top1_protocol_share") is not None:
        parts.append(
            f"主导协议占比：{float(metric.get('top1_protocol_share') or 0):.3f}"
        )
    return "、".join(parts)


def _traffic_logs_page(
    *,
    items: list[dict[str, Any]],
    total: Any,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "items": items,
        "total": int(total or 0),
        "limit": int(limit or 0),
        "offset": int(offset or 0),
    }


def _traffic_log_item(row: dict[str, Any]) -> dict[str, Any]:
    src_port = row.get("src_port")
    dst_port = row.get("dst_port")
    return {
        "id": str(row.get("flow_uid") or row.get("mq_message_id") or ""),
        "srcIp": str(row.get("src_ip") or ""),
        "srcPort": int(src_port) if src_port is not None else 0,
        "dstIp": str(row.get("dst_ip") or ""),
        "dstPort": int(dst_port) if dst_port is not None else 0,
        "accessTime": _format_time(row.get("event_time")) or "-",
        "traffic": int(row.get("total_bytes") or 0),
        "protocol": resolve_flow_protocol_from_row(row),
    }


def _empty_graph(node_mode: str = "host") -> dict[str, Any]:
    return {"flow_count": 0, "total_flow_count": 0, "node_mode": node_mode, "nodes": [], "links": [], "stats": {}}


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
