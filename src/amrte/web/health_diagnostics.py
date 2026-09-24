from __future__ import annotations

from typing import Any

from amrte.core.constants import AMRTE_VERSION
from amrte.core.engine import MANDATORY_SERVICES
from amrte.core.types import HealthStatus


def _name(value: Any) -> str:
    if value is None:
        return "UNKNOWN"

    name = getattr(
        value,
        "name",
        None,
    )

    if name is not None:
        return str(name)

    return str(value)


def _configuration_identity(
    configuration: Any,
) -> dict[str, object]:
    return {
        "snapshot_id": getattr(
            configuration,
            "snapshot_id",
            None,
        ),
        "configuration_hash": getattr(
            configuration,
            "configuration_hash",
            None,
        ),
        "validation_status": _name(
            getattr(
                configuration,
                "validation_status",
                None,
            )
        ),
        "schema_version": getattr(
            configuration,
            "schema_version",
            None,
        ),
    }


def _mandatory_service_projection(
    engine: Any,
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, HealthStatus],
]:
    projected: dict[
        str,
        dict[str, object],
    ] = {}

    components: dict[
        str,
        HealthStatus,
    ] = {}

    for name in MANDATORY_SERVICES:
        try:
            service = engine.registry.require(
                name
            )

            status = HealthStatus.HEALTHY

            if name == "observability":
                observed = _name(
                    getattr(
                        service,
                        "health",
                        None,
                    )
                )

                if observed != "HEALTHY":
                    status = (
                        HealthStatus.UNHEALTHY
                    )

            projected[name] = {
                "registered": True,
                "type": type(
                    service
                ).__name__,
                "status": status.name,
            }

            components[name] = status

        except Exception:
            projected[name] = {
                "registered": False,
                "type": None,
                "status": (
                    HealthStatus.UNKNOWN.name
                ),
            }

            components[name] = (
                HealthStatus.UNKNOWN
            )

    return projected, components


def _observability_projection(
    engine: Any,
) -> dict[str, object]:
    observability = engine.registry.require(
        "observability"
    )

    health = _name(
        getattr(
            observability,
            "health",
            None,
        )
    )

    chain_valid = (
        health == "HEALTHY"
    )

    return {
        "status": health,
        "chain_valid": chain_valid,
        "dropped_diagnostics": getattr(
            observability,
            "dropped_diagnostics",
            0,
        ),
    }


def _persistence_projection(
    runtime: Any,
) -> tuple[
    dict[str, object],
    dict[str, object],
]:
    repository = runtime.repository

    if repository is None:
        return (
            {
                "repository": None,
                "storage_health": "UNKNOWN",
                "chain_valid": False,
            },
            {
                "ready": False,
                "epoch": runtime.recovery_epoch,
            },
        )

    chain = repository.validate_chain()

    chain_valid = bool(
        chain.success
    )

    storage_health = (
        "HEALTHY"
        if chain_valid
        else "UNHEALTHY"
    )

    latest = runtime.last_checkpoint

    recovery_ready = (
        chain_valid
        and latest is not None
    )

    return (
        {
            "repository": type(
                repository
            ).__name__,
            "storage_health": (
                storage_health
            ),
            "chain_valid": chain_valid,
        },
        {
            "ready": recovery_ready,
            "epoch": runtime.recovery_epoch,
        },
    )


def build_health_diagnostics_summary(
    runtime: Any,
) -> dict[str, object]:
    engine = runtime.engine

    if engine is None:
        raise RuntimeError(
            "runtime engine is unavailable"
        )

    health_service = (
        engine.registry.require(
            "health"
        )
    )

    services, components = (
        _mandatory_service_projection(
            engine
        )
    )

    report = health_service.assess(
        components,
        MANDATORY_SERVICES,
    )

    observability = (
        _observability_projection(
            engine
        )
    )

    persistence, recovery = (
        _persistence_projection(
            runtime
        )
    )

    execution = engine.registry.require(
        "execution"
    )

    configuration = engine.configuration
    composition = getattr(runtime, "composition", None)
    composition_diagnostics = (
        composition.diagnostics()
        if composition is not None
        else {
            "components": [],
            "readiness": {
                "ready": False,
                "reasons": ["composition:UNAVAILABLE"],
            },
            "health": {
                "ready": False,
                "reasons": ["composition:UNAVAILABLE"],
                "components": {},
            },
            "research_pipeline": {
                "registered": False,
                "active": False,
                "status": "NOT_REGISTERED",
            },
        }
    )

    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "runtime": {
            "state": runtime.state,
            "environment": (
                engine.environment.name
            ),
            "version": AMRTE_VERSION,
        },
        "authority": {
            "health_service": type(
                health_service
            ).__name__,
            "source": "engine.registry",
            "parallel_health_engine": False,
            "diagnostic_execution": False,
        },
        "readiness": {
            "ready": report.ready,
            "reasons": list(
                report.reasons
            ),
        },
        "composition": {
            "available": composition is not None,
            "readiness": composition_diagnostics[
                "readiness"
            ],
            "health": composition_diagnostics[
                "health"
            ],
            "component_count": len(
                composition_diagnostics[
                    "components"
                ]
            ),
            "research_pipeline": (
                composition_diagnostics[
                    "research_pipeline"
                ]
            ),
        },
        "mandatory_services": services,
        "observability": observability,
        "persistence": persistence,
        "recovery": recovery,
        "configuration": (
            _configuration_identity(
                configuration
            )
        ),
        "capabilities": {
            "view_health": True,
            "view_service_status": True,
            "view_observability_health": True,
            "view_persistence_health": True,
            "run_diagnostics": False,
            "resolve_alerts": False,
            "prepare_updates": False,
            "restore_state": False,
            "mutate_health": False,
        },
        "execution_boundary": {
            "status": "PROHIBITED",
            "provider": type(
                execution
            ).__name__,
            "financial_execution": False,
            "broker_connectivity": False,
            "account_connectivity": False,
        },
    }
