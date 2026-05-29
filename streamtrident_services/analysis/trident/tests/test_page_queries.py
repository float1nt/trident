from __future__ import annotations

import copy
from typing import Any

from app.page_queries import PageQueryService, _compact_protocol_distribution, _protocol_distribution_bucket


class FakeFlows:
    def dashboard_summary(self, **_: Any) -> dict[str, Any]:
        return {
            "total_flows": 10,
            "total_bytes": 10000,
            "protocol_count": 2,
            "normal_flows": 7,
            "risk_flows": 3,
            "normal_bytes": 7000,
            "risk_bytes": 3000,
            "risk_ip_count": 2,
            "current_window_index": 4,
        }

    def protocol_distribution(self, **_: Any) -> list[dict[str, Any]]:
        return [{"protocol": "tls", "value": 8}, {"protocol": "dns", "value": 2}]

    def traffic_trend(self, **_: Any) -> list[dict[str, Any]]:
        return []

    def top_subject_ips_by_learner(self, **_: Any) -> dict[str, list[str]]:
        return {"NEW_1": ["10.0.0.8"]}

    def risk_ip_view(self, **_: Any) -> dict[str, Any]:
        return {
            "total": 1,
            "items": [
                {
                    "subject_ip": "10.0.0.8",
                    "assigned_learner": "NEW_1",
                    "trigger_time": "2026-05-27 10:00:00",
                    "flow_count": 20,
                    "unknown_count": 3,
                    "top_dst_ip": "203.0.113.17",
                    "top_dst_port": 443,
                    "top_protocol": "tls",
                }
            ],
        }

    def learner_trigger_stats(self, **_: Any) -> dict[str, dict[str, Any]]:
        return {
            "NEW_1": {
                "assigned_learner": "NEW_1",
                "first_trigger_time": "2026-05-27 09:30:00",
                "last_trigger_time": "2026-05-27 10:05:00",
                "trigger_count": 21,
            }
        }


class FakeLearners:
    def list_learners(self, **_: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": 11,
                "learner_name": "NEW_1",
                "risk_score": 0.82,
                "risk_band": "high",
                "risk_reason": "concentration=0.82",
                "last_seen_at": "2026-05-27T10:00:00Z",
                "flow_count": 20,
                "rule_json": {
                    "attack_types": [
                        {"attack_type": "DDOS_VICTIM", "confidence": 0.82},
                    ]
                },
            },
            {
                "id": 12,
                "learner_name": "BASELINE_0",
                "risk_score": 0.1,
                "risk_band": "low",
                "risk_reason": "baseline",
                "last_seen_at": "2026-05-27T09:00:00Z",
                "flow_count": 80,
            },
        ]


def test_dashboard_overview_maps_database_rows_to_page_shape() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.dashboard_overview()

    assert data["metrics"]["total_flows"] == 10
    assert data["metrics"]["total_bytes"] == 10000
    assert data["metrics"]["risk_learner_count"] == 1
    assert data["metrics"]["risk_type_count"] == 1
    assert data["traffic_distribution"][1] == {"name": "疑似异常流量", "value": 3000}
    assert data["protocol_distribution"] == [{"name": "其他", "value": 10}]


def test_overview_metrics_reports_total_traffic_bytes() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.overview_metrics()

    assert data["totalTraffic"] == 10000


def test_overview_metrics_reports_distinct_risk_type_count() -> None:
    class MultiLearners(FakeLearners):
        def list_learners(self, **_: Any) -> list[dict[str, Any]]:
            base = FakeLearners().list_learners()[0]
            same_type = copy.deepcopy(base)
            same_type["id"] = 13
            same_type["learner_name"] = "NEW_2"
            other_type = copy.deepcopy(base)
            other_type["id"] = 14
            other_type["learner_name"] = "NEW_3"
            other_type["rule_json"] = {
                "attack_types": [
                    {"attack_type": "PORT_SCAN", "confidence": 0.75},
                ]
            }
            baseline = FakeLearners().list_learners()[1]
            return [base, same_type, other_type, baseline]

    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=MultiLearners())

    data = service.overview_metrics()

    assert data["riskTypeCount"] == 2


def test_overview_traffic_trend_returns_filled_buckets() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.overview_traffic_trend(time_range="24h")

    assert len(data) == 24
    assert set(data[0]) == {"label", "normal", "abnormal"}
    assert sum(item["normal"] + item["abnormal"] for item in data) == 0


def test_overview_traffic_trend_30d_uses_date_range_labels() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.overview_traffic_trend(time_range="30d")

    assert len(data) >= 4
    assert all("~" in item["label"] for item in data)
    assert all(len(item["label"].split("~")) == 2 for item in data)


def test_risk_events_default_to_attack_type_learners() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.risk_events()

    assert data["total"] == 1
    assert data["items"][0]["learner_name"] == "NEW_1"
    assert data["items"][0]["risk_name"] == "DDoS攻击"
    assert data["items"][0]["risk_description"].startswith("海量分布式源IP")
    assert data["items"][0]["subject_ips"] == ["10.0.0.8"]


def test_risk_events_topology_includes_attack_type_learners_only() -> None:
    class TopologyFlows(FakeFlows):
        def topology_graph(self, **_: Any) -> dict[str, Any]:
            return {"flow_count": 1, "node_mode": "host", "nodes": [], "links": [], "stats": {}}

    class TopologyLearners(FakeLearners):
        def get_learner(self, **_: Any) -> dict[str, Any]:
            return FakeLearners().list_learners()[0]

    service = PageQueryService(session_id="s1", flows=TopologyFlows(), learners=TopologyLearners())
    data = service.risk_events_topology()

    assert data["total"] == 1
    assert data["risk_type_total"] == 1
    assert data["risk_ip_count"] == 1
    assert data["learners"] == ["NEW_1"]
    view = data["views"]["NEW_1"]
    assert view["trigger_time"] == "2026-05-27 10:05:00"
    assert view["first_trigger_time"] == "2026-05-27 09:30:00"
    assert view["last_trigger_time"] == "2026-05-27 10:05:00"
    assert view["trigger_count"] == 21

    page = service.risk_events_topology(limit=1, offset=0)
    assert page["total"] == 1
    assert page["risk_type_total"] == 1
    assert len(page["learners"]) == 1
    assert page["learners"][0] == "NEW_1"


def test_risk_events_topology_distinguishes_risk_types_and_events() -> None:
    class TopologyFlows(FakeFlows):
        def topology_graph(self, **_: Any) -> dict[str, Any]:
            return {"flow_count": 1, "node_mode": "host", "nodes": [], "links": [], "stats": {}}

        def risk_ip_view(self, **_: Any) -> dict[str, Any]:
            return {"total": 3, "items": []}

    class MultiLearners(FakeLearners):
        def list_learners(self, **_: Any) -> list[dict[str, Any]]:
            base = FakeLearners().list_learners()[0]
            second = copy.deepcopy(base)
            second["id"] = 13
            second["learner_name"] = "NEW_2"
            third = copy.deepcopy(base)
            third["id"] = 14
            third["learner_name"] = "NEW_3"
            third["rule_json"] = {
                "attack_types": [
                    {"attack_type": "PORT_SCAN", "confidence": 0.75},
                ]
            }
            return [base, second, third]

        def get_learner(self, **kwargs: Any) -> dict[str, Any]:
            name = str(kwargs.get("learner_name") or "")
            for row in self.list_learners():
                if str(row.get("learner_name") or "") == name:
                    return row
            return {}

    service = PageQueryService(session_id="s1", flows=TopologyFlows(), learners=MultiLearners())
    data = service.risk_events_topology()

    assert data["total"] == 3
    assert data["risk_type_total"] == 2
    assert data["risk_ip_count"] == 3


def test_risk_attack_types_event_scope_excludes_benign() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.risk_attack_types(scope="event")

    codes = {item["code"] for item in data["items"]}
    assert "BENIGN_NORMAL" not in codes
    assert "DDOS_VICTIM" in codes
    assert "PORT_SCAN" not in codes
    assert data["items"][0]["name"]
    assert data["items"][0]["desc"]


def test_risk_attack_types_all_scope_returns_dictionary() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.risk_attack_types(scope="all")

    codes = {item["code"] for item in data["items"]}
    assert "BENIGN_NORMAL" in codes
    assert "DDOS_VICTIM" in codes
    assert "PORT_SCAN" in codes


def test_risk_attack_types_include_count() -> None:
    class TopologyFlows(FakeFlows):
        def topology_graph(self, **_: Any) -> dict[str, Any]:
            return {"flow_count": 1, "node_mode": "host", "nodes": [], "links": [], "stats": {}}

    class MultiLearners(FakeLearners):
        def list_learners(self, **_: Any) -> list[dict[str, Any]]:
            base = FakeLearners().list_learners()[0]
            second = copy.deepcopy(base)
            second["id"] = 13
            second["learner_name"] = "NEW_2"
            third = copy.deepcopy(base)
            third["id"] = 14
            third["learner_name"] = "NEW_3"
            third["rule_json"] = {
                "attack_types": [
                    {"attack_type": "PORT_SCAN", "confidence": 0.75},
                ]
            }
            return [base, second, third]

    service = PageQueryService(session_id="s1", flows=TopologyFlows(), learners=MultiLearners())
    data = service.risk_attack_types(scope="event", include_count=True)
    by_code = {item["code"]: item.get("count", 0) for item in data["items"]}

    assert by_code["DDOS_VICTIM"] == 2
    assert by_code["PORT_SCAN"] == 1


def test_risk_attack_types_event_scope_includes_unnamed_learners() -> None:
    class UnknownLearners(FakeLearners):
        def list_learners(self, **_: Any) -> list[dict[str, Any]]:
            unnamed = copy.deepcopy(FakeLearners().list_learners()[0])
            unnamed["id"] = 15
            unnamed["learner_name"] = "NEW_UNKNOWN"
            unnamed["rule_json"] = {
                "attack_types": [
                    {"attack_type": "UNKNOWN_SUSPECTED", "confidence": 0.35},
                ]
            }
            return [unnamed, FakeLearners().list_learners()[1]]

    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=UnknownLearners())

    data = service.risk_attack_types(scope="event", include_count=True)
    by_code = {item["code"]: item for item in data["items"]}

    assert set(by_code) == {"UNKNOWN_SUSPECTED"}
    assert by_code["UNKNOWN_SUSPECTED"]["name"] == "未命名攻击"
    assert by_code["UNKNOWN_SUSPECTED"]["count"] == 1


def test_risk_events_topology_filters_by_attack_types() -> None:
    class TopologyFlows(FakeFlows):
        def topology_graph(self, **_: Any) -> dict[str, Any]:
            return {"flow_count": 1, "node_mode": "host", "nodes": [], "links": [], "stats": {}}

        def risk_ip_view(self, **_: Any) -> dict[str, Any]:
            return {"total": 1, "items": []}

    class MultiLearners(FakeLearners):
        def list_learners(self, **_: Any) -> list[dict[str, Any]]:
            base = FakeLearners().list_learners()[0]
            second = copy.deepcopy(base)
            second["id"] = 13
            second["learner_name"] = "NEW_2"
            third = copy.deepcopy(base)
            third["id"] = 14
            third["learner_name"] = "NEW_3"
            third["rule_json"] = {
                "attack_types": [
                    {"attack_type": "PORT_SCAN", "confidence": 0.75},
                ]
            }
            return [base, second, third]

        def get_learner(self, **kwargs: Any) -> dict[str, Any]:
            name = str(kwargs.get("learner_name") or "")
            for row in self.list_learners():
                if str(row.get("learner_name") or "") == name:
                    return row
            return {}

    service = PageQueryService(session_id="s1", flows=TopologyFlows(), learners=MultiLearners())

    single = service.risk_events_topology(attack_types=["PORT_SCAN"])
    assert single["total"] == 1
    assert single["learners"] == ["NEW_3"]

    multi = service.risk_events_topology(attack_types=["PORT_SCAN", "DDOS_VICTIM"])
    assert multi["total"] == 3

    comma = service.risk_events_topology(attack_types=["PORT_SCAN,DDOS_VICTIM"])
    assert comma["total"] == 3


def test_risk_events_topology_filters_by_display_name_not_learner_name() -> None:
    class TopologyFlows(FakeFlows):
        def topology_graph(self, **_: Any) -> dict[str, Any]:
            return {"flow_count": 1, "node_mode": "host", "nodes": [], "links": [], "stats": {}}

        def risk_ip_view(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs.get("learner_name_like") is None
            return {"total": 1, "items": []}

    class MultiLearners(FakeLearners):
        def list_learners(self, **_: Any) -> list[dict[str, Any]]:
            baseline = FakeLearners().list_learners()[1]
            first = copy.deepcopy(FakeLearners().list_learners()[0])
            first["id"] = 21
            first["learner_name"] = "NEW_2"
            second = copy.deepcopy(first)
            second["id"] = 22
            second["learner_name"] = "NEW_3"
            return [baseline, first, second]

        def get_learner(self, **kwargs: Any) -> dict[str, Any]:
            name = str(kwargs.get("learner_name") or "")
            for row in self.list_learners():
                if str(row.get("learner_name") or "") == name:
                    return row
            return {}

    service = PageQueryService(session_id="s1", flows=TopologyFlows(), learners=MultiLearners())

    by_display = service.risk_events_topology(name="DDoS")
    assert by_display["total"] == 2
    assert set(by_display["learners"]) == {"NEW_2", "NEW_3"}

    by_learner_name = service.risk_events_topology(name="NEW_2")
    assert by_learner_name["total"] == 0

    by_numbered_display = service.risk_events_topology(name="DDoS攻击1")
    assert by_numbered_display["total"] == 1
    assert by_numbered_display["learners"] == ["NEW_2"]


def test_risk_traffic_logs_returns_total_with_items() -> None:
    class FlowListFakeFlows(FakeFlows):
        def list_flows(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "items": [
                    {
                        "flow_uid": "f-1",
                        "src_ip": "10.0.0.8",
                        "dst_ip": "203.0.113.17",
                        "src_port": 12345,
                        "dst_port": 443,
                        "event_time": "2026-05-27 10:00:00",
                        "total_bytes": 100,
                        "app_proto": "unknown",
                        "protocol": 6,
                    }
                ],
                "total": 42,
                "limit": kwargs.get("limit", 10),
                "offset": kwargs.get("offset", 0),
            }

    class FlowListLearners(FakeLearners):
        def get_learner_by_id(self, **_: Any) -> dict[str, Any]:
            return FakeLearners().list_learners()[0]

    service = PageQueryService(
        session_id="s1",
        flows=FlowListFakeFlows(),
        learners=FlowListLearners(),
    )

    data = service.risk_traffic_logs(risk_id=11, limit=10, offset=0)

    assert data["total"] == 42
    assert data["limit"] == 10
    assert data["offset"] == 0
    assert len(data["items"]) == 1
    assert data["items"][0]["protocol"] == "TCP"


def test_risk_ip_view_maps_aggregates_to_table_rows() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.risk_ip_view()

    assert data["total"] == 1
    assert data["items"][0]["subjectIp"] == "10.0.0.8"
    assert data["items"][0]["name"] == "DDoS攻击"
    assert data["items"][0]["id"] == 11
    assert "top_protocol=TLS" in data["items"][0]["description"]


def test_risk_ip_view_excludes_non_risk_unknown_learner() -> None:
    class UnknownFlows(FakeFlows):
        def risk_ip_view(self, **kwargs: Any) -> dict[str, Any]:
            assert "BASELINE_0" not in kwargs["risk_learners"]
            return {
                "total": 0,
                "items": [],
            }

    service = PageQueryService(session_id="s1", flows=UnknownFlows(), learners=FakeLearners())

    data = service.risk_ip_view()

    assert data["total"] == 0
    assert data["items"] == []


def test_risk_list_excludes_non_risk_unknown_learner() -> None:
    class UnknownFlows(FakeFlows):
        def risk_ip_view(self, **kwargs: Any) -> dict[str, Any]:
            assert "BASELINE_0" not in kwargs["risk_learners"]
            return {
                "total": 0,
                "items": [],
            }

    service = PageQueryService(session_id="s1", flows=UnknownFlows(), learners=FakeLearners())

    data = service.risk_list()

    assert data["total"] == 0
    assert data["risks"] == []


def test_risk_list_counts_learners_not_deduped_risk_names() -> None:
    class UnknownFlows(FakeFlows):
        def risk_ip_view(self, **_: Any) -> dict[str, Any]:
            return {
                "total": 2,
                "items": [
                    {
                        "subject_ip": "10.0.0.9",
                        "assigned_learner": "NEW_1",
                        "trigger_time": "2026-05-27 10:00:00",
                        "flow_count": 4,
                        "unknown_count": 2,
                        "top_dst_ip": "203.0.113.18",
                        "top_dst_port": 80,
                        "top_protocol": "tcp",
                    },
                    {
                        "subject_ip": "10.0.0.9",
                        "assigned_learner": "NEW_2",
                        "trigger_time": "2026-05-27 10:01:00",
                        "flow_count": 3,
                        "unknown_count": 3,
                        "top_dst_ip": "203.0.113.19",
                        "top_dst_port": 443,
                        "top_protocol": "tls",
                    },
                ],
            }

    class RiskLearners(FakeLearners):
        def list_learners(self, **_: Any) -> list[dict[str, Any]]:
            return [
                {
                    "id": 11,
                    "learner_name": "NEW_1",
                    "risk_score": 0.82,
                    "risk_band": "high",
                    "risk_reason": "unknown family",
                    "last_seen_at": "2026-05-27T10:00:00Z",
                    "flow_count": 20,
                    "rule_json": {
                        "attack_types": [
                            {"attack_type": "UNKNOWN_SUSPECTED", "confidence": 0.82},
                        ]
                    },
                },
                {
                    "id": 12,
                    "learner_name": "NEW_2",
                    "risk_score": 0.72,
                    "risk_band": "medium",
                    "risk_reason": "unknown family",
                    "last_seen_at": "2026-05-27T10:01:00Z",
                    "flow_count": 12,
                    "rule_json": {
                        "attack_types": [
                            {"attack_type": "UNKNOWN_SUSPECTED", "confidence": 0.72},
                        ]
                    },
                },
            ]

    service = PageQueryService(session_id="s1", flows=UnknownFlows(), learners=RiskLearners())

    data = service.risk_list()

    assert data["total"] == 1
    assert data["risks"][0]["riskCount"] == 2
    assert [risk["learnerName"] for risk in data["risks"][0]["risks"]] == ["NEW_1", "NEW_2"]
    assert [risk["name"] for risk in data["risks"][0]["risks"]] == ["未命名攻击1", "未命名攻击2"]


def test_ip_events_returns_risk_learner_metadata() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.ip_events(ip="10.0.0.8")

    assert data[0]["learnerName"] == "NEW_1"
    assert data[0]["riskBand"] == "high"
    assert data[0]["riskScore"] == 0.82


def test_learner_topology_marks_high_risk_view_as_attack() -> None:
    class CaptureFlows(FakeFlows):
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def topology_graph(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {"flow_count": 1, "node_mode": kwargs["node_mode"], "nodes": [], "links": [], "stats": {}}

    class CaptureLearners(FakeLearners):
        def get_learner(self, **_: Any) -> dict[str, Any]:
            return FakeLearners().list_learners()[0]

    service = PageQueryService(session_id="s1", flows=CaptureFlows(), learners=CaptureLearners())

    data = service.learner_topology(learner_name="NEW_1")

    assert data["views"]["NEW_1"]["is_benign"] is False
    assert all(call["traffic_kind"] == "attack" for call in service.flows.calls)
    assert all(call["risk_learners"] == ["NEW_1"] for call in service.flows.calls)


def test_learner_topology_uses_primary_attack_type_for_benign_view() -> None:
    class CaptureFlows(FakeFlows):
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def topology_graph(self, **kwargs: Any) -> dict[str, Any]:
            self.calls.append(kwargs)
            return {"flow_count": 1, "node_mode": kwargs["node_mode"], "nodes": [], "links": [], "stats": {}}

    class CaptureLearners(FakeLearners):
        def get_learner(self, **_: Any) -> dict[str, Any]:
            return FakeLearners().list_learners()[1]

    service = PageQueryService(session_id="s1", flows=CaptureFlows(), learners=CaptureLearners())

    data = service.learner_topology(learner_name="BASELINE_0")

    assert data["views"]["BASELINE_0"]["is_benign"] is True
    assert all(call["traffic_kind"] == "benign" for call in service.flows.calls)
    assert all(call["risk_learners"] == [] for call in service.flows.calls)


def test_protocol_distribution_bucket_maps_tcp_udp_and_other() -> None:
    assert _protocol_distribution_bucket(6) == "TCP"
    assert _protocol_distribution_bucket("TCP") == "TCP"
    assert _protocol_distribution_bucket(17) == "UDP"
    assert _protocol_distribution_bucket("udp") == "UDP"
    assert _protocol_distribution_bucket(0) == "其他"
    assert _protocol_distribution_bucket(1) == "其他"
    assert _protocol_distribution_bucket("ICMP") == "其他"
    assert _protocol_distribution_bucket("") == "其他"
    assert _protocol_distribution_bucket(None) == "其他"
    assert _protocol_distribution_bucket("unknown") == "其他"


def test_compact_protocol_distribution_groups_non_tcp_udp_into_other() -> None:
    rows = [
        {"protocol": "TCP", "value": 44572},
        {"protocol": "UDP", "value": 42915},
        {"protocol": "0", "value": 116},
        {"protocol": "ICMP", "value": 44},
    ]

    assert _compact_protocol_distribution(rows) == [
        {"name": "TCP", "value": 44572},
        {"name": "UDP", "value": 42915},
        {"name": "其他", "value": 160},
    ]
