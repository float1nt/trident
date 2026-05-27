from __future__ import annotations

import argparse
import json
import logging
import signal
from time import perf_counter

from .config import TridentConfig, load_config
from .flow_loader import FlowLoader
from .output_streams import TridentOutputStreams
from .persistence.ch_flow_repository import ChFlowRepository
from .persistence.learner_repository import LearnerRepository
from .persistence.snapshot_repository import SnapshotRepository
from .redis_consumer import RedisStreamConsumer
from .runtime.assignment_writer import AssignmentWriter
from .runtime.monitoring import process_metrics
from .runtime.online_engine import FlowAssignment, OnlineEngine
from .runtime.snapshot_service import SnapshotService
from .window_buffer import BufferedFlow, FlowWindow, WindowBuffer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trident Redis to ClickHouse worker")
    parser.add_argument("--config", default="config/trident.yaml")
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")


class ShutdownFlag:
    def __init__(self) -> None:
        self.stop = False

    def install(self) -> None:
        def _handler(signum: int, _frame: object) -> None:
            self.stop = True
            logging.info(json.dumps({"event": "shutdown_requested", "signal": signum}, separators=(",", ":")))

        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)


def main() -> int:
    _configure_logging()
    args = parse_args()
    cfg = load_config(args.config)
    shutdown = ShutdownFlag()
    shutdown.install()

    consumer = RedisStreamConsumer(
        cfg.redis_url,
        stream=cfg.input_stream,
        group=cfg.consumer_group,
        consumer=cfg.consumer_name,
    )
    consumer.ensure_group()
    loader = FlowLoader(session_id=cfg.session_id, feature_profile=cfg.feature_profile)
    flow_repo = ChFlowRepository(cfg.clickhouse_dsn)
    learner_repo = LearnerRepository(cfg.postgres_dsn)
    snapshot_repo = SnapshotRepository(cfg.postgres_dsn)
    snapshot_service = SnapshotService(learner_repo, snapshot_repo)
    assignment_writer = AssignmentWriter(flow_repo)
    outputs = TridentOutputStreams(
        cfg.redis_url,
        assignment_stream=cfg.assignment_stream,
        alert_stream=cfg.alert_stream,
        metrics_stream=cfg.metrics_stream,
    )
    engine = OnlineEngine(
        session_id=cfg.session_id,
        cfg=cfg,
        learner_rows=learner_repo.list_learners(session_id=cfg.session_id),
    )
    buffer = WindowBuffer(cfg.window_size)

    pending = consumer.read_pending(count=cfg.read_count)
    if not pending:
        pending = consumer.autoclaim(min_idle_ms=cfg.pending_idle_ms, count=cfg.read_count)
    if pending:
        _process_messages(
            pending,
            cfg=cfg,
            loader=loader,
            flow_repo=flow_repo,
            assignment_writer=assignment_writer,
            snapshot_service=snapshot_service,
            outputs=outputs,
            engine=engine,
            consumer=consumer,
            buffer=None,
            force_window=True,
        )

    while not shutdown.stop:
        messages = consumer.read_new(count=cfg.read_count, block_ms=cfg.block_ms)
        if not messages:
            _log_batch(cfg.session_id, cfg.input_stream, read=0, written=0, acked=0, failed=0)
            if cfg.process_partial_window:
                window = buffer.flush()
                if window is not None:
                    _process_window(
                        window,
                        cfg=cfg,
                        flow_repo=flow_repo,
                        assignment_writer=assignment_writer,
                        snapshot_service=snapshot_service,
                        outputs=outputs,
                        engine=engine,
                        consumer=consumer,
                    )
            if args.once:
                return 0
            continue

        _process_messages(
            messages,
            cfg=cfg,
            loader=loader,
            flow_repo=flow_repo,
            assignment_writer=assignment_writer,
            snapshot_service=snapshot_service,
            outputs=outputs,
            engine=engine,
            consumer=consumer,
            buffer=buffer,
            force_window=False,
        )
        if args.once:
            if cfg.process_partial_window:
                window = buffer.flush()
                if window is not None:
                    _process_window(
                        window,
                        cfg=cfg,
                        flow_repo=flow_repo,
                        assignment_writer=assignment_writer,
                        snapshot_service=snapshot_service,
                        outputs=outputs,
                        engine=engine,
                        consumer=consumer,
                    )
            return 0
    return 0


def _process_messages(
    messages: list[object],
    *,
    cfg: TridentConfig,
    loader: FlowLoader,
    flow_repo: ChFlowRepository,
    assignment_writer: AssignmentWriter,
    snapshot_service: SnapshotService,
    outputs: TridentOutputStreams,
    engine: OnlineEngine,
    consumer: RedisStreamConsumer,
    buffer: WindowBuffer | None,
    force_window: bool,
) -> None:
    t_parse_start = perf_counter()
    good: list[BufferedFlow] = []
    bad_messages: list[object] = []
    for message in messages:
        try:
            record = loader.load(message)  # type: ignore[arg-type]
            good.append(BufferedFlow(message=message, record=record))  # type: ignore[arg-type]
        except Exception:
            bad_messages.append(message)
            logging.exception(
                json.dumps(
                    {
                        "event": "flow_parse_failed",
                        "stream": getattr(message, "stream", ""),
                        "message_id": getattr(message, "message_id", ""),
                    },
                    separators=(",", ":"),
                )
            )

    parse_seconds = perf_counter() - t_parse_start
    windows: list[FlowWindow]
    if force_window or buffer is None:
        windows = [FlowWindow(0, good)] if good else []
    else:
        windows = buffer.add_many(good)

    acked_bad = 0
    if bad_messages and getattr(cfg, "ack"):
        acked_bad = consumer.ack(bad_messages)  # type: ignore[arg-type]

    if not windows:
        _log_batch(
            cfg.session_id,
            cfg.input_stream,
            read=len(messages),
            written=0,
            assigned=0,
            acked=acked_bad,
            failed=len(bad_messages),
            window_index=None,
            metrics={"parse_seconds": parse_seconds, "buffered_count": buffer.buffered_count if buffer else 0},
        )
        return

    for index, window in enumerate(windows):
        _process_window(
            window,
            cfg=cfg,
            flow_repo=flow_repo,
            assignment_writer=assignment_writer,
            snapshot_service=snapshot_service,
            outputs=outputs,
            engine=engine,
            consumer=consumer,
            pre_acked=acked_bad if index == 0 else 0,
            parse_failures=len(bad_messages) if index == 0 else 0,
            extra_metrics={"parse_seconds": parse_seconds if index == 0 else 0.0},
        )


def _process_window(
    window: FlowWindow,
    *,
    cfg: TridentConfig,
    flow_repo: ChFlowRepository,
    assignment_writer: AssignmentWriter,
    snapshot_service: SnapshotService,
    outputs: TridentOutputStreams,
    engine: OnlineEngine,
    consumer: RedisStreamConsumer,
    pre_acked: int = 0,
    parse_failures: int = 0,
    extra_metrics: dict[str, object] | None = None,
) -> None:
    records = [item.record for item in window.items]
    messages = [item.message for item in window.items]
    written = 0
    assigned = 0
    acked = pre_acked
    t_window_start = perf_counter()
    timings: dict[str, float] = {}
    try:
        t_stage = perf_counter()
        written = flow_repo.insert_ingested(records)
        timings["ingest_write_seconds"] = perf_counter() - t_stage
        t_stage = perf_counter()
        result = engine.process_window(window)
        timings["engine_seconds"] = perf_counter() - t_stage
        snapshots_by_learner: dict[str, dict[str, object]] = {}
        t_stage = perf_counter()
        for request in result.snapshot_requests:
            learner = request["learner"]
            snapshot = snapshot_service.flush_snapshot(
                learner,  # type: ignore[arg-type]
                reason=str(request["reason"]),
                window_index=result.window_index,
            )
            learner_name = str(snapshot["learner_name"])
            snapshots_by_learner[learner_name] = snapshot
            engine.set_snapshot_ref(learner_name, str(snapshot["snapshot_id"]), int(snapshot["snapshot_version"]))
        timings["learner_snapshot_seconds"] = perf_counter() - t_stage

        assignments = _with_snapshot_refs(result.assignments, snapshots_by_learner)
        t_stage = perf_counter()
        assigned = assignment_writer.write(records, assignments, window_index=result.window_index)
        timings["assignment_write_seconds"] = perf_counter() - t_stage
        t_stage = perf_counter()
        outputs.publish_assignments(
            [
                {
                    "session_id": cfg.session_id,
                    "window_index": result.window_index,
                    "flow_uid": assignment.flow_uid,
                    "assigned_learner": assignment.assigned_learner,
                    "is_unknown": int(assignment.is_unknown),
                    "pred_loss": assignment.pred_loss,
                    "threshold": assignment.threshold,
                    "learner_snapshot_id": assignment.learner_snapshot_id,
                    "learner_snapshot_version": assignment.learner_snapshot_version,
                }
                for assignment in assignments
            ]
        )
        outputs.publish_alerts(result.alerts)
        timings["redis_output_seconds"] = perf_counter() - t_stage
        metrics = {
            "session_id": cfg.session_id,
            **result.metrics,
            **timings,
            **(extra_metrics or {}),
            "window_total_seconds": perf_counter() - t_window_start,
            "redis_xlen": _safe_metric(lambda: consumer.xlen()),
            "redis_pending": _safe_metric(lambda: consumer.pending_count()),
            "read_count": len(messages),
            "ingest_write_count": written,
            "assignment_write_count": assigned,
            "ack_enabled": int(cfg.ack),
        }
        if cfg.ack and messages:
            t_stage = perf_counter()
            acked += consumer.ack(messages)
            timings["ack_seconds"] = perf_counter() - t_stage
        metrics["ack_seconds"] = timings.get("ack_seconds", 0.0)
        metrics.update(process_metrics())
        outputs.publish_metrics(metrics)
    except Exception:
        logging.exception(
            json.dumps(
                {
                    "event": "window_processing_failed",
                    "session_id": cfg.session_id,
                    "window_index": window.window_index,
                    "read": len(messages),
                },
                separators=(",", ":"),
            )
        )
        _log_batch(
            cfg.session_id,
            cfg.input_stream,
            read=len(messages),
            written=written,
            assigned=assigned,
            acked=acked,
            failed=len(messages) + parse_failures,
            window_index=window.window_index,
            metrics={**timings, **(extra_metrics or {}), "window_total_seconds": perf_counter() - t_window_start},
        )
        return

    _log_batch(
        cfg.session_id,
        cfg.input_stream,
        read=len(messages),
        written=written,
        assigned=assigned,
        acked=acked,
        failed=parse_failures,
        window_index=window.window_index,
        metrics={
            **timings,
            **(extra_metrics or {}),
            "window_total_seconds": perf_counter() - t_window_start,
            "redis_xlen": _safe_metric(lambda: consumer.xlen()),
            "redis_pending": _safe_metric(lambda: consumer.pending_count()),
        },
    )


def _with_snapshot_refs(
    assignments: list[FlowAssignment],
    snapshots_by_learner: dict[str, dict[str, object]],
) -> list[FlowAssignment]:
    updated: list[FlowAssignment] = []
    for assignment in assignments:
        snapshot = snapshots_by_learner.get(assignment.assigned_learner)
        if snapshot is None:
            updated.append(assignment)
            continue
        updated.append(
            FlowAssignment(
                flow_uid=assignment.flow_uid,
                assigned_learner=assignment.assigned_learner,
                is_unknown=assignment.is_unknown,
                pred_loss=assignment.pred_loss,
                threshold=assignment.threshold,
                assignment_meta=assignment.assignment_meta,
                learner_snapshot_id=str(snapshot["snapshot_id"]),
                learner_snapshot_version=int(snapshot["snapshot_version"]),
            )
        )
    return updated


def _log_batch(
    session_id: str,
    stream: str,
    *,
    read: int,
    written: int,
    acked: int,
    failed: int,
    assigned: int = 0,
    window_index: int | None = None,
    metrics: dict[str, object] | None = None,
) -> None:
    logging.info(
        json.dumps(
            {
                "event": "trident_worker_batch",
                "session_id": session_id,
                "stream": stream,
                "window_index": window_index,
                "read": read,
                "written": written,
                "assigned": assigned,
                "acked": acked,
                "failed": failed,
                "metrics": metrics or {},
            },
            separators=(",", ":"),
        )
    )


def _safe_metric(call: object) -> int:
    try:
        return int(call())  # type: ignore[operator]
    except Exception:
        return -1


if __name__ == "__main__":
    raise SystemExit(main())
