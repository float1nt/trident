from __future__ import annotations

import json

from trident_demo.pipeline.context import RunContext


def postrun_stage(ctx: RunContext) -> None:
    run_dir = ctx.output_dir
    ctx.logger.info("PostRun: output directory %s", run_dir)

    benchmark_path = run_dir / "trident_performance_benchmark.json"
    if benchmark_path.exists():
        ctx.logger.info("--- trident_performance_benchmark.json ---")
        payload = json.loads(benchmark_path.read_text(encoding="utf-8"))
        ctx.logger.info("%s", json.dumps(payload, ensure_ascii=False, indent=2))

    if ctx.inject_summary:
        ctx.logger.info("Inject summary: %s", json.dumps(ctx.inject_summary, ensure_ascii=False))

    print(f"\nRun output: {run_dir}")
    if benchmark_path.exists():
        print(f"Benchmark: {benchmark_path}")
    print("Visualize: cd visualize && npm run dev")
    print(f"  Run ID: {ctx.run_id}")
