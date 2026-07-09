"""FastAPI application factory: middleware, error envelope, health/readiness, routes."""
from __future__ import annotations

import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text

from service.api.ingestions import router as ingestions_router
from service.api.query import router as query_router
from service.db import engine
from service.errors import install_error_handlers
from service.observability import configure_logging
from service.queue import redis_conn
from service import metrics, storage


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Takeoff Ingestion Service", version="1.0.0")
    install_error_handlers(app)

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = rid
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        # record RED metrics against the ROUTE TEMPLATE (bounded cardinality, not the raw path)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        if path != "/metrics":
            metrics.REQUESTS.labels(request.method, path, response.status_code).inc()
            metrics.REQUEST_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
        return response

    @app.get("/metrics", tags=["observability"])
    def metrics_endpoint() -> Response:
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type)

    @app.on_event("startup")
    def _startup() -> None:
        # Local convenience: make sure the artifact bucket exists. Best-effort — the
        # createbuckets init also makes it, and /readyz reports object-store health, so a
        # transient MinIO delay must not stop the API from coming up.
        try:
            storage.ensure_bucket()
        except Exception:
            pass

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    def readyz() -> JSONResponse:
        checks = {"database": False, "redis": False, "object_store": False}
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            pass
        try:
            redis_conn().ping()
            checks["redis"] = True
        except Exception:
            pass
        try:
            storage.ping()
            checks["object_store"] = True
        except Exception:
            pass
        ready = all(checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"ready": ready, "checks": checks},
        )

    app.include_router(ingestions_router)
    app.include_router(query_router)
    return app


app = create_app()
