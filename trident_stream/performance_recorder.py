"""Wall-clock stage recorder for Trident performance benchmarks."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Optional

from trident_stream.resource_monitor import ResourceTracker


@dataclass
class PerformanceRecorder:
    enabled: bool = True
    _starts: Dict[str, float] = field(default_factory=dict)
    seconds: Dict[str, float] = field(default_factory=dict)
    _wall_start: Optional[float] = None
    counters: Dict[str, float] = field(default_factory=dict)
    resources: ResourceTracker = field(default_factory=ResourceTracker)

    def configure_device(self, device: str) -> None:
        if not self.enabled:
            return
        self.resources.configure_device(device)

    def start_wall(self) -> None:
        if not self.enabled:
            return
        self._wall_start = perf_counter()
        self.resources.start_run()

    def finish_wall(self) -> None:
        if not self.enabled or self._wall_start is None:
            return
        self.seconds["wall_clock_total"] = perf_counter() - self._wall_start
        self.resources.finish_run()

    def start(self, key: str) -> None:
        if not self.enabled:
            return
        self._starts[key] = perf_counter()
        self.resources.mark_stage_start(key)

    def stop(self, key: str) -> float:
        if not self.enabled:
            return 0.0
        start = self._starts.pop(key, None)
        if start is None:
            return 0.0
        elapsed = perf_counter() - start
        self.seconds[key] = self.seconds.get(key, 0.0) + elapsed
        self.resources.mark_stage_end(key)
        return elapsed

    def add(self, key: str, elapsed: float) -> None:
        if not self.enabled:
            return
        self.seconds[key] = self.seconds.get(key, 0.0) + float(elapsed)

    def set_counter(self, key: str, value: float) -> None:
        if not self.enabled:
            return
        self.counters[key] = float(value)

    def build_report(
        self,
        *,
        run_id: str,
        flow_count: int,
        stream_flow_count: int,
        perf_stats: Optional[Dict[str, Any]] = None,
        qualification_stats: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        stages = dict(self.seconds)
        if perf_stats:
            stages.setdefault(
                "stream_inference",
                float(perf_stats.get("detect_seconds_total", 0.0)),
            )
            stages.setdefault(
                "stream_cluster",
                float(perf_stats.get("cluster_seconds_total", 0.0)),
            )
            stages.setdefault(
                "stream_create_learner",
                float(perf_stats.get("create_learner_seconds_total", 0.0)),
            )
            stages.setdefault(
                "stream_retrain",
                float(perf_stats.get("retrain_seconds_total", 0.0)),
            )
            stages.setdefault(
                "init_create_learner",
                float(perf_stats.get("init_create_learner_seconds_total", 0.0)),
            )
            stages.setdefault(
                "stream_window_total",
                float(perf_stats.get("window_total_seconds_total", 0.0)),
            )

        infer_s = float(stages.get("stream_inference", 0.0))
        qual_total = float(stages.get("qualification_total", 0.0))
        wall = float(stages.get("wall_clock_total", 0.0))
        qual_flows = int(
            (qualification_stats or {}).get("audited_flow_count", 0)
            or self.counters.get("qualification_flow_count", 0)
        )

        throughput: Dict[str, Optional[float]] = {
            "flows_per_second_inference": (
                float(stream_flow_count) / infer_s if infer_s > 0 else None
            ),
            "flows_per_second_end_to_end": (
                float(flow_count) / wall if wall > 0 else None
            ),
            "flows_per_second_qualification": (
                float(qual_flows) / qual_total if qual_total > 0 and qual_flows > 0 else None
            ),
        }

        pipeline_core = (
            float(stages.get("io_load_total", 0.0))
            + float(stages.get("init_learners", 0.0))
            + infer_s
            + float(stages.get("stream_cluster", 0.0))
            + float(stages.get("stream_create_learner", 0.0))
            + float(stages.get("stream_retrain", 0.0))
            + qual_total
        )
        throughput["flows_per_second_pipeline_core"] = (
            float(flow_count) / pipeline_core if pipeline_core > 0 else None
        )

        wall = float(stages.get("wall_clock_total", 0.0))
        resource_usage = self.resources.build_summary(wall)

        return {
            "version": 1,
            "run_id": run_id,
            "flow_count": int(flow_count),
            "stream_flow_count": int(stream_flow_count),
            "stages_seconds": stages,
            "throughput_flows_per_second": throughput,
            "resource_usage": resource_usage,
            "qualification_detail": qualification_stats or {},
            "stream_perf_stats": perf_stats or {},
            "counters": dict(self.counters),
        }

    def write(self, output_dir: Path, report: Dict[str, Any]) -> Dict[str, Path]:
        output_dir = output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "trident_performance_benchmark.json"
        md_path = output_dir / "trident_performance_benchmark.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        md_path.write_text(_format_markdown(report), encoding="utf-8")
        return {"json": json_path, "markdown": md_path}


def _format_markdown(report: Dict[str, Any]) -> str:
    stages: Dict[str, float] = report.get("stages_seconds", {})
    tp: Dict[str, Any] = report.get("throughput_flows_per_second", {})
    qual: Dict[str, Any] = report.get("qualification_detail", {})

    lines = [
        "# Trident Performance Benchmark",
        "",
        f"- run_id: `{report.get('run_id', '')}`",
        f"- flow_count: {report.get('flow_count', 0)}",
        f"- stream_flow_count: {report.get('stream_flow_count', 0)}",
        "",
        "## Stage timings (seconds)",
        "",
        "| Stage | Seconds |",
        "|---|---:|",
    ]
    for key in sorted(stages.keys()):
        lines.append(f"| `{key}` | {float(stages[key]):.6f} |")

    lines.extend(["", "## Throughput (flows / second)", ""])
    for key, value in tp.items():
        if value is None:
            lines.append(f"- **{key}**: n/a")
        else:
            lines.append(f"- **{key}**: {float(value):,.2f}")

    if qual:
        lines.extend(["", "## Qualification breakdown", ""])
        for key, value in qual.items():
            lines.append(f"- {key}: {value}")

    stream = report.get("stream_perf_stats") or {}
    if stream:
        lines.extend(["", "## Stream counters", ""])
        for key in (
            "windows_count",
            "new_learner_count",
            "incremental_update_count",
            "avg_detect_seconds_per_window",
        ):
            if key in stream:
                lines.append(f"- {key}: {stream[key]}")

    resources: Dict[str, Any] = report.get("resource_usage") or {}
    if resources:
        lines.extend(["", "## Resource usage", ""])
        for key in (
            "compute_device",
            "gpu_device_name",
            "cpu_logical_count",
            "process_cpu_seconds_total",
            "cpu_utilization_vs_cores_avg",
            "process_cpu_percent_one_core_avg",
            "process_cpu_percent_one_core_max",
            "process_rss_peak_mb",
            "gpu_peak_allocated_mb",
            "gpu_peak_reserved_mb",
            "gpu_utilization_percent_avg",
            "gpu_utilization_percent_max",
            "gpu_memory_used_mb_max",
        ):
            if key in resources and resources[key] is not None:
                lines.append(f"- {key}: {resources[key]}")

        stage_cpu = resources.get("stage_process_cpu_seconds") or {}
        if stage_cpu:
            lines.extend(["", "### CPU time by stage (seconds)", "", "| Stage | CPU seconds |", "|---|---:|"])
            for key, value in stage_cpu.items():
                lines.append(f"| `{key}` | {float(value):.6f} |")

        stage_gpu = resources.get("stage_gpu_peak_allocated_mb") or {}
        if stage_gpu:
            lines.extend(
                ["", "### GPU peak allocated by stage (MB)", "", "| Stage | Peak MB |", "|---|---:|"]
            )
            for key, value in stage_gpu.items():
                lines.append(f"| `{key}` | {float(value):.3f} |")

    return "\n".join(lines) + "\n"
