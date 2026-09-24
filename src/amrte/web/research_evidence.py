from __future__ import annotations

from typing import Any

from amrte.operations.runtime import VERSION


CAPABILITY_INVENTORY = (
    (
        "research_performance_analytics",
        "ResearchPerformanceAnalyticsEngine",
        "src/amrte/analytics/performance.py",
    ),
    (
        "deterministic_experiments",
        "DeterministicExperimentEngine",
        "src/amrte/validation/experiments.py",
    ),
    (
        "robustness_validation",
        "DeterministicRobustnessEngine",
        "src/amrte/validation/robustness.py",
    ),
    (
        "research_lifecycle",
        "ResearchLifecycleEngine",
        "src/amrte/research/lifecycle.py",
    ),
    (
        "observation_quality",
        "ObservationQualityEngine",
        "src/amrte/research/observation_quality.py",
    ),
    (
        "research_reliability",
        "ResearchReliabilityEngine",
        "src/amrte/research/reliability.py",
    ),
    (
        "temporal_quality_protection",
        "TemporalQualityProtectionEngine",
        "src/amrte/research/temporal_quality.py",
    ),
    (
        "system_safety",
        "SystemSafetyEngine",
        "src/amrte/research/system_safety.py",
    ),
)


def build_research_evidence_summary(
    runtime: Any,
) -> dict[str, Any]:
    """Build a read-only capability projection.

    This function must not instantiate, initialize, execute,
    restore, reconcile, or otherwise mutate any research engine.
    """

    engine = runtime.engine

    if engine is None:
        raise RuntimeError(
            "Persistent research runtime is not active."
        )

    configuration = engine.configuration

    execution = engine.registry.require(
        "execution"
    )

    research_capabilities = [
        {
            "capability": capability,
            "engine_type": engine_type,
            "module": module,
            "implemented": True,
            "runtime_authority": False,
            "runtime_active": False,
            "evidence_available": False,
            "status": "AVAILABLE_NOT_ACTIVATED",
        }
        for (
            capability,
            engine_type,
            module,
        ) in CAPABILITY_INVENTORY
    ]

    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "authority": {
            "projection_only": True,
            "new_runtime_authority": False,
            "target_engine_instantiation": False,
        },
        "runtime": {
            "state": runtime.state,
            "environment": engine.environment.name,
            "version": VERSION,
        },
        "configuration": {
            "snapshot_id": (
                configuration.snapshot_id
            ),
            "configuration_hash": (
                configuration.configuration_hash
            ),
        },
        "research_capabilities": (
            research_capabilities
        ),
        "capabilities": {
            "view_capability_inventory": True,
            "view_readiness": True,
            "run_analytics": False,
            "run_experiments": False,
            "run_robustness": False,
            "mutate_lifecycle": False,
            "evaluate_observations": False,
            "process_reliability": False,
            "process_temporal_quality": False,
            "process_system_safety": False,
            "restore_research_state": False,
        },
        "execution_boundary": {
            "status": "PROHIBITED",
            "provider": (
                type(execution).__name__
            ),
            "financial_execution": False,
            "broker_connectivity": False,
            "account_connectivity": False,
        },
    }
