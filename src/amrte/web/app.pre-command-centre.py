from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request

from amrte.operations.runtime import PersistentResearchRuntime
from amrte.web.dashboard import build_dashboard_summary


VERSION = "0.27.0"
WEB_VERSION = "1.0"
ENVIRONMENT = "RESEARCH"

RuntimeFactory = Callable[[], PersistentResearchRuntime]


def default_runtime_factory() -> PersistentResearchRuntime:
    return PersistentResearchRuntime()


def create_app(
    runtime_factory: RuntimeFactory = default_runtime_factory,
) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = runtime_factory()
        runtime.start()

        app.state.runtime = runtime
        app.state.engine = runtime.engine

        try:
            yield
        finally:
            runtime.shutdown()

    app = FastAPI(
        title="AMRTE Research Console",
        description=(
            "Local research operations and configuration console "
            "for AMRTE."
        ),
        version=VERSION,
        lifespan=lifespan,
    )

    @app.get("/")
    def root(request: Request) -> dict[str, object]:
        runtime = request.app.state.runtime

        return {
            "application": "AMRTE Research Console",
            "version": VERSION,
            "web_version": WEB_VERSION,
            "environment": ENVIRONMENT,
            "research_mode": "RESEARCH-ONLY",
            "execution": "PROHIBITED",
            "status": runtime.state,
        }

    @app.get("/api/v1")
    def api_root() -> dict[str, object]:
        return {
            "api": "AMRTE Local API",
            "version": "v1",
            "research_mode": "RESEARCH-ONLY",
            "execution": "PROHIBITED",
        }

    @app.get("/api/v1/system/status")
    def system_status(request: Request) -> dict[str, object]:
        runtime = request.app.state.runtime

        return {
            "version": VERSION,
            "environment": ENVIRONMENT,
            "state": runtime.state,
            "research_mode": "RESEARCH-ONLY",
            "execution": "PROHIBITED",
        }

    @app.get("/api/v1/system/health")
    def system_health(request: Request) -> dict[str, object]:
        runtime = request.app.state.runtime
        state = runtime.state

        return {
            "status": (
                "HEALTHY"
                if state == "RUNNING"
                else "NOT_RUNNING"
            ),
            "engine_state": state,
            "research_mode": "RESEARCH-ONLY",
            "execution": "PROHIBITED",
        }

    @app.get("/api/v1/dashboard/summary")
    def dashboard_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_dashboard_summary(runtime)

    return app


app = create_app()


