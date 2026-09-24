from __future__ import annotations

from typing import Any

from amrte.operations.runtime import (
    ENVIRONMENT,
    VERSION,
    PersistentResearchRuntime,
)


def build_dashboard_summary(
    runtime: PersistentResearchRuntime,
) -> dict[str, Any]:
    """Build a read-only summary from authoritative AMRTE state."""

    if runtime.engine is None:
        raise RuntimeError("AMRTE runtime is not initialized")

    engine = runtime.engine
    configuration = engine.configuration

    if configuration is None:
        raise RuntimeError("AMRTE configuration is unavailable")

    repository = runtime.repository

    if repository is None:
        raise RuntimeError(
            "AMRTE checkpoint repository is unavailable"
        )

    latest = repository.latest_valid(
        quarantine_invalid=False,
    )

    checkpoint = latest.value if latest.success else None

    chain = repository.validate_chain()

    recovery = runtime.recovery_report

    if recovery is None:
        recovery_summary = {
            "required": False,
            "outcome": "NEW_RUN",
            "confidence": None,
            "ready": True,
            "recovery_epoch": runtime.recovery_epoch,
            "checkpoint_id": None,
        }
    else:
        recovery_summary = {
            "required": True,
            "outcome": recovery.outcome.name,
            "confidence": recovery.confidence.name,
            "ready": recovery.ready,
            "recovery_epoch": recovery.recovery_epoch,
            "checkpoint_id": (
                recovery.checkpoint.checkpoint_id
                if recovery.checkpoint is not None
                else None
            ),
        }

    if checkpoint is None:
        checkpoint_summary = {
            "available": False,
            "checkpoint_id": None,
            "sequence_number": None,
            "previous_checkpoint_id": None,
            "recovery_epoch": runtime.recovery_epoch,
            "shutdown_status": None,
        }
    else:
        checkpoint_summary = {
            "available": True,
            "checkpoint_id": checkpoint.checkpoint_id,
            "sequence_number": checkpoint.sequence_number,
            "previous_checkpoint_id": (
                checkpoint.previous_checkpoint_id
            ),
            "recovery_epoch": checkpoint.recovery_epoch,
            "shutdown_status": checkpoint.shutdown_status.name,
        }

    return {
        "application": {
            "name": "AMRTE Research Console",
            "version": VERSION,
            "environment": ENVIRONMENT,
            "research_mode": "RESEARCH-ONLY",
            "execution": "PROHIBITED",
        },
        "runtime": {
            "state": runtime.state,
            "operational": runtime.state == "RUNNING",
        },
        "configuration": {
            "schema_version": configuration.schema_version,
            "snapshot_id": configuration.snapshot_id,
            "configuration_hash": (
                configuration.configuration_hash
            ),
            "selected_profile": configuration.selected_profile,
            "validation_status": (
                configuration.validation_status.name
            ),
            "warnings": list(configuration.warnings),
        },
        "recovery": recovery_summary,
        "checkpoint": checkpoint_summary,
        "persistence": {
            "chain_valid": chain.success,
            "fallback_used": (
                repository.last_load_used_fallback
            ),
        },
    }
