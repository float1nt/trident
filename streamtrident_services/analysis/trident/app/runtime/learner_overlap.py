from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np


@dataclass(frozen=True, slots=True)
class LearnerOverlapConfig:
    min_jaccard: float = 0.10
    top_k_edges: int = 80
    max_edges: int = 80
    graph_algo: str = "connected"
    mutual_top_k: int = 3
    sample_cap_per_learner: int = 512


@dataclass(frozen=True, slots=True)
class LearnerOverlapEdge:
    learner_a: str
    learner_b: str
    acceptance_intersection: int
    acceptance_count_a: int
    acceptance_count_b: int
    jaccard_acceptance: float
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_a": self.learner_a,
            "learner_b": self.learner_b,
            "acceptance_intersection": int(self.acceptance_intersection),
            "acceptance_count_a": int(self.acceptance_count_a),
            "acceptance_count_b": int(self.acceptance_count_b),
            "jaccard_acceptance": float(self.jaccard_acceptance),
            "score": float(self.score),
        }


@dataclass(frozen=True, slots=True)
class LearnerOverlapAggregate:
    aggregate_name: str
    member_count: int
    members: list[str]
    total_accept_count: int
    internal_edge_count: int
    avg_internal_jaccard: float
    max_internal_jaccard: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_name": self.aggregate_name,
            "member_count": int(self.member_count),
            "members": list(self.members),
            "total_accept_count": int(self.total_accept_count),
            "internal_edge_count": int(self.internal_edge_count),
            "avg_internal_jaccard": float(self.avg_internal_jaccard),
            "max_internal_jaccard": float(self.max_internal_jaccard),
        }


@dataclass(frozen=True, slots=True)
class LearnerOverlapSnapshot:
    learner_names: list[str]
    accept_count: dict[str, int]
    pair_intersections: dict[tuple[str, str], int]
    edges: list[LearnerOverlapEdge]
    aggregates: list[LearnerOverlapAggregate]
    mapping: dict[str, str]
    meta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "learner_names": list(self.learner_names),
            "accept_count": {str(k): int(v) for k, v in self.accept_count.items()},
            "pair_intersections": [
                {
                    "learner_a": a,
                    "learner_b": b,
                    "count": int(v),
                }
                for (a, b), v in sorted(self.pair_intersections.items())
            ],
            "edges": [edge.to_dict() for edge in self.edges],
            "aggregates": [aggregate.to_dict() for aggregate in self.aggregates],
            "mapping": dict(self.mapping),
            "meta": dict(self.meta),
        }


def build_learner_overlap_snapshot(
    *,
    tsieve: Any,
    learner_histories: Mapping[str, list[np.ndarray]],
    config: LearnerOverlapConfig | None = None,
) -> LearnerOverlapSnapshot:
    cfg = config or LearnerOverlapConfig()
    learner_names = [str(name) for name in tsieve.learners.keys()]
    accept_count, pair_intersections, stream_sample_count = _collect_overlap_stats(
        tsieve,
        learner_histories,
        learner_names=learner_names,
        sample_cap_per_learner=int(cfg.sample_cap_per_learner),
    )
    edges = _select_overlap_edges(
        learner_names=learner_names,
        accept_count=accept_count,
        pair_intersections=pair_intersections,
        min_jaccard=float(cfg.min_jaccard),
        top_k_edges=int(cfg.top_k_edges),
        max_edges=int(cfg.max_edges),
    )
    if str(cfg.graph_algo).strip().lower() == "mutual_knn_components":
        components, edge_weights, used_edges = _components_by_mutual_knn(
            learner_names=learner_names,
            edges=edges,
            mutual_top_k=int(cfg.mutual_top_k),
        )
    else:
        components, edge_weights, used_edges = _components_by_connected(learner_names=learner_names, edges=edges)

    aggregates: list[LearnerOverlapAggregate] = []
    mapping: dict[str, str] = {}
    for idx, comp in enumerate(components, start=1):
        aggregate_name = f"AGG_{idx:03d}"
        total_accept_count = int(sum(int(accept_count.get(name, 0)) for name in comp))
        internal_edge_count = 0
        internal_jaccard_sum = 0.0
        max_internal_jaccard = 0.0
        for i in range(len(comp)):
            for j in range(i + 1, len(comp)):
                key = tuple(sorted((comp[i], comp[j])))
                if key not in edge_weights:
                    continue
                internal_edge_count += 1
                weight = float(edge_weights[key])
                internal_jaccard_sum += weight
                max_internal_jaccard = max(max_internal_jaccard, weight)
        avg_internal_jaccard = internal_jaccard_sum / internal_edge_count if internal_edge_count > 0 else 0.0
        aggregates.append(
            LearnerOverlapAggregate(
                aggregate_name=aggregate_name,
                member_count=len(comp),
                members=list(comp),
                total_accept_count=total_accept_count,
                internal_edge_count=internal_edge_count,
                avg_internal_jaccard=float(avg_internal_jaccard),
                max_internal_jaccard=float(max_internal_jaccard),
            )
        )
        for learner_name in comp:
            mapping[learner_name] = aggregate_name

    meta = {
        "aggregate_overlap_enabled": True,
        "aggregate_graph_algo": str(cfg.graph_algo),
        "aggregate_min_jaccard": float(cfg.min_jaccard),
        "aggregate_top_k_edges": int(cfg.top_k_edges),
        "aggregate_max_edges": int(cfg.max_edges),
        "aggregate_mutual_top_k": int(cfg.mutual_top_k),
        "selected_edge_count": int(len(edges)),
        "used_edge_count_after_algo": int(used_edges),
        "aggregate_count": int(len(aggregates)),
        "learner_count": int(len(learner_names)),
        "sample_cap_per_learner": int(cfg.sample_cap_per_learner),
        "accepted_sample_count": int(stream_sample_count),
    }
    return LearnerOverlapSnapshot(
        learner_names=learner_names,
        accept_count=accept_count,
        pair_intersections=pair_intersections,
        edges=edges,
        aggregates=aggregates,
        mapping=mapping,
        meta=meta,
    )


def _collect_overlap_stats(
    tsieve: Any,
    learner_histories: Mapping[str, list[np.ndarray]],
    *,
    learner_names: list[str],
    sample_cap_per_learner: int,
) -> tuple[dict[str, int], dict[tuple[str, str], int], int]:
    accept_count: dict[str, int] = {name: 0 for name in learner_names}
    pair_intersections: dict[tuple[str, str], int] = {}
    stream_sample_count = 0
    active_names = {name for name in learner_names if name in getattr(tsieve, "learners", {})}
    if not active_names:
        return accept_count, pair_intersections, stream_sample_count

    for learner_name in learner_names:
        history = learner_histories.get(learner_name, [])
        if not history:
            continue
        samples = np.asarray(history, dtype=np.float64)
        if samples.size == 0:
            continue
        if samples.ndim == 1:
            samples = samples.reshape(-1, 1)
        if len(samples) > sample_cap_per_learner and hasattr(tsieve, "interval_sample_by_loss"):
            try:
                samples = tsieve.interval_sample_by_loss(learner_name, samples, int(sample_cap_per_learner))
            except Exception:
                samples = samples[: int(sample_cap_per_learner)]
        elif len(samples) > sample_cap_per_learner:
            samples = samples[: int(sample_cap_per_learner)]
        if len(samples) == 0:
            continue
        details = tsieve.classify_batch_details(np.asarray(samples, dtype=np.float64))
        stream_sample_count += len(details)
        for detail in details:
            accepted = _normalized_accepted_names(detail, active_names)
            for name in accepted:
                accept_count[name] = int(accept_count.get(name, 0) + 1)
            for i in range(len(accepted)):
                for j in range(i + 1, len(accepted)):
                    key = (accepted[i], accepted[j])
                    pair_intersections[key] = int(pair_intersections.get(key, 0) + 1)
    return accept_count, pair_intersections, stream_sample_count


def _normalized_accepted_names(detail: Mapping[str, Any], active_names: set[str]) -> list[str]:
    accepted = detail.get("accepted_names", [])
    if not isinstance(accepted, list):
        return []
    names = sorted({str(name) for name in accepted if str(name) in active_names})
    return names


def _select_overlap_edges(
    *,
    learner_names: list[str],
    accept_count: Mapping[str, int],
    pair_intersections: Mapping[tuple[str, str], int],
    min_jaccard: float,
    top_k_edges: int,
    max_edges: int,
) -> list[LearnerOverlapEdge]:
    learner_set = set(learner_names)
    edges: list[LearnerOverlapEdge] = []
    for (a, b), inter in pair_intersections.items():
        if a not in learner_set or b not in learner_set:
            continue
        count_a = int(accept_count.get(a, 0))
        count_b = int(accept_count.get(b, 0))
        if inter <= 0 or count_a <= 0 or count_b <= 0:
            continue
        union = count_a + count_b - int(inter)
        if union <= 0:
            continue
        jaccard = float(inter / union)
        if jaccard < float(min_jaccard):
            continue
        edges.append(
            LearnerOverlapEdge(
                learner_a=a,
                learner_b=b,
                acceptance_intersection=int(inter),
                acceptance_count_a=count_a,
                acceptance_count_b=count_b,
                jaccard_acceptance=jaccard,
                score=jaccard,
            )
        )
    edges = sorted(edges, key=lambda edge: (edge.score, edge.jaccard_acceptance), reverse=True)
    if top_k_edges > 0:
        edges = edges[: int(top_k_edges)]
    if max_edges > 0:
        edges = edges[: int(max_edges)]
    return edges


def _components_by_connected(
    *,
    learner_names: list[str],
    edges: list[LearnerOverlapEdge],
) -> tuple[list[list[str]], dict[tuple[str, str], float], int]:
    learner_set = set(learner_names)
    adj: dict[str, set[str]] = {name: set() for name in learner_names}
    edge_weights: dict[tuple[str, str], float] = {}
    used_edges = 0
    for edge in edges:
        a = edge.learner_a
        b = edge.learner_b
        if a not in learner_set or b not in learner_set:
            continue
        adj[a].add(b)
        adj[b].add(a)
        key = tuple(sorted((a, b)))
        edge_weights[key] = float(edge.jaccard_acceptance)
        used_edges += 1
    components: list[list[str]] = []
    visited: set[str] = set()
    for name in sorted(learner_names):
        if name in visited:
            continue
        stack = [name]
        comp: list[str] = []
        while stack:
            cur = stack.pop()
            if cur in visited:
                continue
            visited.add(cur)
            comp.append(cur)
            for nxt in sorted(adj.get(cur, set())):
                if nxt not in visited:
                    stack.append(nxt)
        components.append(sorted(comp))
    return components, edge_weights, int(used_edges)


def _components_by_mutual_knn(
    *,
    learner_names: list[str],
    edges: list[LearnerOverlapEdge],
    mutual_top_k: int,
) -> tuple[list[list[str]], dict[tuple[str, str], float], int]:
    learner_set = set(learner_names)
    neighbors: dict[str, list[tuple[str, float]]] = {name: [] for name in learner_names}
    jaccard_by_edge: dict[tuple[str, str], float] = {}
    for edge in edges:
        a = edge.learner_a
        b = edge.learner_b
        if a not in learner_set or b not in learner_set:
            continue
        neighbors[a].append((b, float(edge.score)))
        neighbors[b].append((a, float(edge.score)))
        jaccard_by_edge[tuple(sorted((a, b)))] = float(edge.jaccard_acceptance)

    top_k_sets: dict[str, set[str]] = {}
    k = max(1, int(mutual_top_k))
    for name, nbrs in neighbors.items():
        nbrs_sorted = sorted(nbrs, key=lambda item: item[1], reverse=True)
        top_k_sets[name] = {n for n, _ in nbrs_sorted[:k]}

    kept_edges: list[tuple[str, str, float]] = []
    for edge in edges:
        if edge.b in top_k_sets.get(edge.learner_a, set()) and edge.a in top_k_sets.get(edge.learner_b, set()):
            key = tuple(sorted((edge.learner_a, edge.learner_b)))
            kept_edges.append((edge.learner_a, edge.learner_b, float(jaccard_by_edge.get(key, 0.0))))

    dedup: dict[tuple[str, str], float] = {}
    for a, b, weight in kept_edges:
        key = tuple(sorted((a, b)))
        dedup[key] = max(float(dedup.get(key, 0.0)), float(weight))
    reduced_edges = [LearnerOverlapEdge(a, b, 0, 0, 0, w, w) for (a, b), w in dedup.items()]
    return _components_by_connected(learner_names=learner_names, edges=reduced_edges)
