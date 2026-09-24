from __future__ import annotations

from typing import Any

from amrte.strategies.research_scoring_runtime import (
    RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
    RESEARCH_SCORING_RUNTIME_VERSION,
    SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION,
    research_arbitration_assessment_schema_identity,
    research_scoring_components_from_inventory,
    scored_research_candidate_schema_identity,
)


def _diagnostics(composition: Any) -> dict[str, Any] | None:
    if composition is None:
        return None
    try:
        component = composition.get("central_scoring").component
    except Exception:
        return None
    target = getattr(component, "diagnostics", None)
    return target() if target is not None else None


def build_research_scoring_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        research_scoring_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    scoring_diagnostics = _diagnostics(composition)
    return {
        "scored_candidate_schema_version": SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION,
        "scored_candidate_schema_identity": scored_research_candidate_schema_identity(),
        "assessment_schema_version": RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
        "assessment_schema_identity": research_arbitration_assessment_schema_identity(),
        "runtime_version": RESEARCH_SCORING_RUNTIME_VERSION,
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
            "scoring_authority": "ResearchScoringRuntime",
            "p42_input_required": True,
            "strategy_re_evaluation_available": False,
            "raw_observation_bypass_available": False,
            "trusted_observation_bypass_available": False,
            "market_intelligence_bypass_available": False,
            "duplicate_scorer": False,
            "duplicate_arbitration_engine": False,
            "duplicate_configuration": False,
            "duplicate_clock": False,
            "duplicate_persistence": False,
        },
        "current_state": scoring_diagnostics,
        "downstream_boundaries": {
            "risk_decision_active": False,
            "portfolio_decision_active": False,
            "final_decision_active": False,
            "financial_execution_active": False,
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
