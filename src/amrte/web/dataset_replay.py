"""Read-only Dataset & Replay integrity projection for the AMRTE web console."""

from __future__ import annotations

from typing import Any

from amrte.core.constants import AMRTE_VERSION
from amrte.market.boundary import boundary_components_from_inventory

VERSION = AMRTE_VERSION


DATASET_SERVICE_NAMES = (
    "market_data",
    "market_data_provider",
    "dataset",
    "dataset_service",
)

EVENT_SERVICE_NAMES = (
    "events",
    "event_provider",
    "historical_events",
)

REPLAY_SERVICE_NAMES = (
    "replay",
    "replay_service",
    "backtest",
    "simulation",
)


IMPLEMENTED_CAPABILITIES = (
    {
        "capability": "CANONICAL_MARKET_OBSERVATION_CONTRACT",
        "component": "market_data_contract",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "SOURCE_ADAPTER_FRAMEWORK",
        "component": "market_data_source_adapter_framework",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "CANONICAL_DATASET_MANIFEST",
        "component": "market_dataset_authority",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "POINT_IN_TIME_MARKET_REPLAY",
        "component": "market_dataset_authority",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "DATASET_IDENTITY",
        "component": "DeterministicMarketDataProvider",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "DATASET_FINGERPRINT",
        "component": "DeterministicMarketDataProvider",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "AS_OF_MARKET_DATA",
        "component": "DeterministicMarketDataProvider",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "DATASET_VALIDATION_ADMISSION",
        "component": "MarketDataService",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "HISTORICAL_EVENT_AS_OF",
        "component": "DeterministicEventProvider",
        "implemented": True,
        "runtime_authoritative": False,
    },
    {
        "capability": "TEMPORAL_NO_LOOK_AHEAD",
        "component": "MasterConfiguration",
        "implemented": True,
        "runtime_authoritative": True,
    },
)


def _enum_name(value: Any) -> Any:
    if hasattr(value, "name"):
        return value.name
    return value


def _configuration_values(runtime: Any) -> dict[str, Any]:
    engine = runtime.engine

    if engine is None:
        return {}

    provider = engine.registry.require(
        "configuration"
    )

    loaded = provider.load()

    if not loaded.success:
        return {}

    snapshot = loaded.value

    return {
        key: _enum_name(value)
        for key, value in snapshot.values.items()
    }


def _registered_services(
    runtime: Any,
) -> dict[str, Any]:
    engine = runtime.engine

    if engine is None:
        return {}

    result = {}

    for name in engine.registry.names():
        service = engine.registry.require(name)

        result[name] = {
            "type": type(service).__name__,
            "module": type(service).__module__,
        }

    return result


def _composition_boundary_components(runtime: Any) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    if composition is None:
        return {}
    return boundary_components_from_inventory(composition.inventory())


def _first_registered(
    services: dict[str, Any],
    names: tuple[str, ...],
) -> str | None:
    for name in names:
        if name in services:
            return name

    return None


def build_dataset_replay_integrity(
    runtime: Any,
) -> dict[str, Any]:
    """Project existing runtime/configuration state without mutation."""

    values = _configuration_values(runtime)
    services = _registered_services(runtime)
    boundary_components = _composition_boundary_components(runtime)

    dataset_service = _first_registered(
        services,
        DATASET_SERVICE_NAMES,
    )

    event_service = _first_registered(
        services,
        EVENT_SERVICE_NAMES,
    )

    replay_service = _first_registered(
        services,
        REPLAY_SERVICE_NAMES,
    )

    checkpoint = runtime.last_checkpoint

    persistence_dataset_id = (
        checkpoint.dataset_id
        if checkpoint is not None
        else None
    )

    persistence_fingerprint = (
        checkpoint.dataset_fingerprint
        if checkpoint is not None
        else None
    )

    configured_dataset_id = values.get(
        "backtest.dataset_id"
    )

    market_provider_type = values.get(
        "market_data.provider_type"
    )

    event_provider_type = values.get(
        "events.provider_type"
    )

    no_look_ahead = values.get(
        "backtest.no_look_ahead"
    )

    runtime_mode = values.get(
        "runtime.mode"
    )

    execution = services.get(
        "execution",
        {},
    )

    execution_provider = execution.get(
        "type"
    )

    return {
        "version": VERSION,

        "mode": "READ_ONLY",

        "research_only": True,

        "runtime": {
            "state": runtime.state,
            "environment": (
                runtime.engine.environment.name
                if runtime.engine is not None
                else "UNKNOWN"
            ),
            "recovery_epoch": runtime.recovery_epoch,
        },

        "dataset_identity": {
            "configured_dataset_id":
                configured_dataset_id,

            "persistence_dataset_id":
                persistence_dataset_id,

            "persistence_dataset_fingerprint":
                persistence_fingerprint,

            "runtime_dataset_provider_registered":
                dataset_service is not None,

            "runtime_dataset_service":
                dataset_service,
        },

        "provider_policy": {
            "market_data_provider_type":
                market_provider_type,

            "event_provider_type":
                event_provider_type,

            "market_data_offline":
                market_provider_type
                == "DETERMINISTIC_OFFLINE",

            "events_offline":
                event_provider_type
                == "DETERMINISTIC_OFFLINE",

            "event_provider_registered":
                event_service is not None,

            "runtime_event_service":
                event_service,
        },

        "temporal_integrity": {
            "no_look_ahead":
                no_look_ahead is True,

            "configured_value":
                no_look_ahead,

            "as_of_market_data_supported":
                True,

            "as_of_historical_events_supported":
                True,
        },

        "replay_authority": {
            "authoritative_replay_service_registered":
                replay_service is not None
                or boundary_components.get("market_dataset_authority", {}).get("ready") is True,

            "runtime_replay_service":
                replay_service,

            "replay_control_available":
                False,

            "mutation_enabled":
                False,

            "reason": (
                "AUTHORITATIVE_REPLAY_SERVICE_NOT_REGISTERED"
                if replay_service is None
                and boundary_components.get("market_dataset_authority", {}).get("ready") is not True
                else "WEB_REPLAY_MUTATION_NOT_ENABLED"
            ),
        },

        "implemented_capabilities": [
            {
                **item,
                "runtime_authoritative": (
                    item["runtime_authoritative"]
                    or (
                        item["component"]
                        == "DeterministicMarketDataProvider"
                        and dataset_service is not None
                    )
                    or (
                        item["component"]
                        == "MarketDataService"
                        and dataset_service is not None
                    )
                    or (
                        item["component"]
                        == "DeterministicEventProvider"
                        and event_service is not None
                    )
                    or (
                        item["component"]
                        in boundary_components
                        and boundary_components[item["component"]]["ready"] is True
                    )
                ),
            }
            for item in IMPLEMENTED_CAPABILITIES
        ],

        "canonical_market_data_boundary": {
            "registered": bool(boundary_components),
            "components": boundary_components,
            "configured_dataset_loaded": (
                boundary_components.get("market_data_configured_dataset", {}).get("status")
                not in (None, "UNAVAILABLE")
            ),
        },

        "execution_boundary": {
            "capability": "PROHIBITED",

            "provider":
                execution_provider,

            "financial_execution_available":
                False,
        },

        "configuration": {
            "runtime_mode":
                runtime_mode,

            "configuration_snapshot_id": (
                checkpoint.configuration_snapshot_id
                if checkpoint is not None
                else None
            ),

            "configuration_hash": (
                checkpoint.configuration_hash
                if checkpoint is not None
                else None
            ),
        },

        "registered_services": services,
    }
