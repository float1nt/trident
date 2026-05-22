#!/usr/bin/env python3
"""Deprecated: moved to learner_qualification/export_dataset_network_topology.py"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

_TARGET = Path(__file__).resolve().parents[1] / "learner_qualification" / "export_dataset_network_topology.py"

if __name__ == "__main__":
    print(
        "Note: moved to learner_qualification/export_dataset_network_topology.py",
        file=sys.stderr,
    )
    runpy.run_path(str(_TARGET), run_name="__main__")
