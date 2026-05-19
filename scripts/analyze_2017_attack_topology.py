#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd


FILES_2017 = ["monday.csv", "tuesday.csv", "wednesday.csv", "thursday.csv", "friday.csv"]

COL_ALIASES = {
    "label": ["Label", "label"],
    "src_ip": ["Src IP", "Source IP", "src_ip", "source_ip", " Source IP"],
    "dst_ip": ["Dst IP", "Destination IP", "dst_ip", "destination_ip", " Destination IP"],
    "src_port": ["Src Port", "Source Port", "src_port", "source_port", " Source Port"],
    "dst_port": ["Dst Port", "Destination Port", "dst_port", "destination_port", " Destination Port"],
}


def _norm_label(v: object) -> str:
    return str(v).strip().upper()


def _safe_name(v: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(v).strip())
    return s.strip("_") or "unknown"


def _resolve_col(columns: Iterable[str], aliases: List[str]) -> str:
    col_set = set(columns)
    for a in aliases:
        if a in col_set:
            return a
    normalized = {str(c).strip().lower(): c for c in columns}
    for a in aliases:
        key = str(a).strip().lower()
        if key in normalized:
            return str(normalized[key])
    raise KeyError(f"Cannot resolve any column from aliases={aliases}")


def _detect_columns(sample_csv: Path) -> Dict[str, str]:
    cols = pd.read_csv(sample_csv, nrows=0).columns.tolist()
    return {k: _resolve_col(cols, aliases) for k, aliases in COL_ALIASES.items()}


def _read_all_frames(data_dir: Path) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    col_map = _detect_columns(data_dir / FILES_2017[0])
    read_cols = [col_map["label"], col_map["src_ip"], col_map["dst_ip"], col_map["src_port"], col_map["dst_port"]]
    for name in FILES_2017:
        p = data_dir / name
        if not p.exists():
            raise FileNotFoundError(f"Missing source file: {p}")
        df = pd.read_csv(p, low_memory=False, usecols=lambda c: c in read_cols)
        df = df.rename(
            columns={
                col_map["label"]: "Label",
                col_map["src_ip"]: "SrcIP",
                col_map["dst_ip"]: "DstIP",
                col_map["src_port"]: "SrcPort",
                col_map["dst_port"]: "DstPort",
            }
        )
        df["Label"] = df["Label"].map(_norm_label)
        frames.append(df)
    all_df = pd.concat(frames, ignore_index=True)
    return all_df


def _build_attack_graph(df_attack: pd.DataFrame) -> nx.DiGraph:
    src = df_attack["SrcIP"].astype(str).str.strip() + ":" + df_attack["SrcPort"].astype(str).str.strip()
    dst = df_attack["DstIP"].astype(str).str.strip() + ":" + df_attack["DstPort"].astype(str).str.strip()
    pair_counts = (
        pd.DataFrame({"src": src, "dst": dst})
        .groupby(["src", "dst"], as_index=False)
        .size()
        .rename(columns={"size": "weight"})
    )
    g = nx.DiGraph()
    for row in pair_counts.itertuples(index=False):
        g.add_edge(row.src, row.dst, weight=int(row.weight))
    return g


def _graph_metrics(label: str, g: nx.DiGraph, sample_count: int) -> Dict[str, object]:
    n = g.number_of_nodes()
    m = g.number_of_edges()
    if n == 0:
        return {
            "label": label,
            "samples_used": sample_count,
            "nodes": 0,
            "edges": 0,
            "density": 0.0,
            "components_weak": 0,
            "largest_component_ratio": 0.0,
            "reciprocity": 0.0,
            "max_out_degree": 0,
            "max_in_degree": 0,
            "top_source_endpoint": "",
            "top_sink_endpoint": "",
            "hub_out_ratio": 0.0,
            "hub_in_ratio": 0.0,
            "anomaly_flags": "EMPTY",
        }

    wcc = list(nx.weakly_connected_components(g))
    largest_cc = max((len(c) for c in wcc), default=0)
    recip = float(nx.reciprocity(g) or 0.0)
    out_deg = dict(g.out_degree())
    in_deg = dict(g.in_degree())
    max_out = int(max(out_deg.values(), default=0))
    max_in = int(max(in_deg.values(), default=0))
    top_source = max(out_deg.items(), key=lambda x: x[1])[0] if out_deg else ""
    top_sink = max(in_deg.items(), key=lambda x: x[1])[0] if in_deg else ""
    hub_out_ratio = float(max_out / max(1, n - 1))
    hub_in_ratio = float(max_in / max(1, n - 1))
    density = float(nx.density(g))
    largest_ratio = float(largest_cc / max(1, n))

    flags: List[str] = []
    if hub_out_ratio >= 0.25:
        flags.append("STRONG_SOURCE_HUB")
    if hub_in_ratio >= 0.25:
        flags.append("STRONG_SINK_HUB")
    if recip <= 0.01:
        flags.append("VERY_LOW_RECIPROCITY")
    if len(wcc) >= max(8, int(0.1 * n)):
        flags.append("HIGH_FRAGMENTATION")
    if largest_ratio <= 0.35:
        flags.append("SMALL_GIANT_COMPONENT")
    if density >= 0.02 and n > 200:
        flags.append("UNUSUALLY_DENSE")
    if not flags:
        flags.append("NO_STRONG_TOPO_ANOMALY")

    return {
        "label": label,
        "samples_used": sample_count,
        "nodes": n,
        "edges": m,
        "density": density,
        "components_weak": len(wcc),
        "largest_component_ratio": largest_ratio,
        "reciprocity": recip,
        "max_out_degree": max_out,
        "max_in_degree": max_in,
        "top_source_endpoint": str(top_source),
        "top_sink_endpoint": str(top_sink),
        "hub_out_ratio": hub_out_ratio,
        "hub_in_ratio": hub_in_ratio,
        "anomaly_flags": "|".join(flags),
    }


def _plot_graph(label: str, g: nx.DiGraph, out_png: Path, top_edges: int) -> None:
    if g.number_of_edges() == 0:
        fig = plt.figure(figsize=(10, 7))
        plt.text(0.5, 0.5, f"{label}\nEMPTY GRAPH", ha="center", va="center")
        plt.axis("off")
        fig.savefig(out_png, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return

    edges_sorted = sorted(g.edges(data=True), key=lambda x: int(x[2].get("weight", 1)), reverse=True)
    edges_sel = edges_sorted[:top_edges] if top_edges > 0 else edges_sorted
    h = nx.DiGraph()
    for u, v, d in edges_sel:
        h.add_edge(u, v, **d)

    deg_w = dict(h.degree(weight="weight"))
    sizes = [40 + 20 * math.sqrt(max(1.0, float(deg_w.get(n, 1.0)))) for n in h.nodes()]
    colors = ["#dc2626" if h.out_degree(n) > h.in_degree(n) else "#2563eb" for n in h.nodes()]
    pos = nx.spring_layout(h, k=0.6, seed=42)

    fig = plt.figure(figsize=(12, 9))
    nx.draw_networkx_nodes(h, pos, node_size=sizes, node_color=colors, alpha=0.88, linewidths=0.4, edgecolors="#111827")
    nx.draw_networkx_edges(h, pos, arrows=True, alpha=0.35, width=0.8, edge_color="#475569")
    plt.title(f"{label} Topology (top {len(edges_sel)} edges)")
    plt.axis("off")
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze CICIDS2017 attack topology by SrcIP:SrcPort -> DstIP:DstPort."
    )
    parser.add_argument("--data-dir", default="/home/data/2017")
    parser.add_argument("--out-dir", default="outputs/analysis/2017_attack_topology")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-samples-per-attack", type=int, default=80000)
    parser.add_argument("--top-edges-for-plot", type=int, default=300)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading CICIDS2017 raw files ...", flush=True)
    df = _read_all_frames(data_dir)
    total = len(df)
    attack_df = df[df["Label"] != "BENIGN"].copy()
    print(
        f"      rows_total={total} attack_rows={len(attack_df)} attack_labels={attack_df['Label'].nunique()}",
        flush=True,
    )

    print("[2/4] Building topology per attack label ...", flush=True)
    metrics_rows: List[Dict[str, object]] = []
    for label, grp in attack_df.groupby("Label", sort=True):
        use_df = grp
        if args.max_samples_per_attack > 0 and len(grp) > args.max_samples_per_attack:
            idx = rng.choice(len(grp), size=args.max_samples_per_attack, replace=False)
            use_df = grp.iloc[idx]
        g = _build_attack_graph(use_df)
        row = _graph_metrics(label=label, g=g, sample_count=len(use_df))
        metrics_rows.append(row)
        png_name = f"{_safe_name(label)}.png"
        _plot_graph(label=label, g=g, out_png=plot_dir / png_name, top_edges=args.top_edges_for_plot)
        print(
            f"      {label}: samples={len(use_df)} nodes={row['nodes']} edges={row['edges']} flags={row['anomaly_flags']}",
            flush=True,
        )

    metrics_df = pd.DataFrame(metrics_rows).sort_values(
        by=["hub_out_ratio", "hub_in_ratio", "components_weak", "edges"], ascending=False
    )
    metrics_csv = out_dir / "attack_topology_metrics.csv"
    metrics_df.to_csv(metrics_csv, index=False)

    print("[3/4] Writing anomaly summary markdown ...", flush=True)
    md_path = out_dir / "attack_topology_anomaly_report.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# CICIDS2017 Attack Topology Anomaly Report\n\n")
        f.write("构图规则：`SrcIP:SrcPort -> DstIP:DstPort`（有向图，边权为流条数）。\n\n")
        f.write(f"- total_rows: {total}\n")
        f.write(f"- attack_rows: {len(attack_df)}\n")
        f.write(f"- attack_label_count: {attack_df['Label'].nunique()}\n")
        f.write(f"- max_samples_per_attack: {args.max_samples_per_attack}\n")
        f.write(f"- plot_dir: `{plot_dir}`\n\n")
        f.write("## Per Attack Metrics\n\n")
        f.write(
            "| Label | Samples | Nodes | Edges | Reciprocity | Components | LargestCCRatio | TopSource | TopSink | HubOutRatio | HubInRatio | Flags |\n"
        )
        f.write("|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---|\n")
        for r in metrics_df.to_dict(orient="records"):
            f.write(
                f"| {r['label']} | {int(r['samples_used'])} | {int(r['nodes'])} | {int(r['edges'])} "
                f"| {float(r['reciprocity']):.4f} | {int(r['components_weak'])} | {float(r['largest_component_ratio']):.4f} "
                f"| {r['top_source_endpoint']} | {r['top_sink_endpoint']} "
                f"| {float(r['hub_out_ratio']):.4f} | {float(r['hub_in_ratio']):.4f} | {r['anomaly_flags']} |\n"
            )
        f.write("\n")
        f.write("## Reading Guide\n\n")
        f.write("- `STRONG_SOURCE_HUB`: 可能是少量源端点向大量目标扫描/洪泛。\n")
        f.write("- `STRONG_SINK_HUB`: 可能是大量源端点集中攻击同一目标端点。\n")
        f.write("- `VERY_LOW_RECIPROCITY`: 通常是单向攻击流特征明显。\n")
        f.write("- `HIGH_FRAGMENTATION`: 拓扑高度碎片化，可能多源多点并发或短时爆发。\n")
        f.write("- `SMALL_GIANT_COMPONENT`: 缺少主连通团，通常不是稳定业务拓扑。\n")

    print("[4/4] Done.", flush=True)
    print(f"      metrics_csv={metrics_csv}", flush=True)
    print(f"      report_md={md_path}", flush=True)
    print(f"      plots_dir={plot_dir}", flush=True)


if __name__ == "__main__":
    main()

