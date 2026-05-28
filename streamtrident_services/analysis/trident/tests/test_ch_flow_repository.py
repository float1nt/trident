from __future__ import annotations

from app.flow_loader import FlowLoader
from app.persistence.ch_flow_repository import AssignmentUpdate, ChFlowRepository, _topology_node
from app.redis_consumer import RedisStreamMessage
from app.runtime.online_engine import FlowAssignment


def test_assignment_update_preserves_base_row_and_increments_version() -> None:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        "1000-0",
        {"dst_port": "443", "app_proto": "tls", "total_bytes": "2048"},
    )
    record = FlowLoader(session_id="s1", feature_profile="compact").load(message)
    assignment = FlowAssignment(
        flow_uid=record.flow_uid,
        assigned_learner="BASELINE_0",
        is_unknown=False,
        pred_loss=0.1,
        threshold=0.35,
        assignment_meta={"engine": "unit"},
        learner_snapshot_id="snap-1",
        learner_snapshot_version=1,
    )

    row = AssignmentUpdate.from_record(record, assignment, window_index=7).to_clickhouse_row()

    assert row["flow_uid"] == record.flow_uid
    assert row["dst_port"] == 443
    assert row["app_proto"] == "tls"
    assert row["total_bytes"] == 2048
    assert row["assigned_learner"] == "BASELINE_0"
    assert row["record_stage"] == "assigned"
    assert row["record_version"] == 1001


def test_topology_node_includes_directional_flow_counts() -> None:
    node = _topology_node(
        "192.168.10.3",
        12,
        node_mode="host",
        out_flow_count=7,
        in_flow_count=5,
    )

    assert node["flow_count"] == 12
    assert node["out_flow_count"] == 7
    assert node["in_flow_count"] == 5


def test_topology_graph_selects_top_edges_before_nodes() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> str:
            self.sql.append(sql)
            if "top_dst_port_ratio" in sql:
                return '{"total_flow_count":9,"top_dst_port":443,"top_dst_port_ratio":1,"unique_ip_count":2,"unique_endpoint_count":4,"unique_dst_port_count":1}\n'
            return "\n".join(
                [
                    '{"row_type":"node","id":"10.0.0.1","source":"","target":"","value":3,"out_flow_count":3,"in_flow_count":0,"is_benign":0}',
                    '{"row_type":"node","id":"10.0.0.2","source":"","target":"","value":3,"out_flow_count":0,"in_flow_count":3,"is_benign":0}',
                    '{"row_type":"edge","id":"","source":"10.0.0.1","target":"10.0.0.2","value":3,"out_flow_count":0,"in_flow_count":0,"is_benign":0}',
                ]
            )

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    graph = repo.topology_graph(session_id="s1", node_mode="host", top_n=50)

    topology_sql = repo.client.sql[0]
    assert "WITH edge_rows AS" in topology_sql
    assert "ORDER BY value DESC, source ASC, target ASC" in topology_sql
    assert "LIMIT 50" in topology_sql
    assert "selected_nodes AS" in topology_sql
    assert "SELECT source AS node, value AS out_count, 0 AS in_count FROM edge_rows" in topology_sql
    assert "SELECT target AS node, 0 AS out_count, value AS in_count FROM edge_rows" in topology_sql
    stats_sql = repo.client.sql[1]
    assert "unique_ip_count" in stats_sql
    assert "unique_endpoint_count" in stats_sql
    assert "unique_dst_port_count" in stats_sql
    assert graph["flow_count"] == 9
    assert graph["total_flow_count"] == 9
    assert graph["stats"]["unique_ip_count"] == 2
    assert graph["nodes"][0]["id"] == "10.0.0.1"
    assert graph["nodes"][0]["flow_count"] == 3
    assert graph["nodes"][0]["out_flow_count"] == 3
    assert graph["nodes"][0]["in_flow_count"] == 0
    assert graph["links"] == [
        {"source": "10.0.0.1", "target": "10.0.0.2", "value": 3, "is_benign": False}
    ]
