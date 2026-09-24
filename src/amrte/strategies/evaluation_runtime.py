from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.market.intelligence import IntelligenceAvailability, IntelligenceHealth
from amrte.market.intelligence_runtime import (
    UnifiedMarketIntelligenceSnapshot,
    market_intelligence_schema_identity,
)
from amrte.strategies.breakout_volatility import S2Configuration, S2Variant, register_s2
from amrte.strategies.framework import (
    CandidateStatus,
    EvaluationOutcome,
    EvaluationReason,
    FinalResearchAction,
    IStrategy,
    SignalCandidate,
    SignalDirection,
    StrategyEvaluation,
    StrategyFrameworkConfiguration,
    StrategyOrchestrator,
    StrategyRegistry,
    STRATEGY_FRAMEWORK_VERSION,
    STRATEGY_SCHEMA_VERSION,
)
from amrte.strategies.range_mean_reversion import register_s3
from amrte.strategies.trend_pullback import register_s1


STRATEGY_EVALUATION_RUNTIME_VERSION = "1.0"
RESEARCH_CANDIDATE_SCHEMA_VERSION = "1.0"
STRATEGY_EVALUATION_SET_SCHEMA_VERSION = "1.0"


class StrategyEvaluationRuntimeAcceptance(Enum):
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class StrategyEvaluationRuntimeConfiguration:
    configuration_snapshot_id: str = "P42_STRATEGY_EVALUATION_DEFAULT"
    enabled_strategy_ids: tuple[str, ...] = ()
    maximum_evaluation_sets: int = 1024
    maximum_candidates: int = 4096
    maximum_diagnostics: int = 256
    strategy_framework: StrategyFrameworkConfiguration = field(default_factory=StrategyFrameworkConfiguration)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.configuration_snapshot_id.strip():
            errors.append("P42_CONFIGURATION_ID_REQUIRED")
        if min(self.maximum_evaluation_sets, self.maximum_candidates, self.maximum_diagnostics) < 1:
            errors.append("P42_BOUNDS_INVALID")
        errors.extend(self.strategy_framework.validate())
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class StrategyRegistration:
    strategy_id: str
    strategy_name: str
    strategy_version: str
    strategy_family: str
    implementation_identity: str
    enabled: bool
    required_features: tuple[str, ...]
    required_timeframes: tuple[str, ...]
    allowed_regimes: tuple[str, ...]
    required_intelligence: tuple[str, ...]
    configuration_identity: str
    runtime_status: str


@dataclass(frozen=True)
class StrategyEligibilityResult:
    eligibility_id: str
    strategy_id: str
    strategy_version: str
    market_intelligence_snapshot_id: str
    eligible: bool
    status: str
    reason_codes: tuple[str, ...]
    missing_requirements: tuple[str, ...]
    warnings: tuple[str, ...]
    evaluated_at: datetime
    configuration_identity: str


@dataclass(frozen=True)
class ResearchCandidate:
    candidate_id: str
    candidate_schema_version: str
    candidate_schema_identity: str
    strategy_id: str
    strategy_version: str
    strategy_implementation_identity: str
    market_intelligence_snapshot_id: str
    market_intelligence_fingerprint: str
    trusted_observation_id: str
    observation_id: str
    observation_fingerprint: str
    dataset_id: str
    dataset_fingerprint: str
    instrument_id: str
    timeframe: str
    candidate_type: str
    research_direction: str
    generated_at: datetime
    knowledge_cutoff_utc: datetime
    eligibility_id: str
    source_signal_candidate_id: str
    source_research_signal_id: str | None
    reason_codes: tuple[str, ...]
    supporting_evidence_ids: tuple[str, ...]
    conflicting_evidence_ids: tuple[str, ...]
    missing_evidence_ids: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]
    expires_at_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    candidate_fingerprint: str


@dataclass(frozen=True)
class StrategyEvaluationRecord:
    strategy_id: str
    strategy_version: str
    evaluation_id: str
    outcome: str
    final_action: str
    candidate_id: str | None
    source_candidate_id: str | None
    source_research_signal_id: str | None
    reason_codes: tuple[str, ...]
    health: str
    readiness: str


@dataclass(frozen=True)
class StrategyEvaluationSet:
    evaluation_set_id: str
    evaluation_schema_version: str
    evaluation_schema_identity: str
    evaluation_fingerprint: str
    created_at: datetime
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    market_intelligence_snapshot_id: str
    market_intelligence_fingerprint: str
    trusted_observation_id: str
    instrument_id: str
    dataset_id: str
    dataset_fingerprint: str
    strategies_considered: tuple[str, ...]
    strategies_enabled: tuple[str, ...]
    strategies_eligible: tuple[str, ...]
    strategies_evaluated: tuple[str, ...]
    eligibility_results: tuple[StrategyEligibilityResult, ...]
    evaluations: tuple[StrategyEvaluationRecord, ...]
    candidates: tuple[ResearchCandidate, ...]
    no_candidate_outcomes: tuple[str, ...]
    restricted_outcomes: tuple[str, ...]
    error_outcomes: tuple[str, ...]
    scoring_active: bool
    arbitration_active: bool
    final_decision_active: bool
    configuration_identity: str
    recovery_epoch: int


@dataclass(frozen=True)
class StrategyEvaluationRuntimeResult:
    acceptance: StrategyEvaluationRuntimeAcceptance
    evaluation_set: StrategyEvaluationSet | None
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyEvaluationRecoveryState:
    schema_version: str
    runtime_version: str
    configuration_identity: str
    recovery_epoch: int
    processed_snapshot_ids: tuple[str, ...]
    evaluation_sets: tuple[StrategyEvaluationSet, ...]
    orchestrator_state: Mapping[str, Any]
    strategy_states: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "orchestrator_state", MappingProxyType(dict(self.orchestrator_state)))
        object.__setattr__(self, "strategy_states", MappingProxyType(dict(self.strategy_states)))


class StrategyEvaluationRuntime:
    """Authoritative Prompt 42 strategy-evaluation coordinator."""

    def __init__(
        self,
        configuration: StrategyEvaluationRuntimeConfiguration = StrategyEvaluationRuntimeConfiguration(),
        *,
        clock: Any,
        audit: Any,
        registry: StrategyRegistry | None = None,
        orchestrator: StrategyOrchestrator | None = None,
    ) -> None:
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.clock = clock
        self.audit = audit
        self.registry = registry or default_strategy_registry(audit)
        self.orchestrator = orchestrator or StrategyOrchestrator(
            clock,
            audit,
            self.registry,
            configuration.strategy_framework,
        )
        self.evaluation_sets: OrderedDict[str, StrategyEvaluationSet] = OrderedDict()
        self.candidates: OrderedDict[str, ResearchCandidate] = OrderedDict()
        self._processed_snapshot_ids: set[str] = set()
        self.recovery_restricted = False

    @property
    def configuration_identity(self) -> str:
        return self.configuration.configuration_snapshot_id

    def evaluate_unified_snapshot(
        self,
        snapshot: UnifiedMarketIntelligenceSnapshot,
        *,
        reason: EvaluationReason = EvaluationReason.NEW_BAR,
    ) -> StrategyEvaluationRuntimeResult:
        boundary_reasons = self._validate_input(snapshot)
        snapshot_id = snapshot.unified_snapshot_id
        if snapshot_id in self._processed_snapshot_ids:
            existing = next((item for item in self.evaluation_sets.values() if item.market_intelligence_snapshot_id == snapshot.market_intelligence_snapshot_id), None)
            return StrategyEvaluationRuntimeResult(StrategyEvaluationRuntimeAcceptance.DUPLICATE, existing, ("P42_DUPLICATE_INTELLIGENCE_SNAPSHOT",))
        if boundary_reasons:
            self._record("strategy_evaluation_restricted", {"unified_snapshot_id": snapshot_id, "reasons": boundary_reasons})
            return StrategyEvaluationRuntimeResult(StrategyEvaluationRuntimeAcceptance.BLOCKED, None, boundary_reasons)

        intelligence = snapshot.market_intelligence
        evaluations = tuple(self.orchestrator.evaluate(strategy, intelligence, reason) for strategy in self._enabled_strategies())
        eligibility = tuple(self._eligibility(item, snapshot) for item in evaluations)
        candidate_by_source: dict[str, ResearchCandidate] = {}
        candidates: list[ResearchCandidate] = []
        records: list[StrategyEvaluationRecord] = []
        for evaluation in evaluations:
            eligibility_result = next(item for item in eligibility if item.strategy_id == evaluation.strategy_id)
            candidate = self._candidate(snapshot, evaluation, eligibility_result)
            if candidate is not None:
                candidates.append(candidate)
                candidate_by_source[evaluation.candidate.signal_candidate_id] = candidate
                self.candidates[candidate.candidate_id] = candidate
            records.append(
                StrategyEvaluationRecord(
                    evaluation.strategy_id,
                    self.registry.get(evaluation.strategy_id).metadata.identity.version,
                    evaluation.evaluation_id,
                    evaluation.outcome.name,
                    evaluation.final_action.name,
                    candidate.candidate_id if candidate else None,
                    evaluation.candidate.signal_candidate_id if evaluation.candidate else None,
                    evaluation.research_signal.research_signal_id if evaluation.research_signal else None,
                    evaluation.reason_codes,
                    evaluation.strategy_health.name,
                    evaluation.readiness.name,
                )
            )
        evaluation_set = self._evaluation_set(snapshot, evaluations, eligibility, tuple(records), tuple(candidates))
        self.evaluation_sets[evaluation_set.evaluation_set_id] = evaluation_set
        self._processed_snapshot_ids.add(snapshot_id)
        self._bound()
        self._record(
            "strategy_evaluation_set_created",
            {
                "evaluation_set_id": evaluation_set.evaluation_set_id,
                "candidates": len(evaluation_set.candidates),
                "strategies_evaluated": len(evaluation_set.strategies_evaluated),
            },
        )
        return StrategyEvaluationRuntimeResult(StrategyEvaluationRuntimeAcceptance.ACCEPTED, evaluation_set, evaluation_set.restricted_outcomes)

    def recovery_state(self, recovery_epoch: int) -> StrategyEvaluationRecoveryState:
        return StrategyEvaluationRecoveryState(
            STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
            STRATEGY_EVALUATION_RUNTIME_VERSION,
            self.configuration_identity,
            recovery_epoch,
            tuple(sorted(self._processed_snapshot_ids)),
            tuple(self.evaluation_sets.values()),
            self.orchestrator.recovery_state(),
            {
                strategy.metadata.identity.strategy_id: getattr(strategy, "recovery_state", lambda: {})()
                for strategy in self.registry.all()
            },
        )

    def restore(self, state: StrategyEvaluationRecoveryState, expected_recovery_epoch: int) -> bool:
        if (
            state.schema_version != STRATEGY_EVALUATION_SET_SCHEMA_VERSION
            or state.runtime_version != STRATEGY_EVALUATION_RUNTIME_VERSION
            or state.configuration_identity != self.configuration_identity
            or state.recovery_epoch != expected_recovery_epoch
        ):
            self.recovery_restricted = True
            return False
        try:
            if not self.orchestrator.validate_recovery(state.orchestrator_state):
                raise ValueError("orchestrator recovery divergence")
            for strategy in self.registry.all():
                validator = getattr(strategy, "validate_recovery", None)
                strategy_state = state.strategy_states.get(strategy.metadata.identity.strategy_id)
                if validator is not None and strategy_state not in (None, {}):
                    try:
                        valid = bool(validator(strategy_state))
                    except TypeError:
                        valid = True
                    if not valid:
                        raise ValueError(f"strategy recovery divergence:{strategy.metadata.identity.strategy_id}")
            self._processed_snapshot_ids = set(state.processed_snapshot_ids)
            self.evaluation_sets = OrderedDict((item.evaluation_set_id, item) for item in state.evaluation_sets)
            self.candidates = OrderedDict((candidate.candidate_id, candidate) for item in state.evaluation_sets for candidate in item.candidates)
            self.recovery_restricted = False
            return True
        except Exception:
            self.recovery_restricted = True
            return False

    def reconcile(self, recovery_epoch: int) -> tuple[str, ...]:
        issues: list[str] = []
        if self.recovery_restricted:
            issues.append("P42_RECOVERY_RESTRICTED")
        if any(item.recovery_epoch > recovery_epoch for item in self.evaluation_sets.values()):
            issues.append("P42_RECOVERY_EPOCH_REGRESSION")
        return tuple(dict.fromkeys(issues))

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.evaluation_sets.values()), None) if self.evaluation_sets else None
        return {
            "candidate_schema_version": RESEARCH_CANDIDATE_SCHEMA_VERSION,
            "candidate_schema_identity": research_candidate_schema_identity(),
            "evaluation_schema_version": STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
            "evaluation_schema_identity": strategy_evaluation_set_schema_identity(),
            "runtime_version": STRATEGY_EVALUATION_RUNTIME_VERSION,
            "configuration_identity": self.configuration_identity,
            "p41_schema_identity": market_intelligence_schema_identity(),
            "p41_input_required": True,
            "raw_observation_bypass_available": False,
            "trusted_observation_bypass_available": False,
            "strategy_count": len(self.registry),
            "registry": [_registration_dict(item) for item in self.strategy_registrations()],
            "evaluation_set_count": len(self.evaluation_sets),
            "candidate_count": len(self.candidates),
            "latest_evaluation_set": _evaluation_set_summary(latest),
            "scoring_active": False,
            "central_scoring_active": False,
            "arbitration_active": False,
            "final_decision_active": False,
            "financial_execution_available": False,
            "recovery_restricted": self.recovery_restricted,
        }

    def strategy_registrations(self) -> tuple[StrategyRegistration, ...]:
        enabled = set(self.configuration.enabled_strategy_ids)
        return tuple(
            StrategyRegistration(
                strategy.metadata.identity.strategy_id,
                strategy.metadata.identity.name,
                strategy.metadata.identity.version,
                strategy.metadata.identity.family.name,
                strategy_implementation_identity(strategy),
                not enabled or strategy.metadata.identity.strategy_id in enabled,
                tuple(strategy.metadata.required_features),
                tuple(strategy.metadata.required_timeframes),
                tuple(strategy.metadata.allowed_regimes),
                tuple(sorted({req.source.name for req in strategy.metadata.requirements})),
                getattr(getattr(strategy, "configuration", None), "configuration_snapshot_id", self.configuration_identity),
                "READY",
            )
            for strategy in self.registry.all()
        )

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted and len(self.registry) > 0

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.DEGRADED if self.recovery_restricted else HealthStatus.HEALTHY

    def _enabled_strategies(self) -> tuple[IStrategy, ...]:
        enabled = set(self.configuration.enabled_strategy_ids)
        return tuple(strategy for strategy in self.registry.all() if not enabled or strategy.metadata.identity.strategy_id in enabled)

    def _validate_input(self, snapshot: UnifiedMarketIntelligenceSnapshot) -> tuple[str, ...]:
        reasons: list[str] = []
        if snapshot.schema_identity != market_intelligence_schema_identity():
            reasons.append("P42_P41_SCHEMA_IDENTITY_MISMATCH")
        intel = snapshot.market_intelligence
        if intel.market_intelligence_snapshot_id != snapshot.market_intelligence_snapshot_id:
            reasons.append("P42_P41_LINEAGE_MISMATCH")
        if snapshot.research_pipeline_active:
            reasons.append("P42_UNEXPECTED_DECISION_PIPELINE_ACTIVE")
        if snapshot.financial_execution != "NONE":
            reasons.append("P42_UNEXPECTED_EXECUTION_CAPABILITY")
        if intel.intelligence_availability in (IntelligenceAvailability.NOT_AVAILABLE, IntelligenceAvailability.UNKNOWN):
            reasons.append("P42_INTELLIGENCE_UNAVAILABLE")
        if intel.overall_intelligence_health in (IntelligenceHealth.UNTRUSTED, IntelligenceHealth.UNAVAILABLE, IntelligenceHealth.UNKNOWN):
            reasons.append("P42_INTELLIGENCE_UNTRUSTED")
        return tuple(dict.fromkeys(reasons))

    def _eligibility(self, evaluation: StrategyEvaluation, snapshot: UnifiedMarketIntelligenceSnapshot) -> StrategyEligibilityResult:
        eligible = evaluation.applicability.state.name in {"APPLICABLE", "CONDITIONAL"}
        missing: list[str] = []
        if evaluation.applicability.capability_status.name in {"UNSUPPORTED", "UNAVAILABLE", "UNKNOWN"}:
            missing.append(evaluation.applicability.capability_status.name)
        if evaluation.detection is not None:
            missing.extend(item.explanation_code for item in evaluation.detection.missing_evidence)
        return StrategyEligibilityResult(
            deterministic_id("p42_strategy_eligibility", evaluation.evaluation_id, evaluation.applicability.state.name),
            evaluation.strategy_id,
            self.registry.get(evaluation.strategy_id).metadata.identity.version,
            snapshot.market_intelligence_snapshot_id,
            eligible,
            evaluation.applicability.state.name,
            tuple(dict.fromkeys((*evaluation.applicability.reasons, *evaluation.reason_codes))),
            tuple(dict.fromkeys(missing)),
            evaluation.applicability.restrictions,
            self.clock.now(),
            self.configuration_identity,
        )

    def _candidate(
        self,
        snapshot: UnifiedMarketIntelligenceSnapshot,
        evaluation: StrategyEvaluation,
        eligibility: StrategyEligibilityResult,
    ) -> ResearchCandidate | None:
        source = evaluation.candidate
        if source is None or source.candidate_status not in (CandidateStatus.QUALIFIED, CandidateStatus.CONDITIONALLY_QUALIFIED):
            return None
        strategy = self.registry.get(evaluation.strategy_id)
        implementation_identity = strategy_implementation_identity(strategy)
        supporting = tuple(item.evidence_id for item in source.supporting_evidence)
        conflicting = tuple(item.evidence_id for item in source.conflicting_evidence)
        missing = tuple(item.evidence_id for item in source.missing_evidence)
        invalidation = ("TTL_EXPIRES_AT:" + source.expires_at_utc.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),)
        fingerprint = _sha256_json(
            {
                "strategy_id": source.strategy_id,
                "strategy_version": source.strategy_version,
                "implementation_identity": implementation_identity,
                "source_candidate_id": source.signal_candidate_id,
                "market_intelligence_snapshot_id": snapshot.market_intelligence_snapshot_id,
                "market_intelligence_fingerprint": snapshot.snapshot_fingerprint,
                "direction": source.direction.name,
                "eligibility_id": eligibility.eligibility_id,
                "configuration_identity": self.configuration_identity,
                "recovery_epoch": source.recovery_epoch,
            }
        )
        candidate_id = deterministic_id("p42_research_candidate", fingerprint)
        return ResearchCandidate(
            candidate_id,
            RESEARCH_CANDIDATE_SCHEMA_VERSION,
            research_candidate_schema_identity(),
            source.strategy_id,
            source.strategy_version,
            implementation_identity,
            snapshot.market_intelligence_snapshot_id,
            snapshot.snapshot_fingerprint,
            snapshot.trusted_observation_id,
            snapshot.observation_id,
            snapshot.observation_fingerprint,
            snapshot.dataset_id,
            snapshot.dataset_fingerprint,
            source.instrument_id,
            snapshot.timeframe,
            source.candidate_status.name,
            _research_direction(source.direction),
            self.clock.now(),
            snapshot.knowledge_cutoff_utc,
            eligibility.eligibility_id,
            source.signal_candidate_id,
            evaluation.research_signal.research_signal_id if evaluation.research_signal else None,
            tuple(dict.fromkeys((*source.reason_codes, *evaluation.reason_codes, "RESEARCH_CANDIDATE_NOT_AUTHORIZATION"))),
            supporting,
            conflicting,
            missing,
            invalidation,
            source.expires_at_utc,
            self.configuration_identity,
            source.recovery_epoch,
            fingerprint,
        )

    def _evaluation_set(
        self,
        snapshot: UnifiedMarketIntelligenceSnapshot,
        evaluations: tuple[StrategyEvaluation, ...],
        eligibility: tuple[StrategyEligibilityResult, ...],
        records: tuple[StrategyEvaluationRecord, ...],
        candidates: tuple[ResearchCandidate, ...],
    ) -> StrategyEvaluationSet:
        considered = tuple(item.metadata.identity.strategy_id for item in self.registry.all())
        enabled = tuple(item.metadata.identity.strategy_id for item in self._enabled_strategies())
        eligible = tuple(item.strategy_id for item in eligibility if item.eligible)
        evaluated = tuple(item.strategy_id for item in evaluations)
        no_candidate = tuple(item.strategy_id for item in records if item.candidate_id is None and item.outcome in {"NO_ACTION", "COMPLETED"})
        restricted = tuple(item.strategy_id for item in records if item.final_action == "BLOCKED")
        errors = tuple(item.strategy_id for item in records if item.outcome == "ERROR")
        fingerprint = _sha256_json(
            {
                "market_intelligence_snapshot_id": snapshot.market_intelligence_snapshot_id,
                "market_intelligence_fingerprint": snapshot.snapshot_fingerprint,
                "strategies": considered,
                "records": records,
                "candidates": tuple(item.candidate_id for item in candidates),
                "configuration_identity": self.configuration_identity,
                "recovery_epoch": snapshot.recovery_epoch,
            }
        )
        identity = deterministic_id("p42_strategy_evaluation_set", fingerprint)
        return StrategyEvaluationSet(
            identity,
            STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
            strategy_evaluation_set_schema_identity(),
            fingerprint,
            self.clock.now(),
            snapshot.as_of_timestamp_utc,
            snapshot.knowledge_cutoff_utc,
            snapshot.market_intelligence_snapshot_id,
            snapshot.snapshot_fingerprint,
            snapshot.trusted_observation_id,
            snapshot.instrument_id,
            snapshot.dataset_id,
            snapshot.dataset_fingerprint,
            considered,
            enabled,
            eligible,
            evaluated,
            eligibility,
            records,
            candidates,
            no_candidate,
            restricted,
            errors,
            False,
            False,
            False,
            self.configuration_identity,
            snapshot.recovery_epoch,
        )

    def _bound(self) -> None:
        while len(self.evaluation_sets) > self.configuration.maximum_evaluation_sets:
            self.evaluation_sets.popitem(last=False)
        while len(self.candidates) > self.configuration.maximum_candidates:
            self.candidates.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class StrategyEvaluationRuntimeComponent:
    def __init__(self, component_id: str, runtime_holder: dict[str, StrategyEvaluationRuntime] | None = None) -> None:
        self.component_id = component_id
        self.runtime: StrategyEvaluationRuntime | None = None
        self._runtime_holder = runtime_holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                self.runtime = StrategyEvaluationRuntime(clock=context.services["clock"], audit=context.services["audit"])
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record("strategy_evaluation_runtime_initialized", {"component_id": self.component_id, "evaluation_schema_identity": strategy_evaluation_set_schema_identity()})

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def default_strategy_registry(audit: Any = None) -> StrategyRegistry:
    registry = StrategyRegistry()
    register_s1(registry, audit=audit)
    register_s2(registry, S2Configuration(variant=S2Variant.IMMEDIATE), audit=audit)
    register_s2(registry, S2Configuration(variant=S2Variant.RETEST), audit=audit)
    register_s3(registry, audit=audit)
    return registry


def strategy_implementation_identity(strategy: IStrategy) -> str:
    metadata = strategy.metadata
    payload = {
        "strategy_id": metadata.identity.strategy_id,
        "strategy_name": metadata.identity.name,
        "strategy_version": metadata.identity.version,
        "family": metadata.identity.family.name,
        "required_features": metadata.required_features,
        "required_timeframes": metadata.required_timeframes,
        "allowed_regimes": metadata.allowed_regimes,
        "requirements": tuple((item.requirement_id, item.requirement_type.name, item.source.name, item.capability, item.timeframe) for item in metadata.requirements),
        "configuration": _jsonable(getattr(strategy, "configuration", None)),
    }
    return _sha256_json(payload)


def research_candidate_schema_identity() -> str:
    payload = {
        "schema": "p42_research_candidate",
        "version": RESEARCH_CANDIDATE_SCHEMA_VERSION,
        "fields": tuple(ResearchCandidate.__dataclass_fields__),
        "upstream": {"p41_market_intelligence": market_intelligence_schema_identity()},
    }
    return _sha256_json(payload)


def strategy_evaluation_set_schema_identity() -> str:
    payload = {
        "schema": "p42_strategy_evaluation_set",
        "version": STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
        "fields": tuple(StrategyEvaluationSet.__dataclass_fields__),
        "candidate_schema_identity": research_candidate_schema_identity(),
        "framework_version": STRATEGY_FRAMEWORK_VERSION,
        "strategy_schema_version": STRATEGY_SCHEMA_VERSION,
    }
    return _sha256_json(payload)


def strategy_evaluation_component_registrations() -> tuple[tuple[ComponentMetadata, StrategyEvaluationRuntimeComponent], ...]:
    holder: dict[str, StrategyEvaluationRuntime] = {}
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    definitions = (
        ("strategy_registry", ("market_intelligence", "configuration", "clock", "audit", "observability")),
        ("strategy_evaluation", ("strategy_registry", "market_intelligence")),
        ("research_candidate_runtime", ("strategy_evaluation",)),
    )
    return tuple(
        (
            ComponentMetadata(component_id, ComponentType.RESEARCH, STRATEGY_EVALUATION_RUNTIME_VERSION, True, dependencies, capabilities),
            StrategyEvaluationRuntimeComponent(component_id, holder),
        )
        for component_id, dependencies in definitions
    )


def strategy_evaluation_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"strategy_registry", "strategy_evaluation", "research_candidate_runtime"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def _registration_dict(item: StrategyRegistration) -> dict[str, Any]:
    return _jsonable(item)


def _evaluation_set_summary(item: StrategyEvaluationSet | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "evaluation_set_id": item.evaluation_set_id,
        "evaluation_fingerprint": item.evaluation_fingerprint,
        "market_intelligence_snapshot_id": item.market_intelligence_snapshot_id,
        "strategies_considered": list(item.strategies_considered),
        "strategies_eligible": list(item.strategies_eligible),
        "candidate_ids": [candidate.candidate_id for candidate in item.candidates],
        "no_candidate_outcomes": list(item.no_candidate_outcomes),
        "restricted_outcomes": list(item.restricted_outcomes),
        "error_outcomes": list(item.error_outcomes),
        "scoring_active": item.scoring_active,
        "arbitration_active": item.arbitration_active,
        "final_decision_active": item.final_decision_active,
    }


def _research_direction(direction: SignalDirection) -> str:
    return {
        SignalDirection.LONG_BIAS: "BULLISH",
        SignalDirection.SHORT_BIAS: "BEARISH",
        SignalDirection.NEUTRAL: "NEUTRAL",
        SignalDirection.BIDIRECTIONAL: "BIDIRECTIONAL",
    }.get(direction, "UNKNOWN")


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value
