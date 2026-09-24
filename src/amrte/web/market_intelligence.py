from __future__ import annotations

from typing import Any, Mapping

from amrte.market.intelligence_runtime import (
    MARKET_INTELLIGENCE_RUNTIME_VERSION,
    UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
    market_intelligence_components_from_inventory,
    market_intelligence_schema_identity,
)


def _diagnostics(composition: Any) -> dict[str, Any] | None:
    if composition is None:
        return None
    try:
        component = composition.get("market_intelligence").component
    except Exception:
        return None
    target = getattr(component, "diagnostics", None)
    return target() if target is not None else None


def build_market_intelligence_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        market_intelligence_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    intelligence_diagnostics = _diagnostics(composition)
    return {
        "schema_version": UNIFIED_INTELLIGENCE_SCHEMA_VERSION,
        "schema_identity": market_intelligence_schema_identity(),
        "runtime_version": MARKET_INTELLIGENCE_RUNTIME_VERSION,
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
            "intelligence_authority": "MarketIntelligenceRuntime",
            "trusted_observation_input_required": True,
            "raw_observation_bypass_available": False,
            "duplicate_runtime": False,
            "duplicate_clock": False,
            "duplicate_configuration": False,
            "duplicate_persistence": False,
        },
        "trusted_boundary": {
            "accepted_trust_states": ["TRUSTED", "TRUSTED_WITH_WARNINGS"],
            "blocked_trust_states": ["RESTRICTED", "QUARANTINED", "REJECTED", "UNAVAILABLE"],
            "observation_identity_match_required": True,
            "observation_fingerprint_match_required": True,
            "missing_evidence_fails_closed": True,
            "future_observations_rejected": True,
        },
        "current_state": intelligence_diagnostics,
        "recovery": {
            "checkpoint_participation": True,
            "recovery_participation": True,
            "recovery_restricted": (
                intelligence_diagnostics.get("recovery_restricted")
                if isinstance(intelligence_diagnostics, Mapping)
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
