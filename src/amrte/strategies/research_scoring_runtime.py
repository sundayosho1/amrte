from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from itertools import combinations
from types import MappingProxyType
from typing import Any, Mapping

from amrte.core.composition import ComponentCapabilities, ComponentMetadata, ComponentType
from amrte.core.identity import deterministic_id
from amrte.core.observability import DecisionTraceBuilder
from amrte.core.observability_types import DecisionOutcome, DecisionStatus
from amrte.core.types import HealthStatus
from amrte.market.intelligence import MarketIntelligenceSnapshot
from amrte.strategies.evaluation_runtime import (
    RESEARCH_CANDIDATE_SCHEMA_VERSION,
    STRATEGY_EVALUATION_SET_SCHEMA_VERSION,
    ResearchCandidate,
    StrategyEvaluationSet,
    default_strategy_registry,
    research_candidate_schema_identity,
    strategy_evaluation_set_schema_identity,
)
from amrte.strategies.framework import (
    ApplicabilityState,
    CandidateStatus,
    CapabilityStatus,
    DetectionResult,
    DetectionState,
    EvaluationOutcome,
    EvaluationReason,
    EvidenceAvailability,
    EvidenceCategory,
    EvidenceSource,
    FinalResearchAction,
    GateStatus,
    QualificationResult,
    QualificationState,
    ResearchSignal,
    ScoreHealth,
    SignalCandidate,
    SignalDirection,
    SignalEvidence,
    SignalScore,
    StrategyApplicability,
    StrategyDecision,
    StrategyEvaluation,
    StrategyEvaluationContext,
    StrategyFamily,
    StrategyFrameworkConfiguration,
    StrategyHealth,
    StrategyReadiness,
    StrategyRegistry,
)
from amrte.strategies.scoring import (
    SCORING_ENGINE_VERSION,
    SCORING_SCHEMA_VERSION,
    CentralSignalScorer,
    ScoringConfiguration,
)
from amrte.strategies.strategy_arbitration import (
    ARBITRATION_ENGINE_VERSION,
    ARBITRATION_SCHEMA_VERSION,
    ArbitrationConfiguration,
    ArbitrationOutcome,
    ArbitrationResult,
    CompatibilityState,
    ConflictType,
    StrategyArbitrationEngine,
)


RESEARCH_SCORING_RUNTIME_VERSION = "1.0"
SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION = "1.0"
RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION = "1.0"


class ResearchScoringAcceptance(Enum):
    ACCEPTED = "ACCEPTED"
    BLOCKED = "BLOCKED"
    DUPLICATE = "DUPLICATE"
    RESTRICTED = "RESTRICTED"


class CandidateComparability(Enum):
    COMPARABLE = "COMPARABLE"
    INCOMPARABLE = "INCOMPARABLE"


class ResearchArbitrationState(Enum):
    NO_ELIGIBLE_CANDIDATE = "NO_ELIGIBLE_CANDIDATE"
    SINGLE_RESEARCH_CANDIDATE = "SINGLE_RESEARCH_CANDIDATE"
    MULTIPLE_COMPATIBLE_CANDIDATES = "MULTIPLE_COMPATIBLE_CANDIDATES"
    CONFLICT = "CONFLICT"
    TIE = "TIE"
    RESTRICTED = "RESTRICTED"
    REJECTED = "REJECTED"
    INCOMPARABLE = "INCOMPARABLE"
    NO_SELECTION = "NO_SELECTION"


@dataclass(frozen=True)
class ResearchScoringRuntimeConfiguration:
    configuration_snapshot_id: str = "P43_RESEARCH_SCORING_DEFAULT"
    maximum_scored_candidates: int = 4096
    maximum_assessments: int = 1024
    maximum_diagnostics: int = 512
    scoring: ScoringConfiguration = field(default_factory=ScoringConfiguration)
    arbitration: ArbitrationConfiguration = field(default_factory=ArbitrationConfiguration)

    def validate(self) -> tuple[str, ...]:
        errors: list[str] = []
        if not self.configuration_snapshot_id.strip():
            errors.append("P43_CONFIGURATION_ID_REQUIRED")
        if min(self.maximum_scored_candidates, self.maximum_assessments, self.maximum_diagnostics) < 1:
            errors.append("P43_BOUNDS_INVALID")
        errors.extend(f"P43_SCORING_{item}" for item in self.scoring.validate())
        errors.extend(f"P43_ARBITRATION_{item}" for item in self.arbitration.validate())
        return tuple(dict.fromkeys(errors))


@dataclass(frozen=True)
class ScoredResearchCandidate:
    scored_candidate_id: str
    schema_version: str
    schema_identity: str
    candidate_id: str
    candidate_fingerprint: str
    source_signal_candidate_id: str
    strategy_id: str
    strategy_version: str
    scoring_model_id: str
    scoring_model_version: str
    raw_score: float
    normalized_score: float | None
    component_scores: Mapping[str, float]
    factor_scores: tuple[Mapping[str, Any], ...]
    threshold_state: str
    quality_state: str
    comparability_key: tuple[str, ...]
    restrictions: tuple[str, ...]
    warnings: tuple[str, ...]
    reason_codes: tuple[str, ...]
    knowledge_cutoff_utc: datetime
    configuration_identity: str
    recovery_epoch: int
    source_score_id: str
    score_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "component_scores", MappingProxyType(dict(self.component_scores)))
        object.__setattr__(self, "factor_scores", tuple(MappingProxyType(dict(item)) for item in self.factor_scores))


@dataclass(frozen=True)
class CandidateComparison:
    comparison_id: str
    candidate_a_id: str
    candidate_b_id: str
    score_a_id: str | None
    score_b_id: str | None
    comparability: CandidateComparability
    ordering: tuple[str, ...]
    tie: bool
    reason_codes: tuple[str, ...]
    configuration_identity: str


@dataclass(frozen=True)
class ResearchConflict:
    conflict_id: str
    candidate_ids: tuple[str, ...]
    conflict_types: tuple[str, ...]
    severity: str
    reason_codes: tuple[str, ...]
    resolution_state: str
    configuration_identity: str


@dataclass(frozen=True)
class ResearchArbitrationAssessment:
    assessment_id: str
    schema_version: str
    schema_identity: str
    strategy_evaluation_set_id: str
    market_intelligence_snapshot_id: str
    scored_candidates: tuple[ScoredResearchCandidate, ...]
    candidate_comparisons: tuple[CandidateComparison, ...]
    conflicts: tuple[ResearchConflict, ...]
    ties: tuple[CandidateComparison, ...]
    arbitration_state: str
    selected_research_candidate_id: str | None
    rejected_candidate_ids: tuple[str, ...]
    deferred_candidate_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    restrictions: tuple[str, ...]
    warnings: tuple[str, ...]
    scoring_policy_identity: str
    arbitration_policy_identity: str
    configuration_identity: str
    knowledge_cutoff_utc: datetime
    recovery_epoch: int
    assessment_fingerprint: str


@dataclass(frozen=True)
class ResearchScoringRuntimeResult:
    acceptance: ResearchScoringAcceptance
    assessment: ResearchArbitrationAssessment | None
    reason_codes: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchScoringRecoveryState:
    schema_version: str
    runtime_version: str
    p42_evaluation_schema_identity: str
    scoring_schema_identity: str
    assessment_schema_identity: str
    configuration_identity: str
    scoring_configuration_identity: str
    arbitration_configuration_identity: str
    recovery_epoch: int
    processed_evaluation_set_ids: tuple[str, ...]
    assessments: tuple[ResearchArbitrationAssessment, ...]
    scorer_state: Mapping[str, Any]
    arbitration_state: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "scorer_state", MappingProxyType(dict(self.scorer_state)))
        object.__setattr__(self, "arbitration_state", MappingProxyType(dict(self.arbitration_state)))


class ResearchScoringRuntime:
    """Prompt 43 central research scoring and arbitration-evidence runtime."""

    def __init__(
        self,
        configuration: ResearchScoringRuntimeConfiguration = ResearchScoringRuntimeConfiguration(),
        *,
        clock: Any,
        audit: Any,
        registry: StrategyRegistry | None = None,
        scorer: CentralSignalScorer | None = None,
        arbitration: StrategyArbitrationEngine | None = None,
    ) -> None:
        errors = configuration.validate()
        if errors:
            raise ValueError(";".join(errors))
        self.configuration = configuration
        self.clock = clock
        self.audit = audit
        self.registry = registry or default_strategy_registry(audit)
        self.scorer = scorer or CentralSignalScorer(
            configuration=configuration.scoring,
            audit=audit,
            strategy_families={
                strategy.metadata.identity.strategy_id: strategy.metadata.identity.family
                for strategy in self.registry.all()
            },
        )
        self.arbitration = arbitration or StrategyArbitrationEngine(configuration.arbitration, audit)
        self.scored_candidates: OrderedDict[str, ScoredResearchCandidate] = OrderedDict()
        self.assessments: OrderedDict[str, ResearchArbitrationAssessment] = OrderedDict()
        self._processed_evaluation_set_ids: set[str] = set()
        self.recovery_restricted = False
        self.metrics: dict[str, int] = {
            "evaluation_sets_received": 0,
            "candidates_received": 0,
            "candidates_scored": 0,
            "candidates_restricted": 0,
            "scores_below_threshold": 0,
            "conflicts_detected": 0,
            "ties_detected": 0,
            "arbitrations_completed": 0,
            "arbitrations_deferred": 0,
            "no_selection_outcomes": 0,
            "scoring_failures": 0,
            "arbitration_failures": 0,
        }

    @property
    def configuration_identity(self) -> str:
        return self.configuration.configuration_snapshot_id

    def assess(
        self,
        evaluation_set: StrategyEvaluationSet,
        market_intelligence: MarketIntelligenceSnapshot,
    ) -> ResearchScoringRuntimeResult:
        self.metrics["evaluation_sets_received"] += 1
        self.metrics["candidates_received"] += len(evaluation_set.candidates)
        boundary = self._validate_input(evaluation_set, market_intelligence)
        if evaluation_set.evaluation_set_id in self._processed_evaluation_set_ids:
            existing = self.assessments.get(evaluation_set.evaluation_set_id)
            if existing is None:
                existing = next(
                    (item for item in self.assessments.values() if item.strategy_evaluation_set_id == evaluation_set.evaluation_set_id),
                    None,
                )
            return ResearchScoringRuntimeResult(
                ResearchScoringAcceptance.DUPLICATE,
                existing,
                ("P43_DUPLICATE_EVALUATION_SET",),
            )
        if boundary:
            self._record("central_scoring_restricted", {"evaluation_set_id": evaluation_set.evaluation_set_id, "reasons": boundary})
            return ResearchScoringRuntimeResult(ResearchScoringAcceptance.BLOCKED, None, boundary)

        scored: list[ScoredResearchCandidate] = []
        source_evaluations: list[StrategyEvaluation] = []
        restrictions = set(market_intelligence.restrictions)
        warnings = set(evaluation_set.error_outcomes)
        reason_codes: list[str] = []

        for candidate in evaluation_set.candidates:
            result = self._score_candidate(evaluation_set, candidate, market_intelligence)
            if result is None:
                self.metrics["scoring_failures"] += 1
                reason_codes.append("P43_CANDIDATE_SCORING_FAILED")
                continue
            scored_candidate, source_evaluation = result
            scored.append(scored_candidate)
            source_evaluations.append(source_evaluation)
            self.scored_candidates[scored_candidate.scored_candidate_id] = scored_candidate
            self.metrics["candidates_scored"] += 1
            if scored_candidate.restrictions:
                self.metrics["candidates_restricted"] += 1
                restrictions.update(scored_candidate.restrictions)
            if scored_candidate.threshold_state != "PASS":
                self.metrics["scores_below_threshold"] += 1

        comparisons = self._comparisons(tuple(scored))
        ties = tuple(item for item in comparisons if item.tie)
        self.metrics["ties_detected"] += len(ties)
        arbitration_result = self._arbitrate(market_intelligence, tuple(source_evaluations))
        conflicts = self._conflicts(arbitration_result, tuple(scored))
        self.metrics["conflicts_detected"] += len(conflicts)
        state = self._arbitration_state(arbitration_result, comparisons, conflicts, ties, scored)
        if state in {ResearchArbitrationState.NO_SELECTION.value, ResearchArbitrationState.CONFLICT.value, ResearchArbitrationState.TIE.value, ResearchArbitrationState.INCOMPARABLE.value}:
            self.metrics["no_selection_outcomes"] += 1
        if state in {ResearchArbitrationState.NO_SELECTION.value, ResearchArbitrationState.RESTRICTED.value}:
            self.metrics["arbitrations_deferred"] += 1
        self.metrics["arbitrations_completed"] += 1

        selected = self._selected_candidate_id(arbitration_result, tuple(scored))
        rejected = self._rejected_candidate_ids(arbitration_result, tuple(scored))
        deferred = tuple(
            item.candidate_id
            for item in scored
            if item.candidate_id not in rejected and item.candidate_id != selected and state in {ResearchArbitrationState.NO_SELECTION.value, ResearchArbitrationState.CONFLICT.value, ResearchArbitrationState.TIE.value}
        )
        reason_codes.extend(evaluation_set.no_candidate_outcomes)
        reason_codes.extend(evaluation_set.restricted_outcomes)
        reason_codes.extend(arbitration_result.decision.reason_codes if arbitration_result is not None else ("P43_ARBITRATION_UNAVAILABLE",))
        reason_codes.extend(("HIGH_SCORE_IS_NOT_AUTHORIZATION", "RANK1_IS_NOT_AUTHORIZATION", "POST_SCORING_RESEARCH_ONLY"))

        assessment = self._assessment(
            evaluation_set,
            tuple(scored),
            comparisons,
            conflicts,
            ties,
            state,
            selected,
            rejected,
            deferred,
            tuple(sorted(set(reason_codes))),
            tuple(sorted(restrictions)),
            tuple(sorted(warnings)),
        )
        self.assessments[assessment.assessment_id] = assessment
        self._processed_evaluation_set_ids.add(evaluation_set.evaluation_set_id)
        self._bound()
        self._record(
            "post_scoring_assessment_published",
            {
                "assessment_id": assessment.assessment_id,
                "arbitration_state": assessment.arbitration_state,
                "scored_candidates": len(scored),
            },
        )
        return ResearchScoringRuntimeResult(ResearchScoringAcceptance.ACCEPTED, assessment, assessment.reason_codes)

    def recovery_state(self, recovery_epoch: int) -> ResearchScoringRecoveryState:
        return ResearchScoringRecoveryState(
            RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
            RESEARCH_SCORING_RUNTIME_VERSION,
            strategy_evaluation_set_schema_identity(),
            scored_research_candidate_schema_identity(),
            research_arbitration_assessment_schema_identity(),
            self.configuration_identity,
            self.configuration.scoring.configuration_snapshot_id,
            self.configuration.arbitration.configuration_snapshot_id,
            recovery_epoch,
            tuple(sorted(self._processed_evaluation_set_ids)),
            tuple(self.assessments.values()),
            self.scorer.recovery_state(),
            self.arbitration.recovery_state(),
        )

    def restore(self, state: ResearchScoringRecoveryState, expected_recovery_epoch: int) -> bool:
        if (
            state.schema_version != RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION
            or state.runtime_version != RESEARCH_SCORING_RUNTIME_VERSION
            or state.p42_evaluation_schema_identity != strategy_evaluation_set_schema_identity()
            or state.scoring_schema_identity != scored_research_candidate_schema_identity()
            or state.assessment_schema_identity != research_arbitration_assessment_schema_identity()
            or state.configuration_identity != self.configuration_identity
            or state.scoring_configuration_identity != self.configuration.scoring.configuration_snapshot_id
            or state.arbitration_configuration_identity != self.configuration.arbitration.configuration_snapshot_id
            or state.recovery_epoch != expected_recovery_epoch
        ):
            self.recovery_restricted = True
            return False
        if not self.scorer.validate_recovery(state.scorer_state) or not self.arbitration.validate_recovery(state.arbitration_state):
            self.recovery_restricted = True
            return False
        self._processed_evaluation_set_ids = set(state.processed_evaluation_set_ids)
        self.assessments = OrderedDict((item.assessment_id, item) for item in state.assessments)
        self.scored_candidates = OrderedDict(
            (candidate.scored_candidate_id, candidate)
            for item in state.assessments
            for candidate in item.scored_candidates
        )
        self.recovery_restricted = False
        self._bound()
        return True

    def reconcile(self, recovery_epoch: int) -> tuple[str, ...]:
        issues: list[str] = []
        if self.recovery_restricted:
            issues.append("P43_RECOVERY_RESTRICTED")
        if any(item.recovery_epoch > recovery_epoch for item in self.assessments.values()):
            issues.append("P43_RECOVERY_EPOCH_REGRESSION")
        return tuple(dict.fromkeys(issues))

    def diagnostics(self) -> dict[str, Any]:
        latest = next(reversed(self.assessments.values()), None) if self.assessments else None
        return {
            "runtime_version": RESEARCH_SCORING_RUNTIME_VERSION,
            "scored_candidate_schema_version": SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION,
            "scored_candidate_schema_identity": scored_research_candidate_schema_identity(),
            "assessment_schema_version": RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
            "assessment_schema_identity": research_arbitration_assessment_schema_identity(),
            "p42_candidate_schema_identity": research_candidate_schema_identity(),
            "p42_evaluation_schema_identity": strategy_evaluation_set_schema_identity(),
            "configuration_identity": self.configuration_identity,
            "scoring_model": self._model_summary(),
            "normalization_policy": {"method": "MODEL_FACTOR_NORMALIZATION", "version": SCORING_SCHEMA_VERSION, "bounds": [0.0, 100.0]},
            "threshold_policy": {
                "scoring_minimum_completeness": self.configuration.scoring.minimum_completeness,
                "arbitration_minimum_confidence": self.configuration.arbitration.minimum_confidence,
                "arbitration_minimum_quality": self.configuration.arbitration.minimum_quality,
                "arbitration_minimum_completeness": self.configuration.arbitration.minimum_completeness,
                "arbitration_maximum_uncertainty": self.configuration.arbitration.maximum_uncertainty,
            },
            "arbitration_policy": {
                "policy": self.configuration.arbitration.policy.name,
                "version": self.configuration.arbitration.policy_version,
                "configuration_identity": self.configuration.arbitration.configuration_snapshot_id,
                "tie_tolerance": self.configuration.arbitration.tie_tolerance,
            },
            "latest_assessment": _assessment_summary(latest),
            "metrics": dict(self.metrics),
            "scored_candidate_count": len(self.scored_candidates),
            "assessment_count": len(self.assessments),
            "recovery_restricted": self.recovery_restricted,
            "financial_authorization": "NONE",
        }

    def component_ready(self, context: Any) -> bool:
        return not self.recovery_restricted and not self.configuration.validate()

    def component_health(self, context: Any) -> HealthStatus:
        return HealthStatus.DEGRADED if self.recovery_restricted else HealthStatus.HEALTHY

    def _validate_input(self, evaluation_set: StrategyEvaluationSet, intelligence: MarketIntelligenceSnapshot) -> tuple[str, ...]:
        reasons: list[str] = []
        if evaluation_set.evaluation_schema_identity != strategy_evaluation_set_schema_identity():
            reasons.append("P43_P42_EVALUATION_SCHEMA_MISMATCH")
        if evaluation_set.evaluation_schema_version != STRATEGY_EVALUATION_SET_SCHEMA_VERSION:
            reasons.append("P43_P42_EVALUATION_SCHEMA_VERSION_MISMATCH")
        if evaluation_set.scoring_active or evaluation_set.arbitration_active or evaluation_set.final_decision_active:
            reasons.append("P43_P42_DOWNSTREAM_ALREADY_ACTIVE")
        if evaluation_set.market_intelligence_snapshot_id != intelligence.market_intelligence_snapshot_id:
            reasons.append("P43_MARKET_INTELLIGENCE_LINEAGE_MISMATCH")
        if evaluation_set.dataset_id != intelligence.dataset_id or evaluation_set.dataset_fingerprint != intelligence.dataset_fingerprint:
            reasons.append("P43_DATASET_LINEAGE_MISMATCH")
        if evaluation_set.instrument_id != intelligence.instrument_id:
            reasons.append("P43_INSTRUMENT_LINEAGE_MISMATCH")
        if evaluation_set.recovery_epoch != intelligence.recovery_epoch:
            reasons.append("P43_RECOVERY_EPOCH_MISMATCH")
        for candidate in evaluation_set.candidates:
            reasons.extend(self._validate_candidate(evaluation_set, candidate))
        return tuple(dict.fromkeys(reasons))

    def _validate_candidate(self, evaluation_set: StrategyEvaluationSet, candidate: ResearchCandidate) -> tuple[str, ...]:
        reasons: list[str] = []
        if candidate.candidate_schema_identity != research_candidate_schema_identity():
            reasons.append("P43_P42_CANDIDATE_SCHEMA_MISMATCH")
        if candidate.candidate_schema_version != RESEARCH_CANDIDATE_SCHEMA_VERSION:
            reasons.append("P43_P42_CANDIDATE_SCHEMA_VERSION_MISMATCH")
        if candidate.market_intelligence_snapshot_id != evaluation_set.market_intelligence_snapshot_id:
            reasons.append("P43_CANDIDATE_EVALUATION_SET_LINEAGE_MISMATCH")
        if candidate.dataset_id != evaluation_set.dataset_id or candidate.dataset_fingerprint != evaluation_set.dataset_fingerprint:
            reasons.append("P43_CANDIDATE_DATASET_LINEAGE_MISMATCH")
        if candidate.instrument_id != evaluation_set.instrument_id:
            reasons.append("P43_CANDIDATE_INSTRUMENT_LINEAGE_MISMATCH")
        if candidate.knowledge_cutoff_utc != evaluation_set.knowledge_cutoff_utc:
            reasons.append("P43_KNOWLEDGE_CUTOFF_MISMATCH")
        if candidate.configuration_identity != evaluation_set.configuration_identity:
            reasons.append("P43_CANDIDATE_CONFIGURATION_MISMATCH")
        if candidate.recovery_epoch != evaluation_set.recovery_epoch:
            reasons.append("P43_CANDIDATE_RECOVERY_EPOCH_MISMATCH")
        if candidate.candidate_type not in {"QUALIFIED", "CONDITIONALLY_QUALIFIED"}:
            reasons.append("P43_CANDIDATE_STATUS_NOT_SCOREABLE")
        if not getattr(candidate, "__dataclass_params__", None) or not candidate.__dataclass_params__.frozen:
            reasons.append("P43_CANDIDATE_NOT_IMMUTABLE")
        expected = deterministic_id("p42_research_candidate", candidate.candidate_fingerprint)
        if candidate.candidate_id != expected:
            reasons.append("P43_CANDIDATE_IDENTITY_MISMATCH")
        try:
            registry_strategy = self.registry.get(candidate.strategy_id)
            if registry_strategy.metadata.identity.version != candidate.strategy_version:
                reasons.append("P43_STRATEGY_VERSION_MISMATCH")
        except KeyError:
            reasons.append("P43_STRATEGY_METADATA_UNAVAILABLE")
        return reasons

    def _score_candidate(
        self,
        evaluation_set: StrategyEvaluationSet,
        candidate: ResearchCandidate,
        intelligence: MarketIntelligenceSnapshot,
    ) -> tuple[ScoredResearchCandidate, StrategyEvaluation] | None:
        try:
            strategy = self.registry.get(candidate.strategy_id)
        except KeyError:
            return None
        context = StrategyEvaluationContext(
            deterministic_id("p43_score_context", evaluation_set.evaluation_set_id, candidate.candidate_id),
            candidate.strategy_id,
            candidate.instrument_id,
            evaluation_set.as_of_timestamp_utc,
            intelligence,
            candidate.configuration_identity,
            None,
            EvaluationReason.MANUAL_RESEARCH_EVALUATION,
            candidate.recovery_epoch,
        )
        detection = self._detection(context, candidate)
        qualification = QualificationResult(
            deterministic_id("p43_qualification", candidate.candidate_id),
            candidate.strategy_id,
            QualificationState.QUALIFIED if candidate.candidate_type == "QUALIFIED" else QualificationState.CONDITIONALLY_QUALIFIED,
            ("P42_CANDIDATE_STATUS",),
            (),
            ("P42_CONDITIONALLY_QUALIFIED",) if candidate.candidate_type == "CONDITIONALLY_QUALIFIED" else (),
            tuple(f"P42_MISSING:{item}" for item in candidate.missing_evidence_ids),
            (),
        )
        score = self.scorer.score(context, detection, qualification)
        threshold_state = self._threshold_state(score)
        restrictions = tuple(sorted(set((*intelligence.restrictions, *self._score_restrictions(score, threshold_state)))))
        reason_codes = tuple(sorted(set((*candidate.reason_codes, *score.explanation, threshold_state, "SCORED_CANDIDATE_NOT_AUTHORIZATION"))))
        fingerprint = _sha256_json(
            {
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "score_id": score.signal_score_id,
                "score_version_id": score.score_version_id,
                "model_id": score.scoring_model_id,
                "model_version": score.scoring_model_version,
                "configuration_identity": self.configuration_identity,
                "scoring_configuration_identity": score.configuration_snapshot_id,
                "knowledge_cutoff": candidate.knowledge_cutoff_utc,
                "recovery_epoch": candidate.recovery_epoch,
            }
        )
        scored = ScoredResearchCandidate(
            deterministic_id("p43_scored_research_candidate", fingerprint),
            SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION,
            scored_research_candidate_schema_identity(),
            candidate.candidate_id,
            candidate.candidate_fingerprint,
            candidate.source_signal_candidate_id,
            candidate.strategy_id,
            candidate.strategy_version,
            score.scoring_model_id,
            score.scoring_model_version,
            score.overall_score,
            score.overall_score,
            dict(score.component_scores),
            tuple(_factor_summary(item) for item in score.factor_scores),
            threshold_state,
            score.score_health.name,
            (score.scoring_model_id, score.scoring_model_version, score.configuration_snapshot_id, evaluation_set.evaluation_set_id),
            restrictions,
            score.warnings,
            reason_codes,
            candidate.knowledge_cutoff_utc,
            self.configuration_identity,
            candidate.recovery_epoch,
            score.signal_score_id,
            fingerprint,
        )
        source_evaluation = self._source_evaluation(context, candidate, strategy.metadata.identity.family, detection, qualification, score, scored, intelligence)
        self._record("candidate_scoring_completed", {"candidate_id": candidate.candidate_id, "scored_candidate_id": scored.scored_candidate_id, "threshold_state": threshold_state})
        return scored, source_evaluation

    def _detection(self, context: StrategyEvaluationContext, candidate: ResearchCandidate) -> DetectionResult:
        supporting = tuple(
            self._evidence(context, candidate, evidence_id, EvidenceCategory.SUPPORTING, EvidenceAvailability.AVAILABLE)
            for evidence_id in candidate.supporting_evidence_ids
        )
        conflicting = tuple(
            self._evidence(context, candidate, evidence_id, EvidenceCategory.CONFLICTING, EvidenceAvailability.AVAILABLE)
            for evidence_id in candidate.conflicting_evidence_ids
        )
        missing = tuple(
            self._evidence(context, candidate, evidence_id, EvidenceCategory.MISSING, EvidenceAvailability.UNAVAILABLE)
            for evidence_id in candidate.missing_evidence_ids
        )
        return DetectionResult(
            deterministic_id("p43_detection", candidate.candidate_id),
            candidate.strategy_id,
            candidate.instrument_id,
            context.as_of_timestamp_utc,
            DetectionState.DETECTED,
            supporting,
            missing,
            conflicting,
            candidate.market_intelligence_snapshot_id,
            candidate.configuration_identity,
        )

    def _evidence(
        self,
        context: StrategyEvaluationContext,
        candidate: ResearchCandidate,
        evidence_id: str,
        category: EvidenceCategory,
        availability: EvidenceAvailability,
    ) -> SignalEvidence:
        return SignalEvidence(
            evidence_id,
            f"P42_{category.name}_EVIDENCE",
            category,
            EvidenceSource.STRATEGY_DERIVED,
            candidate.market_intelligence_snapshot_id,
            candidate.instrument_id,
            candidate.timeframe,
            evidence_id if availability is EvidenceAvailability.AVAILABLE else None,
            "P42_RESEARCH_CANDIDATE_EVIDENCE",
            _direction(candidate.research_direction),
            50.0 if availability is EvidenceAvailability.AVAILABLE else None,
            availability,
            "P42_IMMUTABLE_EVIDENCE_REFERENCE",
            (candidate.candidate_id, context.evaluation_id),
        )

    def _source_evaluation(
        self,
        context: StrategyEvaluationContext,
        candidate: ResearchCandidate,
        family: StrategyFamily,
        detection: DetectionResult,
        qualification: QualificationResult,
        score: SignalScore,
        scored: ScoredResearchCandidate,
        intelligence: MarketIntelligenceSnapshot,
    ) -> StrategyEvaluation:
        status = CandidateStatus.QUALIFIED if candidate.candidate_type == "QUALIFIED" else CandidateStatus.CONDITIONALLY_QUALIFIED
        source_candidate = SignalCandidate(
            candidate.source_signal_candidate_id,
            deterministic_id("p43_logical_signal", candidate.candidate_id),
            deterministic_id("p43_signal_version", candidate.candidate_id, scored.scored_candidate_id),
            candidate.strategy_id,
            family,
            candidate.strategy_version,
            candidate.instrument_id,
            context.as_of_timestamp_utc,
            _direction(candidate.research_direction),
            detection.detection_id,
            qualification.qualification_id,
            score.signal_score_id,
            tuple(item for item in detection.evidence if item.category is EvidenceCategory.SUPPORTING),
            detection.conflicting_evidence,
            detection.missing_evidence,
            (),
            candidate.market_intelligence_snapshot_id,
            status,
            candidate.expires_at_utc,
            candidate.reason_codes,
            candidate.configuration_identity,
            candidate.recovery_epoch,
        )
        signal = ResearchSignal(
            candidate.source_research_signal_id or deterministic_id("p43_research_signal", candidate.candidate_id, scored.scored_candidate_id),
            source_candidate.logical_signal_id,
            source_candidate.signal_version_id,
            source_candidate.signal_candidate_id,
            candidate.strategy_id,
            family,
            candidate.instrument_id,
            context.as_of_timestamp_utc,
            source_candidate.direction,
            score.overall_score,
            score.confidence,
            score.quality,
            StrategyDecision.QUALIFIED_CANDIDATE,
            GateStatus.UNAVAILABLE,
            GateStatus.UNAVAILABLE,
            GateStatus.UNAVAILABLE,
            FinalResearchAction.RESEARCH_SIGNAL,
            tuple(sorted(set((*intelligence.restrictions, *scored.restrictions, "P43_RESEARCH_ONLY_NO_EXECUTION")))),
            ("P43_SCORED_RESEARCH_CANDIDATE", "HIGH_SCORE_IS_NOT_AUTHORIZATION"),
            candidate.market_intelligence_snapshot_id,
            self.configuration_identity,
            candidate.recovery_epoch,
        )
        trace = DecisionTraceBuilder(self.clock, deterministic_id("p43_decision", scored.scored_candidate_id), deterministic_id("p43_correlation", candidate.candidate_id))
        trace.evaluate("p42_candidate", DecisionStatus.PASSED, "P42_CANDIDATE_VALIDATED", "candidate was scored without strategy re-evaluation")
        decision_trace = trace.complete(DecisionOutcome.NO_ACTION, "P43 research scoring cannot authorize execution")
        health = StrategyHealth.HEALTHY if scored.threshold_state == "PASS" else StrategyHealth.RESTRICTED
        return StrategyEvaluation(
            context.evaluation_id,
            candidate.strategy_id,
            candidate.instrument_id,
            StrategyApplicability(
                deterministic_id("p43_applicability", candidate.candidate_id),
                candidate.strategy_id,
                ApplicabilityState.APPLICABLE,
                CapabilityStatus.SUPPORTED,
                ("P42_CANDIDATE_ALREADY_ELIGIBLE",),
                intelligence.restrictions,
            ),
            detection,
            qualification,
            score,
            source_candidate,
            signal,
            EvaluationOutcome.COMPLETED,
            FinalResearchAction.RESEARCH_SIGNAL,
            health,
            StrategyReadiness.READY_WITH_RESTRICTIONS if scored.restrictions else StrategyReadiness.READY,
            ("P43_SCORED_FROM_P42_CANDIDATE",),
            decision_trace,
        )

    def _comparisons(self, scored: tuple[ScoredResearchCandidate, ...]) -> tuple[CandidateComparison, ...]:
        comparisons: list[CandidateComparison] = []
        for a, b in combinations(scored, 2):
            comparable = a.comparability_key == b.comparability_key and a.quality_state not in {"UNAVAILABLE", "INVALID", "UNKNOWN"} and b.quality_state not in {"UNAVAILABLE", "INVALID", "UNKNOWN"}
            tie = comparable and abs((a.normalized_score or 0.0) - (b.normalized_score or 0.0)) <= self.configuration.arbitration.tie_tolerance
            if comparable:
                ordering = tuple(
                    item.candidate_id
                    for item in sorted((a, b), key=lambda item: (-(item.normalized_score or 0.0), item.strategy_id, item.strategy_version, item.candidate_id))
                )
                reasons = ("P43_COMPARABLE_SAME_MODEL_CONFIGURATION_CONTEXT", "P43_TIE_WITHIN_POLICY_TOLERANCE") if tie else ("P43_COMPARABLE_SAME_MODEL_CONFIGURATION_CONTEXT",)
            else:
                ordering = ()
                reasons = ("P43_INCOMPARABLE_SCORE_CONTEXT",)
            comparison = CandidateComparison(
                deterministic_id("p43_candidate_comparison", a.scored_candidate_id, b.scored_candidate_id, "TIE" if tie else "DISTINCT" if comparable else "INCOMPARABLE"),
                a.candidate_id,
                b.candidate_id,
                a.scored_candidate_id,
                b.scored_candidate_id,
                CandidateComparability.COMPARABLE if comparable else CandidateComparability.INCOMPARABLE,
                ordering,
                tie,
                reasons,
                self.configuration_identity,
            )
            comparisons.append(comparison)
        self._record("candidate_comparison_completed", {"comparisons": len(comparisons)})
        return tuple(comparisons)

    def _arbitrate(self, intelligence: MarketIntelligenceSnapshot, evaluations: tuple[StrategyEvaluation, ...]) -> ArbitrationResult | None:
        metadata = {strategy.metadata.identity.strategy_id: strategy.metadata for strategy in self.registry.all()}
        try:
            result = self.arbitration.arbitrate(intelligence, evaluations, metadata)
            self._record("strategy_arbitration_completed", {"decision_id": result.decision.decision_id, "outcome": result.decision.outcome.name})
            return result
        except Exception as exc:
            self.metrics["arbitration_failures"] += 1
            self._record("strategy_arbitration_failed", {"error": type(exc).__name__})
            return None

    def _conflicts(self, result: ArbitrationResult | None, scored: tuple[ScoredResearchCandidate, ...]) -> tuple[ResearchConflict, ...]:
        if result is None:
            return ()
        source_to_p42 = {item.source_signal_candidate_id: item.candidate_id for item in scored}
        candidate_by_opinion = {opinion.opinion_id: source_to_p42.get(opinion.candidate_id, opinion.candidate_id) for opinion in result.group.opinions}
        score_candidate_ids = {item.candidate_id for item in scored}
        conflicts: list[ResearchConflict] = []
        for conflict in result.conflicts:
            candidate_ids = tuple(candidate_by_opinion.get(item, item) for item in conflict.opinion_ids)
            filtered = tuple(item for item in candidate_ids if item in score_candidate_ids)
            conflict_item = ResearchConflict(
                deterministic_id("p43_research_conflict", conflict.conflict_id, *filtered),
                filtered,
                tuple(item.name for item in conflict.conflict_types),
                conflict.severity.name,
                tuple(dict.fromkeys((conflict.description_code, *conflict.resolution_reason_codes))),
                conflict.resolution_status.name,
                self.configuration_identity,
            )
            conflicts.append(conflict_item)
            self._record("candidate_conflict_detected", {"conflict_id": conflict_item.conflict_id, "types": conflict_item.conflict_types})
        return tuple(conflicts)

    def _arbitration_state(
        self,
        result: ArbitrationResult | None,
        comparisons: tuple[CandidateComparison, ...],
        conflicts: tuple[ResearchConflict, ...],
        ties: tuple[CandidateComparison, ...],
        scored: list[ScoredResearchCandidate],
    ) -> str:
        if result is None:
            return ResearchArbitrationState.RESTRICTED.value
        if any(item.comparability is CandidateComparability.INCOMPARABLE for item in comparisons):
            return ResearchArbitrationState.INCOMPARABLE.value
        if ties and result.decision.outcome is ArbitrationOutcome.NO_ACTION:
            return ResearchArbitrationState.TIE.value
        if conflicts and result.decision.outcome is ArbitrationOutcome.NO_ACTION:
            return ResearchArbitrationState.CONFLICT.value
        if result.decision.outcome is ArbitrationOutcome.ALL_REJECTED:
            return ResearchArbitrationState.NO_ELIGIBLE_CANDIDATE.value
        if result.decision.outcome is ArbitrationOutcome.BLOCKED:
            return ResearchArbitrationState.RESTRICTED.value
        if result.decision.outcome is ArbitrationOutcome.SINGLE_PREFERRED:
            return ResearchArbitrationState.SINGLE_RESEARCH_CANDIDATE.value if len(scored) == 1 else ResearchArbitrationState.CONFLICT.value if conflicts else ResearchArbitrationState.SINGLE_RESEARCH_CANDIDATE.value
        if result.decision.outcome is ArbitrationOutcome.MULTIPLE_COMPATIBLE:
            return ResearchArbitrationState.MULTIPLE_COMPATIBLE_CANDIDATES.value
        if result.decision.outcome is ArbitrationOutcome.NO_ACTION:
            return ResearchArbitrationState.NO_SELECTION.value
        return ResearchArbitrationState.REJECTED.value

    def _selected_candidate_id(self, result: ArbitrationResult | None, scored: tuple[ScoredResearchCandidate, ...]) -> str | None:
        if result is None or result.decision.preferred_opinion_id is None:
            return None
        opinion = next((item for item in result.group.opinions if item.opinion_id == result.decision.preferred_opinion_id), None)
        if opinion is None:
            return None
        return next((item.candidate_id for item in scored if item.source_signal_candidate_id == opinion.candidate_id), None)

    def _rejected_candidate_ids(self, result: ArbitrationResult | None, scored: tuple[ScoredResearchCandidate, ...]) -> tuple[str, ...]:
        if result is None:
            return tuple(item.candidate_id for item in scored)
        source_to_p42 = {item.source_signal_candidate_id: item.candidate_id for item in scored}
        opinion_by_strategy = {opinion.strategy_id: source_to_p42.get(opinion.candidate_id, opinion.candidate_id) for opinion in result.group.opinions}
        opinion_by_id = {opinion.opinion_id: source_to_p42.get(opinion.candidate_id, opinion.candidate_id) for opinion in result.group.opinions}
        rejected = {opinion_by_strategy[item] for item in result.decision.rejected_opinion_ids if item in opinion_by_strategy}
        rejected.update(opinion_by_id[item] for item in result.decision.suppressed_opinion_ids if item in opinion_by_id)
        return tuple(sorted(rejected))

    def _assessment(
        self,
        evaluation_set: StrategyEvaluationSet,
        scored: tuple[ScoredResearchCandidate, ...],
        comparisons: tuple[CandidateComparison, ...],
        conflicts: tuple[ResearchConflict, ...],
        ties: tuple[CandidateComparison, ...],
        state: str,
        selected: str | None,
        rejected: tuple[str, ...],
        deferred: tuple[str, ...],
        reason_codes: tuple[str, ...],
        restrictions: tuple[str, ...],
        warnings: tuple[str, ...],
    ) -> ResearchArbitrationAssessment:
        fingerprint = _sha256_json(
            {
                "evaluation_set_id": evaluation_set.evaluation_set_id,
                "evaluation_fingerprint": evaluation_set.evaluation_fingerprint,
                "scores": tuple(item.score_fingerprint for item in scored),
                "comparisons": tuple(item.comparison_id for item in comparisons),
                "conflicts": tuple(item.conflict_id for item in conflicts),
                "ties": tuple(item.comparison_id for item in ties),
                "state": state,
                "selected": selected,
                "rejected": rejected,
                "deferred": deferred,
                "scoring_policy": self._scoring_policy_identity(),
                "arbitration_policy": self._arbitration_policy_identity(),
                "configuration_identity": self.configuration_identity,
                "recovery_epoch": evaluation_set.recovery_epoch,
            }
        )
        return ResearchArbitrationAssessment(
            deterministic_id("p43_research_arbitration_assessment", fingerprint),
            RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
            research_arbitration_assessment_schema_identity(),
            evaluation_set.evaluation_set_id,
            evaluation_set.market_intelligence_snapshot_id,
            scored,
            comparisons,
            conflicts,
            ties,
            state,
            selected,
            rejected,
            deferred,
            reason_codes,
            restrictions,
            warnings,
            self._scoring_policy_identity(),
            self._arbitration_policy_identity(),
            self.configuration_identity,
            evaluation_set.knowledge_cutoff_utc,
            evaluation_set.recovery_epoch,
            fingerprint,
        )

    def _threshold_state(self, score: SignalScore) -> str:
        if score.score_health in (ScoreHealth.UNAVAILABLE, ScoreHealth.INVALID, ScoreHealth.UNKNOWN):
            return "RESTRICTED"
        if score.score_health is ScoreHealth.INCOMPLETE:
            return "BELOW_THRESHOLD"
        if score.completeness < self.configuration.scoring.minimum_completeness:
            return "BELOW_THRESHOLD"
        return "PASS"

    def _score_restrictions(self, score: SignalScore, threshold_state: str) -> tuple[str, ...]:
        restrictions: list[str] = []
        if threshold_state != "PASS":
            restrictions.append(threshold_state)
        if score.score_health in (ScoreHealth.DEGRADED, ScoreHealth.INCOMPLETE):
            restrictions.append(f"SCORE_HEALTH_{score.score_health.name}")
        return tuple(restrictions)

    def _scoring_policy_identity(self) -> str:
        return deterministic_id(
            "p43_scoring_policy",
            SCORING_ENGINE_VERSION,
            SCORING_SCHEMA_VERSION,
            self.configuration.scoring.configuration_snapshot_id,
        )

    def _arbitration_policy_identity(self) -> str:
        return deterministic_id(
            "p43_arbitration_policy",
            ARBITRATION_ENGINE_VERSION,
            ARBITRATION_SCHEMA_VERSION,
            self.configuration.arbitration.policy.name,
            self.configuration.arbitration.policy_version,
            self.configuration.arbitration.configuration_snapshot_id,
        )

    def _model_summary(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "model_id": model.scoring_model_id,
                "model_version": model.scoring_model_version,
                "score_scale": "0-100",
                "strategy_family": model.strategy_family.name,
                "configuration_identity": model.configuration_hash,
                "factors": [
                    {
                        "factor_id": factor.factor_id,
                        "group": factor.group.name,
                        "weight": factor.weight,
                        "requirement": factor.requirement.name,
                        "normalization": factor.normalization.method.name,
                    }
                    for factor in model.factors
                ],
            }
            for model in self.scorer.registry.all()
        )

    def _bound(self) -> None:
        while len(self.scored_candidates) > self.configuration.maximum_scored_candidates:
            self.scored_candidates.popitem(last=False)
        while len(self.assessments) > self.configuration.maximum_assessments:
            self.assessments.popitem(last=False)

    def _record(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.audit is not None:
            self.audit.record(event, payload)


class ResearchScoringRuntimeComponent:
    def __init__(self, component_id: str, runtime_holder: dict[str, ResearchScoringRuntime] | None = None) -> None:
        self.component_id = component_id
        self.runtime: ResearchScoringRuntime | None = None
        self._runtime_holder = runtime_holder

    def initialize_component(self, context: Any) -> None:
        if self.runtime is None:
            if self._runtime_holder is not None and "runtime" in self._runtime_holder:
                self.runtime = self._runtime_holder["runtime"]
            else:
                self.runtime = ResearchScoringRuntime(clock=context.services["clock"], audit=context.services["audit"])
                if self._runtime_holder is not None:
                    self._runtime_holder["runtime"] = self.runtime
        audit = context.services.get("audit") if hasattr(context, "services") else None
        if audit is not None:
            audit.record(
                "central_scoring_runtime_initialized",
                {
                    "component_id": self.component_id,
                    "scored_candidate_schema_identity": scored_research_candidate_schema_identity(),
                    "assessment_schema_identity": research_arbitration_assessment_schema_identity(),
                },
            )

    def component_ready(self, context: Any) -> bool:
        return self.runtime is not None and self.runtime.component_ready(context)

    def component_health(self, context: Any) -> HealthStatus:
        return self.runtime.component_health(context) if self.runtime is not None else HealthStatus.UNKNOWN

    def diagnostics(self) -> dict[str, Any]:
        payload = self.runtime.diagnostics() if self.runtime is not None else {}
        payload["component_id"] = self.component_id
        return payload


def research_scoring_component_registrations() -> tuple[tuple[ComponentMetadata, ResearchScoringRuntimeComponent], ...]:
    holder: dict[str, ResearchScoringRuntime] = {}
    capabilities = ComponentCapabilities(lifecycle=True, persistence=True, recovery=True, health=True, diagnostics=True, activation=True)
    definitions = (
        ("central_scoring", ("research_candidate_runtime", "strategy_evaluation")),
        ("candidate_comparison", ("central_scoring",)),
        ("strategy_arbitration", ("candidate_comparison",)),
        ("post_scoring_research_assessment", ("strategy_arbitration",)),
    )
    return tuple(
        (
            ComponentMetadata(component_id, ComponentType.RESEARCH, RESEARCH_SCORING_RUNTIME_VERSION, True, dependencies, capabilities),
            ResearchScoringRuntimeComponent(component_id, holder),
        )
        for component_id, dependencies in definitions
    )


def research_scoring_components_from_inventory(inventory: tuple[Mapping[str, Any], ...]) -> dict[str, Mapping[str, Any]]:
    ids = {"central_scoring", "candidate_comparison", "strategy_arbitration", "post_scoring_research_assessment"}
    return {item["component_id"]: item for item in inventory if item.get("component_id") in ids}


def scored_research_candidate_schema_identity() -> str:
    payload = {
        "schema": "p43_scored_research_candidate",
        "version": SCORED_RESEARCH_CANDIDATE_SCHEMA_VERSION,
        "fields": tuple(ScoredResearchCandidate.__dataclass_fields__),
        "upstream": {
            "p42_research_candidate": research_candidate_schema_identity(),
            "p42_strategy_evaluation_set": strategy_evaluation_set_schema_identity(),
        },
        "scoring_engine_version": SCORING_ENGINE_VERSION,
        "scoring_schema_version": SCORING_SCHEMA_VERSION,
    }
    return _sha256_json(payload)


def research_arbitration_assessment_schema_identity() -> str:
    payload = {
        "schema": "p43_research_arbitration_assessment",
        "version": RESEARCH_ARBITRATION_ASSESSMENT_SCHEMA_VERSION,
        "fields": tuple(ResearchArbitrationAssessment.__dataclass_fields__),
        "scored_candidate_schema_identity": scored_research_candidate_schema_identity(),
        "arbitration_engine_version": ARBITRATION_ENGINE_VERSION,
        "arbitration_schema_version": ARBITRATION_SCHEMA_VERSION,
    }
    return _sha256_json(payload)


def _direction(value: str) -> SignalDirection:
    return {
        "BULLISH": SignalDirection.LONG_BIAS,
        "BEARISH": SignalDirection.SHORT_BIAS,
        "NEUTRAL": SignalDirection.NEUTRAL,
        "BIDIRECTIONAL": SignalDirection.BIDIRECTIONAL,
    }.get(value, SignalDirection.UNKNOWN)


def _factor_summary(item: Any) -> dict[str, Any]:
    return {
        "factor_id": getattr(item, "factor_id", ""),
        "factor_group": getattr(getattr(item, "factor_group", None), "name", "UNKNOWN"),
        "source_module": getattr(item, "source_module", ""),
        "raw_value": getattr(item, "raw_value", None),
        "normalized_value": getattr(item, "normalized_value", None),
        "weight": getattr(item, "weight", 0.0),
        "availability": getattr(getattr(item, "availability", None), "name", "UNKNOWN"),
        "health": getattr(getattr(item, "health", None), "name", "UNKNOWN"),
        "contribution": getattr(item, "contribution", 0.0),
        "reason_codes": tuple(getattr(item, "reason_codes", ())),
    }


def _assessment_summary(item: ResearchArbitrationAssessment | None) -> dict[str, Any] | None:
    if item is None:
        return None
    return {
        "assessment_id": item.assessment_id,
        "assessment_fingerprint": item.assessment_fingerprint,
        "strategy_evaluation_set_id": item.strategy_evaluation_set_id,
        "scored_candidate_ids": [candidate.scored_candidate_id for candidate in item.scored_candidates],
        "candidate_ids": [candidate.candidate_id for candidate in item.scored_candidates],
        "comparison_ids": [comparison.comparison_id for comparison in item.candidate_comparisons],
        "conflict_ids": [conflict.conflict_id for conflict in item.conflicts],
        "tie_ids": [tie.comparison_id for tie in item.ties],
        "arbitration_state": item.arbitration_state,
        "selected_research_candidate_id": item.selected_research_candidate_id,
        "financial_authorization": "NONE",
    }


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
