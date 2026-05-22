#!/usr/bin/env python3
"""Rebuild visualization artifacts for an existing run directory."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trident_stream.experiment import TridentStreamingExperiment
from trident_stream.visualization_artifacts import export_visualization_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Path to outputs/runs/<run_id>")
    parser.add_argument(
        "--metric-audit-min-samples",
        type=int,
        default=None,
        help="Override visualization.metric_audit_min_samples from the run config.",
    )
    parser.add_argument(
        "--metric-audit-max-learners",
        type=int,
        default=None,
        help="Override visualization.metric_audit_max_learners from the run config.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    cfg_path = run_dir / "config_snapshot.yaml"
    assignment_path = run_dir / "sample_learner_assignments.csv"
    label_distribution_path = run_dir / "learner_label_distribution.csv"
    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)
    if not assignment_path.exists():
        raise FileNotFoundError(assignment_path)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("export_visualization_artifacts")
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    data, _, _ = TridentStreamingExperiment(cfg, logger)._load_dataset()
    assignments = pd.read_csv(assignment_path)
    label_distribution = (
        pd.read_csv(label_distribution_path)
        if label_distribution_path.exists()
        else pd.DataFrame()
    )
    viz_cfg = cfg.get("visualization", {})
    written = export_visualization_artifacts(
        data=data,
        assignments=assignments,
        label_distribution=label_distribution,
        output_dir=run_dir,
        export_dataset_topology=True,
        metric_audit_min_samples=(
            int(args.metric_audit_min_samples)
            if args.metric_audit_min_samples is not None
            else int(viz_cfg.get("metric_audit_min_samples", 50))
        ),
        metric_audit_max_learners=(
            int(args.metric_audit_max_learners)
            if args.metric_audit_max_learners is not None
            else int(viz_cfg.get("metric_audit_max_learners", 60))
        ),
    )
    for name, path in written.items():
        print(f"Wrote {name}: {path}")


if __name__ == "__main__":
    main()
