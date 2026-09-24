from __future__ import annotations

from typing import Any

from amrte.research.decision_runtime import (
    FINAL_RESEARCH_DECISION_SCHEMA_VERSION,
    MASTER_RESEARCH_DECISION_RUNTIME_VERSION,
    RESEARCH_DECISION_TRACE_SCHEMA_VERSION,
    RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION,
    final_research_decision_schema_identity,
    master_research_decision_components_from_inventory,
    research_decision_trace_schema_identity,
    research_processing_context_schema_identity,
    required_stage_schema_identities,
)
from amrte.research.protection_runtime import research_protection_snapshot_schema_identity


def _diagnostics(composition: Any) -> dict[str, Any] | None:
    if composition is None:
        return None
    try:
        component = composition.get("master_research_decision").component
    except Exception:
        return None
    target = getattr(component, "diagnostics", None)
    return target() if target is not None else None


def build_research_decisions_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        master_research_decision_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    runtime_diagnostics = _diagnostics(composition)
    return {
        "processing_context_schema_version": RESEARCH_PROCESSING_CONTEXT_SCHEMA_VERSION,
        "processing_context_schema_identity": research_processing_context_schema_identity(),
        "final_decision_schema_version": FINAL_RESEARCH_DECISION_SCHEMA_VERSION,
        "final_decision_schema_identity": final_research_decision_schema_identity(),
        "trace_schema_version": RESEARCH_DECISION_TRACE_SCHEMA_VERSION,
        "trace_schema_identity": research_decision_trace_schema_identity(),
        "runtime_version": MASTER_RESEARCH_DECISION_RUNTIME_VERSION,
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
            "final_research_decision_authority": "MasterResearchDecisionOrchestrator",
            "p45_snapshot_required": True,
            "p45_snapshot_schema_identity": research_protection_snapshot_schema_identity(),
            "required_stage_schema_identities": required_stage_schema_identities(),
            "p39_recomputed": False,
            "p40_recomputed": False,
            "p41_recomputed": False,
            "p42_recomputed": False,
            "p43_recomputed": False,
            "p44_recomputed": False,
            "p45_recomputed": False,
            "manual_force_allow_available": False,
            "restriction_bypass_available": False,
        },
        "current_state": runtime_diagnostics,
        "decision_model": {
            "states": ["NO_ACTION", "REJECTED", "RESTRICTED", "ELIGIBLE_RESEARCH", "FAILED"],
            "eligible_research_is_trade_authorization": False,
            "final_decision_is_financial_authorization": False,
            "missing_stage_evidence_fails_closed": True,
            "p45_blocked_can_become_positive": False,
            "p45_restricted_can_become_unrestricted": False,
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
