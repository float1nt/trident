from __future__ import annotations

import os
import resource
from typing import Any


def process_metrics() -> dict[str, Any]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    metrics: dict[str, Any] = {
        "process_user_cpu_seconds": float(usage.ru_utime),
        "process_system_cpu_seconds": float(usage.ru_stime),
        "process_max_rss_kb": int(usage.ru_maxrss),
    }
    try:
        load1, load5, load15 = os.getloadavg()
        metrics.update({"loadavg_1m": load1, "loadavg_5m": load5, "loadavg_15m": load15})
    except OSError:
        pass
    return metrics
