from __future__ import annotations

from app.flow_loader import FlowLoader
from app.persistence.ch_flow_repository import AssignmentUpdate, ChFlowRepository, _topology_node
from app.protocol_utils import main_protocol_sql as _main_protocol_sql
from app.redis_consumer import RedisStreamMessage
from app.runtime.online_engine import FlowAssignment


def test_main_protocol_sql_falls_back_when_app_proto_is_unknown() -> None:
    sql = _main_protocol_sql()
    assert "lower(app_proto) NOT IN ('unknown'" in sql
    assert "protocol = 6, 'TCP'" in sql


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


def test_assignment_update_preserves_payload_sample_columns() -> None:
    message = RedisStreamMessage(
        "suricata:cic_flow",
        "1000-0",
        {
            "payload_sample_b64": "AQID",
            "payload_sample_bytes": "3",
            "payload_original_bytes": "100",
            "payload_truncated": "true",
            "payload_direction": "toserver",
        },
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

    assert row["payload_sample_b64"] == "AQID"
    assert row["payload_sample_bytes"] == 3
    assert row["payload_original_bytes"] == 100
    assert row["payload_truncated"] == 1
    assert row["payload_direction"] == "toserver"


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


def test_topology_node_includes_protocol_when_provided() -> None:
    node = _topology_node(
        "192.168.10.3",
        12,
        node_mode="host",
        protocol="TCP",
    )

    assert node["protocol"] == "TCP"


def test_topology_node_includes_role_when_provided() -> None:
    victim = _topology_node("10.0.0.2", 3, node_mode="host", role="victim")
    attacker = _topology_node("10.0.0.1", 3, node_mode="host", role="attacker")

    assert victim["role"] == "victim"
    assert attacker["role"] == "attacker"


def test_topology_graph_selects_top_victims_with_per_victim_edges() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> str:
            self.sql.append(sql)
            if "victim_counts AS" in sql:
                return "\n".join(
                    [
                        '{"row_type":"victim","victim":"10.0.0.2","victim_flow_count":9}',
                        '{"row_type":"stat","victim":"","victim_flow_count":9}',
                    ]
                )
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

    graph = repo.topology_graph(
        session_id="s1",
        node_mode="host",
        top_n=8,
        edges_per_victim=10,
    )

    victim_sql = repo.client.sql[0]
    edge_sql = repo.client.sql[1]
    assert "victim_counts AS" in victim_sql
    assert "victim_rows AS" in victim_sql
    assert "GROUP BY victim" in victim_sql
    assert "LIMIT 8" in victim_sql
    assert "WITH edge_source AS" in edge_sql
    assert "dst_ip IN ('10.0.0.2')" in edge_sql
    assert "ranked_edges AS" in edge_sql
    assert "row_number() OVER (PARTITION BY target ORDER BY value DESC, source ASC)" in edge_sql
    assert "WHERE edge_rank <= 10" in edge_sql
    assert "node_protocol_rows AS" in edge_sql
    assert "SELECT source AS node, value AS out_count, 0 AS in_count FROM edge_rows" in edge_sql
    assert "SELECT target AS node, 0 AS out_count, value AS in_count FROM edge_rows" in edge_sql
    stats_sql = repo.client.sql[2]
    assert "unique_ip_count" in stats_sql
    assert graph["flow_count"] == 9
    assert graph["stats"]["displayed_victim_count"] == 1
    assert graph["stats"]["edges_per_victim"] == 10
    assert graph["nodes"][0]["role"] == "attacker"
    assert graph["nodes"][1]["role"] == "victim"
    assert graph["links"] == [
        {"source": "10.0.0.1", "target": "10.0.0.2", "value": 3, "is_benign": False}
    ]


def test_topology_graph_can_skip_expensive_stats_query() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> str:
            self.sql.append(sql)
            if "victim_counts AS" in sql:
                return "\n".join(
                    [
                        '{"row_type":"victim","victim":"10.0.0.2","victim_flow_count":9}',
                        '{"row_type":"stat","victim":"","victim_flow_count":9}',
                    ]
                )
            return "\n".join(
                [
                    '{"row_type":"node","id":"10.0.0.1","source":"","target":"","value":3,"out_flow_count":3,"in_flow_count":0,"is_benign":0}',
                    '{"row_type":"node","id":"10.0.0.2","source":"","target":"","value":3,"out_flow_count":0,"in_flow_count":3,"is_benign":0}',
                    '{"row_type":"edge","id":"","source":"10.0.0.1","target":"10.0.0.2","value":3,"out_flow_count":0,"in_flow_count":0,"is_benign":0}',
                    '{"row_type":"stat","id":"","source":"","target":"","value":9,"out_flow_count":0,"in_flow_count":0,"is_benign":0}',
                ]
            )

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    graph = repo.topology_graph(session_id="s1", node_mode="host", include_stats=False)

    assert len(repo.client.sql) == 2
    assert "victim_counts AS" in repo.client.sql[0]
    assert "node_protocol_rows AS" in repo.client.sql[1]
    assert "FROM edge_rows" in repo.client.sql[1]
    assert "SELECT src_ip AS node" not in repo.client.sql[1]
    assert graph["flow_count"] == 9
    assert graph["stats"]["total_flow_count"] == 9


def test_topology_graph_endpoint_drills_from_host_edges_without_source_port() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> str:
            self.sql.append(sql)
            if "victim_counts AS" in sql:
                return "\n".join(
                    [
                        '{"row_type":"victim","victim":"10.0.0.2","victim_flow_count":9}',
                        '{"row_type":"stat","victim":"","victim_flow_count":9}',
                    ]
                )
            if "WITH edge_source AS" in sql and "src_ip AS source_host" not in sql:
                return '{"row_type":"edge","id":"","source":"10.0.0.1","target":"10.0.0.2","value":3,"out_flow_count":0,"in_flow_count":0,"is_benign":0}\n'
            return '{"row_type":"edge","id":"","source":"10.0.0.1","target":"10.0.0.2:443","value":3,"out_flow_count":0,"in_flow_count":0,"is_benign":0}\n'

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    graph = repo.topology_graph(
        session_id="s1",
        node_mode="endpoint",
        risk_learners=["NEW_1"],
        learner_name="NEW_1",
        top_n=8,
        edges_per_victim=10,
        include_stats=False,
    )

    assert len(repo.client.sql) == 3
    endpoint_sql = repo.client.sql[2]
    assert "src_ip AS source_host" in endpoint_sql
    assert "src_ip AS source" in endpoint_sql
    assert "concat(src_ip, ':', toString(src_port)) AS source" not in endpoint_sql
    assert "concat(dst_ip, ':', toString(dst_port)) AS target" in endpoint_sql
    assert "assigned_learner = 'NEW_1'" in endpoint_sql
    assert "(dst_ip, src_ip) IN (('10.0.0.2', '10.0.0.1'))" in endpoint_sql
    assert "(src_ip, dst_ip) IN" not in endpoint_sql
    assert "PARTITION BY source_host, target_host" in endpoint_sql
    assert graph["links"] == [{"source": "10.0.0.1", "target": "10.0.0.2:443", "value": 3, "is_benign": False}]


def test_dashboard_topology_graphs_uses_top_victim_list_for_edge_query() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> str:
            self.sql.append(sql)
            if "victim_counts AS" in sql:
                return "\n".join(
                    [
                        '{"row_type":"victim","topology_kind":"combined","victim":"10.0.0.2","victim_flow_count":9}',
                        '{"row_type":"victim","topology_kind":"attack","victim":"10.0.0.2","victim_flow_count":4}',
                        '{"row_type":"victim","topology_kind":"benign","victim":"10.0.0.3","victim_flow_count":5}',
                        '{"row_type":"stat","topology_kind":"combined","victim":"","victim_flow_count":9}',
                        '{"row_type":"stat","topology_kind":"attack","victim":"","victim_flow_count":4}',
                        '{"row_type":"stat","topology_kind":"benign","victim":"","victim_flow_count":5}',
                    ]
                )
            return "\n".join(
                [
                    '{"row_type":"node","topology_kind":"combined","id":"10.0.0.1","source":"","target":"","value":3,"out_flow_count":3,"in_flow_count":0,"is_benign":0}',
                    '{"row_type":"node","topology_kind":"combined","id":"10.0.0.2","source":"","target":"","value":3,"out_flow_count":0,"in_flow_count":3,"is_benign":0}',
                    '{"row_type":"edge","topology_kind":"combined","id":"","source":"10.0.0.1","target":"10.0.0.2","value":3,"out_flow_count":0,"in_flow_count":0,"is_benign":0}',
                ]
            )

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    graphs = repo.dashboard_topology_graphs(
        session_id="s1",
        node_mode="host",
        risk_learners=["NEW_1"],
    )

    assert len(repo.client.sql) == 2
    victim_sql = repo.client.sql[0]
    edge_sql = repo.client.sql[1]
    assert "victim_counts AS" in victim_sql
    assert "row_number() OVER (PARTITION BY topology_kind ORDER BY victim_flow_count DESC, victim ASC)" in victim_sql
    assert "WITH edge_source AS" in edge_sql
    assert "edge_agg AS" in edge_sql
    assert "INNER JOIN victim_rows" not in edge_sql
    assert "dst_ip IN ('10.0.0.2', '10.0.0.3')" in edge_sql
    assert edge_sql.count("FROM ch_flow") == 1
    assert "countIf(target IN ('10.0.0.2')) AS combined_value" in edge_sql
    assert "countIf(target IN ('10.0.0.3') AND NOT is_attack) AS benign_value" in edge_sql
    assert "countIf(target IN ('10.0.0.2') AND is_attack) AS attack_value" in edge_sql
    assert "topKIf(1)(main_protocol" in edge_sql
    assert "ARRAY JOIN [" in edge_sql
    assert "PARTITION BY topology_kind" in edge_sql
    assert "SELECT src_ip AS node" not in edge_sql
    assert graphs["combined"]["flow_count"] == 9
    assert graphs["attack"]["flow_count"] == 4
    assert graphs["benign"]["flow_count"] == 5


def test_dashboard_topology_graphs_drills_endpoint_edges_from_host_edges() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> str:
            self.sql.append(sql)
            if "victim_counts AS" in sql:
                return "\n".join(
                    [
                        '{"row_type":"victim","topology_kind":"combined","victim":"10.0.0.2","victim_flow_count":9}',
                        '{"row_type":"victim","topology_kind":"attack","victim":"10.0.0.2","victim_flow_count":4}',
                        '{"row_type":"victim","topology_kind":"benign","victim":"10.0.0.3","victim_flow_count":5}',
                        '{"row_type":"stat","topology_kind":"combined","victim":"","victim_flow_count":9}',
                        '{"row_type":"stat","topology_kind":"attack","victim":"","victim_flow_count":4}',
                        '{"row_type":"stat","topology_kind":"benign","victim":"","victim_flow_count":5}',
                    ]
                )
            if "WITH edge_source AS" in sql and "src_ip AS source_host" not in sql:
                return "\n".join(
                    [
                        '{"row_type":"edge","topology_kind":"combined","id":"","source":"10.0.0.1","target":"10.0.0.2","value":3,"out_flow_count":0,"in_flow_count":0,"is_benign":0}',
                        '{"row_type":"edge","topology_kind":"attack","id":"","source":"10.0.0.1","target":"10.0.0.2","value":2,"out_flow_count":0,"in_flow_count":0,"is_benign":0}',
                        '{"row_type":"edge","topology_kind":"benign","id":"","source":"10.0.0.4","target":"10.0.0.3","value":1,"out_flow_count":0,"in_flow_count":0,"is_benign":1}',
                    ]
                )
            return ""

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    repo.dashboard_topology_graphs(
        session_id="s1",
        node_mode="endpoint",
        risk_learners=["NEW_1"],
    )

    assert len(repo.client.sql) == 3
    host_edge_sql = repo.client.sql[1]
    edge_sql = repo.client.sql[2]
    assert "src_ip AS source_host" not in host_edge_sql
    assert "src_ip AS source_host" in edge_sql
    assert "src_ip AS source" in edge_sql
    assert "concat(src_ip, ':', toString(src_port)) AS source" not in edge_sql
    assert "concat(dst_ip, ':', toString(dst_port)) AS target" in edge_sql
    assert "dst_ip IN ('10.0.0.2', '10.0.0.3')" in edge_sql
    assert "(dst_ip, src_ip) IN (('10.0.0.2', '10.0.0.1'), ('10.0.0.3', '10.0.0.4'))" in edge_sql
    assert "(src_ip, dst_ip) IN" not in edge_sql
    assert "PARTITION BY topology_kind, source_host, target_host" in edge_sql
    assert "AND concat(dst_ip, ':', toString(dst_port)) IN" not in edge_sql
    assert "(dst_ip, dst_port) IN" not in edge_sql
    assert edge_sql.count("FROM ch_flow") == 1


def test_dashboard_topology_graphs_applies_time_bounds_to_both_queries() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql: list[str] = []

        def execute(self, sql: str) -> str:
            self.sql.append(sql)
            if "victim_counts AS" in sql:
                return "\n".join(
                    [
                        '{"row_type":"victim","topology_kind":"combined","victim":"10.0.0.2","victim_flow_count":9}',
                        '{"row_type":"stat","topology_kind":"combined","victim":"","victim_flow_count":9}',
                    ]
                )
            return ""

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    repo.dashboard_topology_graphs(
        session_id="s1",
        node_mode="host",
        time_from="2026-06-02T00:00:00Z",
        time_to="2026-06-02T01:00:00Z",
    )

    assert len(repo.client.sql) == 2
    for sql in repo.client.sql:
        assert "event_time >= parseDateTime64BestEffort('2026-06-02T00:00:00Z', 3)" in sql
        assert "event_time <= parseDateTime64BestEffort('2026-06-02T01:00:00Z', 3)" in sql


def test_learner_trigger_stats_batches_min_max_and_count() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql = ""

        def execute(self, sql: str) -> str:
            self.sql = sql
            return (
                '{"assigned_learner":"NEW_1","first_trigger_time":"2026-05-27 09:30:00",'
                '"last_trigger_time":"2026-05-27 10:05:00","trigger_count":21}\n'
            )

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    stats = repo.learner_trigger_stats(session_id="s1", learner_names=["NEW_1", "NEW_1", "NEW_2"])

    assert "min(event_time) AS first_trigger_time" in repo.client.sql
    assert "max(event_time) AS last_trigger_time" in repo.client.sql
    assert "count() AS trigger_count" in repo.client.sql
    assert "assigned_learner IN ('NEW_1', 'NEW_2')" in repo.client.sql
    assert "GROUP BY assigned_learner" in repo.client.sql
    assert stats["NEW_1"]["trigger_count"] == 21
