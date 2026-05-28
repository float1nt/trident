from __future__ import annotations

from app.api_schema import LearnerTopologyData, TopologyGraph


def test_topology_graph_schema_preserves_protocol_fields() -> None:
    graph = TopologyGraph.model_validate(
        {
            "flow_count": 3,
            "total_flow_count": 3,
            "node_mode": "host",
            "nodes": [
                {
                    "id": "10.0.0.1",
                    "ip": "10.0.0.1",
                    "port": None,
                    "flow_count": 3,
                    "protocol": "TCP",
                }
            ],
            "links": [
                {
                    "source": "10.0.0.1",
                    "target": "10.0.0.2",
                    "value": 3,
                    "protocol": "UDP",
                }
            ],
            "stats": {},
        }
    )

    dumped = graph.model_dump()
    assert dumped["nodes"][0]["protocol"] == "TCP"
    assert dumped["links"][0]["protocol"] == "UDP"


def test_learner_topology_data_preserves_nested_protocol_fields() -> None:
    payload = {
        "version": 1,
        "total": 1,
        "risk_type_total": 1,
        "learners": ["NEW_1"],
        "default_learner": "NEW_1",
        "views": {
            "NEW_1": {
                "learner": "NEW_1",
                "risk_id": 1,
                "risk_name": "DDoS攻击",
                "risk_description": "desc",
                "trigger_time": "2026-05-27 10:00:00",
                "attack_ratio": 0.8,
                "dominant_label": "DDoS攻击",
                "dominant_ratio": 0.8,
                "is_benign": False,
                "host": {
                    "flow_count": 1,
                    "total_flow_count": 1,
                    "node_mode": "host",
                    "nodes": [{"id": "10.0.0.1", "ip": "10.0.0.1", "protocol": "TCP"}],
                    "links": [
                        {
                            "source": "10.0.0.1",
                            "target": "10.0.0.2",
                            "value": 1,
                            "protocol": "TCP",
                        }
                    ],
                    "stats": {},
                },
                "endpoint": {
                    "flow_count": 1,
                    "total_flow_count": 1,
                    "node_mode": "endpoint",
                    "nodes": [],
                    "links": [],
                    "stats": {},
                },
            }
        },
    }

    data = LearnerTopologyData.model_validate(payload).model_dump()
    host = data["views"]["NEW_1"]["host"]
    assert host["nodes"][0]["protocol"] == "TCP"
    assert host["links"][0]["protocol"] == "TCP"
