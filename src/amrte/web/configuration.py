from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any

from amrte.operations.runtime import PersistentResearchRuntime


def _serialize(value: Any) -> Any:
    """Convert configuration values into JSON-safe representations."""

    if isinstance(value, Enum):
        return value.name

    if isinstance(value, tuple):
        return [_serialize(item) for item in value]

    if isinstance(value, list):
        return [_serialize(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _serialize(item)
            for key, item in value.items()
        }

    return value


def build_configuration_summary(
    runtime: PersistentResearchRuntime,
) -> dict[str, Any]:
    """Build the read-only effective configuration view."""

    if runtime.engine is None:
        raise RuntimeError("AMRTE runtime is not initialized")

    configuration = runtime.engine.configuration

    if configuration is None:
        raise RuntimeError(
            "AMRTE configuration is unavailable"
        )

    sections: dict[str, list[dict[str, Any]]] = {}

    provenance_counts = Counter(
        configuration.provenance.values()
    )

    for key in sorted(configuration.values):
        value = configuration.values[key]

        section = key.split(".", 1)[0]

        parameter = {
            "key": key,
            "name": (
                key.split(".", 1)[1]
                if "." in key
                else key
            ),
            "value": _serialize(value),
            "value_type": type(value).__name__,
            "provenance": configuration.provenance.get(
                key
            ),
            "overridden_sources": list(
                configuration.overridden_sources.get(
                    key,
                    (),
                )
            ),
        }

        sections.setdefault(
            section,
            [],
        ).append(parameter)

    section_list = [
        {
            "name": name,
            "parameter_count": len(parameters),
            "parameters": parameters,
        }
        for name, parameters in sorted(
            sections.items()
        )
    ]

    selected_profile = configuration.selected_profile

    profile_name = getattr(
        selected_profile,
        "name",
        str(selected_profile),
    )

    validation_status = configuration.validation_status

    validation_name = getattr(
        validation_status,
        "name",
        str(validation_status),
    )

    runtime_environment = configuration.runtime_environment

    environment_name = getattr(
        runtime_environment,
        "name",
        str(runtime_environment),
    )

    return {
        "metadata": {
            "application_version": (
                configuration.application_version
            ),
            "runtime_environment": environment_name,
            "schema_version": configuration.schema_version,
            "snapshot_id": configuration.snapshot_id,
            "configuration_hash": (
                configuration.configuration_hash
            ),
            "created_at": (
                configuration.created_at.isoformat()
            ),
        },
        "profile": {
            "selected": profile_name,
        },
        "validation": {
            "status": validation_name,
            "valid": validation_name == "VALID",
            "warning_count": len(
                configuration.warnings
            ),
            "warnings": [
                _serialize(warning)
                for warning in configuration.warnings
            ],
        },
        "statistics": {
            "parameter_count": len(
                configuration.values
            ),
            "section_count": len(sections),
            "provenance": dict(
                sorted(provenance_counts.items())
            ),
            "overridden_parameter_count": len(
                configuration.overridden_sources
            ),
        },
        "sections": section_list,
    }


def build_configuration_safeguards(
    runtime: PersistentResearchRuntime,
) -> dict[str, Any]:
    """Expose research-boundary configuration safeguards."""

    if runtime.engine is None:
        raise RuntimeError("AMRTE runtime is not initialized")

    configuration = runtime.engine.configuration

    if configuration is None:
        raise RuntimeError(
            "AMRTE configuration is unavailable"
        )

    values = configuration.values
    provenance = configuration.provenance

    keys = (
        "broker.authentication",
        "broker.demo_execution",
        "broker.live_execution",
        "execution.available",
        "runtime.allow_hot_reload",
        "safety.martingale",
        "safety.unlimited_exposure",
        "risk.adaptive.allow_risk_amplification",
    )

    safeguards = []

    for key in keys:
        safeguards.append(
            {
                "key": key,
                "value": _serialize(
                    values.get(key)
                ),
                "provenance": provenance.get(key),
            }
        )

    return {
        "research_only": True,
        "execution": "PROHIBITED",
        "safeguards": safeguards,
    }
