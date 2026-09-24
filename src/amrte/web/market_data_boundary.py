from __future__ import annotations

from typing import Any

from amrte.market.boundary import (
    BOUNDARY_COMPONENT_IDS,
    boundary_components_from_inventory,
)
from amrte.market.observation import (
    CSVBarSourceAdapter,
    DATASET_MANIFEST_SCHEMA_VERSION,
    MARKET_DATA_BOUNDARY_VERSION,
    MARKET_OBSERVATION_SCHEMA_VERSION,
    schema_identity,
)


def _record_diagnostics(composition: Any, component_id: str) -> dict[str, Any] | None:
    try:
        component = composition.get(component_id).component
    except Exception:
        return None
    diagnostics = getattr(component, "diagnostics", None)
    if diagnostics is None:
        return None
    return diagnostics()


def build_market_data_boundary_summary(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    components = (
        boundary_components_from_inventory(tuple(diagnostics["components"]))
        if diagnostics is not None
        else {}
    )
    contract = _record_diagnostics(composition, "market_data_contract") if composition is not None else None
    adapter = _record_diagnostics(composition, "market_data_source_adapter_framework") if composition is not None else None
    authority = _record_diagnostics(composition, "market_dataset_authority") if composition is not None else None
    configured_dataset = components.get("market_data_configured_dataset")

    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "boundary_version": MARKET_DATA_BOUNDARY_VERSION,
        "observation_schema": {
            "version": MARKET_OBSERVATION_SCHEMA_VERSION,
            "identity": schema_identity("observation"),
            "supported_types": ["BAR"],
            "temporal_semantics": "BAR_CLOSE",
            "finalized_closed_bars_only": True,
        },
        "dataset_manifest_schema": {
            "version": DATASET_MANIFEST_SCHEMA_VERSION,
            "identity": schema_identity("dataset_manifest"),
        },
        "composition": {
            "available": composition is not None,
            "component_ids": list(BOUNDARY_COMPONENT_IDS),
            "components": components,
            "research_pipeline": (
                diagnostics["research_pipeline"]
                if diagnostics is not None
                else {"registered": False, "active": False, "status": "NOT_REGISTERED"}
            ),
        },
        "contract": contract,
        "source_adapter_framework": {
            "status": components.get("market_data_source_adapter_framework", {}).get("status", "UNAVAILABLE"),
            "ready": components.get("market_data_source_adapter_framework", {}).get("ready", False),
            "diagnostics": adapter,
            "supported_adapters": [
                {
                    "adapter_type": CSVBarSourceAdapter.adapter_type,
                    "adapter_version": CSVBarSourceAdapter.adapter_version,
                    "required_columns": list(CSVBarSourceAdapter.required_columns),
                    "deterministic": True,
                }
            ],
        },
        "dataset_authority": {
            "status": components.get("market_dataset_authority", {}).get("status", "UNAVAILABLE"),
            "ready": components.get("market_dataset_authority", {}).get("ready", False),
            "diagnostics": authority,
            "configured_dataset_loaded": False,
            "configured_dataset_status": (
                configured_dataset.get("status")
                if configured_dataset is not None
                else "UNREGISTERED"
            ),
            "admission_policy": "STRICT_BY_DEFAULT_WITH_DIAGNOSTIC_MODE",
            "manifest_verification_available": True,
            "point_in_time_replay_available": True,
        },
        "validation": {
            "timestamp_order": "period_start < event_time <= available_at <= received_at",
            "look_ahead_guard": "available_at must be <= logical_time before use",
            "ohlc_guard": "high >= max(open, close), low <= min(open, close), high >= low",
            "duplicate_policy": "exact duplicates warn and deduplicate; revised identity conflicts are invalid",
            "sequence_policy": "regression invalid; gaps warn",
        },
        "replay": {
            "point_in_time_method": "CanonicalDatasetReplay.available_as_of",
            "uses_available_at": True,
            "mutation_enabled": False,
        },
        "execution_boundary": {
            "execution": "PROHIBITED",
            "financial_execution_available": False,
        },
    }
