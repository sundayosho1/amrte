from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from amrte.operations.runtime import (
    PersistentResearchRuntime,
)


VERSION = "1.0"


_HISTORY_FIELDS = (
    "checkpoint_id",
    "sequence_number",
    "previous_checkpoint_id",
    "recovery_epoch",
    "created_at",
    "shutdown_status",
    "state_schema_version",
    "application_version",
    "configuration_schema_version",
    "configuration_snapshot_id",
    "configuration_hash",
    "runtime_environment",
    "experiment_id",
    "dataset_id",
    "dataset_fingerprint",
    "payload_hash",
    "manifest_hash",
    "persistence_format_version",
)


def _serialize(value: Any) -> Any:
    name = getattr(
        value,
        "name",
        None,
    )

    if name is not None:
        return name

    return value


def _checkpoint_projection(
    checkpoint: Any,
) -> dict[str, Any]:
    if checkpoint is None:
        return {
            "available": False,
            "checkpoint_id": None,
            "sequence_number": None,
            "previous_checkpoint_id": None,
            "recovery_epoch": None,
            "created_at": None,
            "shutdown_status": None,
            "configuration_snapshot_id": None,
            "configuration_hash": None,
            "dataset_id": None,
            "dataset_fingerprint": None,
        }

    return {
        "available": True,
        "checkpoint_id":
            checkpoint.checkpoint_id,
        "sequence_number":
            checkpoint.sequence_number,
        "previous_checkpoint_id":
            checkpoint.previous_checkpoint_id,
        "recovery_epoch":
            checkpoint.recovery_epoch,
        "created_at":
            checkpoint.created_at.isoformat(),
        "shutdown_status":
            checkpoint.shutdown_status.name,
        "configuration_snapshot_id":
            checkpoint.configuration_snapshot_id,
        "configuration_hash":
            checkpoint.configuration_hash,
        "dataset_id":
            checkpoint.dataset_id,
        "dataset_fingerprint":
            checkpoint.dataset_fingerprint,
    }


def _history_projection(
    repository: Any,
) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []

    for path in repository.enumerate_checkpoints():
        try:
            raw = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
        ) as exc:
            history.append(
                {
                    "file": path.name,
                    "readable": False,
                    "error":
                        type(exc).__name__,
                }
            )
            continue

        entry = {
            "file": path.name,
            "readable": True,
        }

        for field in _HISTORY_FIELDS:
            entry[field] = raw.get(field)

        history.append(entry)

    history.sort(
        key=lambda item: (
            item.get("sequence_number")
            if isinstance(
                item.get("sequence_number"),
                int,
            )
            else -1
        ),
        reverse=True,
    )

    return history


def build_persistence_recovery_summary(
    runtime: PersistentResearchRuntime,
) -> dict[str, Any]:
    """Build the read-only persistence and recovery view."""

    engine = runtime.engine

    if engine is None:
        raise RuntimeError(
            "AMRTE runtime is not initialized"
        )

    repository = runtime.repository

    if repository is None:
        raise RuntimeError(
            "AMRTE checkpoint repository is unavailable"
        )

    configuration = engine.configuration

    if configuration is None:
        raise RuntimeError(
            "AMRTE configuration is unavailable"
        )

    chain = repository.validate_chain()

    checkpoint = runtime.last_checkpoint

    recovery_report = runtime.recovery_report

    checkpoint_paths = (
        repository.enumerate_checkpoints()
    )

    history = _history_projection(
        repository
    )

    values = configuration.values

    if recovery_report is None:
        recovery = {
            "required": False,
            "outcome": "NEW_RUN",
            "confidence": None,
            "ready": True,
            "used_fallback": False,
            "recovery_epoch":
                runtime.recovery_epoch,
            "checkpoint_id": None,
            "warnings": [],
            "reasons": [],
        }
    else:
        recovery = {
            "required": True,
            "outcome":
                recovery_report.outcome.name,
            "confidence":
                recovery_report.confidence.name,
            "ready":
                recovery_report.ready,
            "used_fallback":
                recovery_report.used_fallback,
            "recovery_epoch":
                recovery_report.recovery_epoch,
            "checkpoint_id": (
                recovery_report.checkpoint.checkpoint_id
                if recovery_report.checkpoint
                is not None
                else None
            ),
            "warnings":
                list(recovery_report.warnings),
            "reasons":
                list(recovery_report.reasons),
        }

    chain_warnings = list(
        getattr(
            chain,
            "warnings",
            (),
        )
    )

    chain_error = None

    if not chain.success:
        error = getattr(
            chain,
            "error",
            None,
        )

        if error is not None:
            chain_error = {
                "code":
                    getattr(
                        error,
                        "code",
                        None,
                    ),
                "message":
                    getattr(
                        error,
                        "message",
                        None,
                    ),
            }

    state_root = getattr(
        repository,
        "root",
        None,
    )

    storage_health = _serialize(
        getattr(
            repository,
            "health",
            None,
        )
    )

    recovery_ready = (
        recovery["ready"]
        and chain.success
    )

    return {
        "version": VERSION,
        "mode": "READ_ONLY",
        "research_only": True,

        "runtime": {
            "state":
                runtime.state,
            "environment":
                engine.environment.name,
            "recovery_epoch":
                runtime.recovery_epoch,
        },

        "authority": {
            "repository":
                type(repository).__name__,
            "source":
                "runtime.repository",
            "parallel_repository_created":
                False,
            "mutation_enabled":
                False,
        },

        "checkpoint":
            _checkpoint_projection(
                checkpoint
            ),

        "lineage": {
            "checkpoint_id": (
                checkpoint.checkpoint_id
                if checkpoint is not None
                else None
            ),
            "previous_checkpoint_id": (
                checkpoint.previous_checkpoint_id
                if checkpoint is not None
                else None
            ),
            "sequence_number": (
                checkpoint.sequence_number
                if checkpoint is not None
                else None
            ),
            "generation_count":
                len(checkpoint_paths),
        },

        "chain_integrity": {
            "valid":
                chain.success,
            "warnings":
                chain_warnings,
            "error":
                chain_error,
        },

        "persistence_configuration": {
            "minimum_interval_seconds":
                values.get(
                    "persistence.minimum_interval_seconds"
                ),
            "maximum_uncheckpointed_events":
                values.get(
                    "persistence.maximum_uncheckpointed_events"
                ),
            "retention_generations":
                values.get(
                    "persistence.retention_generations"
                ),
            "maximum_checkpoint_bytes":
                values.get(
                    "persistence.maximum_checkpoint_bytes"
                ),
        },

        "recovery":
            recovery,

        "storage": {
            "state_root": (
                str(state_root)
                if state_root is not None
                else None
            ),
            "health":
                storage_health,
            "checkpoint_count":
                len(checkpoint_paths),
            "current_present":
                any(
                    path.name
                    == repository.CURRENT
                    for path
                    in checkpoint_paths
                ),
            "previous_present":
                any(
                    path.name
                    == repository.PREVIOUS
                    for path
                    in checkpoint_paths
                ),
        },

        "recovery_readiness": {
            "ready":
                recovery_ready,
            "chain_valid":
                chain.success,
            "runtime_running":
                runtime.state
                == "RUNNING",
            "recovery_report_ready":
                recovery["ready"],
        },

        "checkpoint_history":
            history,

        "durability_safeguards": {
            "minimum_retention_generations":
                2,
            "configured_retention_generations":
                values.get(
                    "persistence.retention_generations"
                ),
            "maximum_checkpoint_bytes":
                values.get(
                    "persistence.maximum_checkpoint_bytes"
                ),
            "chain_verification":
                True,
            "payload_exposure":
                False,
            "automatic_quarantine_from_api":
                False,
        },

        "capabilities": {
            "checkpoint_observation":
                True,
            "chain_verification":
                True,
            "history_observation":
                True,
            "checkpoint_creation":
                False,
            "restore":
                False,
            "rollback":
                False,
            "quarantine":
                False,
            "deletion":
                False,
            "recovery_execution":
                False,
            "configuration_mutation":
                False,
        },

        "execution_boundary": {
            "capability":
                "PROHIBITED",
            "provider":
                type(
                    engine.registry.require(
                        "execution"
                    )
                ).__name__,
            "financial_execution_available":
                False,
        },
    }
