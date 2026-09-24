from __future__ import annotations

import hashlib
import json
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.types import HealthStatus
from amrte.portfolio.correlation import (
    CORRELATION_ENGINE_VERSION,
    CorrelationConfiguration,
    CorrelationDependencyEngine,
    CorrelationHealth,
    ReturnSeries,
)
from amrte.portfolio.risk import PORTFOLIO_ENGINE_VERSION, PortfolioConfiguration
from amrte.risk.sizing import _decimal
from amrte.strategies.research_scoring_runtime import (
    RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
    ResearchArbitrationAssessment,
    ScoredResearchCandidate,
    research_arbitration_assessment_schema_identity,
    scored_research_candidate_schema_identity,
)


RESEARCH_PORTFOLIO_RUNTIME_VERSION = "1.0"
CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION = "1.0"
CORRELATION_RESEARCH_SCHEMA_VERSION = "1.0"
PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION = "1.0"


class PortfolioResearchAcceptance(Enum):
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"


class CandidateRiskState(Enum):
    ACCEPTABLE = "ACCEPTABLE"
    ACCEPTABLE_WITH_RESTRICTIONS = "ACCEPTABLE_WITH_RESTRICTIONS"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"
    DEFERRED = "DEFERRED"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class PortfolioResearchStateValue(Enum):
    ACCEPTABLE = "ACCEPTABLE"
    ACCEPTABLE_WITH_RESTRICTIONS = "ACCEPTABLE_WITH_RESTRICTIONS"
    RESTRICTED = "RESTRICTED"
    NO_ACTION = "NO_ACTION"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID = "INVALID"


class PortfolioConflictType(Enum):
    INSTRUMENT_CONFLICT = "INSTRUMENT_CONFLICT"
    DIRECTIONAL_CONFLICT = "DIRECTIONAL_CONFLICT"
    STRATEGY_CONFLICT = "STRATEGY_CONFLICT"
    STRATEGY_FAMILY_CONFLICT = "STRATEGY_FAMILY_CONFLICT"
    CORRELATION_CONFLICT = "CORRELATION_CONFLICT"
    CONCENTRATION_CONFLICT = "CONCENTRATION_CONFLICT"
    CAPACITY_CONFLICT = "CAPACITY_CONFLICT"
    HYPOTHESIS_OVERLAP = "HYPOTHESIS_OVERLAP"
    DATA_QUALITY_CONFLICT = "DATA_QUALITY_CONFLICT"
    TEMPORAL_CONFLICT = "TEMPORAL_CONFLICT"
    CONFIGURATION_CONFLICT = "CONFIGURATION_CONFLICT"


SEVERITY_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}


@dataclass(frozen=True)
class ResearchPortfolioRuntimeConfiguration:
    configuration_snapshot_id: str = "P44_RESEARCH_PORTFOLIO_DEFAULT"
    maximum_snapshots: int = 1024
    maximum_candidate_risk_assessments: int = 4096
    maximum_correlation_snapshots: int = 1024
    maximum_conflicts: int = 2048
    maximum_simultaneous_research_candidates: int = 8
    maximum_same_instrument_candidates: int = 2
    maximum_same_strategy_family_candidates: int = 2
    maximum_same_direction_share: Decimal = Decimal("0.75")
    maximum_correlated_cluster_members: int = 2
    high_correlation_threshold: Decimal = Decimal("0.75")
    portfolio: PortfolioConfiguration = field(default_factory=PortfolioConfiguration)
    correlation: CorrelationConfiguration = field(default_factory=CorrelationConfiguration)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.configuration_snapshot_id.strip():
            errors.append("P44_CONFIGURATION_ID_REQUIRED")
        if min(
            self.maximum_snapshots,
            self.maximum_candidate_risk_assessments,
            self.maximum_correlation_snapshots,
            self.maximum_conflicts,
            self.maximum_simultaneous_research_candidates,
            self.maximum_same_instrument_candidates,
            self.maximum_same_strategy_family_candidates,
            self.maximum_correlated_cluster_members,
        ) < 1:
            errors.append("P44_BOUNDS_INVALID")
        try:
            share = _decimal(self.maximum_same_direction_share)
            corr = _decimal(self.high_correlation_threshold)
            if not Decimal("0") <= share <= Decimal("1"):
                errors.append("P44_DIRECTION_SHARE_INVALID")
            if not Decimal("0") <= corr <= Decimal("1"):
                errors.append("P44_CORRELATION_THRESHOLD_INVALID")
        except ValueError:
            errors.append("P44_NUMERICAL_INVALID")
        errors.extend(f"P44_PORTFOLIO_{item}" for item in self.portfolio.validate())
        errors.extend(f"P44_CORRELATION_{item}" for item in self.correlation.validate())
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class CandidatePortfolioContext:
    candidate_id: str
    scored_candidate_id: str
    instrument_id: str
    strategy_id: str
    strategy_version: str
    strategy_family: str
    strategy_variant: str | None
    research_direction: str
    dataset_id: str
    dataset_fingerprint: str
    timeframe: str
    market_intelligence_snapshot_id: str
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    context_fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        scored_candidate_id: str,
        instrument_id: str,
        strategy_id: str,
        strategy_version: str,
        strategy_family: str,
        research_direction: str,
        dataset_id: str,
        dataset_fingerprint: str,
        timeframe: str,
        market_intelligence_snapshot_id: str,
        knowledge_cutoff_utc: datetime,
        configuration_identity: str,
        recovery_epoch: int,
        strategy_variant: str | None = None,
    ) -> "CandidatePortfolioContext":
        fingerprint = _sha256_json(
            {
                "candidate_id": candidate_id,
                "scored_candidate_id": scored_candidate_id,
                "instrument_id": instrument_id,
                "strategy_id": strategy_id,
                "strategy_version": strategy_version,
                "strategy_family": strategy_family,
                "strategy_variant": strategy_variant,
                "research_direction": research_direction,
                "dataset_id": dataset_id,
                "dataset_fingerprint": dataset_fingerprint,
                "timeframe": timeframe,
                "market_intelligence_snapshot_id": market_intelligence_snapshot_id,
                "knowledge_cutoff": knowledge_cutoff_utc,
                "configuration_identity": configuration_identity,
                "recovery_epoch": recovery_epoch,
            }
        )
        return cls(candidate_id, scored_candidate_id, instrument_id, strategy_id, strategy_version, strategy_family, strategy_variant, research_direction, dataset_id, dataset_fingerprint, timeframe, market_intelligence_snapshot_id, knowledge_cutoff_utc, configuration_identity, recovery_epoch, fingerprint)


@dataclass(frozen=True)
class CandidateResearchRiskAssessment:
    assessment_id: str
    schema_version: str
    schema_identity: str
    candidate_id: str
    scored_candidate_id: str
    risk_state: str
    research_weight: Decimal
    restrictions: tuple[str, ...]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    interaction_evidence_ids: tuple[str, ...]
    correlation_evidence_ids: tuple[str, ...]
    concentration_evidence_ids: tuple[str, ...]
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    fingerprint: str


@dataclass(frozen=True)
class PortfolioResearchState:
    portfolio_state_id: str
    schema_version: str
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    dataset_id: str
    dataset_fingerprint: str
    instrument_universe: tuple[str, ...]
    strategy_universe: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    research_weights: tuple[tuple[str, Decimal], ...]
    instrument_interactions: tuple[Mapping[str, Any], ...]
    strategy_interactions: tuple[Mapping[str, Any], ...]
    concentration_context: tuple[Mapping[str, Any], ...]
    diversification_context: tuple[Mapping[str, Any], ...]
    capacity_context: Mapping[str, Any]
    restrictions: tuple[str, ...]
    warnings: tuple[str, ...]
    configuration_identity: str
    recovery_epoch: int
    state_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrument_interactions", tuple(MappingProxyType(dict(item)) for item in self.instrument_interactions))
        object.__setattr__(self, "strategy_interactions", tuple(MappingProxyType(dict(item)) for item in self.strategy_interactions))
        object.__setattr__(self, "concentration_context", tuple(MappingProxyType(dict(item)) for item in self.concentration_context))
        object.__setattr__(self, "diversification_context", tuple(MappingProxyType(dict(item)) for item in self.diversification_context))
        object.__setattr__(self, "capacity_context", MappingProxyType(dict(self.capacity_context)))


@dataclass(frozen=True)
class CorrelationResearchSnapshot:
    snapshot_id: str
    schema_version: str
    schema_identity: str
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    instrument_set: tuple[str, ...]
    method: str
    window: int
    minimum_samples: int
    missing_data_policy: str
    precision: str
    pairwise_evidence: tuple[Mapping[str, Any], ...]
    health: str
    restrictions: tuple[str, ...]
    warnings: tuple[str, ...]
    configuration_identity: str
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "pairwise_evidence", tuple(MappingProxyType(dict(item)) for item in self.pairwise_evidence))


@dataclass(frozen=True)
class PortfolioConflict:
    conflict_id: str
    conflict_type: str
    candidate_ids: tuple[str, ...]
    severity: str
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    configuration_identity: str


@dataclass(frozen=True)
class AggregateRestriction:
    restriction_id: str
    source_component: str
    source_evidence_id: str
    severity: str
    reason_code: str
    knowledge_cutoff_utc: datetime
    configuration_identity: str


@dataclass(frozen=True)
class PortfolioResearchSnapshot:
    portfolio_snapshot_id: str
    schema_version: str
    schema_identity: str
    p43_assessment_id: str
    p43_assessment_fingerprint: str
    as_of_timestamp_utc: datetime
    knowledge_cutoff_utc: datetime
    portfolio_state_id: str
    correlation_snapshot_id: str
    candidate_risk_assessments: tuple[CandidateResearchRiskAssessment, ...]
    instrument_interactions: tuple[Mapping[str, Any], ...]
    strategy_interactions: tuple[Mapping[str, Any], ...]
    concentration_evidence: tuple[Mapping[str, Any], ...]
    diversification_evidence: tuple[Mapping[str, Any], ...]
    capacity_evidence: Mapping[str, Any]
    portfolio_conflicts: tuple[PortfolioConflict, ...]
    aggregate_restrictions: tuple[AggregateRestriction, ...]
    warnings: tuple[str, ...]
    portfolio_research_state: str
    reason_codes: tuple[str, ...]
    configuration_identity: str
    recovery_epoch: int
    snapshot_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrument_interactions", tuple(MappingProxyType(dict(item)) for item in self.instrument_interactions))
        object.__setattr__(self, "strategy_interactions", tuple(MappingProxyType(dict(item)) for item in self.strategy_interactions))
        object.__setattr__(self, "concentration_evidence", tuple(MappingProxyType(dict(item)) for item in self.concentration_evidence))
        object.__setattr__(self, "diversification_evidence", tuple(MappingProxyType(dict(item)) for item in self.diversification_evidence))
        object.__setattr__(self, "capacity_evidence", MappingProxyType(dict(self.capacity_evidence)))


@dataclass(frozen=True)
class ResearchPortfolioRuntimeResult:
    acceptance: PortfolioResearchAcceptance
    snapshot: PortfolioResearchSnapshot | None
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchPortfolioRecoveryState:
    schema_version: str
    runtime_version: str
    p43_schema_identity: str
    candidate_risk_schema_identity: str
    correlation_schema_identity: str
    portfolio_snapshot_schema_identity: str
    configuration_identity: str
    risk_policy_identity: str
    portfolio_policy_identity: str
    correlation_policy_identity: str
    recovery_epoch: int
    processed_p43_assessment_ids: tuple[str, ...]
    snapshots: tuple[PortfolioResearchSnapshot, ...]


class ResearchPortfolioRuntime:
    def __init__(
        self,
        configuration: ResearchPortfolioRuntimeConfiguration = ResearchPortfolioRuntimeConfiguration(),
        *,
        clock: Any,
        audit: Any,
        correlation_engine: CorrelationDependencyEngine | None = None,
    ) -> None:
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.clock = clock
        self.audit = audit
        self.correlation_engine = correlation_engine or CorrelationDependencyEngine(configuration.correlation, audit=audit)
        self.candidate_risk: OrderedDict[str, CandidateResearchRiskAssessment] = OrderedDict()
        self.correlation_snapshots: OrderedDict[str, CorrelationResearchSnapshot] = OrderedDict()
        self.snapshots: OrderedDict[str, PortfolioResearchSnapshot] = OrderedDict()
        self.conflicts: OrderedDict[str, PortfolioConflict] = OrderedDict()
        self._processed_p43_assessment_ids: set[str] = set()
        self.recovery_restricted = False
        self.metrics = {
            "p43_assessments_received": 0,
            "candidates_risk_assessed": 0,
            "candidate_restrictions": 0,
            "portfolio_conflicts": 0,
            "correlation_restrictions": 0,
            "concentration_restrictions": 0,
            "capacity_restrictions": 0,
            "portfolio_no_action": 0,
            "unavailable_portfolio_contexts": 0,
            "recovery_divergence": 0,
        }

    @property
    def configuration_identity(self) -> str:
        return self.configuration.configuration_snapshot_id

    def assess(
        self,
        assessment: ResearchArbitrationAssessment,
        candidate_contexts: tuple[CandidatePortfolioContext, ...] = (),
        return_series_by_instrument: Mapping[str, ReturnSeries] | None = None,
    ) -> ResearchPortfolioRuntimeResult:
        self.metrics["p43_assessments_received"] += 1
        boundary = self._validate_input(assessment, candidate_contexts)
        if assessment.assessment_id in self._processed_p43_assessment_ids:
            existing = next((item for item in self.snapshots.values() if item.p43_assessment_id == assessment.assessment_id), None)
            return ResearchPortfolioRuntimeResult(PortfolioResearchAcceptance.DUPLICATE, existing, ("P44_DUPLICATE_P43_ASSESSMENT",))
        if boundary:
            self._record("portfolio_runtime_restricted", {"assessment_id": assessment.assessment_id, "reasons": boundary})
            return ResearchPortfolioRuntimeResult(PortfolioResearchAcceptance.BLOCKED, None, boundary)

        context_by_candidate = {item.candidate_id: item for item in candidate_contexts}
        scored = tuple(assessment.scored_candidates)
        weights = self._weights(scored)
        candidate_risk = tuple(self._candidate_risk(item, context_by_candidate.get(item.candidate_id), assessment, weights.get(item.candidate_id, Decimal("0"))) for item in scored)
        for item in candidate_risk:
            self.candidate_risk[item.assessment_id] = item
        self.metrics["candidates_risk_assessed"] += len(candidate_risk)
        self.metrics["candidate_restrictions"] += sum(1 for item in candidate_risk if item.restrictions)

        portfolio_state = self._portfolio_state(assessment, candidate_contexts, weights)
        correlation_snapshot = self._correlation_snapshot(assessment, candidate_contexts, return_series_by_instrument or {})
        conflicts = self._portfolio_conflicts(assessment, candidate_contexts, correlation_snapshot)
        restrictions = self._aggregate_restrictions(assessment, candidate_risk, correlation_snapshot, conflicts)
        state = self._state(assessment, candidate_risk, conflicts, restrictions, scored)
        if state == PortfolioResearchStateValue.NO_ACTION.value:
            self.metrics["portfolio_no_action"] += 1
            self._record("portfolio_no_action", {"assessment_id": assessment.assessment_id})
        self.metrics["portfolio_conflicts"] += len(conflicts)
        self.metrics["correlation_restrictions"] += sum(1 for item in restrictions if item.source_component == "correlation")
        self.metrics["concentration_restrictions"] += sum(1 for item in restrictions if item.source_component == "concentration")
        self.metrics["capacity_restrictions"] += sum(1 for item in restrictions if item.source_component == "capacity")
        self.metrics["unavailable_portfolio_contexts"] += sum(1 for item in candidate_risk if "P44_CONTEXT_UNAVAILABLE" in item.reason_codes)

        snapshot = self._snapshot(assessment, portfolio_state, correlation_snapshot, candidate_risk, conflicts, restrictions, state)
        self.correlation_snapshots[correlation_snapshot.snapshot_id] = correlation_snapshot
        self.snapshots[snapshot.portfolio_snapshot_id] = snapshot
        self._processed_p43_assessment_ids.add(assessment.assessment_id)
        self._bound()
        self._record("portfolio_research_snapshot_published", {"snapshot_id": snapshot.portfolio_snapshot_id, "state": state})
        return ResearchPortfolioRuntimeResult(PortfolioResearchAcceptance.ACCEPTED, snapshot, snapshot.reason_codes)

    def recovery_state(self, recovery_epoch: int) -> ResearchPortfolioRecoveryState:
        return ResearchPortfolioRecoveryState(
            PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
            RESEARCH_PORTFOLIO_RUNTIME_VERSION,
            research_arbitration_assessment_schema_identity(),
            candidate_research_risk_schema_identity(),
            correlation_research_schema_identity(),
            portfolio_research_snapshot_schema_identity(),
            self.configuration_identity,
            self._risk_policy_identity(),
            self._portfolio_policy_identity(),
            self._correlation_policy_identity(),
            recovery_epoch,
            tuple(sorted(self._processed_p43_assessment_ids)),
            tuple(self.snapshots.values()),
        )

    def restore(self, state: ResearchPortfolioRecoveryState, expected_recovery_epoch: int) -> bool:
        if (
            state.schema_version != PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION
            or state.runtime_version != RESEARCH_PORTFOLIO_RUNTIME_VERSION
            or state.p43_schema_identity != research_arbitration_assessment_schema_identity()
            or state.candidate_risk_schema_identity != candidate_research_risk_schema_identity()
            or state.correlation_schema_identity != correlation_research_schema_identity()
            or state.portfolio_snapshot_schema_identity != portfolio_research_snapshot_schema_identity()
            or state.configuration_identity != self.configuration_identity
            or state.risk_policy_identity != self._risk_policy_identity()
            or state.portfolio_policy_identity != self._portfolio_policy_identity()
            or state.correlation_policy_identity != self._correlation_policy_identity()
            or state.recovery_epoch != expected_recovery_epoch
        ):
            self.recovery_restricted = True
            self.metrics["recovery_divergence"] += 1
            return False
        self._processed_p43_assessment_ids = set(state.processed_p43_assessment_ids)
        self.snapshots = OrderedDict((item.portfolio_snapshot_id, item) for item in state.snapshots)
        self.candidate_risk = OrderedDict((risk.assessment_id, risk) for item in state.snapshots for risk in item.candidate_risk_assessments)
        self.conflicts = OrderedDict((conflict.conflict_id, conflict) for item in state.snapshots for conflict in item.portfolio_conflicts)
        self.recovery_restricted = False
        self._bound()
        self._record("portfolio_runtime_recovered", {"snapshots": len(self.snapshots)})
        return True

    def reconcile(self, recovery_epoch: int) -> tuple[str, ...]:
        issues: list[str] = []
        if self.recovery_restricted:
            issues.append("P44_RECOVERY_RESTRICTED")
        if any(item.recovery_epoch > recovery_epoch for item in self.snapshots.values()):
            issues.append("P44_RECOVERY_EPOCH_REGRESSION")
        return tuple(dict.fromkeys(issues))

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.snapshots.values()), None) if self.snapshots else None
        return {
            "runtime_version": RESEARCH_PORTFOLIO_RUNTIME_VERSION,
            "candidate_risk_schema_version": CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION,
            "candidate_risk_schema_identity": candidate_research_risk_schema_identity(),
            "correlation_schema_version": CORRELATION_RESEARCH_SCHEMA_VERSION,
            "correlation_schema_identity": correlation_research_schema_identity(),
            "portfolio_snapshot_schema_version": PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
            "portfolio_snapshot_schema_identity": portfolio_research_snapshot_schema_identity(),
            "p43_assessment_schema_identity": research_arbitration_assessment_schema_identity(),
            "configuration_identity": self.configuration_identity,
            "risk_policy": {"policy_id": "P44_RESEARCH_RISK_POLICY", "version": "1.0", "configuration_identity": self.configuration_identity},
            "portfolio_policy": {"policy_id": "P44_PORTFOLIO_RESEARCH_POLICY", "version": PORTFOLIO_ENGINE_VERSION, "configuration_identity": self.configuration.portfolio.configuration_snapshot_id},
            "correlation_policy": {"policy_id": "P44_CORRELATION_RESEARCH_POLICY", "version": CORRELATION_ENGINE_VERSION, "configuration_identity": self.configuration.correlation.configuration_snapshot_id},
            "correlation_method": {
                "method": self.configuration.correlation.method.name,
                "window": self.configuration.correlation.lookback_observations,
                "minimum_samples": self.configuration.correlation.minimum_observations,
                "missing_data_policy": self.configuration.correlation.missing_data_policy.name,
                "precision": "12 decimal rounded Pearson",
            },
            "latest_snapshot": _snapshot_summary(latest),
            "metrics": dict(self.metrics),
            "recovery_restricted": self.recovery_restricted,
            "financial_execution": "NONE",
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted and not self.configuration.validate()

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.DEGRADED if self.recovery_restricted else HealthStatus.HEALTHY

    def _validate_input(self, assessment: ResearchArbitrationAssessment, contexts: tuple[CandidatePortfolioContext, ...]) -> tuple[str, ...]:
        reasons: list[str] = []
        if assessment.schema_identity != research_arbitration_assessment_schema_identity():
            reasons.append("P44_P43_ASSESSMENT_SCHEMA_MISMATCH")
        if assessment.schema_version != RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION:
            reasons.append("P44_P43_ASSESSMENT_SCHEMA_VERSION_MISMATCH")
        expected = deterministic_id("p43_research_arbitration_assessment", assessment.assessment_fingerprint)
        if assessment.assessment_id != expected:
            reasons.append("P44_P43_ASSESSMENT_IDENTITY_MISMATCH")
        if not getattr(assessment, "__dataclass_params__", None) or not assessment.__dataclass_params__.frozen:
            reasons.append("P44_P43_ASSESSMENT_NOT_IMMUTABLE")
        scored_ids = {item.scored_candidate_id for item in assessment.scored_candidates}
        candidate_ids = {item.candidate_id for item in assessment.scored_candidates}
        if len(scored_ids) != len(assessment.scored_candidates) or len(candidate_ids) != len(assessment.scored_candidates):
            reasons.append("P44_P43_ASSESSMENT_DUPLICATE_CANDIDATE")
        context_candidate_ids = [item.candidate_id for item in contexts]
        context_scored_ids = [item.scored_candidate_id for item in contexts]
        if len(set(context_candidate_ids)) != len(context_candidate_ids) or len(set(context_scored_ids)) != len(context_scored_ids):
            reasons.append("P44_CONTEXT_DUPLICATE_CANDIDATE")
        if len({item.dataset_id for item in contexts}) > 1 or len({item.dataset_fingerprint for item in contexts}) > 1:
            reasons.append("P44_CONTEXT_DATASET_MISMATCH")
        if len({item.timeframe for item in contexts}) > 1:
            reasons.append("P44_CONTEXT_TIMEFRAME_MISMATCH")
        for scored in assessment.scored_candidates:
            if scored.schema_identity != scored_research_candidate_schema_identity():
                reasons.append("P44_P43_SCORED_CANDIDATE_SCHEMA_MISMATCH")
            if scored.knowledge_cutoff_utc != assessment.knowledge_cutoff_utc:
                reasons.append("P44_KNOWLEDGE_CUTOFF_MISMATCH")
            if scored.recovery_epoch != assessment.recovery_epoch:
                reasons.append("P44_RECOVERY_EPOCH_MISMATCH")
        for context in contexts:
            if context.candidate_id not in candidate_ids or context.scored_candidate_id not in scored_ids:
                reasons.append("P44_CONTEXT_LINEAGE_MISMATCH")
            if context.knowledge_cutoff_utc != assessment.knowledge_cutoff_utc:
                reasons.append("P44_CONTEXT_KNOWLEDGE_CUTOFF_MISMATCH")
            if context.configuration_identity != assessment.configuration_identity:
                reasons.append("P44_CONTEXT_CONFIGURATION_MISMATCH")
            if context.recovery_epoch != assessment.recovery_epoch:
                reasons.append("P44_CONTEXT_RECOVERY_EPOCH_MISMATCH")
        return tuple(dict.fromkeys(reasons))

    def _candidate_risk(self, scored: ScoredResearchCandidate, context: CandidatePortfolioContext | None, assessment: ResearchArbitrationAssessment, weight: Decimal) -> CandidateResearchRiskAssessment:
        restrictions = list(scored.restrictions)
        reasons = ["P44_CANDIDATE_RISK_ASSESSED", "RESEARCH_RISK_ACCEPTABLE_NOT_AUTHORIZATION", "RESEARCH_WEIGHT_NOT_POSITION_SIZE"]
        if context is None:
            restrictions.append("P44_CONTEXT_UNAVAILABLE")
            reasons.append("P44_CONTEXT_UNAVAILABLE")
        if scored.threshold_state != "PASS":
            restrictions.append(scored.threshold_state)
            reasons.append("P44_SCORE_THRESHOLD_RESTRICTED")
        if assessment.arbitration_state in {"NO_ELIGIBLE_CANDIDATE", "CONFLICT", "TIE", "RESTRICTED", "REJECTED", "INCOMPARABLE", "NO_SELECTION"}:
            restrictions.append(f"P43_{assessment.arbitration_state}")
            reasons.append("P44_UPSTREAM_P43_RESTRICTED")
        state = CandidateRiskState.ACCEPTABLE.value
        if "P44_CONTEXT_UNAVAILABLE" in restrictions:
            state = CandidateRiskState.UNAVAILABLE.value
        elif scored.threshold_state != "PASS":
            state = CandidateRiskState.BLOCKED.value
        elif restrictions:
            state = CandidateRiskState.RESTRICTED.value
        fingerprint = _sha256_json(
            {
                "scored_candidate_id": scored.scored_candidate_id,
                "candidate_id": scored.candidate_id,
                "restrictions": tuple(sorted(set(restrictions))),
                "weight": str(weight),
                "configuration_identity": self.configuration_identity,
                "knowledge_cutoff": assessment.knowledge_cutoff_utc,
                "recovery_epoch": assessment.recovery_epoch,
            }
        )
        return CandidateResearchRiskAssessment(
            deterministic_id("p44_candidate_research_risk", fingerprint),
            CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION,
            candidate_research_risk_schema_identity(),
            scored.candidate_id,
            scored.scored_candidate_id,
            state,
            weight,
            tuple(sorted(set(restrictions))),
            scored.warnings,
            tuple(dict.fromkeys(reasons)),
            (),
            (),
            (),
            assessment.knowledge_cutoff_utc,
            self.configuration_identity,
            assessment.recovery_epoch,
            fingerprint,
        )

    def _portfolio_state(self, assessment: ResearchArbitrationAssessment, contexts: tuple[CandidatePortfolioContext, ...], weights: Mapping[str, Decimal]) -> PortfolioResearchState:
        by_candidate = {item.candidate_id: item for item in contexts}
        instruments = tuple(sorted({item.instrument_id for item in contexts}))
        strategies = tuple(sorted({item.strategy_id for item in contexts}))
        dataset_id = next((item.dataset_id for item in contexts), "UNKNOWN")
        dataset_fingerprint = next((item.dataset_fingerprint for item in contexts), "UNKNOWN")
        instrument_interactions = self._instrument_interactions(contexts)
        strategy_interactions = self._strategy_interactions(contexts)
        concentration = self._concentration(contexts)
        diversification = self._diversification(contexts)
        capacity = {
            "candidate_count": len(assessment.scored_candidates),
            "maximum_simultaneous_research_candidates": self.configuration.maximum_simultaneous_research_candidates,
            "within_capacity": len(assessment.scored_candidates) <= self.configuration.maximum_simultaneous_research_candidates,
            "semantics": "RESEARCH_CAPACITY_NOT_BROKER_BUYING_POWER",
        }
        restrictions = []
        if not contexts and assessment.scored_candidates:
            restrictions.append("PORTFOLIO_CONTEXT_UNAVAILABLE")
        elif len(by_candidate) != len(assessment.scored_candidates):
            restrictions.append("PORTFOLIO_CONTEXT_PARTIAL")
        if not capacity["within_capacity"]:
            restrictions.append("PORTFOLIO_CAPACITY_RESTRICTED")
        warnings = []
        if not contexts and assessment.scored_candidates:
            warnings.append("P44_CONTEXT_MISSING")
        elif len(by_candidate) != len(assessment.scored_candidates):
            warnings.append("P44_CONTEXT_PARTIAL")
        fingerprint = _sha256_json(
            {
                "assessment_id": assessment.assessment_id,
                "contexts": tuple(item.context_fingerprint for item in contexts),
                "weights": tuple((key, str(value)) for key, value in sorted(weights.items())),
                "correlation_policy": self._correlation_policy_identity(),
                "configuration_identity": self.configuration_identity,
            }
        )
        return PortfolioResearchState(
            deterministic_id("p44_portfolio_research_state", fingerprint),
            PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
            assessment.knowledge_cutoff_utc,
            assessment.knowledge_cutoff_utc,
            dataset_id,
            dataset_fingerprint,
            instruments,
            strategies,
            tuple(item.candidate_id for item in assessment.scored_candidates),
            tuple(sorted((candidate_id, value) for candidate_id, value in weights.items())),
            instrument_interactions,
            strategy_interactions,
            concentration,
            diversification,
            capacity,
            tuple(sorted(set(restrictions))),
            tuple(sorted(set(warnings))),
            self.configuration_identity,
            assessment.recovery_epoch,
            fingerprint,
        )

    def _correlation_snapshot(self, assessment: ResearchArbitrationAssessment, contexts: tuple[CandidatePortfolioContext, ...], series_by_instrument: Mapping[str, ReturnSeries]) -> CorrelationResearchSnapshot:
        pairwise: list[Mapping[str, Any]] = []
        restrictions: list[str] = []
        by_instrument = {item.instrument_id: item for item in contexts}
        directions = {item.instrument_id: _research_direction(item.research_direction) for item in contexts}
        instruments = tuple(sorted(by_instrument))
        for index, left in enumerate(instruments):
            for right in instruments[index + 1 :]:
                a = series_by_instrument.get(left)
                b = series_by_instrument.get(right)
                if a is None or b is None:
                    record = self.correlation_engine._missing_pair(left, right)
                else:
                    record = self.correlation_engine.pair(a, b, directions[left], directions[right], assessment.knowledge_cutoff_utc)
                evidence = {
                    "pair_id": record.pair_id,
                    "instrument_a": record.instrument_a,
                    "instrument_b": record.instrument_b,
                    "correlation": str(record.correlation) if record.correlation is not None else None,
                    "adjusted_dependency": str(record.adjusted_dependency) if record.adjusted_dependency is not None else None,
                    "aligned_observations": record.aligned_observations,
                    "state": record.state.name,
                    "strength": record.strength.name,
                    "health": record.health.name,
                    "reason_codes": record.reason_codes,
                }
                pairwise.append(evidence)
                if record.health is not CorrelationHealth.HEALTHY:
                    restrictions.append(f"CORRELATION_{record.health.name}")
                elif record.adjusted_dependency is not None and record.adjusted_dependency >= self.configuration.high_correlation_threshold:
                    restrictions.append("CORRELATION_CLUSTER_RESTRICTION")
        health = "HEALTHY" if not restrictions else "PARTIAL"
        fingerprint = _sha256_json(
            {
                "assessment_id": assessment.assessment_id,
                "instruments": instruments,
                "pairs": pairwise,
                "configuration_identity": self.configuration.correlation.configuration_snapshot_id,
                "knowledge_cutoff": assessment.knowledge_cutoff_utc,
            }
        )
        return CorrelationResearchSnapshot(
            deterministic_id("p44_correlation_research_snapshot", fingerprint),
            CORRELATION_RESEARCH_SCHEMA_VERSION,
            correlation_research_schema_identity(),
            assessment.knowledge_cutoff_utc,
            assessment.knowledge_cutoff_utc,
            instruments,
            self.configuration.correlation.method.name,
            self.configuration.correlation.lookback_observations,
            self.configuration.correlation.minimum_observations,
            self.configuration.correlation.missing_data_policy.name,
            "12 decimal rounded Pearson",
            tuple(pairwise),
            health,
            tuple(sorted(set(restrictions))),
            (),
            self.configuration_identity,
            fingerprint,
        )

    def _portfolio_conflicts(self, assessment: ResearchArbitrationAssessment, contexts: tuple[CandidatePortfolioContext, ...], correlation: CorrelationResearchSnapshot) -> tuple[PortfolioConflict, ...]:
        conflicts: list[PortfolioConflict] = []
        by_instrument: dict[str, list[CandidatePortfolioContext]] = {}
        by_family: dict[str, list[CandidatePortfolioContext]] = {}
        for context in contexts:
            by_instrument.setdefault(context.instrument_id, []).append(context)
            by_family.setdefault(context.strategy_family, []).append(context)
        for instrument, items in sorted(by_instrument.items()):
            directions = {item.research_direction for item in items}
            if len(items) > self.configuration.maximum_same_instrument_candidates:
                conflicts.append(self._conflict(PortfolioConflictType.CONCENTRATION_CONFLICT, tuple(item.candidate_id for item in items), "HIGH", ("PORTFOLIO_SAME_INSTRUMENT_CONCENTRATION",)))
            if len(directions) > 1:
                conflicts.append(self._conflict(PortfolioConflictType.DIRECTIONAL_CONFLICT, tuple(item.candidate_id for item in items), "HIGH", ("PORTFOLIO_SAME_INSTRUMENT_OPPOSING_DIRECTION",)))
            elif len(items) > 1:
                conflicts.append(self._conflict(PortfolioConflictType.HYPOTHESIS_OVERLAP, tuple(item.candidate_id for item in items), "MEDIUM", ("PORTFOLIO_SAME_INSTRUMENT_HYPOTHESIS_OVERLAP",)))
        for family, items in sorted(by_family.items()):
            if len(items) > self.configuration.maximum_same_strategy_family_candidates:
                conflicts.append(self._conflict(PortfolioConflictType.STRATEGY_FAMILY_CONFLICT, tuple(item.candidate_id for item in items), "MEDIUM", ("PORTFOLIO_STRATEGY_FAMILY_CONCENTRATION",)))
        direction_counts = Counter(item.research_direction for item in contexts)
        if contexts:
            dominant, count = max(direction_counts.items(), key=lambda item: (item[1], item[0]))
            share = Decimal(count) / Decimal(len(contexts))
            if share > self.configuration.maximum_same_direction_share and len(contexts) > 1:
                involved = tuple(item.candidate_id for item in contexts if item.research_direction == dominant)
                conflicts.append(self._conflict(PortfolioConflictType.CONCENTRATION_CONFLICT, involved, "MEDIUM", ("PORTFOLIO_DIRECTION_CONCENTRATION",)))
        if len(assessment.scored_candidates) > self.configuration.maximum_simultaneous_research_candidates:
            conflicts.append(self._conflict(PortfolioConflictType.CAPACITY_CONFLICT, tuple(item.candidate_id for item in assessment.scored_candidates), "HIGH", ("PORTFOLIO_CAPACITY_RESTRICTED",)))
        for pair in correlation.pairwise_evidence:
            dep = pair.get("adjusted_dependency")
            if dep is not None and _decimal(dep) >= self.configuration.high_correlation_threshold:
                involved = tuple(item.candidate_id for item in contexts if item.instrument_id in {pair["instrument_a"], pair["instrument_b"]})
                conflicts.append(self._conflict(PortfolioConflictType.CORRELATION_CONFLICT, involved, "MEDIUM", ("PORTFOLIO_CORRELATION_CLUSTER",), (pair["pair_id"],)))
        for conflict in conflicts:
            self.conflicts[conflict.conflict_id] = conflict
            self._record("portfolio_conflict_detected", {"conflict_id": conflict.conflict_id, "type": conflict.conflict_type})
        return tuple(conflicts)

    def _aggregate_restrictions(self, assessment: ResearchArbitrationAssessment, risks: tuple[CandidateResearchRiskAssessment, ...], correlation: CorrelationResearchSnapshot, conflicts: tuple[PortfolioConflict, ...]) -> tuple[AggregateRestriction, ...]:
        items: list[AggregateRestriction] = []
        for reason in assessment.restrictions:
            items.append(self._restriction("p43", assessment.assessment_id, "HIGH", reason, assessment.knowledge_cutoff_utc))
        for risk in risks:
            for reason in risk.restrictions:
                items.append(self._restriction("candidate_risk", risk.assessment_id, "HIGH" if "BLOCK" in reason or "UNAVAILABLE" in reason else "MEDIUM", reason, risk.knowledge_cutoff_utc))
        for reason in correlation.restrictions:
            items.append(self._restriction("correlation", correlation.snapshot_id, "MEDIUM", reason, correlation.knowledge_cutoff_utc))
        for conflict in conflicts:
            source = "capacity" if conflict.conflict_type == PortfolioConflictType.CAPACITY_CONFLICT.value else "concentration" if conflict.conflict_type in {PortfolioConflictType.CONCENTRATION_CONFLICT.value, PortfolioConflictType.STRATEGY_FAMILY_CONFLICT.value} else "portfolio_conflict"
            items.append(self._restriction(source, conflict.conflict_id, conflict.severity, conflict.reason_codes[0], assessment.knowledge_cutoff_utc))
            self._record("aggregate_restriction_created", {"restriction_id": items[-1].restriction_id, "reason": items[-1].reason_code})
        return tuple(sorted({item.restriction_id: item for item in items}.values(), key=lambda item: (-SEVERITY_ORDER.get(item.severity, 0), item.source_component, item.reason_code, item.restriction_id)))

    def _snapshot(self, assessment: ResearchArbitrationAssessment, state: PortfolioResearchState, correlation: CorrelationResearchSnapshot, risks: tuple[CandidateResearchRiskAssessment, ...], conflicts: tuple[PortfolioConflict, ...], restrictions: tuple[AggregateRestriction, ...], value: str) -> PortfolioResearchSnapshot:
        reason_codes = tuple(dict.fromkeys((*assessment.reason_codes, *(item.reason_code for item in restrictions), value, "PORTFOLIO_COMPATIBLE_NOT_CAPITAL_ALLOCATION")))
        fingerprint = _sha256_json(
            {
                "p43_assessment_id": assessment.assessment_id,
                "p43_fingerprint": assessment.assessment_fingerprint,
                "portfolio_state": state.state_fingerprint,
                "correlation": correlation.fingerprint,
                "risk": tuple(item.fingerprint for item in risks),
                "conflicts": tuple(item.conflict_id for item in conflicts),
                "restrictions": tuple(item.restriction_id for item in restrictions),
                "configuration_identity": self.configuration_identity,
                "recovery_epoch": assessment.recovery_epoch,
            }
        )
        return PortfolioResearchSnapshot(
            deterministic_id("p44_portfolio_research_snapshot", fingerprint),
            PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
            portfolio_research_snapshot_schema_identity(),
            assessment.assessment_id,
            assessment.assessment_fingerprint,
            assessment.knowledge_cutoff_utc,
            assessment.knowledge_cutoff_utc,
            state.portfolio_state_id,
            correlation.snapshot_id,
            risks,
            state.instrument_interactions,
            state.strategy_interactions,
            state.concentration_context,
            state.diversification_context,
            state.capacity_context,
            conflicts,
            restrictions,
            tuple(sorted(set((*assessment.warnings, *correlation.warnings)))),
            value,
            reason_codes,
            self.configuration_identity,
            assessment.recovery_epoch,
            fingerprint,
        )

    def _state(self, assessment: ResearchArbitrationAssessment, risks: tuple[CandidateResearchRiskAssessment, ...], conflicts: tuple[PortfolioConflict, ...], restrictions: tuple[AggregateRestriction, ...], scored: tuple[ScoredResearchCandidate, ...]) -> str:
        if not scored or assessment.arbitration_state in {"NO_ELIGIBLE_CANDIDATE", "NO_SELECTION"}:
            return PortfolioResearchStateValue.NO_ACTION.value
        if any(risk.risk_state in {CandidateRiskState.UNAVAILABLE.value, CandidateRiskState.INVALID.value} for risk in risks):
            return PortfolioResearchStateValue.UNAVAILABLE.value
        if conflicts or restrictions or assessment.arbitration_state in {"CONFLICT", "TIE", "RESTRICTED", "REJECTED", "INCOMPARABLE"}:
            return PortfolioResearchStateValue.RESTRICTED.value
        return PortfolioResearchStateValue.ACCEPTABLE.value

    def _weights(self, scored: tuple[ScoredResearchCandidate, ...]) -> dict[str, Decimal]:
        if not scored:
            return {}
        weight = Decimal("1") / Decimal(len(scored))
        return {item.candidate_id: weight for item in scored}

    def _instrument_interactions(self, contexts: tuple[CandidatePortfolioContext, ...]) -> tuple[Mapping[str, Any], ...]:
        out = []
        for instrument, count in sorted(Counter(item.instrument_id for item in contexts).items()):
            directions = tuple(sorted({item.research_direction for item in contexts if item.instrument_id == instrument}))
            out.append({"instrument_id": instrument, "candidate_count": count, "directions": directions, "same_instrument": count > 1})
        return tuple(out)

    def _strategy_interactions(self, contexts: tuple[CandidatePortfolioContext, ...]) -> tuple[Mapping[str, Any], ...]:
        out = []
        for family, count in sorted(Counter(item.strategy_family for item in contexts).items()):
            variants = tuple(sorted({item.strategy_variant or "NONE" for item in contexts if item.strategy_family == family}))
            out.append({"strategy_family": family, "candidate_count": count, "variants": variants, "family_concentration": count > self.configuration.maximum_same_strategy_family_candidates})
        return tuple(out)

    def _concentration(self, contexts: tuple[CandidatePortfolioContext, ...]) -> tuple[Mapping[str, Any], ...]:
        return (
            {"dimension": "instrument", "counts": tuple(sorted(Counter(item.instrument_id for item in contexts).items())), "limit": self.configuration.maximum_same_instrument_candidates},
            {"dimension": "strategy_family", "counts": tuple(sorted(Counter(item.strategy_family for item in contexts).items())), "limit": self.configuration.maximum_same_strategy_family_candidates},
            {"dimension": "direction", "counts": tuple(sorted(Counter(item.research_direction for item in contexts).items())), "maximum_share": str(self.configuration.maximum_same_direction_share)},
        )

    def _diversification(self, contexts: tuple[CandidatePortfolioContext, ...]) -> tuple[Mapping[str, Any], ...]:
        instruments = {item.instrument_id for item in contexts}
        families = {item.strategy_family for item in contexts}
        return (
            {"dimension": "instrument", "count": len(instruments), "quality": "UNKNOWN" if not contexts else "SINGLE_INSTRUMENT" if len(instruments) == 1 else "MULTI_INSTRUMENT_REQUIRES_CORRELATION"},
            {"dimension": "strategy_family", "count": len(families), "quality": "UNKNOWN" if not contexts else "SINGLE_FAMILY" if len(families) == 1 else "MULTI_FAMILY"},
        )

    def _conflict(self, kind: PortfolioConflictType, candidate_ids: tuple[str, ...], severity: str, reasons: tuple[str, ...], evidence_ids: tuple[str, ...] = ()) -> PortfolioConflict:
        cid = deterministic_id("p44_portfolio_conflict", kind.value, *sorted(candidate_ids), severity, *reasons, *evidence_ids, self.configuration_identity)
        return PortfolioConflict(cid, kind.value, tuple(sorted(candidate_ids)), severity, reasons, evidence_ids, self.configuration_identity)

    def _restriction(self, source: str, evidence_id: str, severity: str, reason: str, cutoff: datetime) -> AggregateRestriction:
        rid = deterministic_id("p44_aggregate_restriction", source, evidence_id, severity, reason, cutoff.isoformat(), self.configuration_identity)
        return AggregateRestriction(rid, source, evidence_id, severity, reason, cutoff, self.configuration_identity)

    def _risk_policy_identity(self) -> str:
        return deterministic_id("p44_research_risk_policy", "1.0", self.configuration_identity)

    def _portfolio_policy_identity(self) -> str:
        return deterministic_id("p44_portfolio_policy", PORTFOLIO_ENGINE_VERSION, self.configuration.portfolio.configuration_snapshot_id, self.configuration_identity)

    def _correlation_policy_identity(self) -> str:
        return deterministic_id("p44_correlation_policy", CORRELATION_ENGINE_VERSION, self.configuration.correlation.configuration_snapshot_id, self.configuration_identity)

    def _bound(self) -> None:
        for store, limit in (
            (self.candidate_risk, self.configuration.maximum_candidate_risk_assessments),
            (self.correlation_snapshots, self.configuration.maximum_correlation_snapshots),
            (self.snapshots, self.configuration.maximum_snapshots),
            (self.conflicts, self.configuration.maximum_conflicts),
        ):
            while len(store) > limit:
                store.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class ResearchPortfolioRuntimeComponent:
    def __init__(self, component_id: str, runtime_holder: dict[str, ResearchPortfolioRuntime] | None = None) -> None:
        self.component_id = component_id
        self.runtime: ResearchPortfolioRuntime | None = None
        self._runtime_holder = runtime_holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                self.runtime = ResearchPortfolioRuntime(clock=context.services["clock"], audit=context.services["audit"])
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record("research_risk_runtime_initialized", {"component_id": self.component_id, "portfolio_snapshot_schema_identity": portfolio_research_snapshot_schema_identity()})

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def research_portfolio_component_registrations() -> tuple[tuple[ComponentMetadata, ResearchPortfolioRuntimeComponent], ...]:
    holder: dict[str, ResearchPortfolioRuntime] = {}
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    definitions = (
        ("research_risk", ("post_scoring_research_assessment",)),
        ("portfolio_context", ("research_risk",)),
        ("correlation_analysis", ("portfolio_context",)),
        ("concentration_analysis", ("correlation_analysis",)),
        ("portfolio_restrictions", ("concentration_analysis",)),
        ("portfolio_research_snapshot", ("portfolio_restrictions",)),
    )
    return tuple(
        (
            ComponentMetadata(component_id, ComponentType.RESEARCH, RESEARCH_PORTFOLIO_RUNTIME_VERSION, True, dependencies, capabilities),
            ResearchPortfolioRuntimeComponent(component_id, holder),
        )
        for component_id, dependencies in definitions
    )


def research_portfolio_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"research_risk", "portfolio_context", "correlation_analysis", "concentration_analysis", "portfolio_restrictions", "portfolio_research_snapshot"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def candidate_research_risk_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p44_candidate_research_risk",
            "version": CANDIDATE_RESEARCH_RISK_SCHEMA_VERSION,
            "fields": tuple(CandidateResearchRiskAssessment.__dataclass_fields__),
            "upstream": {"p43_scored_candidate": scored_research_candidate_schema_identity()},
        }
    )


def correlation_research_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p44_correlation_research_snapshot",
            "version": CORRELATION_RESEARCH_SCHEMA_VERSION,
            "fields": tuple(CorrelationResearchSnapshot.__dataclass_fields__),
            "engine_version": CORRELATION_ENGINE_VERSION,
        }
    )


def portfolio_research_snapshot_schema_identity() -> str:
    return _sha256_json(
        {
            "schema": "p44_portfolio_research_snapshot",
            "version": PORTFOLIO_RESEARCH_SNAPSHOT_SCHEMA_VERSION,
            "fields": tuple(PortfolioResearchSnapshot.__dataclass_fields__),
            "candidate_risk_schema_identity": candidate_research_risk_schema_identity(),
            "correlation_schema_identity": correlation_research_schema_identity(),
            "upstream": {"p43_assessment": research_arbitration_assessment_schema_identity()},
        }
    )


def _research_direction(value: str):
    from amrte.risk.invalidation import ResearchDirection

    normalized = value.strip().upper()
    if normalized in {"BEARISH", "SHORT", "SHORT_BIAS", "SELL"}:
        return ResearchDirection.BEARISH
    if normalized in {"BULLISH", "LONG", "LONG_BIAS", "BUY"}:
        return ResearchDirection.BULLISH
    return ResearchDirection.BULLISH


def _snapshot_summary(item: PortfolioResearchSnapshot | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "portfolio_snapshot_id": item.portfolio_snapshot_id,
        "snapshot_fingerprint": item.snapshot_fingerprint,
        "p43_assessment_id": item.p43_assessment_id,
        "portfolio_research_state": item.portfolio_research_state,
        "candidate_risk_assessment_ids": [risk.assessment_id for risk in item.candidate_risk_assessments],
        "conflict_ids": [conflict.conflict_id for conflict in item.portfolio_conflicts],
        "restriction_ids": [restriction.restriction_id for restriction in item.aggregate_restrictions],
        "financial_execution": "NONE",
    }


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(nested) for key, nested in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return {field: _jsonable(getattr(value, field)) for field in value.__dataclass_fields__}
    return value
