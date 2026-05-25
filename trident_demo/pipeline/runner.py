from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from trident_demo.benchmark.recorder import PerformanceRecorder
from trident_demo.lib.config_loader import build_logger, load_config
from trident_demo.orchestration.postrun import postrun_stage
from trident_demo.orchestration.preflight import preflight_stage
from trident_demo.orchestration.redis_inject import inject_csv_to_redis
from trident_demo.orchestration.viz_data_prep import run_viz_demo_data_prep
from trident_demo.pipeline.context import RunContext
from trident_demo.pipeline.stages.run_experiment import run_experiment_stage

PROFILE_DEFAULT_CONFIG = {
    "batch": "trident_demo/configs/batch.yaml",
    "replay": "trident_demo/configs/replay.yaml",
    "benchmark": "trident_demo/configs/benchmark.yaml",
    "viz-demo": "trident_demo/configs/viz_demo.yaml",
}


def build_run_id(config_path: str, profile: str, benchmark: bool) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    config_name = Path(config_path).name
    safe_config_name = re.sub(r"[^A-Za-z0-9._-]", "_", config_name)
    prefix = "benchmark" if benchmark or profile == "benchmark" else profile
    return f"{timestamp}_{prefix}_{safe_config_name}"


def prepare_config(
    *,
    repo_root: Path,
    config_path: str,
    profile: str,
    max_rows: int,
    benchmark: bool,
    output_dir: Optional[str],
) -> tuple[Dict[str, Any], str, Path]:
    cfg_path = (repo_root / config_path).resolve()
    cfg = load_config(str(cfg_path))
    cfg.setdefault("runtime", {})
    if benchmark or profile == "benchmark":
        cfg["runtime"]["performance_benchmark"] = True
    if max_rows > 0:
        cfg["runtime"]["max_rows"] = int(max_rows)
        input_cfg = cfg.get("input", {}) if isinstance(cfg.get("input"), dict) else {}
        source = str(input_cfg.get("source", input_cfg.get("type", "csv"))).strip().lower()
        if source in {"redis", "redis_list", "redis_stream"}:
            redis_cfg = input_cfg.setdefault("redis", {})
            if isinstance(redis_cfg, dict):
                redis_cfg["max_messages"] = int(max_rows)
        stream_cfg = cfg.setdefault("stream", {})
        init_benign = int(stream_cfg.get("init_benign_count", 0) or 0)
        if init_benign >= int(max_rows):
            stream_cfg["init_benign_count"] = max(1000, int(max_rows) // 4)
            stream_cfg["init_ratio"] = min(float(stream_cfg.get("init_ratio", 0.01)), 0.25)

    run_id = build_run_id(str(cfg_path), profile, benchmark or profile == "benchmark")
    cfg["runtime"]["run_id"] = run_id

    base_output = Path(output_dir or cfg.get("paths", {}).get("output_dir", "trident_demo/outputs"))
    if not base_output.is_absolute():
        base_output = (repo_root / base_output).resolve()
    run_output_dir = (base_output / run_id).resolve()
    cfg.setdefault("paths", {})
    cfg["paths"]["output_dir"] = str(run_output_dir)
    cfg["paths"]["log_file"] = "run.log"
    return cfg, run_id, run_output_dir


class PipelineRunner:
    def __init__(
        self,
        ctx: RunContext,
        *,
        skip_docker: bool = False,
        no_inject: bool = False,
    ) -> None:
        self.ctx = ctx
        self.skip_docker = skip_docker
        self.no_inject = no_inject

    def run(self) -> None:
        profile = self.ctx.profile
        rec = self.ctx.perf_recorder
        if rec and rec.enabled:
            rec.start_wall()
            rec.start("pipeline_total")
        try:
            if profile == "viz-demo":
                if rec and rec.enabled:
                    rec.start("pipeline_data_prep")
                run_viz_demo_data_prep(self.ctx.repo_root, self.ctx.logger)
                if rec and rec.enabled:
                    rec.stop("pipeline_data_prep")

            if profile in {"replay", "benchmark"}:
                if rec and rec.enabled:
                    rec.start("pipeline_preflight")
                preflight_stage(self.ctx, skip_docker=self.skip_docker)
                if rec and rec.enabled:
                    rec.stop("pipeline_preflight")
                inject_cfg = self.ctx.cfg.get("inject", {})
                inject_enabled = bool(inject_cfg.get("enabled", True))
                if not self.no_inject and inject_enabled:
                    redis_cfg = self.ctx.cfg.get("input", {}).get("redis", {})
                    if rec and rec.enabled:
                        rec.start("pipeline_redis_inject")
                    self.ctx.inject_summary = inject_csv_to_redis(
                        repo_root=self.ctx.repo_root,
                        csv=str(inject_cfg.get("csv", "data/aligned_2017_2019_2026_sampled_x5_yeartagged_for_main.csv")),
                        max_rows=int(
                            inject_cfg.get("max_rows")
                            or self.ctx.cfg.get("runtime", {}).get("max_rows")
                            or 10000
                        ),
                        url=str(redis_cfg.get("url", "redis://127.0.0.1:6379/0")),
                        stream=str(redis_cfg.get("key", "suricata:cic_flow")),
                        clear_stream=bool(inject_cfg.get("clear_stream", True)),
                        logger=self.ctx.logger,
                    )
                    if rec and rec.enabled:
                        rec.stop("pipeline_redis_inject")
                        rec.set_counter(
                            "redis_injected_rows",
                            float(self.ctx.inject_summary.get("injected_rows", 0)),
                        )
                        inject_seconds = float(self.ctx.inject_summary.get("inject_seconds", 0.0) or 0.0)
                        if inject_seconds > 0:
                            rec.add("redis_inject_inner", inject_seconds)
                else:
                    self.ctx.logger.info(
                        "Pipeline: skip CSV→Redis inject (no_inject=%s inject.enabled=%s)",
                        self.no_inject,
                        inject_enabled,
                    )

            self.ctx.logger.info("Pipeline: running Trident experiment (profile=%s)", profile)
            if rec and rec.enabled:
                rec.start("pipeline_experiment")
            run_experiment_stage(self.ctx)
            if rec and rec.enabled:
                rec.stop("pipeline_experiment")

            if rec and rec.enabled:
                rec.start("pipeline_postrun")
            postrun_stage(self.ctx)
            if rec and rec.enabled:
                rec.stop("pipeline_postrun")
        finally:
            if rec and rec.enabled:
                rec.stop("pipeline_total")
                self._write_benchmark_report()

    def _write_benchmark_report(self) -> None:
        rec = self.ctx.perf_recorder
        if not rec or not rec.enabled:
            return
        inputs = self.ctx.extras.get("benchmark_report_inputs")
        if not inputs:
            self.ctx.logger.warning("Benchmark recorder enabled, but experiment did not provide report inputs.")
            rec.finish_wall()
            return
        rec.finish_wall()
        benchmark_report = rec.build_report(**inputs)
        benchmark_paths = rec.write(self.ctx.output_dir, benchmark_report)
        self.ctx.logger.info(
            "Done. TRIDENT_PERFORMANCE_BENCHMARK_JSON=%s",
            benchmark_paths["json"],
        )
        self.ctx.logger.info(
            "Done. TRIDENT_PERFORMANCE_BENCHMARK_MD=%s",
            benchmark_paths["markdown"],
        )
        print(f"Benchmark: {benchmark_paths['json']}")
        infer_fps = benchmark_report.get("throughput_flows_per_second", {}).get(
            "flows_per_second_inference"
        )
        if infer_fps is not None:
            self.ctx.logger.info(
                "Benchmark inference throughput: %.2f flows/s (%d stream flows / %.4fs detect)",
                float(infer_fps),
                int(inputs.get("stream_flow_count", 0)),
                float((inputs.get("perf_stats") or {}).get("detect_seconds_total", 0.0)),
            )


def run_pipeline(
    *,
    repo_root: Path,
    profile: str,
    config_path: Optional[str] = None,
    max_rows: int = 0,
    benchmark: bool = False,
    output_dir: Optional[str] = None,
    skip_docker: bool = False,
    no_inject: bool = False,
) -> RunContext:
    config_path = config_path or PROFILE_DEFAULT_CONFIG[profile]
    cfg, run_id, run_output_dir = prepare_config(
        repo_root=repo_root,
        config_path=config_path,
        profile=profile,
        max_rows=max_rows,
        benchmark=benchmark,
        output_dir=output_dir,
    )
    logger = build_logger(output_dir=run_output_dir, log_file=cfg["paths"]["log_file"])
    logger.info("trident_demo profile=%s run_id=%s output=%s", profile, run_id, run_output_dir)
    perf_enabled = bool(cfg.get("runtime", {}).get("performance_benchmark", False))
    perf_recorder = PerformanceRecorder(enabled=perf_enabled) if perf_enabled else None

    ctx = RunContext(
        profile=profile,
        repo_root=repo_root,
        cfg=cfg,
        logger=logger,
        run_id=run_id,
        output_dir=run_output_dir,
        benchmark=benchmark or profile == "benchmark",
        perf_recorder=perf_recorder,
    )
    PipelineRunner(ctx, skip_docker=skip_docker, no_inject=no_inject).run()
    return ctx
