from __future__ import annotations

from typing import Any, Mapping

from amrte.strategies.evaluation_runtime import (
    RESEARCH_CANDIDATE_SCHEMA_VERSION,
    STRATEGY_EVALUATION_RUNTIME_VERSION,
    STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
    research_candidate_schema_identity,
    strategy_evaluation_components_from_inventory,
    strategy_evaluation_set_schema_identity,
)


def _diagnostics(composition: Any) -> dict[str, Any] | None:
    if composition is None:
        return None
    try:
        component = composition.get("strategy_evaluation").component
    except Exception:
        return None
    target = getattr(component, "diagnostics", None)
    return target() if target is not None else None


def build_strategy_evaluation_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        strategy_evaluation_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    strategy_diagnostics = _diagnostics(composition)
    return {
        "candidate_schema_version": RESEARCH_CANDIDATE_SCHEMA_VERSION,
        "candidate_schema_identity": research_candidate_schema_identity(),
        "evaluation_schema_version": STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
        "evaluation_schema_identity": strategy_evaluation_set_schema_identity(),
        "runtime_version": STRATEGY_EVALUATION_RUNTIME_VERSION,
        "mode": "READ_ONLY",
        "research_only": True,
        "composition": {
            "available": composition is not None,
            "components": components,
            "research_pipeline": (
                diagnostics["research_pipeline"]
                if diagnostics is not None
                else {"registered": False, "active": False, "status": "NOT_REGISTERED"}
            ),
        },
        "runtime_authority": {
            "strategy_authority": "StrategyEvaluationRuntime",
            "p41_input_required": True,
            "raw_observation_bypass_available": False,
            "trusted_observation_bypass_available": False,
            "duplicate_runtime": False,
            "duplicate_configuration": False,
            "duplicate_clock": False,
            "duplicate_persistence": False,
        },
        "current_state": strategy_diagnostics,
        "downstream_boundaries": {
            "central_scoring_active": False,
            "strategy_arbitration_active": False,
            "final_decision_active": False,
            "risk_decision_active": False,
            "portfolio_decision_active": False,
        },
        "recovery": {
            "checkpoint_participation": True,
            "recovery_participation": True,
            "recovery_restricted": (
                strategy_diagnostics.get("recovery_restricted")
                if isinstance(strategy_diagnostics, Mapping)
                else None
            ),
        },
        "execution_boundary": {
            "broker_connectivity": "NONE",
            "trading_account_connectivity": "NONE",
            "financial_credential_collection": "NONE",
            "order_submission": "NONE",
            "position_management": "NONE",
            "leverage_margin_interaction": "NONE",
            "live_trading": "NONE",
            "demo_trading": "NONE",
            "financial_execution": "NONE",
        },
    }
