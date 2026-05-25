#!/usr/bin/env python3
"""Run Trident with stage-level performance benchmarking.

Writes to the run output directory:
  - trident_performance_benchmark.json
  - trident_performance_benchmark.md
  - performance_metrics.json (stream detect/cluster/retrain breakdown)

Usage:
  python3 scripts/benchmark_trident_performance.py --config configs/config.yaml
  python3 scripts/benchmark_trident_performance.py --config configs/config.yaml --max-rows 50000
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("MPLCONFIGDIR", str(Path("/tmp/mplconfig-trident").resolve()))

from trident_stream.config import build_logger, load_config
from trident_stream.experiment import TridentStreamingExperiment


def build_run_id(config_path: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config_name = Path(config_path).name
    safe_config_name = re.sub(r"[^A-Za-z0-9._-]", "_", config_name)
    return f"{timestamp}_benchmark_{safe_config_name}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=str, default="configs/config.yaml")
    parser.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Optional cap on rows loaded (overrides config runtime.max_rows when > 0).",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    cfg.setdefault("runtime", {})["performance_benchmark"] = True
    if args.max_rows > 0:
        cfg["runtime"]["max_rows"] = int(args.max_rows)
    # Keep enough rows for the streaming phase when benchmarking on a subset.
    stream_cfg = cfg.setdefault("stream", {})
    init_benign = int(stream_cfg.get("init_benign_count", 0) or 0)
    max_rows = int(cfg.get("runtime", {}).get("max_rows", 0) or 0)
    if max_rows > 0 and init_benign >= max_rows:
        stream_cfg["init_benign_count"] = max(1000, max_rows // 4)
        stream_cfg["init_ratio"] = min(float(stream_cfg.get("init_ratio", 0.01)), 0.25)

    run_id = build_run_id(args.config)
    cfg["runtime"]["run_id"] = run_id
    base_output_dir = Path(cfg["paths"]["output_dir"])
    run_output_dir = (base_output_dir / "runs" / run_id).resolve()
    cfg["paths"]["output_dir"] = str(run_output_dir)
    cfg["paths"]["log_file"] = "run.log"

    logger = build_logger(output_dir=run_output_dir, log_file=cfg["paths"]["log_file"])
    logger.info("Performance benchmark enabled. Output dir: %s", run_output_dir)
    TridentStreamingExperiment(cfg=cfg, logger=logger).run()
    logger.info(
        "Benchmark artifacts: %s/trident_performance_benchmark.json",
        run_output_dir,
    )


if __name__ == "__main__":
    main()
