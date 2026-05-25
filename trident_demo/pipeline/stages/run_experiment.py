from __future__ import annotations

from trident_demo.pipeline.context import RunContext
from trident_demo.pipeline.experiment import TridentStreamingExperiment


def run_experiment_stage(ctx: RunContext) -> None:
    experiment = TridentStreamingExperiment(
        cfg=ctx.cfg,
        logger=ctx.logger,
        perf_recorder=ctx.perf_recorder,
    )
    experiment.run()
    if experiment.benchmark_report_inputs:
        ctx.extras["benchmark_report_inputs"] = experiment.benchmark_report_inputs
