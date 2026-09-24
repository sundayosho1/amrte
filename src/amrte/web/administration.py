from __future__ import annotations

from typing import Any

from amrte.core.constants import AMRTE_VERSION
from amrte.operations.runtime import (
    DATASET_ID,
    EXPERIMENT_ID,
)


VERSION = AMRTE_VERSION


MANDATORY_SERVICES = (
    "configuration",
    "state",
    "clock",
    "audit",
    "observability",
    "execution",
    "health",
    "random",
)


def _name(value: Any) -> str:
    if hasattr(value, "name"):
        return str(value.name)

    return str(value)


def _configuration_identity(
    configuration: Any,
) -> dict[str, object]:
    return {
        "snapshot_id": (
            configuration.snapshot_id
        ),
        "configuration_hash": (
            configuration.configuration_hash
        ),
    }


def _registered_services(
    engine: Any,
) -> list[dict[str, object]]:
    projected: list[
        dict[str, object]
    ] = []

    for name in MANDATORY_SERVICES:
        service = engine.registry.require(
            name
        )

        projected.append(
            {
                "name": name,
                "type": type(
                    service
                ).__name__,
            }
        )

    return projected


def _persistence_projection(
    runtime: Any,
) -> dict[str, object]:
    repository = runtime.repository

    if repository is None:
        return {
            "repository": None,
            "chain_valid": False,
            "mutation_allowed": False,
        }

    chain = repository.validate_chain()

    return {
        "repository": type(
            repository
        ).__name__,
        "chain_valid": bool(
            chain.success
        ),
        "mutation_allowed": False,
    }


def build_administration_summary(
    runtime: Any,
) -> dict[str, object]:
    engine = runtime.engine

    if engine is None:
        raise RuntimeError(
            "runtime engine is unavailable"
        )

    configuration = engine.configuration

    execution = engine.registry.require(
        "execution"
    )

    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "system_identity": {
            "version": VERSION,
            "environment": (
                engine.environment.name
            ),
            "experiment_id": (
                EXPERIMENT_ID
            ),
            "dataset_id": (
                DATASET_ID
            ),
        },
        "runtime": {
            "state": runtime.state,
            "environment": (
                engine.environment.name
            ),
        },
        "configuration": (
            _configuration_identity(
                configuration
            )
        ),
        "registered_services": (
            _registered_services(
                engine
            )
        ),
        "persistence": (
            _persistence_projection(
                runtime
            )
        ),
        "permissions": {
            "administration_rbac": False,
            "claims_authority": False,
            "invented_permissions": False,
        },
        "capabilities": {
            "view_system_identity": True,
            "view_services": True,
            "view_safeguards": True,
            "mutate_configuration": False,
            "register_services": False,
            "mutate_persistence": False,
            "run_diagnostics": False,
            "restore_state": False,
            "enable_execution": False,
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
