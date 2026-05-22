#!/usr/bin/env python3
"""Export dataset_network_topology.json for an existing run (uses run config_snapshot)."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trident_stream.dataset_topology import save_dataset_network_topology
from trident_stream.experiment import TridentStreamingExperiment


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Path to outputs/runs/<run_id>")
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    cfg_path = run_dir / "config_snapshot.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(cfg_path)

    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    logger = logging.getLogger("export_topology")
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    exp = TridentStreamingExperiment(cfg, logger)
    data, _, _ = exp._load_dataset()
    out = run_dir / "dataset_network_topology.json"
    save_dataset_network_topology(data, out)
    print(f"Wrote {out} ({len(data):,} flows)")


if __name__ == "__main__":
    main()
