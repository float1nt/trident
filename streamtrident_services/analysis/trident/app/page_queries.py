from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from zoneinfo import ZoneInfo

from .persistence.ch_flow_repository import ChFlowRepository
from .persistence.learner_repository import LearnerRepository
from .timezone_utils import (
    bucket_key,
    format_display_time,
    parse_bucket_start,
    resolve_display_timezone,
    to_utc_iso,
)
from .protocol_utils import (
    is_meaningful_app_proto,
    resolve_flow_protocol_from_row,
    resolve_flow_protocol_name,
    transport_protocol_name,
)
from .redis_consumer import RedisListConsumer, RedisStreamConsumer
from .runtime.quality import is_baseline_learner, resolve_session_baseline_learner


ATTACK_TYPE_DISPLAY: dict[str, dict[str, str]] = {
    "ENCRYPTED_INTERNAL_SCAN": {"name": "加密探测内网端口", "category": "恶意攻击类", "desc": "单台主机在短时间内向大量内部主机或端口发起高并发连接，形成明显扫描拓扑。"},
    "ENCRYPTED_PROTOCOL_BRUTE_FORCE": {"name": "加密协议暴力破解", "category": "恶意攻击类", "desc": "攻击源持续密集访问固定加密服务端口，连接路径高度复用。"},
    "P2P_BOTNET_COMMUNICATION": {"name": "P2P 僵尸网络通信", "category": "恶意攻击类", "desc": "单台内部主机连接大量分散外部 IP，连接离散且边复用低。"},
    "ENCRYPTED_AUTOMATED_VULNERABILITY_SWEEP": {"name": "加密自动化漏洞刷网", "category": "恶意攻击类", "desc": "外部主机短时间访问大量内部 HTTPS 站点，目标端口集中。"},
    "ENCRYPTED_MULTI_HOP_PROXY": {"name": "密态非法多跳代理", "category": "恶意攻击类", "desc": "同一节点同时维持多条入向和出向加密链路，呈现中转代理拓扑。"},
    "BENIGN_NORMAL": {"name": "正常流量", "category": "", "desc": "当前窗口未命中攻击规则，行为接近正常业务。"},
    "UNKNOWN_SUSPECTED": {"name": "未命名攻击", "category": "恶意攻击类", "desc": "当前流量存在异常迹象，但尚未匹配到已命名攻击类型。"},
}

EVENT_SCOPE_EXCLUDED_ATTACK_TYPES = frozenset({"BENIGN_NORMAL"})

# Victim-centric topology: top_n = number of attacked dst IPs/ports; edges_per_victim = src→dst edges each.
TOPOLOGY_TOP_VICTIMS_DEFAULT = 8
TOPOLOGY_TOP_VICTIMS_DASHBOARD_MAIN = 50
TOPOLOGY_EDGES_DASHBOARD_MAIN = 15
TOPOLOGY_EDGES_DASHBOARD_COMPACT = 13
TOPOLOGY_EDGES_LEARNER_DETAIL = 15
TOPOLOGY_EDGES_GRID = 11


class PageQueryService:
    def __init__(
        self,
        *,
        session_id: str,
        flows: ChFlowRepository,
        learners: LearnerRepository,
        redis: RedisListConsumer | RedisStreamConsumer | None = None,
        display_timezone: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.flows = flows
        self.learners = learners
        self.redis = redis
        self.display_tz = resolve_display_timezone(display_timezone)

    def _fmt(self, value: Any) -> str:
        return format_display_time(value, self.display_tz)

    def time_range_bounds(self, time_range: str) -> dict[str, str]:
        return _time_range_bounds(time_range, display_tz=self.display_tz)

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
        transport_protocol_rows = _call_protocol_distribution(
            self.flows,
            method_name="transport_protocol_distribution",
            fallback_name="protocol_distribution",
            session_id=sid,
            time_from=time_from,
            time_to=time_to,
            limit=100,
        )
        application_protocol_rows = _call_protocol_distribution(
            self.flows,
            method_name="application_protocol_distribution",
            fallback_name="protocol_distribution",
            session_id=sid,
            time_from=time_from,
            time_to=time_to,
            limit=100,
        )
        transport_protocol_distribution = _compact_protocol_distribution(
            transport_protocol_rows
        )
        application_protocol_distribution = _compact_application_protocol_distribution(
            application_protocol_rows
        )
        active_abnormal_learners = _parse_string_list(summary.get("active_abnormal_learners"))
        risk_type_count = _risk_type_count_from_active_learners(
            learner_rows,
            active_abnormal_learners,
        )

        return {
            "metrics": {
                "total_flows": int(summary.get("total_flows") or 0),
                "total_bytes": int(summary.get("total_bytes") or 0),
                "protocol_count": int(summary.get("protocol_count") or 0),
                "risk_learner_count": len(risk_names),
                "risk_type_count": risk_type_count,
                "risk_ip_count": int(summary.get("risk_ip_count") or 0),
            },
            "traffic_distribution": [
                {"name": "正常流量", "value": int(summary.get("normal_bytes") or 0)},
                {"name": "疑似异常流量", "value": int(summary.get("risk_bytes") or 0)},
            ],
            "protocol_distribution": transport_protocol_distribution,
            "application_protocol_distribution": application_protocol_distribution,
            "runtime": {
                "session_id": sid,
                "current_window_index": int(summary.get("current_window_index") or 0),
                "redis_pending": _safe_int(lambda: self.redis.pending_count()) if self.redis else 0,
                "consumed_flow_count": int(summary.get("total_flows") or 0),
            },
        }

    def overview_metrics(self, *, time_range: str = "24h") -> dict[str, Any]:
        bounds = self.time_range_bounds(time_range)
        overview = self.dashboard_overview(
            time_from=bounds["time_from"],
            time_to=bounds["time_to"],
        )
        metrics = overview["metrics"]
        return {
            "totalTraffic": int(metrics["total_bytes"]),
            "protocolCount": int(metrics["protocol_count"]),
            "riskTypeCount": int(metrics["risk_type_count"]),
            "suspiciousIpCount": int(metrics["risk_ip_count"]),
        }

    def overview_distributions(self, *, time_range: str = "24h") -> dict[str, Any]:
        bounds = self.time_range_bounds(time_range)
        overview = self.dashboard_overview(
            time_from=bounds["time_from"],
            time_to=bounds["time_to"],
        )
        return {
            "traffic": overview["traffic_distribution"],
            "protocol": overview["protocol_distribution"],
            "applicationProtocol": overview["application_protocol_distribution"],
        }

    def overview_traffic_trend(self, *, time_range: str = "24h") -> list[dict[str, Any]]:
        sid = self.session_id
        spec = _traffic_trend_spec(time_range, display_tz=self.display_tz)
        learner_rows = self.learners.list_learners(session_id=sid)
        risk_names = _risk_learner_names(learner_rows)
        rows = self.flows.traffic_trend(
            session_id=sid,
            risk_learners=risk_names,
            bucket=spec["bucket"],
            time_from=spec["time_from"],
            time_to=spec["time_to"],
        )
        if spec.get("aggregate_rolling_weeks"):
            by_bucket = _aggregate_rolling_week_traffic(rows, spec["buckets"], display_tz=self.display_tz)
        else:
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
                display_tz=self.display_tz,
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
                    display_tz=self.display_tz,
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
                    display_tz=self.display_tz,
                )
            )
        return {"items": items, "total": int(result["total"])}

    def dashboard_topology(
        self,
        *,
        session_id: str | None = None,
        top_n: int = TOPOLOGY_TOP_VICTIMS_DEFAULT,
        time_from: str | None = None,
        time_to: str | None = None,
        node_mode: str = "host",
    ) -> dict[str, Any]:
        sid = session_id or self.session_id
        learner_rows = self.learners.list_learners(session_id=sid)
        risk_names = _risk_learner_names(learner_rows)
        top_victims = max(1, min(int(top_n), 500))
        requested_mode = node_mode if node_mode in {"host", "endpoint", "both"} else "host"
        load_host = requested_mode in {"host", "both"}
        load_endpoint = requested_mode in {"endpoint", "both"}
        default_node_mode = "endpoint" if requested_mode == "endpoint" else "host"

        def _graph(
            *,
            node_mode: str,
            traffic_kind: str,
            edges_per_victim: int,
            top_victims_count: int | None = None,
        ) -> dict[str, Any]:
            return self.flows.topology_graph(
                session_id=sid,
                node_mode=node_mode,
                risk_learners=risk_names,
                traffic_kind=traffic_kind,
                time_from=time_from,
                time_to=time_to,
                top_n=top_victims_count if top_victims_count is not None else top_victims,
                edges_per_victim=edges_per_victim,
            )

        if hasattr(self.flows, "dashboard_topology_graphs"):
            host_graphs = (
                self.flows.dashboard_topology_graphs(
                    session_id=sid,
                    node_mode="host",
                    risk_learners=risk_names,
                    time_from=time_from,
                    time_to=time_to,
                    main_top_n=TOPOLOGY_TOP_VICTIMS_DASHBOARD_MAIN,
                    compact_top_n=top_victims,
                    main_edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_MAIN,
                    compact_edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_COMPACT,
                )
                if load_host
                else _empty_topology_graphs("host")
            )
            endpoint_graphs = (
                self.flows.dashboard_topology_graphs(
                    session_id=sid,
                    node_mode="endpoint",
                    risk_learners=risk_names,
                    time_from=time_from,
                    time_to=time_to,
                    main_top_n=TOPOLOGY_TOP_VICTIMS_DASHBOARD_MAIN,
                    compact_top_n=top_victims,
                    main_edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_MAIN,
                    compact_edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_COMPACT,
                )
                if load_endpoint
                else _empty_topology_graphs("endpoint")
            )
            if hasattr(self.flows, "dashboard_topology_stats"):
                stats_by_kind = self.flows.dashboard_topology_stats(
                    session_id=sid,
                    risk_learners=risk_names,
                    time_from=time_from,
                    time_to=time_to,
                    approximate=True,
                )
                if load_host:
                    _merge_dashboard_topology_stats(host_graphs, stats_by_kind)
                if load_endpoint:
                    _merge_dashboard_topology_stats(endpoint_graphs, stats_by_kind)
            views = {
                "__combined__": _topology_view(
                    label="总流量",
                    host=host_graphs["combined"],
                    endpoint=endpoint_graphs["combined"],
                    is_benign=None,
                ),
                "__benign__": _topology_view(
                    label="良性流量",
                    host=host_graphs["benign"],
                    endpoint=endpoint_graphs["benign"],
                    is_benign=True,
                ),
                "__attack__": _topology_view(
                    label="攻击流量",
                    host=host_graphs["attack"],
                    endpoint=endpoint_graphs["attack"],
                    is_benign=False,
                ),
            }
            total_graph = endpoint_graphs["combined"] if requested_mode == "endpoint" else host_graphs["combined"]
            return {
                "version": 1,
                "total_flows": int(total_graph.get("flow_count") or 0),
                "labels": ["__combined__", "__benign__", "__attack__"],
                "default_label": "__combined__",
                "default_node_mode": default_node_mode,
                "aggregate_views": ["__combined__", "__benign__", "__attack__"],
                "views": views,
            }

        views = {
            "__combined__": _topology_view(
                label="总流量",
                host=(
                    _graph(
                        node_mode="host",
                        traffic_kind="combined",
                        edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_MAIN,
                        top_victims_count=TOPOLOGY_TOP_VICTIMS_DASHBOARD_MAIN,
                    )
                    if load_host
                    else _empty_graph("host")
                ),
                endpoint=(
                    _graph(
                        node_mode="endpoint",
                        traffic_kind="combined",
                        edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_MAIN,
                        top_victims_count=TOPOLOGY_TOP_VICTIMS_DASHBOARD_MAIN,
                    )
                    if load_endpoint
                    else _empty_graph("endpoint")
                ),
                is_benign=None,
            ),
            "__benign__": _topology_view(
                label="良性流量",
                host=(
                    _graph(node_mode="host", traffic_kind="benign", edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_COMPACT)
                    if load_host
                    else _empty_graph("host")
                ),
                endpoint=(
                    _graph(node_mode="endpoint", traffic_kind="benign", edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_COMPACT)
                    if load_endpoint
                    else _empty_graph("endpoint")
                ),
                is_benign=True,
            ),
            "__attack__": _topology_view(
                label="攻击流量",
                host=(
                    _graph(node_mode="host", traffic_kind="attack", edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_COMPACT)
                    if load_host
                    else _empty_graph("host")
                ),
                endpoint=(
                    _graph(node_mode="endpoint", traffic_kind="attack", edges_per_victim=TOPOLOGY_EDGES_DASHBOARD_COMPACT)
                    if load_endpoint
                    else _empty_graph("endpoint")
                ),
                is_benign=False,
            ),
        }
        total_graph = views["__combined__"]["endpoint"] if requested_mode == "endpoint" else views["__combined__"]["host"]
        return {
            "version": 1,
            "total_flows": int(total_graph.get("flow_count") or 0),
            "labels": ["__combined__", "__benign__", "__attack__"],
            "default_label": "__combined__",
            "default_node_mode": default_node_mode,
            "aggregate_views": ["__combined__", "__benign__", "__attack__"],
            "views": views,
        }

    def learner_topology(
        self,
        *,
        learner_name: str,
        session_id: str | None = None,
        subject_ip: str | None = None,
        top_n: int = TOPOLOGY_TOP_VICTIMS_DEFAULT,
        edges_per_victim: int = TOPOLOGY_EDGES_LEARNER_DETAIL,
        trigger_stats: dict[str, Any] | None = None,
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
                display_tz=self.display_tz,
            )
            if learner
            else _empty_event_item(learner_name)
        )
        primary_attack = _primary_attack_type(learner, session_baseline_learner=session_baseline)
        is_benign = primary_attack == "BENIGN_NORMAL"
        traffic_kind = "benign" if is_benign else "attack"
        topology_risk_learners = [] if is_benign else [learner_name]
        last_trigger_time = self._fmt((trigger_stats or {}).get("last_trigger_time")) or event["trigger_time"]
        first_trigger_time = self._fmt((trigger_stats or {}).get("first_trigger_time")) or last_trigger_time
        trigger_count = int((trigger_stats or {}).get("trigger_count") or event["flow_count"] or 0)
        if hasattr(self.flows, "topology_graph_pair"):
            graphs = self.flows.topology_graph_pair(
                session_id=sid,
                risk_learners=topology_risk_learners,
                learner_name=learner_name,
                subject_ip=subject_ip,
                traffic_kind=traffic_kind,
                top_n=top_n,
                edges_per_victim=edges_per_victim,
            )
        else:
            graphs = {
                "host": self.flows.topology_graph(
                    session_id=sid,
                    node_mode="host",
                    risk_learners=topology_risk_learners,
                    learner_name=learner_name,
                    subject_ip=subject_ip,
                    traffic_kind=traffic_kind,
                    top_n=top_n,
                    edges_per_victim=edges_per_victim,
                ),
                "endpoint": self.flows.topology_graph(
                    session_id=sid,
                    node_mode="endpoint",
                    risk_learners=topology_risk_learners,
                    learner_name=learner_name,
                    subject_ip=subject_ip,
                    traffic_kind=traffic_kind,
                    top_n=top_n,
                    edges_per_victim=edges_per_victim,
                ),
            }
        view = {
            "learner": learner_name,
            "risk_id": event["risk_id"],
            "risk_name": event["risk_name"],
            "risk_description": event["risk_description"],
            "trigger_time": last_trigger_time,
            "first_trigger_time": first_trigger_time,
            "last_trigger_time": last_trigger_time,
            "trigger_count": trigger_count,
            "attack_ratio": event["attack_ratio"],
            "dominant_label": event["dominant_label"],
            "dominant_ratio": event["risk_score"],
            "is_benign": is_benign,
            "host": graphs["host"],
            "endpoint": graphs["endpoint"],
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

    def risk_attack_types(
        self,
        *,
        scope: str = "event",
        include_count: bool = False,
    ) -> dict[str, Any]:
        scope_key = str(scope or "event").strip().lower()
        exclude = (
            EVENT_SCOPE_EXCLUDED_ATTACK_TYPES
            if scope_key == "event"
            else frozenset()
        )
        rows = self.learners.list_learners(session_id=self.session_id)
        counts = _attack_type_event_counts(rows)
        if scope_key == "event":
            codes = [
                code
                for code in ATTACK_TYPE_DISPLAY
                if code not in exclude and int(counts.get(code, 0)) > 0
            ]
        else:
            codes = [code for code in ATTACK_TYPE_DISPLAY if code not in exclude]
        items: list[dict[str, Any]] = []
        for code in codes:
            display = _attack_display(code)
            items.append(
                {
                    "code": code,
                    "name": display["name"],
                    "category": display.get("category", ""),
                    "desc": display["desc"],
                }
            )
        if include_count:
            for item in items:
                item["count"] = int(counts.get(str(item["code"]) or "", 0))
        return {"items": items}

    def risk_events_topology(
        self,
        *,
        name: str | None = None,
        attack_types: list[str] | None = None,
        trigger_start: str | None = None,
        trigger_end: str | None = None,
        top_n: int = TOPOLOGY_TOP_VICTIMS_DEFAULT,
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
            attack_types=attack_types,
            risk_band=None,
            time_from=time_from,
            time_to=time_to,
            include_all_bands=False,
            display_sequence_by_name=display_sequence_by_name,
            session_baseline_learner=session_baseline,
            display_tz=self.display_tz,
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
        page_learner_names = [str(row.get("learner_name") or "") for row in page_rows if row.get("learner_name")]
        trigger_stats_by_learner = (
            self.flows.learner_trigger_stats(session_id=sid, learner_names=page_learner_names)
            if hasattr(self.flows, "learner_trigger_stats")
            else {}
        )
        views: dict[str, Any] = {}
        learners: list[str] = []
        for row in page_rows:
            learner_name = str(row.get("learner_name") or "")
            if not learner_name:
                continue
            topology = self.learner_topology(
                learner_name=learner_name,
                top_n=top_n,
                edges_per_victim=TOPOLOGY_EDGES_GRID,
                trigger_stats=trigger_stats_by_learner.get(learner_name),
            )
            view = topology["views"][learner_name]
            learners.append(learner_name)
            views[learner_name] = view
        if page_learner_names and hasattr(self.flows, "learner_topology_stats"):
            stats_by_learner = self.flows.learner_topology_stats(
                session_id=sid,
                learner_names=page_learner_names,
                approximate=True,
            )
            _merge_learner_topology_stats(views, stats_by_learner)
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
            display_tz=self.display_tz,
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
        trigger_stats = (
            self.flows.learner_trigger_stats(
                session_id=self.session_id,
                learner_names=[learner_name],
            ).get(learner_name, {})
            if learner_name and hasattr(self.flows, "learner_trigger_stats")
            else {}
        )
        last_trigger_time = (
            self._fmt((trigger_stats or {}).get("last_trigger_time"))
            or item.get("triggerTime")
            or "-"
        )
        first_trigger_time = (
            self._fmt((trigger_stats or {}).get("first_trigger_time"))
            or last_trigger_time
        )
        trigger_count = int(
            (trigger_stats or {}).get("trigger_count")
            or learner.get("flow_count")
            or 0
        )
        item["triggerTime"] = last_trigger_time
        item["firstTriggerTime"] = first_trigger_time
        item["lastTriggerTime"] = last_trigger_time
        item["triggerCount"] = trigger_count
        return item

    def risk_network_topology(self, *, risk_id: int, top_n: int = 50) -> dict[str, Any]:
        learner = self.learners.get_learner_by_id(session_id=self.session_id, learner_id=risk_id) or {}
        learner_name = str(learner.get("learner_name") or "")
        if not learner_name:
            return _empty_dataset_topology()
        topology = self.learner_topology(learner_name=learner_name, top_n=top_n)
        view = topology["views"][learner_name]
        if hasattr(self.flows, "learner_topology_stats"):
            stats_by_learner = self.flows.learner_topology_stats(
                session_id=self.session_id,
                learner_names=[learner_name],
                approximate=True,
            )
            _merge_learner_topology_stats({learner_name: view}, stats_by_learner)
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
                    "is_benign": view.get("is_benign"),
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
        items = [_traffic_log_item(row, display_tz=self.display_tz) for row in flows["items"]]
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
            topology = self.learner_topology(
                learner_name=learner_name,
                subject_ip=ip,
                top_n=top_n,
            )
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
        items = [_traffic_log_item(row, display_tz=self.display_tz) for row in flows["items"]]
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


def _parse_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text or text in {"[]"}:
        return []
    return [text]


def _risk_type_count_from_active_learners(
    learner_rows: list[dict[str, Any]],
    active_learner_names: list[str],
) -> int:
    learner_by_name = {
        str(row.get("learner_name") or ""): row
        for row in learner_rows
        if str(row.get("learner_name") or "")
    }
    names: set[str] = set()
    for learner_name in active_learner_names:
        row = learner_by_name.get(learner_name)
        if not row or not _is_attack_learner(row):
            continue
        display = _attack_display(_rule_attack_type(row))
        name = str(display.get("name") or "").strip()
        if name:
            names.add(name)
    return len(names)


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


def _normalize_attack_type_codes(raw: list[str] | None) -> set[str] | None:
    if not raw:
        return None
    codes: set[str] = set()
    for item in raw:
        for part in str(item or "").split(","):
            code = part.strip().upper()
            if code:
                codes.add(code)
    return codes or None


def _attack_type_event_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if not _is_attack_learner(row) or int(row.get("flow_count") or 0) <= 0:
            continue
        attack_type = _rule_attack_type(row)
        if not attack_type or attack_type == "BENIGN_NORMAL":
            continue
        counts[attack_type] = counts.get(attack_type, 0) + 1
    return counts


def _filter_learner_rows(
    rows: list[dict[str, Any]],
    *,
    name: str | None,
    attack_types: list[str] | None = None,
    risk_band: str | None,
    time_from: str | None,
    time_to: str | None,
    include_all_bands: bool = False,
    display_sequence_by_name: dict[str, int] | None = None,
    session_baseline_learner: str | None = None,
    display_tz: ZoneInfo,
) -> list[dict[str, Any]]:
    time_from = _clean_trigger_bound(time_from)
    time_to = _clean_trigger_bound(time_to)
    filtered = []
    name_text = (name or "").strip().lower()
    band_text = (risk_band or "").strip().lower()
    attack_type_codes = _normalize_attack_type_codes(attack_types)
    for row in rows:
        row_band = str(row.get("risk_band") or "").lower()
        if band_text:
            if row_band != band_text:
                continue
        elif not include_all_bands and not _is_attack_learner(row):
            continue
        if attack_type_codes:
            row_attack = _rule_attack_type(row).upper()
            if row_attack not in attack_type_codes:
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
        seen_text = format_display_time(seen, display_tz)
        if time_from and seen_text and seen_text < time_from:
            continue
        if time_to and seen_text and seen_text > time_to:
            continue
        filtered.append(row)
    return sorted(
        filtered,
        key=lambda row: (
            -_float(row.get("risk_score")),
            format_display_time(row.get("last_seen_at"), display_tz),
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
    display_tz: ZoneInfo,
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
        "risk_category": display.get("category", ""),
        "risk_description": risk_description,
        "trigger_time": format_display_time(row.get("last_seen_at"), display_tz) or "-",
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


def _merge_dashboard_topology_stats(
    graphs: dict[str, dict[str, Any]],
    stats_by_kind: dict[str, dict[str, Any]],
) -> None:
    for kind, graph in graphs.items():
        stats = stats_by_kind.get(kind)
        if not stats:
            continue
        graph_stats = dict(graph.get("stats") or {})
        graph_stats.update(stats)
        graph["stats"] = graph_stats
        total_flow_count = int(stats.get("total_flow_count") or 0)
        graph["flow_count"] = total_flow_count
        graph["total_flow_count"] = total_flow_count


def _merge_learner_topology_stats(
    views: dict[str, dict[str, Any]],
    stats_by_learner: dict[str, dict[str, Any]],
) -> None:
    for learner_name, view in views.items():
        stats = stats_by_learner.get(learner_name)
        if not stats:
            continue
        total_flow_count = int(stats.get("total_flow_count") or 0)
        for graph_key in ("host", "endpoint"):
            graph = view.get(graph_key)
            if not isinstance(graph, dict):
                continue
            graph_stats = dict(graph.get("stats") or {})
            graph_stats.update(stats)
            graph["stats"] = graph_stats
            if total_flow_count:
                graph["flow_count"] = total_flow_count
                graph["total_flow_count"] = total_flow_count


def _risk_ip_item(
    row: dict[str, Any],
    learner: dict[str, Any] | None,
    *,
    is_risk_learner: bool,
    display_sequence_by_name: dict[str, int] | None = None,
    display_tz: ZoneInfo,
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
        "triggerTime": format_display_time(row.get("trigger_time"), display_tz) or "-",
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


def _compact_application_protocol_distribution(
    rows: list[dict[str, Any]],
    *,
    visible: int = 11,
) -> list[dict[str, Any]]:
    totals: dict[str, int] = {}
    for row in rows:
        count = int(row.get("value") or 0)
        if count <= 0:
            continue
        name = _application_protocol_name(row.get("protocol"))
        totals[name] = totals.get(name, 0) + count

    sorted_items = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    if len(sorted_items) <= visible:
        return [{"name": name, "value": value} for name, value in sorted_items]

    visible_items = sorted_items[: max(0, visible - 1)]
    other_value = sum(value for _, value in sorted_items[max(0, visible - 1):])
    return [
        *[{"name": name, "value": value} for name, value in visible_items],
        {"name": "其他", "value": other_value},
    ]


def _application_protocol_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "UNKNOWN"
    lowered = text.lower()
    if lowered in {"unknown", "none", "-"}:
        return "UNKNOWN"
    return text.upper()


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


def _call_protocol_distribution(
    flows: Any,
    *,
    method_name: str,
    fallback_name: str,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    method = getattr(flows, method_name, None)
    if method is None:
        method = getattr(flows, fallback_name)
    return method(**kwargs)


def _format_time(value: Any, *, display_tz: ZoneInfo) -> str:
    return format_display_time(value, display_tz)


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


def _time_range_bounds(value: str, *, display_tz: ZoneInfo) -> dict[str, str]:
    """Canonical overview window; shared by metrics, distributions, topology, and traffic trend."""
    now_local = datetime.now(display_tz)
    current_hour = now_local.replace(minute=0, second=0, microsecond=0)
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if value == "7d":
        start = today - timedelta(days=6)
    elif value == "30d":
        first_day = today - timedelta(days=29)
        start = first_day - timedelta(days=first_day.weekday())
    else:
        start = current_hour - timedelta(hours=23)

    return {"time_from": to_utc_iso(start), "time_to": to_utc_iso(now_local)}


def _time_range_start(value: str, *, display_tz: ZoneInfo) -> str | None:
    return _time_range_bounds(value, display_tz=display_tz)["time_from"]


def _traffic_trend_spec(value: str, *, display_tz: ZoneInfo) -> dict[str, Any]:
    bounds = _time_range_bounds(value, display_tz=display_tz)
    now_local = datetime.now(display_tz)
    current_hour = now_local.replace(minute=0, second=0, microsecond=0)
    today = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if value == "7d":
        start = today - timedelta(days=6)
        buckets = [
            {
                "key": bucket_key(start + timedelta(days=index), display_tz),
                "label": (start + timedelta(days=index)).strftime("%m-%d"),
            }
            for index in range(7)
        ]
        return {
            "bucket": "day",
            "time_from": bounds["time_from"],
            "time_to": bounds["time_to"],
            "buckets": buckets,
        }

    if value == "30d":
        week_count = 4
        buckets = _rolling_week_buckets(today, week_count=week_count, display_tz=display_tz)
        oldest_week_start = buckets[0]["week_start"]
        return {
            "bucket": "day",
            "time_from": to_utc_iso(oldest_week_start),
            "time_to": bounds["time_to"],
            "buckets": buckets,
            "aggregate_rolling_weeks": True,
        }

    start = current_hour - timedelta(hours=23)
    buckets = [
        {
            "key": bucket_key(start + timedelta(hours=index), display_tz),
            "label": (start + timedelta(hours=index)).strftime("%H:00"),
        }
        for index in range(24)
    ]
    return {
        "bucket": "hour",
        "time_from": bounds["time_from"],
        "time_to": bounds["time_to"],
        "buckets": buckets,
    }


def _format_chart_date_range(start: datetime, end: datetime, *, display_tz: ZoneInfo) -> str:
    """Chart x-axis label for weekly buckets, e.g. 05-01~05-07."""
    start_day = start.astimezone(display_tz)
    end_day = end.astimezone(display_tz)
    return f"{start_day.strftime('%m-%d')}~{end_day.strftime('%m-%d')}"


def _rolling_week_buckets(
    today: datetime,
    *,
    week_count: int = 4,
    display_tz: ZoneInfo,
) -> list[dict[str, Any]]:
    """Rolling 7-day windows ending at today; oldest bucket first."""
    buckets: list[dict[str, Any]] = []
    for index in range(week_count):
        week_end = today - timedelta(days=(week_count - 1 - index) * 7)
        week_start = week_end - timedelta(days=6)
        buckets.append(
            {
                "key": bucket_key(week_start, display_tz),
                "label": _format_chart_date_range(week_start, week_end, display_tz=display_tz),
                "week_start": week_start,
                "week_end": week_end,
            }
        )
    return buckets


def _aggregate_rolling_week_traffic(
    rows: list[dict[str, Any]],
    buckets: list[dict[str, Any]],
    *,
    display_tz: ZoneInfo,
) -> dict[str, dict[str, int]]:
    totals = {
        str(item["key"]): {"normal": 0, "abnormal": 0}
        for item in buckets
    }
    for row in rows:
        bucket_start = parse_bucket_start(row.get("bucket_start"), display_tz=display_tz)
        if bucket_start is None:
            continue
        for item in buckets:
            week_start = item["week_start"]
            week_end = item["week_end"]
            if week_start <= bucket_start <= week_end:
                key = str(item["key"])
                totals[key]["normal"] += int(row.get("normal") or 0)
                totals[key]["abnormal"] += int(row.get("abnormal") or 0)
                break
    return totals


def _risk_item_from_learner(
    learner: dict[str, Any],
    *,
    subject_ip: str = "",
    include_count: bool = False,
    display_sequence_by_name: dict[str, int] | None = None,
    display_tz: ZoneInfo,
) -> dict[str, Any]:
    display = _display_for_learner(learner, display_sequence_by_name=display_sequence_by_name)
    item = {
        "id": int(learner.get("id") or 0),
        "subjectIp": subject_ip or "-",
        "name": display["name"],
        "triggerTime": format_display_time(learner.get("last_seen_at"), display_tz) or "-",
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


def _traffic_log_item(row: dict[str, Any], *, display_tz: ZoneInfo) -> dict[str, Any]:
    src_port = row.get("src_port")
    dst_port = row.get("dst_port")
    return {
        "id": str(row.get("flow_uid") or row.get("mq_message_id") or ""),
        "srcIp": str(row.get("src_ip") or ""),
        "srcPort": int(src_port) if src_port is not None else 0,
        "dstIp": str(row.get("dst_ip") or ""),
        "dstPort": int(dst_port) if dst_port is not None else 0,
        "accessTime": format_display_time(row.get("event_time"), display_tz) or "-",
        "traffic": int(row.get("total_bytes") or 0),
        "protocol": resolve_flow_protocol_from_row(row),
    }


def _empty_graph(node_mode: str = "host") -> dict[str, Any]:
    return {"flow_count": 0, "total_flow_count": 0, "node_mode": node_mode, "nodes": [], "links": [], "stats": {}}


def _empty_topology_graphs(node_mode: str) -> dict[str, dict[str, Any]]:
    return {
        "combined": _empty_graph(node_mode),
        "benign": _empty_graph(node_mode),
        "attack": _empty_graph(node_mode),
    }


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
