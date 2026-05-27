from __future__ import annotations

import argparse
from typing import Any

from fastapi import FastAPI, Query

from .config import TridentConfig, load_config
from .persistence.ch_flow_repository import ChFlowRepository
from .persistence.learner_repository import LearnerRepository
from .redis_consumer import RedisStreamConsumer


def create_app(config_path: str | None = None) -> FastAPI:
    cfg = load_config(config_path)
    app = FastAPI(title="Trident Service API")
    app.state.cfg = cfg

    @app.get("/api/v1/health")
    def health() -> dict[str, Any]:
        return _ok(
            {
                "session_id": cfg.session_id,
                "redis": _probe(lambda: _redis(cfg).ping()),
                "clickhouse": _probe(lambda: ChFlowRepository(cfg.clickhouse_dsn).ping()),
                "postgres": _probe(lambda: LearnerRepository(cfg.postgres_dsn).ping()),
            }
        )

    @app.get("/api/v1/runtime/summary")
    def runtime_summary() -> dict[str, Any]:
        redis_state = _redis(cfg)
        flow_repo = ChFlowRepository(cfg.clickhouse_dsn)
        return _ok(
            {
                "session_id": cfg.session_id,
                "redis_xlen": _safe_int(lambda: redis_state.xlen()),
                "redis_pending": _safe_int(lambda: redis_state.pending_count()),
                "consumed_flow_count": _safe_int(lambda: flow_repo.count_flows(session_id=cfg.session_id)),
                "current_window_index": _safe_int(lambda: flow_repo.max_window_index(session_id=cfg.session_id)),
            }
        )

    @app.get("/api/v1/flows")
    def list_flows(
        session_id: str | None = None,
        window_index: int | None = None,
        learner_name: str | None = None,
        is_unknown: bool | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        rows = ChFlowRepository(cfg.clickhouse_dsn).list_flows(
            session_id=session_id or cfg.session_id,
            window_index=window_index,
            learner_name=learner_name,
            is_unknown=is_unknown,
            time_from=time_from,
            time_to=time_to,
            limit=limit,
            cursor=cursor,
        )
        return _ok({"items": rows, "next_cursor": rows[-1]["flow_uid"] if rows else None})

    @app.get("/api/v1/learners")
    def list_learners(session_id: str | None = None) -> dict[str, Any]:
        return _ok({"items": LearnerRepository(cfg.postgres_dsn).list_learners(session_id=session_id or cfg.session_id)})

    @app.get("/api/v1/learners/{learner_name}")
    def get_learner(learner_name: str, session_id: str | None = None) -> dict[str, Any]:
        learner = LearnerRepository(cfg.postgres_dsn).get_learner(
            session_id=session_id or cfg.session_id,
            learner_name=learner_name,
        )
        return _ok(learner or {})

    @app.get("/api/v1/learners/{learner_name}/flows")
    def learner_flows(
        learner_name: str,
        session_id: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        rows = ChFlowRepository(cfg.clickhouse_dsn).list_flows(
            session_id=session_id or cfg.session_id,
            learner_name=learner_name,
            limit=limit,
            cursor=cursor,
        )
        return _ok({"items": rows, "next_cursor": rows[-1]["flow_uid"] if rows else None})

    return app


def _redis(cfg: TridentConfig) -> RedisStreamConsumer:
    return RedisStreamConsumer(
        cfg.redis_url,
        stream=cfg.input_stream,
        group=cfg.consumer_group,
        consumer=cfg.consumer_name,
    )


def _ok(data: Any) -> dict[str, Any]:
    return {"code": 0, "message": "ok", "data": data}


def _probe(call: Any) -> dict[str, Any]:
    try:
        call()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _safe_int(call: Any) -> int:
    try:
        return int(call())
    except Exception:
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trident read-only API")
    parser.add_argument("--config", default="config/trident.yaml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    return parser.parse_args()


def main() -> int:
    import uvicorn

    args = parse_args()
    uvicorn.run(create_app(args.config), host=args.host, port=args.port)
    return 0


app = create_app(None)


if __name__ == "__main__":
    raise SystemExit(main())
