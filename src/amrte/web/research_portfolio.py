from __future__ import annotations

from typing import Any

from amrte.portfolio.research_portfolio_runtime import (
    CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION,
    CORRELATION_RESEARCH_SCHEMA_VERSION,
    PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
    RESEARCH_PORTFOLIO_RUNTIME_VERSION,
    candidate_research_risk_schema_identity,
    correlation_research_schema_identity,
    portfolio_research_snapshot_schema_identity,
    research_portfolio_components_from_inventory,
)
from amrte.strategies.research_scoring_runtime import (
    research_arbitration_assessment_schema_identity,
    scored_research_candidate_schema_identity,
)


def _diagnostics(composition: Any) -> dict[str, Any] | None:
    if composition is None:
        return None
    try:
        component = composition.get("portfolio_research_snapshot").component
    except Exception:
        return None
    target = getattr(component, "diagnostics", None)
    return target() if target is not None else None


def build_research_portfolio_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        research_portfolio_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    runtime_diagnostics = _diagnostics(composition)
    return {
        "candidate_risk_schema_version": CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION,
        "candidate_risk_schema_identity": candidate_research_risk_schema_identity(),
        "correlation_schema_version": CORRELATION_RESEARCH_SCHEMA_VERSION,
        "correlation_schema_identity": correlation_research_schema_identity(),
        "portfolio_snapshot_schema_version": PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
        "portfolio_snapshot_schema_identity": portfolio_research_snapshot_schema_identity(),
        "runtime_version": RESEARCH_PORTFOLIO_RUNTIME_VERSION,
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
            "risk_portfolio_authority": "ResearchPortfolioRuntime",
            "p43_assessment_required": True,
            "p43_scored_candidate_schema_identity": scored_research_candidate_schema_identity(),
            "p43_assessment_schema_identity": research_arbitration_assessment_schema_identity(),
            "strategy_re_evaluation_available": False,
            "candidate_rescoring_available": False,
            "arbitration_recompute_available": False,
            "raw_observation_bypass_available": False,
            "market_data_acquisition_available": False,
            "duplicate_portfolio_engine": False,
            "duplicate_correlation_engine": False,
            "duplicate_configuration": False,
            "duplicate_clock": False,
            "duplicate_persistence": False,
        },
        "current_state": runtime_diagnostics,
        "downstream_boundaries": {
            "final_decision_active": False,
            "financial_execution_active": False,
            "capital_allocation_active": False,
            "position_sizing_active": False,
        },
        "semantic_boundaries": {
            "research_risk_acceptable_is_authorization": False,
            "portfolio_compatible_is_capital_allocation": False,
            "research_weight_is_position_size": False,
            "portfolio_capacity_is_broker_buying_power": False,
        },
        "execution_boundary": {
            "broker_connectivity": "NONE",
            "trading_account_connectivity": "NONE",
            "financial_credential_collection": "NONE",
            "order_submission": "NONE",
            "position_management": "NONE",
            "capital_allocation": "NONE",
            "leverage_margin_interaction": "NONE",
            "live_trading": "NONE",
            "demo_trading": "NONE",
            "financial_execution": "NONE",
        },
    }
