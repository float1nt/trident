from __future__ import annotations

from typing import Any

from app.page_queries import PageQueryService


class FakeFlows:
    def dashboard_summary(self, **_: Any) -> dict[str, Any]:
        return {
            "total_flows": 10,
            "protocol_count": 2,
            "normal_flows": 7,
            "risk_flows": 3,
            "risk_ip_count": 2,
            "current_window_index": 4,
        }

    def protocol_distribution(self, **_: Any) -> list[dict[str, Any]]:
        return [{"protocol": "tls", "value": 8}, {"protocol": "dns", "value": 2}]

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
    assert data["metrics"]["risk_learner_count"] == 1
    assert data["traffic_distribution"][1] == {"name": "疑似异常流量", "value": 3}
    assert data["protocol_distribution"] == [{"name": "TLS", "value": 8}, {"name": "DNS", "value": 2}]


def test_risk_events_default_to_medium_and_high_learners() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.risk_events()

    assert data["total"] == 1
    assert data["items"][0]["learner_name"] == "NEW_1"
    assert data["items"][0]["risk_name"] == "分布式拒绝服务攻击"
    assert data["items"][0]["subject_ips"] == ["10.0.0.8"]


def test_risk_events_topology_includes_all_risk_bands() -> None:
    class TopologyFlows(FakeFlows):
        def topology_graph(self, **_: Any) -> dict[str, Any]:
            return {"flow_count": 1, "node_mode": "host", "nodes": [], "links": [], "stats": {}}

    class TopologyLearners(FakeLearners):
        def get_learner(self, **_: Any) -> dict[str, Any]:
            return FakeLearners().list_learners()[0]

    service = PageQueryService(session_id="s1", flows=TopologyFlows(), learners=TopologyLearners())
    data = service.risk_events_topology()

    assert sorted(data["learners"]) == ["BASELINE_0", "NEW_1"]


def test_risk_ip_view_maps_aggregates_to_table_rows() -> None:
    service = PageQueryService(session_id="s1", flows=FakeFlows(), learners=FakeLearners())

    data = service.risk_ip_view()

    assert data["total"] == 1
    assert data["items"][0]["subjectIp"] == "10.0.0.8"
    assert data["items"][0]["name"] == "分布式拒绝服务攻击"
    assert data["items"][0]["id"] == 11
    assert "top_protocol=TLS" in data["items"][0]["description"]
