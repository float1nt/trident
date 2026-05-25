from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass
class RunContext:
    profile: str
    repo_root: Path
    cfg: Dict[str, Any]
    logger: Any
    run_id: str
    output_dir: Path
    benchmark: bool = False
    inject_summary: Optional[Dict[str, Any]] = None
    perf_recorder: Optional[Any] = None
    extras: Dict[str, Any] = field(default_factory=dict)
