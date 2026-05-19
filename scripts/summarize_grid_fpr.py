#!/usr/bin/env python3
"""
Summarize risk_false_positive_rate (and FNR) over finished runs.

Reads each outputs/runs/*/config_snapshot.yaml + metrics.json.
Optional: only runs whose description starts with fpr_grid_ (default).

Usage:
  python3 scripts/summarize_grid_fpr.py
  python3 scripts/summarize_grid_fpr.py --runs-root outputs/runs --top 15
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs-root", type=Path, default=REPO_ROOT / "outputs" / "runs")
    ap.add_argument(
        "--prefix",
        default="fpr_grid_",
        help="Only include runs whose config description starts with this (empty = all)",
    )
    ap.add_argument("--top", type=int, default=20, help="How many rows to print")
    args = ap.parse_args()

    rows: List[Tuple[float, float, float, float, float, float, str]] = []
    for run_dir in sorted(args.runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        cfg_path = run_dir / "config_snapshot.yaml"
        met_path = run_dir / "metrics.json"
        cfg = _load(cfg_path)
        if cfg is None:
            continue
        desc = str(cfg.get("description") or "")
        if args.prefix and not desc.startswith(args.prefix):
            continue
        if not met_path.is_file():
            continue
        with open(met_path, "r", encoding="utf-8") as f:
            met = json.load(f)
        fpr = float(met.get("risk_false_positive_rate", float("nan")))
        fnr = float(met.get("risk_false_negative_rate", float("nan")))
        rt = cfg.get("runtime") or {}
        ts = cfg.get("tscissors") or {}
        tv = cfg.get("tsieve") or {}
        b = float(rt.get("benign_accept_scale", float("nan")))
        q = float(ts.get("evt_quantile", float("nan")))
        r = float(ts.get("evt_risk", float("nan")))
        d = float(tv.get("increment_drift_min_score", float("nan")))
        rows.append((fpr, fnr, b, q, r, d, str(run_dir.name)))

    rows.sort(key=lambda x: x[0])
    print(f"runs_root={args.runs_root}  matched={len(rows)}  sort_by=risk_false_positive_rate (↑ low FPR)\n")
    print(f"{'FPR%':>9} {'FNR%':>9} {'b':>7} {'evt_q':>7} {'evt_r':>9} {'drift':>7}  run_dir")
    for fpr, fnr, b, q, r, d, name in rows[: max(0, args.top)]:
        print(
            f"{fpr * 100:9.4f} {fnr * 100:9.4f} {b:7g} {q:7g} {r:9g} {d:7g}  {name}"
        )


if __name__ == "__main__":
    main()
