from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.config_engine import ConfigurationValidator
from amrte.core.config_schema import HARD_SAFETY_VALUES, SCHEMA
from amrte.core.constants import AMRTE_VERSION
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.research.improvement_intelligence import (
    ImprovementCandidate,
    improvement_candidate_schema_identity,
    research_improvement_policy_identity,
    research_improvement_snapshot_schema_identity,
)


CONTROLLED_EXPERIMENT_RUNTIME_VERSION = "1.0"
RESEARCH_EXPERIMENT_SPECIFICATION_SCHEMA_VERSION = "1.0"
RESEARCH_CONFIGURATION_VARIANT_SCHEMA_VERSION = "1.0"
RESEARCH_DATASET_PARTITION_PLAN_SCHEMA_VERSION = "1.0"
RESEARCH_VALIDATION_STAGE_RESULT_SCHEMA_VERSION = "1.0"
RESEARCH_EXPERIMENT_RESULT_SCHEMA_VERSION = "1.0"
RESEARCH_CONFIGURATION_COMPARISON_SCHEMA_VERSION = "1.0"
RESEARCH_CONFIGURATION_PROMOTION_DECISION_SCHEMA_VERSION = "1.0"
VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION = "1.0"
RESEARCH_CONFIGURATION_ROLLBACK_SCHEMA_VERSION = "1.0"
RESEARCH_EXPERIMENT_LEDGER_SCHEMA_VERSION = "1.0"
RESEARCH_EXPERIMENT_POLICY_VERSION = "1.0"
RESEARCH_VALIDATION_METRIC_POLICY_VERSION = "1.0"
RESEARCH_CONFIGURATION_PROMOTION_POLICY_VERSION = "1.0"


class ExperimentLifecycleState(Enum):
    PROPOSED = "PROPOSED"
    VALIDATED_SPEC = "VALIDATED_SPEC"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


class ValidationStageName(Enum):
    SPECIFICATION = "SPECIFICATION"
    HISTORICAL = "HISTORICAL"
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    WALK_FORWARD = "WALK_FORWARD"
    ROBUSTNESS = "ROBUSTNESS"
    SENSITIVITY = "SENSITIVITY"
    COMPARISON = "COMPARISON"
    PROMOTION_ASSESSMENT = "PROMOTION_ASSESSMENT"


class StageStatus(Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"


class ExperimentAcceptanceState(Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALID = "INVALID"


class PromotionDecisionValue(Enum):
    REJECT = "REJECT"
    DEFER = "DEFER"
    REQUIRE_MORE_EVIDENCE = "REQUIRE_MORE_EVIDENCE"
    APPROVE_RESEARCH_CONFIGURATION = "APPROVE_RESEARCH_CONFIGURATION"


class ConfigurationStatus(Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    APPROVED_RESEARCH = "APPROVED_RESEARCH"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    ROLLED_BACK = "ROLLED_BACK"


class MetricDirection(Enum):
    HIGHER_IS_BETTER = "HIGHER_IS_BETTER"
    LOWER_IS_BETTER = "LOWER_IS_BETTER"
    TARGET_RANGE = "TARGET_RANGE"
    DIAGNOSTIC_ONLY = "DIAGNOSTIC_ONLY"


class RobustnessClassification(Enum):
    ROBUST = "ROBUST"
    CONDITIONALLY_ROBUST = "CONDITIONALLY_ROBUST"
    FRAGILE = "FRAGILE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class ExperimentSearchBudget:
    maximum_variants: int
    maximum_comparisons: int
    maximum_parameter_combinations: int
    maximum_dataset_passes: int
    maximum_walk_forward_folds: int
    budget_identity: str

    @classmethod
    def current(cls) -> "ExperimentSearchBudget":
        payload = {
            "maximum_variants": 8,
            "maximum_comparisons": 16,
            "maximum_parameter_combinations": 32,
            "maximum_dataset_passes": 24,
            "maximum_walk_forward_folds": 8,
        }
        return cls(
            int(payload["maximum_variants"]),
            int(payload["maximum_comparisons"]),
            int(payload["maximum_parameter_combinations"]),
            int(payload["maximum_dataset_passes"]),
            int(payload["maximum_walk_forward_folds"]),
            _sha256_json(payload),
        )


@dataclass(frozen=True)
class ResearchExperimentPolicy:
    policy_id: str
    version: str
    minimum_stage_sample: int
    minimum_oos_sample: int
    minimum_walk_forward_folds: int
    maximum_sensitivity_range: Decimal
    maximum_generalization_gap: Decimal
    safety_regression_tolerance: Decimal
    holdout_reuse_limit: int
    mandatory_stages: tuple[str, ...]
    search_budget: ExperimentSearchBudget
    policy_identity: str

    @classmethod
    def current(cls) -> "ResearchExperimentPolicy":
        budget = ExperimentSearchBudget.current()
        payload = {
            "policy_id": "P50_CONTROLLED_RESEARCH_EXPERIMENT_POLICY",
            "version": RESEARCH_EXPERIMENT_POLICY_VERSION,
            "minimum_stage_sample": 3,
            "minimum_oos_sample": 3,
            "minimum_walk_forward_folds": 2,
            "maximum_sensitivity_range": "0.25000000",
            "maximum_generalization_gap": "0.50000000",
            "safety_regression_tolerance": "0.00000000",
            "holdout_reuse_limit": 1,
            "mandatory_stages": (
                ValidationStageName.SPECIFICATION.value,
                ValidationStageName.HISTORICAL.value,
                ValidationStageName.OUT_OF_SAMPLE.value,
                ValidationStageName.WALK_FORWARD.value,
                ValidationStageName.ROBUSTNESS.value,
                ValidationStageName.SENSITIVITY.value,
                ValidationStageName.COMPARISON.value,
                ValidationStageName.PROMOTION_ASSESSMENT.value,
            ),
            "search_budget": budget.budget_identity,
        }
        return cls(
            str(payload["policy_id"]),
            str(payload["version"]),
            int(payload["minimum_stage_sample"]),
            int(payload["minimum_oos_sample"]),
            int(payload["minimum_walk_forward_folds"]),
            Decimal(str(payload["maximum_sensitivity_range"])),
            Decimal(str(payload["maximum_generalization_gap"])),
            Decimal(str(payload["safety_regression_tolerance"])),
            int(payload["holdout_reuse_limit"]),
            tuple(str(item) for item in payload["mandatory_stages"]),
            budget,
            _sha256_json(payload),
        )


@dataclass(frozen=True)
class ResearchValidationMetricPolicy:
    policy_id: str
    version: str
    primary_metrics: Mapping[str, str]
    secondary_metrics: Mapping[str, str]
    safety_metrics: Mapping[str, str]
    metric_policy_identity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "primary_metrics", MappingProxyType(dict(self.primary_metrics)))
        object.__setattr__(self, "secondary_metrics", MappingProxyType(dict(self.secondary_metrics)))
        object.__setattr__(self, "safety_metrics", MappingProxyType(dict(self.safety_metrics)))

    @classmethod
    def current(cls) -> "ResearchValidationMetricPolicy":
        payload = {
            "policy_id": "P50_RESEARCH_VALIDATION_METRIC_POLICY",
            "version": RESEARCH_VALIDATION_METRIC_POLICY_VERSION,
            "primary_metrics": {"research_score_delta": MetricDirection.HIGHER_IS_BETTER.value},
            "secondary_metrics": {
                "stage_mean": MetricDirection.HIGHER_IS_BETTER.value,
                "generalization_gap": MetricDirection.LOWER_IS_BETTER.value,
                "fold_stability": MetricDirection.HIGHER_IS_BETTER.value,
            },
            "safety_metrics": {
                "temporal_integrity": MetricDirection.TARGET_RANGE.value,
                "data_integrity": MetricDirection.TARGET_RANGE.value,
                "protection_preservation": MetricDirection.TARGET_RANGE.value,
                "determinism": MetricDirection.TARGET_RANGE.value,
                "recovery_equivalence": MetricDirection.TARGET_RANGE.value,
            },
        }
        return cls(
            str(payload["policy_id"]),
            str(payload["version"]),
            dict(payload["primary_metrics"]),
            dict(payload["secondary_metrics"]),
            dict(payload["safety_metrics"]),
            _sha256_json(payload),
        )


@dataclass(frozen=True)
class ResearchConfigurationPromotionPolicy:
    policy_id: str
    version: str
    mandatory_gates: tuple[str, ...]
    regression_budget: Mapping[str, str]
    promotion_policy_identity: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "regression_budget", MappingProxyType(dict(self.regression_budget)))

    @classmethod
    def current(cls) -> "ResearchConfigurationPromotionPolicy":
        payload = {
            "policy_id": "P50_RESEARCH_CONFIGURATION_PROMOTION_POLICY",
            "version": RESEARCH_CONFIGURATION_PROMOTION_POLICY_VERSION,
            "mandatory_gates": (
                "SOURCE_CANDIDATE_VALID",
                "SPECIFICATION_VALID",
                "DATASET_VALID",
                "TEMPORAL_INTEGRITY_VALID",
                "OOS_EVIDENCE_SUFFICIENT",
                "WALK_FORWARD_VALID",
                "ROBUSTNESS_ACCEPTABLE",
                "SENSITIVITY_ACCEPTABLE",
                "CRITICAL_REGRESSIONS_ABSENT",
                "DETERMINISM_VALID",
                "RECOVERY_VALID",
                "PROTECTION_NOT_WEAKENED",
                "EVIDENCE_COMPLETE",
            ),
            "regression_budget": {
                "safety_regression": "0.00000000",
                "temporal_violation": "0",
                "holdout_contamination": "0",
            },
        }
        return cls(
            str(payload["policy_id"]),
            str(payload["version"]),
            tuple(str(item) for item in payload["mandatory_gates"]),
            dict(payload["regression_budget"]),
            _sha256_json(payload),
        )


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: str
    sequence: int
    development_start: datetime
    development_end: datetime
    validation_start: datetime
    validation_end: datetime
    fold_fingerprint: str


@dataclass(frozen=True)
class ResearchDatasetPartitionPlan:
    partition_plan_id: str
    schema_version: str
    schema_identity: str
    dataset_id: str
    dataset_fingerprint: str
    source_identity: str
    instrument: str
    timeframe: str
    coverage_start: datetime
    coverage_end: datetime
    development_start: datetime
    development_end: datetime
    validation_start: datetime
    validation_end: datetime
    out_of_sample_start: datetime
    out_of_sample_end: datetime
    holdout_start: datetime | None
    holdout_end: datetime | None
    walk_forward_folds: tuple[WalkForwardFold, ...]
    partition_policy_identity: str
    partition_fingerprint: str


@dataclass(frozen=True)
class ResearchConfigurationVariant:
    variant_id: str
    schema_version: str
    schema_identity: str
    baseline_configuration_id: str
    challenger_configuration_id: str
    scope: str
    configuration_delta: Mapping[str, Any]
    resolved_configuration: Mapping[str, Any]
    baseline_configuration_fingerprint: str
    resolved_configuration_fingerprint: str
    source_improvement_candidate_id: str
    rationale: str
    search_space: Mapping[str, Any]
    search_budget_identity: str
    created_at_logical: datetime
    variant_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "configuration_delta", MappingProxyType(dict(self.configuration_delta)))
        object.__setattr__(self, "resolved_configuration", MappingProxyType(dict(self.resolved_configuration)))
        object.__setattr__(self, "search_space", MappingProxyType(dict(self.search_space)))


@dataclass(frozen=True)
class ResearchExperimentSpecification:
    experiment_id: str
    schema_version: str
    schema_identity: str
    source_improvement_candidate_id: str
    source_improvement_snapshot_id: str
    hypothesis: str
    target_component: str
    target_component_version: str
    baseline_configuration_id: str
    challenger_configuration_id: str
    configuration_variant_id: str
    dataset_identity: str
    partition_plan_identity: str
    experiment_policy_identity: str
    metric_policy_identity: str
    promotion_policy_identity: str
    primary_research_metrics: tuple[str, ...]
    secondary_research_metrics: tuple[str, ...]
    safety_metrics: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    rejection_criteria: tuple[str, ...]
    knowledge_cutoff: datetime
    created_at_logical: datetime
    software_release_identity: str
    environment_identity: Mapping[str, str]
    lifecycle_state: str
    experiment_fingerprint: str
    financial_execution: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment_identity", MappingProxyType(dict(self.environment_identity)))


@dataclass(frozen=True)
class ResearchValidationStageResult:
    stage_result_id: str
    schema_version: str
    schema_identity: str
    experiment_id: str
    stage_name: str
    stage_sequence: int
    status: str
    partition_identity: str
    sample_count: int
    missing_count: int
    metric_results: Mapping[str, Decimal | None]
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    robustness_classification: str | None
    started_at_logical: datetime
    completed_at_logical: datetime
    stage_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "metric_results", MappingProxyType(dict(self.metric_results)))


@dataclass(frozen=True)
class ResearchExperimentResult:
    result_id: str
    schema_version: str
    schema_identity: str
    experiment_id: str
    baseline_configuration_id: str
    challenger_configuration_id: str
    dataset_identity: str
    partition_plan_identity: str
    historical_result_id: str | None
    out_of_sample_result_id: str | None
    walk_forward_result_id: str | None
    robustness_result_id: str | None
    sensitivity_result_id: str | None
    primary_metric_results: Mapping[str, Decimal | None]
    secondary_metric_results: Mapping[str, Decimal | None]
    safety_metric_results: Mapping[str, Decimal | None]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    acceptance_state: str
    rejection_reasons: tuple[str, ...]
    completed_stage_ids: tuple[str, ...]
    search_space_attempted: Mapping[str, Any]
    variants_attempted: tuple[str, ...]
    metrics_examined: tuple[str, ...]
    cohorts_examined: tuple[str, ...]
    reproducibility_fingerprint: str
    result_fingerprint: str
    financial_execution: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "primary_metric_results", MappingProxyType(dict(self.primary_metric_results)))
        object.__setattr__(self, "secondary_metric_results", MappingProxyType(dict(self.secondary_metric_results)))
        object.__setattr__(self, "safety_metric_results", MappingProxyType(dict(self.safety_metric_results)))
        object.__setattr__(self, "search_space_attempted", MappingProxyType(dict(self.search_space_attempted)))


@dataclass(frozen=True)
class ResearchConfigurationComparison:
    comparison_id: str
    schema_version: str
    schema_identity: str
    experiment_id: str
    result_id: str
    baseline_configuration_id: str
    challenger_configuration_id: str
    comparable: bool
    comparison_dimensions: Mapping[str, str]
    primary_metric_delta: Decimal | None
    safety_regressions: tuple[str, ...]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    comparison_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "comparison_dimensions", MappingProxyType(dict(self.comparison_dimensions)))


@dataclass(frozen=True)
class ResearchConfigurationPromotionDecision:
    promotion_decision_id: str
    schema_version: str
    schema_identity: str
    experiment_id: str
    result_id: str
    comparison_id: str
    baseline_configuration_id: str
    challenger_configuration_id: str
    decision: str
    gate_results: Mapping[str, str]
    acceptance_reasons: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    promotion_policy_identity: str
    approved_research_configuration_id: str | None
    decision_fingerprint: str
    financial_execution: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "gate_results", MappingProxyType(dict(self.gate_results)))


@dataclass(frozen=True)
class VersionedResearchConfiguration:
    research_configuration_id: str
    schema_version: str
    schema_identity: str
    configuration_version: str
    parent_configuration_id: str
    experiment_id: str
    promotion_decision_id: str
    source_improvement_candidate_id: str
    resolved_configuration: Mapping[str, Any]
    configuration_delta: Mapping[str, Any]
    configuration_fingerprint: str
    created_at_logical: datetime
    approval_evidence_refs: tuple[str, ...]
    status: str
    configuration_lineage: tuple[str, ...]
    configuration_fingerprint_authority: str
    financial_execution: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_configuration", MappingProxyType(dict(self.resolved_configuration)))
        object.__setattr__(self, "configuration_delta", MappingProxyType(dict(self.configuration_delta)))


@dataclass(frozen=True)
class ResearchConfigurationRollback:
    rollback_id: str
    schema_version: str
    schema_identity: str
    from_configuration: str
    to_configuration: str
    reason: str
    evidence_refs: tuple[str, ...]
    policy_identity: str
    logical_timestamp: datetime
    rollback_fingerprint: str


@dataclass(frozen=True)
class ResearchExperimentLedgerRecord:
    ledger_record_id: str
    schema_version: str
    schema_identity: str
    event_type: str
    subject_id: str
    previous_record_id: str | None
    payload_fingerprint: str
    created_at_logical: datetime
    record_fingerprint: str


@dataclass(frozen=True)
class HoldoutExposure:
    holdout_identity: str
    exposure_count: int
    experiment_ids: tuple[str, ...]
    first_exposure: datetime
    latest_exposure: datetime
    pristine: bool


@dataclass(frozen=True)
class ControlledExperimentRecoveryState:
    schema_version: str
    runtime_version: str
    experiment_policy_identity: str
    metric_policy_identity: str
    promotion_policy_identity: str
    configuration_identity: str
    recovery_epoch: int
    variants: tuple[ResearchConfigurationVariant, ...]
    partition_plans: tuple[ResearchDatasetPartitionPlan, ...]
    specifications: tuple[ResearchExperimentSpecification, ...]
    stage_results: tuple[ResearchValidationStageResult, ...]
    results: tuple[ResearchExperimentResult, ...]
    comparisons: tuple[ResearchConfigurationComparison, ...]
    promotion_decisions: tuple[ResearchConfigurationPromotionDecision, ...]
    configurations: tuple[VersionedResearchConfiguration, ...]
    rollbacks: tuple[ResearchConfigurationRollback, ...]
    ledger: tuple[ResearchExperimentLedgerRecord, ...]
    holdout_exposures: tuple[HoldoutExposure, ...]


class ControlledResearchExperimentRuntime:
    """Governed research change-control runtime.

    P50 creates research artifacts only. It cannot deploy, trade, authorize
    orders, mutate strategy source, or replace active financial systems.
    """

    supported_scopes = {
        "strategy",
        "feature",
        "threshold",
        "filter",
        "scoring",
        "arbitration",
        "risk research policy",
        "portfolio research policy",
        "protection research policy",
        "data-quality research policy",
    }

    def __init__(
        self,
        *,
        clock: Any,
        audit: Any,
        experiment_policy: ResearchExperimentPolicy | None = None,
        metric_policy: ResearchValidationMetricPolicy | None = None,
        promotion_policy: ResearchConfigurationPromotionPolicy | None = None,
        configuration_identity: str = "P50_CONTROLLED_EXPERIMENT_DEFAULT",
        storage_root: Path = Path("data/research-controlled-experiments"),
        maximum_experiments: int = 4096,
        maximum_configurations: int = 1024,
        maximum_query_limit: int = 100,
    ) -> None:
        self.clock = clock
        self.audit = audit
        self.experiment_policy = experiment_policy or ResearchExperimentPolicy.current()
        self.metric_policy = metric_policy or ResearchValidationMetricPolicy.current()
        self.promotion_policy = promotion_policy or ResearchConfigurationPromotionPolicy.current()
        self.configuration_identity = configuration_identity
        self.storage_root = Path(storage_root)
        self.maximum_experiments = max(1, maximum_experiments)
        self.maximum_configurations = max(1, maximum_configurations)
        self.maximum_query_limit = max(1, min(maximum_query_limit, 500))
        self.variants: OrderedDict[str, ResearchConfigurationVariant] = OrderedDict()
        self.partition_plans: OrderedDict[str, ResearchDatasetPartitionPlan] = OrderedDict()
        self.specifications: OrderedDict[str, ResearchExperimentSpecification] = OrderedDict()
        self.stage_results: OrderedDict[str, ResearchValidationStageResult] = OrderedDict()
        self.results: OrderedDict[str, ResearchExperimentResult] = OrderedDict()
        self.comparisons: OrderedDict[str, ResearchConfigurationComparison] = OrderedDict()
        self.promotion_decisions: OrderedDict[str, ResearchConfigurationPromotionDecision] = OrderedDict()
        self.configurations: OrderedDict[str, VersionedResearchConfiguration] = OrderedDict()
        self.rollbacks: OrderedDict[str, ResearchConfigurationRollback] = OrderedDict()
        self.ledger: OrderedDict[str, ResearchExperimentLedgerRecord] = OrderedDict()
        self.holdout_exposures: OrderedDict[str, HoldoutExposure] = OrderedDict()
        self.recovery_restricted = False
        self.metrics = {
            "experiments_registered": 0,
            "experiments_completed": 0,
            "experiments_rejected": 0,
            "experiments_inconclusive": 0,
            "variants_tested": 0,
            "historical_validations": 0,
            "oos_validations": 0,
            "walk_forward_folds": 0,
            "robustness_evaluations": 0,
            "sensitivity_evaluations": 0,
            "promotion_approvals": 0,
            "promotion_rejections": 0,
            "promotion_deferrals": 0,
            "approved_research_configurations": 0,
            "rollbacks": 0,
            "recovery_count": 0,
            "recovery_failures": 0,
            "reproducibility_failures": 0,
            "temporal_violations": 0,
            "holdout_contamination_events": 0,
        }
        self.initialize_component(None)

    def initialize_component(self, context: Any) -> None:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._record("controlled_experiment_runtime_initialized", {"policy_identity": self.experiment_policy.policy_identity})

    def validate_improvement_candidate(self, candidate: ImprovementCandidate, *, as_of: datetime | None = None) -> tuple[str, ...]:
        now = as_of or self.clock.now()
        reasons: list[str] = []
        if candidate.schema_version != "1.0" or candidate.schema_identity != improvement_candidate_schema_identity():
            reasons.append("P50_P49_CANDIDATE_SCHEMA_MISMATCH")
        if not candidate.candidate_fingerprint:
            reasons.append("P50_P49_CANDIDATE_FINGERPRINT_MISSING")
        if candidate.automatic_change:
            reasons.append("P50_P49_AUTOMATIC_CHANGE_FORBIDDEN")
        if not candidate.validation_required:
            reasons.append("P50_P49_VALIDATION_REQUIRED_MISSING")
        if not candidate.source_snapshot_ids:
            reasons.append("P50_P49_P48_LINEAGE_MISSING")
        if not candidate.source_p47_evidence_ids:
            reasons.append("P50_P49_P47_LINEAGE_MISSING")
        if candidate.analysis_policy_identity != research_improvement_policy_identity():
            reasons.append("P50_P49_POLICY_MISMATCH")
        if not candidate.configuration_identity:
            reasons.append("P50_P49_CONFIGURATION_IDENTITY_MISSING")
        if candidate.as_of > now or candidate.knowledge_cutoff > now:
            reasons.append("P50_P49_TEMPORAL_INTEGRITY_VIOLATION")
        return tuple(dict.fromkeys(reasons))

    def create_configuration_variant(
        self,
        candidate: ImprovementCandidate,
        *,
        baseline_configuration_id: str,
        challenger_configuration_id: str,
        scope: str,
        configuration_delta: Mapping[str, Any],
        baseline_configuration: Mapping[str, Any],
        rationale: str | None = None,
        search_space: Mapping[str, Iterable[Any]] | None = None,
        as_of: datetime | None = None,
    ) -> ResearchConfigurationVariant:
        now = as_of or self.clock.now()
        candidate_reasons = self.validate_improvement_candidate(candidate, as_of=now)
        if candidate_reasons:
            raise ValueError(";".join(candidate_reasons))
        reasons = self._validate_delta(scope, configuration_delta, search_space or {})
        if reasons:
            raise ValueError(";".join(reasons))
        resolved = dict(baseline_configuration)
        resolved.update(dict(configuration_delta))
        baseline_fingerprint = _sha256_json({"configuration": baseline_configuration_id, "values": baseline_configuration})
        resolved_fingerprint = _sha256_json({"configuration": challenger_configuration_id, "values": resolved})
        payload = {
            "candidate": candidate.candidate_id,
            "baseline": baseline_configuration_id,
            "challenger": challenger_configuration_id,
            "scope": scope,
            "delta": dict(configuration_delta),
            "resolved": resolved_fingerprint,
            "search_space": _jsonable(search_space or {}),
            "budget": self.experiment_policy.search_budget.budget_identity,
            "created_at": now,
        }
        fingerprint = _sha256_json(payload)
        variant = ResearchConfigurationVariant(
            deterministic_id("p50_research_configuration_variant", fingerprint),
            RESEARCH_CONFIGURATION_VARIANT_SCHEMA_VERSION,
            research_configuration_variant_schema_identity(),
            baseline_configuration_id,
            challenger_configuration_id,
            scope,
            dict(configuration_delta),
            resolved,
            baseline_fingerprint,
            resolved_fingerprint,
            candidate.candidate_id,
            rationale or str(candidate.proposed_hypothesis.get("research_question", candidate.finding_summary)),
            {key: tuple(value) for key, value in (search_space or {}).items()},
            self.experiment_policy.search_budget.budget_identity,
            now,
            fingerprint,
        )
        self.variants[variant.variant_id] = variant
        self._trim(self.variants, self.maximum_configurations)
        self.metrics["variants_tested"] += 1
        self._ledger("configuration_variant_created", variant.variant_id, fingerprint, now)
        return variant

    def create_partition_plan(
        self,
        *,
        dataset_id: str,
        dataset_fingerprint: str,
        source_identity: str,
        instrument: str,
        timeframe: str,
        coverage_start: datetime,
        coverage_end: datetime,
        as_of: datetime | None = None,
    ) -> ResearchDatasetPartitionPlan:
        if coverage_start >= coverage_end:
            raise ValueError("P50_PARTITION_COVERAGE_INVALID")
        span = coverage_end - coverage_start
        step = span / 5
        development_start = coverage_start
        development_end = coverage_start + step * 2
        validation_start = development_end
        validation_end = validation_start + step
        out_of_sample_start = validation_end
        out_of_sample_end = out_of_sample_start + step
        holdout_start = out_of_sample_end
        holdout_end = coverage_end
        folds = []
        fold_width = step / 2
        for sequence in (1, 2):
            dev_start = coverage_start + fold_width * (sequence - 1)
            dev_end = dev_start + step
            val_start = dev_end
            val_end = val_start + fold_width
            fingerprint = _sha256_json(
                {
                    "dataset": dataset_fingerprint,
                    "sequence": sequence,
                    "dev_start": dev_start,
                    "dev_end": dev_end,
                    "val_start": val_start,
                    "val_end": val_end,
                }
            )
            folds.append(WalkForwardFold(deterministic_id("p50_walk_forward_fold", fingerprint), sequence, dev_start, dev_end, val_start, val_end, fingerprint))
        payload = {
            "dataset_id": dataset_id,
            "dataset_fingerprint": dataset_fingerprint,
            "source": source_identity,
            "instrument": instrument,
            "timeframe": timeframe,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "folds": tuple(item.fold_fingerprint for item in folds),
            "policy": self.experiment_policy.policy_identity,
        }
        fingerprint = _sha256_json(payload)
        plan = ResearchDatasetPartitionPlan(
            deterministic_id("p50_partition_plan", fingerprint),
            RESEARCH_DATASET_PARTITION_PLAN_SCHEMA_VERSION,
            research_dataset_partition_plan_schema_identity(),
            dataset_id,
            dataset_fingerprint,
            source_identity,
            instrument,
            timeframe,
            coverage_start,
            coverage_end,
            development_start,
            development_end,
            validation_start,
            validation_end,
            out_of_sample_start,
            out_of_sample_end,
            holdout_start,
            holdout_end,
            tuple(folds),
            self.experiment_policy.policy_identity,
            fingerprint,
        )
        reasons = self._validate_partition(plan)
        if reasons:
            raise ValueError(";".join(reasons))
        self.partition_plans[plan.partition_plan_id] = plan
        self._ledger("dataset_partition_created", plan.partition_plan_id, fingerprint, as_of or self.clock.now())
        return plan

    def register_experiment(
        self,
        candidate: ImprovementCandidate,
        *,
        source_improvement_snapshot_id: str,
        variant: ResearchConfigurationVariant,
        partition_plan: ResearchDatasetPartitionPlan,
        software_release_identity: str,
        as_of: datetime | None = None,
    ) -> ResearchExperimentSpecification:
        now = as_of or self.clock.now()
        candidate_reasons = self.validate_improvement_candidate(candidate, as_of=now)
        if candidate_reasons:
            raise ValueError(";".join(candidate_reasons))
        if source_improvement_snapshot_id not in candidate.source_snapshot_ids:
            raise ValueError("P50_ORPHAN_EXPERIMENT_FORBIDDEN")
        if variant.source_improvement_candidate_id != candidate.candidate_id:
            raise ValueError("P50_VARIANT_CANDIDATE_MISMATCH")
        partition_reasons = self._validate_partition(partition_plan)
        if partition_reasons:
            raise ValueError(";".join(partition_reasons))
        environment = {
            "python_version": platform.python_version(),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "application_version": AMRTE_VERSION,
        }
        payload = {
            "candidate": candidate.candidate_id,
            "snapshot": source_improvement_snapshot_id,
            "hypothesis": dict(candidate.proposed_hypothesis),
            "target": variant.scope,
            "baseline": variant.baseline_configuration_id,
            "challenger": variant.challenger_configuration_id,
            "variant": variant.variant_id,
            "dataset": partition_plan.dataset_fingerprint,
            "partition": partition_plan.partition_fingerprint,
            "experiment_policy": self.experiment_policy.policy_identity,
            "metric_policy": self.metric_policy.metric_policy_identity,
            "promotion_policy": self.promotion_policy.promotion_policy_identity,
            "software": software_release_identity,
        }
        fingerprint = _sha256_json(payload)
        existing = next((item for item in self.specifications.values() if item.experiment_fingerprint == fingerprint), None)
        if existing:
            return existing
        spec = ResearchExperimentSpecification(
            deterministic_id("p50_research_experiment", fingerprint),
            RESEARCH_EXPERIMENT_SPECIFICATION_SCHEMA_VERSION,
            research_experiment_specification_schema_identity(),
            candidate.candidate_id,
            source_improvement_snapshot_id,
            str(candidate.proposed_hypothesis.get("research_question", candidate.finding_summary)),
            str(candidate.proposed_hypothesis.get("target_component", variant.scope)),
            str(candidate.proposed_hypothesis.get("target_version", "EVIDENCE_DEFINED")),
            variant.baseline_configuration_id,
            variant.challenger_configuration_id,
            variant.variant_id,
            partition_plan.dataset_fingerprint,
            partition_plan.partition_plan_id,
            self.experiment_policy.policy_identity,
            self.metric_policy.metric_policy_identity,
            self.promotion_policy.promotion_policy_identity,
            tuple(self.metric_policy.primary_metrics),
            tuple(self.metric_policy.secondary_metrics),
            tuple(self.metric_policy.safety_metrics),
            ("all_mandatory_stages_pass", "critical_regressions_absent", "reproducibility_valid"),
            ("temporal_violation", "holdout_contaminated", "critical_regression", "oos_failed", "sensitivity_too_high"),
            candidate.knowledge_cutoff,
            now,
            software_release_identity,
            environment,
            ExperimentLifecycleState.VALIDATED_SPEC.value,
            fingerprint,
        )
        self.specifications[spec.experiment_id] = spec
        self._trim(self.specifications, self.maximum_experiments)
        self.metrics["experiments_registered"] += 1
        self._ledger("experiment_registered", spec.experiment_id, fingerprint, now)
        self._record("experiment_registered", {"experiment_id": spec.experiment_id})
        return spec

    def record_holdout_exposure(self, partition_plan_id: str, experiment_id: str, as_of: datetime | None = None) -> HoldoutExposure:
        now = as_of or self.clock.now()
        plan = self.partition_plans[partition_plan_id]
        if plan.holdout_start is None or plan.holdout_end is None:
            raise ValueError("P50_HOLDOUT_UNAVAILABLE")
        identity = deterministic_id("p50_holdout", partition_plan_id, plan.holdout_start.isoformat(), plan.holdout_end.isoformat(), plan.dataset_fingerprint)
        previous = self.holdout_exposures.get(identity)
        if previous is None:
            exposure = HoldoutExposure(identity, 1, (experiment_id,), now, now, True)
        else:
            experiments = tuple(dict.fromkeys((*previous.experiment_ids, experiment_id)))
            exposure = HoldoutExposure(identity, previous.exposure_count + 1, experiments, previous.first_exposure, now, previous.exposure_count + 1 <= self.experiment_policy.holdout_reuse_limit)
        if not exposure.pristine:
            self.metrics["holdout_contamination_events"] += 1
        self.holdout_exposures[identity] = exposure
        self._ledger("holdout_exposed", identity, _sha256_json(exposure), now)
        return exposure

    def run_validation(
        self,
        experiment_id: str,
        evidence: Mapping[str, Iterable[Decimal | int | float]],
        *,
        safety_evidence: Mapping[str, Decimal | int | float] | None = None,
        as_of: datetime | None = None,
    ) -> ResearchExperimentResult:
        now = as_of or self.clock.now()
        spec = self.specifications[experiment_id]
        variant = self.variants[spec.configuration_variant_id]
        plan = self.partition_plans[spec.partition_plan_identity]
        stage_order = (
            ValidationStageName.SPECIFICATION,
            ValidationStageName.HISTORICAL,
            ValidationStageName.OUT_OF_SAMPLE,
            ValidationStageName.WALK_FORWARD,
            ValidationStageName.ROBUSTNESS,
            ValidationStageName.SENSITIVITY,
        )
        stage_results = []
        hard_reasons: list[str] = []
        warnings: list[str] = []
        for sequence, stage in enumerate(stage_order, start=1):
            result = self._stage_result(spec, plan, stage, sequence, tuple(Decimal(str(item)) for item in evidence.get(stage.value, ())), now)
            self.stage_results[result.stage_result_id] = result
            stage_results.append(result)
            if result.status in {StageStatus.FAILED.value, StageStatus.INVALID.value}:
                hard_reasons.extend(result.reason_codes)
            elif result.status in {StageStatus.INCONCLUSIVE.value, StageStatus.UNAVAILABLE.value}:
                warnings.extend(result.reason_codes)
        completed_ids = tuple(item.stage_result_id for item in stage_results)
        primary = {"research_score_delta": _mean_tuple(tuple(value for item in stage_results for value in item.metric_results.values() if value is not None))}
        secondary = {
            "stage_mean": primary["research_score_delta"],
            "generalization_gap": self._generalization_gap(stage_results),
            "fold_stability": self._fold_stability(stage_results),
        }
        safety = self._safety_results(safety_evidence or {})
        if any(value is not None and value < self.experiment_policy.safety_regression_tolerance for value in safety.values()):
            hard_reasons.append("CRITICAL_REGRESSION")
        if any(item.status == StageStatus.INCONCLUSIVE.value for item in stage_results):
            acceptance = ExperimentAcceptanceState.INCONCLUSIVE
        elif hard_reasons:
            acceptance = ExperimentAcceptanceState.REJECTED
        else:
            acceptance = ExperimentAcceptanceState.ACCEPTED
        reproducibility = deterministic_id("p50_experiment_replay", spec.experiment_id, *completed_ids, _sha256_json(primary), _sha256_json(secondary), _sha256_json(safety))
        payload = {
            "experiment": spec.experiment_id,
            "stages": completed_ids,
            "primary": primary,
            "secondary": secondary,
            "safety": safety,
            "acceptance": acceptance.value,
            "reasons": tuple(sorted(set(hard_reasons))),
            "replay": reproducibility,
        }
        fingerprint = _sha256_json(payload)
        result = ResearchExperimentResult(
            deterministic_id("p50_research_experiment_result", fingerprint),
            RESEARCH_EXPERIMENT_RESULT_SCHEMA_VERSION,
            research_experiment_result_schema_identity(),
            spec.experiment_id,
            spec.baseline_configuration_id,
            spec.challenger_configuration_id,
            spec.dataset_identity,
            spec.partition_plan_identity,
            self._stage_id(stage_results, ValidationStageName.HISTORICAL),
            self._stage_id(stage_results, ValidationStageName.OUT_OF_SAMPLE),
            self._stage_id(stage_results, ValidationStageName.WALK_FORWARD),
            self._stage_id(stage_results, ValidationStageName.ROBUSTNESS),
            self._stage_id(stage_results, ValidationStageName.SENSITIVITY),
            primary,
            secondary,
            safety,
            tuple(sorted(set(warnings))),
            (
                "HistoricalOutperformance != ValidatedGeneralization",
                "ExperimentSuccess != PermissionToDeploy",
                "ValidatedResearchConfiguration != GuaranteedFuturePerformance",
            ),
            acceptance.value,
            tuple(sorted(set(hard_reasons))),
            completed_ids,
            variant.search_space,
            (variant.variant_id,),
            tuple((*self.metric_policy.primary_metrics, *self.metric_policy.secondary_metrics, *self.metric_policy.safety_metrics)),
            ("global", variant.scope, plan.instrument, plan.timeframe),
            reproducibility,
            fingerprint,
        )
        self.results[result.result_id] = result
        self.metrics["experiments_completed"] += 1
        if acceptance is ExperimentAcceptanceState.REJECTED:
            self.metrics["experiments_rejected"] += 1
        if acceptance is ExperimentAcceptanceState.INCONCLUSIVE:
            self.metrics["experiments_inconclusive"] += 1
        self.metrics["historical_validations"] += 1
        self.metrics["oos_validations"] += 1
        self.metrics["walk_forward_folds"] += len(plan.walk_forward_folds)
        self.metrics["robustness_evaluations"] += 1
        self.metrics["sensitivity_evaluations"] += 1
        self._ledger("experiment_result_recorded", result.result_id, fingerprint, now)
        return result

    def compare_champion_challenger(self, result_id: str, *, as_of: datetime | None = None) -> ResearchConfigurationComparison:
        result = self.results[result_id]
        spec = self.specifications[result.experiment_id]
        stage_ids = set(result.completed_stage_ids)
        comparable = all(stage_ids) and result.dataset_identity == spec.dataset_identity and result.partition_plan_identity == spec.partition_plan_identity
        safety_regressions = tuple(key for key, value in result.safety_metric_results.items() if value is not None and value < self.experiment_policy.safety_regression_tolerance)
        reason_codes = []
        if not comparable:
            reason_codes.append("INCOMPARABLE")
        if safety_regressions:
            reason_codes.append("CRITICAL_REGRESSION")
        if result.acceptance_state == ExperimentAcceptanceState.ACCEPTED.value and comparable and not safety_regressions:
            reason_codes.append("VALIDATION_PASSED")
        payload = {
            "result": result_id,
            "comparable": comparable,
            "primary": result.primary_metric_results.get("research_score_delta"),
            "safety": safety_regressions,
            "reasons": reason_codes,
        }
        fingerprint = _sha256_json(payload)
        comparison = ResearchConfigurationComparison(
            deterministic_id("p50_configuration_comparison", fingerprint),
            RESEARCH_CONFIGURATION_COMPARISON_SCHEMA_VERSION,
            research_configuration_comparison_schema_identity(),
            result.experiment_id,
            result.result_id,
            result.baseline_configuration_id,
            result.challenger_configuration_id,
            comparable,
            {
                "dataset": "IDENTICAL",
                "partition": "IDENTICAL",
                "knowledge_cutoff": "IDENTICAL",
                "policy": "IDENTICAL",
                "software_environment": "RECORDED",
            },
            result.primary_metric_results.get("research_score_delta"),
            safety_regressions,
            ("Champion != FinanciallyDeployedSystem", "Challenger != FinanciallyAuthorizedSystem"),
            tuple(reason_codes),
            fingerprint,
        )
        self.comparisons[comparison.comparison_id] = comparison
        self._ledger("challenger_compared", comparison.comparison_id, fingerprint, as_of or self.clock.now())
        return comparison

    def assess_promotion(self, result_id: str, comparison_id: str | None = None, *, as_of: datetime | None = None) -> ResearchConfigurationPromotionDecision:
        now = as_of or self.clock.now()
        result = self.results[result_id]
        comparison = self.comparisons.get(comparison_id) if comparison_id else self.compare_champion_challenger(result_id, as_of=now)
        gate_results = self._gate_results(result, comparison)
        failed = tuple(key for key, value in gate_results.items() if value != "PASSED")
        approved_config_id = None
        warnings = ["ResearchPromotion != FinancialAuthorization", "SuccessfulExperiment != AutomaticPromotion"]
        if not comparison.comparable:
            decision = PromotionDecisionValue.DEFER
            rejection = ("INCOMPARABLE",)
        elif result.acceptance_state == ExperimentAcceptanceState.INCONCLUSIVE.value:
            decision = PromotionDecisionValue.REQUIRE_MORE_EVIDENCE
            rejection = ("MORE_EVIDENCE_REQUIRED",)
        elif failed:
            decision = PromotionDecisionValue.REJECT
            rejection = tuple(failed)
        else:
            decision = PromotionDecisionValue.APPROVE_RESEARCH_CONFIGURATION
            rejection = ()
        payload = {
            "result": result_id,
            "comparison": comparison.comparison_id,
            "decision": decision.value,
            "gates": gate_results,
            "policy": self.promotion_policy.promotion_policy_identity,
        }
        fingerprint = _sha256_json(payload)
        decision_id = deterministic_id("p50_promotion_decision", fingerprint)
        if decision is PromotionDecisionValue.APPROVE_RESEARCH_CONFIGURATION:
            approved_config_id = deterministic_id("p50_approved_research_configuration", decision_id, result.challenger_configuration_id)
        promotion = ResearchConfigurationPromotionDecision(
            decision_id,
            RESEARCH_CONFIGURATION_PROMOTION_DECISION_SCHEMA_VERSION,
            research_configuration_promotion_decision_schema_identity(),
            result.experiment_id,
            result.result_id,
            comparison.comparison_id,
            result.baseline_configuration_id,
            result.challenger_configuration_id,
            decision.value,
            gate_results,
            ("VALIDATION_PASSED",) if decision is PromotionDecisionValue.APPROVE_RESEARCH_CONFIGURATION else (),
            rejection,
            tuple(warnings),
            ("ApprovedResearchConfiguration != LiveTradingConfiguration", "No future performance guarantee."),
            self.promotion_policy.promotion_policy_identity,
            approved_config_id,
            fingerprint,
        )
        self.promotion_decisions[promotion.promotion_decision_id] = promotion
        if decision is PromotionDecisionValue.APPROVE_RESEARCH_CONFIGURATION:
            self.metrics["promotion_approvals"] += 1
            self.create_versioned_configuration(promotion.promotion_decision_id, as_of=now)
        elif decision is PromotionDecisionValue.DEFER:
            self.metrics["promotion_deferrals"] += 1
        else:
            self.metrics["promotion_rejections"] += 1
        self._ledger(f"promotion_{decision.value.lower()}", promotion.promotion_decision_id, fingerprint, now)
        return promotion

    def create_versioned_configuration(self, promotion_decision_id: str, *, as_of: datetime | None = None) -> VersionedResearchConfiguration:
        now = as_of or self.clock.now()
        promotion = self.promotion_decisions[promotion_decision_id]
        if promotion.decision != PromotionDecisionValue.APPROVE_RESEARCH_CONFIGURATION.value:
            raise ValueError("P50_PROMOTION_NOT_APPROVED")
        existing = next((item for item in self.configurations.values() if item.promotion_decision_id == promotion_decision_id), None)
        if existing:
            return existing
        result = self.results[promotion.result_id]
        spec = self.specifications[promotion.experiment_id]
        variant = self.variants[spec.configuration_variant_id]
        parent_lineage = tuple(item.research_configuration_id for item in self.configurations.values() if item.parent_configuration_id == variant.baseline_configuration_id)
        version = f"{variant.challenger_configuration_id}@research-v{len(parent_lineage) + 1}"
        config_id = promotion.approved_research_configuration_id or deterministic_id("p50_approved_research_configuration", promotion_decision_id)
        fingerprint = _sha256_json({"config": config_id, "version": version, "variant": variant.variant_fingerprint, "decision": promotion_decision_id})
        configuration = VersionedResearchConfiguration(
            config_id,
            VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION,
            versioned_research_configuration_schema_identity(),
            version,
            variant.baseline_configuration_id,
            promotion.experiment_id,
            promotion.promotion_decision_id,
            spec.source_improvement_candidate_id,
            variant.resolved_configuration,
            variant.configuration_delta,
            variant.resolved_configuration_fingerprint,
            now,
            (spec.experiment_id, result.result_id, promotion.promotion_decision_id, promotion.comparison_id),
            ConfigurationStatus.APPROVED_RESEARCH.value,
            (*parent_lineage, config_id),
            fingerprint,
        )
        self.configurations[configuration.research_configuration_id] = configuration
        self._trim(self.configurations, self.maximum_configurations)
        self.metrics["approved_research_configurations"] += 1
        self._ledger("research_configuration_created", configuration.research_configuration_id, fingerprint, now)
        return configuration

    def rollback_configuration(self, from_configuration: str, to_configuration: str, *, reason: str, evidence_refs: Iterable[str], as_of: datetime | None = None) -> ResearchConfigurationRollback:
        now = as_of or self.clock.now()
        if from_configuration not in self.configurations or to_configuration not in self.configurations:
            raise ValueError("P50_ROLLBACK_CONFIGURATION_UNKNOWN")
        payload = {
            "from": from_configuration,
            "to": to_configuration,
            "reason": reason,
            "evidence": tuple(evidence_refs),
            "policy": self.promotion_policy.promotion_policy_identity,
        }
        fingerprint = _sha256_json(payload)
        rollback = ResearchConfigurationRollback(
            deterministic_id("p50_configuration_rollback", fingerprint),
            RESEARCH_CONFIGURATION_ROLLBACK_SCHEMA_VERSION,
            research_configuration_rollback_schema_identity(),
            from_configuration,
            to_configuration,
            reason,
            tuple(evidence_refs),
            self.promotion_policy.promotion_policy_identity,
            now,
            fingerprint,
        )
        self.rollbacks[rollback.rollback_id] = rollback
        self.metrics["rollbacks"] += 1
        self._ledger("research_configuration_rolled_back", rollback.rollback_id, fingerprint, now)
        return rollback

    def query_experiments(self, *, offset: int = 0, limit: int = 50) -> tuple[ResearchExperimentSpecification, ...]:
        limit = max(1, min(limit, self.maximum_query_limit))
        return tuple(self.specifications.values())[max(0, offset) : max(0, offset) + limit]

    def query_configurations(self, *, offset: int = 0, limit: int = 50) -> tuple[VersionedResearchConfiguration, ...]:
        limit = max(1, min(limit, self.maximum_query_limit))
        return tuple(self.configurations.values())[max(0, offset) : max(0, offset) + limit]

    def recovery_state(self, recovery_epoch: int) -> ControlledExperimentRecoveryState:
        return ControlledExperimentRecoveryState(
            RESEARCH_EXPERIMENT_LEDGER_SCHEMA_VERSION,
            CONTROLLED_EXPERIMENT_RUNTIME_VERSION,
            self.experiment_policy.policy_identity,
            self.metric_policy.metric_policy_identity,
            self.promotion_policy.promotion_policy_identity,
            self.configuration_identity,
            recovery_epoch,
            tuple(self.variants.values()),
            tuple(self.partition_plans.values()),
            tuple(self.specifications.values()),
            tuple(self.stage_results.values()),
            tuple(self.results.values()),
            tuple(self.comparisons.values()),
            tuple(self.promotion_decisions.values()),
            tuple(self.configurations.values()),
            tuple(self.rollbacks.values()),
            tuple(self.ledger.values()),
            tuple(self.holdout_exposures.values()),
        )

    def restore(self, state: ControlledExperimentRecoveryState, recovery_epoch: int) -> bool:
        self.metrics["recovery_count"] += 1
        if (
            state.runtime_version != CONTROLLED_EXPERIMENT_RUNTIME_VERSION
            or state.experiment_policy_identity != self.experiment_policy.policy_identity
            or state.metric_policy_identity != self.metric_policy.metric_policy_identity
            or state.promotion_policy_identity != self.promotion_policy.promotion_policy_identity
            or state.configuration_identity != self.configuration_identity
            or state.recovery_epoch != recovery_epoch
        ):
            self.recovery_restricted = True
            self.metrics["recovery_failures"] += 1
            self._record("experiment_recovery_failed", {"reason": "P50_RECOVERY_IDENTITY_MISMATCH"})
            return False
        try:
            self.variants = OrderedDict((item.variant_id, item) for item in state.variants)
            self.partition_plans = OrderedDict((item.partition_plan_id, item) for item in state.partition_plans)
            self.specifications = OrderedDict((item.experiment_id, item) for item in state.specifications)
            self.stage_results = OrderedDict((item.stage_result_id, item) for item in state.stage_results)
            self.results = OrderedDict((item.result_id, item) for item in state.results)
            self.comparisons = OrderedDict((item.comparison_id, item) for item in state.comparisons)
            self.promotion_decisions = OrderedDict((item.promotion_decision_id, item) for item in state.promotion_decisions)
            self.configurations = OrderedDict((item.research_configuration_id, item) for item in state.configurations)
            self.rollbacks = OrderedDict((item.rollback_id, item) for item in state.rollbacks)
            self.ledger = OrderedDict((item.ledger_record_id, item) for item in state.ledger)
            self.holdout_exposures = OrderedDict((item.holdout_identity, item) for item in state.holdout_exposures)
            self._validate_restored_graph()
            self.recovery_restricted = False
            self._record("experiment_recovery_completed", {"experiments": len(self.specifications)})
            return True
        except Exception:
            self.recovery_restricted = True
            self.metrics["recovery_failures"] += 1
            self._record("experiment_recovery_failed", {"reason": "P50_RECOVERY_GRAPH_INVALID"})
            return False

    def replay_fingerprint(self) -> str:
        return deterministic_id(
            "p50_experiment_runtime_replay",
            self.experiment_policy.policy_identity,
            self.metric_policy.metric_policy_identity,
            self.promotion_policy.promotion_policy_identity,
            *self.variants,
            *self.partition_plans,
            *self.specifications,
            *self.stage_results,
            *self.results,
            *self.comparisons,
            *self.promotion_decisions,
            *self.configurations,
            *self.rollbacks,
            *self.ledger,
        )

    def incremental_equals_full_rebuild(self) -> bool:
        state = self.recovery_state(0)
        rebuilt = ControlledResearchExperimentRuntime(
            clock=self.clock,
            audit=None,
            experiment_policy=self.experiment_policy,
            metric_policy=self.metric_policy,
            promotion_policy=self.promotion_policy,
            configuration_identity=self.configuration_identity,
            storage_root=self.storage_root,
        )
        return rebuilt.restore(state, 0) and rebuilt.replay_fingerprint() == self.replay_fingerprint()

    def diagnostics(self) -> dict[str, Any]:
        return {
            "runtime_version": CONTROLLED_EXPERIMENT_RUNTIME_VERSION,
            "experiment_policy_identity": self.experiment_policy.policy_identity,
            "metric_policy_identity": self.metric_policy.metric_policy_identity,
            "promotion_policy_identity": self.promotion_policy.promotion_policy_identity,
            "schemas": {
                "experiment_specification": research_experiment_specification_schema_identity(),
                "configuration_variant": research_configuration_variant_schema_identity(),
                "dataset_partition_plan": research_dataset_partition_plan_schema_identity(),
                "validation_stage_result": research_validation_stage_result_schema_identity(),
                "experiment_result": research_experiment_result_schema_identity(),
                "promotion_decision": research_configuration_promotion_decision_schema_identity(),
                "versioned_research_configuration": versioned_research_configuration_schema_identity(),
            },
            "experiment_count": len(self.specifications),
            "result_count": len(self.results),
            "approved_research_configuration_count": len(self.configurations),
            "metrics": dict(self.metrics),
            "runtime_health": self.component_health(None).name,
            "experiment_evidence_sufficiency": "AVAILABLE" if self.results else "NO_EXPERIMENT_EVIDENCE",
            "promotion_engine_health": "AVAILABLE",
            "configuration_registry_health": "AVAILABLE",
            "financial_execution": "NONE",
            "memory": {
                "experiments": len(self.specifications),
                "experiment_limit": self.maximum_experiments,
                "configurations": len(self.configurations),
                "configuration_limit": self.maximum_configurations,
            },
        }

    def component_ready(self, context: Any) -> bool:
        return True

    def component_health(self, context: Any) -> HealthStatus:
        if self.recovery_restricted:
            return HealthStatus.RESTRICTED
        return HealthStatus.HEALTHY

    def _validate_delta(self, scope: str, delta: Mapping[str, Any], search_space: Mapping[str, Iterable[Any]]) -> tuple[str, ...]:
        reasons = []
        if scope not in self.supported_scopes:
            reasons.append("P50_CONFIGURATION_SCOPE_UNSUPPORTED")
        if not delta:
            reasons.append("P50_CONFIGURATION_DELTA_EMPTY")
        if len(delta) > self.experiment_policy.search_budget.maximum_parameter_combinations:
            reasons.append("P50_CONFIGURATION_DELTA_UNBOUNDED")
        if len(search_space) > self.experiment_policy.search_budget.maximum_parameter_combinations:
            reasons.append("P50_SEARCH_SPACE_UNBOUNDED")
        for key, value in delta.items():
            if key not in SCHEMA:
                reasons.append("P50_CONFIGURATION_SCHEMA_UNKNOWN_FIELD")
                continue
            definition = SCHEMA[key]
            if key in HARD_SAFETY_VALUES and value != HARD_SAFETY_VALUES[key]:
                reasons.append("P50_HARD_SAFETY_WEAKENING_FORBIDDEN")
            expected = definition.value_type
            valid_type = isinstance(value, expected) or (expected is float and isinstance(value, (int, float)) and not isinstance(value, bool))
            if not valid_type:
                reasons.append("P50_CONFIGURATION_TYPE_INVALID")
            if isinstance(value, (int, float)):
                numeric = float(value)
                if definition.minimum is not None and numeric < definition.minimum:
                    reasons.append("P50_CONFIGURATION_RANGE_INVALID")
                if definition.maximum is not None and numeric > definition.maximum:
                    reasons.append("P50_CONFIGURATION_RANGE_INVALID")
            if definition.choices and value not in definition.choices:
                reasons.append("P50_CONFIGURATION_CHOICE_INVALID")
        for key, values in search_space.items():
            value_tuple = tuple(values)
            if key not in delta or not value_tuple or len(value_tuple) > self.experiment_policy.search_budget.maximum_variants:
                reasons.append("P50_SEARCH_SPACE_INVALID")
        return tuple(sorted(set(reasons)))

    def _validate_partition(self, plan: ResearchDatasetPartitionPlan) -> tuple[str, ...]:
        reasons = []
        if not plan.dataset_id or not plan.dataset_fingerprint or not plan.source_identity:
            reasons.append("P50_DATASET_IDENTITY_INVALID")
        if not (plan.coverage_start < plan.development_end <= plan.validation_start < plan.validation_end <= plan.out_of_sample_start < plan.out_of_sample_end <= (plan.holdout_start or plan.coverage_end) <= plan.coverage_end):
            reasons.append("P50_TEMPORAL_PARTITION_INVALID")
        for fold in plan.walk_forward_folds:
            if not (fold.development_start < fold.development_end <= fold.validation_start < fold.validation_end <= plan.coverage_end):
                reasons.append("P50_WALK_FORWARD_FOLD_LEAKAGE")
        return tuple(sorted(set(reasons)))

    def _stage_result(
        self,
        spec: ResearchExperimentSpecification,
        plan: ResearchDatasetPartitionPlan,
        stage: ValidationStageName,
        sequence: int,
        values: tuple[Decimal, ...],
        as_of: datetime,
    ) -> ResearchValidationStageResult:
        sample_count = len(values)
        missing = 0
        mean = _mean_tuple(values)
        reason_codes: list[str] = []
        warnings: list[str] = []
        limitations: list[str] = []
        robustness = None
        if stage is ValidationStageName.SPECIFICATION:
            status = StageStatus.PASSED
            reason_codes.append("SPECIFICATION_VALID")
        elif stage is ValidationStageName.OUT_OF_SAMPLE and sample_count < self.experiment_policy.minimum_oos_sample:
            status = StageStatus.INCONCLUSIVE
            reason_codes.append("INSUFFICIENT_EVIDENCE")
        elif stage is ValidationStageName.WALK_FORWARD:
            if sample_count < self.experiment_policy.minimum_walk_forward_folds:
                status = StageStatus.INCONCLUSIVE
                reason_codes.append("WALK_FORWARD_INSUFFICIENT_FOLDS")
            elif any(value < Decimal("0") for value in values):
                status = StageStatus.FAILED
                reason_codes.append("WALK_FORWARD_UNSTABLE")
            else:
                status = StageStatus.PASSED
                reason_codes.append("WALK_FORWARD_PASSED_WITH_FOLD_EVIDENCE")
        elif sample_count < self.experiment_policy.minimum_stage_sample:
            status = StageStatus.INCONCLUSIVE
            reason_codes.append("INSUFFICIENT_EVIDENCE")
            limitations.append("MissingEvidence != ZeroEvidence")
        elif stage is ValidationStageName.ROBUSTNESS:
            if mean is None:
                status = StageStatus.INCONCLUSIVE
                robustness = RobustnessClassification.INSUFFICIENT_EVIDENCE.value
                reason_codes.append("ROBUSTNESS_INSUFFICIENT_EVIDENCE")
            elif any(value < Decimal("0") for value in values):
                status = StageStatus.FAILED
                robustness = RobustnessClassification.FRAGILE.value
                reason_codes.append("ROBUSTNESS_FAILED")
            else:
                robustness = RobustnessClassification.ROBUST.value if max(values) - min(values) <= self.experiment_policy.maximum_generalization_gap else RobustnessClassification.CONDITIONALLY_ROBUST.value
                status = StageStatus.PASSED
                reason_codes.append(f"ROBUSTNESS_{robustness}")
        elif stage is ValidationStageName.SENSITIVITY:
            span = max(values) - min(values) if values else Decimal("0")
            if span > self.experiment_policy.maximum_sensitivity_range:
                status = StageStatus.FAILED
                reason_codes.append("SENSITIVITY_TOO_HIGH")
                warnings.append("SharpHistoricalOptimum != RobustConfiguration")
            else:
                status = StageStatus.PASSED
                reason_codes.append("SENSITIVITY_ACCEPTABLE")
        elif mean is not None and mean >= Decimal("0"):
            status = StageStatus.PASSED
            reason_codes.append(f"{stage.value}_PASSED")
        else:
            status = StageStatus.FAILED
            reason_codes.append(f"{stage.value}_FAILED")
        partition_identity = {
            ValidationStageName.SPECIFICATION: plan.partition_plan_id,
            ValidationStageName.HISTORICAL: "DEVELOPMENT",
            ValidationStageName.OUT_OF_SAMPLE: "OUT_OF_SAMPLE",
            ValidationStageName.WALK_FORWARD: "WALK_FORWARD",
            ValidationStageName.ROBUSTNESS: "ROBUSTNESS",
            ValidationStageName.SENSITIVITY: "SENSITIVITY",
        }[stage]
        metrics = {"stage_mean": mean, "research_score_delta": mean, "sample_count": Decimal(sample_count)}
        payload = {
            "experiment": spec.experiment_id,
            "stage": stage.value,
            "sequence": sequence,
            "status": status.value,
            "partition": partition_identity,
            "metrics": metrics,
            "reasons": tuple(reason_codes),
        }
        fingerprint = _sha256_json(payload)
        return ResearchValidationStageResult(
            deterministic_id("p50_validation_stage_result", fingerprint),
            RESEARCH_VALIDATION_STAGE_RESULT_SCHEMA_VERSION,
            research_validation_stage_result_schema_identity(),
            spec.experiment_id,
            stage.value,
            sequence,
            status.value,
            partition_identity,
            sample_count,
            missing,
            metrics,
            tuple(reason_codes),
            tuple(warnings),
            tuple(limitations),
            robustness,
            as_of,
            as_of,
            fingerprint,
        )

    @staticmethod
    def _stage_id(items: tuple[ResearchValidationStageResult, ...] | list[ResearchValidationStageResult], stage: ValidationStageName) -> str | None:
        return next((item.stage_result_id for item in items if item.stage_name == stage.value), None)

    @staticmethod
    def _generalization_gap(items: Iterable[ResearchValidationStageResult]) -> Decimal | None:
        lookup = {item.stage_name: item.metric_results.get("stage_mean") for item in items}
        historical = lookup.get(ValidationStageName.HISTORICAL.value)
        oos = lookup.get(ValidationStageName.OUT_OF_SAMPLE.value)
        return _q(abs(oos - historical)) if historical is not None and oos is not None else None

    @staticmethod
    def _fold_stability(items: Iterable[ResearchValidationStageResult]) -> Decimal | None:
        wf = next((item for item in items if item.stage_name == ValidationStageName.WALK_FORWARD.value), None)
        if wf is None or wf.status != StageStatus.PASSED.value:
            return None
        return Decimal("1.00000000")

    def _safety_results(self, evidence: Mapping[str, Decimal | int | float]) -> dict[str, Decimal | None]:
        result = {}
        for key in self.metric_policy.safety_metrics:
            result[key] = _q(Decimal(str(evidence[key]))) if key in evidence else Decimal("0.00000000")
        return result

    def _gate_results(self, result: ResearchExperimentResult, comparison: ResearchConfigurationComparison) -> dict[str, str]:
        stages = {self.stage_results[item].stage_name: self.stage_results[item] for item in result.completed_stage_ids}
        gates = {gate: "PASSED" for gate in self.promotion_policy.mandatory_gates}
        if result.acceptance_state == ExperimentAcceptanceState.REJECTED.value:
            gates["EVIDENCE_COMPLETE"] = "FAILED"
        if result.acceptance_state == ExperimentAcceptanceState.INCONCLUSIVE.value:
            gates["EVIDENCE_COMPLETE"] = "INCONCLUSIVE"
        if not comparison.comparable:
            gates["EVIDENCE_COMPLETE"] = "FAILED"
        if stages.get(ValidationStageName.OUT_OF_SAMPLE.value, None) is None or stages[ValidationStageName.OUT_OF_SAMPLE.value].status != StageStatus.PASSED.value:
            gates["OOS_EVIDENCE_SUFFICIENT"] = "INCONCLUSIVE"
        if stages.get(ValidationStageName.WALK_FORWARD.value, None) is None or stages[ValidationStageName.WALK_FORWARD.value].status != StageStatus.PASSED.value:
            gates["WALK_FORWARD_VALID"] = "FAILED"
        if stages.get(ValidationStageName.ROBUSTNESS.value, None) is None or stages[ValidationStageName.ROBUSTNESS.value].status != StageStatus.PASSED.value:
            gates["ROBUSTNESS_ACCEPTABLE"] = "FAILED"
        if stages.get(ValidationStageName.SENSITIVITY.value, None) is None or stages[ValidationStageName.SENSITIVITY.value].status != StageStatus.PASSED.value:
            gates["SENSITIVITY_ACCEPTABLE"] = "FAILED"
        if comparison.safety_regressions or "CRITICAL_REGRESSION" in result.rejection_reasons:
            gates["CRITICAL_REGRESSIONS_ABSENT"] = "FAILED"
            gates["PROTECTION_NOT_WEAKENED"] = "FAILED"
        return gates

    def _validate_restored_graph(self) -> None:
        for spec in self.specifications.values():
            if spec.configuration_variant_id not in self.variants or spec.partition_plan_identity not in self.partition_plans:
                raise ValueError("P50_RESTORED_ORPHAN_SPEC")
        for result in self.results.values():
            if result.experiment_id not in self.specifications:
                raise ValueError("P50_RESTORED_ORPHAN_RESULT")
        for decision in self.promotion_decisions.values():
            if decision.result_id not in self.results or decision.comparison_id not in self.comparisons:
                raise ValueError("P50_RESTORED_ORPHAN_DECISION")

    def _ledger(self, event_type: str, subject_id: str, payload_fingerprint: str, as_of: datetime) -> None:
        previous = next(reversed(self.ledger), None) if self.ledger else None
        payload = {
            "event_type": event_type,
            "subject": subject_id,
            "previous": previous,
            "payload": payload_fingerprint,
            "as_of": as_of,
        }
        fingerprint = _sha256_json(payload)
        record = ResearchExperimentLedgerRecord(
            deterministic_id("p50_experiment_ledger_record", fingerprint),
            RESEARCH_EXPERIMENT_LEDGER_SCHEMA_VERSION,
            research_experiment_ledger_schema_identity(),
            event_type,
            subject_id,
            previous,
            payload_fingerprint,
            as_of,
            fingerprint,
        )
        self.ledger[record.ledger_record_id] = record

    @staticmethod
    def _trim(items: OrderedDict[str, Any], maximum: int) -> None:
        while len(items) > maximum:
            items.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, dict(payload))


class ControlledExperimentComponent:
    def __init__(self, component_id: str, holder: dict[str, ControlledResearchExperimentRuntime]) -> None:
        self.component_id = component_id
        self.runtime: ControlledResearchExperimentRuntime | None = None
        self._holder = holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if "runtime" in self._holder:
                self.runtime = self._holder["runtime"]
            else:
                self.runtime = ControlledResearchExperimentRuntime(clock=context.services["clock"], audit=context.services["audit"])
                self._holder["runtime"] = self.runtime
        self.runtime.initialize_component(context)

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def component_diagnostics(self, context: Any) -> dict[str, Any]:
        return self.runtime.diagnostics() if self.runtime is not None else {}

    def snapshot_component_state(self, context: Any) -> Mapping[str, Any]:
        return {"component_id": self.component_id, "replay_fingerprint": self.runtime.replay_fingerprint() if self.runtime else None}

    def restore_component_state(self, payload: Mapping[str, Any] | None, context: Any) -> None:
        return None

    def reconcile_component(self, context: Any) -> bool:
        return True

    def start_component(self, context: Any) -> None:
        return None

    def stop_component(self, context: Any) -> None:
        return None


def controlled_experiment_component_registrations() -> tuple[tuple[ComponentMetadata, ControlledExperimentComponent], ...]:
    holder: dict[str, ControlledResearchExperimentRuntime] = {}
    definitions = (
        ("experiment_registry", ("research_improvement_snapshot",)),
        ("experiment_specification_validator", ("experiment_registry",)),
        ("dataset_partition_manager", ("experiment_specification_validator",)),
        ("research_experiment_runtime", ("dataset_partition_manager",)),
        ("historical_validation", ("research_experiment_runtime",)),
        ("out_of_sample_validation", ("historical_validation",)),
        ("walk_forward_validation", ("out_of_sample_validation",)),
        ("robustness_validation", ("walk_forward_validation",)),
        ("sensitivity_validation", ("robustness_validation",)),
        ("configuration_comparison", ("sensitivity_validation",)),
        ("research_promotion_assessment", ("configuration_comparison",)),
        ("versioned_research_configuration", ("research_promotion_assessment",)),
    )
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    return tuple(
        (
            ComponentMetadata(component_id, ComponentType.RESEARCH, CONTROLLED_EXPERIMENT_RUNTIME_VERSION, True, dependencies, capabilities),
            ControlledExperimentComponent(component_id, holder),
        )
        for component_id, dependencies in definitions
    )


def controlled_experiment_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, dict[str, Any]]:
    ids = {
        "experiment_registry",
        "experiment_specification_validator",
        "dataset_partition_manager",
        "research_experiment_runtime",
        "historical_validation",
        "out_of_sample_validation",
        "walk_forward_validation",
        "robustness_validation",
        "sensitivity_validation",
        "configuration_comparison",
        "research_promotion_assessment",
        "versioned_research_configuration",
    }
    return {
        str(item["component_id"]): {
            "active": bool(item.get("active")),
            "ready": bool(item.get("ready")),
            "status": str(item.get("status")),
            "health": str(item.get("health")),
            "persistence_participant": bool(item.get("persistence_participant")),
            "recovery_participant": bool(item.get("recovery_participant")),
        }
        for item in inventory
        if item.get("component_id") in ids
    }


def research_experiment_specification_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_experiment_specification", "version": RESEARCH_EXPERIMENT_SPECIFICATION_SCHEMA_VERSION, "fields": tuple(ResearchExperimentSpecification.__dataclass_fields__), "p49_candidate": improvement_candidate_schema_identity()})


def research_configuration_variant_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_configuration_variant", "version": RESEARCH_CONFIGURATION_VARIANT_SCHEMA_VERSION, "fields": tuple(ResearchConfigurationVariant.__dataclass_fields__)})


def research_dataset_partition_plan_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_dataset_partition_plan", "version": RESEARCH_DATASET_PARTITION_PLAN_SCHEMA_VERSION, "fields": tuple(ResearchDatasetPartitionPlan.__dataclass_fields__)})


def research_validation_stage_result_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_validation_stage_result", "version": RESEARCH_VALIDATION_STAGE_RESULT_SCHEMA_VERSION, "fields": tuple(ResearchValidationStageResult.__dataclass_fields__)})


def research_experiment_result_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_experiment_result", "version": RESEARCH_EXPERIMENT_RESULT_SCHEMA_VERSION, "fields": tuple(ResearchExperimentResult.__dataclass_fields__), "stage": research_validation_stage_result_schema_identity()})


def research_configuration_comparison_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_configuration_comparison", "version": RESEARCH_CONFIGURATION_COMPARISON_SCHEMA_VERSION, "fields": tuple(ResearchConfigurationComparison.__dataclass_fields__), "result": research_experiment_result_schema_identity()})


def research_configuration_promotion_decision_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_configuration_promotion_decision", "version": RESEARCH_CONFIGURATION_PROMOTION_DECISION_SCHEMA_VERSION, "fields": tuple(ResearchConfigurationPromotionDecision.__dataclass_fields__), "comparison": research_configuration_comparison_schema_identity()})


def versioned_research_configuration_schema_identity() -> str:
    return _sha256_json({"schema": "p50_versioned_research_configuration", "version": VERSIONED_RESEARCH_CONFIGURATION_SCHEMA_VERSION, "fields": tuple(VersionedResearchConfiguration.__dataclass_fields__), "promotion": research_configuration_promotion_decision_schema_identity()})


def research_configuration_rollback_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_configuration_rollback", "version": RESEARCH_CONFIGURATION_ROLLBACK_SCHEMA_VERSION, "fields": tuple(ResearchConfigurationRollback.__dataclass_fields__), "configuration": versioned_research_configuration_schema_identity()})


def research_experiment_ledger_schema_identity() -> str:
    return _sha256_json({"schema": "p50_research_experiment_ledger", "version": RESEARCH_EXPERIMENT_LEDGER_SCHEMA_VERSION, "fields": tuple(ResearchExperimentLedgerRecord.__dataclass_fields__)})


def research_experiment_policy_identity() -> str:
    return ResearchExperimentPolicy.current().policy_identity


def research_validation_metric_policy_identity() -> str:
    return ResearchValidationMetricPolicy.current().metric_policy_identity


def research_configuration_promotion_policy_identity() -> str:
    return ResearchConfigurationPromotionPolicy.current().promotion_policy_identity


def _mean_tuple(values: tuple[Decimal, ...]) -> Decimal | None:
    return _q(sum(values, Decimal("0")) / Decimal(len(values))) if values else None


def _q(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("0.00000001"))


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value
