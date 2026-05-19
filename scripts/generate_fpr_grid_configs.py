#!/usr/bin/env python3
"""
Generate YAML experiment configs for an FPR-focused grid search.

Defaults follow configs/experiments/fpr_grid_snapshot_20260515/.
Override baseline and output folder with --base and --grid-dir (e.g. from a newer
outputs/runs/.../config_snapshot.yaml-derived _snapshot_base.yaml).

Grid size = len(scales) * len(quantiles) * len(risks) * len(drift_scores)
(default Cartesian product: 54 configs).

Varying axes (optimize risk_false_positive_rate in metrics.json — lower is better):
  - runtime.benign_accept_scale
  - tscissors.evt_quantile
  - tscissors.evt_risk
  - tsieve.increment_drift_min_score

Usage:
  python3 scripts/generate_fpr_grid_configs.py
  python3 scripts/generate_fpr_grid_configs.py --dry-run
  python3 scripts/generate_fpr_grid_configs.py \\
    --base configs/experiments/fpr_grid_from_snapshot_110942/_snapshot_base.yaml \\
    --grid-dir configs/experiments/fpr_grid_from_snapshot_110942

Batch runs (example):
  for c in configs/experiments/fpr_grid_from_snapshot_110942/grid_*.yaml; do
    python3 main.py --config "$c"
  done

After runs:
  python3 scripts/summarize_grid_fpr.py
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRID_DIR = REPO_ROOT / "configs/experiments/fpr_grid_snapshot_20260515"
DEFAULT_BASE_YAML = DEFAULT_GRID_DIR / "_snapshot_base.yaml"

# Edit these lists to shrink/expand the search.
DEFAULT_BENIGN_ACCEPT_SCALES = (0.30, 0.34, 0.38)
DEFAULT_EVT_QUANTILES = (0.95, 0.96, 0.97)
DEFAULT_EVT_RISKS = (0.001, 0.0015, 0.002)
DEFAULT_DRIFT_MIN_SCORES = (0.10, 0.12)


def _num_tag(prefix: str, x: float) -> str:
    """Stable filename fragment, e.g. b0p34 q0p97 r0p0015 d0p12"""
    if abs(x - round(x)) < 1e-9:
        return f"{prefix}{int(round(x))}"
    s = ("%g" % x).replace(".", "p").replace("-", "m")
    return f"{prefix}{s}"


def _deep_copy(d: Dict[str, Any]) -> Dict[str, Any]:
    return yaml.safe_load(yaml.safe_dump(d, sort_keys=False))


def iter_grid(
    scales: Iterable[float],
    quantiles: Iterable[float],
    risks: Iterable[float],
    drift_scores: Iterable[float],
) -> Iterable[Tuple[float, float, float, float]]:
    return itertools.product(scales, quantiles, risks, drift_scores)


def apply_combo(cfg: Dict[str, Any], b: float, q: float, r: float, d: float) -> None:
    cfg.setdefault("runtime", {})["benign_accept_scale"] = b
    cfg.setdefault("tscissors", {})["evt_quantile"] = q
    cfg.setdefault("tscissors", {})["evt_risk"] = r
    cfg.setdefault("tsieve", {})["increment_drift_min_score"] = d
    parts = [_num_tag("b", b), _num_tag("q", q), _num_tag("r", r), _num_tag("d", d)]
    cfg["description"] = "fpr_grid_" + "_".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Write grid_*.yaml under --grid-dir (FPR-focused Cartesian grid).")
    ap.add_argument("--dry-run", action="store_true", help="Print count only")
    ap.add_argument(
        "--clean",
        action="store_true",
        help="Remove existing grid_*.yaml in the grid directory before writing",
    )
    ap.add_argument(
        "--base",
        type=Path,
        default=DEFAULT_BASE_YAML,
        help=f"YAML baseline (default: {DEFAULT_BASE_YAML.relative_to(REPO_ROOT)})",
    )
    ap.add_argument(
        "--grid-dir",
        type=Path,
        default=DEFAULT_GRID_DIR,
        help=f"Directory for grid_*.yaml (default: {DEFAULT_GRID_DIR.relative_to(REPO_ROOT)})",
    )
    args = ap.parse_args()

    base_yaml = args.base.expanduser().resolve()
    grid_dir = args.grid_dir.expanduser().resolve()
    if not base_yaml.is_file():
        raise SystemExit(f"Missing --base file: {base_yaml}")

    with open(base_yaml, "r", encoding="utf-8") as f:
        base: Dict[str, Any] = yaml.safe_load(f)

    combos = list(
        iter_grid(
            DEFAULT_BENIGN_ACCEPT_SCALES,
            DEFAULT_EVT_QUANTILES,
            DEFAULT_EVT_RISKS,
            DEFAULT_DRIFT_MIN_SCORES,
        )
    )
    if args.dry_run:
        print(f"Would write {len(combos)} configs to {grid_dir}")
        print(f"Baseline: {base_yaml.relative_to(REPO_ROOT)}")
        return

    grid_dir.mkdir(parents=True, exist_ok=True)

    if args.clean:
        for p in grid_dir.glob("grid_*.yaml"):
            p.unlink()

    for b, q, r, d in combos:
        cfg = _deep_copy(base)
        apply_combo(cfg, b, q, r, d)
        stem = "_".join([_num_tag("b", b), _num_tag("q", q), _num_tag("r", r), _num_tag("d", d)])
        out_path = grid_dir / f"grid_{stem}.yaml"
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        print(out_path.relative_to(REPO_ROOT))

    print(f"Wrote {len(combos)} configs.")


if __name__ == "__main__":
    main()
