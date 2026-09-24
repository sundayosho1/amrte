from __future__ import annotations

from typing import Any

from amrte.portfolio.research_portfolio_runtime import portfolio_research_snapshot_schema_identity
from amrte.research.protection_runtime import (
    PROTECTION_EVIDENCE_SCHEMA_VERSION,
    RESEARCH_PROTECTION_RUNTIME_VERSION,
    RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
    protection_evidence_schema_identity,
    research_protection_components_from_inventory,
    research_protection_snapshot_schema_identity,
)


def _diagnostics(composition: Any) -> dict[str, Any] | None:
    if composition is None:
        return None
    try:
        component = composition.get("research_protection_snapshot").component
    except Exception:
        return None
    target = getattr(component, "diagnostics", None)
    return target() if target is not None else None


def build_research_protection_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        research_protection_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    runtime_diagnostics = _diagnostics(composition)
    return {
        "protection_snapshot_schema_version": RESEARCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
        "protection_snapshot_schema_identity": research_protection_snapshot_schema_identity(),
        "protection_evidence_schema_version": PROTECTION_EVIDENCE_SCHEMA_VERSION,
        "protection_evidence_schema_identity": protection_evidence_schema_identity(),
        "runtime_version": RESEARCH_PROTECTION_RUNTIME_VERSION,
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
            "protection_authority": "ResearchProtectionRuntime",
            "p44_snapshot_required": True,
            "p44_portfolio_snapshot_schema_identity": portfolio_research_snapshot_schema_identity(),
            "p44_recomputed": False,
            "p43_recomputed": False,
            "strategy_re_evaluation_available": False,
            "candidate_rescoring_available": False,
            "portfolio_risk_recompute_available": False,
            "manual_force_allow_available": False,
            "safety_bypass_available": False,
        },
        "current_state": runtime_diagnostics,
        "permission_model": {
            "states": ["ALLOWED", "RESTRICTED", "BLOCKED"],
            "monotonic": True,
            "blocked_dominates": True,
            "allowed_is_financial_authorization": False,
        },
        "protection_domains": {
            "observation_protection": True,
            "research_reliability": True,
            "strategy_health": True,
            "temporal_protection": True,
            "cooldowns": True,
            "degradation": True,
            "lifecycle": True,
            "dependency": True,
            "recovery": True,
            "system_safety": True,
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
