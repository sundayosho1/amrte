from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from amrte.core.constants import AMRTE_VERSION
from amrte.web.administration import build_administration_summary
from amrte.web.research_evidence import build_research_evidence_summary
from amrte.web.research_governance import build_research_governance_summary
from amrte.web.research_lifecycle_quality import (
    build_research_lifecycle_quality_payload,
)
from amrte.web.health_diagnostics import build_health_diagnostics_summary

from amrte.operations.runtime import PersistentResearchRuntime
from amrte.web.operational_readiness import operational_readiness_projection
from amrte.web.dataset_replay import build_dataset_replay_integrity
from amrte.web.research_controls import build_research_control_authority
from amrte.web.configuration import (
    build_configuration_safeguards,
    build_configuration_summary,
)
from amrte.web.dashboard import build_dashboard_summary
from amrte.web.observability import (
    build_observability_summary,
)
from amrte.web.persistence_recovery import (
    build_persistence_recovery_summary,
)
from amrte.web.runtime_composition import (
    build_runtime_composition_summary,
)
from amrte.web.market_data_boundary import (
    build_market_data_boundary_summary,
)
from amrte.web.data_quality_runtime import (
    build_data_quality_runtime_summary,
)
from amrte.web.market_intelligence import (
    build_market_intelligence_summary,
)
from amrte.web.strategy_evaluation import (
    build_strategy_evaluation_summary,
)
from amrte.web.research_scoring import (
    build_research_scoring_summary,
)
from amrte.web.research_portfolio import (
    build_research_portfolio_summary,
)
from amrte.web.research_protection import (
    build_research_protection_summary,
)
from amrte.web.research_decisions import (
    build_research_decisions_summary,
)


VERSION = AMRTE_VERSION
WEB_VERSION = "1.0"
ENVIRONMENT = "RESEARCH"

STATIC_ROOT = Path(__file__).resolve().parent / "static"

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

    @app.get("/", include_in_schema=False)
    def root() -> FileResponse:
        return FileResponse(
            STATIC_ROOT / "index.html",
            media_type="text/html",
        )
    @app.get(
        "/configuration",
        include_in_schema=False,
    )
    def configuration_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT / "configuration.html",
            media_type="text/html",
        )

    @app.get(
        "/research-controls",
        include_in_schema=False,
    )
    def research_controls_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT / "research-controls.html",
            media_type="text/html",
        )

    @app.get(
        "/dataset-replay",
        include_in_schema=False,
    )
    def dataset_replay_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT / "dataset-replay.html",
            media_type="text/html",
        )

    @app.get(
        "/observability",
        include_in_schema=False,
    )
    def observability_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT / "observability.html",
            media_type="text/html",
        )

    @app.get("/api/v1/research-controls")
    def research_controls(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_control_authority(
            runtime
        )

    @app.get("/api/v1/dataset-replay")
    def dataset_replay(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_dataset_replay_integrity(
            runtime
        )

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
        composition = runtime.composition
        composition_diagnostics = (
            composition.diagnostics()
            if composition is not None
            else None
        )

        return {
            "status": (
                "HEALTHY"
                if state == "RUNNING"
                else "NOT_RUNNING"
            ),
            "engine_state": state,
            "core_runtime_state": state,
            "component_readiness": (
                composition_diagnostics["readiness"]
                if composition_diagnostics is not None
                else {
                    "ready": False,
                    "reasons": ["composition:UNAVAILABLE"],
                }
            ),
            "component_health": (
                composition_diagnostics["health"]
                if composition_diagnostics is not None
                else {
                    "ready": False,
                    "reasons": ["composition:UNAVAILABLE"],
                }
            ),
            "research_pipeline": (
                composition_diagnostics["research_pipeline"]
                if composition_diagnostics is not None
                else {
                    "active": False,
                    "status": "NOT_REGISTERED",
                }
            ),
            "research_mode": "RESEARCH-ONLY",
            "execution": "PROHIBITED",
        }

    @app.get(
        "/health-diagnostics",
        include_in_schema=False,
    )
    def health_diagnostics_page():
        return FileResponse(
            STATIC_ROOT
            / "health-diagnostics.html",
        )

    @app.get("/api/v1/health-diagnostics")
    def health_diagnostics_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime

        return build_health_diagnostics_summary(
            runtime
        )

    @app.get("/api/v1/observability")
    def observability_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_observability_summary(
            runtime
        )

    @app.get(
        "/persistence-recovery",
        include_in_schema=False,
    )
    def persistence_recovery_page():
        return FileResponse(
            STATIC_ROOT
            / "persistence-recovery.html",
        )


    @app.get(
        "/administration",
        include_in_schema=False,
    )
    def administration_page():
        return FileResponse(
            STATIC_ROOT
            / "administration.html",
        )

    @app.get("/api/v1/persistence-recovery")
    def persistence_recovery_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_persistence_recovery_summary(
            runtime
        )


    @app.get(
        "/research-evidence",
        include_in_schema=False,
    )
    def research_evidence_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT
            / "research-evidence.html",
            media_type="text/html",
        )

    @app.get(
        "/research-governance",
        include_in_schema=False,
    )
    def research_governance_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT
            / "research-governance.html",
            media_type="text/html",
        )

    @app.get(
        "/research-lifecycle-quality",
        include_in_schema=False,
    )
    def research_lifecycle_quality_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT / "research-lifecycle-quality.html",
            media_type="text/html",
        )
    @app.get(
        "/operational-readiness",
        include_in_schema=False,
    )
    def operational_readiness_page() -> FileResponse:
        return FileResponse(
            STATIC_ROOT
            / "operational-readiness.html",
            media_type="text/html",
        )
    @app.get("/api/v1/research-evidence")
    def research_evidence(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_evidence_summary(
            runtime
        )

    @app.get("/api/v1/research-governance")
    def research_governance(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_governance_summary(
            runtime
        )

    @app.get("/api/v1/research-lifecycle-quality")
    def research_lifecycle_quality(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_lifecycle_quality_payload(
            runtime
        )
    @app.get("/api/v1/operational-readiness")
    def operational_readiness(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return operational_readiness_projection(
            runtime
        )
    @app.get("/api/v1/administration")
    def administration_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_administration_summary(
            runtime
        )

    @app.get("/api/v1/runtime-composition")
    def runtime_composition_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_runtime_composition_summary(
            runtime
        )

    @app.get("/api/v1/market-data-boundary")
    def market_data_boundary_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_market_data_boundary_summary(
            runtime
        )

    @app.get("/api/v1/data-quality-runtime")
    def data_quality_runtime_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_data_quality_runtime_summary(
            runtime
        )

    @app.get("/api/v1/market-intelligence")
    def market_intelligence_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_market_intelligence_summary(
            runtime
        )

    @app.get("/api/v1/strategy-evaluation")
    def strategy_evaluation_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_strategy_evaluation_summary(
            runtime
        )

    @app.get("/api/v1/research-scoring")
    def research_scoring_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_scoring_summary(
            runtime
        )

    @app.get("/api/v1/research-portfolio")
    def research_portfolio_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_portfolio_summary(
            runtime
        )

    @app.get("/api/v1/research-protection")
    def research_protection_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_protection_summary(
            runtime
        )

    @app.get("/api/v1/research-decisions")
    def research_decisions_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_research_decisions_summary(
            runtime
        )

    @app.get("/api/v1/dashboard/summary")
    def dashboard_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_dashboard_summary(runtime)

    @app.get("/api/v1/configuration")
    def configuration_summary(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_configuration_summary(runtime)

    @app.get("/api/v1/configuration/safeguards")
    def configuration_safeguards(
        request: Request,
    ) -> dict[str, object]:
        runtime = request.app.state.runtime
        return build_configuration_safeguards(runtime)

    app.mount(
        "/static",
        StaticFiles(directory=STATIC_ROOT),
        name="static",
    )

    return app


app = create_app()








