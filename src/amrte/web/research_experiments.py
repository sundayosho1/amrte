from __future__ import annotations

from typing import Any

from amrte.research.controlled_experimentation import (
    CONTROLLED_EXPERIMENT_RUNTIME_VERSION,
    controlled_experiment_components_from_inventory,
    research_configuration_promotion_decision_schema_identity,
    research_configuration_promotion_policy_identity,
    research_configuration_variant_schema_identity,
    research_dataset_partition_plan_schema_identity,
    research_experiment_policy_identity,
    research_experiment_result_schema_identity,
    research_experiment_specification_schema_identity,
    research_validation_metric_policy_identity,
    research_validation_stage_result_schema_identity,
    versioned_research_configuration_schema_identity,
)


def build_research_experiments_summary(runtime: Any, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    composition = getattr(runtime, "composition", None)
    diagnostics = composition.diagnostics() if composition is not None else None
    experiment = _experiment_runtime(composition)
    bounded_limit = max(1, min(int(limit), 100))
    items = experiment.query_experiments(offset=max(0, int(offset)), limit=bounded_limit) if experiment else ()
    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "schema_version": "1.0",
        "runtime_version": CONTROLLED_EXPERIMENT_RUNTIME_VERSION,
        "policies": {
            "experiment_policy": research_experiment_policy_identity(),
            "metric_policy": research_validation_metric_policy_identity(),
            "promotion_policy": research_configuration_promotion_policy_identity(),
        },
        "schemas": _schemas(),
        "authority": {
            "input_boundary": "P49 ImprovementCandidate",
            "automatic_change": False,
            "experiment_success_is_deployment_permission": False,
            "configuration_variant_is_active_configuration": False,
            "financial_authorization": "NONE",
        },
        "components": controlled_experiment_components_from_inventory(tuple(diagnostics["components"])) if diagnostics else {},
        "runtime_health": experiment.diagnostics() if experiment else None,
        "offset": max(0, int(offset)),
        "limit": bounded_limit,
        "experiment_count": len(experiment.specifications) if experiment else 0,
        "items": [_experiment_payload(item, experiment) for item in items],
        "financial_execution": "NONE",
    }


def build_research_experiment_detail(runtime: Any, experiment_id: str) -> dict[str, Any]:
    experiment = _experiment_runtime(getattr(runtime, "composition", None))
    if experiment is None:
        return {"mode": "READ_ONLY", "available": False, "reason": "P50_RUNTIME_UNAVAILABLE", "financial_execution": "NONE"}
    spec = experiment.specifications.get(experiment_id)
    if spec is None:
        return {"mode": "READ_ONLY", "available": False, "reason": "P50_EXPERIMENT_NOT_FOUND", "experiment_id": experiment_id, "financial_execution": "NONE"}
    payload = _experiment_payload(spec, experiment)
    payload.update(
        {
            "acceptance_criteria": list(spec.acceptance_criteria),
            "rejection_criteria": list(spec.rejection_criteria),
            "environment_identity": dict(spec.environment_identity),
            "stage_results": [_stage_payload(item) for item in experiment.stage_results.values() if item.experiment_id == spec.experiment_id],
            "result_ids": [item.result_id for item in experiment.results.values() if item.experiment_id == spec.experiment_id],
            "promotion_decision_ids": [item.promotion_decision_id for item in experiment.promotion_decisions.values() if item.experiment_id == spec.experiment_id],
        }
    )
    return {"mode": "READ_ONLY", "available": True, "experiment": payload, "financial_execution": "NONE"}


def build_research_configurations_summary(runtime: Any, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    experiment = _experiment_runtime(getattr(runtime, "composition", None))
    bounded_limit = max(1, min(int(limit), 100))
    items = experiment.query_configurations(offset=max(0, int(offset)), limit=bounded_limit) if experiment else ()
    return {
        "mode": "READ_ONLY",
        "research_only": True,
        "schema_version": "1.0",
        "configuration_count": len(experiment.configurations) if experiment else 0,
        "offset": max(0, int(offset)),
        "limit": bounded_limit,
        "items": [
            {
                "research_configuration_id": item.research_configuration_id,
                "configuration_version": item.configuration_version,
                "parent_configuration_id": item.parent_configuration_id,
                "experiment_id": item.experiment_id,
                "promotion_decision_id": item.promotion_decision_id,
                "status": item.status,
                "configuration_fingerprint": item.configuration_fingerprint,
                "approval_evidence_refs": list(item.approval_evidence_refs),
                "financial_execution": item.financial_execution,
            }
            for item in items
        ],
        "financial_execution": "NONE",
    }


def _experiment_runtime(composition: Any) -> Any | None:
    if composition is None:
        return None
    try:
        component = composition.get("research_experiment_runtime").component
    except Exception:
        return None
    return getattr(component, "runtime", None)


def _schemas() -> dict[str, str]:
    return {
        "experiment_specification": research_experiment_specification_schema_identity(),
        "configuration_variant": research_configuration_variant_schema_identity(),
        "dataset_partition_plan": research_dataset_partition_plan_schema_identity(),
        "validation_stage_result": research_validation_stage_result_schema_identity(),
        "experiment_result": research_experiment_result_schema_identity(),
        "promotion_decision": research_configuration_promotion_decision_schema_identity(),
        "versioned_research_configuration": versioned_research_configuration_schema_identity(),
    }


def _experiment_payload(spec: Any, experiment: Any) -> dict[str, Any]:
    result = next((item for item in reversed(tuple(experiment.results.values())) if item.experiment_id == spec.experiment_id), None)
    promotion = next((item for item in reversed(tuple(experiment.promotion_decisions.values())) if item.experiment_id == spec.experiment_id), None)
    return {
        "experiment_id": spec.experiment_id,
        "source_improvement_candidate_id": spec.source_improvement_candidate_id,
        "source_improvement_snapshot_id": spec.source_improvement_snapshot_id,
        "hypothesis": spec.hypothesis,
        "lifecycle_state": spec.lifecycle_state,
        "dataset_identity": spec.dataset_identity,
        "partition_plan_identity": spec.partition_plan_identity,
        "baseline_configuration_id": spec.baseline_configuration_id,
        "challenger_configuration_id": spec.challenger_configuration_id,
        "validation_stages": list(spec.acceptance_criteria),
        "acceptance_state": result.acceptance_state if result else "NO_RESULT",
        "promotion_state": promotion.decision if promotion else "NO_PROMOTION_DECISION",
        "reproducibility_identity": result.reproducibility_fingerprint if result else spec.experiment_fingerprint,
        "warnings": list(result.warnings) if result else [],
        "limitations": list(result.limitations) if result else ["RuntimeHealthy != ExperimentPassed"],
        "financial_execution": spec.financial_execution,
    }


def _stage_payload(item: Any) -> dict[str, Any]:
    return {
        "stage_result_id": item.stage_result_id,
        "stage_name": item.stage_name,
        "status": item.status,
        "partition_identity": item.partition_identity,
        "sample_count": item.sample_count,
        "missing_count": item.missing_count,
        "reason_codes": list(item.reason_codes),
        "warnings": list(item.warnings),
        "limitations": list(item.limitations),
        "robustness_classification": item.robustness_classification,
    }
