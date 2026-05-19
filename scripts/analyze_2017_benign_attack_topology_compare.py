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
        df["DayFile"] = name
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _sample_df(df: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    if n <= 0 or len(df) <= n:
        return df
    idx = rng.choice(len(df), size=n, replace=False)
    return df.iloc[idx]


def _build_graph(df_part: pd.DataFrame) -> nx.DiGraph:
    src = df_part["SrcIP"].astype(str).str.strip() + ":" + df_part["SrcPort"].astype(str).str.strip()
    dst = df_part["DstIP"].astype(str).str.strip() + ":" + df_part["DstPort"].astype(str).str.strip()
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


def _metrics(name: str, g: nx.DiGraph, samples: int) -> Dict[str, object]:
    n = g.number_of_nodes()
    m = g.number_of_edges()
    if n == 0:
        return {
            "group": name,
            "samples_used": samples,
            "nodes": 0,
            "edges": 0,
            "density": 0.0,
            "components_weak": 0,
            "largest_component_ratio": 0.0,
            "reciprocity": 0.0,
            "max_out_degree": 0,
            "max_in_degree": 0,
            "hub_out_ratio": 0.0,
            "hub_in_ratio": 0.0,
            "flags": "EMPTY",
        }

    wcc = list(nx.weakly_connected_components(g))
    largest_cc = max((len(c) for c in wcc), default=0)
    recip = float(nx.reciprocity(g) or 0.0)
    out_deg = dict(g.out_degree())
    in_deg = dict(g.in_degree())
    max_out = int(max(out_deg.values(), default=0))
    max_in = int(max(in_deg.values(), default=0))
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
        "group": name,
        "samples_used": samples,
        "nodes": n,
        "edges": m,
        "density": density,
        "components_weak": len(wcc),
        "largest_component_ratio": largest_ratio,
        "reciprocity": recip,
        "max_out_degree": max_out,
        "max_in_degree": max_in,
        "hub_out_ratio": hub_out_ratio,
        "hub_in_ratio": hub_in_ratio,
        "flags": "|".join(flags),
    }


def _plot_graph(name: str, g: nx.DiGraph, out_png: Path, top_edges: int) -> None:
    if g.number_of_edges() == 0:
        fig = plt.figure(figsize=(10, 7))
        plt.text(0.5, 0.5, f"{name}\nEMPTY GRAPH", ha="center", va="center")
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
    colors = ["#16a34a" if "BENIGN" in name else "#dc2626" for _ in h.nodes()]
    pos = nx.spring_layout(h, k=0.6, seed=42)

    fig = plt.figure(figsize=(12, 9))
    nx.draw_networkx_nodes(h, pos, node_size=sizes, node_color=colors, alpha=0.88, linewidths=0.4, edgecolors="#111827")
    nx.draw_networkx_edges(h, pos, arrows=True, alpha=0.35, width=0.8, edge_color="#475569")
    plt.title(f"{name} Topology (top {len(edges_sel)} edges)")
    plt.axis("off")
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare BENIGN vs ATTACK topology on CICIDS2017.")
    parser.add_argument("--data-dir", default="/home/data/2017")
    parser.add_argument("--out-dir", default="outputs/analysis/2017_benign_attack_topology_compare")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-benign-samples", type=int, default=120000)
    parser.add_argument("--max-attack-samples", type=int, default=120000)
    parser.add_argument("--top-edges-for-plot", type=int, default=400)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    data_dir = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plot_dir = out_dir / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)

    print("[1/4] Loading data ...", flush=True)
    df = _read_all_frames(data_dir)
    benign_df = df[df["Label"] == "BENIGN"].copy()
    attack_df = df[df["Label"] != "BENIGN"].copy()
    benign_use = _sample_df(benign_df, args.max_benign_samples, rng)
    attack_use = _sample_df(attack_df, args.max_attack_samples, rng)
    print(
        f"      total={len(df)} benign={len(benign_df)} attack={len(attack_df)} "
        f"| benign_used={len(benign_use)} attack_used={len(attack_use)}",
        flush=True,
    )

    print("[2/4] Building graphs ...", flush=True)
    g_benign = _build_graph(benign_use)
    g_attack = _build_graph(attack_use)

    m_benign = _metrics("BENIGN_ALL", g_benign, len(benign_use))
    m_attack = _metrics("ATTACK_ALL", g_attack, len(attack_use))
    metrics_df = pd.DataFrame([m_benign, m_attack])

    metrics_csv = out_dir / "benign_attack_topology_metrics.csv"
    metrics_df.to_csv(metrics_csv, index=False)

    _plot_graph("BENIGN_ALL", g_benign, plot_dir / "BENIGN_ALL.png", top_edges=args.top_edges_for_plot)
    _plot_graph("ATTACK_ALL", g_attack, plot_dir / "ATTACK_ALL.png", top_edges=args.top_edges_for_plot)

    print("[3/4] Building day-level BENIGN baseline ...", flush=True)
    day_rows: List[Dict[str, object]] = []
    for day, grp in benign_df.groupby("DayFile", sort=True):
        part = _sample_df(grp, min(30000, len(grp)), rng)
        g_day = _build_graph(part)
        row = _metrics(f"BENIGN_{day}", g_day, len(part))
        day_rows.append(row)
        _plot_graph(f"BENIGN_{day}", g_day, plot_dir / f"BENIGN_{_safe_name(day)}.png", top_edges=250)
    day_df = pd.DataFrame(day_rows)
    day_csv = out_dir / "benign_daily_topology_metrics.csv"
    day_df.to_csv(day_csv, index=False)

    print("[4/4] Writing compare report ...", flush=True)
    md_path = out_dir / "benign_attack_topology_compare_report.md"
    with md_path.open("w", encoding="utf-8") as f:
        f.write("# CICIDS2017 BENIGN vs ATTACK Topology Comparison\n\n")
        f.write(
            f"- benign_used={len(benign_use)}, attack_used={len(attack_use)}, "
            f"top_edges_for_plot={args.top_edges_for_plot}\n"
        )
        f.write(f"- plots_dir: `{plot_dir}`\n\n")

        f.write("## Global Compare\n\n")
        f.write("| Group | Samples | Nodes | Edges | Reciprocity | Components | LargestCCRatio | HubOutRatio | HubInRatio | Flags |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|\n")
        for row in metrics_df.to_dict(orient="records"):
            f.write(
                f"| {row['group']} | {int(row['samples_used'])} | {int(row['nodes'])} | {int(row['edges'])} "
                f"| {float(row['reciprocity']):.4f} | {int(row['components_weak'])} | {float(row['largest_component_ratio']):.4f} "
                f"| {float(row['hub_out_ratio']):.4f} | {float(row['hub_in_ratio']):.4f} | {row['flags']} |\n"
            )

        f.write("\n## BENIGN Daily Baseline\n\n")
        f.write("| Group | Samples | Nodes | Edges | Reciprocity | Components | LargestCCRatio | HubOutRatio | HubInRatio | Flags |\n")
        f.write("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|\n")
        for row in day_df.to_dict(orient="records"):
            f.write(
                f"| {row['group']} | {int(row['samples_used'])} | {int(row['nodes'])} | {int(row['edges'])} "
                f"| {float(row['reciprocity']):.4f} | {int(row['components_weak'])} | {float(row['largest_component_ratio']):.4f} "
                f"| {float(row['hub_out_ratio']):.4f} | {float(row['hub_in_ratio']):.4f} | {row['flags']} |\n"
            )

    print(f"      metrics_csv={metrics_csv}", flush=True)
    print(f"      benign_daily_csv={day_csv}", flush=True)
    print(f"      report_md={md_path}", flush=True)
    print(f"      plots_dir={plot_dir}", flush=True)


if __name__ == "__main__":
    main()

