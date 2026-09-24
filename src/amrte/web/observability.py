from __future__ import annotations

from collections import Counter
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from amrte.operations.runtime import (
    PersistentResearchRuntime,
)


def _serialize(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, Enum):
        return value.name

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, Mapping):
        return {
            str(key): _serialize(item)
            for key, item in value.items()
        }

    if isinstance(value, (tuple, list)):
        return [
            _serialize(item)
            for item in value
        ]

    if isinstance(value, (str, int, float, bool)):
        return value

    return str(value)


def _event_projection(event: Any) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_sequence": event.event_sequence,
        "timestamp": _serialize(event.timestamp),
        "runtime_environment":
            event.runtime_environment,
        "application_version":
            event.application_version,
        "instance_id": event.instance_id,
        "recovery_epoch": event.recovery_epoch,
        "experiment_id": event.experiment_id,
        "dataset_id": event.dataset_id,
        "configuration_snapshot_id":
            event.configuration_snapshot_id,
        "configuration_hash":
            event.configuration_hash,
        "module": event.module,
        "operation": event.operation,
        "severity": _serialize(event.severity),
        "classifications":
            _serialize(event.classifications),
        "category": _serialize(event.category),
        "event_type": event.event_type,
        "event_code": event.event_code,
        "message": event.message,
        "system_state": event.system_state,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "decision_id": event.decision_id,
        "checkpoint_id": event.checkpoint_id,
        "tags": _serialize(event.tags),
        "context": _serialize(event.context),
        "previous_audit_hash":
            event.previous_audit_hash,
        "event_hash": event.event_hash,
    }


def build_observability_summary(
    runtime: PersistentResearchRuntime,
) -> dict[str, Any]:
    engine = runtime.engine

    if engine is None:
        raise RuntimeError(
            "runtime engine is not available"
        )

    observability = engine.registry.require(
        "observability"
    )

    events = tuple(
        observability.events
    )

    severity_counts = Counter(
        event.severity.name
        for event in events
    )

    category_counts = Counter(
        event.category.name
        for event in events
    )

    classification_counts = Counter(
        classification.name
        for event in events
        for classification in event.classifications
    )

    module_counts = Counter(
        event.module
        for event in events
    )

    chain_valid = observability.verify_chain(
        events
    )

    latest = tuple(
        reversed(events[-100:])
    )

    registered_services = tuple(
        sorted(
            engine.registry.names()
        )
    )

    checkpoint = runtime.last_checkpoint

    return {
        "version": "1.0",
        "mode": "READ_ONLY",
        "research_only": True,
        "runtime": {
            "state": runtime.state,
            "environment": engine.environment.name,
            "recovery_epoch":
                runtime.recovery_epoch,
        },
        "authority": {
            "service":
                "ObservabilityService",
            "registered":
                "observability"
                in registered_services,
            "source":
                "engine.registry",
            "parallel_service_created":
                False,
            "mutation_enabled":
                False,
        },
        "health": {
            "observability":
                _serialize(
                    observability.health
                ),
            "chain_valid":
                chain_valid,
            "dropped_diagnostics":
                getattr(
                    observability,
                    "dropped_diagnostics",
                    0,
                ),
        },
        "retention": {
            "retained_event_count":
                len(events),
            "maximum_history":
                observability.maximum_history,
            "returned_event_count":
                len(latest),
            "returned_event_limit":
                100,
        },
        "statistics": {
            "severity":
                dict(
                    sorted(
                        severity_counts.items()
                    )
                ),
            "category":
                dict(
                    sorted(
                        category_counts.items()
                    )
                ),
            "classification":
                dict(
                    sorted(
                        classification_counts.items()
                    )
                ),
            "module":
                dict(
                    sorted(
                        module_counts.items()
                    )
                ),
        },
        "checkpoint": {
            "checkpoint_id":
                (
                    checkpoint.checkpoint_id
                    if checkpoint is not None
                    else None
                ),
            "sequence":
                (
                    checkpoint.sequence_number
                    if checkpoint is not None
                    else None
                ),
            "configuration_snapshot_id":
                (
                    checkpoint.configuration_snapshot_id
                    if checkpoint is not None
                    else None
                ),
            "configuration_hash":
                (
                    checkpoint.configuration_hash
                    if checkpoint is not None
                    else None
                ),
        },
        "capabilities": {
            "retained_events":
                True,
            "query":
                True,
            "incident_timeline":
                True,
            "chain_verification":
                True,
            "persistent_jsonl_sink":
                True,
            "log_deletion":
                False,
            "log_clearing":
                False,
            "alert_acknowledgement":
                False,
            "diagnostic_execution":
                False,
            "configuration_mutation":
                False,
        },
        "events": [
            _event_projection(event)
            for event in latest
        ],
        "registered_services":
            list(registered_services),
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
