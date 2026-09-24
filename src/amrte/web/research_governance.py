from __future__ import annotations

from typing import Any


CAPABILITY_INVENTORY = (
    "system_safety",
    "research_lifecycle",
    "observation_quality",
    "research_reliability",
    "temporal_quality_protection",
)


def _capability(name: str) -> dict[str, Any]:
    return {
        "capability": name,
        "implemented": True,
        "runtime_authority": False,
        "runtime_active": False,
        "current_state_available": False,
        "status": "AVAILABLE_NOT_ACTIVATED",
    }


def build_research_governance_summary(runtime) -> dict[str, Any]:
    """
    Build a strictly read-only governance projection.

    This module deliberately does not instantiate or invoke the mutable
    governance engines. Implemented domain contracts are reported as
    definitions/capabilities only unless a canonical runtime authority
    exists elsewhere.
    """
    engine = runtime.engine

    if engine is None:
        raise RuntimeError("research runtime is not started")

    configuration = engine.configuration
    execution = engine.registry.require("execution")

    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "authority": {
            "projection_only": True,
            "new_runtime_authority": False,
            "target_engine_instantiation": False,
        },
        "runtime": {
            "state": runtime.state,
            "environment": engine.environment.name,
            "version": "0.27.0",
        },
        "governance_capabilities": [
            _capability(name)
            for name in CAPABILITY_INVENTORY
        ],
        "lifecycle_governance": {
            "implemented": True,
            "runtime_authority": False,
            "runtime_active": False,
            "current_state_available": False,
            "strict_state_machine": True,
            "fail_closed": True,
            "require_lineage": True,
            "require_dataset_match": True,
            "require_configuration_match": True,
            "require_temporal_integrity": True,
            "require_quality_for_authorization": True,
            "require_workflow_for_activation": True,
        },
        "system_safety": {
            "implemented": True,
            "runtime_authority": False,
            "runtime_active": False,
            "current_state_available": False,
            "fail_closed_recovery": True,
            "recovery_requires_evidence": True,
            "recovery_requires_actor": True,
            "recovery_requires_reason": True,
            "probation_required": True,
            "circuit_breaker_defined": True,
            "emergency_stop_defined": True,
        },
        "quality_protection": {
            "observation_quality": {
                "implemented": True,
                "runtime_authority": False,
                "runtime_active": False,
                "current_state_available": False,
                "non_amplifying": True,
            },
            "research_reliability": {
                "implemented": True,
                "runtime_authority": False,
                "runtime_active": False,
                "current_state_available": False,
                "non_amplifying": True,
            },
            "temporal_quality": {
                "implemented": True,
                "runtime_authority": False,
                "runtime_active": False,
                "current_state_available": False,
                "non_amplifying": True,
            },
        },
        "promotion_governance": {
            "implemented": True,
            "automatic_promotion": False,
            "manual_approval_required": True,
            "stage_skipping_allowed": False,
            "evidence_required": True,
            "final_stage": "RESEARCH_OPERATION_APPROVED",
        },
        "recovery_governance": {
            "fail_closed": True,
            "silent_repair": False,
            "state_manufacture": False,
            "automatic_recovery": False,
            "evidence_required": True,
        },
        "configuration_safeguards": {
            "fail_closed": bool(
                configuration.values["protection.fail_closed"]
            ),
            "deterministic_backtest": bool(
                configuration.values["backtest.deterministic"]
            ),
            "no_look_ahead": bool(
                configuration.values["backtest.no_look_ahead"]
            ),
            "strict_market_data_integrity": bool(
                configuration.values["market_data.strict_integrity"]
            ),
            "adaptive_risk_amplification_allowed": bool(
                configuration.values[
                    "risk.adaptive.allow_risk_amplification"
                ]
            ),
        },
        "execution_boundary": {
            "status": "PROHIBITED",
            "provider": type(execution).__name__,
            "financial_execution": False,
            "broker_connectivity": False,
            "account_connectivity": False,
        },
        "controls": {
            "view_governance_inventory": True,
            "view_safety_definitions": True,
            "view_promotion_governance": True,
            "view_recovery_governance": True,
            "initialize": False,
            "process": False,
            "transition": False,
            "evaluate": False,
            "promote": False,
            "request_recovery": False,
            "confirm_probation": False,
            "restore": False,
            "mutate": False,
        },
    }