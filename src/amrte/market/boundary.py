from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.types import HealthStatus

from .observation import (
    CSVBarSourceAdapter,
    DATASET_MANIFEST_SCHEMA_VERSION,
    MARKET_DATA_BOUNDARY_VERSION,
    MARKET_OBSERVATION_SCHEMA_VERSION,
    schema_identity,
)


BOUNDARY_COMPONENT_IDS = (
    "market_data_contract",
    "market_data_source_adapter_framework",
    "market_dataset_authority",
    "market_data_configured_dataset",
)


@dataclass(frozen=True)
class MarketDataBoundaryComponent:
    component_id: str
    role: str
    dataset_loaded: bool = False

    def initialize_component(self, context: Any) -> None:
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record(
                "market_data_boundary_initialized",
                {
                    "component_id": self.component_id,
                    "role": self.role,
                    "boundary_version": MARKET_DATA_BOUNDARY_VERSION,
                    "observation_schema_version": MARKET_OBSERVATION_SCHEMA_VERSION,
                    "dataset_manifest_schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
                },
            )

    def component_ready(self, context: Any) -> bool:
        return True

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.HEALTHY

    def diagnostics(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "role": self.role,
            "boundary_version": MARKET_DATA_BOUNDARY_VERSION,
            "observation_schema_version": MARKET_OBSERVATION_SCHEMA_VERSION,
            "dataset_manifest_schema_version": DATASET_MANIFEST_SCHEMA_VERSION,
            "observation_schema_identity": schema_identity("observation"),
            "dataset_manifest_schema_identity": schema_identity("dataset_manifest"),
            "supported_observation_types": ["BAR"],
            "temporal_semantics": "BAR_CLOSE",
            "supported_adapters": [
                {
                    "adapter_type": CSVBarSourceAdapter.adapter_type,
                    "adapter_version": CSVBarSourceAdapter.adapter_version,
                    "required_columns": list(CSVBarSourceAdapter.required_columns),
                }
            ],
            "dataset_loaded": self.dataset_loaded,
            "mutation_enabled": False,
            "financial_execution_available": False,
        }


def market_data_component_registrations() -> tuple[tuple[ComponentMetadata, MarketDataBoundaryComponent | None], ...]:
    capabilities = ComponentCapabilities(
        lifecycle=True,
        persistence=False,
        recovery=False,
        health=True,
        diagnostics=True,
        activation=True,
    )
    diagnostic_only = ComponentCapabilities(
        lifecycle=False,
        persistence=False,
        recovery=False,
        health=True,
        diagnostics=True,
        activation=False,
    )
    return (
        (
            ComponentMetadata(
                component_id="market_data_contract",
                component_type=ComponentType.RESEARCH,
                component_version=MARKET_DATA_BOUNDARY_VERSION,
                required=True,
                dependencies=("configuration", "clock", "audit", "observability"),
                capabilities=capabilities,
            ),
            MarketDataBoundaryComponent("market_data_contract", "canonical observation contract"),
        ),
        (
            ComponentMetadata(
                component_id="market_data_source_adapter_framework",
                component_type=ComponentType.RESEARCH,
                component_version=MARKET_DATA_BOUNDARY_VERSION,
                required=True,
                dependencies=("market_data_contract",),
                capabilities=capabilities,
            ),
            MarketDataBoundaryComponent("market_data_source_adapter_framework", "source adapter framework"),
        ),
        (
            ComponentMetadata(
                component_id="market_dataset_authority",
                component_type=ComponentType.RESEARCH,
                component_version=MARKET_DATA_BOUNDARY_VERSION,
                required=True,
                dependencies=("market_data_contract", "market_data_source_adapter_framework"),
                capabilities=capabilities,
            ),
            MarketDataBoundaryComponent("market_dataset_authority", "canonical dataset authority"),
        ),
        (
            ComponentMetadata(
                component_id="market_data_configured_dataset",
                component_type=ComponentType.RESEARCH,
                component_version=MARKET_DATA_BOUNDARY_VERSION,
                required=False,
                dependencies=("market_dataset_authority",),
                capabilities=diagnostic_only,
                available=False,
            ),
            None,
        ),
    )


def boundary_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    return {
        item["component_id"]: item
        for item in inventory
        if item.get("component_id") in BOUNDARY_COMPONENT_IDS
    }
