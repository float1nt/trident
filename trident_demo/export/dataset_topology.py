"""Build compact IP/port flow graphs for frontend visualization."""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from trident_demo.lib.utils import is_benign_label


def _is_private_ip(ip_s: str) -> bool:
    try:
        return ipaddress.ip_address(ip_s.strip()).is_private
    except ValueError:
        return ip_s.startswith("192.168.") or ip_s.startswith("10.")


def _endpoint(ip: object, port: object) -> str:
    ip_s = str(ip).strip()
    try:
        port_i = int(float(port))
    except (TypeError, ValueError):
        port_i = 0
    return f"{ip_s}:{port_i}"


def _host(ip: object) -> str:
    return str(ip).strip()


def build_flow_topology_for_frame(
    df: pd.DataFrame,
    *,
    node_mode: str = "host",
    max_edges: int = 80,
    max_nodes: int = 100,
    split_by_benign: bool = False,
) -> Dict[str, Any]:
    """Aggregate flows into a directed graph (top edges by count)."""
    if df.empty:
        return {"flow_count": 0, "nodes": [], "links": [], "stats": {}}

    src_ip = df["Src IP"].astype(str).str.strip()
    dst_ip = df["Dst IP"].astype(str).str.strip()
    src_port = pd.to_numeric(df["Src Port"], errors="coerce").fillna(0).astype(int)
    dst_port = pd.to_numeric(df["Dst Port"], errors="coerce").fillna(0).astype(int)

    if node_mode == "host":
        src_id = src_ip.map(_host)
        dst_id = dst_ip.map(_host)
    else:
        src_id = [_endpoint(a, b) for a, b in zip(src_ip, src_port)]
        dst_id = [_endpoint(a, b) for a, b in zip(dst_ip, dst_port)]

    edge_base = pd.DataFrame({"source": src_id, "target": dst_id})
    if split_by_benign and "LabelNorm" in df.columns:
        edge_base["is_benign"] = df["LabelNorm"].astype(str).map(is_benign_label).values
        by_type = (
            edge_base.groupby(["source", "target", "is_benign"], as_index=False)
            .size()
            .rename(columns={"size": "value"})
        )
        pair_rank = (
            by_type.groupby(["source", "target"], as_index=False)["value"]
            .sum()
            .rename(columns={"pair_total": "value"})
            .sort_values("value", ascending=False)
        )
        if max_edges > 0:
            top_pairs = {
                (str(r["source"]), str(r["target"]))
                for _, r in pair_rank.head(max_edges).iterrows()
            }
            edge_df = by_type[
                by_type.apply(
                    lambda r: (str(r["source"]), str(r["target"])) in top_pairs, axis=1
                )
            ].sort_values("value", ascending=False)
        else:
            edge_df = by_type.sort_values("value", ascending=False)
    else:
        edge_df = (
            edge_base.groupby(["source", "target"], as_index=False)
            .size()
            .rename(columns={"size": "value"})
        )
    edge_df = edge_df.sort_values("value", ascending=False)
    if max_edges > 0:
        edge_df = edge_df.head(max_edges)

    node_flow: Dict[str, int] = {}
    for _, row in edge_df.iterrows():
        s, t, v = str(row["source"]), str(row["target"]), int(row["value"])
        node_flow[s] = node_flow.get(s, 0) + v
        node_flow[t] = node_flow.get(t, 0) + v

    top_nodes = sorted(node_flow.items(), key=lambda x: x[1], reverse=True)
    if max_nodes > 0:
        keep_nodes = {n for n, _ in top_nodes[:max_nodes]}
    else:
        keep_nodes = set(node_flow.keys())

    edge_df = edge_df[
        edge_df["source"].isin(keep_nodes) & edge_df["target"].isin(keep_nodes)
    ]

    def node_meta(nid: str) -> Dict[str, Any]:
        if node_mode == "host":
            ip_s = nid
            port_i = None
        else:
            if ":" in nid:
                ip_s, port_s = nid.rsplit(":", 1)
                try:
                    port_i = int(port_s)
                except ValueError:
                    port_i = None
            else:
                ip_s, port_i = nid, None
        return {
            "id": nid,
            "ip": ip_s,
            "port": port_i,
            "flow_count": int(node_flow.get(nid, 0)),
            "is_internal": bool(_is_private_ip(ip_s)),
        }

    nodes = [node_meta(n) for n in sorted(keep_nodes)]
    links: List[Dict[str, Any]] = []
    for _, r in edge_df.iterrows():
        link: Dict[str, Any] = {
            "source": str(r["source"]),
            "target": str(r["target"]),
            "value": int(r["value"]),
        }
        if "is_benign" in edge_df.columns:
            link["is_benign"] = bool(r["is_benign"])
        links.append(link)

    stats = {
        "unique_src_ip": int(src_ip.nunique()),
        "unique_dst_ip": int(dst_ip.nunique()),
        "unique_dst_port": int(dst_port.nunique()),
        "internal_src_ratio": float((src_ip.map(_is_private_ip)).mean()),
        "internal_dst_ratio": float((dst_ip.map(_is_private_ip)).mean()),
        "edge_count": len(links),
        "node_count": len(nodes),
    }
    if len(dst_port) > 0:
        top_port = dst_port.value_counts().head(1)
        if len(top_port):
            stats["top_dst_port"] = int(top_port.index[0])
            stats["top_dst_port_ratio"] = float(top_port.iloc[0] / len(df))

    return {
        "flow_count": int(len(df)),
        "node_mode": node_mode,
        "nodes": nodes,
        "links": links,
        "stats": stats,
    }


def build_dataset_network_topology(
    data: pd.DataFrame,
    *,
    max_edges: int = 80,
    max_nodes: int = 100,
    min_label_flows: int = 1000,
    max_labels: int = 15,
) -> Dict[str, Any]:
    required = {"Src IP", "Dst IP", "Src Port", "Dst Port", "LabelNorm"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Dataset missing columns for topology: {sorted(missing)}")

    label_counts = data["LabelNorm"].astype(str).value_counts()
    label_targets = [
        str(lbl)
        for lbl, cnt in label_counts.items()
        if int(cnt) >= min_label_flows
    ][:max_labels]

    views: Dict[str, Any] = {}
    for label in label_targets:
        part = data.loc[data["LabelNorm"].astype(str) == label]
        views[label] = {
            "label": label,
            "view_kind": "label",
            "is_benign": bool(is_benign_label(label)),
            "endpoint": build_flow_topology_for_frame(
                part, node_mode="endpoint", max_edges=max_edges, max_nodes=max_nodes
            ),
            "host": build_flow_topology_for_frame(
                part, node_mode="host", max_edges=max_edges, max_nodes=max_nodes
            ),
        }

    benign_mask = data["LabelNorm"].astype(str).map(is_benign_label)
    benign_df = data.loc[benign_mask]
    attack_df = data.loc[~benign_mask]

    def _aggregate_view(
        key: str,
        frame: pd.DataFrame,
        *,
        is_benign: Optional[bool],
        split_edges: bool,
    ) -> Dict[str, Any]:
        return {
            "label": key,
            "view_kind": "aggregate",
            "is_benign": is_benign,
            "endpoint": build_flow_topology_for_frame(
                frame,
                node_mode="endpoint",
                max_edges=max_edges,
                max_nodes=max_nodes,
                split_by_benign=split_edges,
            ),
            "host": build_flow_topology_for_frame(
                frame,
                node_mode="host",
                max_edges=max_edges,
                max_nodes=max_nodes,
                split_by_benign=split_edges,
            ),
        }

    views["__benign__"] = _aggregate_view(
        "__benign__", benign_df, is_benign=True, split_edges=False
    )
    views["__attack__"] = _aggregate_view(
        "__attack__", attack_df, is_benign=False, split_edges=False
    )
    views["__combined__"] = _aggregate_view(
        "__combined__", data, is_benign=None, split_edges=True
    )

    default_label = "__combined__"
    return {
        "version": 2,
        "total_flows": int(len(data)),
        "labels": label_targets,
        "default_label": default_label,
        "default_node_mode": "host",
        "aggregate_views": ["__combined__", "__benign__", "__attack__"],
        "views": views,
    }


def save_dataset_network_topology(
    data: pd.DataFrame,
    output_path: Path,
    **kwargs: Any,
) -> Optional[Path]:
    if data.empty:
        return None
    payload = build_dataset_network_topology(data, **kwargs)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output_path


def build_learner_network_topology(
    data: pd.DataFrame,
    assign_df: pd.DataFrame,
    *,
    max_edges: int = 60,
    max_nodes: int = 80,
    min_learner_flows: int = 300,
    max_learners: int = 50,
) -> Dict[str, Any]:
    """Per-learner flow graphs from row_index → assigned_learner mapping."""
    required = {"Src IP", "Dst IP", "Src Port", "Dst Port", "LabelNorm"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Dataset missing columns for learner topology: {sorted(missing)}")
    if assign_df.empty or "row_index" not in assign_df.columns or "assigned_learner" not in assign_df.columns:
        return {"version": 1, "learners": [], "default_learner": "", "views": {}}

    assign = assign_df[["row_index", "assigned_learner"]].copy()
    assign["row_index"] = pd.to_numeric(assign["row_index"], errors="coerce")
    assign = assign.dropna(subset=["row_index", "assigned_learner"])
    assign["row_index"] = assign["row_index"].astype(int)
    assign["assigned_learner"] = assign["assigned_learner"].astype(str)
    assign = assign.drop_duplicates(subset=["row_index"], keep="last")

    flow = data.reset_index(drop=True).copy()
    flow["row_index"] = np.arange(len(flow), dtype=np.int64)
    merged = flow.merge(assign, on="row_index", how="inner")
    if merged.empty:
        return {"version": 1, "learners": [], "default_learner": "", "views": {}}

    counts = merged["assigned_learner"].value_counts()
    learner_targets = [
        str(name)
        for name, cnt in counts.items()
        if int(cnt) >= min_learner_flows and str(name) not in ("", "UNKNOWN")
    ][:max_learners]

    views: Dict[str, Any] = {}
    for learner in learner_targets:
        part = merged.loc[merged["assigned_learner"].astype(str) == learner]
        if part.empty:
            continue
        is_attack = ~part["LabelNorm"].astype(str).map(is_benign_label)
        attack_ratio = float(is_attack.mean()) if len(part) else 0.0
        label_counts = part["LabelNorm"].astype(str).value_counts()
        dominant_label = str(label_counts.index[0]) if len(label_counts) else ""
        dominant_ratio = (
            float(label_counts.iloc[0] / len(part)) if len(label_counts) else 0.0
        )
        views[learner] = {
            "learner": learner,
            "attack_ratio": attack_ratio,
            "dominant_label": dominant_label,
            "dominant_ratio": dominant_ratio,
            "is_benign": None,
            "host": build_flow_topology_for_frame(
                part,
                node_mode="host",
                max_edges=max_edges,
                max_nodes=max_nodes,
                split_by_benign=True,
            ),
            "endpoint": build_flow_topology_for_frame(
                part,
                node_mode="endpoint",
                max_edges=max_edges,
                max_nodes=max_nodes,
                split_by_benign=True,
            ),
        }

    learner_targets = sorted(
        learner_targets,
        key=lambda k: float(views[k]["attack_ratio"]),
        reverse=True,
    )
    default_learner = learner_targets[0] if learner_targets else ""
    return {
        "version": 1,
        "learners": learner_targets,
        "default_learner": default_learner,
        "views": views,
    }


def save_learner_network_topology(
    data: pd.DataFrame,
    assign_df: pd.DataFrame,
    output_path: Path,
    **kwargs: Any,
) -> Optional[Path]:
    if data.empty or assign_df.empty:
        return None
    payload = build_learner_network_topology(data, assign_df, **kwargs)
    if not payload.get("views"):
        return None
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return output_path
