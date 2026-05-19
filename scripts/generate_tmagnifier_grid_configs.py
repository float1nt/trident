#!/usr/bin/env python3
"""
Generate YAML experiment configs for a TMagnifier (DBSCAN / buffer) grid.

Baseline: same family as configs/experiments/fpr_grid_from_snapshot_110942/_snapshot_base.yaml
(use --base to point at any compatible full config).

Default Cartesian product varies:
  - tmagnifier.dbscan_eps
  - tmagnifier.dbscan_min_samples

Optional axes (set tuples with more than one value to expand the grid):
  - CLUSTER_TRIGGER_SIZES
  - NEW_CLASS_MIN_SIZES
  - MAX_UNKNOWN_BUFFERS

Usage:
  python3 scripts/generate_tmagnifier_grid_configs.py --dry-run
  python3 scripts/generate_tmagnifier_grid_configs.py --clean

Batch runs:
  for c in configs/experiments/tmagnifier_grid_snapshot_110942/grid_*.yaml; do
    python3 main.py --config "$c"
  done
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRID_DIR = REPO_ROOT / "configs/experiments/tmagnifier_grid_snapshot_110942"
DEFAULT_BASE_YAML = REPO_ROOT / "configs/experiments/fpr_grid_from_snapshot_110942/_snapshot_base.yaml"

# ---- Edit these to shrink/expand the search ----
DEFAULT_DBSCAN_EPS = (1.3, 1.4, 1.5, 1.6)
DEFAULT_DBSCAN_MIN_SAMPLES = (10, 15, 20)
# Singletons by default (add values to multiply grid size).
CLUSTER_TRIGGER_SIZES = (120,)
NEW_CLASS_MIN_SIZES = (500,)
MAX_UNKNOWN_BUFFERS = (30000,)
# -----------------------------------------------


def _eps_tag(eps: float) -> str:
    s = ("%g" % eps).replace(".", "p").replace("-", "m")
    return f"eps{s}"


def _int_tag(prefix: str, n: int) -> str:
    return f"{prefix}{int(n)}"


def _deep_copy(d: Dict[str, Any]) -> Dict[str, Any]:
    return yaml.safe_load(yaml.safe_dump(d, sort_keys=False))


Combo = Tuple[float, int, int, int, int]


def iter_grid(
    eps_list: Iterable[float],
    min_list: Iterable[int],
    trig_list: Iterable[int],
    nc_list: Iterable[int],
    buf_list: Iterable[int],
) -> Iterable[Combo]:
    return itertools.product(eps_list, min_list, trig_list, nc_list, buf_list)


def apply_combo(cfg: Dict[str, Any], eps: float, m: int, trig: int, nc: int, buf: int) -> None:
    tm = cfg.setdefault("tmagnifier", {})
    tm["dbscan_eps"] = float(eps)
    tm["dbscan_min_samples"] = int(m)
    tm["cluster_trigger_size"] = int(trig)
    tm["new_class_min_size"] = int(nc)
    tm["max_unknown_buffer"] = int(buf)

    stem_parts = [_eps_tag(eps), _int_tag("m", m)]
    if len(CLUSTER_TRIGGER_SIZES) > 1 or trig != CLUSTER_TRIGGER_SIZES[0]:
        stem_parts.append(_int_tag("trig", trig))
    if len(NEW_CLASS_MIN_SIZES) > 1 or nc != NEW_CLASS_MIN_SIZES[0]:
        stem_parts.append(_int_tag("nc", nc))
    if len(MAX_UNKNOWN_BUFFERS) > 1 or buf != MAX_UNKNOWN_BUFFERS[0]:
        stem_parts.append(_int_tag("ub", buf))

    cfg["description"] = "tmag_grid_" + "_".join(stem_parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Write tmagnifier grid_*.yaml under --grid-dir.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--clean", action="store_true", help="Remove existing grid_*.yaml first")
    ap.add_argument(
        "--base",
        type=Path,
        default=DEFAULT_BASE_YAML,
        help="Baseline YAML path",
    )
    ap.add_argument("--grid-dir", type=Path, default=DEFAULT_GRID_DIR, help="Output directory")
    args = ap.parse_args()

    base_yaml = args.base.expanduser().resolve()
    grid_dir = args.grid_dir.expanduser().resolve()
    if not base_yaml.is_file():
        raise SystemExit(f"Missing --base file: {base_yaml}")

    with open(base_yaml, "r", encoding="utf-8") as f:
        base: Dict[str, Any] = yaml.safe_load(f)

    combos = list(
        iter_grid(
            DEFAULT_DBSCAN_EPS,
            DEFAULT_DBSCAN_MIN_SAMPLES,
            CLUSTER_TRIGGER_SIZES,
            NEW_CLASS_MIN_SIZES,
            MAX_UNKNOWN_BUFFERS,
        )
    )

    total_mult = (
        len(DEFAULT_DBSCAN_EPS)
        * len(DEFAULT_DBSCAN_MIN_SAMPLES)
        * len(CLUSTER_TRIGGER_SIZES)
        * len(NEW_CLASS_MIN_SIZES)
        * len(MAX_UNKNOWN_BUFFERS)
    )
    if args.dry_run:
        print(f"Would write {len(combos)} configs (expected product={total_mult}) to {grid_dir}")
        print(f"Baseline: {base_yaml.relative_to(REPO_ROOT)}")
        return

    grid_dir.mkdir(parents=True, exist_ok=True)
    if args.clean:
        for p in grid_dir.glob("grid_*.yaml"):
            p.unlink()

    for eps, m, trig, nc, buf in combos:
        cfg = _deep_copy(base)
        apply_combo(cfg, eps, m, trig, nc, buf)
        tm = cfg.get("tmagnifier") or {}
        stem = "_".join(
            [
                _eps_tag(float(tm["dbscan_eps"])),
                _int_tag("m", int(tm["dbscan_min_samples"])),
            ]
        )
        if len(CLUSTER_TRIGGER_SIZES) > 1:
            stem += "_" + _int_tag("trig", int(tm["cluster_trigger_size"]))
        if len(NEW_CLASS_MIN_SIZES) > 1:
            stem += "_" + _int_tag("nc", int(tm["new_class_min_size"]))
        if len(MAX_UNKNOWN_BUFFERS) > 1:
            stem += "_" + _int_tag("ub", int(tm["max_unknown_buffer"]))
        out_path = grid_dir / f"grid_{stem}.yaml"
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        print(out_path.relative_to(REPO_ROOT))

    print(f"Wrote {len(combos)} configs.")


if __name__ == "__main__":
    main()
