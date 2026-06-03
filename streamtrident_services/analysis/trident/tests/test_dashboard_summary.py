from __future__ import annotations

from app.persistence.ch_flow_repository import ChFlowRepository


def test_dashboard_summary_counts_dst_ip_for_risk_flows() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.sql = ""

        def execute(self, sql: str) -> str:
            self.sql = sql
            return (
                '{"total_flows":4,"total_bytes":400,"protocol_count":2,"risk_flows":2,'
                '"normal_flows":2,"risk_bytes":200,"normal_bytes":200,'
                '"risk_ip_count":2,"active_abnormal_learners":["NEW_1"],'
                '"current_window_index":3}\n'
            )

    repo = ChFlowRepository.__new__(ChFlowRepository)
    repo.client = FakeClient()

    summary = repo.dashboard_summary(
        session_id="s1",
        risk_learners=["NEW_1"],
        time_from="2026-05-01T00:00:00Z",
        time_to="2026-05-02T00:00:00Z",
    )

    assert "uniqExactIf(dst_ip, assigned_learner IN ('NEW_1')) AS risk_ip_count" in repo.client.sql
    assert "groupUniqArrayIf(assigned_learner, assigned_learner IN ('NEW_1')) AS active_abnormal_learners" in repo.client.sql
    assert "event_time <= parseDateTime64BestEffort('2026-05-02T00:00:00Z', 3, 'UTC')" in repo.client.sql
    assert summary["risk_ip_count"] == 2
    assert summary["active_abnormal_learners"] == ["NEW_1"]
