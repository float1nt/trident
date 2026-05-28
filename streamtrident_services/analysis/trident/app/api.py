from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import os
from typing import Any
from pathlib import Path

from fastapi import FastAPI, Query

from .api_routes.auth import register_auth_routes
from .api_schema import (
    ApiResponse,
    DashboardTopologyData,
    FlowListData,
    LearnerTopologyData,
)
from .collection_settings import (
    CollectionSettings,
    PROTOCOL_OPTIONS,
    apply_suricata_config,
)
from .config import TridentConfig, load_config
from .logging_utils import configure_logging, emit_event


def create_app(config_path: str | None = None) -> FastAPI:
    cfg = load_config(config_path)
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        emit_event(
            "api_started",
            session_id=cfg.session_id,
            redis_url=cfg.redis_url,
            input_stream=cfg.input_stream,
            consumer_mode=cfg.consumer_mode,
            clickhouse_dsn=cfg.clickhouse_dsn,
            postgres_dsn=cfg.postgres_dsn,
        )
        yield
        emit_event("api_stopped", session_id=cfg.session_id)

    app = FastAPI(title="Trident Service API", lifespan=lifespan)
    app.state.cfg = cfg
    register_auth_routes(app, _auth_manager())

    @app.get("/collection/settings", response_model=ApiResponse)
    def get_collection_settings() -> dict[str, Any]:
        settings = _collection_settings_repo(cfg).get_settings(session_id=cfg.session_id)
        return _ok(settings.model_dump())

    @app.put("/collection/settings", response_model=ApiResponse)
    def put_collection_settings(payload: CollectionSettings) -> dict[str, Any]:
        settings = _collection_settings_repo(cfg).save_settings(
            session_id=cfg.session_id,
            settings=payload,
        )
        apply_result = apply_suricata_config(settings)
        if not apply_result.get("applied"):
            emit_event("collection_settings_apply_failed", apply_result=apply_result)
            from fastapi import HTTPException

            raise HTTPException(status_code=502, detail=apply_result)
        return _ok(settings.model_dump())

    @app.get("/collection/protocols", response_model=ApiResponse)
    def collection_protocols() -> dict[str, Any]:
        return _ok(PROTOCOL_OPTIONS)

    @app.post("/collection/settings/apply", response_model=ApiResponse)
    def apply_collection_settings() -> dict[str, Any]:
        settings = _collection_settings_repo(cfg).get_settings(session_id=cfg.session_id)
        apply_result = apply_suricata_config(settings)
        if not apply_result.get("applied"):
            emit_event("collection_settings_apply_failed", apply_result=apply_result)
            from fastapi import HTTPException

            raise HTTPException(status_code=502, detail=apply_result)
        return _ok(apply_result)

    @app.get("/api/v1/health", response_model=ApiResponse)
    def health() -> dict[str, Any]:
        return _ok(
            {
                "session_id": cfg.session_id,
                "redis": _probe(lambda: _redis(cfg).ping()),
                "clickhouse": _probe(lambda: _flow_repo(cfg).ping()),
                "postgres": _probe(lambda: _learner_repo(cfg).ping()),
            }
        )

    @app.get("/api/v1/runtime/summary", response_model=ApiResponse)
    def runtime_summary() -> dict[str, Any]:
        redis_state = _redis(cfg)
        flow_repo = _flow_repo(cfg)
        return _ok(
            {
                "session_id": cfg.session_id,
                "redis_xlen": _safe_int(lambda: redis_state.xlen()),
                "redis_pending": _safe_int(lambda: redis_state.pending_count()),
                "consumed_flow_count": _safe_int(lambda: flow_repo.count_flows(session_id=cfg.session_id)),
                "current_window_index": _safe_int(lambda: flow_repo.max_window_index(session_id=cfg.session_id)),
            }
        )

    @app.get("/overview/metrics", response_model=ApiResponse)
    def overview_metrics(
        timeRange: str = "24h",
    ) -> dict[str, Any]:
        return _ok(_pages(cfg).overview_metrics(time_range=timeRange))

    @app.get("/overview/distributions", response_model=ApiResponse)
    def overview_distributions(
        timeRange: str = "24h",
    ) -> dict[str, Any]:
        return _ok(_pages(cfg).overview_distributions(time_range=timeRange))

    @app.get("/overview/traffic-trend", response_model=ApiResponse)
    def overview_traffic_trend(
        timeRange: str = "24h",
    ) -> dict[str, Any]:
        return _ok(_pages(cfg).overview_traffic_trend(time_range=timeRange))

    @app.get("/overview/network-topology", response_model=ApiResponse)
    def overview_network_topology(
        timeRange: str = "24h",
        top_n: int = Query(50, ge=1, le=500),
    ) -> dict[str, Any]:
        time_from = _time_range_start(timeRange)
        data = _pages(cfg).dashboard_topology(
            top_n=top_n,
            time_from=time_from,
        )
        return _ok(DashboardTopologyData.model_validate(data).model_dump())

    @app.get("/risks", response_model=ApiResponse)
    def risks(
        limit: int = Query(10, ge=1, le=1000),
        offset: int = Query(0, ge=0),
        name: str | None = None,
        subjectIp: str | None = None,
    ) -> dict[str, Any]:
        return _ok(_pages(cfg).risk_list(limit=limit, offset=offset, name=name, subject_ip=subjectIp))

    @app.get("/risk/events/topology", response_model=ApiResponse)
    def risk_events_topology(
        name: str | None = None,
        triggerStart: str | None = None,
        triggerEnd: str | None = None,
        top_n: int = Query(50, ge=1, le=500),
        limit: int = Query(6, ge=1, le=50),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        data = _pages(cfg).risk_events_topology(
            name=name,
            trigger_start=triggerStart,
            trigger_end=triggerEnd,
            top_n=top_n,
            limit=limit,
            offset=offset,
        )
        return _ok(LearnerTopologyData.model_validate(data).model_dump())

    @app.get("/risks/{risk_id}/network-topology", response_model=ApiResponse)
    def risk_network_topology(
        risk_id: int,
        top_n: int = Query(50, ge=1, le=500),
    ) -> dict[str, Any]:
        data = _pages(cfg).risk_network_topology(risk_id=risk_id, top_n=top_n)
        return _ok(DashboardTopologyData.model_validate(data).model_dump())

    @app.get("/risks/{risk_id}/ips", response_model=ApiResponse)
    def risk_ips(risk_id: int) -> dict[str, Any]:
        return _ok(_pages(cfg).risk_ips(risk_id=risk_id))

    @app.get("/risks/{risk_id}/traffic-logs", response_model=ApiResponse)
    def risk_traffic_logs(
        risk_id: int,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        return _ok(_pages(cfg).risk_traffic_logs(risk_id=risk_id, limit=limit, offset=offset))

    @app.get("/risks/{risk_id}/protocol-distribution", response_model=ApiResponse)
    def risk_protocol_distribution(risk_id: int) -> dict[str, Any]:
        return _ok(_pages(cfg).risk_protocol_distribution(risk_id=risk_id))

    @app.get("/risks/{risk_id}", response_model=ApiResponse)
    def risk_by_id(risk_id: int) -> dict[str, Any]:
        return _ok(_pages(cfg).risk_by_id(risk_id=risk_id))

    @app.get("/risk/ips/{ip}/summary", response_model=ApiResponse)
    def risk_ip_summary(ip: str) -> dict[str, Any]:
        return _ok(_pages(cfg).ip_summary(ip=ip))

    @app.get("/risk/ips/{ip}/events/topology", response_model=ApiResponse)
    def risk_ip_events_topology(
        ip: str,
        top_n: int = Query(50, ge=1, le=500),
        limit: int = Query(6, ge=1, le=50),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        data = _pages(cfg).ip_events_topology(
            ip=ip,
            top_n=top_n,
            limit=limit,
            offset=offset,
        )
        return _ok(LearnerTopologyData.model_validate(data).model_dump())

    @app.get("/risk/ips/{ip}/events", response_model=ApiResponse)
    def risk_ip_events(ip: str) -> dict[str, Any]:
        return _ok(_pages(cfg).ip_events(ip=ip))

    @app.get("/risk/ips/{ip}/traffic-logs", response_model=ApiResponse)
    def risk_ip_traffic_logs(
        ip: str,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> dict[str, Any]:
        return _ok(_pages(cfg).ip_traffic_logs(ip=ip, limit=limit, offset=offset))

    @app.get("/api/v1/flows", response_model=ApiResponse)
    def list_flows(
        session_id: str | None = None,
        window_index: int | None = None,
        learner_name: str | None = None,
        is_unknown: bool | None = None,
        time_from: str | None = None,
        time_to: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int | None = Query(None, ge=0),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        result = _flow_repo(cfg).list_flows(
            session_id=session_id or cfg.session_id,
            window_index=window_index,
            learner_name=learner_name,
            is_unknown=is_unknown,
            time_from=time_from,
            time_to=time_to,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
        return _ok(FlowListData.model_validate(result).model_dump())

    @app.get("/api/v1/learners", response_model=ApiResponse)
    def list_learners(session_id: str | None = None) -> dict[str, Any]:
        return _ok({"items": _learner_repo(cfg).list_learners(session_id=session_id or cfg.session_id)})

    @app.get("/api/v1/learners/{learner_name}", response_model=ApiResponse)
    def get_learner(learner_name: str, session_id: str | None = None) -> dict[str, Any]:
        learner = _learner_repo(cfg).get_learner(
            session_id=session_id or cfg.session_id,
            learner_name=learner_name,
        )
        return _ok(learner or {})

    @app.get("/api/v1/learners/{learner_name}/flows", response_model=ApiResponse)
    def learner_flows(
        learner_name: str,
        session_id: str | None = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int | None = Query(None, ge=0),
        cursor: str | None = None,
    ) -> dict[str, Any]:
        result = _flow_repo(cfg).list_flows(
            session_id=session_id or cfg.session_id,
            learner_name=learner_name,
            limit=limit,
            offset=offset,
            cursor=cursor,
        )
        return _ok(FlowListData.model_validate(result).model_dump())

    return app


def _redis(cfg: TridentConfig) -> RedisStreamConsumer:
    from .redis_consumer import RedisStreamConsumer

    return RedisStreamConsumer(
        cfg.redis_url,
        stream=cfg.input_stream,
        group=cfg.consumer_group,
        consumer=cfg.consumer_name,
    )


def _flow_repo(cfg: TridentConfig):
    from .persistence.ch_flow_repository import ChFlowRepository

    return ChFlowRepository(cfg.clickhouse_dsn)


def _learner_repo(cfg: TridentConfig):
    from .persistence.learner_repository import LearnerRepository

    return LearnerRepository(cfg.postgres_dsn)


def _auth_manager():
    from .auth import AuthManager

    return AuthManager()


def _collection_settings_repo(cfg: TridentConfig):
    from .collection_settings import CollectionSettingsRepository

    return CollectionSettingsRepository(cfg.postgres_dsn)


def _pages(cfg: TridentConfig) -> PageQueryService:
    from .page_queries import PageQueryService

    return PageQueryService(
        session_id=cfg.session_id,
        flows=_flow_repo(cfg),
        learners=_learner_repo(cfg),
        redis=_redis(cfg),
    )


def _ok(data: Any) -> dict[str, Any]:
    return {"code": 200, "message": "success", "data": data}


def _time_range_start(value: str) -> str | None:
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    if value == "7d":
        start = now - timedelta(days=7)
    elif value == "30d":
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(hours=24)
    return start.isoformat(timespec="seconds").replace("+00:00", "Z")


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

    log_dir = Path(os.getenv("TRIDENT_LOG_DIR", "/var/log/trident"))
    log_file = os.getenv("TRIDENT_LOG_FILE", "api.log")
    configure_logging(service_name="trident-api", log_path=log_dir / log_file)
    args = parse_args()
    emit_event("api_bootstrap", host=args.host, port=args.port, config=args.config)
    uvicorn.run(create_app(args.config), host=args.host, port=args.port, access_log=False, log_config=None)
    return 0


app = create_app(None)


if __name__ == "__main__":
    raise SystemExit(main())
