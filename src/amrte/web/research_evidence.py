from __future__ import annotations

from typing import Any

from amrte.operations.runtime import VERSION
from amrte.research.evidence_ledger import (
    RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION,
    research_decision_evidence_components_from_inventory,
    research_decision_evidence_record_schema_identity,
)


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
    composition = getattr(runtime, "composition", None)
    composition_diagnostics = composition.diagnostics() if composition is not None else None
    ledger_diagnostics = _ledger_diagnostics(composition)
    ledger_components = (
        research_decision_evidence_components_from_inventory(
            tuple(composition_diagnostics["components"])
        )
        if composition_diagnostics is not None
        else {}
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
        "ledger": {
            "runtime_version": RESEARCH_DECISION_EVIDENCE_LEDGER_VERSION,
            "record_schema_identity": research_decision_evidence_record_schema_identity(),
            "status": ledger_diagnostics,
            "components": ledger_components,
            "checkpoint_is_ledger": False,
            "historical_evidence_mutation_available": False,
            "append_only": True,
            "financial_execution": "NONE",
        },
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


def build_research_evidence_record_detail(
    runtime: Any,
    record_id: str,
) -> dict[str, Any]:
    ledger = _ledger_runtime(getattr(runtime, "composition", None))
    if ledger is None:
        return {
            "mode": "READ_ONLY",
            "available": False,
            "record_id": record_id,
            "reason": "P47_LEDGER_UNAVAILABLE",
        }
    try:
        bundle = ledger.reconstruct_by_record_id(record_id)
    except KeyError:
        return {
            "mode": "READ_ONLY",
            "available": False,
            "record_id": record_id,
            "reason": "P47_EVIDENCE_RECORD_NOT_FOUND",
        }
    record = bundle.record
    return {
        "mode": "READ_ONLY",
        "available": True,
        "record": {
            "evidence_record_id": record.evidence_record_id,
            "ledger_sequence": record.ledger_sequence,
            "record_type": record.record_type,
            "decision_id": record.decision_id,
            "trace_id": record.trace_id,
            "processing_context_id": record.processing_context_id,
            "dataset_id": record.dataset_id,
            "dataset_fingerprint": record.dataset_fingerprint,
            "observation_id": record.observation_id,
            "knowledge_cutoff_utc": record.knowledge_cutoff_utc.isoformat(),
            "configuration_identity": record.configuration_identity,
            "pipeline_identity": record.pipeline_identity,
            "recovery_epoch": record.recovery_epoch,
            "classification": record.final_classification,
            "reason_codes": list(record.reason_codes),
            "restriction_references": list(record.restriction_references),
            "stage_evidence_ids": [
                item.get("evidence_id") for item in record.stage_evidence
            ],
            "previous_record_hash": record.previous_record_hash,
            "record_hash": record.record_hash,
            "evidence_fingerprint": record.evidence_fingerprint,
            "verification_state": bundle.integrity.status.value,
            "verification_reasons": list(bundle.integrity.reason_codes),
            "financial_execution": "NONE",
        },
        "reconstruction": {
            "recomputed_decision": bundle.reconstruction_recomputed_decision,
            "decision": dict(bundle.decision),
            "trace": dict(bundle.trace),
            "processing_context": dict(bundle.processing_context),
            "stage_evidence": [dict(item) for item in bundle.stage_evidence],
            "release_provenance": dict(bundle.release_provenance),
        },
    }


def _ledger_runtime(composition: Any) -> Any | None:
    if composition is None:
        return None
    try:
        component = composition.get("research_evidence_ledger").component
    except Exception:
        return None
    return getattr(component, "runtime", None)


def _ledger_diagnostics(composition: Any) -> dict[str, Any] | None:
    ledger = _ledger_runtime(composition)
    if ledger is None:
        return None
    return ledger.diagnostics()
