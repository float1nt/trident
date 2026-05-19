#!/usr/bin/env python3
"""
Generate + run FPR/FNR hyperparameter grid, then rank by composite score.

Axes (Cartesian product):
  - runtime.benign_accept_scale
  - tscissors.evt_quantile
  - tscissors.evt_risk
  - tsieve.increment_drift_min_score

Composite objective (minimize): fpr + fnr  (risk_false_positive_rate + risk_false_negative_rate)

Usage:
  python3 scripts/run_hpo_fpr_fnr_grid.py --dry-run
  python3 scripts/run_hpo_fpr_fnr_grid.py --generate-only
  python3 scripts/run_hpo_fpr_fnr_grid.py
  python3 scripts/run_hpo_fpr_fnr_grid.py --skip-existing
"""

from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRID_DIR = REPO_ROOT / "configs/experiments/hpo_compact35_fpr_fnr_20260519"
DEFAULT_BASE_YAML = DEFAULT_GRID_DIR / "_snapshot_base.yaml"
DEFAULT_RESULTS_JSON = REPO_ROOT / "experiments/hpo_compact35_fpr_fnr_20260519.json"

# Focused grid around prior HPO sweet spot (24 combos).
DEFAULT_BENIGN_ACCEPT_SCALES = (0.28, 0.30, 0.34)
DEFAULT_EVT_QUANTILES = (0.95, 0.97)
DEFAULT_EVT_RISKS = (0.001, 0.0015)
DEFAULT_DRIFT_MIN_SCORES = (0.10, 0.12)

DEFAULT_DESC_PREFIX = "hpo_c35_"


def _num_tag(prefix: str, x: float) -> str:
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


def apply_combo(
    cfg: Dict[str, Any],
    b: float,
    q: float,
    r: float,
    d: float,
    desc_prefix: str,
) -> str:
    cfg.setdefault("runtime", {})["benign_accept_scale"] = b
    cfg.setdefault("tscissors", {})["evt_quantile"] = q
    cfg.setdefault("tscissors", {})["evt_risk"] = r
    cfg.setdefault("tsieve", {})["increment_drift_min_score"] = d
    stem = "_".join([_num_tag("b", b), _num_tag("q", q), _num_tag("r", r), _num_tag("d", d)])
    cfg["description"] = desc_prefix + stem
    return stem


def generate_configs(
    base_yaml: Path,
    grid_dir: Path,
    scales: Iterable[float],
    quantiles: Iterable[float],
    risks: Iterable[float],
    drift_scores: Iterable[float],
    clean: bool,
    desc_prefix: str,
) -> List[Path]:
    with open(base_yaml, "r", encoding="utf-8") as f:
        base: Dict[str, Any] = yaml.safe_load(f)
    grid_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        for p in grid_dir.glob("grid_*.yaml"):
            p.unlink()
    paths: List[Path] = []
    for b, q, r, d in iter_grid(scales, quantiles, risks, drift_scores):
        cfg = _deep_copy(base)
        stem = apply_combo(cfg, b, q, r, d, desc_prefix)
        out_path = grid_dir / f"grid_{stem}.yaml"
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
        paths.append(out_path)
    return paths


def _run_has_metrics(run_dir: Path) -> bool:
    return (run_dir / "metrics.json").is_file()


def run_one(config_path: Path, repo_root: Path) -> Tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "main.py", "--config", str(config_path.relative_to(repo_root))],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        return False, tail
    for line in reversed((proc.stdout or "").splitlines()):
        if "[RunID]" in line:
            # not in stdout typically
            pass
    # Find newest run dir matching config name
    cfg_name = config_path.name
    runs_root = repo_root / "outputs" / "runs"
    candidates = sorted(
        runs_root.glob(f"*_{cfg_name}"),
        key=lambda p: p.stat().st_mtime,
    )
    if not candidates:
        return False, "no run directory found"
    return True, candidates[-1].name


def collect_result(repo_root: Path, run_name: str, config_path: Path) -> Dict[str, Any]:
    run_dir = repo_root / "outputs" / "runs" / run_name
    cfg = yaml.safe_load((run_dir / "config_snapshot.yaml").read_text(encoding="utf-8"))
    met = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    summary_path = run_dir / "run_summary.txt"
    learners = None
    if summary_path.is_file():
        for line in summary_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("final_learner_count:"):
                learners = int(line.split(":", 1)[1].strip())
                break
    rt = cfg.get("runtime") or {}
    ts = cfg.get("tscissors") or {}
    tv = cfg.get("tsieve") or {}
    fpr = float(met.get("risk_false_positive_rate", float("nan")))
    fnr = float(met.get("risk_false_negative_rate", float("nan")))
    return {
        "config": config_path.name,
        "run_id": run_name,
        "run_dir": str(run_dir.relative_to(repo_root)),
        "b": float(rt.get("benign_accept_scale", float("nan"))),
        "evt_q": float(ts.get("evt_quantile", float("nan"))),
        "evt_risk": float(ts.get("evt_risk", float("nan"))),
        "drift_min_score": float(tv.get("increment_drift_min_score", float("nan"))),
        "feature_profile": str(rt.get("feature_profile", "")),
        "fpr": fpr,
        "fnr": fnr,
        "fpr_fnr_sum": fpr + fnr,
        "learners": learners,
        "ok": True,
    }


def print_leaderboard(rows: List[Dict[str, Any]], top: int, baseline_sum: float | None) -> None:
    ok_rows = [r for r in rows if r.get("ok")]
    ok_rows.sort(key=lambda r: (float(r.get("fpr_fnr_sum", 9e9)), float(r.get("fpr", 9e9))))
    print(f"\n=== Top {top} by FPR+FNR (lower is better) ===")
    print(f"{'sum%':>8} {'FPR%':>8} {'FNR%':>8} {'b':>6} {'q':>6} {'r':>8} {'d':>6}  run")
    for r in ok_rows[:top]:
        print(
            f"{r['fpr_fnr_sum']*100:8.3f} {r['fpr']*100:8.3f} {r['fnr']*100:8.3f} "
            f"{r['b']:6g} {r['evt_q']:6g} {r['evt_risk']:8g} {r['drift_min_score']:6g}  {r['run_id']}"
        )
    if baseline_sum is not None and ok_rows:
        best = ok_rows[0]
        delta = (best["fpr_fnr_sum"] - baseline_sum) * 100
        print(f"\nBaseline sum={baseline_sum*100:.3f}%  best sum={best['fpr_fnr_sum']*100:.3f}%  delta={delta:+.3f} pp")


def main() -> None:
    ap = argparse.ArgumentParser(description="FPR+FNR grid search for compact35 baseline.")
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE_YAML)
    ap.add_argument("--grid-dir", type=Path, default=DEFAULT_GRID_DIR)
    ap.add_argument("--results-json", type=Path, default=DEFAULT_RESULTS_JSON)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--generate-only", action="store_true")
    ap.add_argument("--clean", action="store_true", help="Remove existing grid_*.yaml before generate")
    ap.add_argument("--skip-existing", action="store_true", help="Skip configs that already have a finished run")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument(
        "--desc-prefix",
        default=DEFAULT_DESC_PREFIX,
        help="Prefix for config description (tags runs in metrics)",
    )
    ap.add_argument(
        "--baseline-fpr",
        type=float,
        default=0.052331009004388924,
        help="Reference FPR from 20260519_085337 run (for reporting)",
    )
    ap.add_argument(
        "--baseline-fnr",
        type=float,
        default=0.08229269327212166,
        help="Reference FNR from 20260519_085337 run",
    )
    args = ap.parse_args()

    base_yaml = args.base.expanduser().resolve()
    grid_dir = args.grid_dir.expanduser().resolve()
    if not base_yaml.is_file():
        raise SystemExit(f"Missing base: {base_yaml}")

    combos = list(
        iter_grid(
            DEFAULT_BENIGN_ACCEPT_SCALES,
            DEFAULT_EVT_QUANTILES,
            DEFAULT_EVT_RISKS,
            DEFAULT_DRIFT_MIN_SCORES,
        )
    )
    if args.dry_run:
        print(f"Grid size={len(combos)}  dir={grid_dir}")
        print(f"Baseline FPR+FNR={(args.baseline_fpr + args.baseline_fnr)*100:.3f}%")
        return

    config_paths = generate_configs(
        base_yaml,
        grid_dir,
        DEFAULT_BENIGN_ACCEPT_SCALES,
        DEFAULT_EVT_QUANTILES,
        DEFAULT_EVT_RISKS,
        DEFAULT_DRIFT_MIN_SCORES,
        clean=args.clean,
        desc_prefix=str(args.desc_prefix),
    )
    print(f"Generated {len(config_paths)} configs under {grid_dir.relative_to(REPO_ROOT)}")

    if args.generate_only:
        return

    baseline_sum = args.baseline_fpr + args.baseline_fnr
    results: List[Dict[str, Any]] = []
    runs_root = REPO_ROOT / "outputs" / "runs"

    for i, cfg_path in enumerate(config_paths, 1):
        cfg_name = cfg_path.name
        if args.skip_existing:
            existing = sorted(runs_root.glob(f"*_{cfg_name}"), key=lambda p: p.stat().st_mtime)
            if existing and _run_has_metrics(existing[-1]):
                run_name = existing[-1].name
                print(f"[{i}/{len(config_paths)}] skip existing {run_name}")
                results.append(collect_result(REPO_ROOT, run_name, cfg_path))
                continue

        print(f"[{i}/{len(config_paths)}] running {cfg_name} ...", flush=True)
        ok, info = run_one(cfg_path, REPO_ROOT)
        if not ok:
            print(f"  FAILED: {info[:500]}")
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            results.append(
                {
                    "config": cfg_name,
                    "ok": False,
                    "error": info,
                    "description": cfg.get("description"),
                }
            )
            continue
        row = collect_result(REPO_ROOT, info, cfg_path)
        results.append(row)
        print(
            f"  ok FPR={row['fpr']*100:.3f}% FNR={row['fnr']*100:.3f}% "
            f"sum={row['fpr_fnr_sum']*100:.3f}% learners={row.get('learners')}"
        )

    args.results_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "grid_dir": str(grid_dir.relative_to(REPO_ROOT)),
        "desc_prefix": str(args.desc_prefix),
        "baseline": {
            "fpr": args.baseline_fpr,
            "fnr": args.baseline_fnr,
            "fpr_fnr_sum": baseline_sum,
        },
        "objective": "minimize risk_false_positive_rate + risk_false_negative_rate",
        "results": results,
    }
    with open(args.results_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\nWrote {args.results_json.relative_to(REPO_ROOT)}")
    print_leaderboard(results, args.top, baseline_sum)


if __name__ == "__main__":
    main()
