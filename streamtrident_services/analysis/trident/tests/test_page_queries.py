from __future__ import annotations

from typing import Any

from app.page_queries import PageQueryService


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
    assert data["traffic_distribution"][1] == {"name": "疑似异常流量", "value": 3000}
    assert data["protocol_distribution"] == [{"name": "TLS", "value": 8}, {"name": "DNS", "value": 2}]


def test_overview_metrics_reports_total_traffic_bytes() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.overview_metrics()

    assert data["totalTraffic"] == 10000


def test_overview_traffic_trend_returns_filled_buckets() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.overview_traffic_trend(time_range="24h")

    assert len(data) == 24
    assert set(data[0]) == {"label", "normal", "abnormal"}
    assert sum(item["normal"] + item["abnormal"] for item in data) == 0


def test_risk_events_default_to_attack_type_learners() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.risk_events()

    assert data["total"] == 1
    assert data["items"][0]["learner_name"] == "NEW_1"
    assert data["items"][0]["risk_name"] == "DDoS攻击"
    assert "风险类型=" not in data["items"][0]["risk_description"]
    assert data["items"][0]["risk_description"].startswith("置信度=0.820; 说明=")
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

    assert data["total"] == 2
    assert sorted(data["learners"]) == ["BASELINE_0", "NEW_1"]

    page = service.risk_events_topology(limit=1, offset=0)
    assert page["total"] == 2
    assert len(page["learners"]) == 1
    assert page["learners"][0] in data["learners"]


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
    assert [risk["name"] for risk in data["risks"][0]["risks"]] == ["未命名攻击", "未命名攻击"]


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
