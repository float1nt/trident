from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    code: int = 200
    message: str = "success"
    data: Any


class FlowListData(BaseModel):
    items: list[dict[str, Any]]
    total: int | None = None
    limit: int
    offset: int | None = None
    next_cursor: str | None = None


class TopologyNode(BaseModel):
    id: str
    ip: str
    port: int | None = None
    flow_count: int = 0
    out_flow_count: int = 0
    in_flow_count: int = 0
    is_internal: bool = False


class TopologyLink(BaseModel):
    source: str
    target: str
    value: int
    is_benign: bool | None = None


class TopologyGraph(BaseModel):
    flow_count: int
    total_flow_count: int = 0
    node_mode: str
    nodes: list[TopologyNode]
    links: list[TopologyLink]
    stats: dict[str, float | int] = Field(default_factory=dict)


class TopologyLabelView(BaseModel):
    label: str
    view_kind: str = "aggregate"
    is_benign: bool | None = None
    endpoint: TopologyGraph
    host: TopologyGraph


class DashboardTopologyData(BaseModel):
    version: int = 1
    total_flows: int
    labels: list[str]
    default_label: str
    default_node_mode: str = "host"
    aggregate_views: list[str] = Field(default_factory=list)
    views: dict[str, TopologyLabelView]


class LearnerTopologyView(BaseModel):
    learner: str
    risk_id: int
    risk_name: str
    risk_description: str
    trigger_time: str
    attack_ratio: float
    dominant_label: str
    dominant_ratio: float | None = None
    is_benign: bool | None = None
    host: TopologyGraph
    endpoint: TopologyGraph


class LearnerTopologyData(BaseModel):
    version: int = 1
    total: int | None = None
    learners: list[str]
    default_learner: str
    views: dict[str, LearnerTopologyView]


class LearnerDetailData(BaseModel):
    learner: dict[str, Any]
    top_subject_ips: list[str]
    recent_flows: FlowListData
    topology: LearnerTopologyData | None = None
