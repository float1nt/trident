#!/usr/bin/env python3
"""Rebuild canonical assignment + label distribution for an existing run.

Fixes mismatch when learner_label_distribution.csv used cumulative counts
(including creation-cluster rows) but sample_learner_assignments.csv only
exported stream-phase predictions.

Usage:
  PYTHONPATH=. python3 scripts/rebuild_run_assignment_artifacts.py outputs/runs/<run_id>
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Set

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trident_stream.experiment import TridentStreamingExperiment
from trident_stream.utils import is_benign_label, split_year_label


def _reconstruct_init_creation_indices(cfg: dict, data: pd.DataFrame) -> Dict[str, List[int]]:
    """Mirror init learner binding row indices from config + filtered data."""
    stream_cfg = cfg["stream"]
    tsieve_cfg = cfg["tsieve"]
    init_ratio = float(stream_cfg["init_ratio"])
    init_end = int(len(data) * init_ratio)
    init_end = max(init_end, 5000)
    init_end = min(init_end, len(data) - 1)
    init_benign_count_cfg = int(stream_cfg.get("init_benign_count", 0) or 0)

    if stream_cfg["init_known_mode"] == "benign_only" and init_benign_count_cfg > 0:
        full_mask = data["LabelNorm"].map(is_benign_label).values
        init_benign_year = str(stream_cfg.get("init_benign_year", "")).strip()
        if init_benign_year:
            year_mask = data["LabelNorm"].map(
                lambda x: split_year_label(str(x))[0] == init_benign_year
            ).values
            full_mask = full_mask & year_mask
        eligible_idx = np.flatnonzero(full_mask)
        if len(eligible_idx) > 0:
            target_n = min(init_benign_count_cfg, int(len(eligible_idx)))
            required_end = int(eligible_idx[target_n - 1] + 1)
            init_end = max(init_end, required_end)
            init_end = min(init_end, len(data) - 1)

    df_init = data.iloc[:init_end].copy()
    df_init["_creation_row_index"] = np.arange(init_end, dtype=np.int64)

    if stream_cfg["init_known_mode"] == "benign_only":
        mask = df_init["LabelNorm"].map(is_benign_label).values
        init_benign_year = str(stream_cfg.get("init_benign_year", "")).strip()
        if init_benign_year:
            year_mask = df_init["LabelNorm"].map(
                lambda x: split_year_label(str(x))[0] == init_benign_year
            ).values
            mask = mask & year_mask
        df_init = df_init.loc[mask].reset_index(drop=True)
        if init_benign_count_cfg > 0:
            keep_n = min(init_benign_count_cfg, len(df_init))
            df_init = df_init.iloc[:keep_n].reset_index(drop=True)

    out: Dict[str, List[int]] = {}
    min_class = int(tsieve_cfg["min_class_samples"])
    for label in df_init["LabelNorm"].unique().tolist():
        idx = np.where(df_init["LabelNorm"].values == label)[0]
        if len(idx) < min_class:
            continue
        out[str(label)] = [
            int(df_init["_creation_row_index"].iloc[int(j)]) for j in idx
        ]
    return out


def _reconstruct_new_creation_indices(
    stream_df: pd.DataFrame,
    data: pd.DataFrame,
    creation_df: pd.DataFrame,
    used: Set[int],
) -> Dict[str, List[int]]:
    """Claim UNKNOWN stream rows to match creation label counts (birth order)."""
    label_col = "LabelNorm" if "LabelNorm" in data.columns else "Label"
    flow = data.copy()
    flow["row_index"] = np.arange(len(flow), dtype=np.int64)

    stream_owner = dict(
        zip(
            stream_df["row_index"].astype(int),
            stream_df["assigned_learner"].astype(str),
        )
    )
    unknown_mask = flow["row_index"].map(
        lambda ri: stream_owner.get(int(ri), "UNKNOWN") == "UNKNOWN"
    )
    pool = flow.loc[unknown_mask & (~flow["row_index"].isin(list(used)))].copy()

    out: Dict[str, List[int]] = {}
    new_rows = creation_df.loc[creation_df["stage"].astype(str) == "new"]
    for _, crow in new_rows.iterrows():
        ln = str(crow["learner_name"])
        dist = json.loads(str(crow["label_distribution_json"]))
        picked: List[int] = []
        for lbl, need in sorted(dist.items(), key=lambda x: -int(x[1])):
            need_i = int(need)
            if need_i <= 0:
                continue
            cand = pool.loc[pool[label_col].astype(str) == str(lbl), "row_index"].astype(int)
            for ri in cand.head(need_i).tolist():
                if int(ri) in used:
                    continue
                picked.append(int(ri))
                used.add(int(ri))
                if len(picked) >= int(crow["sample_count"]):
                    break
            pool = pool.loc[~pool["row_index"].isin(picked)]
            if len(picked) >= int(crow["sample_count"]):
                break
        out[ln] = picked
    return out


def _build_assign_from_stream_and_creation(
    stream_df: pd.DataFrame,
    creation_idx: Dict[str, List[int]],
) -> pd.DataFrame:
    row_owner: Dict[int, str] = {}
    stream_ts: Dict[int, str] = {}
    for _, row in stream_df.iterrows():
        ri = int(row["row_index"])
        row_owner[ri] = str(row["assigned_learner"])
        if "timestamp" in stream_df.columns:
            stream_ts[ri] = str(row.get("timestamp", "") or "")

    for learner_name, indices in creation_idx.items():
        ln = str(learner_name)
        for ri in indices:
            row_i = int(ri)
            cur = row_owner.get(row_i)
            if cur is None or cur == "UNKNOWN":
                row_owner[row_i] = ln

    stream_pairs = set(
        zip(
            stream_df["row_index"].astype(int),
            stream_df["assigned_learner"].astype(str),
        )
    )
    rows = []
    for ri in sorted(row_owner):
        ln = row_owner[ri]
        phase = "stream" if (ri, ln) in stream_pairs else "creation_fill"
        rows.append(
            {
                "row_index": ri,
                "assigned_learner": ln,
                "phase": phase,
                "timestamp": stream_ts.get(ri, ""),
            }
        )
    return pd.DataFrame(rows)


def _load_creation_idx(run_dir: Path, cfg: dict, data: pd.DataFrame, stream_df: pd.DataFrame) -> Dict[str, List[int]]:
    creation_path = run_dir / "learner_creation_row_indices.json"
    if creation_path.exists():
        raw = json.loads(creation_path.read_text(encoding="utf-8"))
        return {str(k): [int(x) for x in v] for k, v in raw.items()}

    creation_csv = run_dir / "learner_creation_distribution.csv"
    if not creation_csv.exists():
        raise FileNotFoundError(
            f"Need {creation_path.name} or {creation_csv.name} to reconstruct creation rows."
        )
    creation_df = pd.read_csv(creation_csv)
    used: Set[int] = set()
    creation_idx = _reconstruct_init_creation_indices(cfg, data)
    for indices in creation_idx.values():
        used.update(indices)
    creation_idx.update(
        _reconstruct_new_creation_indices(stream_df, data, creation_df, used)
    )
    return creation_idx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--write-creation-indices",
        action="store_true",
        help="Also persist learner_creation_row_indices.json for future rebuilds.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    cfg = yaml.safe_load((run_dir / "config_snapshot.yaml").read_text(encoding="utf-8"))
    logger = logging.getLogger("rebuild_assign")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    assign_path = run_dir / "sample_learner_assignments.csv"
    if not assign_path.exists():
        raise FileNotFoundError(assign_path)

    exp = TridentStreamingExperiment(cfg, logger)
    data, _, _ = exp._load_dataset()

    stream_df = pd.read_csv(assign_path)
    creation_idx: Dict[str, List[int]] | None = None
    if "phase" in stream_df.columns and (stream_df["phase"].astype(str) == "creation_fill").any():
        print("[info] assignments already canonical; rebuilding profile only", flush=True)
        assign_export_df = stream_df
    else:
        stream_only = (
            stream_df[stream_df["phase"].astype(str) == "stream"].copy()
            if "phase" in stream_df.columns
            else stream_df.copy()
        )
        creation_idx = _load_creation_idx(run_dir, cfg, data, stream_only)
        assign_export_df = _build_assign_from_stream_and_creation(stream_only, creation_idx)
        assign_export_df.to_csv(assign_path, index=False)
        print(f"[ok] wrote canonical assignments: {assign_path}", flush=True)
        if args.write_creation_indices:
            out_path = run_dir / "learner_creation_row_indices.json"
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(
                    {k: sorted(v) for k, v in creation_idx.items()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
            print(f"[ok] wrote {out_path}", flush=True)
    cols = ["row_index", "assigned_learner"]
    if "phase" in assign_export_df.columns:
        cols.append("phase")
    profile_rows = exp._build_profile_rows_from_assignment_df(data, assign_export_df[cols])
    profile_path = run_dir / "learner_label_distribution.csv"
    pd.DataFrame(profile_rows).to_csv(profile_path, index=False)
    print(f"[ok] wrote {profile_path} ({len(profile_rows)} learners)", flush=True)

    label_df = pd.read_csv(profile_path)
    a_counts = assign_export_df.groupby("assigned_learner").size()
    l_counts = label_df.set_index("learner_name")["total_assigned_samples"]
    merged = pd.DataFrame({"assign": a_counts, "label": l_counts}).fillna(0).astype(int)
    merged["diff"] = merged["label"] - merged["assign"]
    bad = merged[merged["diff"] != 0]
    if len(bad):
        print(f"[warn] {len(bad)} learner(s) still differ:", flush=True)
        print(bad.head(10).to_string(), flush=True)
    else:
        print("[ok] assignment counts match label distribution", flush=True)


if __name__ == "__main__":
    main()
