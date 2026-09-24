from __future__ import annotations

from typing import Any


def build_runtime_composition_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)

    if composition is None:
        return {
            "mode": "READ_ONLY",
            "research_only": True,
            "runtime_state": runtime.state,
            "composition_available": False,
            "components": [],
            "readiness": {
                "ready": False,
                "reasons": ["composition:UNAVAILABLE"],
            },
            "health": {
                "ready": False,
                "reasons": ["composition:UNAVAILABLE"],
            },
            "research_pipeline": {
                "registered": False,
                "active": False,
                "status": "NOT_REGISTERED",
            },
        }

    diagnostics = composition.diagnostics()

    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "runtime_state": runtime.state,
        "composition_available": True,
        "registry_frozen": diagnostics["registry_frozen"],
        "validated": diagnostics["validated"],
        "initialization_order": diagnostics["initialization_order"],
        "shutdown_order": diagnostics["shutdown_order"],
        "readiness": diagnostics["readiness"],
        "health": diagnostics["health"],
        "components": diagnostics["components"],
        "research_pipeline": diagnostics["research_pipeline"],
        "failure_reasons": diagnostics["failure_reasons"],
        "capabilities": {
            "view_inventory": True,
            "view_dependencies": True,
            "view_lifecycle": True,
            "register_components": False,
            "activate_components": False,
            "mutate_dependencies": False,
        },
    }
