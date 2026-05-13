from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import networkx as nx
import yaml


@dataclass
class Edge:
    a: str
    b: str
    jaccard: float


def _safe_div(x: float, y: float) -> float:
    return float(x / y) if y else 0.0


def _load_learner_rows(path: Path) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with path.open() as f:
        for r in csv.DictReader(f):
            dist = json.loads(str(r.get("label_distribution_json", "{}")))
            total = int(float(r.get("total_assigned_samples", 0) or 0))
            creation = int(float(r.get("creation_sample_count", 0) or 0))
            rows.append(
                {
                    "learner_name": str(r.get("learner_name", "")),
                    "total_assigned_samples": total,
                    "creation_sample_count": creation,
                    "label_distribution": {str(k): int(v) for k, v in dist.items()},
                }
            )
    return rows


def _load_edges(path: Path) -> List[Edge]:
    edges: List[Edge] = []
    with path.open() as f:
        for r in csv.DictReader(f):
            a = str(r.get("learner_a_raw", ""))
            b = str(r.get("learner_b_raw", ""))
            if not a or not b or a == b:
                continue
            jac = float(r.get("jaccard_acceptance", 0.0) or 0.0)
            edges.append(Edge(a=a, b=b, jaccard=jac))
    return edges


def _select_edges(
    edges: Sequence[Edge], min_jaccard: float, top_k_edges: int, max_edges: int
) -> List[Edge]:
    kept = [e for e in edges if e.jaccard >= min_jaccard]
    kept.sort(key=lambda e: e.jaccard, reverse=True)
    if top_k_edges > 0:
        kept = kept[:top_k_edges]
    if max_edges > 0:
        kept = kept[:max_edges]
    return kept


def _components_connected(nodes: Iterable[str], edges: Sequence[Edge]) -> List[List[str]]:
    g = nx.Graph()
    g.add_nodes_from(nodes)
    for e in edges:
        g.add_edge(e.a, e.b, weight=e.jaccard)
    return [sorted(list(c)) for c in nx.connected_components(g)]


def _components_mutual_knn(
    nodes: Iterable[str], edges: Sequence[Edge], mutual_top_k: int
) -> List[List[str]]:
    node_set = set(nodes)
    nbr: Dict[str, List[Tuple[str, float]]] = {n: [] for n in node_set}
    for e in edges:
        if e.a in node_set and e.b in node_set:
            nbr[e.a].append((e.b, e.jaccard))
            nbr[e.b].append((e.a, e.jaccard))

    topk: Dict[str, Set[str]] = {}
    for n, items in nbr.items():
        items.sort(key=lambda x: x[1], reverse=True)
        topk[n] = {m for m, _ in items[: max(0, mutual_top_k)]}

    g = nx.Graph()
    g.add_nodes_from(node_set)
    for a in node_set:
        for b in topk.get(a, set()):
            if a in topk.get(b, set()):
                key = tuple(sorted((a, b)))
                if not g.has_edge(*key):
                    g.add_edge(*key)
    return [sorted(list(c)) for c in nx.connected_components(g)]


def _communities_to_components(communities: Iterable[Set[str]], nodes: Iterable[str]) -> List[List[str]]:
    comps = [sorted(list(c)) for c in communities if c]
    assigned = {x for c in comps for x in c}
    for n in nodes:
        if n not in assigned:
            comps.append([n])
    return comps


def _components_lpa(nodes: Iterable[str], edges: Sequence[Edge], seed: int) -> List[List[str]]:
    g = nx.Graph()
    g.add_nodes_from(nodes)
    for e in edges:
        g.add_edge(e.a, e.b, weight=e.jaccard)
    comm = nx.algorithms.community.asyn_lpa_communities(g, weight="weight", seed=seed)
    return _communities_to_components(comm, nodes)


def _components_greedy(nodes: Iterable[str], edges: Sequence[Edge]) -> List[List[str]]:
    g = nx.Graph()
    g.add_nodes_from(nodes)
    for e in edges:
        g.add_edge(e.a, e.b, weight=e.jaccard)
    comm = nx.algorithms.community.greedy_modularity_communities(g, weight="weight")
    return _communities_to_components(comm, nodes)


def _components_louvain(nodes: Iterable[str], edges: Sequence[Edge], seed: int) -> List[List[str]]:
    if not hasattr(nx.algorithms.community, "louvain_communities"):
        raise RuntimeError("networkx current version does not provide louvain_communities")
    g = nx.Graph()
    g.add_nodes_from(nodes)
    for e in edges:
        g.add_edge(e.a, e.b, weight=e.jaccard)
    comm = nx.algorithms.community.louvain_communities(g, weight="weight", seed=seed)
    return _communities_to_components(comm, nodes)


def _build_agg_rows(
    components: Sequence[Sequence[str]], learner_rows: Dict[str, Dict[str, object]]
) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    agg_rows: List[Dict[str, object]] = []
    map_rows: List[Dict[str, object]] = []

    for i, comp in enumerate(components, start=1):
        agg_name = f"AGG_{i:03d}"
        dist: Dict[str, int] = {}
        total = 0
        creation = 0
        for ln in comp:
            row = learner_rows.get(ln)
            if row is None:
                continue
            total += int(row["total_assigned_samples"])
            creation += int(row["creation_sample_count"])
            for k, v in row["label_distribution"].items():
                dist[k] = int(dist.get(k, 0) + int(v))

            map_rows.append(
                {
                    "learner_name": ln,
                    "aggregate_name": agg_name,
                    "component_size": len(comp),
                }
            )

        benign = int(sum(v for k, v in dist.items() if str(k).endswith("|BENIGN") or str(k) == "2017|BENIGN"))
        attack = int(max(total - benign, 0))
        attack_ratio = _safe_div(float(attack), float(total))
        dominant_label = max(dist, key=dist.get) if dist else ""
        dominant_count = int(dist.get(dominant_label, 0)) if dist else 0
        dominant_ratio = _safe_div(float(dominant_count), float(total))

        agg_rows.append(
            {
                "attack_ratio": attack_ratio,
                "aggregate_name": agg_name,
                "member_count": int(len(comp)),
                "members_json": json.dumps(list(comp), ensure_ascii=False),
                "total_assigned_samples": int(total),
                "creation_sample_count": int(creation),
                "post_creation_added_samples": int(max(total - creation, 0)),
                "dominant_label": str(dominant_label),
                "dominant_count": int(dominant_count),
                "dominant_ratio": float(dominant_ratio),
                "benign_count": int(benign),
                "attack_count": int(attack),
                "learner_polarity": ("MALICIOUS" if attack_ratio >= 0.5 else "BENIGN"),
                "label_distribution_json": json.dumps(dist, ensure_ascii=False),
            }
        )

    agg_rows.sort(key=lambda r: (float(r["attack_ratio"]), int(r["total_assigned_samples"])), reverse=True)
    map_rows.sort(key=lambda r: (r["aggregate_name"], r["learner_name"]))
    return agg_rows, map_rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Run multiple aggregate algorithms offline from one run dir.")
    ap.add_argument("--run-dir", required=True, help="Path to outputs/runs/<run_id> directory")
    ap.add_argument("--config", required=True, help="YAML config for algorithm sweep")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    cfg = yaml.safe_load(Path(args.config).read_text())

    learner_dist_path = run_dir / "learner_label_distribution.csv"
    pair_path = run_dir / "debug_true_overlap_pairs.csv"
    if not learner_dist_path.exists() or not pair_path.exists():
        raise FileNotFoundError("Missing required files: learner_label_distribution.csv / debug_true_overlap_pairs.csv")

    learner_rows = _load_learner_rows(learner_dist_path)
    learner_by_name = {str(r["learner_name"]): r for r in learner_rows}
    learner_names = sorted(learner_by_name.keys())
    all_edges = _load_edges(pair_path)

    base_min_j = float(cfg.get("min_jaccard", 0.15))
    base_top_k = int(cfg.get("top_k_edges", 200))
    base_max_e = int(cfg.get("max_edges", 200))
    seed = int(cfg.get("seed", 42))
    algos = cfg.get("algorithms", [])
    if not algos:
        raise ValueError("algorithms must not be empty in config")

    summary: List[Dict[str, object]] = []
    selected_edges = _select_edges(all_edges, base_min_j, base_top_k, base_max_e)

    for a in algos:
        name = str(a.get("name", "")).strip().lower()
        if not name:
            continue
        if name == "connected_components":
            comps = _components_connected(learner_names, selected_edges)
        elif name == "mutual_knn_components":
            k = int(a.get("mutual_top_k", cfg.get("mutual_top_k", 3)))
            comps = _components_mutual_knn(learner_names, selected_edges, k)
        elif name == "label_propagation":
            comps = _components_lpa(learner_names, selected_edges, seed=seed)
        elif name == "greedy_modularity":
            comps = _components_greedy(learner_names, selected_edges)
        elif name == "louvain":
            comps = _components_louvain(learner_names, selected_edges, seed=seed)
        else:
            raise ValueError(f"Unsupported algorithm name: {name}")

        agg_rows, map_rows = _build_agg_rows(comps, learner_by_name)
        agg_path = run_dir / f"learner_aggregated_distribution_{name}.csv"
        map_path = run_dir / f"learner_aggregation_mapping_{name}.csv"
        with agg_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(agg_rows[0].keys()) if agg_rows else [])
            if agg_rows:
                w.writeheader()
                w.writerows(agg_rows)
        with map_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["learner_name", "aggregate_name", "component_size"])
            w.writeheader()
            w.writerows(map_rows)

        benign_like = int(sum(1 for r in agg_rows if str(r.get("learner_polarity")) == "BENIGN"))
        summary.append(
            {
                "algorithm": name,
                "aggregate_count": int(len(agg_rows)),
                "benign_aggregate_count": int(benign_like),
                "max_member_count": int(max((int(r["member_count"]) for r in agg_rows), default=0)),
                "output_agg_csv": str(agg_path),
                "output_map_csv": str(map_path),
            }
        )

    summary_path = run_dir / "aggregation_algorithm_sweep_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Wrote: {summary_path}")
    for row in summary:
        print(row)


if __name__ == "__main__":
    main()

