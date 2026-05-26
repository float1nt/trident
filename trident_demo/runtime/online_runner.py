from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from trident_demo.benchmark.recorder import PerformanceRecorder
from trident_demo.lib.config_loader import build_logger, load_config
from trident_demo.pipeline.context import RunContext
from trident_demo.pipeline.runner import PipelineRunner

DEFAULT_ONLINE_CONFIG = "trident_demo/configs/online.yaml"


def _run_id_now(config_path: Path) -> str:
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in config_path.name)
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_online_{safe_name}"


def prepare_online_config(
    *,
    repo_root: Path,
    config_path: str,
    output_dir: Optional[str] = None,
    max_rows: int = 0,
    redis_url: Optional[str] = None,
    redis_stream: Optional[str] = None,
    window_size: int = 0,
) -> tuple[Dict[str, Any], str, Path]:
    cfg_path = Path(config_path)
    if not cfg_path.is_absolute():
        cfg_path = (repo_root / cfg_path).resolve()
    cfg = load_config(str(cfg_path))

    run_id = _run_id_now(cfg_path)
    cfg.setdefault("runtime", {})
    cfg["runtime"]["run_id"] = run_id
    cfg["runtime"]["performance_benchmark"] = True
    cfg["runtime"]["perf_mode"] = True
    cfg["runtime"]["debug_overlap_enabled"] = False
    cfg["runtime"]["aggregate_overlap_enabled"] = False
    cfg["runtime"]["missing_value_report_enabled"] = False
    if max_rows > 0:
        cfg["runtime"]["max_rows"] = int(max_rows)

    cfg.setdefault("input", {})
    cfg["input"]["source"] = "redis_stream"
    redis_cfg = cfg["input"].setdefault("redis", {})
    if redis_url:
        redis_cfg["url"] = str(redis_url)
    redis_cfg["data_structure"] = "stream"
    if redis_stream:
        redis_cfg["key"] = str(redis_stream)
        redis_cfg["stream"] = str(redis_stream)
    elif redis_cfg.get("stream") and not redis_cfg.get("key"):
        redis_cfg["key"] = redis_cfg["stream"]
    elif redis_cfg.get("key") and not redis_cfg.get("stream"):
        redis_cfg["stream"] = redis_cfg["key"]
    if max_rows > 0:
        redis_cfg["max_messages"] = int(max_rows)
    redis_cfg["apply_runtime_filters"] = False

    if window_size > 0:
        cfg.setdefault("stream", {})["window_size"] = int(window_size)

    cfg.setdefault("inject", {})["enabled"] = False
    cfg.setdefault("decision_tree", {})["enabled"] = False
    viz_cfg = cfg.setdefault("visualization", {})
    viz_cfg["enabled"] = False
    viz_cfg["dataset_topology_enabled"] = False
    viz_cfg["learner_topology_enabled"] = False
    viz_cfg["metric_audit_enabled"] = False
    viz_cfg["live_flush_enabled"] = True
    viz_cfg["live_flush_window_csv"] = True
    viz_cfg["live_flush_metric_audit"] = False

    base_output = Path(output_dir or cfg.get("paths", {}).get("output_dir", "trident_demo/outputs"))
    if not base_output.is_absolute():
        base_output = (repo_root / base_output).resolve()
    run_output_dir = (base_output / run_id).resolve()
    cfg.setdefault("paths", {})
    cfg["paths"]["output_dir"] = str(run_output_dir)
    cfg["paths"]["log_file"] = "run.log"
    return cfg, run_id, run_output_dir


def run_online(
    *,
    repo_root: Path,
    config_path: str = DEFAULT_ONLINE_CONFIG,
    max_rows: int = 0,
    output_dir: Optional[str] = None,
    redis_url: Optional[str] = None,
    redis_stream: Optional[str] = None,
    window_size: int = 0,
    skip_docker: bool = True,
) -> RunContext:
    cfg, run_id, run_output_dir = prepare_online_config(
        repo_root=repo_root,
        config_path=config_path,
        output_dir=output_dir,
        max_rows=max_rows,
        redis_url=redis_url,
        redis_stream=redis_stream,
        window_size=window_size,
    )
    logger = build_logger(output_dir=run_output_dir, log_file=cfg["paths"]["log_file"])
    logger.info("trident_demo online run_id=%s output=%s", run_id, run_output_dir)
    logger.info(
        "Online runtime: redis=%s stream=%s window_size=%s max_rows=%s",
        cfg.get("input", {}).get("redis", {}).get("url"),
        cfg.get("input", {}).get("redis", {}).get("key"),
        cfg.get("stream", {}).get("window_size"),
        cfg.get("runtime", {}).get("max_rows", 0),
    )

    ctx = RunContext(
        profile="benchmark",
        repo_root=repo_root,
        cfg=cfg,
        logger=logger,
        run_id=run_id,
        output_dir=run_output_dir,
        benchmark=True,
        perf_recorder=PerformanceRecorder(enabled=True),
    )
    PipelineRunner(ctx, skip_docker=skip_docker, no_inject=True).run()
    return ctx
