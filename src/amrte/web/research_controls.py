"""Read-only research-control authority view over the active AMRTE runtime."""

from __future__ import annotations

from typing import Any

from amrte.operations.runtime import PersistentResearchRuntime


CONTROL_SERVICE_NAMES = (
    "dashboard",
    "research",
    "research_control",
    "controls",
    "workflow",
    "lifecycle",
    "protection",
    "safety",
)

GOVERNED_CONTROL_CATALOG = (
    {
        "action": "PAUSE_RESEARCH",
        "category": "RESEARCH_LIFECYCLE",
        "available": False,
        "reason": "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED",
    },
    {
        "action": "RESUME_RESEARCH",
        "category": "RESEARCH_LIFECYCLE",
        "available": False,
        "reason": "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED",
    },
    {
        "action": "REQUEST_RECONCILIATION",
        "category": "RECOVERY",
        "available": False,
        "reason": "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED",
    },
    {
        "action": "REQUEST_DIAGNOSTICS",
        "category": "DIAGNOSTICS",
        "available": False,
        "reason": "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED",
    },
    {
        "action": "ACKNOWLEDGE_ALERT",
        "category": "OBSERVABILITY",
        "available": False,
        "reason": "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED",
    },
    {
        "action": "EXPORT_RESEARCH",
        "category": "RESEARCH_DATA",
        "available": False,
        "reason": "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED",
    },
    {
        "action": "CHANGE_PREFERENCES",
        "category": "DASHBOARD",
        "available": False,
        "reason": "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED",
    },
)


def _service_descriptor(
    runtime: PersistentResearchRuntime,
    name: str,
) -> dict[str, Any]:
    """Describe a registered service without mutating it."""

    registry = runtime.engine.registry
    service = registry.require(name)

    return {
        "name": name,
        "module": type(service).__module__,
        "type": type(service).__name__,
    }


def build_research_control_authority(
    runtime: PersistentResearchRuntime,
) -> dict[str, Any]:
    """Build the read-only research-control authority view."""

    if runtime.engine is None:
        raise RuntimeError("RUNTIME_NOT_STARTED")

    engine = runtime.engine
    registry = engine.registry
    registered_names = tuple(registry.names())
    registered_set = set(registered_names)

    control_services = {
        name: name in registered_set
        for name in CONTROL_SERVICE_NAMES
    }

    authoritative_control_services = tuple(
        name
        for name in CONTROL_SERVICE_NAMES
        if name in registered_set
    )

    execution = registry.require("execution")

    services = tuple(
        _service_descriptor(runtime, name)
        for name in registered_names
    )

    controls_available = bool(
        authoritative_control_services
    )

    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "runtime": {
            "state": engine.state_machine.state.name,
            "environment": engine.environment.name,
            "recovery_epoch": runtime.recovery_epoch,
        },
        "authority": {
            "controls_available": controls_available,
            "mutation_enabled": False,
            "authoritative_control_service_registered":
                controls_available,
            "reason": (
                "READ_ONLY_WEB_POLICY"
                if controls_available
                else
                "AUTHORITATIVE_CONTROL_SERVICE_NOT_REGISTERED"
            ),
        },
        "execution_boundary": {
            "capability": "PROHIBITED",
            "provider": type(execution).__name__,
            "financial_execution_available": False,
        },
        "control_services": control_services,
        "registered_services": services,
        "governed_controls": GOVERNED_CONTROL_CATALOG,
        "state_machine": {
            "state": engine.state_machine.state.name,
            "direct_web_transition_allowed": False,
        },
    }
