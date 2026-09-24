from __future__ import annotations

from typing import Any

from amrte.research.data_quality_runtime import (
    DATA_QUALITY_RUNTIME_VERSION,
    QUALITY_TRUST_SCHEMA_VERSION,
    data_quality_components_from_inventory,
    quality_trust_schema_identity,
)


def _diagnostics(composition: Any) -> dict[str, Any] | None:
    if composition is None:
        return None
    try:
        component = composition.get("data_trust").component
    except Exception:
        return None
    target = getattr(component, "diagnostics", None)
    return target() if target is not None else None


def build_data_quality_runtime_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        data_quality_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    trust_diagnostics = _diagnostics(composition)
    return {
        "schema_version": QUALITY_TRUST_SCHEMA_VERSION,
        "schema_identity": quality_trust_schema_identity(),
        "runtime_version": DATA_QUALITY_RUNTIME_VERSION,
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
            "ingestion_authority": "DataQualityTrustRuntime",
            "single_ingestion_authority": True,
            "duplicate_runtime": False,
            "duplicate_clock": False,
            "duplicate_configuration": False,
            "duplicate_persistence": False,
        },
        "trust_model": {
            "states": [
                "TRUSTED",
                "TRUSTED_WITH_WARNINGS",
                "RESTRICTED",
                "QUARANTINED",
                "REJECTED",
                "UNAVAILABLE",
            ],
            "data_received_not_data_trusted": True,
            "missing_evidence_fails_closed": True,
            "future_evidence_rejected": True,
        },
        "current_state": trust_diagnostics,
        "recovery": {
            "checkpoint_participation": True,
            "recovery_participation": True,
            "recovery_restricted": (
                trust_diagnostics.get("recovery_restricted")
                if trust_diagnostics is not None
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
